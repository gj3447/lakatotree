#!/usr/bin/env python3
"""MCP result_path surface — mcp_only_reproducible_gate_unreachable (lower better).

0 = add_node and submit_result surfaces accept result_path (F-CON-1 reachable via MCP).
1 = gap (pre-PR#16).
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def measure() -> int:
    mcp = (ROOT / "lakatos" / "mcp_server.py").read_text(encoding="utf-8")
    # both write surfaces must document/accept result_path
    if mcp.count("result_path") < 2:
        return 1
    if "def add_node" not in mcp and "add_node" not in mcp:
        return 1
    if "submit_result" not in mcp and "test_result" not in mcp:
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
