"""Laudan conceptual problems — empirical balance와 분리된 개념 문제 계층.
# KG: span_lakatotree_S1_laudan_layer
"""

import pytest

from lakatos.quant.laudan import conceptual_problem_score, problem_balance


def test_conceptual_problem_score_counts_internal_and_external_problems():
    score = conceptual_problem_score(
        internal_inconsistency=2,
        external_conflict=1,
    )

    assert score == 3.0


def test_conceptual_problem_score_uses_explicit_policy_weights():
    score = conceptual_problem_score(
        internal_inconsistency=2,
        external_conflict=1,
        internal_weight=2.0,
        external_weight=3.0,
    )

    assert score == 7.0


def test_conceptual_problems_are_separate_from_empirical_problem_balance():
    empirical = problem_balance(closed=3, opened=1)
    conceptual = conceptual_problem_score(internal_inconsistency=3, external_conflict=0)

    assert empirical == 2
    assert conceptual == 3.0


def test_conceptual_problem_score_rejects_negative_counts_and_weights():
    with pytest.raises(ValueError, match="internal_inconsistency"):
        conceptual_problem_score(internal_inconsistency=-1, external_conflict=0)

    with pytest.raises(ValueError, match="external_weight"):
        conceptual_problem_score(
            internal_inconsistency=1,
            external_conflict=1,
            external_weight=-0.1,
        )

