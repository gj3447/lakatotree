"""Compatibility facade for the quant-level programme-series diagnostic kernel.

The implementation lives in :mod:`lakatos.quant.programme_series` so lower
``quant`` code never imports the higher ``programme`` layer.  Existing public
imports remain stable through these exact-object re-exports.
"""
from __future__ import annotations

from lakatos.quant.programme_series import (
    DIAGNOSTIC_ONLY_AUTHORITY,
    KNOWN_VERDICTS,
    NEUTRAL_VERDICTS,
    NONPROGRESSIVE_VERDICTS,
    OFF_AXIS_VERDICTS,
    PROGRESSIVE_VERDICTS,
    SERIES_KNOWN_VERDICTS,
    SERIES_NEUTRAL_VERDICTS,
    SERIES_NONPROGRESS_VERDICTS,
    SERIES_OFF_AXIS_VERDICTS,
    SERIES_PROGRESS_VERDICTS,
    ProgrammeSeriesAppraisal,
    ProgrammeSeriesRecord,
    programme_series_appraisal,
    series_from_path,
)

__all__ = [
    "DIAGNOSTIC_ONLY_AUTHORITY",
    "KNOWN_VERDICTS",
    "NEUTRAL_VERDICTS",
    "NONPROGRESSIVE_VERDICTS",
    "OFF_AXIS_VERDICTS",
    "PROGRESSIVE_VERDICTS",
    "SERIES_KNOWN_VERDICTS",
    "SERIES_NEUTRAL_VERDICTS",
    "SERIES_NONPROGRESS_VERDICTS",
    "SERIES_OFF_AXIS_VERDICTS",
    "SERIES_PROGRESS_VERDICTS",
    "ProgrammeSeriesAppraisal",
    "ProgrammeSeriesRecord",
    "programme_series_appraisal",
    "series_from_path",
]
