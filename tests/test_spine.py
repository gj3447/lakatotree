"""엔진 spine TDD — judge(메트릭)+LakatosGate(질적)+승격게이트 단일 권위(F-ARCH-1).
# KG: span_lakatotree_spine / q-lkt-engine-unify
"""
from lakatos.engine import LakatosEvidence, LakatosGate
from lakatos.spine import reconcile_verdict, promotion_decision

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
    assert r['verdict'] == 'progressive' and r['lakatos'] == 'unverified'
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
from lakatos.spine import synthesize_promotion, credibility_from_trust

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

# credibility_from_trust 매핑 — source_trust → CredibilityPromotionGate 입력 (set_verdict 배선)
def test_credibility_high_trust_is_extracted_passes():
    # bash 지반·고신뢰(>=0.70) → EXTRACTED, target<=current → 게이트 자명 통과
    c = credibility_from_trust(1.0)
    assert c['current'] == CredibilityTier.EXTRACTED and c['has_direct_source'] is True
    d = synthesize_promotion(scripted_verdict='progressive', stands=True, credibility=c)
    assert d['ok'] and d['gates']['credibility']['passed'] is True

def test_credibility_low_trust_internet_blocks_canonical():
    # source_trust 0.5 = 인터넷 영향 중간신뢰, 직접출처·인간판정 없음 → CANONICAL 차단
    c = credibility_from_trust(0.5)
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

def test_credibility_human_verdict_unblocks():
    c = credibility_from_trust(0.5, has_human_verdict=True)
    d = synthesize_promotion(scripted_verdict='progressive', stands=True, credibility=c)
    assert d['ok']
