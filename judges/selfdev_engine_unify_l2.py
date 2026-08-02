#!/usr/bin/env python3
"""L2 wrapper: sealed metric or delegate to engine_unify_vocab."""
from __future__ import annotations
import json, sys
from pathlib import Path

def main():
    sealed = sys.argv[1] if len(sys.argv) > 1 else ""
    if sealed:
        print(f"metric={int(json.load(open(sealed, encoding='utf-8'))['metric'])}")
        return
    # live delegate
    import runpy
    runpy.run_path(str(Path(__file__).resolve().parent / "engine_unify_vocab.py"), run_name="__main__")

if __name__ == "__main__":
    main()
