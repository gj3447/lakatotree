"""통합티어(LAKATOS_IT): producer replay *live e2e* — 실 Neo4j + 실 sandbox 실행으로 위조 metric 적발.

나생문 #1 근본 봉합의 끝단 영수증: 채점 스크립트를 *실제 재실행*(LAKATOS_REPLAY_EXEC)해 client 가 보고한
metric_value 를 검증하고, 그 결과(measurement_externally_anchored)를 CANONICAL 노드에 *persist* 함을 실 그래프로
확인한다. hermetic 단위(tests/fix_harness/test_fix_producer_replay_live.py)는 판정/배선을 포트 주입으로 핀하나,
'실 Neo4j 에 persist 된 anchor 를 readback' 은 여기서만 — 영수증 없는 green 금지(gated, LAKATOS_IT 필요).

정직 측정(재실행==recorded) → anchored True · 위조(재실행≠recorded) → anchored False.
# KG: span_lakatotree_engine / span_lakatotree_rebuild
"""
from uuid import uuid4

import pytest

from lakatos.node_state import NodeState
from server.container import AppContainer
from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import NodeIn, VerdictIn
from server.contexts.tree.writer import TreeKgWriter

pytestmark = pytest.mark.integration


class _DummyMongo:
    def close(self):
        pass


class _BorrowedDriver:
    """Do not let a per-test container close the session-scoped Neo4j fixture."""

    def __init__(self, driver):
        self._driver = driver

    def session(self, *args, **kwargs):
        return self._driver.session(*args, **kwargs)

    def close(self):
        pass


def _seed_candidate(kg, *, tree, tag, judge_script, result_path, recorded_metric):
    """CANONICAL_CANDIDATE 후보 노드 직접 셋업 — progressive/scripted, 실 scorer 경로 + recorded metric.
    (submit→judge 전 과정 대신 후보 상태를 그래프에 직접 둬 set_verdict 승격경로만 e2e 한다.)"""
    kg('''MERGE (t:LakatosTree {name:$tree})
          MERGE (e:LakatosNode:PrismExperiment {name:$node_name})
          SET e.verdict='progressive', e.verdict_source='scripted', e.node_state=$st,
              e.tag=$tag,
              e.judge_script=$js, e.metric_value=$mv, e.result_path=$rp, e.pred_noise_band=0.0,
              e.qualitative_self_report=false, e.novel_confirmed=true, e.author='',
              e.measurement_externally_anchored=null
          MERGE (t)-[:HAS_NODE]->(e)''',
       tree=tree, node_name=f"{tree}/{tag}", tag=tag,
       st=NodeState.CANONICAL_CANDIDATE.value, js=judge_script,
       rp=result_path, mv=recorded_metric)


def _service(container, monkeypatch):
    """실 app._producer_replay_for_node 를 컨테이너 kg 로 — 게이트 ON. 실 _replay_run(subprocess) 사용."""
    import server.app as app
    monkeypatch.setenv('LAKATOS_REPLAY_EXEC', '1')
    monkeypatch.setattr(app, 'kg', container.kg)   # app 함수가 컨테이너 그래프를 읽게
    return JudgementService(kg=container.kg, kg_tx=container.kg_tx,
                            hist=lambda *args, **kwargs: None,
                            foundation=lambda _n: None,
                            reproducible_for_node=lambda _n, _t: None,
                            producer_replay_for_node=app._producer_replay_for_node)


def _anchored(kg, tag, tree):
    rows = kg(
        '''MATCH (:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
           RETURN e.measurement_externally_anchored AS mea''',
        tree=tree,
        tag=tag,
    )
    assert len(rows) == 1, f"tree-scoped anchor readback must resolve exactly one node, got {len(rows)}"
    return rows[0]['mea']


def _cleanup(container, tree):
    """Remove every graph/outbox artifact owned by this live replay case."""
    try:
        container.kg(
            "MATCH (r:VerdictReceipt {tree:$tree}) DETACH DELETE r",
            tree=tree,
        )
        container.kg(
            "MATCH (o:OutboxEntry {tree:$tree}) DETACH DELETE o",
            tree=tree,
        )
        container.kg(
            "MATCH (t:LakatosTree {name:$tree}) "
            "OPTIONAL MATCH (t)-[:HAS_NODE]->(e) DETACH DELETE e, t",
            tree=tree,
        )
        rows = container.kg(
            "OPTIONAL MATCH (o:OutboxEntry {tree:$tree}) "
            "WITH count(o) AS outboxes "
            "OPTIONAL MATCH (r:VerdictReceipt {tree:$tree}) "
            "RETURN outboxes, count(r) AS receipts",
            tree=tree,
        )
        assert rows == [{"outboxes": 0, "receipts": 0}], (
            "producer replay test leaked a ledger artifact"
        )
    finally:
        container.close()


def test_live_producer_replay_persists_true_for_honest_metric(neo4j_driver, tmp_path, monkeypatch):
    """정직: 실 scorer 가 recorded 와 같은 metric 을 재생성 → 재실행 검증 → anchored=True 가 노드에 persist."""
    tree = f"PRODUCER_REPLAY_{uuid4().hex}"
    c = AppContainer(neo=_BorrowedDriver(neo4j_driver), mongo=_DummyMongo(), pg_kw={})
    scorer = tmp_path / "scorer.py"
    result = tmp_path / "result.json"
    scorer.write_text("import sys\nprint('metric=0.50')\n")   # args 무시, recorded 와 동일
    result.write_text("{}\n")
    _seed_candidate(c.kg, tree=tree, tag='honest', judge_script=str(scorer),
                    result_path=str(result), recorded_metric=0.50)
    svc = _service(c, monkeypatch)

    try:
        svc.set_verdict(tree, 'honest', VerdictIn(verdict='CANONICAL'))
        assert _anchored(c.kg, 'honest', tree) is True
        TreeKgWriter(c.kg_tx).upsert_nodes(
            tree, [NodeIn(tag='honest', result_path='forged-after-promotion.json')]
        )
        rows = c.kg(
            "MATCH (:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:'honest'}) "
            "RETURN e.verdict AS verdict, e.verdict_source AS source, "
            "e.result_path AS result_path",
            tree=tree,
        )
        assert rows == [{
            'verdict': 'CANONICAL',
            'source': 'admin',
            'result_path': str(result),
        }]
    finally:
        _cleanup(c, tree)


def test_live_producer_replay_persists_false_for_forged_metric(neo4j_driver, tmp_path, monkeypatch):
    """위조: client 가 recorded=0.99 로 보고했으나 실 scorer 재실행은 0.50 → 불일치 → anchored=False persist.
    이것이 #1 forge 의 런타임 봉합: 서버가 숫자를 신뢰하지 않고 현실(재실행)이 끊는다."""
    tree = f"PRODUCER_REPLAY_{uuid4().hex}"
    c = AppContainer(neo=_BorrowedDriver(neo4j_driver), mongo=_DummyMongo(), pg_kw={})
    scorer = tmp_path / "scorer.py"
    result = tmp_path / "result.json"
    scorer.write_text("import sys\nprint('metric=0.50')\n")   # 실제값 0.50
    result.write_text("{}\n")
    _seed_candidate(c.kg, tree=tree, tag='forged', judge_script=str(scorer),
                    result_path=str(result), recorded_metric=0.99)   # client 위조 0.99
    svc = _service(c, monkeypatch)

    try:
        svc.set_verdict(tree, 'forged', VerdictIn(verdict='CANONICAL'))
        assert _anchored(c.kg, 'forged', tree) is False
    finally:
        _cleanup(c, tree)
