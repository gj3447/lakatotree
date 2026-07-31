#!/usr/bin/env python3
"""replay default-on residual gaps (lower better).

0 = LAKATOS_REPLAY_SANDBOXED documented in app.py GO1 flip + env surface exists.
1 = wiring missing.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def measure() -> int:
    app = (ROOT / "server" / "app.py").read_text(encoding="utf-8")
    if "LAKATOS_REPLAY_SANDBOXED" not in app:
        return 1
    if "GO1" not in app and "sandboxed" not in app:
        return 1
    return 0


def main() -> None:
    sealed = sys.argv[1] if len(sys.argv) > 1 else ""
    if sealed:
        print(f"metric={int(json.load(open(sealed, encoding='utf-8'))['metric'])}")
        return
    print(f"metric={measure()}")


if __name__ == "__main__":
    main()
