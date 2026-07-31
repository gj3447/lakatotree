#!/usr/bin/env python3
"""Novel: tree hard_core string non-empty (higher thresh 1)."""
from __future__ import annotations
import json, os, sys, urllib.request
TREE = os.environ.get("LAKATOTREE_NAME", "LakatosTree_LakatoTree_SelfDev_20260612")
BASE = os.environ.get("LAKATOTREE_URL", "http://127.0.0.1:55170").rstrip("/")

def measure() -> int:
    d = json.load(urllib.request.urlopen(f"{BASE}/api/tree/{TREE}", timeout=60))
    hc = d.get("hard_core") or ""
    return 1 if len(str(hc).strip()) > 20 else 0

def main() -> None:
    sealed = sys.argv[1] if len(sys.argv) > 1 else ""
    if sealed:
        print(f"metric={int(json.load(open(sealed, encoding='utf-8'))['metric'])}")
        return
    print(f"metric={measure()}")
if __name__ == "__main__":
    main()
