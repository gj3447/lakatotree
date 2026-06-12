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

def test_metric_progressive_but_hardcore_violated_downgrades():   # 핵심: 질적 게이트가 메트릭 진보를 강등
    r = reconcile_verdict('progressive', LakatosGate.evaluate(HARDCORE_VIOLATED))
    assert r['verdict'] == 'degenerating' and 'hard_core_preserved' in r['reasons']

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
from lakatos.spine import synthesize_promotion

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
