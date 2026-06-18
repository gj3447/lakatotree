"""Laudan comparative anomaly — rival-relative problem solving.
# KG: span_lakatotree_S1_laudan_layer
"""

import pytest

from lakatos.quant.laudan import RivalProblemRecord, rival_relative_anomaly


def test_rival_relative_anomaly_when_target_unsolved_and_rival_solved():
    records = (
        RivalProblemRecord(programme="target", problem="p", solved=False),
        RivalProblemRecord(programme="rival", problem="p", solved=True),
    )

    assert rival_relative_anomaly("target", "p", records)


def test_rival_relative_anomaly_false_when_problem_unsolved_by_everyone():
    records = (
        RivalProblemRecord(programme="target", problem="p", solved=False),
        RivalProblemRecord(programme="rival", problem="p", solved=False),
    )

    assert not rival_relative_anomaly("target", "p", records)


def test_rival_relative_anomaly_false_when_target_already_solved():
    records = (
        RivalProblemRecord(programme="target", problem="p", solved=True),
        RivalProblemRecord(programme="rival", problem="p", solved=True),
    )

    assert not rival_relative_anomaly("target", "p", records)


def test_rival_relative_anomaly_ignores_other_problems_and_low_quality_solutions():
    records = (
        RivalProblemRecord(programme="target", problem="p", solved=False),
        RivalProblemRecord(programme="rival", problem="other", solved=True),
        RivalProblemRecord(programme="weak-rival", problem="p", solved=True, explanation_quality=0.2),
    )

    assert not rival_relative_anomaly("target", "p", records, min_rival_quality=0.5)


def test_rival_problem_record_rejects_empty_names_and_bad_quality():
    with pytest.raises(ValueError, match="programme"):
        RivalProblemRecord(programme="", problem="p", solved=True)

    with pytest.raises(ValueError, match="explanation_quality"):
        RivalProblemRecord(programme="rival", problem="p", solved=True, explanation_quality=-0.1)

