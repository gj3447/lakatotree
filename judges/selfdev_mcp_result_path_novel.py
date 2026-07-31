#!/usr/bin/env python3
"""Novel axis: certificate_five_gates_certified infrastructure (higher, thresh 1.0).

Counts whether certify.GATES defines the five+ gate names required for a certificate
surface (not a live node cert — structural readiness of the five-gate AND).
metric=1 if preregistered/reproducible/stands/calibrated/grounded all present.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEED = ("preregistered", "reproducible", "stands", "calibrated", "grounded")


def measure() -> int:
    text = (ROOT / "lakatos" / "verdict" / "certify.py").read_text(encoding="utf-8")
    if "GATES" not in text:
        return 0
    return 1 if all(g in text for g in NEED) else 0


def main() -> None:
    sealed = sys.argv[1] if len(sys.argv) > 1 else ""
    if sealed:
        print(f"metric={int(json.load(open(sealed, encoding='utf-8'))['metric'])}")
        return
    print(f"metric={measure()}")


if __name__ == "__main__":
    main()
