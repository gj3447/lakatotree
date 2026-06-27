"""FIX-HARNESS #3 (P2 correctness): 누락/0 noise_band 가 Bayes 효과크기 가중을 조용히 최대화 — '마진 < 대폭' 무력화.

- finding id: #3 (P2 correctness)
- locations:
    lakatos/quant/bayes.py:57-60  effect_size = abs(delta) / max(noise_band, GROUNDED['effect_size_floor'](=1e-6))
    lakatos/quant/bayes.py:70-72  bayes_factor: es = min(effect_size, EFF_CAP)/EFF_CAP; w = max(es, WEIGHT_FLOOR)*evidence_weight; exp(log(base)*w)
    lakatos/quant/metrics.py:58,141  feeder 가 `r.get('pred_noise_band') or 0.0` 로 누락/None 을 0.0 으로 강등
    lakatos/multiplicity.py:37  noise_band<=0 을 untestable(None) 로 *올바르게* 처리 — bayes 와 비일관
- the bug:
    noise_band 가 0/누락이면 분모가 floor(1e-6) 로 붕괴 → 임의의 delta 가 effect_size 를 EFF_CAP(4.0) 까지
    포화 → es=1.0 → full base BF(progressive=6.0) 을 받는다. 즉 '불확실성 미선언'이 *최대 증거력*을 공짜로 얻는다.
    VERIFIED: bayes_factor('progressive',0.001,0.0)==6.0 이고 ==bayes_factor('progressive',999,0.0)==6.0
             bayes_factor('progressive',0.001,1.0)==1.71 (정직하게 선언하면 약한 증거).
    그리고 branch_credence([{progressive,delta=2,noise_band=5,target=A}])=0.631 인데
          noise_band=0 으로 바꾸면 0.857 (≡ noise band 생략 = STRICTLY HIGHER credence = fail-toward-strong).
    multiplicity.py:37 은 noise_band<=0 을 untestable(None) 로 보는데 bayes 만 fail-open.
- the exact fix (lakatos/quant/bayes.py:57-72):
    noise_band<=0 일 때 es 를 최대(1.0)로 포화시키지 말고 약증거(weak evidence)로 떨어뜨린다 —
    예: noise_band<=0 이면 effect_size 를 0(→ es=0 → w=WEIGHT_FLOOR, 마진 최소 증거력)으로 처리하거나,
    선언-0 과 부재를 구분하고 부재는 weak/untestable 로. feeder 의 `or 0.0` 강등(metrics.py:58,141) 제거.
    핵심 계약: noise_band 미선언/0 의 *trivial* delta 가 *huge* delta 와 동일한(최대) bayes_factor 를
    받아선 안 된다. noise band 생략이 정직 선언보다 strictly higher credence 를 만들어선 안 된다.

xfail(strict) until fixed — 아래 단언은 *수정 후* 올바른 동작을 인코딩한다(오늘 = 버그라 FAIL).
"""
from __future__ import annotations

import pytest

from lakatos.quant.bayes import bayes_factor, branch_credence


# 정책 게이트 메커니즘이 존재함을 고정하는 양성 오라클(positive oracle):
# noise_band 가 정직하게 선언되면 effect-size 가중이 작동해 marginal < big 이 성립한다.
# 이건 오늘도 통과 — 메커니즘 자체는 살아있고, 문제는 noise_band<=0 의 fail-open 분기뿐임을 격리한다.
def test_declared_noise_band_separates_marginal_from_big():
    marginal = bayes_factor('progressive', 0.001, noise_band=1.0)
    big = bayes_factor('progressive', 4.0, noise_band=1.0)
    # 정직하게 불확실성을 선언하면 큰 개선이 더 강한 증거를 받는다(마진 < 대폭). 메커니즘 존재 증명.
    assert big > marginal
    assert marginal < 6.0   # 마진은 base(6.0) 에 못 미친다


# 결함축 음성 오라클(negative oracle, bug-dead): noise_band=0 인 trivial delta 가
# huge delta 와 *같은* (최대) bayes_factor 를 받아선 안 된다.
@pytest.mark.xfail(reason="FIX-HARNESS #3: noise_band=0/누락이 effect-size 가중을 최대화해 trivial delta 가 full base BF 를 받음 — RED until lakatos/quant/bayes.py:57-72 (noise_band<=0 → weak, not es=1.0); strict trips when fixed",
                   strict=True)
def test_zero_noise_band_trivial_delta_must_not_mint_max_bayes_factor():
    trivial = bayes_factor('progressive', 0.001, noise_band=0.0)
    huge = bayes_factor('progressive', 999.0, noise_band=0.0)
    base = bayes_factor('progressive', 999.0, noise_band=1e-9)  # 사실상 최대(base=6.0)
    # 수정 후 계약: 불확실성 미선언(noise_band=0) 의 trivial 개선은 huge 개선과 같은 최대 증거력을
    # 받아선 안 된다. 오늘은 둘 다 6.0 (== base) 으로 동일 = 버그.
    assert trivial < huge, f"trivial({trivial}) == huge({huge}): noise_band=0 가 effect-size 를 포화시킴"
    assert trivial < base, f"trivial({trivial}) 가 full base BF({base}) 를 공짜로 받음(fail-open)"


# 결함축 음성 오라클 #2 (branch_credence 경로, 실 정본경로): noise band 를 생략(0)하는 것이
# 정직하게 선언하는 것보다 STRICTLY HIGHER credence 를 만들어선 안 된다(fail-toward-strong 금지).
@pytest.mark.xfail(reason="FIX-HARNESS #3: branch_credence 에서 noise_band 생략(0)이 정직 선언보다 높은 신뢰도를 만듦 — RED until lakatos/quant/bayes.py:57-72; strict trips when fixed",
                   strict=True)
def test_omitting_noise_band_must_not_beat_declaring_it():
    declared = branch_credence([{'verdict': 'progressive', 'delta': 2.0, 'noise_band': 5.0, 'target': 'A'}])
    omitted = branch_credence([{'verdict': 'progressive', 'delta': 2.0, 'noise_band': 0.0, 'target': 'A'}])
    # 수정 후 계약: 불확실성 미선언이 정직 선언보다 더 강한 신뢰도를 minting 해선 안 된다.
    # 오늘은 omitted(0.857) > declared(0.631) = 버그(fail-toward-strong).
    assert omitted <= declared, f"omitting noise band({omitted}) > declaring it({declared}): fail-toward-strong"


# 이중 가드 export (defect-axis negative oracle / mechanism positive oracle).
GUARD_DEFECT = test_zero_noise_band_trivial_delta_must_not_mint_max_bayes_factor.__name__
GUARD_MECHANISM = test_declared_noise_band_separates_marginal_from_big.__name__
