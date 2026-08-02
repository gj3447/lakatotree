#!/usr/bin/env python3
"""Novel: live OO receipt exists with cid + ship_status (higher thr 1)."""
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
            return 0
        if d.get("cid") and d.get("verify_ok") is True and d.get("ship_status"):
            return 1
    return 0


def main() -> None:
    sealed = sys.argv[1] if len(sys.argv) > 1 else ""
    if sealed:
        print(f"metric={int(json.load(open(sealed, encoding='utf-8')).get('novel', 0))}")
        return
    print(f"metric={measure()}")


if __name__ == "__main__":
    main()
