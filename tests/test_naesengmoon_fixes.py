"""나생문 수정 회귀 — 수식 비정합/zero-trust/BLAS/ECE/text-novelty.
# KG: VR_LakatoTree_naesengmoon_3lens_20260612
"""
from lakatos.quant.bayes import bayes_factor, branch_credence
from lakatos.quant.trust import evidence_weight
from lakatos.io.envfp import environment_fingerprint
from lakatos.quant.calibrate import calibration_error

def test_partial_does_not_accumulate_to_certainty():  # F-MATH-2
    assert branch_credence([{'verdict': 'partial'}] * 200) == 0.5   # 땜빵만 = 변화없음

def test_balanced_progressive_rejected_cancels():     # F-MATH-1
    c = branch_credence([{'verdict': 'progressive', 'delta': -0.1, 'noise_band': 0.01},
                         {'verdict': 'rejected', 'delta': 0.1, 'noise_band': 0.01}])
    assert abs(c - 0.5) < 0.05   # 대칭 상쇄

def test_zero_trust_is_no_information():               # F-MATH-4
    assert abs(bayes_factor('progressive', delta=-0.1, noise_band=0.01, source_trust=0.0) - 1.0) < 1e-9
    assert evidence_weight(0.0) == 0.0

def test_envfp_includes_blas():                        # F-MATH-5
    assert 'blas' in environment_fingerprint()

def test_ece_clamps_negative():                        # F-MATH-7
    calibration_error([(-0.1, 0), (0.5, 1)])   # 크래시/오염 없음
