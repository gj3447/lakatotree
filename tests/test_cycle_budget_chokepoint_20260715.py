"""사이클 예산의 *진짜 초크포인트* 강제 — 3-verb 우회 봉쇄 (적대검증 2026-07-15 REJECT 대응).

첫 구현(2026-07-15)은 run_cycle 만 거부했다. 적대검증이 그 자리를 정확히 짚었다:

    "THE BUDGET IS BYPASSABLE — 소진된 에이전트가 3-verb 경로(add_node + register_prediction +
     submit_result)로 갈아타면 계속 채점된다. 따라서 그 정지는 agent-elective 이며, 주장하던
     S5 '에이전트 자기판단과 독립된 정지'의 정확한 반대다."

옳은 지적이다. 채점은 결국 JudgementService.submit_test_result(REST POST …/test_result · MCP
submit_result · run_cycle 내부호출) 로 들어오고, 판결 민팅은 set_verdict 로도 된다 — 그 두 곳이
게이트 밖이면 run_cycle 거부는 문(door) 옆의 장식이다. 이 파일이 그 문을 못 박는다.

양방향 + 정직한 경계:
  발화   — 소진 트리는 submit_test_result / set_verdict *어느 verb 로도* 채점 못 함(429, 쓰기 0).
  무영향 — 잔여가 있거나 미선언(기본)이면 거동 불변(채점 정상, 응답 shape 불변).
  경계   — add_node/register_prediction 은 세지도 막지도 않는다(예산 = *판결*의 상한, write 의
           상한이 아님). 이 한계도 테스트로 박아 둔다 — 문서만의 주장으로 남기지 않는다.
# KG: span_lakatotree_engine / G3_one_verb_honest_cycle
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from server.contexts.tree import cycle_budget as cb
from server.contexts.tree.judgement import create_judgement_router
from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import PredictionIn, VerdictIn
from server.contexts.tree.schemas import TestResultIn as _TestResultIn  # noqa: N814 (pytest 수집 회피)


# 미채점 노드의 사전등록 읽기(submit_test_result 초입) — 게이트가 없으면 여기로 흘러 채점된다.
_PRED_ROW = dict(m='p95', d='lower', b=0.5, nb=0.05, novel=None, vsrc=None, nmet=None,
                 ndir=None, nthr=None, psha=None, closes=None, n_opened=0)
# set_verdict 의 상태 읽기(행정 분기) — DRAFT 노드에 'proof' 를 찍는 정상 시나리오.
_STATE_ROW = dict(verdict=None, verdict_source=None, node_state=None, pred_registered_at=None,
                  judged_at=None, metric_value=None, prev_receipt_sha=None)


class _World:
    """fake 세계 — 예산 파생조회(트리 메타 + 채점노드 count)와 판결 write 를 기록만 한다.

    budget=None → cycle_budget 미선언(기존 트리 전부). scored → *저장소*에 이미 있는 채점노드 수.
    writes 는 판결이 실제로 민팅됐는지의 증거: 거부라면 반드시 비어 있어야 한다.
    """

    def __init__(self, budget=None, scored=0):
        self.budget, self.scored = budget, scored
        self.queries: list[str] = []
        self.writes: list = []

    def kg(self, q, **p):
        self.queries.append(q)
        if 'cycle_budget' in q:
            return [{'cycle_budget': self.budget, 'used': self.scored}]
        if 'RETURN e.pred_metric' in q:
            return [dict(_PRED_ROW)]
        if 'RETURN e.verdict AS verdict, e.verdict_source' in q:
            return [dict(_STATE_ROW)]
        if 'MERGE (rec:VerdictReceipt' in q:      # set_verdict 의 행정 판결 write
            self.writes.append(q)
            return [{'tag': p.get('tag')}]
        return []

    def kg_tx(self, ops):                          # submit_test_result 의 판결 write(원자 tx)
        ops = list(ops)
        self.writes.append(ops)
        return [[{'claimed': 'v'}]] + [[] for _ in ops[1:]]


def _svc(w: _World) -> JudgementService:
    return JudgementService(kg=w.kg, kg_tx=w.kg_tx, hist=lambda *a, **k: None,
                            foundation=lambda *a, **k: None,
                            reproducible_for_node=lambda *a, **k: None)


def _result() -> _TestResultIn:
    return _TestResultIn(metric_value=0.4, script='judge.py')


# ── 발화: 소진 트리는 *어느 채점 verb 로도* 못 채점한다 ──────────────────────────────────

def test_submit_test_result_refuses_when_budget_exhausted_and_writes_nothing():
    """실 초크포인트 강제 — 소진 트리의 submit 은 429 + 쓰기 0.

    run_cycle 거부와 달리 여긴 REST/MCP 가 직접 때리는 표면이다(POST …/node/{tag}/test_result,
    mcp submit_result). 게이트 이전 코드에선 이 호출이 그대로 판결을 민팅했다.
    """
    w = _World(budget=3, scored=3)
    with pytest.raises(HTTPException) as e:
        _svc(w).submit_test_result('T', 'n1', _result())
    assert e.value.status_code == 429, f'소진 트리 submit 이 429 로 안 막힘: {e.value.status_code}'
    assert cb.EXHAUSTED_SIGNATURE in str(e.value.detail)
    assert w.writes == [], f'거부인데 판결 write 발생: {w.writes}'
    assert not any('RETURN e.pred_metric' in q for q in w.queries), \
        '거부가 사전등록 읽기 *뒤*에 났다 — 게이트는 판결 파이프라인 진입 전이어야'


def test_set_verdict_refuses_when_budget_exhausted_and_writes_nothing():
    """set_verdict 도 verdict + :VerdictReceipt 를 민팅한다(미채점 draft 면 새 소모 1) — 같은 게이트."""
    w = _World(budget=2, scored=2)
    with pytest.raises(HTTPException) as e:
        _svc(w).set_verdict('T', 'n1', VerdictIn(verdict='proof'))
    assert e.value.status_code == 429
    assert w.writes == [], f'거부인데 행정 판결 write 발생: {w.writes}'


def test_three_verb_path_cannot_outrun_the_budget():
    """★적대검증이 짚은 우회 그 자체의 회귀가드.

    공격: run_cycle 이 budget_exhausted 를 뱉자 에이전트가 3-verb 경로로 갈아탄다.
    구조 verb(register_prediction)는 여전히 통과한다 — 그건 예산 밖이라고 *정직하게* 선언한 범위다.
    그러나 마지막 한 칸(submit_result = 채점)에서 막히므로 판결은 결코 안 나온다: 우회 통로가 판결에
    닿지 못하면 그 경로로 점수를 살 수 없다.
    """
    w = _World(budget=1, scored=1)
    svc = _svc(w)

    svc.register_prediction('T', 'n2', PredictionIn(     # 구조 write: 예산 밖(선언된 범위)
        metric_name='p95', direction='lower', baseline_value=0.5, novel_prediction='x'))

    with pytest.raises(HTTPException) as e:              # 채점: 막힌다 → 우회 실패
        svc.submit_test_result('T', 'n2', _result())
    assert e.value.status_code == 429
    assert not any(isinstance(x, list) for x in w.writes), \
        '3-verb 경로가 판결 write 까지 관통 — 예산 우회 가능(정지가 agent-elective)'


def test_rest_surface_returns_429_not_a_verdict():
    """프로덕션 진입점 reachability — 서비스 내부가 아니라 *실 FastAPI 라우트*가 429 를 돌려준다.
    (적대검증이 지목한 표면: POST /api/tree/{name}/node/{tag}/test_result)"""
    w = _World(budget=1, scored=1)
    app = FastAPI()
    app.include_router(create_judgement_router(lambda: _svc(w)))
    r = TestClient(app, raise_server_exceptions=False).post(
        '/api/tree/T/node/n1/test_result', json={'metric_value': 0.4, 'script': 'judge.py'})
    assert r.status_code == 429, f'REST 표면이 안 막힘: {r.status_code} {r.text[:120]}'
    assert 'verdict' not in r.json(), '거부가 판결처럼 보이면 안 됨(가짜 green)'
    assert w.writes == []


def test_refusal_is_derived_from_storage_not_instance_state():
    """내구(S5): 새 인스턴스(프로세스 재시작 재현)도 같은 거부 — 인메모리 카운터면 여기서 부활한다."""
    for _ in range(2):
        w = _World(budget=2, scored=2)
        with pytest.raises(HTTPException) as e:
            _svc(w).submit_test_result('T', 'n1', _result())
        assert e.value.status_code == 429
    assert any('cycle_budget' in q for q in w.queries), \
        '예산을 저장소에 안 물어봄 — 파생이 아니라 메모리 상태'


# ── 무영향: 잔여가 있거나 미선언이면 거동 불변 ─────────────────────────────────────────

@pytest.mark.parametrize('budget,scored', [(5, 2), (None, 99)])
def test_scoring_proceeds_when_budget_remains_or_unset(budget, scored):
    """게이트는 blanket block 이 아니다 — 잔여가 있거나 미선언(기본)이면 채점이 정상 성립한다.
    (미선언 트리는 채점노드가 99 여도 무제한: 기존 트리 전부에 대해 비파괴)"""
    w = _World(budget=budget, scored=scored)
    out = _svc(w).submit_test_result('T', 'n1', _result())
    assert out['ok'] is True and w.writes, '잔여/미선언인데 채점이 안 됨(거동 파괴)'


def test_kg_read_failure_fails_safe_to_unlimited_at_the_chokepoint():
    """★정직한 한계를 실행가능하게 박제(soft bypass): *예산 조회만* 실패하면 소진 트리(1/99)도 채점된다.

    fail-CLOSED 가 아니다 — 그러므로 "에이전트 자기판단과 독립된 정지"는 무조건적 주장이 아니라 KG
    가용성에 *조건부*다. 부분장애 중엔 예산이 조용히 우회된다. 이 테스트는 그 우회를 고발이 아니라
    *계약*으로 못 박는다(CLAUDE.md §4: fake-heavy 경로의 kg 조회는 fail-safe). hard bound 가 필요해지면
    cycle_budget.budget_state 의 except 를 fail-closed 로 뒤집는 게 그 지점이다.
    """
    w = _World(budget=1, scored=99)      # 소진 상태 — 조회만 되면 반드시 429 여야 하는 트리
    real_kg = w.kg

    def flaky(q, **p):
        if 'cycle_budget' in q:
            raise RuntimeError('neo4j 연결 불가(부분 장애)')
        return real_kg(q, **p)

    svc = JudgementService(kg=flaky, kg_tx=w.kg_tx, hist=lambda *a, **k: None,
                           foundation=lambda *a, **k: None,
                           reproducible_for_node=lambda *a, **k: None)
    out = svc.submit_test_result('T', 'n1', _result())
    assert out['ok'] is True and w.writes, \
        'KG 장애 시 채점이 죽으면 안 됨(fail-safe 계약) — 소진 트리가 여기선 그대로 뚫린다'


# ── 경계(정직): 예산은 *판결*의 상한이지 write 의 상한이 아니다 ──────────────────────────

def test_structural_writes_are_neither_charged_nor_refused():
    """선언된 한계를 실행가능하게 박제 — 소진 트리에도 register_prediction 은 통과한다.

    이게 '봉쇄 실패'가 아니라 *선언된 범위*인 이유: 예측등록은 판결을 못 만든다(verdict 0). 그리고
    그 소모를 세지도 않는다 — 세지 않는 걸 막으면 소모/거부 비대칭이 반대편으로 생기고, 무엇보다
    구 술어(current_receipt_sha IS NOT NULL)는 예측 영수증을 소모로 세는 바람에 budget=1 인 run_cycle
    이 방금 등록한 자기 예측 때문에 자기 submit 을 거부하는 자멸을 낳았다.
    """
    w = _World(budget=1, scored=1)
    out = _svc(w).register_prediction('T', 'n3', PredictionIn(
        metric_name='p95', direction='lower', baseline_value=0.5, novel_prediction='x'))
    assert out['ok'] is True, '예측등록까지 막으면 선언한 범위(판결 상한)를 넘는다'


def test_used_predicate_counts_scored_nodes_not_prediction_receipts():
    """소모 집계 술어의 구조 가드 — 세는 것과 막는 것을 같은 정의에 묶는다.

    ★한계 명시: Cypher 는 이 스위트에서 *실행*되지 않는다(라이브 neo4j 없음) → 술어의 DB-side 의미론은
      구조 단언으로만 고정한다(repo 선례: test_design_audit_m5 의 원자 CAS 가드 단언).
    """
    q = cb._STATE_CYPHER
    assert 'current_receipt_sha IS NOT NULL' not in q, \
        '구 술어 잔존 — 예측 영수증을 소모로 세면 run_cycle 이 자기 사이클을 거부한다(자멸)'
    assert "coalesce(r.receipt_kind,'verdict') <> 'prediction'" in q, \
        '판결 영수증만 세는 필터 누락'
    assert 'e.verdict_source IN $forceful' in q, \
        'FORCEFUL source 절 누락 — CANONICAL 승격이 scripted→admin 으로 덮으면 소모가 감소(비단조)'
