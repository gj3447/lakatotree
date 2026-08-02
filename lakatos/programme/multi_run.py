"""Opt-in multi-run measurement helper (default OFF).

q-selfdev-series-multirun-optin: single-run remains default; callers pass multi_run=True
to collect N independent run values (mean/std). Pure function — no global config flip.
"""
from __future__ import annotations

import math
import statistics
from collections.abc import Callable
from typing import Any


def multi_run_collect(
    run_fn: Callable[[int], float],
    *,
    multi_run: bool = False,
    n: int = 3,
) -> dict[str, Any]:
    """Run ``run_fn(seed)`` once (default) or N times when multi_run=True.

    ``run_fn`` receives seed index 0..n-1. Returns multi_run flag, n, values, mean, std.
    Default multi_run=False preserves single-run behaviour (n=1, std=0).
    """
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise ValueError("n must be a positive integer")
    if not multi_run:
        v = float(run_fn(0))
        return dict(multi_run=False, n=1, values=[v], mean=v, std=0.0)
    values = [float(run_fn(i)) for i in range(n)]
    mean = statistics.fmean(values)
    std = statistics.pstdev(values) if len(values) > 1 else 0.0
    if not math.isfinite(mean) or not math.isfinite(std):
        raise ValueError("run_fn produced non-finite metrics")
    return dict(multi_run=True, n=n, values=values, mean=mean, std=std)
