#!/usr/bin/env python3
"""OO LIVE_LOOP residual failures (lower better).

0 = sealed live receipt with verify_ok + metric=0 (ship+positive readback).
Does not re-open network; L2 replay reads the receipt file only.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = [
    ROOT / "raw" / "selfdev_oo_live_ship_20260801.json",
    Path("/opt/lakatotree/raw/selfdev_oo_live_ship_20260801.json"),
]


def measure() -> int:
    for p in CANDIDATES:
        if not p.is_file():
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return 1
        if (
            d.get("verify_ok") is True
            and int(d.get("metric", 1)) == 0
            and d.get("mode") == "LIVE_READBACK_WARN_NONPROD"
            and int(d.get("outcomes") or 0) >= 1
        ):
            return 0
        return 1
    return 1  # no live receipt


def main() -> None:
    sealed = sys.argv[1] if len(sys.argv) > 1 else ""
    if sealed:
        print(f"metric={int(json.load(open(sealed, encoding='utf-8'))['metric'])}")
        return
    print(f"metric={measure()}")


if __name__ == "__main__":
    main()
