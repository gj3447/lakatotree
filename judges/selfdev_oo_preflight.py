#!/usr/bin/env python3
"""OO live preflight residual failures (lower better).

Counts missing secrets + offline test failures. Does NOT claim LIVE_READBACK_WARN.
0 = offline OO tests green AND (optional) secrets present — secrets usually missing → >0.
"""
from __future__ import annotations
import json, os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def measure() -> int:
    fail = 0
    # offline unit wing
    try:
        p = subprocess.run(
            [sys.executable, "-m", "pytest",
             "tests/test_oo_sink.py", "tests/test_oo_verify.py", "-q", "--tb=no"],
            cwd=ROOT, capture_output=True, text=True, timeout=120,
        )
        if p.returncode != 0:
            fail += 1
    except Exception:
        fail += 1
    # secrets for live ship
    if not os.environ.get("OO_PASS") and not os.environ.get("OOPTDD_OO_PASSWORD"):
        fail += 1  # honest: live ship not available
    if not os.environ.get("OO_URL") and not os.environ.get("OOPTDD_OO_URL"):
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
