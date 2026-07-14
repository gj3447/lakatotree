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

_PROGRESSIVE = ('progressive', 'progressive_conditional', 'progressive_unverified')


@dataclass(frozen=True)
class VerdictDecision:
    verdict: str
    lakatos_status: str
    novel_independent: bool


def apply_verdict_demotes(verdict: str, lakatos_status: str, *, hc_derived: bool | None,
                          require_novel_anchor: bool, novel: bool, cross_metric_novel: bool,
                          novel_server_anchored: bool,
                          reproducible: bool | None = None,
                          reproducibility_ceiling: bool = False,
                          engine_fresh_fire: bool = False) -> VerdictDecision:
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
      ④ jp4 CA fail-closed(JP 캠페인): stale/무능력 판관(engine_fresh_fire)은 FORCEFUL progressive 를
         못 찍는다 → partial('provisional_stale_engine'). *마지막* 인 이유: 내용기반 라벨(①②③)이 더
         행동유도적이고 각자의 회복 통로를 가지므로, provisional 은 '그 외엔 progressive 였다'의 정밀
         표식이어야 freshen 통로(재기동 후 동일값 재제출 승급)가 내용 결함까지 승급시키는 오염이 없다.
    precedence: ①→②→③→④. 상위가 verdict 를 progressive 밖으로 빼면 하위는 발화하지 않는다. ②가 ③보다
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
    if engine_fresh_fire and verdict in _PROGRESSIVE:
        return VerdictDecision('partial', 'provisional_stale_engine', False)
    return VerdictDecision(verdict, lakatos_status, novel_independent)


def engine_freshness_fires(fresh: dict | None) -> bool:
    """jp4 발화 술어(순수) — 판정가능할 때만 문다: stale_code is True(판관 규칙코드가 부팅 후 실변경)
    또는 capable is False(러닝 프로세스에 G6/resolve_measurement 결손). None(미주입/미무장)과
    stale_code None(판정불가: git 부재/sha 미상)은 발화 안 함 — AG4 '부재≠반증'(dead-σ) 원칙."""
    if not fresh:
        return False
    return fresh.get('stale_code') is True or fresh.get('capable') is False


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
                         measurement_grade: str, engine_rule_sha: str | None = None) -> dict:
    """G1 :VerdictReceipt 봉인 필드 조립(godmethod L758-761 거동 불변 추출).

    lakatos.verdicts.RECEIPT_FIELDS 와 *정확히 1:1*(특성화 골든이 키 집합 동일성 고정). verdict_source
    는 scripted 고정(수동판결 어휘는 별도 경로). AG3 착지(2026-07-03): measurement_grade(측정 출처등급 —
    server_regenerated/client_asserted)를 봉인 필드로 추가 → RECEIPT_FIELDS 도 동시 확장(둘 다 안 하면
    골든 RED). grade 가 payload 에 들어가 진짜검증≠위조가 다른 receipt_sha 를 든다.

    jp1 (JP 캠페인): engine_rule_sha(판관 정체성) — None 기본값은 v1 mint(presence-dispatch; 키는 항상
    포함돼 키집합 골든이 자동 동시확장, sha-봉인된 기존 judge 스크립트 무편집 green). *프로덕션* 유일
    호출부(judgement_service submit)는 ENGINE_RULE_SHA 를 명시 전달해야 하며 이는 fix_harness 가드가
    핀한다(기본값 뒤에 숨은 v1-조용히-mint 드리프트 보험).
    """
    return dict(tree=tree, tag=tag, target_id=target_id, verdict=verdict,
                verdict_source='scripted', metric_name=metric_name, metric_value=metric_value,
                novel_confirmed=novel_confirmed, lakatos_status=lakatos_status,
                judged_at=judged_at, judge_script_sha=judge_script_sha, prev_receipt_sha=prev_receipt_sha,
                measurement_grade=measurement_grade, engine_rule_sha=engine_rule_sha)


def resolve_measurement(replay, client_metric, *, attested: bool = False, authored: bool = False):
    """AG3 값소유 + AG5 attested 등급 결정 seam — I/O-free 순수 (측정주권 2026-07-03).

    replay = ProducerReplayVerdict | None. submit 시 *들어온*(incoming) 값을 서버가 재유도한 결과이지
    persisted 노드가 아니다(AG6/V4 ordering 역전 교정 — 신규노드도 seal 전 소유). attested = 유효
    write-cert 가 *트리 선언 allow-list* 대비 서명됐나. authored(jp5 신설) = 유효 자발적 자기서명
    (무-attestor fallback — authorship 증명이지 권위 아님). 반환: (effective_metric, grade, status)

    ★measurement_grade 4단 provenance 사다리(AG5/R-SOV V3 + jp5):
        server_regenerated  (서버가 값 재유도 — 최상, 값소유)
      > attested            (트리 선언 allow-list 신원 서명 — 값은 client 지만 익명 아님·비부인)
      > authored            (자기서명 — 저자성 증명·비부인이나 *권위 아님*; OWNED_GRADES 밖 → G6 불가)
      > client_asserted     (무서명 client float — 최하)

      replay.verified ∧ regenerated 존재 → server_regenerated(regenerated 를 SSOT 로 *SCOPED 치환*).
      그 외(None / mismatch / regen None) → client 값 유지, grade = attested > authored > client_asserted.
                                            status = not_attempted(replay None) | verified | mismatch
                                                   | not_replayable(verdict 있으나 verified None —
                                                     CLI 계약 비호환 등 재실행 불가; 2026-07-13 신설,
                                                     dead-σ: 검증 불가를 mismatch(반증)로 오분류 금지).

    SCOPED 원칙(확정결정): 값소유는 verified∧regenerated 부분집합에 국한(외부/비재현값 파괴 금지).
    ★dead-σ 안전: attested/authored 는 서명이 실제 붙을 때만 — 무서명은 그대로 client_asserted(무회귀).
    jp5 인센티브 역전 봉합: 버리는 키페어 self-sign 이 attested(G6 PASS)를 사던 구멍 — 권위는 트리가
    선언한 allow-list 만 준다(호출부가 bool(attestors)로 상호배타 분기 — 동시 True 도달 불가, permissive).
    """
    if replay is not None and replay.verified and replay.regenerated is not None:
        return replay.regenerated, 'server_regenerated', 'verified'
    if replay is None:
        status = 'not_attempted'
    elif replay.verified is None:
        # 재실행 *시도했으나 실행 불가*(CLI 계약 비호환 등) — 검증 불가 ≠ 반증(dead-σ).
        # 종전엔 falsy 로 'mismatch' 에 합쳐져 fsck MEASUREMENT_REFUTED 오발화(E16/E17 사건, 2026-07-13).
        status = 'not_replayable'
    else:
        status = 'verified' if replay.verified else 'mismatch'
    grade = 'attested' if attested else ('authored' if authored else 'client_asserted')
    return client_metric, grade, status
