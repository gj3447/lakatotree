"""FIX-HARNESS #3: *부재* noise_band 가 Bayes 효과크기 가중을 최대화하는 fail-open 회귀 가드.

- finding id: #3 (P2 correctness)
- locations:
    lakatos/quant/bayes.py:57-60  effect_size = abs(delta) / max(noise_band, GROUNDED['effect_size_floor'](=1e-6))
    lakatos/quant/bayes.py:70-72  bayes_factor: es = min(effect_size, EFF_CAP)/EFF_CAP; w = max(es, WEIGHT_FLOOR)*evidence_weight; exp(log(base)*w)
    lakatos/quant/metrics.py feeder 가 `r.get('pred_noise_band') or 0.0` 로 누락/None 을 0.0 으로 강등
    lakatos/multiplicity.py:37  noise_band<=0 을 untestable(None) 로 *올바르게* 처리 — bayes 와 비일관
- the bug:
    noise_band 키가 부재한 노드를 feeder 가 0.0 으로 강등하면 임의의 delta 가 full base BF를 받는다.
    즉 '불확실성 미선언'이 *최대 증거력*을 공짜로 얻는다.
    수정 전에는 feeder가 부재를 0으로 눌러 declared-zero의 최대 BF를 공짜로 부여했다.
    branch_credence에서도 noise_band 키 생략이 정직한 양수 선언보다 높은 credence를 만들었다.
    multiplicity.py:37 은 noise_band<=0 을 untestable(None) 로 보는데 bayes 만 fail-open.
- the fix: 부재(None)는 WEIGHT_FLOOR 약증거로, 명시적 0은 결정론적 측정으로 보존한다.
  feeder는 키 부재를 None으로 운반하며 `or 0.0`으로 의미를 지우지 않는다.

아래 이중가드는 부재 fail-safe와 선언된 척도 메커니즘을 각각 고정한다.
"""
from __future__ import annotations

import pytest

from lakatos.quant.bayes import BF_BASE, bayes_factor, branch_credence


# 정책 게이트 메커니즘이 존재함을 고정하는 양성 오라클(positive oracle):
# noise_band 가 정직하게 선언되면 effect-size 가중이 작동해 marginal < big 이 성립한다.
# 이건 오늘도 통과 — 메커니즘 자체는 살아있고, 문제는 noise_band<=0 의 fail-open 분기뿐임을 격리한다.
def test_declared_noise_band_separates_marginal_from_big():
    marginal = bayes_factor('progressive', 0.001, noise_band=1.0)
    big = bayes_factor('progressive', 4.0, noise_band=1.0)
    # 정직하게 불확실성을 선언하면 큰 개선이 더 강한 증거를 받는다(마진 < 대폭). 메커니즘 존재 증명.
    assert big > marginal
    assert marginal < 6.0   # 마진은 base(6.0) 에 못 미친다


def test_declared_zero_is_deterministic_and_keeps_sensitivity():
    """양성 오라클: 명시된 0은 부재가 아니라 결정론적 측정이다."""
    assert bayes_factor('progressive', 0.5, noise_band=0.0) > 3.0


def test_absent_noise_band_must_not_mint_max_bayes_factor():
    """결함축: 척도 부재는 delta 크기와 무관한 약증거이며 선언-0보다 약해야 한다."""
    absent_trivial = bayes_factor('progressive', 0.001, noise_band=None)
    absent_huge = bayes_factor('progressive', 999.0, noise_band=None)
    deterministic = bayes_factor('progressive', 999.0, noise_band=0.0)
    assert absent_trivial < deterministic
    assert absent_huge < deterministic
    assert absent_trivial == pytest.approx(absent_huge)


def test_absent_noise_band_weakens_negative_evidence_symmetrically():
    absent_small = bayes_factor('rejected', 0.001, noise_band=None)
    absent_huge = bayes_factor('rejected', 999.0, noise_band=None)
    declared_zero = bayes_factor('rejected', 999.0, noise_band=0.0)
    assert absent_small == pytest.approx(absent_huge)
    assert declared_zero == pytest.approx(BF_BASE['rejected'])
    assert declared_zero < absent_small < 1.0


def test_python_default_keeps_legacy_declared_zero_contract():
    assert bayes_factor('progressive', 0.5) == \
        bayes_factor('progressive', 0.5, noise_band=0.0) == BF_BASE['progressive']


# 결함축 음성 오라클 #2 (branch_credence 경로): noise_band 키를 생략하는 것이
# 정직하게 선언하는 것보다 STRICTLY HIGHER credence 를 만들어선 안 된다(fail-toward-strong 금지).
def test_omitting_noise_band_must_not_beat_declaring_it():
    declared = branch_credence([{'verdict': 'progressive', 'delta': 2.0, 'noise_band': 5.0, 'target': 'A'}])
    omitted = branch_credence([{'verdict': 'progressive', 'delta': 2.0, 'target': 'A'}])
    # 수정 후 계약: 불확실성 미선언이 정직 선언보다 더 강한 신뢰도를 minting 해선 안 된다.
    assert omitted <= declared, f"omitting noise band({omitted}) > declaring it({declared}): fail-toward-strong"


# 이중 가드 export (defect-axis negative oracle / mechanism positive oracle).
GUARD_DEFECT = test_absent_noise_band_must_not_mint_max_bayes_factor.__name__
GUARD_MECHANISM = test_declared_noise_band_separates_marginal_from_big.__name__
