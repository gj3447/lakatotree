"""multi_run opt-in helper — default OFF."""
from __future__ import annotations

from lakatos.programme.multi_run import multi_run_collect


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
