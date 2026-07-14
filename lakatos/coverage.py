"""Fail-closed coverage declarations shared by write and read paths.

An empty backlog is absence of a known omission, not evidence that a scope was
exhaustively inspected.  Only an explicit declaration with a non-empty scope
statement can earn ``exhaustive``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal


CoverageStatus = Literal["unknown", "partial", "exhaustive"]
COVERAGE_STATUSES = frozenset({"unknown", "partial", "exhaustive"})


def resolve_coverage_status(
    declared: object,
    *,
    statement: str = "",
    backlog: Sequence[str] = (),
) -> CoverageStatus:
    """Return the strongest status justified by the stored evidence.

    Corrupt or legacy declarations fail closed.  A known backlog is structural
    evidence of partial coverage and therefore overrides every declaration.
    """
    if backlog:
        return "partial"
    if declared == "partial":
        return "partial"
    if declared == "exhaustive" and statement.strip():
        return "exhaustive"
    return "unknown"


def validate_coverage_declaration(
    declared: object,
    *,
    statement: str = "",
    backlog: Sequence[str] = (),
) -> CoverageStatus:
    """Validate a write declaration, then return its canonical stored status."""
    if declared not in COVERAGE_STATUSES:
        raise ValueError(
            "coverage_status must be one of unknown, partial, exhaustive"
        )
    if declared == "exhaustive" and backlog:
        raise ValueError(
            "coverage_backlog must be empty when coverage_status is exhaustive"
        )
    if declared == "exhaustive" and not statement.strip():
        raise ValueError(
            "coverage_statement must name the inspected scope when coverage_status is exhaustive"
        )
    return resolve_coverage_status(declared, statement=statement, backlog=backlog)
