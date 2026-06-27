"""FIX-HARNESS #16 (+#17 same root cause): non-atomic "atomic CAS" verdict guard.

finding id: #16 (P1) + #17 (same root cause)
locations:
  - server/contexts/tree/judgement_service.py:555-596 (#16 submit_test_result — the
    "원자 CAS claim" 가드 SET 과 그 뒤 0행→409 검사)
  - server/contexts/tree/judgement_service.py:268-304 (#17 CANONICAL promotion, #H5)
  - server/contexts/tree/evidence_claim_service.py:125-147 (#17 add_critique auto-demote, #H7)

the bug:
  The verdict-claim op is  "MATCH ... WHERE e.verdict_source IS NULL OR
  e.verdict_source <> 'scripted' SET ... RETURN e.tag AS claimed"  run inside one
  managed-write tx (self.kg_tx). The code comment (555-559) calls this the *atomic
  authority* closing TOCTOU. But Neo4j default isolation is READ_COMMITTED: the
  predicate in WHERE is evaluated at MATCH *read* time, and the node write-lock is only
  taken at SET — it is NOT re-evaluated after the lock is acquired. So two concurrent
  submit_test_result on the SAME node both read verdict_source=NULL, both pass WHERE,
  then serialize at SET: the 2nd overwrites the 1st verdict (lost update / double
  scoring). Both ops RETURN a row, so the 0-row→409 guard at 594-596 fires for NEITHER.
  Net: both submissions "succeed", the node is re-scored, and the re-roll protection the
  guard claims to give is absent. The sync endpoint runs on a threadpool thread/session,
  so this races even with a single uvicorn worker.

the exact fix:
  Force the per-node write-lock BEFORE the guard predicate is read, so WHERE is evaluated
  under lock. e.g. prepend an eager lock-acquire:
      MATCH (t)-[:HAS_NODE]->(e {tag:$tag})
      SET e._cas = coalesce(e._cas,0)+0      // take write lock now
      WITH e WHERE (e.verdict_source IS NULL OR e.verdict_source <> 'scripted')
      SET ...
      RETURN e.tag AS claimed
  (or a Neo4j uniqueness/existence constraint on verdict_source, or app-layer per-node
  serialization) — then keep the existing 0-row→409. Post-fix: of two concurrent submits
  exactly ONE persists a scripted verdict (200) and the other gets HTTP 409; the node ends
  with the winner's verdict, never overwritten.

xfail(strict) until fixed: the assertions below encode the CORRECT post-fix behavior
  (exactly one 409 + no overwrite), so they FAIL today (bug present) and will PASS once the
  guard is made truly atomic — strict xfail then trips and forces removing the marker.

harness honesty (rule 6): a faithful reproduction needs REAL concurrent Neo4j
  transactions under READ_COMMITTED — a hermetic fake would have to reimplement Neo4j
  isolation, which would be a tautology. So this is a LAKATOS_IT-gated integration test
  (mirrors tests/integration/conftest.py + tests/integration/test_kg_tx_atomicity.py). It
  SKIPS locally (no Neo4j) — that is expected. hermetic=false, the bug is SPECIFIED here
  and only OBSERVED when run against a real Neo4j (LAKATOS_IT=1 + testcontainers).
"""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException

from server.container import AppContainer
from server.contexts.tree.judgement_service import JudgementService
# alias 로 import — 클래스명이 'Test*' 라 pytest 가 테스트 클래스로 오수집하는 것 방지.
from server.contexts.tree.schemas import PredictionIn
from server.contexts.tree.schemas import TestResultIn as _TestResultIn

pytestmark = pytest.mark.integration

LAKATOS_IT = os.getenv('LAKATOS_IT')


class _DummyMongo:
    def close(self):
        pass


@pytest.fixture(scope='session')
def neo4j_driver():
    """세션 1회 실 Neo4j 컨테이너 + 드라이버 (tests/integration/conftest.py 미러).

    LAKATOS_IT 미설정 시 skip — 로컬/CI 단위 suite 는 docker 없이 그대로(이 파일은 그때 skip).
    testcontainers 부재(clean clone)면 importorskip 으로 collection 안 깨짐."""
    if not LAKATOS_IT:
        pytest.skip('LAKATOS_IT 미설정 — 통합티어 skip (실 Neo4j 동시 tx 없이는 비원자 CAS 재현 불가)')
    neo4j_mod = pytest.importorskip('testcontainers.neo4j')
    from neo4j import GraphDatabase

    with neo4j_mod.Neo4jContainer('neo4j:5') as neo:
        uri = neo.get_connection_url()
        password = getattr(neo, 'password', None) or 'password'
        driver = GraphDatabase.driver(uri, auth=('neo4j', password))
        try:
            driver.verify_connectivity()
            yield driver
        finally:
            driver.close()


def _service(driver):
    """kg/kg_tx 만 실 Neo4j. hist=no-op(PG best-effort, 이 테스트 무관), foundation/reproducible
    는 set_verdict 전용이라 submit_test_result 경로에선 미사용 → stub."""
    c = AppContainer(neo=driver, mongo=_DummyMongo(), pg_kw={})
    return JudgementService(
        kg=c.kg,
        kg_tx=c.kg_tx,
        hist=lambda *a, **k: None,
        foundation=lambda name: None,
        reproducible_for_node=lambda name, tag: None,
    )


def _seed_predicted_node(c_kg_tx):
    """고유 tree + DRAFT 노드 1개를 만들고 lower-is-better 예측을 등록 — submit_test_result 가
    judge() 를 거쳐 *비원자 CAS SET* 까지 도달하도록. tag 는 동시 submit 의 *같은 노드*."""
    tree = f'fh1617-{uuid.uuid4().hex[:8]}'
    tag = 'n1'
    c_kg_tx([
        ("MERGE (t:LakatosTree {name:$tree})", {'tree': tree}),
        ("MATCH (t:LakatosTree {name:$tree}) "
         "MERGE (t)-[:HAS_NODE]->(e:Node {tag:$tag})", {'tree': tree, 'tag': tag}),
    ])
    return tree, tag


def _submit(svc, tree, tag, metric_value, script):
    """submit_test_result 한 번 — (ok_dict, None) 또는 (None, http_status). HTTP 409 = CAS 거절."""
    try:
        out = svc.submit_test_result(
            tree, tag,
            _TestResultIn(metric_value=metric_value, script=script))
        return ('ok', out)
    except HTTPException as e:
        return ('http', e.status_code)


@pytest.mark.xfail(reason="FIX-HARNESS #16: non-atomic READ_COMMITTED 'atomic CAS' guard "
                          "lets two concurrent submit_test_result both pass WHERE and both SET "
                          "(lost-update, neither hits 0-row→409) — RED until "
                          "server/contexts/tree/judgement_service.py:560-596 evaluates the guard "
                          "under a write-lock; strict trips when fixed",
                   strict=True)
def test_concurrent_submit_exactly_one_409(neo4j_driver):
    """#16 핵심: 같은 노드에 *서로 다른* metric 으로 두 submit_test_result 를 동시 발사하면,
    올바른 post-fix 거동은 정확히 하나만 200(scripted 영속)·다른 하나는 HTTP 409.
    현재(비원자 CAS): 둘 다 WHERE(vsrc IS NULL) 통과 → 둘 다 SET → 0행 가드가 *아무도* 안 잡음
    → 409 가 0건 → 아래 단언 실패(=버그 고정)."""
    svc = _service(neo4j_driver)
    tree, tag = _seed_predicted_node(svc.kg_tx)
    svc.register_prediction(tree, tag, PredictionIn(
        metric_name='loss', direction='lower', baseline_value=1.0, noise_band=0.0))

    # 두 스레드를 거의 동시에 — 각자 별도 Neo4j session/tx(엔드포인트 threadpool 디스패치와 동형).
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_a = ex.submit(_submit, svc, tree, tag, 0.5, 'inline-judge-a')
        f_b = ex.submit(_submit, svc, tree, tag, 0.4, 'inline-judge-b')
        results = [f_a.result(), f_b.result()]

    n_409 = sum(1 for kind, val in results if kind == 'http' and val == 409)
    n_ok = sum(1 for kind, _ in results if kind == 'ok')
    # post-fix 정답: 승자 1 + CAS 거절(409) 1. 비원자 버그면 n_409==0(이중채점) → 실패.
    assert (n_ok, n_409) == (1, 1), (
        f'동시 submit 이 원자 CAS 가 아님 — 정확히 하나만 200·하나만 409 여야 하는데 results={results} '
        f'(n_ok={n_ok}, n_409={n_409}); READ_COMMITTED 에서 두 tx 가 WHERE 를 lock 없이 읽어 이중채점)')


@pytest.mark.xfail(reason="FIX-HARNESS #16: lost-update — the loser's SET overwrites the winner's "
                          "scripted verdict because WHERE is not re-checked under the write-lock; "
                          "RED until the guard is evaluated under lock at "
                          "judgement_service.py:560-596; strict trips when fixed",
                   strict=True)
def test_winning_verdict_is_not_overwritten(neo4j_driver):
    """#16 lost-update 고정: 동시 submit 후 노드에 영속된 metric_value 는 *200 을 받은 제출자의 값*
    이어야 한다(패자는 409 로 거절되어 SET 하지 않음). 비원자 버그면 패자의 SET 이 마지막에 커밋되어
    승자 값을 덮어쓸 수 있다 → 영속값 ≠ 승자값."""
    svc = _service(neo4j_driver)
    tree, tag = _seed_predicted_node(svc.kg_tx)
    svc.register_prediction(tree, tag, PredictionIn(
        metric_name='loss', direction='lower', baseline_value=1.0, noise_band=0.0))

    vals = {'inline-judge-a': 0.5, 'inline-judge-b': 0.4}
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_a = ex.submit(_submit, svc, tree, tag, vals['inline-judge-a'], 'inline-judge-a')
        f_b = ex.submit(_submit, svc, tree, tag, vals['inline-judge-b'], 'inline-judge-b')
        out = {'a': f_a.result(), 'b': f_b.result()}

    winners = [val for val, (kind, _) in
               zip([vals['inline-judge-a'], vals['inline-judge-b']], [out['a'], out['b']])
               if kind == 'ok']
    # post-fix: 정확히 한 승자. (#16 가 살아있으면 둘 다 ok 라 이 단언이 먼저 깨짐 = 버그 고정.)
    assert len(winners) == 1, f'정확히 한 제출만 영속돼야 함(원자 CAS) — out={out}'
    winner_value = winners[0]

    rows = svc.kg("MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag}) "
                  "RETURN e.verdict_source AS vsrc, e.metric_value AS mv", tree=tree, tag=tag)
    assert rows and rows[0]['vsrc'] == 'scripted'
    assert rows[0]['mv'] == winner_value, (
        f"패자의 SET 이 승자 판결을 덮어씀(lost update) — 영속 metric_value={rows[0]['mv']} "
        f'≠ 승자값 {winner_value}')
