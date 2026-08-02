#!/usr/bin/env python3
"""list index dangling count (lower better). Prefer sealed; live hits /api/trees/janitor."""
from __future__ import annotations
import json, os, sys, urllib.request
BASE = os.environ.get("LAKATOTREE_URL", "http://127.0.0.1:55170").rstrip("/")
TOKEN = os.environ.get("LAKATOS_API_TOKEN", "")
def measure() -> int:
    req = urllib.request.Request(
        f"{BASE}/api/trees/janitor", method="POST",
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
        data=b"{}",
    )
    try:
        d = json.load(urllib.request.urlopen(req, timeout=120))
        return int(d.get("dangling_count") or 0)
    except Exception:
        return 99
def main():
    sealed = sys.argv[1] if len(sys.argv)>1 else ""
    if sealed:
        print(f"metric={int(json.load(open(sealed))['metric'])}"); return
    print(f"metric={measure()}")
if __name__=="__main__": main()
