"""lakatos.programme — THEORY.md 계층 (engine reorg 2026-06-18)."""

from lakatos.programme.series import ProgrammeSeriesAppraisal, ProgrammeSeriesRecord, programme_series_appraisal
from lakatos.programme.tradition import (
    ResearchTradition,
    TraditionAppraisal,
    TraditionCommitment,
    TraditionRevision,
    appraise_tradition_revision,
)

__all__ = [
    "ProgrammeSeriesAppraisal",
    "ProgrammeSeriesRecord",
    "programme_series_appraisal",
    "ResearchTradition",
    "TraditionAppraisal",
    "TraditionCommitment",
    "TraditionRevision",
    "appraise_tradition_revision",
]
