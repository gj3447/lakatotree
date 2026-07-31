#!/usr/bin/env python3
"""Novel: role layout tests present (higher 1)."""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def measure() -> int:
    return 1 if (ROOT/"tests/test_extaudit_role_layout.py").is_file() or (ROOT/"tests/test_layout_fail_closed_20260728.py").is_file() else 0
def main():
    sealed = sys.argv[1] if len(sys.argv)>1 else ""
    if sealed:
        print(f"metric={int(json.load(open(sealed))['metric'])}"); return
    print(f"metric={measure()}")
if __name__=="__main__": main()
