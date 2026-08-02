#!/usr/bin/env python3
"""novel structural corroboration gaps (lower 0=novel_script surface live)."""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def measure() -> int:
    m = (ROOT/"lakatos/mcp_server.py").read_text(encoding="utf-8")
    j = (ROOT/"server/contexts/tree/judgement_service.py").read_text(encoding="utf-8")
    ok = "novel_script" in m and ("novel_server_anchored" in j or "novel_script" in j)
    return 0 if ok else 1
def main():
    sealed = sys.argv[1] if len(sys.argv)>1 else ""
    if sealed:
        print(f"metric={int(json.load(open(sealed))['metric'])}"); return
    print(f"metric={measure()}")
if __name__=="__main__": main()
