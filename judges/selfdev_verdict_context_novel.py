#!/usr/bin/env python3
"""Novel: format_verdict_with_val / assurance display present (higher 1)."""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def measure() -> int:
    for rel in ("lakatos/assurance.py", "server/contexts/tree/repository.py", "server/contexts/tree/judgement_policy.py"):
        p = ROOT/rel
        if p.is_file() and "format_verdict" in p.read_text(encoding="utf-8"):
            return 1
    return 0
def main():
    sealed = sys.argv[1] if len(sys.argv)>1 else ""
    if sealed:
        print(f"metric={int(json.load(open(sealed))['metric'])}"); return
    print(f"metric={measure()}")
if __name__=="__main__": main()
