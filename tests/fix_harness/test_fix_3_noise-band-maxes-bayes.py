"""FIX-HARNESS #3 (P2 correctness): *부재* noise_band 가 Bayes 효과크기 가중을 조용히 최대화 — fail-toward-strong.

- finding id: #3 (P2 correctness)
- locations:
    lakatos/quant/bayes.py:bayes_factor   noise_band 부재(None)도 0 처럼 floor(1e-6)로 나눠 effect_size 포화
    lakatos/quant/metrics.py:58,141,303    feeder 가 `r.get('pred_noise_band') or 0.0` 로 *누락* 을 0.0 으로 강등
    lakatos/eureka.py:88,131               eureka 도 동일 강등 → 미선언 노드가 최대 증거(true-eureka 위조)
    lakatos/multiplicity.py:37             noise_band<=0 을 untestable 로 *올바르게* 처리 — bayes 와 비일관(수정 전)
- the bug:
    불확실성을 *선언하지 않은*(noise_band 키 부재) 노드가 feeder 에서 0.0 으로 강등되고, bayes_factor 가
    0.0 을 무잡음(=최대 민감도)으로 취급 → 임의의 delta 가 full base BF(progressive=6.0)을 *공짜로* 받는다.
    즉 '불확실성 미선언'이 정직히 선언한 노드보다 강한 증거력을 얻는다(fail-toward-strong).
- the fix (정직한 시맨틱: 부재 ≠ 선언-0):
    bayes_factor 가 noise_band=None(부재)을 약증거(WEIGHT_FLOOR, failsafe)로 처리한다 — SOURCE_TRUST_FAILSAFE
    와 동형. *선언된* noise_band(0 포함)는 결정론적 측정 척도로 보고 정상 효과크기를 적용한다(선언-0 = 무잡음
    측정 = 큰 민감도 정당). feeder 는 누락을 0 으로 강등하지 말고 None 으로 흘린다(`or 0.0` 제거).
    핵심 계약: noise_band *부재* 가 최대 증거력을 공짜로 받아선 안 되고, 생략이 정직 선언보다 strictly higher
    credence 를 만들어선 안 된다. 단 *선언된* 결정론적 0 은 망가뜨리지 않는다.

xfail(strict) until fixed — 아래 음성 오라클은 수정 후 올바른 동작을 인코딩한다(오늘 = 버그라 FAIL).
"""
from __future__ import annotations

import pytest

from lakatos.quant.bayes import bayes_factor, branch_credence


# ── 양성/메커니즘 오라클 (오늘도 green): 정직히 선언하면 effect-size 가중이 작동(marginal < big). ──
def test_declared_noise_band_separates_marginal_from_big():
    marginal = bayes_factor('progressive', 0.001, noise_band=1.0)
    big = bayes_factor('progressive', 4.0, noise_band=1.0)
    assert big > marginal           # 선언된 불확실성 하에서 큰 개선이 더 강한 증거 — 메커니즘 존재
    assert marginal < 6.0           # 마진은 base(6.0) 에 못 미친다


# ── 양성/메커니즘 오라클 #2 (오늘도 green): *선언된* 결정론적 0 은 큰 민감도를 정당히 유지(over-fix 방지). ──
def test_declared_zero_is_deterministic_and_keeps_sensitivity():
    declared_zero = bayes_factor('progressive', 0.5, noise_band=0.0)   # 무잡음 측정 = 진짜 신호
    assert declared_zero > 3.0      # 선언-0 은 약화되지 않는다(부재와 구별)


# ── 결함축 음성 오라클 (defect, bug-dead): *부재*(None) noise_band 는 최대 증거를 공짜로 받지 못한다. ──
# [FIXED 2026-06-28] #3 — green regression (bayes_factor: noise_band None → weak; declared-0 preserved)
def test_absent_noise_band_must_not_mint_max_bayes_factor():
    absent_trivial = bayes_factor('progressive', 0.001, noise_band=None)
    absent_huge = bayes_factor('progressive', 999.0, noise_band=None)
    deterministic = bayes_factor('progressive', 999.0, noise_band=0.0)   # 선언-0(무잡음) = 강함
    # 수정 후 계약: 부재(미선언)는 척도 미상 → 약증거(failsafe). delta 크기와 무관(척도가 없으니).
    assert absent_trivial < deterministic, f"부재({absent_trivial}) 가 선언-0({deterministic}) 만큼 강함 = fail-open"
    assert absent_huge < deterministic, f"부재 huge({absent_huge}) 도 선언-0({deterministic}) 미만이어야"
    assert absent_trivial == pytest.approx(absent_huge), "부재는 척도 미상 → delta 무관 약증거(동일)"


# ── 결함축 음성 오라클 #2 (branch_credence 실 정본경로): 생략(키 부재)이 정직 선언보다 높은 신뢰도 금지. ──
# [FIXED 2026-06-28] #3 — green regression (feeders pass absent noise_band as None → weak credence)
def test_omitting_noise_band_must_not_beat_declaring_it():
    declared = branch_credence([{'verdict': 'progressive', 'delta': 2.0, 'noise_band': 5.0, 'target': 'A'}])
    omitted = branch_credence([{'verdict': 'progressive', 'delta': 2.0, 'target': 'A'}])   # noise_band 키 부재
    # 수정 후 계약: 불확실성 미선언(부재)이 정직 선언보다 더 강한 신뢰도를 minting 해선 안 된다.
    assert omitted <= declared, f"omitting noise band({omitted}) > declaring it({declared}): fail-toward-strong"


# 이중 가드 export (defect-axis negative oracle / mechanism positive oracle).
GUARD_DEFECT = test_absent_noise_band_must_not_mint_max_bayes_factor.__name__
GUARD_MECHANISM = test_declared_noise_band_separates_marginal_from_big.__name__
