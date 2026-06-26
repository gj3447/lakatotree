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
    from lakatos.quant import bayes
    assert bayes.BF_BASE['progressive'] == G.GROUNDED['bf_progressive']['value']
    assert bayes.BF_BASE['rejected'] == G.GROUNDED['bf_rejected']['value']
    assert bayes.EFF_CAP == G.GROUNDED['eff_cap']['value']
    assert bayes.DEFAULT_PRIOR == G.GROUNDED['default_prior']['value']


def test_laudan_constants_match_grounding():
    from lakatos.quant import laudan
    assert laudan.ABANDON_K == G.GROUNDED['abandon_k']['value']
    assert laudan.ABANDON_BUDGET == G.GROUNDED['abandon_budget']['value']


def test_fertility_constants_match_grounding():
    from lakatos.quant import fertility
    assert fertility.NOBEL_MIN_HITRATE_LB == G.GROUNDED['nobel_min_hitrate_lb']['value']


# ── 정직성: 고아 인용 0 (모든 source 키가 SOURCES 에 등록) ──────────────
def test_no_orphan_citations():
    for k, g in G.GROUNDED.items():
        assert g['source'] in G.SOURCES, f'고아 인용: {k} → {g["source"]}'


# ── 정직성: tier 가 문헌값/정책값을 정직히 구분 (가짜 정밀 차단) ────────
def test_every_constant_has_tier():
    for k, g in G.GROUNDED.items():
        assert g['tier'] in ('literature', 'policy_in_scale', 'policy'), f'{k} tier 누락/오류'


def test_policy_constants_labeled_policy_not_literature():
    # ★나생문: 역산/엔지니어링 값은 policy 로 정직 표시 (문헌인 척 금지)
    tiers = G.grounding_tiers()
    for c in ('weight_floor', 'abandon_b', 'w_problem', 'abandon_budget'):
        assert c in tiers['policy'], f'{c} 는 정책값인데 policy tier 아님'
    # 순수 문헌값은 literature
    for c in ('pagerank_damping', 'default_prior'):
        assert c in tiers['literature']
    # ★웹 재검증 2026-06-14 정정: ece_bins(=10)·eigentrust_alpha(=0.15)는 원전이 인쇄한 값이 아니라
    # 정책 기본값/파생값(Guo 원전 M=15 / PageRank teleport 1−0.85) → policy_in_scale (문헌인 척 금지)
    assert G.GROUNDED['ece_bins']['tier'] == 'policy_in_scale'
    assert G.GROUNDED['eigentrust_alpha']['tier'] == 'policy_in_scale'


def test_policy_source_constants_point_to_policy_or_inspiration():
    # source='policy' 인 값은 SOURCES['policy'] 가 "문헌 도출 아님"을 명시
    assert '문헌 도출 아님' in G.SOURCES['policy']


def test_two_ln_bf_is_magnitude_nonnegative():
    # bf<1 이어도 two_ln_bf ≥0 (크기), 방향은 favors
    r = G.interpret_bayes_factor(0.1)
    assert r['two_ln_bf'] >= 0 and r['favors'] == 'against'


# ── F-MATH-2: _band_label 입력 순서 무관 (정렬 안 된 밴드도 옳게) ───────
def test_band_label_order_independent():
    unsorted_bands = [(10, 'high'), (3, 'medium'), (1, 'low')]
    assert G._band_label(5.0, unsorted_bands) == 'medium'   # 5 ∈ [3,10)
    assert G._band_label(0.5, unsorted_bands) == 'low'      # < 첫 하한 → 최저
    assert G._band_label(20.0, unsorted_bands) == 'high'


# ── F-MATH-3: SPRT α+β≥1 거부 (경계 역전 방지) ────────────────────────
def test_sprt_rejects_alpha_plus_beta_ge_1():
    with pytest.raises(ValueError):
        G.sprt_log_boundaries(0.6, 0.5)   # 합 1.1 ≥ 1 → 경계 역전
    with pytest.raises(ValueError):
        G.sprt_log_boundaries(0.5, 0.5)   # 합 정확히 1


# ── F-MATH-1: NOBEL 실효 최소표본 = 9/9 (3/3·8/8 탈락) ─────────────────
def test_nobel_effective_minimum_is_9():
    from lakatos.quant.fertility import nobel_grade
    def fert(c, r): return dict(registered=r, confirmed=c, fertility=c / r)
    assert nobel_grade(fert(3, 3)) is False    # 하한 0.438 < 0.7
    assert nobel_grade(fert(8, 8)) is False    # 하한 0.676 < 0.7
    assert nobel_grade(fert(9, 9)) is True     # 하한 0.701 ≥ 0.7 (실효 통과선)
    assert nobel_grade(fert(9, 10)) is False   # 적중률 자체 부족


# ── SPRT-근거 폐기가 휴리스틱 K=3 과 정합 ─────────────────────────────
def test_sprt_abandonment_matches_k3_heuristic():
    from lakatos.quant.laudan import should_abandon_sprt
    # 노드당 ≈−1 nat 비진보 3개 → 누적 −3 ≤ lnB(−2.944) → abandon (K=3 휴리스틱과 일치)
    v, s, (lnA, lnB) = should_abandon_sprt([-1.0, -1.0, -1.0])
    assert v == 'abandon' and s <= lnB
    # 진보 누적 → retain
    v2, _, _ = should_abandon_sprt([1.0, 1.0, 1.0])
    assert v2 == 'retain'
    # 약한 혼합 → 미결(더 관측)
    v3, _, _ = should_abandon_sprt([-0.5, 0.3])
    assert v3 == 'undecided'


# ── B6 T-H-1/THR-2/LKT-T2: grounding single-source 소비 + wilson 입력검증 + UCB 정본 ──

def test_grounding_single_source_consumed_by_modules():
    import inspect
    import lakatos.quant.calibrate as cal, lakatos.trust as tr, lakatos.programme.explore as ex
    assert inspect.signature(cal.calibration_error).parameters['bins'].default == G.GROUNDED['ece_bins']['value']
    assert inspect.signature(tr.trustrank).parameters['damping'].default == G.GROUNDED['pagerank_damping']['value']
    assert inspect.signature(tr.eigentrust).parameters['alpha'].default == G.GROUNDED['eigentrust_alpha']['value']
    assert ex.UCB_C == G.GROUNDED['ucb_c']['value']


def test_ucb_c_grounded_precise():
    import math
    assert G.GROUNDED['ucb_c']['value'] == math.sqrt(2)        # 정밀 √2 (1.414 하드코딩 아님)
    assert G.GROUNDED['ucb_c']['tier'] == 'literature'


def test_wilson_lower_bound_rejects_k_out_of_range():
    import pytest
    with pytest.raises(ValueError):
        G.wilson_lower_bound(11, 10)      # k>n → math domain error 대신 ValueError
    with pytest.raises(ValueError):
        G.wilson_lower_bound(-1, 5)
    assert G.wilson_lower_bound(0, 0) == 0.0                   # n=0 가드 보존


def test_wilson_k_positive_n_zero_now_raises():
    # 나생문 B6: (11,10)/(-1,5)는 전에도 math domain error 였음. 진짜 새로 닫힌 path =
    # (k>0, n=0) — 전엔 n==0 단락으로 0.0 조용히 반환(silent wrong), 이제 ValueError.
    with pytest.raises(ValueError):
        G.wilson_lower_bound(5, 0)


# ── B2: 수치 가드 상수도 grounding 정본 (하드코딩 1e-6/1e-9 금지, drift/G5 우회 차단) ──
def test_numeric_guards_registered_in_grounding():
    # effect_size 분모-0 가드 / log_score log(0) 클램프 — 두 수치 가드가 GROUNDED 정본에 등록
    assert G.GROUNDED['effect_size_floor']['value'] == 1e-6
    assert G.GROUNDED['log_score_eps']['value'] == 1e-9
    assert G.GROUNDED['effect_size_floor']['tier'] in ('policy', 'policy_in_scale')
    assert G.GROUNDED['log_score_eps']['tier'] in ('policy', 'policy_in_scale')
    # 고아 인용 금지(source 가 SOURCES 에 등록)는 test_no_orphan_citations 가 전수 검증


def test_numeric_guard_defaults_bind_to_grounding():
    # ece_bins/UCB_C 처럼 함수 기본값이 grounding 정본을 실제로 소비 (test_grounding_single_source… 패턴)
    import inspect
    from lakatos.quant import bayes, calibrate
    assert inspect.signature(bayes.effect_size).parameters['floor'].default \
        == G.GROUNDED['effect_size_floor']['value']
    assert inspect.signature(calibrate.log_score).parameters['eps'].default \
        == G.GROUNDED['log_score_eps']['value']


def test_no_inline_numeric_guards_left_in_quant():
    # quant/ 소스에 인라인 1e-6/1e-9 가 남아있지 않아야 한다(grounding 만 보유) — 야매 회귀 차단
    import pathlib
    import lakatos.quant as q
    qdir = pathlib.Path(q.__file__).parent
    offenders = [f.name for f in qdir.glob('*.py')
                 if ('1e-6' in f.read_text(encoding='utf-8')
                     or '1e-9' in f.read_text(encoding='utf-8'))]
    assert not offenders, f'quant/ 인라인 수치가드 잔존: {offenders}'


def test_p6_3_credibility_and_claim_thresholds_grounded():
    # P6-3: spine/engine 가 0.70/0.35 를 각자 하드코딩하던 것 → GROUNDED 단일 정본. claim 도.
    from lakatos.verdict import spine
    from lakatos.claim import ClaimStandingPolicy
    from lakatos.engine import CredibilityTier
    assert spine._CRED_EXT == G.GROUNDED['credibility_extracted_trust']['value'] == 0.70
    assert spine._CRED_INF == G.GROUNDED['credibility_inferred_trust']['value'] == 0.35
    p = ClaimStandingPolicy()
    assert p.min_confidence == G.GROUNDED['claim_min_confidence']['value']
    assert p.strong_confidence == G.GROUNDED['claim_strong_confidence']['value']
    # 경계가 grounded 값을 실제로 씀(spine·engine 공유). prom-honesty/credibility: 경계 매핑은
    # *eigentrust-backed* 일 때만 등급화(trust_backed=True); unbacked self-report 는 AMBIGUOUS(inconclusive).
    assert spine.credibility_from_trust(0.70, trust_backed=True)['current'] == CredibilityTier.EXTRACTED
    assert spine.credibility_from_trust(0.34, trust_backed=True)['current'] == CredibilityTier.AMBIGUOUS
    assert spine.credibility_from_trust(0.70)['current'] == CredibilityTier.AMBIGUOUS   # unbacked=inconclusive


# ── 정직성: 고아 라이선스 0 (코드의 '라이선스(THEORY §8): <id>' 앵커가 모두 SOURCES 에 등록) ──────────
def test_license_anchors_resolve_to_sources():
    """test_no_orphan_citations 의 *메커니즘 라이선스* 판 — 숫자(상수)뿐 아니라 간판 메커니즘의 철학적
    라이선스도 grounding.SOURCES 에 못 박혀야(THEORY §8 dogfooding: "라이선스 없는 메커니즘 금지").
    코드의 '라이선스(THEORY §8): a b c' 앵커가 가리키는 모든 sourceId 가 SOURCES 에 실재하는지 전수 검증."""
    import re
    from pathlib import Path
    import lakatos.grounding as G
    pkg = Path(G.__file__).parent
    orphans = []
    for f in pkg.rglob('*.py'):
        for ids in re.findall(r'라이선스\(THEORY §8\):\s*([a-z0-9_ ]+)', f.read_text(encoding='utf-8')):
            for sid in ids.split():
                if sid not in G.SOURCES:
                    orphans.append(f'{f.name}:{sid}')
    assert not orphans, f'고아 라이선스 앵커(grounding.SOURCES 미등록): {orphans}'


def test_license_anchors_present_on_key_modules():
    """앵커가 실제로 박혔는지(빈 가드 방지) — 핵심 모듈에 라이선스 앵커가 존재."""
    from pathlib import Path
    import lakatos.grounding as G
    pkg = Path(G.__file__).parent
    anchored = {f.name for f in pkg.rglob('*.py')
                if '라이선스(THEORY §8):' in f.read_text(encoding='utf-8')}
    assert {'judge.py', 'agm.py', 'bayes.py', 'argue.py', 'leaderboard.py'} <= anchored
