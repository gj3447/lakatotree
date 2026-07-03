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
                          novel_server_anchored: bool,
                          reproducible: bool | None = None,
                          reproducibility_ceiling: bool = False) -> VerdictDecision:
    """dialectical_verdict 이후의 *구조적* 강등 체인(godmethod L686-696 의 거동 불변 추출 + AG4 확장).

      ① #H1-hardcore: hard_core 구조 위반(touched ∩ core ≠ ∅ → hc_derived is False)이면 메트릭/질적
         주장과 무관하게 different_programme 로 강등('음의 휴리스틱을 떠남 = 다른 프로그램', AXIS-CORR).
      ② AG4/R-SOV V2 재현성 천장(측정주권 2026-07-03): anchored tier 게이트(reproducibility_ceiling)가
         무장되고 재현성이 *구조적으로 반증*(reproducible is False: lineage dangling/비-source root)이면
         progressive→partial 천장(reproducibility_refuted). 하드 409 아님(값 보존), CANONICAL 은 못 열되.
         ★불가 None(result_path 없음/sha 미검증=증명불가)은 **천장 안 함**(부재≠반증, dead-σ) — 라이브
         무회귀의 뿌리. reproducible is True 도 물론 통과.
      ③ FF1: require_novel_anchor 트리에서 cross-metric novel 이 서버앵커 없이 progressive 면
         partial(novel_not_server_anchored) — client float 한 줄이 thesis 머리를 사는 구멍 봉합.
    precedence: ①→②→③. 상위가 verdict 를 progressive 밖으로 빼면 하위는 발화하지 않는다. ②가 ③보다
    우선(재현성 구조반증이 novel 앵커 갭보다 근본적) — 둘 다 partial 이나 label 이 reproducibility_refuted.
    """
    novel_independent = bool(novel)
    if hc_derived is False and verdict in _PROGRESSIVE:
        return VerdictDecision('different_programme', 'hard_core_violated_structural', novel_independent)
    if reproducibility_ceiling and reproducible is False and verdict in _PROGRESSIVE:
        return VerdictDecision('partial', 'reproducibility_refuted', False)
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
                         judged_at: str, judge_script_sha: str, prev_receipt_sha,
                         measurement_grade: str) -> dict:
    """G1 :VerdictReceipt 봉인 필드 조립(godmethod L758-761 거동 불변 추출).

    lakatos.verdicts.RECEIPT_FIELDS 와 *정확히 1:1*(특성화 골든이 키 집합 동일성 고정). verdict_source
    는 scripted 고정(수동판결 어휘는 별도 경로). AG3 착지(2026-07-03): measurement_grade(측정 출처등급 —
    server_regenerated/client_asserted)를 봉인 필드로 추가 → RECEIPT_FIELDS 도 동시 확장(둘 다 안 하면
    골든 RED). grade 가 payload 에 들어가 진짜검증≠위조가 다른 receipt_sha 를 든다.
    """
    return dict(tree=tree, tag=tag, target_id=target_id, verdict=verdict,
                verdict_source='scripted', metric_name=metric_name, metric_value=metric_value,
                novel_confirmed=novel_confirmed, lakatos_status=lakatos_status,
                judged_at=judged_at, judge_script_sha=judge_script_sha, prev_receipt_sha=prev_receipt_sha,
                measurement_grade=measurement_grade)


def resolve_measurement(replay, client_metric):
    """AG3/R-SOV V1 값소유(value-ownership) 결정 seam — I/O-free 순수 (측정주권 2026-07-03).

    replay = ProducerReplayVerdict | None. submit 시 *들어온*(incoming) 값을 서버가 재유도한 결과이지
    persisted 노드가 아니다(AG6/V4 ordering 역전 교정 — 신규노드도 seal 전 소유). 반환:
        (effective_metric, measurement_grade, replay_status)

      replay is None            → 서버 미실행(exec OFF/비재현 스크립트): client 값 유지,
                                    grade=client_asserted, status=not_attempted (dead-σ: 부재≠반증).
      replay.verified is True    → 서버가 값을 재유도·일치: regenerated 를 SSOT 로 *치환*(값소유),
        ∧ regenerated 존재         grade=server_regenerated, status=verified.
      그 외(mismatch / regen None)→ SCOPED 치환만 — client 값 유지(반증값·외부 null 값 소유 안 함),
                                    grade=client_asserted, status=verified|mismatch(replay.verified 반영).

    SCOPED 원칙(확정결정): 값소유는 verified∧regenerated 부분집합에 국한 — '항상치환'은 외부/비재현값
    (regenerated=None)을 파괴한다. 치환값은 client 와 tol(1e-9) 내이므로 verdict 는 불변, 바뀌는 건 *출처*
    (서버가 자기 bits 를 소유)다.
    """
    if replay is None:
        return client_metric, 'client_asserted', 'not_attempted'
    status = 'verified' if replay.verified else 'mismatch'
    if replay.verified and replay.regenerated is not None:
        return replay.regenerated, 'server_regenerated', status
    return client_metric, 'client_asserted', status
