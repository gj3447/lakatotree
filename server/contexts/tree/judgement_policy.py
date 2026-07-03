"""순수 판결 정책 — submit_test_result(judgement_service) godmethod 에서 추출한 I/O-free 결정 로직.

DE1(측정주권 PROM 2026-07-03): 344줄 godmethod 의 *판결 결정 seam* 을 순수 함수로 분리해
AG3(값소유/measurement_grade)·AG4(재현성 분류 partial 천장)·AG5(attested grade)의 착지대를 만든다.
거동 불변 추출 — 각 함수는 원 godmethod 의 해당 절과 1:1(특성화 골든:
tests/fix_harness/test_de1_submit_characterization_20260703.py 가 4-사분면 전수 고정).

여기엔 kg/kg_tx/HTTP 가 없다(순수). raise 는 호출부(godmethod)에 남는다 — I/O 결합 검증(sha 재유도·
write-cert·state transition)은 여전히 서비스가 오케스트레이션한다.
# KG 거울: LakatosTree_MeasurementSovereignty_20260703 / de1_godmethod_split
"""
from __future__ import annotations

from dataclasses import dataclass

_PROGRESSIVE = ('progressive', 'progressive_conditional')


@dataclass(frozen=True)
class VerdictDecision:
    verdict: str
    lakatos_status: str
    novel_independent: bool


def apply_verdict_demotes(verdict: str, lakatos_status: str, *, hc_derived: bool | None,
                          require_novel_anchor: bool, novel: bool, cross_metric_novel: bool,
                          novel_server_anchored: bool) -> VerdictDecision:
    """dialectical_verdict 이후의 *구조적* 강등 체인(godmethod L686-696 의 거동 불변 추출).

      ① #H1-hardcore: hard_core 구조 위반(touched ∩ core ≠ ∅ → hc_derived is False)이면 메트릭/질적
         주장과 무관하게 different_programme 로 강등('음의 휴리스틱을 떠남 = 다른 프로그램', AXIS-CORR).
      ② FF1: require_novel_anchor 트리에서 cross-metric novel 이 서버앵커 없이 progressive 면
         partial(novel_not_server_anchored) — client float 한 줄이 thesis 머리를 사는 구멍 봉합.
    precedence: ①이 verdict 를 progressive 밖으로 빼면 ②는 발화하지 않는다(원본 순서 보존).
    AG4 착지대: 여기에 '재현성 미검증 anchored → partial 천장'(하드 409 아님)을 추가한다.
    """
    novel_independent = bool(novel)
    if hc_derived is False and verdict in _PROGRESSIVE:
        return VerdictDecision('different_programme', 'hard_core_violated_structural', novel_independent)
    if (require_novel_anchor and novel and cross_metric_novel and not novel_server_anchored
            and verdict in _PROGRESSIVE):
        return VerdictDecision('partial', 'novel_not_server_anchored', False)
    return VerdictDecision(verdict, lakatos_status, novel_independent)


def qualitative_flags(*, have_qual: bool, verdict: str, novel_server_anchored: bool,
                      ce_novel_corroborated: bool) -> tuple[bool, bool]:
    """질적 backing 판정(#H1/#H10, godmethod L705-707 거동 불변 추출) → (qual_backed, qual_self_report).

    backed = 서버앵커 독립 novel 측정 영수증(novel_server_anchored) ∧ ce_novel_corroborated.
    self_report = 질적 주장이 있고 progressive 를 떠받치는데 backed 아님 → CANONICAL floor 가 메트릭
    단독으론 안 여는 표식. (client 문자열 한 줄로 backed 처리하던 H1↔H6 잔여를 서버앵커로 봉합.)
    """
    qual_backed = bool(novel_server_anchored and ce_novel_corroborated)
    qual_self_report = bool(have_qual and verdict in _PROGRESSIVE and not qual_backed)
    return qual_backed, qual_self_report


def build_receipt_fields(*, tree: str, tag: str, target_id, verdict: str, metric_name,
                         metric_value: float, novel_confirmed: bool, lakatos_status: str,
                         judged_at: str, judge_script_sha: str, prev_receipt_sha) -> dict:
    """G1 :VerdictReceipt 봉인 필드 조립(godmethod L758-761 거동 불변 추출).

    lakatos.verdicts.RECEIPT_FIELDS 와 *정확히 1:1*(특성화 골든이 키 집합 동일성 고정). verdict_source
    는 scripted 고정(수동판결 어휘는 별도 경로). AG3 착지대: measurement_grade(측정 출처등급)를 여기에
    추가하고 RECEIPT_FIELDS 도 동시 확장한다(둘 다 안 하면 골든 RED).
    """
    return dict(tree=tree, tag=tag, target_id=target_id, verdict=verdict,
                verdict_source='scripted', metric_name=metric_name, metric_value=metric_value,
                novel_confirmed=novel_confirmed, lakatos_status=lakatos_status,
                judged_at=judged_at, judge_script_sha=judge_script_sha, prev_receipt_sha=prev_receipt_sha)
