#!/usr/bin/env python3
"""Novel: OO gate is fail-closed without secret (1 if getenv check present)."""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def measure() -> int:
    oo = (ROOT/"lakatos/io/oo_sink.py").read_text(encoding="utf-8")
    return 1 if "getenv" in oo and "OO_PASS" in oo else 0
def main():
    sealed = sys.argv[1] if len(sys.argv)>1 else ""
    if sealed:
        print(f"metric={int(json.load(open(sealed))['metric'])}"); return
    print(f"metric={measure()}")
if __name__=="__main__": main()
