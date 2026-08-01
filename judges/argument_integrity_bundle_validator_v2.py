#!/usr/bin/env python3
"""Fail-closed structural validator for the additive ARG-5 v2 bundle.

This validator is not a scientific judge.  It verifies the immutable evidence
DAG, raw JUnit semantics, frozen source inputs, and preregistration activation,
then deterministically replays the separately frozen judge.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

PROTOCOL_PATH = (
    REPO / "ooptdd_receipts/ARGUMENT_INTEGRITY/v2/harness_v2.json"
)
ACTIVATION_PATH = (
    REPO / "ooptdd_receipts/ARGUMENT_INTEGRITY/v2/activation_20260802.json"
)
PRODUCER_PATH = (
    REPO / "ooptdd_receipts/ARGUMENT_INTEGRITY/v2/real_harness_v2.py"
)
JUDGE_PATH = REPO / "judges/arg5_unconditional_ownership_oracle.py"
TARGET_TEST = "test_arg_5_create_claim_has_one_owner_and_does_not_leak"
EXPECTED_CLASSNAME = "tests.integration.test_argument_integrity_real_neo4j"
EXPERIMENT_ID = "ARG5_UNCONDITIONAL_OWNERSHIP_COMPARISON_20260802"
PHASE_FILES = (
    ("positive", "positive.json", "positive.junit.xml", "GREEN", 0),
    (
        "negative_unconditional_ownership",
        "negative.json",
        "negative.junit.xml",
        "RED",
        1,
    ),
    ("restored", "restored.json", "restored.junit.xml", "GREEN", 0),
)
INFRA_MARKERS = (
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
NEGATIVE_REQUIRED_MARKERS = ("AssertionError", "assert 0 == 1", "idempotent")
NEGATIVE_FORBIDDEN_MARKERS = (*INFRA_MARKERS, "assert 0 == 2")
EMPTY_LIST_FIELDS = (
    "infra_failures",
    "unexpected_failures",
    "missing_tests",
    "required_detail_mismatches",
)
JUDGE_INPUT_BINDINGS = {
    "protocol.json",
    "activation.json",
    "environment.json",
    "mutation.json",
    "positive.json",
    "positive.junit.xml",
    "negative.json",
    "negative.junit.xml",
    "restored.json",
    "restored.junit.xml",
}


def _sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha_file(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(r"[0-9a-f]{64}", value) is not None
    )


def _exact_int(value: Any, expected: int) -> bool:
    return type(value) is int and value == expected


def _same_json(left: Any, right: Any) -> bool:
    """Compare JSON values without Python's bool/int equality collapse."""
    return json.dumps(left, sort_keys=True, separators=(",", ":")) == json.dumps(
        right, sort_keys=True, separators=(",", ":")
    )


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


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _git_blob(commit: str, relative_path: str) -> bytes | None:
    import subprocess

    try:
        return subprocess.run(
            ["git", "show", f"{commit}:{relative_path}"],
            cwd=REPO,
            check=True,
            capture_output=True,
        ).stdout
    except subprocess.CalledProcessError:
        return None


def _validate_protocol(
    protocol_path: Path, failures: list[str]
) -> tuple[dict[str, Any], str | None]:
    protocol = _read_json(protocol_path, failures)
    protocol_sha = _sha_file(protocol_path) if protocol_path.is_file() else None
    if protocol.get("schema_version") != "lakatotree-argument-integrity-v2-protocol/v1":
        failures.append("protocol:schema_version")
    if protocol.get("experiment_id") != EXPERIMENT_ID:
        failures.append("protocol:experiment_id")
    if protocol.get("classification") != (
        "prospective_confirmatory_replication_with_prior_exposure"
    ):
        failures.append("protocol:classification")
    if protocol.get("scientific_status") != "UNJUDGED":
        failures.append("protocol:scientific_status")

    locked = protocol.get("locked_inputs")
    if not isinstance(locked, dict):
        failures.append("protocol:locked_inputs")
        locked = {}
    current = {
        "producer_sha256": PRODUCER_PATH,
        "validator_sha256": Path(__file__).resolve(),
        "legacy_helper_sha256": (
            REPO / "ooptdd_receipts/ARGUMENT_INTEGRITY/real_harness.py"
        ),
        "requirements_sha256": (
            REPO / "ooptdd_receipts/ARGUMENT_INTEGRITY/requirements.yaml"
        ),
        "dependency_lock_sha256": REPO / "uv.lock",
    }
    for key, path in current.items():
        if not path.is_file() or locked.get(key) != _sha_file(path):
            failures.append(f"protocol:current_input:{key}")

    base = protocol.get("base_source")
    if not isinstance(base, dict):
        failures.append("protocol:base_source")
        base = {}
    commit = base.get("commit")
    if not isinstance(commit, str) or re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        failures.append("protocol:base_commit")
        commit = ""
    base_paths = {
        "service_sha256": "server/contexts/tree/evidence_claim_service.py",
        "integration_test_sha256": (
            "tests/integration/test_argument_integrity_real_neo4j.py"
        ),
        "fixture_sha256": "tests/integration/conftest.py",
    }
    for key, path in base_paths.items():
        blob = _git_blob(commit, path) if commit else None
        if blob is None or locked.get(key) != _sha_bytes(blob):
            failures.append(f"protocol:base_input:{key}")

    frozen = protocol.get("frozen_v1")
    if not isinstance(frozen, dict):
        failures.append("protocol:frozen_v1")
        frozen = {}
    for name, item in frozen.items():
        if not isinstance(item, dict):
            failures.append(f"protocol:frozen_v1_shape:{name}")
            continue
        path_value = item.get("path")
        path = REPO / path_value if isinstance(path_value, str) else Path("/")
        if not path.is_file() or item.get("sha256") != _sha_file(path):
            failures.append(f"protocol:frozen_v1_drift:{name}")

    intervention = protocol.get("intervention")
    if not isinstance(intervention, dict):
        failures.append("protocol:intervention")
        intervention = {}
    service_blob = _git_blob(
        commit, "server/contexts/tree/evidence_claim_service.py"
    ) if commit else None
    if service_blob is not None:
        old = str(intervention.get("old_bytes") or "").encode()
        new = str(intervention.get("new_bytes") or "").encode()
        assignment = str(intervention.get("assignment_bytes") or "").encode()
        if (service_blob.count(old), service_blob.count(new), service_blob.count(assignment)) != (
            1,
            0,
            1,
        ):
            failures.append("protocol:intervention_markers")
        mutated = service_blob.replace(old, new, 1)
        if intervention.get("expected_postimage_sha256") != _sha_bytes(mutated):
            failures.append("protocol:intervention_postimage")
    return protocol, protocol_sha


def _validate_activation(
    activation_path: Path,
    protocol: dict[str, Any],
    protocol_sha: str | None,
    failures: list[str],
) -> tuple[dict[str, Any], str | None]:
    activation = _read_json(activation_path, failures)
    activation_sha = _sha_file(activation_path) if activation_path.is_file() else None
    judge_sha = _sha_file(JUDGE_PATH) if JUDGE_PATH.is_file() else None
    if judge_sha is None or not _is_sha256(judge_sha):
        failures.append("activation:judge_source_missing")
    expected = {
        "schema_version": "lakatotree-argument-integrity-v2-activation/v1",
        "experiment_id": EXPERIMENT_ID,
        "active": True,
        "scientific_status": "PREREGISTERED_UNJUDGED",
        "server_readback_verified": True,
        "protocol_sha256": protocol_sha,
        "judge_sha256": judge_sha,
    }
    for key, value in expected.items():
        actual = activation.get(key)
        if type(value) is bool:
            valid = actual is value
        else:
            valid = actual == value
        if not valid:
            failures.append(f"activation:{key}")
    registered_at = _parse_time(activation.get("server_registered_at"))
    if registered_at is None or registered_at.utcoffset() is None:
        failures.append("activation:server_registered_at")
    readback = activation.get("exact_readback")
    if not isinstance(readback, dict):
        failures.append("activation:exact_readback")
        readback = {}
    server = protocol.get("server_preregistration") or {}
    metric = protocol.get("metric") or {}
    readback_expected = {
        "tree_name": server.get("tree_name"),
        "node_tag": server.get("node_tag"),
        "metric_name": metric.get("name"),
        "direction": metric.get("direction"),
        "baseline_value": metric.get("baseline"),
        "noise_band": metric.get("noise_band"),
        "scale_type": metric.get("scale_type"),
        "judge_script_sha": expected["judge_sha256"],
        "verify_ok": True,
        "rederived": None,
        "cached_verdict": None,
    }
    for key, value in readback_expected.items():
        actual = readback.get(key)
        if type(value) is bool:
            valid = actual is value
        elif type(value) is int:
            valid = _exact_int(actual, value)
        else:
            valid = actual == value
        if not valid:
            failures.append(f"activation:readback:{key}")
    head = readback.get("receipt_chain_head")
    if not _is_sha256(head) or readback.get("prediction_receipt_sha") != head:
        failures.append("activation:receipt_chain_head")
    evidence = activation.get("evidence")
    contract_paths = (protocol.get("activation_contract") or {}).get(
        "evidence_paths"
    )
    if not isinstance(evidence, dict) or not isinstance(contract_paths, dict):
        failures.append("activation:evidence")
        evidence = {}
        contract_paths = {}
    required_evidence = {
        "preregistration_request",
        "server_response",
        "receipts_readback",
        "receipts_verify",
    }
    if set(evidence) != required_evidence or set(contract_paths) != required_evidence:
        failures.append("activation:evidence_keys")
    for name in sorted(required_evidence):
        item = evidence.get(name)
        expected_path = contract_paths.get(name)
        if (
            not isinstance(item, dict)
            or item.get("path") != expected_path
            or not _is_sha256(item.get("sha256"))
        ):
            failures.append(f"activation:evidence_shape:{name}")
            continue
        if activation_path.resolve() == ACTIVATION_PATH.resolve():
            path = REPO / expected_path
        else:
            path = activation_path.parent / Path(str(expected_path)).name
        if (
            not path.is_file()
            or path.is_symlink()
            or item.get("sha256") != _sha_file(path)
        ):
            failures.append(f"activation:evidence_hash:{name}")
    return activation, activation_sha


def _raw_junit(path: Path, prefix: str, failures: list[str]) -> list[dict[str, Any]]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        failures.append(f"{prefix}:raw_junit:{type(exc).__name__}")
        return []
    cases: list[dict[str, Any]] = []
    for node in root.iter("testcase"):
        status = "passed"
        detail = None
        failure_type = None
        raw_detail = ""
        for child_name, child_status in (
            ("failure", "failed"),
            ("error", "error"),
            ("skipped", "skipped"),
        ):
            child = node.find(child_name)
            if child is not None:
                status = child_status
                message = child.get("message") or ""
                body = child.text or ""
                failure_type = child.get("type")
                detail = (message or body)[:500]
                raw_detail = "\n".join(
                    value for value in (failure_type or "", message, body) if value
                )
                break
        cases.append(
            {
                "name": node.get("name", ""),
                "classname": node.get("classname", ""),
                "status": status,
                "detail": detail,
                "failure_type": failure_type,
                "raw_detail": raw_detail,
            }
        )
    names = [case["name"] for case in cases]
    if len(names) != len(set(names)):
        failures.append(f"{prefix}:raw_junit_duplicate_case")
    if any(marker in case["raw_detail"] for case in cases for marker in INFRA_MARKERS):
        failures.append(f"{prefix}:raw_infrastructure_marker")
    return cases


def _validate_phase(
    root: Path,
    phase: dict[str, Any],
    *,
    phase_name: str,
    junit_filename: str,
    expected: str,
    exit_code: int,
    protocol: dict[str, Any],
    protocol_sha: str | None,
    environment_sha: str,
    failures: list[str],
) -> None:
    prefix = phase_name
    observed = expected
    if phase.get("schema_version") != "lakatotree-requirements-harness-run/v1":
        failures.append(f"{prefix}:schema_version")
    exact = {
        "phase": phase_name,
        "expected": expected,
        "observed": observed,
        "accepted": True,
        "execution_ok": True,
        "exit_code": exit_code,
        "timed_out": False,
        "canonical_worktree_mutated": False,
        "environment_sha256": environment_sha,
        "protocol_sha256": protocol_sha,
        "producer_sha256": (protocol.get("locked_inputs") or {}).get(
            "producer_sha256"
        ),
        "junit_path": junit_filename,
    }
    for key, value in exact.items():
        actual = phase.get(key)
        if type(value) is bool:
            valid = actual is value
        elif type(value) is int:
            valid = _exact_int(actual, value)
        else:
            valid = actual == value
        if not valid:
            failures.append(f"{prefix}:{key}")
    for field in EMPTY_LIST_FIELDS:
        if phase.get(field) != []:
            failures.append(f"{prefix}:{field}")
    duration = phase.get("duration_seconds")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or duration < 0:
        failures.append(f"{prefix}:duration_seconds")
    if not _is_sha256(phase.get("output_sha256")):
        failures.append(f"{prefix}:output_sha256")

    commit = (protocol.get("base_source") or {}).get("commit")
    service_sha = (protocol.get("locked_inputs") or {}).get("service_sha256")
    mutation = protocol.get("intervention") or {}
    expected_revision = (
        f"{commit}+mutation:{mutation.get('mutation_id')}"
        if expected == "RED"
        else commit
    )
    expected_source = (
        mutation.get("expected_postimage_sha256") if expected == "RED" else service_sha
    )
    if phase.get("source_revision") != expected_revision:
        failures.append(f"{prefix}:source_revision")
    if phase.get("source_sha256") != expected_source:
        failures.append(f"{prefix}:source_sha256")

    command = phase.get("command")
    selector = (
        "tests/integration/test_argument_integrity_real_neo4j.py::" + TARGET_TEST
    )
    if (
        not isinstance(command, list)
        or any(not isinstance(item, str) for item in command)
        or len(command) != 8
        or command[1:6] != ["-m", "pytest", "-q", "-p", "no:cacheprovider"]
        or command[5] != "no:cacheprovider"
        or command[6] != selector
        or not command[7].startswith("--junitxml=")
        or not command[7].endswith(f"/{junit_filename}")
    ):
        failures.append(f"{prefix}:command")

    junit_path = root / junit_filename
    if not junit_path.is_file() or phase.get("junit_sha256") != _sha_file(junit_path):
        failures.append(f"{prefix}:junit_sha256")
    raw_cases = _raw_junit(junit_path, prefix, failures)
    if len(raw_cases) != 1 or {case["name"] for case in raw_cases} != {TARGET_TEST}:
        failures.append(f"{prefix}:raw_test_set")
    raw_case = raw_cases[0] if len(raw_cases) == 1 else {}
    required_status = "failed" if expected == "RED" else "passed"
    if raw_case.get("classname") != EXPECTED_CLASSNAME:
        failures.append(f"{prefix}:raw_classname")
    if raw_case.get("status") != required_status:
        failures.append(f"{prefix}:raw_status")

    junit = phase.get("junit")
    if not isinstance(junit, dict):
        failures.append(f"{prefix}:junit")
        junit = {}
    expected_counts = {
        "present": True,
        "tests": 1,
        "passed": 0 if expected == "RED" else 1,
        "failed": 1 if expected == "RED" else 0,
        "errors": 0,
        "skipped": 0,
    }
    for key, value in expected_counts.items():
        actual = junit.get(key)
        valid = actual is value if type(value) is bool else _exact_int(actual, value)
        if not valid:
            failures.append(f"{prefix}:junit_{key}")
    summary_cases = junit.get("cases")
    if not isinstance(summary_cases, list) or len(summary_cases) != 1:
        failures.append(f"{prefix}:summary_case_count")
        summary_case = {}
    else:
        summary_case = summary_cases[0] if isinstance(summary_cases[0], dict) else {}
    if summary_case != {key: raw_case.get(key) for key in (
        "name", "classname", "status", "detail", "failure_type"
    )}:
        failures.append(f"{prefix}:raw_summary_mismatch")
    expected_semantic = [TARGET_TEST] if expected == "RED" else []
    if phase.get("semantic_failures") != expected_semantic:
        failures.append(f"{prefix}:semantic_failures")
    if expected == "RED":
        raw_detail = str(raw_case.get("raw_detail") or "")
        for marker in NEGATIVE_REQUIRED_MARKERS:
            if marker not in raw_detail:
                failures.append(f"{prefix}:required_marker:{marker}")
        for marker in NEGATIVE_FORBIDDEN_MARKERS:
            if marker in raw_detail:
                failures.append(f"{prefix}:forbidden_marker:{marker}")


def _validate_mutation(
    mutation: dict[str, Any], protocol: dict[str, Any], failures: list[str]
) -> None:
    intervention = protocol.get("intervention") or {}
    exact = {
        "schema_version": "lakatotree-arg5-ownership-comparison-mutation/v2",
        "mutation_id": intervention.get("mutation_id"),
        "source": intervention.get("source"),
        "source_before_sha256": (protocol.get("locked_inputs") or {}).get(
            "service_sha256"
        ),
        "source_after_sha256": intervention.get("expected_postimage_sha256"),
        "comparison_before_count": 1,
        "comparison_after_count": 0,
        "unconditional_before_count": 0,
        "unconditional_after_count": 1,
        "assignment_before_count": 1,
        "assignment_after_count": 1,
        "replacements": 1,
        "canonical_worktree_mutated": False,
    }
    for key, value in exact.items():
        actual = mutation.get(key)
        if type(value) is bool:
            valid = actual is value
        elif type(value) is int:
            valid = _exact_int(actual, value)
        else:
            valid = actual == value
        if not valid:
            failures.append(f"mutation:{key}")


def _validate_environment(
    environment: dict[str, Any],
    activation: dict[str, Any],
    protocol: dict[str, Any],
    protocol_sha: str | None,
    failures: list[str],
) -> None:
    if environment.get("schema_version") != (
        "lakatotree-argument-integrity-v2-environment/v1"
    ):
        failures.append("environment:schema_version")
    if environment.get("datastore_environment_values_recorded") is not False:
        failures.append("environment:secret_values_recorded")
    if environment.get("declared_images") != (protocol.get("runtime") or {}).get(
        "images"
    ):
        failures.append("environment:declared_images")
    preflight = environment.get("preflight")
    if not isinstance(preflight, dict) or preflight.get("ready") is not True:
        failures.append("environment:preflight")
        preflight = {}
    if preflight.get("protocol_sha256") != protocol_sha:
        failures.append("environment:protocol_sha256")
    if not _same_json(preflight.get("activation"), activation):
        failures.append("environment:activation")
    checks = preflight.get("checks")
    if not isinstance(checks, dict):
        failures.append("environment:preflight_checks")
        checks = {}
    required_checks = {
        "protocol_schema",
        "experiment_id",
        "replication_classification",
        "server_scientific_status",
        "canonical_worktree_clean",
        "python_3_14",
        "package:testcontainers",
        "package:docker",
        "package:neo4j",
        "package:psycopg2-binary",
        "base_commit_present",
        "producer_sha256",
        "validator_sha256",
        "legacy_helper_sha256",
        "requirements_sha256",
        "dependency_lock_sha256",
        "service_sha256",
        "integration_test_sha256",
        "fixture_sha256",
        "expected_postimage_sha256",
        "activation_present",
        "activation_schema",
        "activation_enabled",
        "activation_protocol_sha256",
        "activation_judge_present",
        "activation_judge_sha256",
        "activation_server_readback_verified",
        "activation_scientific_status",
        "activation_registered_at",
        "activation_readback_shape",
        "activation_readback_tree",
        "activation_readback_tag",
        "activation_readback_metric",
        "activation_readback_direction",
        "activation_readback_baseline",
        "activation_readback_noise",
        "activation_readback_scale",
        "activation_readback_judge",
        "activation_readback_verify",
        "activation_readback_unjudged",
        "activation_readback_head",
        "activation_evidence_shape",
        "activation_evidence_keys",
        "docker_reachable",
    }
    for name in (
        "preregistration_request",
        "server_response",
        "receipts_readback",
        "receipts_verify",
    ):
        required_checks.add(f"activation_evidence_shape:{name}")
        required_checks.add(f"activation_evidence_hash:{name}")
    for tag in ((protocol.get("runtime") or {}).get("images") or {}):
        required_checks.add(f"docker_image_digest:{tag}")
    if set(preflight.get("required_checks") or []) != required_checks:
        failures.append("environment:required_checks")
    if set(checks) != required_checks | {
        "comparison_marker_count",
        "assignment_marker_count",
    }:
        failures.append("environment:preflight_check_set")
    for key in required_checks:
        if checks.get(key) is not True:
            failures.append(f"environment:preflight_check:{key}")
    if not _exact_int(checks.get("comparison_marker_count"), 1):
        failures.append("environment:comparison_marker_count")
    if not _exact_int(checks.get("assignment_marker_count"), 1):
        failures.append("environment:assignment_marker_count")
    packages = environment.get("packages")
    required_packages = {
        "testcontainers",
        "docker",
        "neo4j",
        "psycopg2-binary",
    }
    if (
        not isinstance(packages, dict)
        or set(packages) != required_packages
        or any(
            not isinstance(packages.get(name), str) or not packages[name]
            for name in required_packages
        )
    ):
        failures.append("environment:packages")
    docker = environment.get("docker")
    if not isinstance(docker, dict) or docker.get("reachable") is not True:
        failures.append("environment:docker")
        docker = {}
    images = docker.get("images") if isinstance(docker, dict) else {}
    if not isinstance(images, dict):
        failures.append("environment:docker_images")
        images = {}
    for tag, digest in ((protocol.get("runtime") or {}).get("images") or {}).items():
        image = images.get(tag)
        if (
            not isinstance(image, dict)
            or image.get("present") is not True
            or digest not in (image.get("repo_digests") or [])
        ):
            failures.append(f"environment:image_digest:{tag}")
    locked = protocol.get("locked_inputs") or {}
    archive_readback = environment.get("archive_readback")
    if not isinstance(archive_readback, dict):
        failures.append("environment:archive_readback")
        archive_readback = {}
    expected_archive = {
        key: locked.get(key)
        for key in (
            "service_sha256",
            "integration_test_sha256",
            "fixture_sha256",
        )
    }
    for name in ("positive", "mutated_preimage"):
        if not _same_json(archive_readback.get(name), expected_archive):
            failures.append(f"environment:archive_readback:{name}")
    postflight = environment.get("postflight")
    if not isinstance(postflight, dict):
        failures.append("environment:postflight")
        postflight = {}
    expected_postflight = {
        "head": preflight.get("canonical_head"),
        "status_sha256": preflight.get("canonical_status_sha256"),
        "clean": True,
        "matches_preflight": True,
    }
    if not _same_json(postflight, expected_postflight):
        failures.append("environment:postflight_drift")


def _validate_judge_input(
    root: Path,
    judge_input: dict[str, Any],
    *,
    protocol: dict[str, Any],
    protocol_sha: str | None,
    activation_sha: str | None,
    failures: list[str],
) -> None:
    if judge_input.get("schema_version") != (
        "lakatotree-argument-integrity-v2-judge-input/v1"
    ):
        failures.append("judge_input:schema_version")
    if judge_input.get("experiment_id") != EXPERIMENT_ID:
        failures.append("judge_input:experiment_id")
    if judge_input.get("source_commit") != (protocol.get("base_source") or {}).get(
        "commit"
    ):
        failures.append("judge_input:source_commit")
    if judge_input.get("canonical_worktree_mutated") is not False:
        failures.append("judge_input:canonical_worktree_mutated")
    protocol_binding = judge_input.get("protocol") or {}
    if not _same_json(protocol_binding, {
        "path": "protocol.json",
        "source_path": "ooptdd_receipts/ARGUMENT_INTEGRITY/v2/harness_v2.json",
        "sha256": protocol_sha,
    }):
        failures.append("judge_input:protocol")
    activation_binding = judge_input.get("activation") or {}
    if not _same_json(activation_binding, {
        "path": "activation.json",
        "source_path": "ooptdd_receipts/ARGUMENT_INTEGRITY/v2/activation_20260802.json",
        "sha256": activation_sha,
    }):
        failures.append("judge_input:activation")
    producer_binding = judge_input.get("producer") or {}
    if not _same_json(producer_binding, {
        "path": "ooptdd_receipts/ARGUMENT_INTEGRITY/v2/real_harness_v2.py",
        "sha256": (protocol.get("locked_inputs") or {}).get("producer_sha256"),
        "working_tree_dirty": False,
    }):
        failures.append("judge_input:producer")
    bindings = judge_input.get("bindings")
    if not isinstance(bindings, dict) or set(bindings) != JUDGE_INPUT_BINDINGS:
        failures.append("judge_input:binding_set")
        bindings = bindings if isinstance(bindings, dict) else {}
    for filename in JUDGE_INPUT_BINDINGS:
        path = root / filename
        if not path.is_file() or bindings.get(filename) != _sha_file(path):
            failures.append(f"judge_input:binding:{filename}")

    sequence = judge_input.get("phase_sequence")
    if not isinstance(sequence, list) or len(sequence) != len(PHASE_FILES):
        failures.append("judge_input:phase_sequence_shape")
        sequence = []
    for actual, (phase, filename, junit_filename, _, _) in zip(
        sequence, PHASE_FILES, strict=False
    ):
        expected = {
            "phase": phase,
            "path": filename,
            "sha256": _sha_file(root / filename) if (root / filename).is_file() else None,
            "junit_path": junit_filename,
            "junit_sha256": (
                _sha_file(root / junit_filename)
                if (root / junit_filename).is_file()
                else None
            ),
        }
        if not _same_json(actual, expected):
            failures.append(f"judge_input:phase_sequence:{phase}")


def _validate_receipt(
    root: Path,
    receipt: dict[str, Any],
    *,
    protocol: dict[str, Any],
    protocol_sha: str | None,
    activation: dict[str, Any],
    activation_sha: str | None,
    judge_input_sha: str | None,
    judge: dict[str, Any],
    failures: list[str],
) -> None:
    expected = {
        "schema_version": "lakatotree-argument-integrity-v2-receipt/v1",
        "experiment_id": EXPERIMENT_ID,
        "complete": True,
        "scientific_status": "UNJUDGED",
        "server_result_submitted": False,
        "claim_boundary": protocol.get("claim_boundary"),
        "source_commit": (protocol.get("base_source") or {}).get("commit"),
        "protocol_sha256": protocol_sha,
        "activation_sha256": activation_sha,
        "producer_sha256": (protocol.get("locked_inputs") or {}).get(
            "producer_sha256"
        ),
        "judge_input_sha256": judge_input_sha,
        "canonical_worktree_mutated": False,
    }
    for key, value in expected.items():
        actual = receipt.get(key)
        if type(value) is bool:
            valid = actual is value
        else:
            valid = actual == value
        if not valid:
            failures.append(f"receipt:{key}")
    captured_at = _parse_time(receipt.get("captured_at"))
    registered_at = _parse_time(activation.get("server_registered_at"))
    if (
        captured_at is None
        or captured_at.utcoffset() is None
        or registered_at is None
        or captured_at <= registered_at
    ):
        failures.append("receipt:preregistration_precedence")
    judge_binding = receipt.get("judge")
    if not isinstance(judge_binding, dict):
        failures.append("receipt:judge")
        judge_binding = {}
    expected_judge = {
        "source_sha256": _sha_file(JUDGE_PATH) if JUDGE_PATH.is_file() else None,
        "result_sha256": (
            _sha_file(root / "judge.json") if (root / "judge.json").is_file() else None
        ),
        "exit_code": 0,
        "metric": 0,
    }
    for key, value in expected_judge.items():
        actual = judge_binding.get(key)
        valid = _exact_int(actual, value) if type(value) is int else actual == value
        if not valid:
            failures.append(f"receipt:judge:{key}")
    if judge.get("scientific_status") != "UNJUDGED":
        failures.append("judge:scientific_status")


def _validate_manifest(
    root: Path, protocol: dict[str, Any], failures: list[str]
) -> None:
    allowlist = protocol.get("artifact_allowlist")
    if (
        not isinstance(allowlist, list)
        or any(not isinstance(item, str) for item in allowlist)
        or len(allowlist) != len(set(allowlist))
    ):
        failures.append("bundle_manifest:protocol_allowlist")
        allowlist = []
    expected_paths = set(allowlist)
    manifest = _read_json(root / "bundle_manifest.json", failures)
    if manifest.get("schema_version") != "lakatotree-argument-integrity-v2-bundle/v1":
        failures.append("bundle_manifest:schema_version")
    raw_entries = manifest.get("files")
    if not isinstance(raw_entries, list):
        failures.append("bundle_manifest:files")
        raw_entries = []
    entries: dict[str, dict[str, Any]] = {}
    for item in raw_entries:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            failures.append("bundle_manifest:entry_shape")
            continue
        if item["path"] in entries:
            failures.append("bundle_manifest:duplicate_path")
        entries[item["path"]] = item
    if set(entries) != expected_paths:
        failures.append("bundle_manifest:path_set")
    actual_entries = list(root.rglob("*"))
    if any(path.is_symlink() or not path.is_file() for path in actual_entries):
        failures.append("bundle_manifest:non_regular_entry")
    actual_paths = {
        path.relative_to(root).as_posix()
        for path in actual_entries
        if path.is_file() and not path.is_symlink()
    }
    if actual_paths != expected_paths | {"bundle_manifest.json"}:
        failures.append("bundle_manifest:artifact_set")
    for filename in expected_paths:
        path = root / filename
        item = entries.get(filename, {})
        if not path.is_file():
            failures.append(f"bundle_manifest:missing:{filename}")
            continue
        if not _exact_int(item.get("bytes"), path.stat().st_size):
            failures.append(f"bundle_manifest:bytes:{filename}")
        if item.get("sha256") != _sha_file(path):
            failures.append(f"bundle_manifest:sha256:{filename}")


def validate_bundle(
    artifact_dir: str | Path,
    *,
    protocol_path: Path = PROTOCOL_PATH,
    activation_path: Path = ACTIVATION_PATH,
) -> dict[str, Any]:
    root = Path(artifact_dir).resolve()
    failures: list[str] = []
    protocol, protocol_sha = _validate_protocol(protocol_path, failures)
    activation, activation_sha = _validate_activation(
        activation_path, protocol, protocol_sha, failures
    )
    protocol_snapshot = root / "protocol.json"
    activation_snapshot = root / "activation.json"
    if (
        not protocol_snapshot.is_file()
        or protocol_snapshot.is_symlink()
        or protocol_sha != _sha_file(protocol_snapshot)
    ):
        failures.append("bundle:protocol_snapshot")
    if (
        not activation_snapshot.is_file()
        or activation_snapshot.is_symlink()
        or activation_sha != _sha_file(activation_snapshot)
    ):
        failures.append("bundle:activation_snapshot")

    mutation = _read_json(root / "mutation.json", failures)
    _validate_mutation(mutation, protocol, failures)
    environment = _read_json(root / "environment.json", failures)
    environment_sha = (
        _sha_file(root / "environment.json")
        if (root / "environment.json").is_file()
        else ""
    )
    _validate_environment(
        environment, activation, protocol, protocol_sha, failures
    )
    for phase_name, filename, junit_filename, expected, exit_code in PHASE_FILES:
        phase = _read_json(root / filename, failures)
        _validate_phase(
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
    judge_input_sha = _sha_file(judge_input_path) if judge_input_path.is_file() else None
    _validate_judge_input(
        root,
        judge_input,
        protocol=protocol,
        protocol_sha=protocol_sha,
        activation_sha=activation_sha,
        failures=failures,
    )

    judge_path = root / "judge.json"
    judge = _read_json(judge_path, failures)
    try:
        from judges import arg5_unconditional_ownership_oracle as frozen_judge

        expected_judge = frozen_judge.judge(
            root,
            protocol_path=protocol_path,
            activation_path=activation_path,
        )
    except (ImportError, OSError, ValueError) as exc:
        failures.append(f"judge:replay:{type(exc).__name__}")
        expected_judge = {}
    if not _same_json(judge, expected_judge):
        failures.append("judge:frozen_replay")
    metric_name = (protocol.get("metric") or {}).get("name")
    judge_expected = {
        "schema_version": "lakatotree-argument-integrity-v2-judge-result/v1",
        "experiment_id": EXPERIMENT_ID,
        "metric_name": metric_name,
        "metric": 0,
        "direction": "lower",
        "threshold": 0,
        "noise_band": 0,
        "status": "PASS",
        "scientific_status": "UNJUDGED",
        "failures": [],
        "judge_input_sha256": judge_input_sha,
        "judge_source_sha256": _sha_file(JUDGE_PATH) if JUDGE_PATH.is_file() else None,
        "protocol_sha256": protocol_sha,
        "activation_sha256": activation_sha,
    }
    for key, value in judge_expected.items():
        actual = judge.get(key)
        valid = _exact_int(actual, value) if type(value) is int else actual == value
        if not valid:
            failures.append(f"judge:result:{key}")

    receipt_path = root / "receipt.json"
    receipt = _read_json(receipt_path, failures)
    _validate_receipt(
        root,
        receipt,
        protocol=protocol,
        protocol_sha=protocol_sha,
        activation=activation,
        activation_sha=activation_sha,
        judge_input_sha=judge_input_sha,
        judge=judge,
        failures=failures,
    )
    _validate_manifest(root, protocol, failures)

    unique = sorted(set(failures))
    return {
        "schema_version": "lakatotree-argument-integrity-v2-bundle-validation/v1",
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
