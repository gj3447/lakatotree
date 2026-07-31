#!/usr/bin/env python3
"""Count progressive/CANONICAL nodes with server_regenerated + eureka_true (higher better)."""
from __future__ import annotations
import json, os, sys, urllib.request
TREE = os.environ.get("LAKATOTREE_NAME", "LakatosTree_LakatoTree_SelfDev_20260612")
BASE = os.environ.get("LAKATOTREE_URL", "http://127.0.0.1:55170").rstrip("/")

def main() -> None:
    sealed = sys.argv[1] if len(sys.argv) > 1 else ""
    if sealed:
        try:
            print(f"metric={int(json.load(open(sealed, encoding='utf-8'))['metric'])}")
            return
        except Exception:
            pass
    tok = os.environ.get("LAKATOS_API_TOKEN", "")
    req = urllib.request.Request(
        f"{BASE}/api/tree/{TREE}",
        headers={"Authorization": f"Bearer {tok}"} if tok else {},
    )
    # tree may be public
    try:
        d = json.load(urllib.request.urlopen(f"{BASE}/api/tree/{TREE}", timeout=60))
    except Exception:
        d = json.load(urllib.request.urlopen(req, timeout=60))
    n = 0
    for row in d.get("nodes") or []:
        if row.get("measurement_grade") != "server_regenerated":
            continue
        if row.get("replay_status") != "verified":
            continue
        if not row.get("eureka_true"):
            continue
        if row.get("verdict") in ("progressive", "CANONICAL", "progressive_unverified"):
            n += 1
    print(f"metric={n}")

if __name__ == "__main__":
    main()
