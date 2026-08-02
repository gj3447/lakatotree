#!/usr/bin/env python3
"""write_surface_ok (higher better). Replay-safe."""
from __future__ import annotations
import json, os, sys, urllib.request
BASE = os.environ.get("LAKATOTREE_URL", "http://127.0.0.1:55170").rstrip("/")

def main() -> None:
    sealed = sys.argv[1] if len(sys.argv) > 1 else ""
    if sealed:
        try:
            print(f"metric={int(json.load(open(sealed, encoding='utf-8'))['metric'])}")
            return
        except Exception:
            pass
    try:
        ver = json.load(urllib.request.urlopen(f"{BASE}/version", timeout=15))
        op = json.load(urllib.request.urlopen(f"{BASE}/openapi.json", timeout=30))
        has_ra = any("reattribute" in p for p in (op.get("paths") or {}))
        ok = bool(ver.get("identity_verified")) and has_ra and not ver.get("stale")
        print(f"metric={1 if ok else 0}")
    except Exception:
        print("metric=0")

if __name__ == "__main__":
    main()
