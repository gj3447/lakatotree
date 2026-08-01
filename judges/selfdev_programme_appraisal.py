#!/usr/bin/env python3
"""programme_appraisal wiring failures (lower better).

0 = tree_metrics exposes programme_appraisal with dual-layer note and no promotion authority.
Live: GET /metrics when LAKATOTREE_URL set; else local pure check on code.
"""
from __future__ import annotations
import json, os, sys, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def measure_code() -> int:
    src = (ROOT / "lakatos" / "quant" / "metrics.py").read_text(encoding="utf-8")
    if "_programme_appraisal_layer" not in src:
        return 1
    if "programme_appraisal=programme_appraisal" not in src and "programme_appraisal" not in src:
        return 1
    return 0


def measure_live() -> int | None:
    base = os.environ.get("LAKATOTREE_URL", "").rstrip("/")
    tree = os.environ.get("LAKATOTREE_NAME", "LakatosTree_LakatoTree_SelfDev_20260612")
    tok = os.environ.get("LAKATOS_API_TOKEN", "")
    if not base:
        return None
    try:
        req = urllib.request.Request(
            f"{base}/api/tree/{tree}/metrics",
            headers={"Authorization": f"Bearer {tok}"} if tok else {},
        )
        m = json.load(urllib.request.urlopen(req, timeout=60))
        pa = m.get("programme_appraisal") or {}
        if not pa:
            return 1
        if pa.get("promotion_authority") is not False:
            return 1
        if pa.get("status") not in ("UNAPPRAISED", "PROGRESSIVE", "STAGNANT", "DEGENERATING"):
            return 1
        if "dual-layer" not in str(pa.get("note") or ""):
            return 1
        return 0
    except Exception:
        return 1


def measure() -> int:
    c = measure_code()
    if c:
        return c
    live = measure_live()
    return c if live is None else live


def main() -> None:
    sealed = sys.argv[1] if len(sys.argv) > 1 else ""
    if sealed:
        print(f"metric={int(json.load(open(sealed, encoding='utf-8'))['metric'])}")
        return
    print(f"metric={measure()}")


if __name__ == "__main__":
    main()
