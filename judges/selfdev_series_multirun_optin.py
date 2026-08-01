#!/usr/bin/env python3
"""series multi-run opt-in residual failures (lower better).

0 = default multi_run is OFF and multi_run=True N=3 path returns n=3 with mean/std.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lakatos.programme.multi_run import multi_run_collect  # noqa: E402


def measure() -> int:
    fail = 0
    d = multi_run_collect(lambda s: 1.0)
    if d["multi_run"] is not False or d["n"] != 1:
        fail += 1
    m = multi_run_collect(lambda s: float(s * 0), multi_run=True, n=3)
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
