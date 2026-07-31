#!/usr/bin/env python3
"""budget raise gate gaps (lower better). 0=confirm_budget_raise field + service gate present."""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def measure() -> int:
    sch = (ROOT/"server/contexts/tree/schemas.py").read_text(encoding="utf-8")
    svc = (ROOT/"server/contexts/tree/service.py").read_text(encoding="utf-8")
    if "confirm_budget_raise" not in sch: return 1
    if "_assert_budget_raise_gate" not in svc: return 1
    if "write-cert" not in svc and "write_cert" not in svc: return 1
    return 0
def main():
    sealed = sys.argv[1] if len(sys.argv)>1 else ""
    if sealed:
        print(f"metric={int(json.load(open(sealed))['metric'])}"); return
    print(f"metric={measure()}")
if __name__=="__main__": main()
