#!/usr/bin/env python3
"""oo live residual: gate not coded (lower 0=gate present; live ship still needs OO_PASS)."""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def measure() -> int:
    oo = (ROOT/"lakatos/io/oo_sink.py").read_text(encoding="utf-8")
    ok = "OO_PASS" in oo and "CONSUMER_LOGS_E2E" in oo
    return 0 if ok else 1
def main():
    sealed = sys.argv[1] if len(sys.argv)>1 else ""
    if sealed:
        print(f"metric={int(json.load(open(sealed))['metric'])}"); return
    print(f"metric={measure()}")
if __name__=="__main__": main()
