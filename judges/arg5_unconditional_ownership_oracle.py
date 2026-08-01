#!/usr/bin/env python3
"""Frozen v2 judge for ARG-5 unconditional ownership acknowledgement.

The judge is deliberately read-only.  It consumes the preregistered protocol,
activation, judge input, phase summaries, mutation receipt, environment receipt,
and raw JUnit.  It never reads the later scientific receipt or bundle manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from judges import argument_integrity_bundle_validator_v2 as contract  # noqa: E402


PROTOCOL_PATH = (
    REPO / "ooptdd_receipts/ARGUMENT_INTEGRITY/v2/harness_v2.json"
)
ACTIVATION_PATH = (
    REPO / "ooptdd_receipts/ARGUMENT_INTEGRITY/v2/activation_20260802.json"
)
FROZEN_PROTOCOL_SHA256 = (
    "99dc3c3e3ba9de1eb859366fd3c6ed7554f4c61feca05ee905d40492eb169fd8"
)
METRIC_NAME = "arg5_unconditional_ownership_comparison_gaps"


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path, failures: list[str]) -> dict[str, Any]:
    return contract._read_json(path, failures)


def judge(
    artifact_dir: str | Path,
    *,
    protocol_path: Path = PROTOCOL_PATH,
    activation_path: Path = ACTIVATION_PATH,
) -> dict[str, Any]:
    root = Path(artifact_dir).resolve()
    failures: list[str] = []
    protocol, protocol_sha = contract._validate_protocol(protocol_path, failures)
    if protocol_sha != FROZEN_PROTOCOL_SHA256:
        failures.append("protocol:frozen_sha256")
    activation, activation_sha = contract._validate_activation(
        activation_path, protocol, protocol_sha, failures
    )

    protocol_snapshot = root / "protocol.json"
    activation_snapshot = root / "activation.json"
    if (
        not protocol_snapshot.is_file()
        or protocol_snapshot.is_symlink()
        or _sha_file(protocol_snapshot) != protocol_sha
    ):
        failures.append("bundle:protocol_snapshot")
    if (
        not activation_snapshot.is_file()
        or activation_snapshot.is_symlink()
        or _sha_file(activation_snapshot) != activation_sha
    ):
        failures.append("bundle:activation_snapshot")

    mutation = _read_json(root / "mutation.json", failures)
    contract._validate_mutation(mutation, protocol, failures)
    environment_path = root / "environment.json"
    environment = _read_json(environment_path, failures)
    environment_sha = (
        _sha_file(environment_path) if environment_path.is_file() else ""
    )
    contract._validate_environment(
        environment, activation, protocol, protocol_sha, failures
    )
    registered_at = contract._parse_time(activation.get("server_registered_at"))
    captured_at = contract._parse_time(environment.get("captured_at"))
    if (
        registered_at is None
        or captured_at is None
        or captured_at.utcoffset() is None
        or captured_at <= registered_at
    ):
        failures.append("environment:preregistration_precedence")

    for phase_name, filename, junit_filename, expected, exit_code in contract.PHASE_FILES:
        phase = _read_json(root / filename, failures)
        contract._validate_phase(
            root,
            phase,
            phase_name=phase_name,
            junit_filename=junit_filename,
            expected=expected,
            exit_code=exit_code,
            protocol=protocol,
            protocol_sha=protocol_sha,
            environment_sha=environment_sha,
            failures=failures,
        )

    judge_input_path = root / "judge_input.json"
    judge_input = _read_json(judge_input_path, failures)
    judge_input_sha = (
        _sha_file(judge_input_path) if judge_input_path.is_file() else None
    )
    contract._validate_judge_input(
        root,
        judge_input,
        protocol=protocol,
        protocol_sha=protocol_sha,
        activation_sha=activation_sha,
        failures=failures,
    )

    unique = sorted(set(failures))
    return {
        "schema_version": "lakatotree-argument-integrity-v2-judge-result/v1",
        "experiment_id": contract.EXPERIMENT_ID,
        "metric_name": METRIC_NAME,
        "metric": len(unique),
        "direction": "lower",
        "threshold": 0,
        "noise_band": 0,
        "status": "PASS" if not unique else "FAIL",
        "scientific_status": "UNJUDGED",
        "failures": unique,
        "judge_input_sha256": judge_input_sha,
        "judge_source_sha256": _sha_file(Path(__file__).resolve()),
        "protocol_sha256": protocol_sha,
        "activation_sha256": activation_sha,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = judge(args.artifact_dir)
    encoded = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    else:
        print(encoded, end="")
    return 0 if type(result["metric"]) is int and result["metric"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
