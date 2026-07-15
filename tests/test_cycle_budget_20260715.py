"""GAP-1 (PROM16 S1/S5) — 트리별 사이클 예산의 루프-경계 강제.

run_cycle 은 결정론적 1-pass 고, 다회 루프는 *외부*(agent/스크립트)가 돈다 — 즉 종전엔 "몇 번까지"
라는 상한이 엔진 어디에도 없었다(PROM16 '무한 루프 금지' + '에이전트 자기판단과 독립된 정지' 결손).
예산은 트리 메타(cycle_budget)에 선언하고, 소모량은 **저장된 채점노드를 세어 파생**한다.

  내구(durable) 가 요점: 인메모리 카운터면 서버 재시작·다중 워커·다중 프로세스마다 0 으로 리셋돼
  상한이 허구가 된다. 저장소 count 파생이면 누가 언제 재시작하든 같은 답(fresh run == resume).

가드 방향 양쪽:
  발화   — 예산 소진 시 타입 거부(status='budget_exhausted', remaining_budget=0) + **쓰기 0**
  무영향 — 미선언(기본)이면 응답 shape 까지 종전과 동일(비파괴), 잔여분이 있으면 정상 실행
# KG: span_lakatotree_engine / G3_one_verb_honest_cycle
"""
from __future__ import annotations

import pytest

from server.contexts.tree.programme_service import ProgrammeService
from server.contexts.tree.schemas import CritiqueIn, CycleIn, NodeIn, PredictionIn
from server.contexts.tree.schemas import TestResultIn as Result


class _Cell:
    """fake 세계 — 예산 조회(트리 메타 + 채점노드 count)와 하위 verb 를 실제 서명대로 재현.

    budget=None 이면 트리에 cycle_budget 이 *미선언*(기존 트리 전부)인 상태를 재현한다.
    kg_fails=True 는 KG 부분장애(조회 불가) 재현 — fail-safe(예산 미상 = 무제한) 박제용.
    """

    def __init__(self, budget=None, scored=0, kg_fails=False):
        self.budget, self.scored, self.kg_fails = budget, scored, kg_fails
        self.nodes: dict[str, dict] = {}
        self.pipeline: list[str] = []

    def kg(self, query, **p):
        if self.kg_fails:
            raise RuntimeError('neo4j 연결 불가(부분 장애 시뮬레이션)')
        if 'cycle_budget' in query:                     # 예산 상태 파생 조회
            return [{'cycle_budget': self.budget, 'used': self.scored}]
        if 'HAS_NODE' in query and p.get('tag') is not None:
            return [{'tag': p['tag']}] if p['tag'] in self.nodes else []
        return []

    def add_node(self, name, node: NodeIn):
        self.pipeline.append('node')
        self.nodes.setdefault(node.tag, {})
        return {'ok': True, 'tag': node.tag}

    def register_prediction(self, name, tag, p: PredictionIn):
        self.pipeline.append('predict')
        return {'ok': True}

    def submit_test_result(self, name, tag, r: Result):
        self.pipeline.append('submit')
        self.nodes[tag]['verdict_source'] = 'scripted'
        return {'verdict': 'progressive', 'novel': None, 'delta': -0.9}

    def add_critique(self, name, tag, c: CritiqueIn):
        self.pipeline.append('critique')
        return {'ok': True}


def _svc(cell: _Cell) -> ProgrammeService:
    return ProgrammeService(
        kg=cell.kg, hist=lambda *a, **k: None, pg=lambda: None,
        tree_data=lambda n: {'nodes': [], 'frontier': []}, compute_metrics=lambda td: {},
        add_node=cell.add_node, register_prediction=cell.register_prediction,
        submit_test_result=cell.submit_test_result, add_critique=cell.add_critique,
        standing=lambda n, t: {'stands': True}, insert_artifact=lambda a: None)


def _cycle(**kw) -> CycleIn:
    return CycleIn(**{'tag': 'n1', 'metric_name': 'seam', 'baseline': 10.0,
                      'direction': 'lower', 'measured': 1.0, 'script': 'inline', **kw})


# ── 발화: 예산 소진 = 타입 거부 + 쓰기 0 ────────────────────────────────────────────────

def test_exhausted_budget_returns_typed_refusal_and_writes_nothing():
    """예산 3, 이미 채점 3 → 실행 대신 타입 거부. 노드 0(첫 write 전에 멈춤)."""
    cell = _Cell(budget=3, scored=3)
    out = _svc(cell).run_cycle('T', _cycle())
    assert out['status'] == 'budget_exhausted'
    assert out['remaining_budget'] == 0
    assert cell.pipeline == [], f'거부인데 하위 verb 실행됨: {cell.pipeline} (쓰기 전 거부 실패)'
    assert cell.nodes == {}, '거부인데 노드가 생성됨 — "BEFORE any write" 위반'
    assert 'verdict' not in out, '거부가 판결처럼 보이면 안 됨(가짜 green)'


def test_overshot_budget_still_refuses_and_clamps_remaining_to_zero():
    """소모(4) > 예산(3) — TOCTOU 로 1 넘긴 상태(알려진 soft 한계)에서도 거부는 성립하고
    remaining 은 음수로 새지 않는다(0 clamp)."""
    cell = _Cell(budget=3, scored=4)
    out = _svc(cell).run_cycle('T', _cycle())
    assert out['status'] == 'budget_exhausted' and out['remaining_budget'] == 0


def test_budget_is_derived_from_storage_not_memory_counter():
    """내구성 박제: 같은 서비스 인스턴스를 몇 번 부르든 답은 *저장소 count* 로만 갈린다.

    인메모리 카운터 구현이면 첫 호출 후 내부 상태가 증가해 두 번째 호출이 달라지지만, 저장소
    파생이면 저장소가 안 변한 한 몇 번을 불러도 같은 거부다(재시작/다중 프로세스 = 같은 답).
    """
    cell = _Cell(budget=1, scored=1)
    svc = _svc(cell)
    assert svc.run_cycle('T', _cycle())['status'] == 'budget_exhausted'
    assert svc.run_cycle('T', _cycle())['status'] == 'budget_exhausted'   # 멱등 거부
    fresh = _svc(_Cell(budget=1, scored=1))    # 새 프로세스 재현(카운터 리셋 상황)
    assert fresh.run_cycle('T', _cycle())['status'] == 'budget_exhausted', \
        '새 인스턴스에서 예산이 부활 — 인메모리 카운터(비내구) 구현'


# ── 무영향: 미선언 기본 = 무제한 + 응답 shape 불변 ───────────────────────────────────────

def test_unset_budget_is_unlimited_and_response_shape_unchanged():
    """기본(미선언)은 완전 비파괴 — 실행되고, 예산 키가 응답에 *끼어들지 않는다*."""
    cell = _Cell(budget=None, scored=99)          # 채점 99개여도 미선언이면 무제한
    out = _svc(cell).run_cycle('T', _cycle())
    assert out['verdict'] == 'progressive'
    assert cell.pipeline[:3] == ['node', 'predict', 'submit']
    assert 'remaining_budget' not in out and 'status' not in out, \
        '예산 미선언인데 응답 shape 이 바뀜(하위호환 파괴)'


def test_remaining_budget_exposed_and_decrements_when_set():
    """선언 시엔 잔여를 노출. 이 사이클이 영수증 1 을 착륙시키므로 잔여 = (예산-소모) - 1."""
    cell = _Cell(budget=5, scored=2)
    out = _svc(cell).run_cycle('T', _cycle())
    assert out['verdict'] == 'progressive'        # 잔여 있으면 정상 실행
    assert out['remaining_budget'] == 2           # 5 - 2 = 3 남았고 이번 것 소모 → 2


def test_last_cycle_within_budget_runs_then_reports_zero():
    """경계값: 잔여 1 이면 *실행*되고(거부 아님) 잔여 0 을 보고 → 다음 호출이 거부된다."""
    cell = _Cell(budget=3, scored=2)
    out = _svc(cell).run_cycle('T', _cycle())
    assert out.get('status') != 'budget_exhausted' and out['verdict'] == 'progressive'
    assert out['remaining_budget'] == 0


def test_kg_read_failure_fails_safe_to_unlimited():
    """정직한 한계 박제(soft bypass): 예산 조회 실패 = *무제한*으로 진행한다.

    fail-CLOSED 가 아니다 — 의도적 trade-off 이고 그래서 여기 박아둔다: KG 부분장애 때 예산이
    조용히 우회된다(CLAUDE.md §4 'fake-heavy 경로 kg 조회는 fail-safe' 규율 + KG-less 테스트가
    실 neo4j 를 치면 안 된다는 제약과의 타협). 예산은 hard 안전 게이트가 아니라 soft 루프 상한.
    """
    cell = _Cell(budget=1, scored=99, kg_fails=True)
    out = _svc(cell).run_cycle('T', _cycle())
    assert out['verdict'] == 'progressive', 'KG 장애 시 사이클이 죽으면 안 됨(fail-safe 계약)'
    assert 'remaining_budget' not in out, '예산 미상인데 잔여를 지어내면 안 됨'


def test_dry_run_preview_is_not_charged_but_is_refused_when_exhausted():
    """dry_run 은 쓰기 0 이라 예산을 *소모하지 않지만*, 소진된 트리에선 미리보기도 거부한다
    (루프 드라이버가 이유코드로 즉시 멈추도록 — 못 도는 사이클의 미리보기는 오도)."""
    exhausted = _Cell(budget=2, scored=2)
    out = _svc(exhausted).run_cycle('T', _cycle(dry_run=True))
    assert out['status'] == 'budget_exhausted' and exhausted.pipeline == []

    live = _Cell(budget=2, scored=0)              # 잔여 있으면 미리보기 정상 + 소모 0
    prev = _svc(live).run_cycle('T', _cycle(dry_run=True))
    assert prev['dry_run'] is True and 'verdict_preview' in prev
    assert live.pipeline == [] and live.nodes == {}
