"""BPC 검사 ground-truth (사전등록 예측) — 정답 verdict 메커니즘 + 파이프라인 drift 탐지 (TDD).

(B) 해결 검증: 정답 verdict = lakatotree 사전등록 잠금 Prediction. 외부 라벨 없이 재현가능·조작불가.
ZDF 측정 dev → judge → PASS/FAIL, 파이프라인 verdict(oo)와 대조해 drift 잡음.
"""
import pytest

from examples.bpc_inspection_groundtruth import (
    tolerance_for, preregister, ground_truth_verdict, check_against_pipeline, run)
from lakatos.judge import judge, PredictionMissing, PredictionLocked, check_registration


# ── 공차 spec (정답 contract 근거) ──
def test_tolerance_grounded_tiered():
    assert tolerance_for('bush_base') == 1.5
    assert tolerance_for('bolt') == 0.8
    assert tolerance_for('b_point') == 1.0
    assert tolerance_for('unknown_group') == 1.0          # default


# ── 정답 verdict = dev < tolerance (엄격) ──
def test_within_tolerance_is_pass():
    assert ground_truth_verdict('bolt', 0.31) == 'PASS'   # 0.31 < 0.8
    assert ground_truth_verdict('bush_base', 1.49) == 'PASS'


def test_over_or_equal_tolerance_is_fail_strict():
    assert ground_truth_verdict('bolt', 0.95) == 'FAIL'   # 0.95 > 0.8
    assert ground_truth_verdict('bolt', 0.80) == 'FAIL'   # ==tol → 엄격 < → FAIL


def test_ground_truth_matches_pipeline_rule_improved():
    # judge.improved 가 prismv2/jg_bpc 의 dev_xy<tolerance_mm 와 동일함을 직접 확인
    assert judge(preregister('bolt'), 0.5).improved is True    # 0.5 < 0.8
    assert judge(preregister('bolt'), 0.9).improved is False   # 0.9 > 0.8


# ── lakatotree 계약 강제: 사전등록 필수 + 잠금 (정답이 *조작불가* 인 이유) ──
def test_no_posthoc_scoring_prediction_missing():
    with pytest.raises(PredictionMissing):
        judge(None, 0.5)                                  # 사전등록 없는 채점 금지


def test_prediction_locked_after_judged():
    with pytest.raises(PredictionLocked):
        check_registration(already_judged=True)           # 채점 후 재등록/변경 금지


def test_tolerance_frozen_cannot_mutate():
    p = preregister('bolt')
    with pytest.raises(Exception):                        # frozen dataclass — 잠긴 공차 변경 불가
        p.baseline_value = 99.0


# ── 전체-ZDF 테스트의 핵심: 파이프라인 verdict vs 정답 ──
def test_pipeline_drift_detected():
    r = check_against_pipeline('bolt', 0.95, 'PASS')      # 정답 FAIL 인데 파이프라인 PASS
    assert r['ground_truth'] == 'FAIL' and r['pipeline'] == 'PASS' and r['match'] is False


def test_pipeline_match_when_correct():
    assert check_against_pipeline('bolt', 0.31, 'pass')['match'] is True   # 대소문자 무관


def test_run_demo_overall_fail_and_one_mismatch():
    out = run()
    assert out['overall_ground_truth'] == 'FAIL'          # 공차초과 feature 존재
    assert len(out['mismatches']) == 1                    # drift 1건 탐지
