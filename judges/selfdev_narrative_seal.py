#!/usr/bin/env python3
"""narrative escape residual: comment_sha missing from receipt fields (lower; 0=sealed)."""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def measure() -> int:
    v = (ROOT/"lakatos/verdicts.py").read_text(encoding="utf-8")
    f = (ROOT/"server/contexts/audit/fsck.py").read_text(encoding="utf-8")
    ok = "comment_sha" in v and "COMMENT_DRIFT" in f and "comment_sha_at_verdict" in f or "COMMENT_DRIFT_AFTER_VERDICT" in f
    return 0 if ok else 1
def main():
    sealed = sys.argv[1] if len(sys.argv)>1 else ""
    if sealed:
        print(f"metric={int(json.load(open(sealed))['metric'])}"); return
    print(f"metric={measure()}")
if __name__=="__main__": main()
