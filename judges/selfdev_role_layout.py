#!/usr/bin/env python3
"""role separation residual gaps (lower 0=layout gate live)."""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def measure() -> int:
    g = ROOT/"server/contexts/tree/layout_gate.py"
    j = (ROOT/"server/contexts/tree/judgement_service.py").read_text(encoding="utf-8")
    ok = g.is_file() and "resolve_role_layout" in j and "disjoint_violation" in j
    return 0 if ok else 1
def main():
    sealed = sys.argv[1] if len(sys.argv)>1 else ""
    if sealed:
        print(f"metric={int(json.load(open(sealed))['metric'])}"); return
    print(f"metric={measure()}")
if __name__=="__main__": main()
