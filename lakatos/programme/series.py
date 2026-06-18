"""Programme-as-series diagnostic layer.

Lakatos appraises a research programme across a sequence of problem shifts, not
only by a single node. This module deliberately remains diagnostic-only: it can
describe pressure in a series, but it cannot promote or abandon a canonical
claim by itself.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable


DIAGNOSTIC_ONLY_AUTHORITY = "diagnostic_only"

PROGRESSIVE_VERDICTS = {"progressive"}
NONPROGRESSIVE_VERDICTS = {"partial", "equivalent", "rejected", "degenerating"}
OFF_AXIS_VERDICTS = {"different_programme", "withdrawn"}
KNOWN_VERDICTS = PROGRESSIVE_VERDICTS | NONPROGRESSIVE_VERDICTS | OFF_AXIS_VERDICTS


@dataclass(frozen=True)
class ProgrammeSeriesRecord:
    """One time-ordered step in a programme series diagnostic."""

    tag: str
    verdict: str
    problem_balance_delta: int = 0
    rival_anomaly: bool = False
    conceptual_problem_score: float = 0.0
    lifecycle_state: str | None = None

    def __post_init__(self) -> None:
        if not self.tag.strip():
            raise ValueError("tag must be non-empty")
        if self.verdict not in KNOWN_VERDICTS:
            raise ValueError(f"verdict must be one of {sorted(KNOWN_VERDICTS)}")
        if isinstance(self.problem_balance_delta, bool) or not isinstance(self.problem_balance_delta, int):
            raise ValueError("problem_balance_delta must be an integer")
        score = float(self.conceptual_problem_score)
        if not math.isfinite(score) or score < 0:
            raise ValueError("conceptual_problem_score must be a non-negative finite number")
        if self.lifecycle_state is not None and not self.lifecycle_state.strip():
            raise ValueError("lifecycle_state must be non-empty when provided")


@dataclass(frozen=True)
class ProgrammeSeriesAppraisal:
    """Diagnostic outcome for a programme series."""

    trend: str
    authority: str
    promotion_authority: bool
    steps: int
    progressive_count: int
    nonprogressive_count: int
    off_axis_count: int
    problem_balance_total: int
    rival_anomaly_count: int
    conceptual_problem_score: float
    lifecycle_states: tuple[str, ...]
    reasons: tuple[str, ...]


def programme_series_appraisal(
    records: Iterable[ProgrammeSeriesRecord],
    *,
    recent_window: int | None = None,
) -> ProgrammeSeriesAppraisal:
    """Summarize path-level pressure without changing verdict authority."""

    rows = tuple(records)
    if recent_window is not None:
        if isinstance(recent_window, bool) or not isinstance(recent_window, int) or recent_window <= 0:
            raise ValueError("recent_window must be a positive integer")
        rows = rows[-recent_window:]

    if not rows:
        return _appraisal(
            "insufficient",
            rows,
            (),
            reasons=("no programme-series records",),
        )

    in_axis = tuple(r for r in rows if r.verdict not in OFF_AXIS_VERDICTS)
    if not in_axis:
        return _appraisal(
            "off_axis",
            rows,
            in_axis,
            reasons=("all records are programme-identity/off-axis events",),
        )

    progressive_count = sum(1 for r in in_axis if r.verdict in PROGRESSIVE_VERDICTS)
    nonprogressive_count = sum(1 for r in in_axis if r.verdict in NONPROGRESSIVE_VERDICTS)
    problem_balance_total = sum(r.problem_balance_delta for r in in_axis)
    rival_anomaly_count = sum(1 for r in in_axis if r.rival_anomaly)
    conceptual_problem_score = math.fsum(r.conceptual_problem_score for r in in_axis)

    reasons: list[str] = []
    if problem_balance_total < 0:
        reasons.append(f"problem_balance_total={problem_balance_total}")
    if rival_anomaly_count:
        reasons.append(f"rival_anomalies={rival_anomaly_count}")
    if conceptual_problem_score > 0:
        reasons.append(f"conceptual_problem_score={conceptual_problem_score:g}")

    if (
        progressive_count > nonprogressive_count
        and problem_balance_total >= 0
        and rival_anomaly_count == 0
        and conceptual_problem_score == 0
    ):
        trend = "progressive"
        reasons.append("progressive majority without problem/rival/conceptual pressure")
    elif (
        nonprogressive_count > 0
        and nonprogressive_count >= progressive_count
        and (problem_balance_total < 0 or rival_anomaly_count > 0 or conceptual_problem_score > 0)
    ):
        trend = "degenerating"
        reasons.append("nonprogressive sequence with diagnostic pressure")
    else:
        trend = "mixed"
        if not reasons:
            reasons.append("mixed or weak series evidence")

    return _appraisal(trend, rows, in_axis, reasons=tuple(reasons))


def _appraisal(
    trend: str,
    rows: tuple[ProgrammeSeriesRecord, ...],
    in_axis: tuple[ProgrammeSeriesRecord, ...],
    *,
    reasons: tuple[str, ...],
) -> ProgrammeSeriesAppraisal:
    return ProgrammeSeriesAppraisal(
        trend=trend,
        authority=DIAGNOSTIC_ONLY_AUTHORITY,
        promotion_authority=False,
        steps=len(rows),
        progressive_count=sum(1 for r in in_axis if r.verdict in PROGRESSIVE_VERDICTS),
        nonprogressive_count=sum(1 for r in in_axis if r.verdict in NONPROGRESSIVE_VERDICTS),
        off_axis_count=sum(1 for r in rows if r.verdict in OFF_AXIS_VERDICTS),
        problem_balance_total=sum(r.problem_balance_delta for r in in_axis),
        rival_anomaly_count=sum(1 for r in in_axis if r.rival_anomaly),
        conceptual_problem_score=math.fsum(r.conceptual_problem_score for r in in_axis),
        lifecycle_states=tuple(r.lifecycle_state for r in in_axis if r.lifecycle_state),
        reasons=reasons,
    )
