#!/usr/bin/env python3
"""Replay the preregistered HALCON gate count from a sealed BPC analysis."""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path


SIBLING = Path(__file__).with_name("judge_bpc_tab_global_python_gates_20260714.py")
EXPECTED_SIBLING_SHA256 = "04268965303d7524cc5ed4ca92d09a72dab952559681884f6a1b1443c9ab562a"


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: judge_bpc_tab_global_halcon_gates_20260714.py RESULT.json")
    if hashlib.sha256(SIBLING.read_bytes()).hexdigest() != EXPECTED_SIBLING_SHA256:
        raise RuntimeError("frozen sibling verifier hash mismatch")
    spec = importlib.util.spec_from_file_location("bpc_tab_global_python_judge", SIBLING)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load frozen sibling verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    payload = module.load_and_verify(Path(sys.argv[1]))
    print(f"metric={payload['lakato_measurement']['halcon_cross_engine_gate_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
