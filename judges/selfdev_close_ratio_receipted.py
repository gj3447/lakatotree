#!/usr/bin/env python3
"""SelfDev live metric: frontier.close_ratio_receipted (higher better).

Novel companion for receipted-close / predicate-align cycles.
Prints `metric=<float>`.
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
    v = float(fr.get("close_ratio_receipted") or 0.0)
    print(f"metric={v}")


if __name__ == "__main__":
    main()
