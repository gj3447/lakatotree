"""Acceptance checks for the fail-closed industrial dimension gate."""
from __future__ import annotations

import copy

import pytest

from lakatos.verdict.industrial import REQUIRED_FIELDS, judge_dimension


def _result(**overrides) -> dict:
    result = {
        "measurand": "hole_diameter",
        "cad_nominal": {"value": 10.0},
        "measured": {"value": 10.2},
        "deviation": {"value": 0.2},
        "tolerance": {"upper": 1.0},
        "uncertainty": {"U_k2": 0.1},
        "decision_rule": "guard_band",
        # The gate must recompute this instead of trusting the producer.
        "conformity_state": "fail",
        "gauge": {"status": "acceptable"},
        "independent_truth": "traceable_reference",
        "negative_controls": ["known_bad_part"],
    }
    result.update(overrides)
    return result


def test_non_mapping_result_is_blocked():
    verdict = judge_dimension(None)

    assert verdict.verdict == "BLOCKED"
    assert verdict.missing == ("<result>",)
    assert verdict.conformity == "indeterminate"


@pytest.mark.parametrize("field", REQUIRED_FIELDS)
def test_every_required_field_fails_closed_when_absent(field):
    result = _result()
    del result[field]

    verdict = judge_dimension(result)

    assert verdict.verdict == "BLOCKED"
    assert field in verdict.missing


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("measurand", " "),
        ("cad_nominal", 10.0),
        ("measured", {}),
        ("uncertainty", None),
        ("negative_controls", []),
    ],
)
def test_malformed_load_bearing_fields_are_blocked(field, value):
    result = copy.deepcopy(_result())
    result[field] = value

    verdict = judge_dimension(result)

    assert verdict.verdict == "BLOCKED"
    assert field in verdict.missing


@pytest.mark.parametrize(
    ("deviation", "gauge", "expected_conformity", "expected_verdict"),
    [
        (0.2, "acceptable", "pass", "PASS-PRODUCTION-CANDIDATE"),
        (0.2, "weak", "pass", "CONDITIONAL"),
        (0.95, "acceptable", "indeterminate", "CONDITIONAL"),
        (1.2, "acceptable", "fail", "NO-GO"),
    ],
)
def test_gate_recomputes_conformity_and_applies_guard_band_and_gauge_cap(
    deviation, gauge, expected_conformity, expected_verdict
):
    result = _result(deviation={"value": deviation}, gauge={"status": gauge})

    verdict = judge_dimension(result)

    assert verdict.conformity == expected_conformity
    assert verdict.verdict == expected_verdict
    assert verdict.missing == ()
