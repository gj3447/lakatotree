#!/usr/bin/env python3
"""Novel axis: eureka_true_at_judgement_seam (higher better, threshold 1.0).

Structural: eureka module maps programme-head status so judgement-time eureka can
stay true after CANONICAL promote (not always BF-marginal). Metric=1 if map present.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def measure() -> int:
    text = (ROOT / "lakatos" / "eureka.py").read_text(encoding="utf-8")
    # eureka_verdict must map CANONICAL and progressive_unverified → progressive
    has_fn = "def eureka_verdict" in text
    has_canon = "CANONICAL" in text and "progressive" in text
    has_unv = "progressive_unverified" in text
    return 1 if (has_fn and has_canon and has_unv) else 0


def main() -> None:
    sealed = sys.argv[1] if len(sys.argv) > 1 else ""
    if sealed:
        print(f"metric={int(json.load(open(sealed, encoding='utf-8'))['metric'])}")
        return
    print(f"metric={measure()}")


if __name__ == "__main__":
    main()
