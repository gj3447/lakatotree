"""Acceptance checks for separating rigid registration from feature Z evidence."""
from __future__ import annotations

import copy

import pytest

from lakatos.verdict.z_height import REQUIRED_FIELDS, judge_z_height


def _result(**overrides) -> dict:
    result = {
        "measurand": "plate_surface_z",
        "datum_frame": "frozen_view_frame",
        "intended_cad_layer": "panel_surface",
        "candidate_layers": ["panel_surface", "washer_top"],
        "selected_layer": "panel_surface",
        "layer_selection_rule": "feature_specific_prior",
        "z_signed_error_mm": 0.2,
        "registration_residual_mm": 0.5,
        "uncertainty": {"U_k2_mm": 0.4},
        "decision_rule": "guard_band",
        "conformity_state": "pass",
    }
    result.update(overrides)
    return result


def test_non_mapping_result_is_blocked():
    verdict = judge_z_height(None)

    assert verdict.verdict == "BLOCKED"
    assert verdict.missing == ("<result>",)
    assert verdict.z_certified_by_registration is False


@pytest.mark.parametrize("field", REQUIRED_FIELDS)
def test_every_required_surface_fails_closed_when_absent(field):
    result = _result()
    del result[field]

    verdict = judge_z_height(result)

    assert verdict.verdict == "BLOCKED"
    assert field in verdict.missing


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("measurand", None),
        ("datum_frame", " "),
        ("candidate_layers", ["panel_surface"]),
        ("uncertainty", {}),
        ("z_signed_error_mm", "0.2"),
    ],
)
def test_malformed_load_bearing_surface_is_blocked(field, value):
    result = copy.deepcopy(_result())
    result[field] = value

    verdict = judge_z_height(result)

    assert verdict.verdict == "BLOCKED"
    assert field in verdict.missing


def test_z_outside_uncertainty_but_inside_registration_band_is_indeterminate():
    verdict = judge_z_height(_result(z_signed_error_mm=0.6))

    assert verdict.verdict == "Z-INDETERMINATE"
    assert verdict.z_certified_by_registration is False
