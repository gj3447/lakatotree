"""신뢰도 보정 TDD — proper scoring(Brier/log)로 예측 calibration 정량.
# KG: span_lakatotree_calibrate
"""
from lakatos.calibrate import brier_score, log_score, calibration_error

def test_brier_perfect_is_zero():
    assert brier_score([(1.0, 1), (0.0, 0)]) == 0.0

def test_brier_worst_is_one():
    assert brier_score([(0.0, 1), (1.0, 0)]) == 1.0

def test_log_score_penalizes_overconfidence():
    # 확신했는데 틀림 = 큰 페널티 (log 가 overconfidence 강벌)
    confident_wrong = log_score([(0.99, 0)])
    mild_wrong = log_score([(0.6, 0)])
    assert confident_wrong > mild_wrong

def test_calibration_error_well_calibrated():
    # 0.5 라 말한 게 절반 맞으면 보정 잘 됨 (ECE 낮음)
    fc = [(0.5, 1), (0.5, 0), (0.5, 1), (0.5, 0)]
    assert calibration_error(fc) < 0.1
