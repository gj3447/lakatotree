"""설계감사 H1 frontier 닫기 — hard_core 보존을 self-report bool 이 아니라 negative_heuristic 으로 구조 파생.

H1 의 잔여: 메트릭/judge-novel 은 외부측정에 묶이나 'hard_core 보존'은 client bool(lakatos_hardcore).
여기서: 제출이 touched_assumptions(이 노드가 건드린 가정)를 선언하면, 서버가 tree.hard_core 와
negative_heuristic(touched ∩ core)으로 교집합 판정 → 위반이면 lakatos_hardcore=True(거짓 주장)를 무시하고
different_programme 로 강등('음의 휴리스틱을 떠남=다른 프로그램'). bool 로 위반을 못 숨긴다.
(잔여 frontier: touched-set 은 아직 제출자 선언 — git-diff∩Longinus 파생은 후속.)
"""
from __future__ import annotations

from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import TestResultIn as Result   # pytest Test* 수집 경고 회피


def _svc(captured: list, hard_core: str):
    def kg(query, **p):
        if 'pred_metric AS m' in query:                # submit 사전등록 read (novel target=다른 metric → judge progressive)
            return [{'m': 'seam', 'd': 'lower', 'b': 10.0, 'nb': 0.0, 'scale': 'ratio', 'novel': 'n',
                     'vsrc': None, 'nmet': 'novelaxis', 'ndir': 'higher', 'nthr': 1.0, 'psha': None,
                     'closes': None, 'n_opened': 0, 'hard_core': hard_core}]
        return []                                      # eigentrust 등 = internal
    def kg_tx(ops):
        captured.append(ops)
        return [[{'claimed': 'n'}] for _ in ops]       # 원자 CAS claim 성공
    return JudgementService(kg=kg, kg_tx=kg_tx, hist=lambda *a, **k: None,
                            foundation=lambda n: None, reproducible_for_node=lambda n, t: None)


def _verdict(captured: list) -> str:
    """캡처된 첫 op(판결 SET)의 verdict 파라미터(cypher $v)."""
    return captured[0][0][1]['v']


_QUAL = dict(lakatos_anomaly=True, lakatos_consequence=True, lakatos_excess=True,
             lakatos_hardcore=True)   # 질적 bool 전부 '보존' 주장(self-report)


def test_hard_core_violation_overrides_self_report_to_different_programme():
    """lakatos_hardcore=True(거짓 보존 주장)여도 touched 가 hard core 를 건드리면 different_programme."""
    cap: list = []
    _svc(cap, "core_a, core_b").submit_test_result('T', 'n', Result(
        metric_value=1.0, script='inline', novel_measured=1.0, **_QUAL,
        touched_assumptions=['core_a']))               # 실제로 hard core 건드림
    assert _verdict(cap) == 'different_programme', "구조적 hard_core 위반이 bool 주장에 가려짐"


def test_belt_touch_stays_progressive():
    """belt(=hard core 밖) 가정만 건드리면 보존 → progressive 유지(과잉강등 회귀가드)."""
    cap: list = []
    _svc(cap, "core_a, core_b").submit_test_result('T', 'n', Result(
        metric_value=1.0, script='inline', novel_measured=1.0, **_QUAL,
        touched_assumptions=['belt_x']))               # hard core 밖
    assert _verdict(cap) == 'progressive'


def test_no_touched_set_falls_back_to_legacy():
    """touched 미선언이면 구조 파생 안 하고 레거시(자기보고) 폴백 — 기존 거동 불변."""
    cap: list = []
    _svc(cap, "core_a, core_b").submit_test_result('T', 'n', Result(
        metric_value=1.0, script='inline', novel_measured=1.0, **_QUAL))
    assert _verdict(cap) == 'progressive'
