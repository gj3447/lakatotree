"""정량 점수 기반지식 TDD — 모든 상수가 권위 문헌 밴드에 정확히 근거(야매 점수 금지).

사용자(2026-06-12): "기반 지식이 풍부하게 있는 기반으로 정확하게 점수를 매겨야".
canonical 값은 상계(WebSearch) 검증 후 계산 확인. 이 테스트가 야매 회귀를 차단한다.
# KG: span_lakatotree_grounding / q-lkt-quantitative-grounding
"""
import math

import pytest

from lakatos import grounding as G


# ── Jeffreys (1961): 밴드 경계 = 10^(k/2) ──────────────────────────────
def test_jeffreys_band_boundaries():
    assert G._band_label(1.0, G.JEFFREYS_BANDS) == 'barely_worth_mentioning'
    assert G._band_label(3.2, G.JEFFREYS_BANDS) == 'substantial'   # >10^0.5
    assert G._band_label(10.0, G.JEFFREYS_BANDS) == 'strong'
    assert G._band_label(31.7, G.JEFFREYS_BANDS) == 'very_strong'
    assert G._band_label(100.0, G.JEFFREYS_BANDS) == 'decisive'


def test_jeffreys_boundaries_are_half_decades():
    los = [lo for lo, _ in G.JEFFREYS_BANDS]
    assert math.isclose(los[1], 10 ** 0.5, rel_tol=1e-9)
    assert math.isclose(los[3], 10 ** 1.5, rel_tol=1e-9)


# ── Kass & Raftery (1995): 2·ln(BF) 척도 ───────────────────────────────
def test_interpret_bf_progressive_value():
    # BF_BASE progressive=6.0 → Jeffreys substantial, KR positive
    r = G.interpret_bayes_factor(6.0)
    assert r['jeffreys'] == 'substantial' and r['kass_raftery'] == 'positive'
    assert r['favors'] == 'for'
    assert math.isclose(r['two_ln_bf'], 2 * math.log(6), abs_tol=1e-3)  # 함수가 4자리 반올림


def test_interpret_bf_decisive():
    r = G.interpret_bayes_factor(200.0)
    assert r['jeffreys'] == 'decisive' and r['kass_raftery'] == 'very_strong'


def test_interpret_bf_against_uses_reciprocal():
    r = G.interpret_bayes_factor(1 / 6.0)
    assert r['favors'] == 'against' and r['jeffreys'] == 'substantial'  # 역수 등급


def test_interpret_bf_rejects_nonpositive():
    with pytest.raises(ValueError):
        G.interpret_bayes_factor(0.0)


# ── Cohen (1988): 효과크기 등급 ────────────────────────────────────────
def test_cohen_d_grades():
    assert G.cohen_d_grade(0.1) == 'negligible'
    assert G.cohen_d_grade(0.2) == 'small'
    assert G.cohen_d_grade(0.5) == 'medium'
    assert G.cohen_d_grade(0.8) == 'large'
    assert G.cohen_d_grade(-0.9) == 'large'   # 절대값


# ── Wald (1945): SPRT 경계 ─────────────────────────────────────────────
def test_sprt_boundaries_symmetric_at_05():
    lnA, lnB = G.sprt_log_boundaries(0.05, 0.05)
    assert math.isclose(lnA, 2.944, abs_tol=1e-3)
    assert math.isclose(lnB, -2.944, abs_tol=1e-3)
    assert math.isclose(lnA, -lnB, rel_tol=1e-9)   # 대칭


def test_sprt_boundary_formula():
    a, b = 0.01, 0.05
    lnA, lnB = G.sprt_log_boundaries(a, b)
    assert math.isclose(lnA, math.log((1 - b) / a), rel_tol=1e-12)
    assert math.isclose(lnB, math.log(b / (1 - a)), rel_tol=1e-12)


# ── Wilson (1927): 신뢰하한 알려진 값 ──────────────────────────────────
def test_wilson_known_values():
    assert math.isclose(G.wilson_lower_bound(10, 10), 0.722, abs_tol=1e-3)
    assert math.isclose(G.wilson_lower_bound(9, 10), 0.596, abs_tol=1e-3)
    assert math.isclose(G.wilson_lower_bound(20, 20), 0.839, abs_tol=1e-3)
    assert G.wilson_lower_bound(0, 0) == 0.0


def test_wilson_10of10_passes_9of10_fails_nobel_threshold():
    # 0.7 임계의 근거: 9/10 탈락, 10/10 통과 (운 좋은 소표본 배제)
    assert G.wilson_lower_bound(9, 10) < 0.7 <= G.wilson_lower_bound(10, 10)


# ── provenance: 점수가 자기 근거(문헌)를 들고 다님 ────────────────────
def test_provenance_carries_citation():
    p = G.provenance('bf_progressive')
    assert p['value'] == 6.0 and 'Jeffreys' in p['citation']
    assert 'substantial' in p['band']


# ── 일관성: 모듈 상수가 grounding 정본과 일치 (drift 차단) ─────────────
def test_bayes_constants_match_grounding():
    from lakatos import bayes
    assert bayes.BF_BASE['progressive'] == G.GROUNDED['bf_progressive']['value']
    assert bayes.BF_BASE['rejected'] == G.GROUNDED['bf_rejected']['value']
    assert bayes.EFF_CAP == G.GROUNDED['eff_cap']['value']
    assert bayes.DEFAULT_PRIOR == G.GROUNDED['default_prior']['value']


def test_laudan_constants_match_grounding():
    from lakatos import laudan
    assert laudan.ABANDON_K == G.GROUNDED['abandon_k']['value']
    assert laudan.ABANDON_BUDGET == G.GROUNDED['abandon_budget']['value']


def test_fertility_constants_match_grounding():
    from lakatos import fertility
    assert fertility.NOBEL_MIN_HITRATE_LB == G.GROUNDED['nobel_min_hitrate_lb']['value']


# ── SPRT-근거 폐기가 휴리스틱 K=3 과 정합 ─────────────────────────────
def test_sprt_abandonment_matches_k3_heuristic():
    from lakatos.laudan import should_abandon_sprt
    # 노드당 ≈−1 nat 비진보 3개 → 누적 −3 ≤ lnB(−2.944) → abandon (K=3 휴리스틱과 일치)
    v, s, (lnA, lnB) = should_abandon_sprt([-1.0, -1.0, -1.0])
    assert v == 'abandon' and s <= lnB
    # 진보 누적 → retain
    v2, _, _ = should_abandon_sprt([1.0, 1.0, 1.0])
    assert v2 == 'retain'
    # 약한 혼합 → 미결(더 관측)
    v3, _, _ = should_abandon_sprt([-0.5, 0.3])
    assert v3 == 'undecided'
