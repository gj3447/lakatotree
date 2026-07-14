"""Acceptance checks for precise, blocking-class Kusari critiques."""
from __future__ import annotations

import pytest

from lakatos.verdict.kusari import REQUIRED_FIELDS, TARGET_AXES, lint_checklist, lint_critique


def _critique(**overrides) -> dict:
    item = {
        "target_artifact": "server/read_models.py:compute_tree_metrics",
        "failure_mode": "canonical path silently collapses",
        "expected_observable": "path_sources_matched >= 1",
        "blocking_verdict": "blocked",
        "algorithm": "force_of_row provenance classification",
    }
    item.update(overrides)
    return item


def test_non_mapping_critique_is_invalid():
    verdict = lint_critique("vague")

    assert verdict.valid is False
    assert verdict.problems == ("<item>",)


@pytest.mark.parametrize("field", REQUIRED_FIELDS)
def test_every_required_field_rejects_blank_values(field):
    item = _critique()
    item[field] = " "

    verdict = lint_critique(item)

    assert verdict.valid is False
    assert field in verdict.problems


@pytest.mark.parametrize("axis", TARGET_AXES)
def test_each_specific_target_axis_is_independently_sufficient(axis):
    item = _critique()
    item.pop("algorithm")
    item[axis] = "named target"

    verdict = lint_critique(item)

    assert verdict.valid is True
    assert verdict.problems == ()


def test_vague_critique_without_target_axis_is_invalid():
    item = _critique()
    item.pop("algorithm")

    verdict = lint_critique(item)

    assert verdict.valid is False
    assert "target_specificity" in verdict.problems


def test_non_blocking_verdict_cannot_masquerade_as_critique():
    verdict = lint_critique(_critique(blocking_verdict="PASS"))

    assert verdict.valid is False
    assert "blocking_verdict:non-blocking" in verdict.problems


def test_blocking_verdict_comparison_is_case_insensitive():
    assert lint_critique(_critique(blocking_verdict="BLOCKED")).valid is True


@pytest.mark.parametrize("items", [None, []])
def test_empty_or_non_list_checklist_is_invalid(items):
    verdict = lint_checklist(items)

    assert verdict.valid is False
    assert verdict.problems == ("<empty>",)


def test_all_valid_checklist_passes():
    assert lint_checklist([_critique(), _critique(threshold="0.05")]).valid is True


def test_one_invalid_item_blocks_the_whole_checklist_with_index():
    verdict = lint_checklist([_critique(), {}])

    assert verdict.valid is False
    assert any(problem.startswith("item[1]:") for problem in verdict.problems)
