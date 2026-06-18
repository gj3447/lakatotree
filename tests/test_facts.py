"""Reusable fact-query evaluator (OQ5) — judges express expected facts as DATA, evaluated
by one runner, not a bespoke per-rule conditional grader (Kythe Souffle / Glean where)."""
from __future__ import annotations

import pytest

from lakatos.facts import FACT_PREDICATE_REGISTRY, FactQuery, evaluate, fact_predicate


def test_reusable_evaluator_exists():
    assert {"present", "field"} <= set(FACT_PREDICATE_REGISTRY)


def test_field_and_present_queries_as_data():
    rows = {"CUP": {"yolo_id": 1, "production": True},
            "LABEL": {"yolo_id": 3, "production": False}}
    qs = [
        FactQuery("present", "class:CUP", ("CUP",)),
        FactQuery("field", "class_id:CUP", ("CUP", "yolo_id", "==", 1)),
        FactQuery("field", "class_production:CUP", ("CUP", "production", "==", True)),
        FactQuery("present", "class:MISSING", ("MISSING",)),
    ]
    assert evaluate(rows, qs) == ["class:MISSING"]  # only the absent one fails


def test_missing_row_emits_one_label_not_per_field():
    # vacuous-pass-when-absent (matches the migrated judge's original `continue` behaviour)
    rows: dict = {}
    qs = [FactQuery("present", "class:X", ("X",)),
          FactQuery("field", "class_id:X", ("X", "yolo_id", "==", 1))]
    assert evaluate(rows, qs) == ["class:X"]


def test_contains_op_for_measurement_contract():
    rows = {"OUTER_HOLE": {"measurement_contract": "center_xy,radius"}}
    qs = [FactQuery("field", "hole_center_xy:OUTER_HOLE",
                    ("OUTER_HOLE", "measurement_contract", "contains", "center_xy"))]
    assert evaluate(rows, qs) == []


def test_duplicate_predicate_raises():
    with pytest.raises(ValueError):
        @fact_predicate("present")
        def _dup(rows, args):  # pragma: no cover
            return True


def test_unknown_predicate_raises():
    with pytest.raises(KeyError):
        evaluate({}, [FactQuery("nope", "x", ())])
