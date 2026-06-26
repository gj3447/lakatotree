"""설계감사 H1 — 질적 verdict(LakatosGate/PnR)가 영수증 없는 client bool 로 progressive 를 떠받친 뒤
scripted COUNTS 영수증을 상속해 CANONICAL floor 를 통과하던 결함.

척추: 메트릭 개선은 실 영수증이나 '하드코어 보존·초과경험내용'은 self-report 다. 독립 영수증(독립 novel
측정 sha 또는 인간 attestation) 없이 질적 self-report 가 progressive 를 유지하면, floor 는 메트릭 scripted
영수증 *단독* 으론 CANONICAL 을 안 연다(reproducible/human 등 별도 영수증 요구).
# KG: span_lakatotree_spine
"""
from __future__ import annotations

from lakatos.verdict.spine import synthesize_promotion
from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import TestResultIn as Result   # 별칭: pytest 가 Test* 클래스로 수집하려는 경고 회피


# ── floor 게이트(spine) — H1 의 핵심 ────────────────────────────────────────────
def test_qualitative_self_report_does_not_reach_canonical_floor():
    """질적 self-report 로 progressive 가 된 노드는 메트릭 scripted COUNTS *단독* 으로 floor 못 연다."""
    decision = synthesize_promotion(
        scripted_verdict='progressive', verdict_source='scripted', stands=True,
        reproducible=None, credibility=None,
        qualitative_self_report=True)            # ← 질적 self-report 표식
    assert decision['ok'] is False
    assert 'no_receipt_for_canonical' in decision['reasons']
    assert decision['gates']['floor']['passed'] is False


def test_floor_unaffected_for_non_qualitative_scripted():
    """회귀가드: 질적 self-report 가 아닌 보통 scripted progressive 는 메트릭 영수증으로 *여전히* 통과."""
    decision = synthesize_promotion(
        scripted_verdict='progressive', verdict_source='scripted', stands=True,
        reproducible=None, credibility=None,
        qualitative_self_report=False)
    assert decision['ok'] is True
    assert decision['gates']['floor']['passed'] is True


def test_qualitative_self_report_passes_with_independent_receipt():
    """질적 self-report 라도 *독립* 영수증(reproducible 실 replay)이 있으면 floor 가 열린다(과잉차단 아님)."""
    decision = synthesize_promotion(
        scripted_verdict='progressive', verdict_source='scripted', stands=True,
        reproducible=True, credibility=None,
        qualitative_self_report=True)
    assert decision['ok'] is True
    assert decision['gates']['floor']['passed'] is True


# ── submit 이 질적 self-report 노드를 표식하는지(service) ─────────────────────────
def _svc(captured: list):
    def kg(query, **p):
        if 'pred_metric AS m' in query:               # submit 의 사전등록 read (novel target 등록됨)
            return [{'m': 'seam', 'd': 'lower', 'b': 10.0, 'nb': 0.0, 'scale': 'ratio',
                     'novel': 'novel claim', 'vsrc': None,
                     'nmet': 'novelaxis', 'ndir': 'higher', 'nthr': 1.0,
                     'psha': None, 'closes': None, 'n_opened': 0}]
        return []                                     # eigentrust 등 = 인터넷관측 없음(internal)
    def kg_tx(ops):
        captured.append(ops)
        return [[{'claimed': 'n'}] for _ in ops]      # 원자 CAS claim 성공(1행)
    return JudgementService(kg=kg, kg_tx=kg_tx, hist=lambda *a, **k: None,
                            foundation=lambda n: None, reproducible_for_node=lambda n, t: None)


# judge-novel(메트릭 참신성)은 독립 측정으로 backed → verdict='progressive'. 그러나 LakatosGate 질적
#   bool(하드코어/초과경험)은 별개 self-report 축 — 이게 H1 의 표적이다.
_NOVEL = dict(novel_measured=1.0, novel_sha='beef')   # judge novel 충족 + 측정sha 독립


def _qsr_param(captured: list) -> bool:
    """캡처된 첫 op(판결 SET)의 qualitative_self_report 파라미터(cypher $qsr)."""
    return bool(captured[0][0][1].get('qsr'))


def test_submit_marks_unbacked_qualitative_self_report():
    """progressive(judge-novel backed)이지만 질적 bool(하드코어/초과경험)은 독립 영수증 없는 self-report
    → qualitative_self_report=True 로 표식(메트릭/judge-novel 만으론 질적 진보주장 미입증)."""
    cap: list = []
    _svc(cap).submit_test_result('T', 'n', Result(
        metric_value=1.0, script='inline', **_NOVEL,        # 개선(10→1) + judge-novel 충족 → progressive
        lakatos_anomaly=True, lakatos_consequence=True,
        lakatos_excess=True, lakatos_hardcore=True))        # 질적 bool 전부 self-report, ce 미corroborated
    assert _qsr_param(cap) is True


def test_submit_independent_corroboration_is_not_self_report(tmp_path):
    """질적 excess 가 *서버앵커* novel 영수증(novel_script 재계산)+ce_novel_corroborated 으로 backed →
    self-report 아님(False). #H10: backing 의 근거는 client novel_sha 문자열이 아니라 서버 재계산 영수증."""
    measure = tmp_path / "novel_measure.py"; measure.write_bytes(b"print('independent excess: 1.0')\n")
    cap: list = []
    _svc(cap).submit_test_result('T', 'n', Result(
        metric_value=1.0, script='inline', **_NOVEL,
        novel_script=str(measure),                          # #H10: 서버앵커 novel 영수증(위조 문자열 아님)
        lakatos_anomaly=True, lakatos_consequence=True,
        lakatos_excess=True, lakatos_hardcore=True,
        ce_novel_corroborated=True))                        # 독립 corroboration 영수증
    assert _qsr_param(cap) is False
