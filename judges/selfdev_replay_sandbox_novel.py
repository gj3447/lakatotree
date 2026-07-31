#!/usr/bin/env python3
"""Novel: measurement_lock module present (higher, thresh 1)."""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def measure() -> int:
    p = ROOT / "lakatos" / "measurement_lock.py"
    return 1 if p.is_file() and "MeasurementLock" in p.read_text(encoding="utf-8") else 0


def main() -> None:
    sealed = sys.argv[1] if len(sys.argv) > 1 else ""
    if sealed:
        print(f"metric={int(json.load(open(sealed, encoding='utf-8'))['metric'])}")
        return
    print(f"metric={measure()}")


if __name__ == "__main__":
    main()
