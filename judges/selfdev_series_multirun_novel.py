#!/usr/bin/env python3
"""Novel: multi_run module + tests present (higher, thr 1)."""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def measure() -> int:
    mod = ROOT / "lakatos" / "programme" / "multi_run.py"
    test = ROOT / "tests" / "test_multi_run_optin_20260801.py"
    return 1 if mod.is_file() and test.is_file() else 0


def main() -> None:
    sealed = sys.argv[1] if len(sys.argv) > 1 else ""
    if sealed:
        print(f"metric={int(json.load(open(sealed, encoding='utf-8'))['metric'])}")
        return
    print(f"metric={measure()}")


if __name__ == "__main__":
    main()
