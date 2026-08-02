#!/usr/bin/env python3
"""Deterministic judge for the targeted ARG-5 claim-ownership mutation.

This module does not run databases or mutate LakatoTree.  It judges a frozen
``real_harness.py`` artifact bundle and returns a gap count.  Metric zero means
the current service was GREEN, the targeted claim-token mutation produced only
the expected semantic assertion RED, and restored current source was GREEN.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


METRIC_NAME = "arg5_targeted_semantic_negative_gaps"
TARGET_TEST = "test_arg_5_create_claim_has_one_owner_and_does_not_leak"
HISTORICAL_TESTS = (
    "test_arg_1_dangling_target_is_rejected_without_side_effects",
    "test_arg_2_argument_identity_is_immutable",
    "test_arg_3_exact_retry_is_idempotent_without_duplicate_history",
    "test_arg_4_tree_lock_serializes_cross_node_identity_race",
)
ALL_TESTS = (*HISTORICAL_TESTS, TARGET_TEST)
PHASE_FILES = (
    ("positive", "positive.json"),
    ("negative_historical_arg_1_4", "negative_historical.json"),
    ("negative_targeted_arg_5_claim", "negative_arg5_claim.json"),
    ("restored_positive", "restored_positive.json"),
)
INFRA_FAILURE_MARKERS = (
    "PoolError",
    "ConnectionError",
    "Connection refused",
    "Connection reset",
    "DockerException",
    "ImageNotFound",
    "OperationalError",
    "TimeoutExpired",
    "testcontainers.core",
)


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path, failures: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        failures.append(f"unreadable:{path.name}:{type(exc).__name__}")
        return {}
    if not isinstance(value, dict):
        failures.append(f"not_object:{path.name}")
        return {}
    return value


def _cases(phase: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = ((phase.get("junit") or {}).get("cases") or [])
    return {
        str(case.get("name")): case
        for case in raw
        if isinstance(case, dict) and case.get("name")
    }


def _check_green(
    phase: dict[str, Any], phase_name: str, failures: list[str]
) -> None:
    if phase.get("phase") != phase_name:
        failures.append(f"phase_name:{phase_name}")
    if not phase.get("accepted") or phase.get("observed") != "GREEN":
        failures.append(f"not_green:{phase_name}")
    cases = _cases(phase)
    if set(cases) != set(ALL_TESTS):
        failures.append(f"test_set:{phase_name}")
    if any(case.get("status") != "passed" for case in cases.values()):
        failures.append(f"nonpass_case:{phase_name}")


def _infra_details(cases: dict[str, dict[str, Any]]) -> list[str]:
    found = []
    for name, case in cases.items():
        detail = str(case.get("detail") or "")
        if any(marker in detail for marker in INFRA_FAILURE_MARKERS):
            found.append(name)
    return sorted(found)


def judge(artifact_dir: str | Path) -> dict[str, Any]:
    root = Path(artifact_dir).resolve()
    failures: list[str] = []
    phase_by_name: dict[str, dict[str, Any]] = {}
    for phase_name, filename in PHASE_FILES:
        phase_by_name[phase_name] = _read_json(root / filename, failures)

    _check_green(phase_by_name["positive"], "positive", failures)
    _check_green(phase_by_name["restored_positive"], "restored_positive", failures)

    historical = phase_by_name["negative_historical_arg_1_4"]
    historical_cases = _cases(historical)
    if historical.get("phase") != "negative_historical_arg_1_4":
        failures.append("phase_name:negative_historical_arg_1_4")
    if not historical.get("accepted") or historical.get("observed") != "RED":
        failures.append("historical_not_semantic_red")
    if set(historical_cases) != set(HISTORICAL_TESTS):
        failures.append("historical_test_set")
    if any(case.get("status") != "failed" for case in historical_cases.values()):
        failures.append("historical_nonfailed_case")
    for name in _infra_details(historical_cases):
        failures.append(f"historical_infra_failure:{name}")

    targeted = phase_by_name["negative_targeted_arg_5_claim"]
    targeted_cases = _cases(targeted)
    if targeted.get("phase") != "negative_targeted_arg_5_claim":
        failures.append("phase_name:negative_targeted_arg_5_claim")
    if not targeted.get("accepted") or targeted.get("observed") != "RED":
        failures.append("targeted_not_semantic_red")
    if set(targeted_cases) != {TARGET_TEST}:
        failures.append("targeted_test_set")
    target_case = targeted_cases.get(TARGET_TEST, {})
    if target_case.get("status") != "failed":
        failures.append("targeted_case_not_failed")
    if "AssertionError" not in str(target_case.get("detail") or ""):
        failures.append("targeted_failure_not_assertion")
    for name in _infra_details(targeted_cases):
        failures.append(f"targeted_infra_failure:{name}")

    mutation = _read_json(root / "arg5_claim_mutation.json", failures)
    if mutation.get("mutation_id") != "arg5-remove-on-create-claim":
        failures.append("mutation_id")
    if mutation.get("replacements") != 1:
        failures.append("mutation_replacements")
    if mutation.get("marker_removed") is not True:
        failures.append("mutation_marker_not_removed")
    before_sha = mutation.get("source_before_sha256")
    after_sha = mutation.get("source_after_sha256")
    if not isinstance(before_sha, str) or len(before_sha) != 64:
        failures.append("mutation_before_sha")
    if not isinstance(after_sha, str) or len(after_sha) != 64 or after_sha == before_sha:
        failures.append("mutation_after_sha")
    if targeted.get("source_sha256") != after_sha:
        failures.append("targeted_source_sha")

    receipt_path = root / "receipt.json"
    receipt = _read_json(receipt_path, failures)
    if receipt.get("complete") is not True:
        failures.append("receipt_incomplete")
    if receipt.get("canonical_worktree_mutated") is not False:
        failures.append("canonical_worktree_mutated")
    bindings = receipt.get("bindings") or {}
    if bindings.get("service_sha256") != before_sha:
        failures.append("receipt_service_sha")
    if bindings.get("targeted_judge_sha256") != _sha_file(Path(__file__).resolve()):
        failures.append("receipt_judge_sha")
    sequence = receipt.get("sequence") or []
    if [item.get("phase") for item in sequence if isinstance(item, dict)] != [
        phase for phase, _ in PHASE_FILES
    ]:
        failures.append("receipt_sequence")
    for item in sequence:
        if not isinstance(item, dict):
            failures.append("receipt_sequence_item")
            continue
        path = root / str(item.get("path") or "")
        if not path.is_file() or item.get("sha256") != _sha_file(path):
            failures.append(f"receipt_phase_sha:{item.get('phase')}")

    unique_failures = sorted(set(failures))
    return {
        "schema_version": "lakatotree-judge-result/v1",
        "experiment_id": "ARG5_TARGETED_CLAIM_OWNERSHIP_SEMANTIC_NEGATIVE_20260801",
        "metric_name": METRIC_NAME,
        "metric": len(unique_failures),
        "direction": "lower",
        "threshold": 0,
        "noise_band": 0,
        "status": "PASS" if not unique_failures else "FAIL",
        "failures": unique_failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = judge(args.artifact_dir)
    encoded = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0 if result["metric"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
