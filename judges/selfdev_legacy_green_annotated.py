#!/usr/bin/env python3
"""Count of legacy green tags listed in sealed catalog (higher better)."""
from __future__ import annotations
import json, sys

def main() -> None:
    sealed = sys.argv[1] if len(sys.argv) > 1 else ""
    if not sealed:
        print("metric=0")
        return
    d = json.load(open(sealed, encoding="utf-8"))
    tags = d.get("legacy_inconclusive_tags") or d.get("tags") or []
    print(f"metric={len(tags)}")

if __name__ == "__main__":
    main()
