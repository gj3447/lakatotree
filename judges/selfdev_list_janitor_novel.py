#!/usr/bin/env python3
"""Novel: janitor endpoint wired in api.py (higher 1)."""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def measure() -> int:
    api = (ROOT/"server/contexts/tree/api.py").read_text(encoding="utf-8")
    return 1 if "list_index_janitor" in api and "/api/trees/janitor" in api else 0
def main():
    sealed = sys.argv[1] if len(sys.argv)>1 else ""
    if sealed:
        print(f"metric={int(json.load(open(sealed))['metric'])}"); return
    print(f"metric={measure()}")
if __name__=="__main__": main()
