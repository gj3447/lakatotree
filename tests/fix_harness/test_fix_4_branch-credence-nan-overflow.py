"""FIX-HARNESS #4 (P3 correctness): branch_credence returns NaN on float odds overflow.

finding id: #4
locations:
  - lakatos/quant/bayes.py:116-120  dedup post-loop: `for lb in best_log_bf.values(): odds *= math.exp(lb)`
    then `return odds / (1 + odds)`.
  - lakatos/quant/bayes.py:93-97  docstring promises 반환 (0,1] 과 포화 시 정확히 1.0.
  - lakatos/quant/bayes.py:132-133  should_abandon_bayes: `c < threshold` — NaN < threshold == False
    (fail-toward-retain). NaN 은 metrics.py:253 canonical_credence 로도 새어나간다.

the bug:
  ~395+ 개의 distinct 최대강도(BF=6 포화) 확증이 들어오면 dedup 후 odds 가 +inf 로 오버플로한다.
  그 다음 odds/(1+odds) = inf/(1+inf) = inf/inf = NaN 을 반환한다. docstring 이 약속한 (0,1]
  (포화 시 정확히 1.0) 을 위반한다. VERIFIED: n=300 → 1.0, n=400 → nan (math.isnan==True).
  하류 영향: should_abandon_bayes 의 `NaN < threshold` 는 항상 False → 폐기 판정 무력화(retain),
  그리고 NaN 이 canonical_credence 메트릭으로 전파된다.

the exact fix (lakatos/quant/bayes.py:116-120):
  log-odds 공간에서 누적 + 안정적 sigmoid 로 계산하거나, odds/(1+odds) 직전에 odds 를 유한
  최댓값으로 clamp 한다. 그러면 포화는 정확히 1.0 으로 saturate 하고 NaN 은 발생하지 않는다.

xfail(strict) until fixed: 단언은 *수정 후* 올바른 동작(유한값 ∈ (0,1])을 encode 한다 →
오늘은 NaN 이라 FAIL(버그 present), 고쳐지면 strict 가 trip.
"""
from __future__ import annotations

import math

import pytest

from lakatos.quant.bayes import branch_credence, should_abandon_bayes


# 400 개의 *서로 다른* target 에 대한 최대강도(BF=6 포화) 확증.
# distinct 라 dedup 가 접지 못한다 → odds 가 곱해져 +inf 로 오버플로한다.
_MAX_CONF = [
    {"verdict": "progressive", "target": f"t{i}", "delta": 100, "noise_band": 0}
    for i in range(400)
]


# 사전조건 / mechanism positive-oracle: 포화 미달(n=300)에서는 (0,1] 의 유한값(정확히 1.0)을
# 정상 반환한다 — 실제 코드 경로가 살아있고 오버플로 *전엔* 계약을 지킴을 고정.
def test_below_overflow_returns_finite_in_unit_interval():
    r = branch_credence(
        [{"verdict": "progressive", "target": f"t{i}", "delta": 100, "noise_band": 0}
         for i in range(300)]
    )
    assert math.isfinite(r)
    assert 0.0 < r <= 1.0


# defect-axis negative oracle.
# [FIXED 2026-06-27] #4 — green regression (bayes.branch_credence clamps non-finite odds → 1.0)
def test_overflow_must_saturate_finite_not_nan():
    r = branch_credence(_MAX_CONF)
    # 수정 후 올바른 동작: 유한값이며 docstring 이 약속한 (0,1] 안에서 1.0 으로 포화.
    assert math.isfinite(r), f"branch_credence returned non-finite {r!r}"
    assert not math.isnan(r)
    assert 0.0 < r <= 1.0


# defect-axis negative oracle (하류): NaN 이 should_abandon_bayes 의 비교를 무력화(fail-toward-retain).
# [FIXED 2026-06-27] #4 — green regression (should_abandon_bayes credence finite)
def test_should_abandon_credence_must_be_finite():
    _abandon, c = should_abandon_bayes(_MAX_CONF)
    assert math.isfinite(c), f"should_abandon_bayes credence non-finite {c!r}"
    assert not math.isnan(c)
