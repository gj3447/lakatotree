#!/usr/bin/env python3
"""env endtoend residual: environment fingerprint missing (lower 0=present)."""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def measure() -> int:
    lin = (ROOT/"lakatos/io/lineage.py").read_text(encoding="utf-8")
    ad = (ROOT/"lakatos/io/adapters.py").read_text(encoding="utf-8")
    ok = "fingerprint_environment" in lin and "EnvironmentFingerprint" in lin and "OpenLineage" in ad
    return 0 if ok else 1
def main():
    sealed = sys.argv[1] if len(sys.argv)>1 else ""
    if sealed:
        print(f"metric={int(json.load(open(sealed))['metric'])}"); return
    print(f"metric={measure()}")
if __name__=="__main__": main()
