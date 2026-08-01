"""multi_run opt-in helper — default OFF + CycleIn wire validation."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from lakatos.programme.multi_run import multi_run_collect
from server.contexts.tree.schemas import CycleIn


def test_default_single_run():
    out = multi_run_collect(lambda s: 10.0 + s)
    assert out["multi_run"] is False
    assert out["n"] == 1
    assert out["values"] == [10.0]
    assert out["std"] == 0.0


def test_multi_run_n3_mean_std():
    out = multi_run_collect(lambda s: float(s), multi_run=True, n=3)
    assert out["multi_run"] is True
    assert out["n"] == 3
    assert out["values"] == [0.0, 1.0, 2.0]
    assert out["mean"] == 1.0
    assert out["std"] > 0


def test_cyclein_multi_run_default_off():
    c = CycleIn(tag="t", metric_name="m", baseline=1.0, measured=0.5)
    assert c.multi_run is False
    assert c.multi_run_values == []


def test_cyclein_multi_run_values_accepted():
    c = CycleIn(
        tag="t", metric_name="m", baseline=1.0, measured=1.0,
        multi_run=True, multi_run_values=[0.0, 1.0, 2.0],
    )
    assert c.multi_run is True
    assert len(c.multi_run_values) == 3
