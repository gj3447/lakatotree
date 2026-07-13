"""progressive_unverified — 판정엔진 감사(_pidna_receipts/lakatotree_judge_engine_audit_2026-07-12.md)
finding A(유일 CRITICAL) 수정 가드. metric progressive + ZERO Lakatos 정성검증(dogfood default: lakatos_*
필드 부재 + PnR 부재)이 full 'progressive' 로 발행되어 fertility/eureka/CANONICAL-floor/series 가
미검증을 진보로 취급하던 버그 → spine 이 DISTINCT verdict 'progressive_unverified' 를 발행.

설계 = 10-agent exhaustive map + 3-architect design panel + 6 adversarial verification 합의:
  FORK1 B-neutral(series NEUTRAL, consec 루프 불변) / FORK2 set-exclusion-only(force_of 무변) /
  FORK3 E2-orthogonal(eureka 발견 축 = novel⊥belt, pu→progressive 매핑으로 BF 6.0 복원, abandon-stack BF 1.0).
이 verdict 는 이전에 존재하지 않았으므로 emit(spine.reconcile_verdict) revert 시 전 가드 RED.
# KG: span_lakatotree_spine / audit-finding-A-progressive-unverified
"""
from lakatos.verdict.pnr import Response, appraise_response
from lakatos.verdict.spine import dialectical_verdict, reconcile_verdict
from lakatos.verdicts import (CONFIRMED_NOVEL_PROGRESS, ENGINE_VERDICTS, NONPROGRESSIVE_VERDICTS,
                              PROGRESS_VERDICTS, SCRIPTED_VERDICTS, VERDICT_REGISTRY,
                              is_engine_verdict, is_progress_verdict, is_self_report_blocked_verdict)
from lakatos.quant.bayes import BF_BASE, bayes_factor
from lakatos.eureka import eureka_verdict
from lakatos.verdict.promote import PROMOTABLE, promotion_gate

PU = 'progressive_unverified'


# ── emit: the SOLE producer (spine.reconcile_verdict) ────────────────────────────────────────
def test_metric_progressive_without_lakatos_emits_unverified():
    r = reconcile_verdict('progressive', None)
    assert r['verdict'] == PU
    assert r['lakatos'] == 'unverified' and r['status'] == 'qualitative_unverified'
    assert 'lakatos_evidence_missing' in r['reasons']


def test_metric_nonprogressive_is_never_unverified():
    # 메트릭 비진보는 unverified 대상 아님 — pu 는 metric progressive 에서만 발생.
    assert reconcile_verdict('partial', None)['verdict'] == 'partial'
    assert reconcile_verdict('rejected', None)['verdict'] == 'rejected'


def test_zero_scrutiny_dialectic_emits_unverified():
    # LakatosGate 도 PnR 도 없는 완전 무검증 → pu.
    assert dialectical_verdict('progressive')['verdict'] == PU


# ── PnR rescue: a present appraisal IS qualitative scrutiny → lifts pu ────────────────────────
def test_pnr_progressive_lifts_unverified_to_full_progressive():
    prog = appraise_response(Response.LEMMA_INCORPORATION, excess_content=True,
                             novel_corroborated=True, in_heuristic_spirit=True)
    assert prog.verdict == 'progressive'
    # PnR progressive = Lakatos dialectical 확증 → unverified 를 full progressive 로 승격(무검증 아님).
    assert dialectical_verdict('progressive', pnr_appraisal=prog)['verdict'] == 'progressive'


def test_pnr_conditional_lifts_unverified_to_conditional():
    cond = appraise_response(Response.LEMMA_INCORPORATION, excess_content=True,
                             novel_corroborated=False, in_heuristic_spirit=True)
    assert cond.verdict == 'conditional'
    assert dialectical_verdict('progressive', pnr_appraisal=cond)['verdict'] == 'progressive_conditional'


def test_pnr_degenerating_overrides_unverified():
    degen = appraise_response(Response.LEMMA_INCORPORATION, excess_content=False)
    assert degen.verdict == 'degenerating'
    assert dialectical_verdict('progressive', pnr_appraisal=degen)['verdict'] == 'degenerating'


# ── vocabulary memberships (the keystone) ────────────────────────────────────────────────────
def test_registered_and_engine_and_self_report_blocked():
    assert PU in VERDICT_REGISTRY, 'unregistered → validation.py 가 write 를 422'
    assert PU in ENGINE_VERDICTS and is_engine_verdict(PU)
    assert is_self_report_blocked_verdict(PU), '엔진 어휘는 client self-report 금지'


def test_out_of_every_progress_and_scripted_set():
    # OUT of SCRIPTED(no CANONICAL floor judge_receipt) / PROGRESS(canonical_improved_recent raw 체크) /
    # NONPROGRESSIVE(미검증 ≠ 퇴행) / CONFIRMED_NOVEL_PROGRESS(미검증 ≠ prediction_hit).
    assert PU not in SCRIPTED_VERDICTS
    assert PU not in PROGRESS_VERDICTS and not is_progress_verdict(PU)
    assert PU not in NONPROGRESSIVE_VERDICTS
    assert PU not in CONFIRMED_NOVEL_PROGRESS
    # 진보/비진보 축은 여전히 disjoint (registry invariant 불변).
    assert PROGRESS_VERDICTS.isdisjoint(NONPROGRESSIVE_VERDICTS)


# ── bayes: abandon-stack neutrality (BF 1.0, no credence, no abandon-immunity) ─────────────────
def test_bayes_factor_is_neutral_for_unverified():
    assert BF_BASE[PU] == 1.0, 'THR-1: 명시 등록(.get default 의존 금지)'
    # base==1.0 short-circuit → 효과크기 무관 BF=1.0 (미검증은 credence 축적 못 함).
    assert bayes_factor(PU, delta=5.0, noise_band=0.1) == 1.0


# ── eureka E2: discovery axis reads pu as progressive (novel ⊥ Lakatos belt) ───────────────────
def test_eureka_verdict_maps_unverified_to_progressive():
    assert eureka_verdict(PU) == 'progressive'
    # abandon-stack(BF 1.0) 과 달리 발견 축은 metric 강도(BF 6.0)로 평가 — 두 축 분리.
    assert bayes_factor(eureka_verdict(PU), delta=5.0, noise_band=0.1) > 3.162
    # 진짜 progressive 는 매핑 무영향(항등), degenerating/partial 등도 불변.
    assert eureka_verdict('progressive') == 'progressive'
    assert eureka_verdict('degenerating') == 'degenerating'


# ── CANONICAL floor: fail-closed via PROMOTABLE exclusion (no promote.py change) ───────────────
def test_unverified_is_not_promotable():
    assert PU not in PROMOTABLE
    ok, reasons = promotion_gate(scripted_verdict=PU, stands=True)
    assert not ok and any('verdict_not_promotable' in r for r in reasons)


# ── series: NEUTRAL third state — known, in-axis, excluded from BOTH counts (FORK1 B) ──────────
def test_series_treats_unverified_as_neutral_not_progress_not_degeneration():
    from lakatos.programme.series import (KNOWN_VERDICTS, NEUTRAL_VERDICTS, ProgrammeSeriesRecord,
                                          programme_series_appraisal)
    assert PU in KNOWN_VERDICTS and PU in NEUTRAL_VERDICTS
    # a neutral-only series: not RAISE, not dropped, and NEITHER progressive NOR degenerating → 'mixed'.
    rows = [ProgrammeSeriesRecord(tag='n1', verdict=PU), ProgrammeSeriesRecord(tag='n2', verdict=PU)]
    ap = programme_series_appraisal(rows)
    assert ap.progressive_count == 0 and ap.nonprogressive_count == 0
    assert ap.trend != 'progressive' and ap.trend != 'degenerating'


# ── write-path demote: rule1 hard_core → different_programme still fires on pu (FORK write-path) ─
def test_hard_core_violation_still_overrides_unverified():
    from server.contexts.tree.judgement_policy import apply_verdict_demotes
    # hard_core 위반(hc_derived False)은 have_qual 무관 구조 신호 → 미검증 노드도 different_programme 로 강등.
    d = apply_verdict_demotes(PU, 'unverified', hc_derived=False, require_novel_anchor=False,
                              novel=False, cross_metric_novel=False, novel_server_anchored=False)
    assert d.verdict == 'different_programme'
    # 위반 아니면 pu 그대로 (구조적 강등 미발화).
    d2 = apply_verdict_demotes(PU, 'unverified', hc_derived=True, require_novel_anchor=False,
                               novel=False, cross_metric_novel=False, novel_server_anchored=False)
    assert d2.verdict == PU
