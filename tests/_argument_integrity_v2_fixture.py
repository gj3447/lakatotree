"""Synthetic, no-Docker fixtures for the frozen ARG-5 v2 evidence contract."""
from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from judges import arg5_unconditional_ownership_oracle as oracle
from judges import argument_integrity_bundle_validator_v2 as validator


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def refresh_manifest(root: Path, protocol: dict) -> None:
    entries = []
    for filename in sorted(protocol["artifact_allowlist"]):
        path = root / filename
        entries.append(
            {"path": filename, "bytes": path.stat().st_size, "sha256": sha(path)}
        )
    write_json(
        root / "bundle_manifest.json",
        {
            "schema_version": "lakatotree-argument-integrity-v2-bundle/v1",
            "files": entries,
        },
    )


def rebind_judge_input(root: Path, filename: str) -> None:
    path = root / "judge_input.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["bindings"][filename] = sha(root / filename)
    for item in value["phase_sequence"]:
        if item["path"] == filename:
            item["sha256"] = sha(root / filename)
        if item["junit_path"] == filename:
            item["junit_sha256"] = sha(root / filename)
    write_json(path, value)


def rejudge_and_rebind_receipt(
    root: Path, protocol_path: Path, activation_path: Path
) -> None:
    result = oracle.judge(
        root, protocol_path=protocol_path, activation_path=activation_path
    )
    write_json(root / "judge.json", result)
    receipt_path = root / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["judge_input_sha256"] = sha(root / "judge_input.json")
    receipt["judge"]["result_sha256"] = sha(root / "judge.json")
    receipt["judge"]["metric"] = result["metric"]
    receipt["judge"]["exit_code"] = 0 if result["metric"] == 0 else 1
    receipt["complete"] = result["metric"] == 0
    write_json(receipt_path, receipt)


def _required_preflight_checks(protocol: dict) -> set[str]:
    checks = {
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
        checks.add(f"activation_evidence_shape:{name}")
        checks.add(f"activation_evidence_hash:{name}")
    for tag in protocol["runtime"]["images"]:
        checks.add(f"docker_image_digest:{tag}")
    return checks


def _activation(authority: Path, protocol: dict) -> Path:
    evidence = {}
    for name, repo_path in protocol["activation_contract"]["evidence_paths"].items():
        path = authority / Path(repo_path).name
        write_json(path, {"synthetic": True, "kind": name})
        evidence[name] = {"path": repo_path, "sha256": sha(path)}
    judge_sha = sha(Path(oracle.__file__).resolve())
    head = "a" * 64
    metric = protocol["metric"]
    server = protocol["server_preregistration"]
    activation = {
        "schema_version": "lakatotree-argument-integrity-v2-activation/v1",
        "experiment_id": protocol["experiment_id"],
        "active": True,
        "scientific_status": "PREREGISTERED_UNJUDGED",
        "server_readback_verified": True,
        "server_registered_at": "2026-08-02T00:00:00+00:00",
        "protocol_sha256": sha(validator.PROTOCOL_PATH),
        "judge_sha256": judge_sha,
        "evidence": evidence,
        "exact_readback": {
            "tree_name": server["tree_name"],
            "node_tag": server["node_tag"],
            "metric_name": metric["name"],
            "direction": metric["direction"],
            "baseline_value": metric["baseline"],
            "noise_band": metric["noise_band"],
            "scale_type": metric["scale_type"],
            "judge_script_sha": judge_sha,
            "verify_ok": True,
            "rederived": None,
            "cached_verdict": None,
            "receipt_chain_head": head,
            "prediction_receipt_sha": head,
        },
    }
    path = authority / "activation_20260802.json"
    write_json(path, activation)
    return path


def _junit(path: Path, *, failed: bool) -> dict:
    suites = ET.Element("testsuites")
    suite = ET.SubElement(suites, "testsuite")
    case = ET.SubElement(
        suite,
        "testcase",
        {"classname": validator.EXPECTED_CLASSNAME, "name": validator.TARGET_TEST},
    )
    detail = None
    if failed:
        detail = "AssertionError: assert 0 == 1"
        failure = ET.SubElement(case, "failure", {"message": detail})
        failure.text = (
            "semantic schedule mismatch\n"
            "assert 0 == 1\n"
            "where 0 = idempotent acknowledgements"
        )
    ET.ElementTree(suites).write(path, encoding="unicode")
    return {
        "present": True,
        "tests": 1,
        "passed": 0 if failed else 1,
        "failed": 1 if failed else 0,
        "errors": 0,
        "skipped": 0,
        "cases": [
            {
                "name": validator.TARGET_TEST,
                "classname": validator.EXPECTED_CLASSNAME,
                "status": "failed" if failed else "passed",
                "detail": detail,
                "failure_type": None,
            }
        ],
    }


def build_bundle(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "bundle"
    root.mkdir()
    authority = tmp_path / "authority"
    authority.mkdir()
    protocol_path = validator.PROTOCOL_PATH
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    activation_path = _activation(authority, protocol)
    activation = json.loads(activation_path.read_text(encoding="utf-8"))
    (root / "protocol.json").write_bytes(protocol_path.read_bytes())
    (root / "activation.json").write_bytes(activation_path.read_bytes())

    intervention = protocol["intervention"]
    mutation = {
        "schema_version": "lakatotree-arg5-ownership-comparison-mutation/v2",
        "mutation_id": intervention["mutation_id"],
        "source": intervention["source"],
        "source_before_sha256": protocol["locked_inputs"]["service_sha256"],
        "source_after_sha256": intervention["expected_postimage_sha256"],
        "comparison_before_count": 1,
        "comparison_after_count": 0,
        "unconditional_before_count": 0,
        "unconditional_after_count": 1,
        "assignment_before_count": 1,
        "assignment_after_count": 1,
        "replacements": 1,
        "canonical_worktree_mutated": False,
    }
    write_json(root / "mutation.json", mutation)

    required_checks = _required_preflight_checks(protocol)
    checks = {name: True for name in required_checks}
    checks["comparison_marker_count"] = 1
    checks["assignment_marker_count"] = 1
    status_sha = hashlib.sha256(b"").hexdigest()
    head = "f" * 40
    preflight = {
        "ready": True,
        "checks": checks,
        "required_checks": sorted(required_checks),
        "activation": activation,
        "docker": {"reachable": True},
        "protocol_sha256": sha(protocol_path),
        "canonical_head": head,
        "canonical_status_sha256": status_sha,
    }
    images = {
        tag: {"present": True, "repo_digests": [digest], "id": "sha256:" + "b" * 64}
        for tag, digest in protocol["runtime"]["images"].items()
    }
    locked = protocol["locked_inputs"]
    archive = {
        key: locked[key]
        for key in (
            "service_sha256",
            "integration_test_sha256",
            "fixture_sha256",
        )
    }
    environment = {
        "schema_version": "lakatotree-argument-integrity-v2-environment/v1",
        "captured_at": "2026-08-02T00:01:00+00:00",
        "python": "3.14.0",
        "implementation": "CPython",
        "platform": "synthetic",
        "packages": {
            "testcontainers": "4.0",
            "docker": "7.0",
            "neo4j": "5.0",
            "psycopg2-binary": "2.9",
        },
        "declared_images": protocol["runtime"]["images"],
        "docker": {"reachable": True, "server_version": "synthetic", "images": images},
        "preflight": preflight,
        "archive_readback": {"positive": archive, "mutated_preimage": archive},
        "postflight": {
            "head": head,
            "status_sha256": status_sha,
            "clean": True,
            "matches_preflight": True,
        },
        "datastore_environment_values_recorded": False,
    }
    write_json(root / "environment.json", environment)
    environment_sha = sha(root / "environment.json")

    phases = {}
    for phase_name, filename, junit_filename, expected, exit_code in validator.PHASE_FILES:
        failed = expected == "RED"
        junit = _junit(root / junit_filename, failed=failed)
        source_revision = protocol["base_source"]["commit"]
        source_sha = locked["service_sha256"]
        if failed:
            source_revision += "+mutation:" + intervention["mutation_id"]
            source_sha = intervention["expected_postimage_sha256"]
        selector = (
            "tests/integration/test_argument_integrity_real_neo4j.py::"
            + validator.TARGET_TEST
        )
        phase = {
            "schema_version": "lakatotree-requirements-harness-run/v1",
            "phase": phase_name,
            "expected": expected,
            "observed": expected,
            "accepted": True,
            "execution_ok": True,
            "source_revision": source_revision,
            "source_sha256": source_sha,
            "command": [
                "python",
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                selector,
                f"--junitxml={root / junit_filename}",
            ],
            "exit_code": exit_code,
            "timed_out": False,
            "duration_seconds": 0.1,
            "output_sha256": "c" * 64,
            "output_tail": "synthetic",
            "junit": junit,
            "junit_path": junit_filename,
            "junit_sha256": sha(root / junit_filename),
            "missing_tests": [],
            "semantic_failures": [validator.TARGET_TEST] if failed else [],
            "infra_failures": [],
            "unexpected_failures": [],
            "required_detail_mismatches": [],
            "canonical_worktree_mutated": False,
            "environment_sha256": environment_sha,
            "protocol_sha256": sha(protocol_path),
            "producer_sha256": locked["producer_sha256"],
        }
        write_json(root / filename, phase)
        phases[phase_name] = (filename, junit_filename)

    bindings = {
        filename: sha(root / filename)
        for filename in validator.JUDGE_INPUT_BINDINGS
    }
    sequence = []
    for phase_name, filename, junit_filename, _, _ in validator.PHASE_FILES:
        sequence.append(
            {
                "phase": phase_name,
                "path": filename,
                "sha256": sha(root / filename),
                "junit_path": junit_filename,
                "junit_sha256": sha(root / junit_filename),
            }
        )
    judge_input = {
        "schema_version": "lakatotree-argument-integrity-v2-judge-input/v1",
        "experiment_id": protocol["experiment_id"],
        "protocol": {
            "path": "protocol.json",
            "source_path": "ooptdd_receipts/ARGUMENT_INTEGRITY/v2/harness_v2.json",
            "sha256": sha(protocol_path),
        },
        "activation": {
            "path": "activation.json",
            "source_path": "ooptdd_receipts/ARGUMENT_INTEGRITY/v2/activation_20260802.json",
            "sha256": sha(activation_path),
        },
        "producer": {
            "path": "ooptdd_receipts/ARGUMENT_INTEGRITY/v2/real_harness_v2.py",
            "sha256": locked["producer_sha256"],
            "working_tree_dirty": False,
        },
        "source_commit": protocol["base_source"]["commit"],
        "bindings": bindings,
        "phase_sequence": sequence,
        "canonical_worktree_mutated": False,
    }
    write_json(root / "judge_input.json", judge_input)

    judge = oracle.judge(
        root, protocol_path=protocol_path, activation_path=activation_path
    )
    assert judge["metric"] == 0, judge["failures"]
    write_json(root / "judge.json", judge)
    receipt = {
        "schema_version": "lakatotree-argument-integrity-v2-receipt/v1",
        "experiment_id": protocol["experiment_id"],
        "captured_at": "2026-08-02T00:02:00+00:00",
        "complete": True,
        "scientific_status": "UNJUDGED",
        "server_result_submitted": False,
        "claim_boundary": protocol["claim_boundary"],
        "source_commit": protocol["base_source"]["commit"],
        "protocol_sha256": sha(protocol_path),
        "activation_sha256": sha(activation_path),
        "producer_sha256": locked["producer_sha256"],
        "judge_input_sha256": sha(root / "judge_input.json"),
        "judge": {
            "source_sha256": sha(Path(oracle.__file__).resolve()),
            "result_sha256": sha(root / "judge.json"),
            "exit_code": 0,
            "metric": 0,
        },
        "canonical_worktree_mutated": False,
    }
    write_json(root / "receipt.json", receipt)
    refresh_manifest(root, protocol)
    return root, protocol_path, activation_path
