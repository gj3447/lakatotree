"""rerunnable negative controls — consumer_b.ZLayerNegativeControlsExecuted.

준거: docs/BPC_Z_HEIGHT_CAD_SURFACE_PROM_20260624.md "Required Negative Controls".
각 음성대조(known-bad 입력)는 *expected-fail* 을 내야 한다 — 통과(Z-PASS-CANDIDATE)가 나오면
게이트가 그 실패양식을 못 잡는 것이다. 여기서는 judge_z_height 게이트의 *판별력*을 6개 대조로 강제한다
(2개는 실 consumer_b 증거에 앵커: wrong-layer=feature_z_offset, mirrored-frame=dual_z_frame_gate).
※ 이 테스트는 게이트-수준 판별이다. consumer_a *파이프라인*에 perturbed scan 을 먹이는 전수 실행은 더 깊은
   frontier 로 남는다(README/doc 에 명시). 그래도 "선언만"이 아니라 실행·기록되는 receipt 다.
# KG: CT_LakatoTree_3D_PROM_LonginusReview_20260624 / consumer_b.ZLayerNegativeControlsExecuted
"""
from __future__ import annotations

import json
import os

import pytest

from lakatos.verdict.z_height import judge_z_height

_BPC = "<WORKSPACE>/PROJECT/3D/BPC_ICP_SPEC"
_FEATURE_Z_OFFSET = f"{_BPC}/out/feature_z_offset_per_hole.json"


def _zresult(**over) -> dict:
    base = {
        "measurand": "plate_surface_z",
        "datum_frame": "frozen_view_frame",
        "intended_cad_layer": "panel_surface",
        "candidate_layers": [
            {"name": "panel_surface", "cad_z_mm": -232.0, "distance_mm": 3.7, "z_frame_state": "NORMAL"},
            {"name": "washer_top", "cad_z_mm": -200.2, "distance_mm": 0.4, "z_frame_state": "NORMAL"},
        ],
        "selected_layer": "panel_surface",
        "layer_selection_rule": "feature_specific_prior",
        "z_signed_error_mm": 0.2,
        "registration_residual_mm": 0.5,
        "uncertainty": {"u_c_mm": 0.2, "U_k2_mm": 0.4},
        "decision_rule": "guard_band",
        "conformity_state": "pass",
    }
    base.update(over)
    return base


# (name, perturbed result, expected verdict). expected 는 전부 *non-pass*(expected-fail).
_CONTROLS = [
    ("wrong_z_layer",
     _zresult(selected_layer="panel_surface", z_signed_error_mm=3.83, registration_residual_mm=0.5),
     "Z-NOT-CERTIFIED"),
    ("mirrored_frame_wrong_axis",   # dual_z_frame_gate_v1: v15_xmirror panel_z -230.30 vs aruco_v3 -208.50 = 21.8mm
     _zresult(selected_layer="v15_xmirror", z_signed_error_mm=21.8, registration_residual_mm=0.5,
              candidate_layers=[
                  {"name": "aruco_v3", "cad_z_mm": -208.50, "distance_mm": 0.4, "z_frame_state": "NORMAL"},
                  {"name": "v15_xmirror", "cad_z_mm": -230.30, "distance_mm": 22.0, "z_frame_state": "SHIFTED_22MM"}]),
     "Z-NOT-CERTIFIED"),
    ("free_icp_fallback",           # collapse → garbage z, large registration residual
     _zresult(layer_selection_rule="free_icp_global", z_signed_error_mm=6.0, registration_residual_mm=4.05),
     "Z-NOT-CERTIFIED"),
    ("panel_only_fit",              # 단일 후보로 뭉갬 → frame/sign audit 부재
     _zresult(candidate_layers=[{"name": "panel_surface", "cad_z_mm": -232.0, "distance_mm": 3.7}]),
     "BLOCKED"),
    ("nearest_triangle_only",       # feature-specific 아님 + nearest-wrong layer → z 오차
     _zresult(layer_selection_rule="nearest_cad_triangle", z_signed_error_mm=1.5, registration_residual_mm=0.5),
     "Z-NOT-CERTIFIED"),
    ("shuffled_feature_ids",        # 잘못된 nominal 대조 → 큰 z 오차
     _zresult(z_signed_error_mm=5.0, registration_residual_mm=0.5),
     "Z-NOT-CERTIFIED"),
]


@pytest.mark.parametrize("name, result, expected", _CONTROLS, ids=[c[0] for c in _CONTROLS])
def test_negative_control_produces_expected_fail(name, result, expected):
    v = judge_z_height(result)
    assert v.verdict != "Z-PASS-CANDIDATE", f"음성대조 {name} 가 통과해버림(게이트 판별 실패): {v}"
    assert v.verdict == expected, f"{name}: expected {expected}, got {v.verdict} ({v.reason})"


def test_all_six_controls_present():
    """6개 음성대조가 전부 정의·실행되는지(누락=묵시적 약화 금지)."""
    assert len(_CONTROLS) == 6
    assert {c[0] for c in _CONTROLS} == {
        "wrong_z_layer", "mirrored_frame_wrong_axis", "free_icp_fallback",
        "panel_only_fit", "nearest_triangle_only", "shuffled_feature_ids"}


def test_baseline_good_result_passes_so_controls_are_meaningful():
    """음성대조가 의미 있으려면 baseline(정상)은 통과해야 한다(전부 fail 나면 무의미)."""
    assert judge_z_height(_zresult()).verdict == "Z-PASS-CANDIDATE"


@pytest.mark.skipif(not os.path.exists(_FEATURE_Z_OFFSET),
                    reason="consumer_b production evidence not on disk (clean clone) — hermetic skip")
def test_wrong_layer_control_anchored_to_real_evidence():
    """wrong-layer 대조를 실 feature_z_offset 의 plate signed-z(multi-mm)로 앵커."""
    rows = json.load(open(_FEATURE_Z_OFFSET, encoding="utf-8"))["v17_vgicp"]["per_hole_summary"]
    worst = max((r for r in rows if r["group"] == "plate_standard"), key=lambda r: abs(r["signed_dist_mm"]))
    v = judge_z_height(_zresult(z_signed_error_mm=worst["signed_dist_mm"], registration_residual_mm=0.5))
    assert v.verdict == "Z-NOT-CERTIFIED", (worst, v)
