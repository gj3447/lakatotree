#!/usr/bin/env python3
"""hard_core discard incidents on SelfDev tree (lower better; goal 0)."""
from __future__ import annotations
import json, os, sys, urllib.request
TREE = os.environ.get("LAKATOTREE_NAME", "LakatosTree_LakatoTree_SelfDev_20260612")
BASE = os.environ.get("LAKATOTREE_URL", "http://127.0.0.1:55170").rstrip("/")

def measure() -> int:
    # Structural: no node verdict rejected the tree hard_core; use open question residual only.
    # Count nodes that claim hardcore violation via lakatos_status markers if any.
    d = json.load(urllib.request.urlopen(f"{BASE}/api/tree/{TREE}", timeout=60))
    bad = 0
    for n in d.get("nodes") or []:
        st = str(n.get("lakatos_status") or "")
        if "hard_core" in st.lower() and "viol" in st.lower():
            bad += 1
        if n.get("verdict") == "rejected" and "hard" in str(n.get("note") or "").lower():
            bad += 1
    return bad

def main() -> None:
    sealed = sys.argv[1] if len(sys.argv) > 1 else ""
    if sealed:
        print(f"metric={int(json.load(open(sealed, encoding='utf-8'))['metric'])}")
        return
    print(f"metric={measure()}")
if __name__ == "__main__":
    main()
