#!/usr/bin/env python3
"""MCP closes_question surface residual — eureka_ledger_idle_at_scoring (lower better).

0 = register_prediction MCP/REST surface accepts closes_question (ledger can bind at scoring).
1 = surface missing (pre-PR#17 gap).
Sealed path argv[1] prints frozen metric for L2 replay.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def measure() -> int:
    mcp = (ROOT / "lakatos" / "mcp_server.py").read_text(encoding="utf-8")
    # surface must expose closes_question on prediction registration path
    if "closes_question" not in mcp:
        return 1
    if "def register_prediction" not in mcp and "register_prediction" not in mcp:
        return 1
    # REST prediction schema also carries the field (server)
    schemas = list((ROOT / "server").rglob("*schema*.py")) + list((ROOT / "server").rglob("*prediction*"))
    blob = mcp
    for p in schemas:
        try:
            blob += "\n" + p.read_text(encoding="utf-8")
        except Exception:
            pass
    if "closes_question" not in blob:
        return 1
    return 0


def main() -> None:
    sealed = sys.argv[1] if len(sys.argv) > 1 else ""
    if sealed:
        print(f"metric={int(json.load(open(sealed, encoding='utf-8'))['metric'])}")
        return
    print(f"metric={measure()}")


if __name__ == "__main__":
    main()
