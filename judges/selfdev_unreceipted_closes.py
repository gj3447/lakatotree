#!/usr/bin/env python3
"""SelfDev unreceipted_closes (lower better). Replay: python script [result_path]."""
from __future__ import annotations
import json, os, sys, urllib.request
TREE = os.environ.get("LAKATOTREE_NAME", "LakatosTree_LakatoTree_SelfDev_20260612")
BASE = os.environ.get("LAKATOTREE_URL", "http://127.0.0.1:55170").rstrip("/")

def from_sealed(path: str) -> float | None:
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        if "metric" in d:
            return float(d["metric"])
    except Exception:
        return None
    return None

def from_live() -> float:
    tok = os.environ.get("LAKATOS_API_TOKEN", "")
    req = urllib.request.Request(
        f"{BASE}/api/tree/{TREE}/metrics",
        headers={"Authorization": f"Bearer {tok}"} if tok else {},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        m = json.load(resp)
    return float((m.get("frontier") or {}).get("unreceipted_closes") or 0)

def main() -> None:
    sealed = sys.argv[1] if len(sys.argv) > 1 else ""
    v = from_sealed(sealed) if sealed else None
    if v is None:
        v = from_live()
    # harness contract: integer metrics print without .0 when whole
    if float(v).is_integer():
        print(f"metric={int(v)}")
    else:
        print(f"metric={v}")

if __name__ == "__main__":
    main()
