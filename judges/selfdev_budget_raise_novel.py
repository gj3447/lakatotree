#!/usr/bin/env python3
"""Novel: unit tests for budget raise gate present (higher thresh 1)."""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def measure() -> int:
    p = ROOT/"tests/test_budget_raise_gate_20260801.py"
    return 1 if p.is_file() and "confirm_budget_raise" in p.read_text(encoding="utf-8") else 0
def main():
    sealed = sys.argv[1] if len(sys.argv)>1 else ""
    if sealed:
        print(f"metric={int(json.load(open(sealed))['metric'])}"); return
    print(f"metric={measure()}")
if __name__=="__main__": main()
