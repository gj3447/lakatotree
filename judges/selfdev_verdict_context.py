#!/usr/bin/env python3
"""verdict context parity gaps: display without assurance (lower 0=parity)."""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def measure() -> int:
    r = (ROOT/"server/contexts/tree/repository.py").read_text(encoding="utf-8")
    ok = "verdict_display" in r and "format_verdict_with_val" in r and "assurance" in r
    return 0 if ok else 1
def main():
    sealed = sys.argv[1] if len(sys.argv)>1 else ""
    if sealed:
        print(f"metric={int(json.load(open(sealed))['metric'])}"); return
    print(f"metric={measure()}")
if __name__=="__main__": main()
