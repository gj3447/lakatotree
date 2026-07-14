#!/usr/bin/env python3
"""Replay the preregistered Python gate count from a sealed BPC analysis."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


SCHEMA = "bpc.tab_bolt.global_field_analysis.v1"
PYTHON_GATES = (
    "group_cell_denominator_exact",
    "capable_group_cells",
    "passing_group_cells",
    "each_group_pass_min",
    "feature_extension_denominator_exact",
    "feature_extension_candidates",
)
HALCON_GATES = (
    "halcon_rows",
    "halcon_cross_engine_pass",
    "halcon_connection_groups",
    "joint_python_halcon_group_cells",
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def load_and_verify(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != SCHEMA or payload.get("no_product_verdict") is not True:
        raise RuntimeError("wrong BPC analysis contract")
    gates = (payload.get("aggregate") or {}).get("gates") or {}
    expected = set(PYTHON_GATES) | set(HALCON_GATES)
    if set(gates) != expected or any(type(gates[name]) is not bool for name in expected):
        raise RuntimeError("gate inventory is missing or substituted")
    measurement = payload.get("lakato_measurement") or {}
    python_count = sum(gates[name] for name in PYTHON_GATES)
    halcon_count = sum(gates[name] for name in HALCON_GATES)
    if (
        measurement.get("python_global_field_gate_count") != python_count
        or measurement.get("python_global_field_gate_expected") != len(PYTHON_GATES)
        or measurement.get("halcon_cross_engine_gate_count") != halcon_count
        or measurement.get("halcon_cross_engine_gate_expected") != len(HALCON_GATES)
    ):
        raise RuntimeError("embedded Lakato measurement is inconsistent")
    contract = payload.get("evidence_contract") or {}
    if (
        len(contract.get("lots") or []) != 5
        or contract.get("feature_rows") != 50
        or contract.get("candidate_rows", 0) < 45
        or contract.get("connection_groups", 0) < 9
    ):
        raise RuntimeError("sealed evidence denominator is not preregistered")
    reproducibility = payload.get("reproducibility") or {}
    required_hashes = (
        "protocol_sha256",
        "probe_sha256",
        "halcon_sha256",
        "halcon_receipt_sha256",
        "analysis_script_sha256",
    )
    if any(not SHA256.fullmatch(str(reproducibility.get(name) or "")) for name in required_hashes):
        raise RuntimeError("reproducibility hash is absent or malformed")
    all_passed = python_count == len(PYTHON_GATES) and halcon_count == len(HALCON_GATES)
    if (payload.get("status") == "PASS") != all_passed:
        raise RuntimeError("analysis status is inconsistent with the frozen gates")
    return payload


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: judge_bpc_tab_global_python_gates_20260714.py RESULT.json")
    payload = load_and_verify(Path(sys.argv[1]))
    print(f"metric={payload['lakato_measurement']['python_global_field_gate_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
