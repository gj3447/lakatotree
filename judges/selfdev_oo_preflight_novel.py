#!/usr/bin/env python3
"""Novel: offline OO tests exist and dual-gate coded (higher thr 1)."""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def measure() -> int:
    sink = (ROOT / "lakatos" / "io" / "oo_sink.py")
    if not sink.is_file():
        sink = ROOT / "lakatos" / "oo_sink.py"
    text = sink.read_text(encoding="utf-8") if sink.is_file() else ""
    tests = (ROOT / "tests" / "test_oo_sink.py").is_file()
    return 1 if tests and "OO_PASS" in text else 0


def main() -> None:
    sealed = sys.argv[1] if len(sys.argv) > 1 else ""
    if sealed:
        print(f"metric={int(json.load(open(sealed, encoding='utf-8'))['metric'])}")
        return
    print(f"metric={measure()}")


if __name__ == "__main__":
    main()
