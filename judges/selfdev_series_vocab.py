#!/usr/bin/env python3
"""single-run vocab residual: series/tradition modules missing (lower 0=present)."""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def measure() -> int:
    has_series = any((ROOT/"lakatos").rglob("*series*")) or (ROOT/"tests/test_programme_series.py").is_file()
    has_trad = "tradition" in (ROOT/"lakatos").joinpath("mcp_server.py").read_text(encoding="utf-8")
    return 0 if (has_series and has_trad) else 1
def main():
    sealed = sys.argv[1] if len(sys.argv)>1 else ""
    if sealed:
        print(f"metric={int(json.load(open(sealed))['metric'])}"); return
    print(f"metric={measure()}")
if __name__=="__main__": main()
