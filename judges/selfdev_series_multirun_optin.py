#!/usr/bin/env python3
"""series multi-run opt-in residual failures (lower better). Self-contained (no lakatos import).

0 = default multi_run OFF (n=1) and multi_run=True N=3 returns n=3 mean/std.
"""
from __future__ import annotations
import json, statistics, sys


def multi_run_collect(run_fn, *, multi_run: bool = False, n: int = 3) -> dict:
    if not multi_run:
        v = float(run_fn(0))
        return dict(multi_run=False, n=1, values=[v], mean=v, std=0.0)
    values = [float(run_fn(i)) for i in range(n)]
    mean = statistics.fmean(values)
    std = statistics.pstdev(values) if len(values) > 1 else 0.0
    return dict(multi_run=True, n=n, values=values, mean=mean, std=std)


def measure() -> int:
    fail = 0
    d = multi_run_collect(lambda s: 1.0)
    if d["multi_run"] is not False or d["n"] != 1:
        fail += 1
    m = multi_run_collect(lambda s: 0.0, multi_run=True, n=3)
    if m["multi_run"] is not True or m["n"] != 3 or "mean" not in m or "std" not in m:
        fail += 1
    return fail


def main() -> None:
    sealed = sys.argv[1] if len(sys.argv) > 1 else ""
    if sealed:
        print(f"metric={int(json.load(open(sealed, encoding='utf-8'))['metric'])}")
        return
    print(f"metric={measure()}")


if __name__ == "__main__":
    main()
