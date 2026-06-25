"""rerunnable acceptance check — BPC.ZHeightCadSurfaceFailureMode (Longinus 바인딩 PIERCE).

준거: docs/BPC_Z_HEIGHT_CAD_SURFACE_PROM_20260624.md "Required BPC Z Guards".
claim: good CAD registration 이 global residual·CAD membership·measured contact 를 *뭉개면* wrong feature z 를
       숨길 수 있다. acceptance: rigid residual / per-feature z residual / frame-sign audit 를 *분리*한 production
       결과 증거. 이 테스트가 그 세 분리를 fail-closed 로 강제하고, 실제 BPC 증거로 "registration green인데 z 3-4mm"
       (LGN-BPC-Z-003)를 재현한다(외부 증거 부재 시 hermetic skip — clean clone 재현성 보존).
# KG: CT_LakatoTree_3D_PROM_LonginusReview_20260624 / BPC.ZHeightCadSurfaceFailureMode
"""
from __future__ import annotations

import json
import os

import pytest

from lakatos.verdict.z_height import REQUIRED_FIELDS, ZHeightVerdict, judge_z_height

_BPC = "/data/kjra/PROJECT/3D/BPC_ICP_SPEC"
_FEATURE_Z_OFFSET = f"{_BPC}/out/feature_z_offset_per_hole.json"


def _zresult(**over) -> dict:
    """세 surface 를 분리한 잘 형성된 Z 결과(기본=z 오차 작음·registration green)."""
    base = {
        "measurand": "plate_surface_z",
        "datum_frame": "frozen_view_frame",
        "intended_cad_layer": "panel_surface",
        "candidate_layers": [                          # frame/sign audit: 경쟁 후보 ≥2
            {"name": "panel_surface", "cad_z_mm": -232.0, "distance_mm": 3.7, "z_frame_state": "NORMAL"},
            {"name": "washer_top", "cad_z_mm": -200.2, "distance_mm": 0.4, "z_frame_state": "SHIFTED_22MM"},
        ],
        "selected_layer": "panel_surface",
        "layer_selection_rule": "feature_specific_prior",
        "z_signed_error_mm": 0.2,                      # per-feature z residual
        "registration_residual_mm": 0.5,              # rigid residual (별도)
        "uncertainty": {"u_c_mm": 0.2, "U_k2_mm": 0.4},
        "decision_rule": "guard_band",
        "conformity_state": "pass",
    }
    base.update(over)
    return base


# ── 완비 + z 오차 작음 → pass candidate ──────────────────────────────────────
def test_complete_small_z_error_is_pass_candidate():
    v = judge_z_height(_zresult())
    assert isinstance(v, ZHeightVerdict)
    assert v.verdict == "Z-PASS-CANDIDATE"
    assert v.z_certified_by_registration is True
    assert v.missing == ()


# ── 핵심(LGN-BPC-Z-003): registration green인데 z 3-4mm → Z-NOT-CERTIFIED ──────
def test_registration_green_but_large_z_is_not_certified():
    v = judge_z_height(_zresult(z_signed_error_mm=3.83, registration_residual_mm=0.5))
    assert v.verdict == "Z-NOT-CERTIFIED"
    assert v.z_certified_by_registration is False
    assert "registration" in v.reason


# ── 세 분리 결여 → fail-closed ────────────────────────────────────────────────
@pytest.mark.parametrize("field", REQUIRED_FIELDS)
def test_missing_required_field_blocks(field):
    r = _zresult()
    del r[field]
    v = judge_z_height(r)
    assert v.verdict == "BLOCKED", f"{field} 누락인데 BLOCKED 아님: {v}"
    assert field in v.missing


def test_single_candidate_layer_is_collapsed_frame_audit_blocked():
    """frame/sign audit 가 단일 후보로 뭉개지면(경쟁 프레임 미제시) BLOCKED."""
    v = judge_z_height(_zresult(candidate_layers=[
        {"name": "panel_surface", "cad_z_mm": -232.0, "distance_mm": 3.7}]))
    assert v.verdict == "BLOCKED"
    assert "candidate_layers" in v.missing


def test_incomplete_uncertainty_blocks():
    assert judge_z_height(_zresult(uncertainty={"u_c_mm": 0.2})).verdict == "BLOCKED"


# ── near-band → indeterminate ────────────────────────────────────────────────
def test_near_band_is_indeterminate():
    # zerr 0.8 > U 0.4 (pass 아님) 이나 reg+U=0.9 >= 0.8 (not-certified 아님) → indeterminate
    v = judge_z_height(_zresult(z_signed_error_mm=0.8, registration_residual_mm=0.5))
    assert v.verdict == "Z-INDETERMINATE"


def test_non_dict_is_blocked_not_crash():
    assert judge_z_height(None).verdict == "BLOCKED"
    assert judge_z_height("nope").verdict == "BLOCKED"


# ── 실 production 증거 검증(외부 디스크 부재 시 hermetic skip) ────────────────
@pytest.mark.skipif(not os.path.exists(_FEATURE_Z_OFFSET),
                    reason="BPC production evidence not on disk (clean clone) — hermetic skip")
def test_real_feature_z_offset_exposes_hidden_z_error():
    """실 BPC feature_z_offset_per_hole.json: registration green인데 per-feature signed z 가 multi-mm
    → 게이트가 Z-NOT-CERTIFIED 로 split(LGN-BPC-Z-003 재현)."""
    rows = json.load(open(_FEATURE_Z_OFFSET, encoding="utf-8"))["v17_vgicp"]["per_hole_summary"]
    plate = [r for r in rows if r["group"] == "plate_standard"]
    assert plate, "plate_standard holes 가 실 증거에 있어야"
    worst = max(plate, key=lambda r: abs(r["signed_dist_mm"]))
    assert abs(worst["signed_dist_mm"]) > 1.0, ("plate signed z 가 multi-mm 여야(숨은 오차)", worst)
    v = judge_z_height(_zresult(z_signed_error_mm=worst["signed_dist_mm"], registration_residual_mm=0.5))
    assert v.verdict == "Z-NOT-CERTIFIED", (worst, v)
    assert v.z_certified_by_registration is False
