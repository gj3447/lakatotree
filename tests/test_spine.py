"""엔진 spine TDD — judge(메트릭)+LakatosGate(질적)+승격게이트 단일 권위(F-ARCH-1).
# KG: span_lakatotree_spine / q-lkt-engine-unify
"""
from lakatos.engine import LakatosEvidence, LakatosGate
from lakatos.verdict.spine import reconcile_verdict, promotion_decision

GOOD = LakatosEvidence(theory_laden_anomaly=True, independent_testable_consequence=True,
                       excess_empirical_content=True, hard_core_preserved=True, implementation_complete=True)
HARDCORE_VIOLATED = LakatosEvidence(theory_laden_anomaly=True, independent_testable_consequence=True,
                                    excess_empirical_content=True, hard_core_preserved=False, implementation_complete=True)
INCOMPLETE = LakatosEvidence(theory_laden_anomaly=True, independent_testable_consequence=True,
                             excess_empirical_content=True, hard_core_preserved=True, implementation_complete=False)

def test_metric_progressive_plus_good_lakatos_stays_progressive():
    r = reconcile_verdict('progressive', LakatosGate.evaluate(GOOD))
    assert r['verdict'] == 'progressive' and r['status'] == 'reconciled'

def test_metric_progressive_but_hardcore_violated_is_different_programme():   # AXIS-CORR: 핵 이탈=다른 프로그램
    r = reconcile_verdict('progressive', LakatosGate.evaluate(HARDCORE_VIOLATED))
    assert r['verdict'] == 'different_programme' and 'hard_core_violated' in r['reasons']

def test_metric_progressive_incomplete_conditional():
    r = reconcile_verdict('progressive', LakatosGate.evaluate(INCOMPLETE))
    assert r['verdict'] == 'progressive_conditional'

def test_missing_lakatos_evidence_flags_unverified():   # 정직: 질적 미검증
    r = reconcile_verdict('progressive', None)
    assert r['verdict'] == 'progressive_unverified' and r['lakatos'] == 'unverified'
    assert r['status'] == 'qualitative_unverified'
    assert 'lakatos_evidence_missing' in r['reasons']

def test_metric_not_progressive_governs():   # 메트릭 비진보는 질적 무관하게 그대로
    r = reconcile_verdict('partial', LakatosGate.evaluate(GOOD))
    assert r['verdict'] == 'partial'

def test_metric_nonprogressive_surfaces_qualitative_diagnosis():
    # audit qual-fidelity bug fix: 비진보 metric 이어도 질적 진단(hard_core 위반 등)을 버리지 않는다
    r = reconcile_verdict('partial', LakatosGate.evaluate(HARDCORE_VIOLATED))
    assert r['verdict'] == 'partial'                 # metric 이 verdict 결정(개선 없으면 진보 아님)
    assert r['lakatos'] == 'different_programme'      # 질적 진단은 동봉 — 전엔 'n/a' 로 사라졌음
    assert any('hard_core' in q for q in r['qualitative_reasons'])

def test_promotion_decision_composes_all_gates():
    ok, reasons = promotion_decision(scripted_verdict='progressive', stands=True,
                                     reproducible=False, foundation_gaps=('root-data-contract',),
                                     credibility_reasons=('ambiguous_no_corroboration',))
    assert not ok
    assert 'not_reproducible' in reasons and any('foundation' in r for r in reasons)
    assert 'ambiguous_no_corroboration' in reasons

def test_promotion_decision_clean_passes():
    ok, reasons = promotion_decision(scripted_verdict='progressive', stands=True)
    assert ok and reasons == ()


# === 완전 합성: 모든 승격 게이트 (Foundation + Credibility + 헌법) ===
from lakatos.engine import FoundationMap, FoundationRequirement, KnowledgeKind, CredibilityTier
from lakatos.verdict.spine import synthesize_promotion, credibility_from_trust

def _foundation_with_gap():
    fm = FoundationMap()
    fm.add(FoundationRequirement(name='root-data', kind=KnowledgeKind.DATA,
                                 question='roots?', why_needed='replay', status='needed'))
    return fm

def test_synthesize_all_pass():
    d = synthesize_promotion(scripted_verdict='progressive', stands=True)
    assert d['ok'] and d['reasons'] == ()

def test_synthesize_foundation_gap_blocks():   # FoundationGate 배선
    d = synthesize_promotion(scripted_verdict='progressive', stands=True,
                             foundation=_foundation_with_gap())
    assert not d['ok'] and any('foundation' in r for r in d['reasons'])
    assert d['gates']['foundation']['passed'] is False

def test_synthesize_credibility_blocks():   # CredibilityPromotionGate 배선
    d = synthesize_promotion(scripted_verdict='progressive', stands=True,
                             credibility=dict(current=CredibilityTier.AMBIGUOUS, target=CredibilityTier.EXTRACTED,
                                              has_direct_source=False, has_independent_corroboration=False,
                                              has_human_verdict=False))
    assert not d['ok'] and d['gates']['credibility']['passed'] is False

def test_synthesize_reproducible_false_blocks():
    d = synthesize_promotion(scripted_verdict='progressive', stands=True, reproducible=False)
    assert not d['ok'] and 'not_reproducible' in d['reasons']

def test_synthesize_per_gate_report():
    d = synthesize_promotion(scripted_verdict='progressive', stands=True)
    assert 'constitution' in d['gates']

# credibility_from_trust 매핑 — eigentrust-backed trust → CredibilityPromotionGate (prom-honesty/credibility)
def test_credibility_unbacked_high_trust_is_inconclusive_blocks():
    # ★self-report 고신뢰(eigentrust 미뒷받침, 기본)는 inconclusive → 직접출처 없음·AMBIGUOUS → EXTRACTED 차단
    c = credibility_from_trust(1.0)   # trust_backed=False (default)
    assert c['current'] == CredibilityTier.AMBIGUOUS and c['has_direct_source'] is False
    d = synthesize_promotion(scripted_verdict='progressive', stands=True, credibility=c)
    assert not d['ok'] and d['gates']['credibility']['passed'] is False

def test_credibility_eigentrust_backed_high_trust_passes():
    # eigentrust 로 뒷받침된 고신뢰만 직접출처 EXTRACTED → 통과(게이트 의도='고신뢰 grounded 통과' 보존)
    c = credibility_from_trust(1.0, trust_backed=True)
    assert c['current'] == CredibilityTier.EXTRACTED and c['has_direct_source'] is True
    d = synthesize_promotion(scripted_verdict='progressive', stands=True, credibility=c)
    assert d['ok'] and d['gates']['credibility']['passed'] is True

def test_credibility_backed_mid_trust_blocks_canonical():
    # eigentrust-backed 라도 중신뢰(0.5)는 INFERRED, 직접출처 없음 → CANONICAL 차단
    c = credibility_from_trust(0.5, trust_backed=True)
    assert c['current'] == CredibilityTier.INFERRED and c['has_direct_source'] is False
    d = synthesize_promotion(scripted_verdict='progressive', stands=True, credibility=c)
    assert not d['ok'] and d['gates']['credibility']['passed'] is False

def test_credibility_ambiguous_needs_human():
    # source_trust 0.2 = 저신뢰 → AMBIGUOUS, 인간판정 필수
    c = credibility_from_trust(0.2)
    assert c['current'] == CredibilityTier.AMBIGUOUS
    blocked = synthesize_promotion(scripted_verdict='progressive', stands=True, credibility=c)
    assert not blocked['ok']
    c2 = credibility_from_trust(0.2, has_human_verdict=True)
    passed = synthesize_promotion(scripted_verdict='progressive', stands=True, credibility=c2)
    assert passed['ok']  # 인간이 vouch 하면 통과


# === prom-honesty/provenance (정본 prom 2026-06-21): CANONICAL floor — *위조불가 영수증* ≥1 요구 ===
def test_floor_blocks_canonical_with_no_receipt():
    """R3 발견 봉쇄: 내부 proof 노드(미채점·무critique·무영수증)는 constitution-only 로 CANONICAL 못 됨.
    하드코어(영수증 없는 green=거짓말)·3치(무영수증=inconclusive≠pass)·Lakatos(CANONICAL=최강주장)."""
    d = synthesize_promotion(scripted_verdict='proof', stands=True)
    assert not d['ok'] and d['gates']['floor']['passed'] is False
    assert 'no_receipt_for_canonical' in d['gates']['floor']['reasons']

def test_floor_satisfied_by_judge_scored_verdict():
    """judge-scored 판결(scripted; PROM-A 가 노드 self-report 봉쇄)은 위조불가 영수증 → floor 통과."""
    d = synthesize_promotion(scripted_verdict='progressive', stands=True)
    assert d['ok'] and d['gates']['floor']['passed'] is True

def test_floor_satisfied_by_real_reproducibility():
    """reproducible=True(실 lineage replay)는 위조불가 영수증 → proof 노드라도 floor 통과."""
    d = synthesize_promotion(scripted_verdict='proof', stands=True, reproducible=True)
    assert d['ok'] and d['gates']['floor']['passed'] is True

def test_floor_judge_receipt_via_verdict_source_excludes_legacy_null_source():
    """set_verdict 경로(verdict_source 전달)는 force_of(SSOT)로 판정 — 레거시 NULL-source progressive 는
    영수증 아님(force_of==INCONCLUSIVE). scripted source 만 judge 영수증으로 floor 통과."""
    ok = synthesize_promotion(scripted_verdict='progressive', stands=True, verdict_source='scripted')
    assert ok['ok'] and ok['gates']['floor']['passed'] is True
    legacy = synthesize_promotion(scripted_verdict='progressive', stands=True, verdict_source=None)
    assert not legacy['ok'] and legacy['gates']['floor']['passed'] is False


def test_floor_satisfied_by_human_verdict():
    """human verdict(명시적 attest)는 위조불가 영수증 → proof 노드라도 floor 통과."""
    d = synthesize_promotion(scripted_verdict='proof', stands=True,
                             credibility=credibility_from_trust(0.2, has_human_verdict=True))
    assert d['ok'] and d['gates']['floor']['passed'] is True


def test_credibility_human_verdict_unblocks():
    c = credibility_from_trust(0.5, has_human_verdict=True)
    d = synthesize_promotion(scripted_verdict='progressive', stands=True, credibility=c)
    assert d['ok']


# ── reconcile_standing: certify.py:13 의 '새 반박이 G3 깨면 자동 철회' 이행 ──────────
from lakatos.verdict.spine import reconcile_standing


def test_standing_holds_no_demotion():
    r = reconcile_standing('CANONICAL', stands=True)
    assert r['demoted'] is False and r['verdict'] == 'CANONICAL'


def test_rebutted_canonical_auto_demotes_to_former():
    # 막지 못한 반박(stands=False) + valid_until_rebutted(default True) → 현재최선 철회
    r = reconcile_standing('CANONICAL', stands=False, valid_until_rebutted=True)
    assert r['demoted'] is True
    assert r['verdict'] == 'former_canonical'
    assert r['current_best_pointer'] is False
    assert r['verdict_source'] == 'engine'        # 인간 행정판결과 구분
    assert r['standing_broken'] is True


def test_human_locked_canonical_not_auto_demoted():
    # valid_until_rebutted=False = 인간이 반박-자동무효 OFF(더 강한 잠금) → 자동강등 제외(인간경계)
    r = reconcile_standing('CANONICAL', stands=False, valid_until_rebutted=False)
    assert r['demoted'] is False
    assert r['verdict'] == 'CANONICAL'             # 강등 안 함
    assert r['standing_broken'] is True            # 단 깨짐은 노출(정직)


def test_non_canonical_not_auto_demoted():
    # CANONICAL 아닌 노드는 자동강등 대상 아님 — judgement 은 순수 agent/인간 몫
    r = reconcile_standing('progressive', stands=False)
    assert r['demoted'] is False
    assert r['verdict'] == 'progressive'
    assert r['standing_broken'] is True


def test_demotion_is_symmetric_to_promotion_gate():
    # 승격이 stands 를 요구(synthesize_promotion)하듯, 철회도 같은 stands 사실에 대칭
    from lakatos.verdict.spine import synthesize_promotion
    blocked = synthesize_promotion(scripted_verdict='proof', stands=False)
    assert blocked['ok'] is False                  # stands=False 면 승격 차단
    assert reconcile_standing('CANONICAL', stands=False)['demoted'] is True  # 동일 사실 → 철회
