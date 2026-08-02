#!/usr/bin/env python3
"""Count active inconclusive greens (exclude legacy_inconclusive_annotate). lower better."""
from __future__ import annotations
import json, os, sys, urllib.request

TREE = os.environ.get("LAKATOTREE_NAME", "LakatosTree_LakatoTree_SelfDev_20260612")
BASE = os.environ.get("LAKATOTREE_URL", "http://127.0.0.1:55170").rstrip("/")
MARK = "legacy_inconclusive_annotate"
PROGRESS = frozenset({
    "progressive", "progressive_unverified", "progressive_conditional", "CANONICAL",
})


def measure() -> int:
    d = json.load(urllib.request.urlopen(f"{BASE}/api/tree/{TREE}", timeout=60))
    n = 0
    for row in d.get("nodes") or []:
        if row.get("verdict") not in PROGRESS:
            continue
        lim = str(row.get("limitation") or "")
        if MARK in lim:
            continue
        # active inconclusive: no COUNTS-grade receipt path
        mg = row.get("measurement_grade")
        replay = row.get("replay_status")
        sha = row.get("current_receipt_sha")
        if mg == "server_regenerated" and replay == "verified":
            continue
        if sha and mg != "client_asserted":
            # has receipt pointer but not L2 — still may be forceful_without_receipt class
            pass
        if (mg == "client_asserted" and replay != "verified") or not sha:
            n += 1
    return n


def main() -> None:
    sealed = sys.argv[1] if len(sys.argv) > 1 else ""
    if sealed:
        print(f"metric={int(json.load(open(sealed, encoding='utf-8'))['metric'])}")
        return
    print(f"metric={measure()}")


if __name__ == "__main__":
    main()
