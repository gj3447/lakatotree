"""Programme-as-series diagnostic OOPTDD receipts."""

import pytest

from lakatos.programme.series import (
    DIAGNOSTIC_ONLY_AUTHORITY,
    ProgrammeSeriesRecord,
    programme_series_appraisal,
)


def test_series_appraisal_marks_sustained_progress_without_pressure():
    appraisal = programme_series_appraisal(
        [
            ProgrammeSeriesRecord("n1", "progressive", problem_balance_delta=1),
            ProgrammeSeriesRecord("n2", "progressive", problem_balance_delta=0),
        ]
    )

    assert appraisal.trend == "progressive"
    assert appraisal.authority == DIAGNOSTIC_ONLY_AUTHORITY
    assert appraisal.promotion_authority is False
    assert appraisal.progressive_count == 2
    assert appraisal.problem_balance_total == 1


def test_series_appraisal_marks_degenerating_series_with_rival_pressure():
    appraisal = programme_series_appraisal(
        [
            ProgrammeSeriesRecord("n1", "partial", problem_balance_delta=-1),
            ProgrammeSeriesRecord("n2", "rejected", problem_balance_delta=-1, rival_anomaly=True),
            ProgrammeSeriesRecord("n3", "equivalent", problem_balance_delta=0),
        ]
    )

    assert appraisal.trend == "degenerating"
    assert appraisal.nonprogressive_count == 3
    assert appraisal.rival_anomaly_count == 1
    assert any("rival" in reason for reason in appraisal.reasons)


def test_different_programme_is_off_axis_not_degenerating_pressure():
    appraisal = programme_series_appraisal(
        [
            ProgrammeSeriesRecord("fork", "different_programme", problem_balance_delta=-5),
        ]
    )

    assert appraisal.trend == "off_axis"
    assert appraisal.off_axis_count == 1
    assert appraisal.nonprogressive_count == 0
    assert appraisal.problem_balance_total == 0


def test_conceptual_pressure_stays_diagnostic_only():
    appraisal = programme_series_appraisal(
        [
            ProgrammeSeriesRecord("n1", "progressive"),
            ProgrammeSeriesRecord("n2", "progressive", conceptual_problem_score=2.0),
        ]
    )

    assert appraisal.trend == "mixed"
    assert appraisal.conceptual_problem_score == 2.0
    assert appraisal.promotion_authority is False
    assert any("conceptual" in reason for reason in appraisal.reasons)


def test_series_record_rejects_empty_tag_unknown_verdict_and_bad_scores():
    with pytest.raises(ValueError, match="tag"):
        ProgrammeSeriesRecord("", "progressive")
    with pytest.raises(ValueError, match="verdict"):
        ProgrammeSeriesRecord("n1", "magic")
    with pytest.raises(ValueError, match="conceptual_problem_score"):
        ProgrammeSeriesRecord("n1", "progressive", conceptual_problem_score=-0.1)


def test_recent_window_is_positive_and_uses_latest_steps():
    appraisal = programme_series_appraisal(
        [
            ProgrammeSeriesRecord("n1", "progressive"),
            ProgrammeSeriesRecord("n2", "rejected", rival_anomaly=True),
        ],
        recent_window=1,
    )

    assert appraisal.trend == "degenerating"
    assert appraisal.steps == 1
    assert appraisal.progressive_count == 0

    with pytest.raises(ValueError, match="recent_window"):
        programme_series_appraisal([], recent_window=0)
