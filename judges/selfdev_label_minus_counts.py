#!/usr/bin/env python3
"""SelfDev label_minus_counts_closes (lower better). Replay-safe."""
from __future__ import annotations
import json, os, sys, urllib.request
TREE = os.environ.get("LAKATOTREE_NAME", "LakatosTree_LakatoTree_SelfDev_20260612")
BASE = os.environ.get("LAKATOTREE_URL", "http://127.0.0.1:55170").rstrip("/")

def main() -> None:
    sealed = sys.argv[1] if len(sys.argv) > 1 else ""
    v = None
    if sealed:
        try:
            v = float(json.load(open(sealed, encoding="utf-8"))["metric"])
        except Exception:
            v = None
    if v is None:
        tok = os.environ.get("LAKATOS_API_TOKEN", "")
        req = urllib.request.Request(
            f"{BASE}/api/tree/{TREE}/metrics",
            headers={"Authorization": f"Bearer {tok}"} if tok else {},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            m = json.load(resp)
        v = float((m.get("frontier") or {}).get("label_minus_counts_closes") or 0)
    print(f"metric={int(v)}" if float(v).is_integer() else f"metric={v}")

if __name__ == "__main__":
    main()
