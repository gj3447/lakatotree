#!/usr/bin/env python3
"""Novel companion: write tools reachable (1=ok, 0=fail). Higher better."""
from __future__ import annotations

import json
import os
import urllib.request

BASE = os.environ.get("LAKATOTREE_URL", "http://127.0.0.1:55170").rstrip("/")


def main() -> None:
    # Public version + reattribute path in openapi = write surface present
    try:
        ver = json.load(urllib.request.urlopen(f"{BASE}/version", timeout=15))
        op = json.load(urllib.request.urlopen(f"{BASE}/openapi.json", timeout=30))
        has_ra = any("reattribute" in p for p in (op.get("paths") or {}))
        ok = bool(ver.get("identity_verified")) and has_ra and not ver.get("stale")
        print(f"metric={1 if ok else 0}")
    except Exception:  # noqa: BLE001
        print("metric=0")


if __name__ == "__main__":
    main()
