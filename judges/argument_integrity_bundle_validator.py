#!/usr/bin/env python3
"""Validate ARGUMENT_INTEGRITY bundle structure without issuing a verdict.

The frozen ARG-5 judge remains the semantic metric authority for its original
experiment.  This module is a separate fail-closed structural validator: it
rejects infrastructure, timeout, collection, unexpected-test, receipt, or hash
states that a producer-controlled ``accepted`` boolean could otherwise hide.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

try:  # package import under pytest / ``python -m``
    from judges import arg5_targeted_negative_oracle as frozen_judge
except ModuleNotFoundError:  # direct ``python judges/...py`` CLI execution
    import arg5_targeted_negative_oracle as frozen_judge


TARGET_TEST = "test_arg_5_create_claim_has_one_owner_and_does_not_leak"
HISTORICAL_TESTS = (
    "test_arg_1_dangling_target_is_rejected_without_side_effects",
    "test_arg_2_argument_identity_is_immutable",
    "test_arg_3_exact_retry_is_idempotent_without_duplicate_history",
    "test_arg_4_tree_lock_serializes_cross_node_identity_race",
)
ALL_TESTS = (*HISTORICAL_TESTS, TARGET_TEST)
EXPECTED_CLASSNAME = "tests.integration.test_argument_integrity_real_neo4j"
FROZEN_EXPERIMENT_ID = "ARG5_TARGETED_CLAIM_OWNERSHIP_SEMANTIC_NEGATIVE_20260801"
FROZEN_JUDGE_SHA256 = "eedeacea5d066814708221e682ce0883f1566259812ae1a845d405aedffb9e20"
FROZEN_PREREG_SHA256 = "d9eb3d7194bf096284f9c33e926416deed2f9c35b7c812c5ec580dd8c5891b12"
PHASE_FILES = (
    ("positive", "positive.json"),
    ("negative_historical_arg_1_4", "negative_historical.json"),
    ("negative_targeted_arg_5_claim", "negative_arg5_claim.json"),
    ("restored_positive", "restored_positive.json"),
)
_PHASE_CONTRACTS = {
    "positive": (ALL_TESTS, "GREEN", "GREEN", 0),
    "negative_historical_arg_1_4": (HISTORICAL_TESTS, "RED", "RED", 1),
    "negative_targeted_arg_5_claim": ((TARGET_TEST,), "RED", "RED", 1),
    "restored_positive": (ALL_TESTS, "GREEN", "GREEN", 0),
}
_JUNIT_FILES = {
    "positive": "positive.junit.xml",
    "negative_historical_arg_1_4": "negative_historical.junit.xml",
    "negative_targeted_arg_5_claim": "negative_arg5_claim.junit.xml",
    "restored_positive": "restored_positive.junit.xml",
}
_INFRA_MARKERS = (
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
_EMPTY_LIST_FIELDS = (
    "infra_failures",
    "unexpected_failures",
    "missing_tests",
    "required_detail_mismatches",
)
_BINDING_KEYS = {
    "arg5_claim_mutation_sha256",
    "environment_sha256",
    "fixture_sha256",
    "harness_sha256",
    "historical_negative_service_sha256",
    "manifest_sha256",
    "preregistration_sha256",
    "producer_sha256",
    "requirements_sha256",
    "service_sha256",
    "targeted_judge_sha256",
    "targeted_negative_service_sha256",
}
_BUNDLE_FILES = {
    "arg5_claim_mutation.json",
    "environment.json",
    "judge.json",
    "negative_arg5_claim.json",
    "negative_arg5_claim.junit.xml",
    "negative_historical.json",
    "negative_historical.junit.xml",
    "positive.json",
    "positive.junit.xml",
    "receipt.json",
    "restored_positive.json",
    "restored_positive.junit.xml",
}
_REQUIRED_ENV_INPUT_BINDINGS = {
    "judges/arg5_targeted_negative_oracle.py": "targeted_judge_sha256",
    "ooptdd_receipts/ARGUMENT_INTEGRITY/harness.json": "manifest_sha256",
    "ooptdd_receipts/ARGUMENT_INTEGRITY/prereg_arg5_semantic_negative_20260801.json": "preregistration_sha256",
    "ooptdd_receipts/ARGUMENT_INTEGRITY/real_harness.py": "producer_sha256",
    "ooptdd_receipts/ARGUMENT_INTEGRITY/requirements.yaml": "requirements_sha256",
    "server/contexts/tree/evidence_claim_service.py": "service_sha256",
    "tests/integration/conftest.py": "fixture_sha256",
    "tests/integration/test_argument_integrity_real_neo4j.py": "harness_sha256",
}
_FAILURE_DETAIL_MARKERS = {
    HISTORICAL_TESTS[0]: ("AssertionError", "'ok' == '422'"),
    HISTORICAL_TESTS[1]: ("AssertionError", "'ok' == '409'"),
    HISTORICAL_TESTS[2]: ("KeyError: 'idempotent'",),
    HISTORICAL_TESTS[3]: (
        "AssertionError",
        "['ok', 'ok'] == ['409', 'ok']",
    ),
    TARGET_TEST: ("AssertionError: assert 0 == 2", "['409', '409'].count"),
}


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _exact_int(value: Any, expected: int) -> bool:
    return type(value) is int and value == expected


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


def _summary_case_map(
    junit: dict[str, Any], prefix: str, failures: list[str]
) -> dict[str, dict[str, Any]]:
    raw = junit.get("cases")
    if not isinstance(raw, list):
        failures.append(f"{prefix}:junit_cases")
        return {}
    cases: list[dict[str, Any]] = []
    for case in raw:
        if not isinstance(case, dict) or not isinstance(case.get("name"), str):
            failures.append(f"{prefix}:junit_case_shape")
            continue
        cases.append(case)
    names = [case["name"] for case in cases]
    if len(names) != len(set(names)):
        failures.append(f"{prefix}:junit_duplicate_case")
    return {case["name"]: case for case in cases}


def _raw_junit_cases(
    path: Path, prefix: str, failures: list[str]
) -> list[dict[str, Any]]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        failures.append(f"{prefix}:raw_junit:{type(exc).__name__}")
        return []
    cases = []
    for case in root.iter("testcase"):
        status = "passed"
        detail = ""
        raw_detail = ""
        failure_type = None
        for child_name, child_status in (
            ("failure", "failed"),
            ("error", "error"),
            ("skipped", "skipped"),
        ):
            child = case.find(child_name)
            if child is not None:
                status = child_status
                message = child.get("message") or ""
                body = child.text or ""
                failure_type = child.get("type")
                detail = (message or body)[:500]
                raw_detail = "\n".join(
                    item for item in (failure_type or "", message, body) if item
                )
                break
        cases.append(
            {
                "name": case.get("name", ""),
                "classname": case.get("classname", ""),
                "status": status,
                "detail": detail or None,
                "failure_type": failure_type,
                "raw_detail": raw_detail,
            }
        )
    names = [case["name"] for case in cases]
    if len(names) != len(set(names)):
        failures.append(f"{prefix}:raw_junit_duplicate_case")
    if any(
        marker in case["raw_detail"]
        for case in cases
        for marker in _INFRA_MARKERS
    ):
        failures.append(f"{prefix}:raw_infra_failure")
    return cases


def _validate_phase(
    phase: dict[str, Any], phase_name: str, failures: list[str]
) -> None:
    tests, expected, observed, exit_code = _PHASE_CONTRACTS[phase_name]
    prefix = "targeted" if phase_name == "negative_targeted_arg_5_claim" else phase_name
    if phase.get("schema_version") != "lakatotree-requirements-harness-run/v1":
        failures.append(f"{prefix}:schema_version")
    if phase.get("phase") != phase_name:
        failures.append(f"{prefix}:phase")
    if phase.get("expected") != expected or phase.get("observed") != observed:
        failures.append(f"{prefix}:expected_observed")
    if phase.get("accepted") is not True:
        failures.append(f"{prefix}:not_accepted")
    if phase.get("execution_ok") is not True:
        failures.append(f"{prefix}:execution_not_ok")
    if phase.get("timed_out") is not False:
        failures.append(f"{prefix}:timed_out")
    if phase.get("canonical_worktree_mutated") is not False:
        failures.append(f"{prefix}:canonical_worktree_mutated")
    if not _exact_int(phase.get("exit_code"), exit_code):
        failures.append(f"{prefix}:exit_code")
    for field in _EMPTY_LIST_FIELDS:
        if phase.get(field) != []:
            failures.append(f"{prefix}:{field}")

    junit = phase.get("junit")
    if not isinstance(junit, dict):
        failures.append(f"{prefix}:junit")
        return
    failed = observed == "RED"
    expected_semantic_failures = list(tests) if failed else []
    if phase.get("semantic_failures") != expected_semantic_failures:
        failures.append(f"{prefix}:semantic_failures")
    expected_count = len(tests)
    expected_counts = {
        "present": True,
        "tests": expected_count,
        "passed": 0 if failed else expected_count,
        "failed": expected_count if failed else 0,
        "errors": 0,
        "skipped": 0,
    }
    for key, value in expected_counts.items():
        actual = junit.get(key)
        valid = actual is value if type(value) is bool else _exact_int(actual, value)
        if not valid:
            failures.append(f"{prefix}:junit_{key}")
    cases = _summary_case_map(junit, prefix, failures)
    if len(junit.get("cases") or []) != expected_count:
        failures.append(f"{prefix}:junit_case_count")
    if set(cases) != set(tests):
        failures.append(f"{prefix}:junit_test_set")
    required_status = "failed" if failed else "passed"
    if any(case.get("status") != required_status for case in cases.values()):
        failures.append(f"{prefix}:junit_status")
    if any(case.get("classname") != EXPECTED_CLASSNAME for case in cases.values()):
        failures.append(f"{prefix}:junit_classname")

    junit_filename = _JUNIT_FILES[phase_name]
    junit_path = Path(phase.get("_artifact_root", ".")) / junit_filename
    if phase.get("junit_path") != junit_filename:
        failures.append(f"{prefix}:junit_path")
    if not junit_path.is_file():
        failures.append(f"{prefix}:raw_junit_missing")
        return
    if phase.get("junit_sha256") != _sha_file(junit_path):
        failures.append(f"{prefix}:raw_junit_sha")
    raw_cases = _raw_junit_cases(junit_path, prefix, failures)
    if len(raw_cases) != expected_count:
        failures.append(f"{prefix}:raw_junit_count")
    raw_by_name = {case["name"]: case for case in raw_cases}
    if set(raw_by_name) != set(tests):
        failures.append(f"{prefix}:raw_junit_test_set")
    if any(case.get("classname") != EXPECTED_CLASSNAME for case in raw_cases):
        failures.append(f"{prefix}:raw_junit_classname")
    for name in set(raw_by_name) & set(cases):
        raw_case = raw_by_name[name]
        summary_case = cases[name]
        if (
            summary_case.get("status") != raw_case["status"]
            or summary_case.get("classname", "") != raw_case["classname"]
            or summary_case.get("detail") != raw_case["detail"]
            or summary_case.get("failure_type") != raw_case["failure_type"]
        ):
            failures.append(f"{prefix}:raw_summary_mismatch:{name}")
        for marker in (_FAILURE_DETAIL_MARKERS.get(name, ()) if failed else ()):
            if marker not in raw_case["raw_detail"]:
                failures.append(f"{prefix}:raw_detail_marker:{name}")


def _validate_receipt_bindings(
    root: Path,
    phases: dict[str, dict[str, Any]],
    receipt: dict[str, Any],
    failures: list[str],
) -> None:
    bindings = receipt.get("bindings")
    if not isinstance(bindings, dict) or set(bindings) != _BINDING_KEYS:
        failures.append("receipt:bindings_keys")
        bindings = bindings if isinstance(bindings, dict) else {}
    for key in _BINDING_KEYS:
        if not _is_sha256(bindings.get(key)):
            failures.append(f"receipt:binding_shape:{key}")

    file_bindings = {
        "arg5_claim_mutation_sha256": root / "arg5_claim_mutation.json",
        "environment_sha256": root / "environment.json",
    }
    for key, path in file_bindings.items():
        if not path.is_file() or bindings.get(key) != _sha_file(path):
            failures.append(f"receipt:binding_file:{key}")

    actual_frozen_judge_sha = _sha_file(Path(frozen_judge.__file__).resolve())
    if actual_frozen_judge_sha != FROZEN_JUDGE_SHA256:
        failures.append("validator:frozen_judge_source_drift")
    if bindings.get("targeted_judge_sha256") != FROZEN_JUDGE_SHA256:
        failures.append("receipt:frozen_judge_sha256")
    if bindings.get("preregistration_sha256") != FROZEN_PREREG_SHA256:
        failures.append("receipt:frozen_prereg_sha256")

    mutation = _read_json(root / "arg5_claim_mutation.json", failures)
    if mutation.get("schema_version") != "lakatotree-targeted-source-mutation/v1":
        failures.append("mutation:schema_version")
    if mutation.get("mutation_id") != "arg5-remove-on-create-claim":
        failures.append("mutation:id")
    if mutation.get("source") != "server/contexts/tree/evidence_claim_service.py":
        failures.append("mutation:source")
    if not _exact_int(mutation.get("replacements"), 1):
        failures.append("mutation:replacements")
    if mutation.get("marker_removed") is not True:
        failures.append("mutation:marker_removed")
    if mutation.get("canonical_worktree_mutated") is not False:
        failures.append("mutation:canonical_worktree_mutated")
    before_sha = mutation.get("source_before_sha256")
    after_sha = mutation.get("source_after_sha256")
    if (
        not _is_sha256(before_sha)
        or not _is_sha256(after_sha)
        or before_sha == after_sha
    ):
        failures.append("mutation:source_sha256")
    if bindings.get("service_sha256") != before_sha:
        failures.append("receipt:service_sha256")
    if bindings.get("targeted_negative_service_sha256") != after_sha:
        failures.append("receipt:targeted_negative_service_sha256")

    source_binding = {
        "positive": "service_sha256",
        "negative_historical_arg_1_4": "historical_negative_service_sha256",
        "negative_targeted_arg_5_claim": "targeted_negative_service_sha256",
        "restored_positive": "service_sha256",
    }
    producer = receipt.get("producer")
    if not isinstance(producer, dict):
        failures.append("receipt:producer")
        producer = {}
    git_head = producer.get("git_head")
    if not isinstance(git_head, str) or re.fullmatch(r"[0-9a-f]{40}", git_head) is None:
        failures.append("receipt:producer_git_head")
    if producer.get("entrypoint") != "ooptdd_receipts/ARGUMENT_INTEGRITY/real_harness.py":
        failures.append("receipt:producer_entrypoint")
    if producer.get("sha256") != bindings.get("producer_sha256"):
        failures.append("receipt:producer_sha256")
    if producer.get("working_tree_dirty") is not False:
        failures.append("receipt:working_tree_dirty")
    if isinstance(git_head, str) and receipt.get("receipt_id") != f"argument-integrity-{git_head[:12]}":
        failures.append("receipt:id")

    for phase_name, phase in phases.items():
        prefix = "targeted" if phase_name == "negative_targeted_arg_5_claim" else phase_name
        if phase.get("environment_sha256") != bindings.get("environment_sha256"):
            failures.append(f"{prefix}:environment_sha256")
        if phase.get("requirements_sha256") != bindings.get("requirements_sha256"):
            failures.append(f"{prefix}:requirements_sha256")
        if phase.get("harness_sha256") != bindings.get("harness_sha256"):
            failures.append(f"{prefix}:harness_sha256")
        if phase.get("source_sha256") != bindings.get(source_binding[phase_name]):
            failures.append(f"{prefix}:source_sha256")
        if not _is_sha256(phase.get("output_sha256")):
            failures.append(f"{prefix}:output_sha256")
        duration = phase.get("duration_seconds")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or duration < 0:
            failures.append(f"{prefix}:duration_seconds")
        if not isinstance(phase.get("command"), list) or not phase.get("command"):
            failures.append(f"{prefix}:command")

    if isinstance(git_head, str):
        if phases["positive"].get("source_revision") != git_head:
            failures.append("positive:source_revision")
        if phases["restored_positive"].get("source_revision") != git_head:
            failures.append("restored_positive:source_revision")
        if phases["negative_targeted_arg_5_claim"].get("source_revision") != (
            f"{git_head}+mutation:arg5-remove-on-create-claim"
        ):
            failures.append("targeted:source_revision")
    historical_revision = phases["negative_historical_arg_1_4"].get("source_revision")
    if not isinstance(historical_revision, str) or re.fullmatch(
        r"[0-9a-f]{40}", historical_revision
    ) is None:
        failures.append("negative_historical_arg_1_4:source_revision")

    environment = _read_json(root / "environment.json", failures)
    if environment.get("schema_version") != "lakatotree-requirements-harness-environment/v1":
        failures.append("environment:schema_version")
    if environment.get("datastore_environment_values_recorded") is not False:
        failures.append("environment:secret_values_recorded")
    if ((environment.get("preflight") or {}).get("ready")) is not True:
        failures.append("environment:preflight_not_ready")
    if ((environment.get("docker") or {}).get("reachable")) is not True:
        failures.append("environment:docker_not_reachable")
    inputs = environment.get("inputs")
    if not isinstance(inputs, dict):
        failures.append("environment:inputs")
        inputs = {}
    for path, binding_key in _REQUIRED_ENV_INPUT_BINDINGS.items():
        entry = inputs.get(path)
        if not isinstance(entry, dict) or entry.get("sha256") != bindings.get(binding_key):
            failures.append(f"environment:input_binding:{path}")


def _validate_bundle_manifest(root: Path, failures: list[str]) -> None:
    manifest = _read_json(root / "bundle_manifest.json", failures)
    if manifest.get("schema_version") != "lakatotree-requirements-harness-bundle/v1":
        failures.append("bundle_manifest:schema_version")
    raw_entries = manifest.get("files")
    if not isinstance(raw_entries, list):
        failures.append("bundle_manifest:files")
        raw_entries = []
    entries: dict[str, dict[str, Any]] = {}
    for entry in raw_entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            failures.append("bundle_manifest:entry_shape")
            continue
        path = entry["path"]
        if path in entries:
            failures.append("bundle_manifest:duplicate_path")
        entries[path] = entry
    if set(entries) != _BUNDLE_FILES:
        failures.append("bundle_manifest:path_set")
    actual_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }
    if actual_files != _BUNDLE_FILES | {"bundle_manifest.json"}:
        failures.append("bundle_manifest:artifact_set")
    for filename in _BUNDLE_FILES:
        path = root / filename
        entry = entries.get(filename, {})
        if not path.is_file():
            failures.append(f"bundle_manifest:missing:{filename}")
            continue
        if not _exact_int(entry.get("bytes"), path.stat().st_size):
            failures.append(f"bundle_manifest:bytes:{filename}")
        if entry.get("sha256") != _sha_file(path):
            failures.append(f"bundle_manifest:sha256:{filename}")


def validate_bundle(artifact_dir: str | Path) -> dict[str, Any]:
    root = Path(artifact_dir).resolve()
    failures: list[str] = []
    phases: dict[str, dict[str, Any]] = {}
    for phase_name, filename in PHASE_FILES:
        phase = _read_json(root / filename, failures)
        phase["_artifact_root"] = str(root)
        phases[phase_name] = phase
        _validate_phase(phase, phase_name, failures)

    receipt_path = root / "receipt.json"
    receipt = _read_json(receipt_path, failures)
    if receipt.get("schema_version") != "lakatotree-requirements-harness-receipt/v2":
        failures.append("receipt:schema_version")
    if receipt.get("complete") is not True:
        failures.append("receipt:incomplete")
    if receipt.get("canonical_worktree_mutated") is not False:
        failures.append("receipt:canonical_worktree_mutated")
    if receipt.get("tier") != "L_IDE":
        failures.append("receipt:tier")
    requirements = receipt.get("requirements")
    if not isinstance(requirements, dict) or requirements.get("ids") != [
        "ARG-1",
        "ARG-2",
        "ARG-3",
        "ARG-4",
        "ARG-5",
    ]:
        failures.append("receipt:requirements_ids")
    if not isinstance(requirements, dict) or requirements.get("spec") != (
        "ooptdd_receipts/ARGUMENT_INTEGRITY/requirements.yaml"
    ):
        failures.append("receipt:requirements_spec")
    if not isinstance(receipt.get("claim_boundary"), str) or not receipt.get(
        "claim_boundary"
    ):
        failures.append("receipt:claim_boundary")

    _validate_receipt_bindings(root, phases, receipt, failures)

    sequence = receipt.get("sequence")
    if not isinstance(sequence, list) or len(sequence) != len(PHASE_FILES):
        failures.append("receipt:sequence_shape")
        sequence = []
    ordered_phases = [
        item.get("phase") if isinstance(item, dict) else None for item in sequence
    ]
    if ordered_phases != [phase for phase, _ in PHASE_FILES]:
        failures.append("receipt:sequence_order")
    by_phase = {
        str(item.get("phase")): item for item in sequence if isinstance(item, dict)
    }
    if set(by_phase) != {phase for phase, _ in PHASE_FILES}:
        failures.append("receipt:sequence_phases")
    for phase_name, filename in PHASE_FILES:
        item = by_phase.get(phase_name, {})
        phase = phases[phase_name]
        if (
            item.get("path") != filename
            or item.get("expected") != phase.get("expected")
            or item.get("observed") != phase.get("observed")
            or item.get("accepted") is not True
            or phase.get("accepted") is not True
        ):
            failures.append(f"receipt_sequence_contract:{phase_name}")
        path = root / filename
        if not path.is_file() or item.get("sha256") != _sha_file(path):
            failures.append(f"receipt_sequence_sha:{phase_name}")

    judge_binding = receipt.get("judge")
    if not isinstance(judge_binding, dict):
        failures.append("judge:receipt_binding")
        judge_binding = {}
    if judge_binding.get("path") != "judge.json":
        failures.append("judge:path")
    judge_path = root / "judge.json"
    judge = _read_json(judge_path, failures) if judge_path.is_file() else {}
    if not judge_path.is_file():
        failures.append("judge:missing")
    elif judge_binding.get("sha256") != _sha_file(judge_path):
        failures.append("judge:sha256")
    if not _exact_int(judge_binding.get("exit_code"), 0):
        failures.append("judge:exit_code")
    if not _exact_int(judge_binding.get("metric"), 0):
        failures.append("judge:receipt_metric")
    if judge_binding.get("metric_name") != frozen_judge.METRIC_NAME:
        failures.append("judge:receipt_metric_name")
    expected_judge = frozen_judge.judge(root)
    if judge != expected_judge:
        failures.append("judge:frozen_replay")
    if (
        judge.get("schema_version") != "lakatotree-judge-result/v1"
        or judge.get("experiment_id") != FROZEN_EXPERIMENT_ID
        or judge.get("metric_name") != frozen_judge.METRIC_NAME
        or not _exact_int(judge.get("metric"), 0)
        or judge.get("direction") != "lower"
        or not _exact_int(judge.get("threshold"), 0)
        or not _exact_int(judge.get("noise_band"), 0)
        or judge.get("status") != "PASS"
    ):
        failures.append("judge:result")
    if judge.get("failures") != []:
        failures.append("judge:failures")

    _validate_bundle_manifest(root, failures)

    unique = sorted(set(failures))
    return {
        "schema_version": "lakatotree-bundle-validation/v1",
        "valid": not unique,
        "gap_count": len(unique),
        "failures": unique,
        "receipt_sha256": _sha_file(receipt_path) if receipt_path.is_file() else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = validate_bundle(args.artifact_dir)
    encoded = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
