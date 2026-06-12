"""gap8 다중비교 보정 — p 근사 정직성 + BH/Bonferroni 표준 케이스 검증."""
import math

import pytest

from lakatos.multiplicity import (
    benjamini_hochberg, bonferroni, false_progressive_screen, judgment_pvalue,
)


def test_pvalue_strong_improvement_small_p():
    # lower 방향, delta=-3σ → p ≈ 0.00135
    p = judgment_pvalue(-0.3, 0.1, 'lower')
    assert abs(p - 0.00135) < 0.0005


def test_pvalue_no_improvement_large_p():
    p = judgment_pvalue(0.0, 0.1, 'lower')   # 개선 0 → p=0.5
    assert abs(p - 0.5) < 1e-9


def test_pvalue_zero_noise_is_untestable_not_significant():
    assert judgment_pvalue(-5.0, 0.0, 'lower') is None   # 정직②: 침묵 통과 금지


def test_pvalue_direction_validated():
    with pytest.raises(ValueError):
        judgment_pvalue(-1.0, 0.1, 'sideways')


def test_bonferroni_divides_alpha():
    # m=4 (None 은 수행된 검정이 아님 — 분모에서 제외), alpha=0.05 → 컷 0.0125
    flags = bonferroni([0.009, 0.02, None, 0.5, 0.011], alpha=0.05)
    assert flags == [True, False, False, False, True]


def test_bh_step_up_textbook_case():
    # BH 고전 케이스: m=4, q=0.05 — 정렬 p=[0.01,0.02,0.03,0.2], 컷 k/m*q=[0.0125,0.025,0.0375,0.05]
    # k*=3 (0.03≤0.0375) → 앞 3개 reject
    flags = benjamini_hochberg([0.02, 0.2, 0.01, 0.03], q=0.05)
    assert flags == [True, False, True, True]


def test_bh_none_pvals_never_reject():
    assert benjamini_hochberg([None, None]) == [False, False]


def test_screen_reports_untestable_and_survivors():
    cands = [
        {'tag': 'b_strong', 'delta': -0.5, 'noise_band': 0.1, 'direction': 'lower'},
        {'tag': 'b_marginal', 'delta': -0.11, 'noise_band': 0.1, 'direction': 'lower'},
        {'tag': 'b_nonoise', 'delta': -9.9, 'noise_band': 0.0, 'direction': 'lower'},
    ]
    rep = false_progressive_screen(cands)
    assert rep.family_size == 2
    assert rep.untestable == ('b_nonoise',)
    assert 'b_strong' in rep.survivors_bh
    assert 'b_marginal' not in rep.survivors_bonferroni   # 마진 개선은 FWER 에서 탈락
    assert '판결을 바꾸지 않는다' in rep.note


def test_grounded_fdr_q():
    from lakatos.grounding import provenance
    p = provenance('fdr_q')
    assert p['value'] == 0.05 and 'Benjamini' in p['citation']
