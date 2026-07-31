#!/usr/bin/env python3
"""SelfDev live metric: frontier.label_minus_counts_closes (lower better).

Predicate-align honesty: FORCEFUL label closes minus force_of_row COUNTS closes.
Prints `metric=<int>`.
"""
from __future__ import annotations

import json
import os
import urllib.request

TREE = os.environ.get(
    "LAKATOTREE_NAME", "LakatosTree_LakatoTree_SelfDev_20260612"
)
BASE = os.environ.get("LAKATOTREE_URL", "http://127.0.0.1:55170").rstrip("/")


def main() -> None:
    url = f"{BASE}/api/tree/{TREE}/metrics"
    tok = os.environ.get("LAKATOS_API_TOKEN", "")
    headers = {"Authorization": f"Bearer {tok}"} if tok else {}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        m = json.load(resp)
    fr = m.get("frontier") or {}
    v = int(fr.get("label_minus_counts_closes") or 0)
    print(f"metric={v}")


if __name__ == "__main__":
    main()
