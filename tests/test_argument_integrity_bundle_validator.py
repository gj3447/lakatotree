"""Structural false-green guards for the ARGUMENT_INTEGRITY artifact bundle."""
from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from judges import argument_integrity_bundle_validator as validator
from judges import arg5_targeted_negative_oracle as frozen_judge


_CURRENT_HEAD = "d48b860647a110399968093a87180de1094971f1"
_HISTORICAL_HEAD = "ea0301cd7121e3382b0364e112aa852134a0c11d"
_HASHES = {
    "fixture": "1" * 64,
    "harness": "2" * 64,
    "historical": "3" * 64,
    "manifest": "4" * 64,
    "producer": "5" * 64,
    "requirements": "6" * 64,
    "service": "7" * 64,
    "targeted": "8" * 64,
}


def _write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _refresh_manifest(tmp_path):
    entries = []
    for filename in sorted(validator._BUNDLE_FILES):
        path = tmp_path / filename
        entries.append(
            {
                "path": filename,
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    _write_json(
        tmp_path / "bundle_manifest.json",
        {
            "schema_version": "lakatotree-requirements-harness-bundle/v1",
            "files": entries,
        },
    )


def _phase(name, tests, *, expected, observed, environment_sha256, source_revision, source_sha256):
    failed = observed == "RED"
    cases = [
        {
            "name": test,
            "classname": validator.EXPECTED_CLASSNAME,
            "status": "failed" if failed else "passed",
            "detail": "\n".join(validator._FAILURE_DETAIL_MARKERS[test]) if failed else None,
            "failure_type": None,
        }
        for test in tests
    ]
    return {
        "schema_version": "lakatotree-requirements-harness-run/v1",
        "phase": name,
        "expected": expected,
        "observed": observed,
        "accepted": True,
        "execution_ok": True,
        "exit_code": 1 if failed else 0,
        "timed_out": False,
        "canonical_worktree_mutated": False,
        "command": ["python", "-m", "pytest"],
        "duration_seconds": 0.1,
        "environment_sha256": environment_sha256,
        "harness_sha256": _HASHES["harness"],
        "infra_failures": [],
        "unexpected_failures": [],
        "missing_tests": [],
        "required_detail_mismatches": [],
        "requirements_sha256": _HASHES["requirements"],
        "semantic_failures": list(tests) if failed else [],
        "source_revision": source_revision,
        "source_sha256": source_sha256,
        "output_sha256": "9" * 64,
        "junit": {
            "present": True,
            "tests": len(cases),
            "passed": 0 if failed else len(cases),
            "failed": len(cases) if failed else 0,
            "errors": 0,
            "skipped": 0,
            "cases": cases,
        },
    }


def _bundle(tmp_path):
    mutation = {
        "schema_version": "lakatotree-targeted-source-mutation/v1",
        "mutation_id": "arg5-remove-on-create-claim",
        "source": "server/contexts/tree/evidence_claim_service.py",
        "source_before_sha256": _HASHES["service"],
        "source_after_sha256": _HASHES["targeted"],
        "replacements": 1,
        "marker_removed": True,
        "canonical_worktree_mutated": False,
    }
    _write_json(tmp_path / "arg5_claim_mutation.json", mutation)
    environment = {
        "schema_version": "lakatotree-requirements-harness-environment/v1",
        "datastore_environment_values_recorded": False,
        "docker": {"reachable": True},
        "preflight": {"ready": True},
        "inputs": {
            "judges/arg5_targeted_negative_oracle.py": {
                "bytes": 1,
                "sha256": validator.FROZEN_JUDGE_SHA256,
            },
            "ooptdd_receipts/ARGUMENT_INTEGRITY/harness.json": {
                "bytes": 1,
                "sha256": _HASHES["manifest"],
            },
            "ooptdd_receipts/ARGUMENT_INTEGRITY/prereg_arg5_semantic_negative_20260801.json": {
                "bytes": 1,
                "sha256": validator.FROZEN_PREREG_SHA256,
            },
            "ooptdd_receipts/ARGUMENT_INTEGRITY/real_harness.py": {
                "bytes": 1,
                "sha256": _HASHES["producer"],
            },
            "ooptdd_receipts/ARGUMENT_INTEGRITY/requirements.yaml": {
                "bytes": 1,
                "sha256": _HASHES["requirements"],
            },
            "server/contexts/tree/evidence_claim_service.py": {
                "bytes": 1,
                "sha256": _HASHES["service"],
            },
            "tests/integration/conftest.py": {
                "bytes": 1,
                "sha256": _HASHES["fixture"],
            },
            "tests/integration/test_argument_integrity_real_neo4j.py": {
                "bytes": 1,
                "sha256": _HASHES["harness"],
            },
        },
    }
    _write_json(tmp_path / "environment.json", environment)
    environment_sha256 = hashlib.sha256(
        (tmp_path / "environment.json").read_bytes()
    ).hexdigest()
    phases = {
        "positive.json": _phase(
            "positive",
            validator.ALL_TESTS,
            expected="GREEN",
            observed="GREEN",
            environment_sha256=environment_sha256,
            source_revision=_CURRENT_HEAD,
            source_sha256=_HASHES["service"],
        ),
        "negative_historical.json": _phase(
            "negative_historical_arg_1_4",
            validator.HISTORICAL_TESTS,
            expected="RED",
            observed="RED",
            environment_sha256=environment_sha256,
            source_revision=_HISTORICAL_HEAD,
            source_sha256=_HASHES["historical"],
        ),
        "negative_arg5_claim.json": _phase(
            "negative_targeted_arg_5_claim",
            (validator.TARGET_TEST,),
            expected="RED",
            observed="RED",
            environment_sha256=environment_sha256,
            source_revision=f"{_CURRENT_HEAD}+mutation:arg5-remove-on-create-claim",
            source_sha256=_HASHES["targeted"],
        ),
        "restored_positive.json": _phase(
            "restored_positive",
            validator.ALL_TESTS,
            expected="GREEN",
            observed="GREEN",
            environment_sha256=environment_sha256,
            source_revision=_CURRENT_HEAD,
            source_sha256=_HASHES["service"],
        ),
    }
    junit_files = {
        "positive.json": "positive.junit.xml",
        "negative_historical.json": "negative_historical.junit.xml",
        "negative_arg5_claim.json": "negative_arg5_claim.junit.xml",
        "restored_positive.json": "restored_positive.junit.xml",
    }
    for filename, value in phases.items():
        junit_path = tmp_path / junit_files[filename]
        suites = ET.Element("testsuites")
        suite = ET.SubElement(suites, "testsuite")
        for case in value["junit"]["cases"]:
            testcase = ET.SubElement(
                suite,
                "testcase",
                {"classname": case["classname"], "name": case["name"]},
            )
            if case["status"] == "failed":
                failure = ET.SubElement(testcase, "failure")
                failure.text = case["detail"]
        ET.ElementTree(suites).write(junit_path, encoding="unicode")
        value["junit_path"] = junit_path.name
        value["junit_sha256"] = hashlib.sha256(junit_path.read_bytes()).hexdigest()
        _write_json(tmp_path / filename, value)

    sequence = []
    for phase, filename in validator.PHASE_FILES:
        value = phases[filename]
        sequence.append(
            {
                "phase": phase,
                "expected": value["expected"],
                "observed": value["observed"],
                "accepted": value["accepted"],
                "path": filename,
                "sha256": hashlib.sha256((tmp_path / filename).read_bytes()).hexdigest(),
            }
        )
    receipt = {
        "schema_version": "lakatotree-requirements-harness-receipt/v2",
        "receipt_id": f"argument-integrity-{_CURRENT_HEAD[:12]}",
        "tier": "L_IDE",
        "complete": True,
        "canonical_worktree_mutated": False,
        "claim_boundary": "synthetic validator fixture; no scientific authority",
        "bindings": {
            "arg5_claim_mutation_sha256": hashlib.sha256(
                (tmp_path / "arg5_claim_mutation.json").read_bytes()
            ).hexdigest(),
            "environment_sha256": environment_sha256,
            "fixture_sha256": _HASHES["fixture"],
            "harness_sha256": _HASHES["harness"],
            "historical_negative_service_sha256": _HASHES["historical"],
            "manifest_sha256": _HASHES["manifest"],
            "preregistration_sha256": validator.FROZEN_PREREG_SHA256,
            "producer_sha256": _HASHES["producer"],
            "requirements_sha256": _HASHES["requirements"],
            "service_sha256": _HASHES["service"],
            "targeted_judge_sha256": validator.FROZEN_JUDGE_SHA256,
            "targeted_negative_service_sha256": _HASHES["targeted"],
        },
        "producer": {
            "entrypoint": "ooptdd_receipts/ARGUMENT_INTEGRITY/real_harness.py",
            "git_head": _CURRENT_HEAD,
            "sha256": _HASHES["producer"],
            "working_tree_dirty": False,
        },
        "requirements": {
            "ids": ["ARG-1", "ARG-2", "ARG-3", "ARG-4", "ARG-5"],
            "spec": "ooptdd_receipts/ARGUMENT_INTEGRITY/requirements.yaml",
        },
        "sequence": sequence,
        "judge": {
            "path": "judge.json",
            "sha256": "0" * 64,
            "exit_code": 0,
            "metric": 0,
            "metric_name": frozen_judge.METRIC_NAME,
        },
    }
    _write_json(tmp_path / "receipt.json", receipt)
    judge = frozen_judge.judge(tmp_path)
    assert judge["status"] == "PASS"
    _write_json(tmp_path / "judge.json", judge)
    receipt["judge"]["sha256"] = hashlib.sha256(
        (tmp_path / "judge.json").read_bytes()
    ).hexdigest()
    _write_json(tmp_path / "receipt.json", receipt)

    _refresh_manifest(tmp_path)


def _rebind_phase(tmp_path, filename, phase_name):
    receipt_path = tmp_path / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    item = next(item for item in receipt["sequence"] if item["phase"] == phase_name)
    item["sha256"] = hashlib.sha256((tmp_path / filename).read_bytes()).hexdigest()
    _write_json(receipt_path, receipt)
    _refresh_manifest(tmp_path)


def test_validator_accepts_exact_structural_bundle(tmp_path):
    _bundle(tmp_path)

    result = validator.validate_bundle(tmp_path)

    assert result["valid"] is True
    assert result["gap_count"] == 0
    assert result["failures"] == []


@pytest.mark.parametrize(
    ("field", "value", "failure"),
    [
        ("execution_ok", False, "targeted:execution_not_ok"),
        ("timed_out", True, "targeted:timed_out"),
        ("infra_failures", ["arg5"], "targeted:infra_failures"),
        ("unexpected_failures", ["other"], "targeted:unexpected_failures"),
        ("missing_tests", ["arg5"], "targeted:missing_tests"),
        (
            "required_detail_mismatches",
            ["arg5"],
            "targeted:required_detail_mismatches",
        ),
    ],
)
def test_validator_rejects_structural_false_green(tmp_path, field, value, failure):
    _bundle(tmp_path)
    phase_path = tmp_path / "negative_arg5_claim.json"
    phase = json.loads(phase_path.read_text(encoding="utf-8"))
    phase[field] = value
    _write_json(phase_path, phase)
    _rebind_phase(
        tmp_path, "negative_arg5_claim.json", "negative_targeted_arg_5_claim"
    )

    result = validator.validate_bundle(tmp_path)

    assert result["valid"] is False
    assert result["gap_count"] > 0
    assert failure in result["failures"]


def test_validator_rejects_receipt_that_lies_about_phase_acceptance(tmp_path):
    _bundle(tmp_path)
    receipt_path = tmp_path / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["sequence"][2]["accepted"] = False
    _write_json(receipt_path, receipt)
    _refresh_manifest(tmp_path)

    result = validator.validate_bundle(tmp_path)

    assert result["valid"] is False
    assert "receipt_sequence_contract:negative_targeted_arg_5_claim" in result["failures"]


def test_validator_scans_raw_junit_beyond_truncated_summary(tmp_path):
    _bundle(tmp_path)
    junit_path = tmp_path / "negative_arg5_claim.junit.xml"
    padding = "x" * 700
    junit_path.write_text(
        "<testsuites><testsuite>"
        f'<testcase classname="{validator.EXPECTED_CLASSNAME}" '
        f'name="{validator.TARGET_TEST}">'
        f'<failure message="AssertionError: ownership">{padding}PoolError</failure>'
        "</testcase></testsuite></testsuites>",
        encoding="utf-8",
    )
    phase_path = tmp_path / "negative_arg5_claim.json"
    phase = json.loads(phase_path.read_text(encoding="utf-8"))
    phase["junit_sha256"] = hashlib.sha256(junit_path.read_bytes()).hexdigest()
    _write_json(phase_path, phase)
    _rebind_phase(
        tmp_path, "negative_arg5_claim.json", "negative_targeted_arg_5_claim"
    )

    result = validator.validate_bundle(tmp_path)

    assert result["valid"] is False
    assert "targeted:raw_infra_failure" in result["failures"]


def test_validator_rejects_missing_receipt_bindings(tmp_path):
    _bundle(tmp_path)
    receipt_path = tmp_path / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt.pop("bindings")
    _write_json(receipt_path, receipt)
    _refresh_manifest(tmp_path)

    result = validator.validate_bundle(tmp_path)

    assert result["valid"] is False
    assert "receipt:bindings_keys" in result["failures"]


def test_validator_rejects_fake_minimal_judge(tmp_path):
    _bundle(tmp_path)
    _write_json(
        tmp_path / "judge.json",
        {"metric": 0, "status": "PASS", "failures": []},
    )
    receipt_path = tmp_path / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["judge"]["sha256"] = hashlib.sha256(
        (tmp_path / "judge.json").read_bytes()
    ).hexdigest()
    _write_json(receipt_path, receipt)
    _refresh_manifest(tmp_path)

    result = validator.validate_bundle(tmp_path)

    assert result["valid"] is False
    assert "judge:frozen_replay" in result["failures"]


def test_validator_rejects_duplicate_summary_case(tmp_path):
    _bundle(tmp_path)
    phase_path = tmp_path / "negative_arg5_claim.json"
    phase = json.loads(phase_path.read_text(encoding="utf-8"))
    phase["junit"]["cases"].append(dict(phase["junit"]["cases"][0]))
    _write_json(phase_path, phase)
    _rebind_phase(
        tmp_path, "negative_arg5_claim.json", "negative_targeted_arg_5_claim"
    )

    result = validator.validate_bundle(tmp_path)

    assert result["valid"] is False
    assert "targeted:junit_duplicate_case" in result["failures"]


@pytest.mark.parametrize("bad_exit_code", [True, False, 2, 124])
def test_validator_rejects_non_exact_exit_code(tmp_path, bad_exit_code):
    _bundle(tmp_path)
    phase_path = tmp_path / "negative_arg5_claim.json"
    phase = json.loads(phase_path.read_text(encoding="utf-8"))
    phase["exit_code"] = bad_exit_code
    _write_json(phase_path, phase)
    _rebind_phase(
        tmp_path, "negative_arg5_claim.json", "negative_targeted_arg_5_claim"
    )

    result = validator.validate_bundle(tmp_path)

    assert result["valid"] is False
    assert "targeted:exit_code" in result["failures"]


def test_validator_rejects_individually_drifted_binding(tmp_path):
    _bundle(tmp_path)
    receipt_path = tmp_path / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["bindings"]["fixture_sha256"] = "a" * 64
    _write_json(receipt_path, receipt)
    _refresh_manifest(tmp_path)

    result = validator.validate_bundle(tmp_path)

    assert result["valid"] is False
    assert (
        "environment:input_binding:tests/integration/conftest.py"
        in result["failures"]
    )


def test_validator_rejects_rehashed_judge_with_wrong_identity(tmp_path):
    _bundle(tmp_path)
    judge_path = tmp_path / "judge.json"
    judge = json.loads(judge_path.read_text(encoding="utf-8"))
    judge["experiment_id"] = "ATTACKER_RELABELED_EXPERIMENT"
    _write_json(judge_path, judge)
    receipt_path = tmp_path / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["judge"]["sha256"] = hashlib.sha256(judge_path.read_bytes()).hexdigest()
    _write_json(receipt_path, receipt)
    _refresh_manifest(tmp_path)

    result = validator.validate_bundle(tmp_path)

    assert result["valid"] is False
    assert "judge:frozen_replay" in result["failures"]
    assert "judge:result" in result["failures"]


def test_validator_rejects_duplicate_raw_junit_case(tmp_path):
    _bundle(tmp_path)
    junit_path = tmp_path / "negative_arg5_claim.junit.xml"
    tree = ET.parse(junit_path)
    suite = next(tree.getroot().iter("testsuite"))
    original = next(suite.iter("testcase"))
    duplicate = ET.SubElement(
        suite,
        "testcase",
        {"classname": original.get("classname"), "name": original.get("name")},
    )
    failure = ET.SubElement(duplicate, "failure")
    failure.text = "\n".join(validator._FAILURE_DETAIL_MARKERS[validator.TARGET_TEST])
    tree.write(junit_path, encoding="unicode")
    phase_path = tmp_path / "negative_arg5_claim.json"
    phase = json.loads(phase_path.read_text(encoding="utf-8"))
    phase["junit_sha256"] = hashlib.sha256(junit_path.read_bytes()).hexdigest()
    _write_json(phase_path, phase)
    _rebind_phase(
        tmp_path, "negative_arg5_claim.json", "negative_targeted_arg_5_claim"
    )

    result = validator.validate_bundle(tmp_path)

    assert result["valid"] is False
    assert "targeted:raw_junit_duplicate_case" in result["failures"]
    assert "targeted:raw_junit_count" in result["failures"]


def test_validator_rejects_phase_hash_drift(tmp_path):
    _bundle(tmp_path)
    phase_path = tmp_path / "positive.json"
    phase = json.loads(phase_path.read_text(encoding="utf-8"))
    phase["duration_seconds"] = 0.2
    _write_json(phase_path, phase)
    _refresh_manifest(tmp_path)

    result = validator.validate_bundle(tmp_path)

    assert result["valid"] is False
    assert "receipt_sequence_sha:positive" in result["failures"]


def test_validator_rejects_judge_hash_drift(tmp_path):
    _bundle(tmp_path)
    judge_path = tmp_path / "judge.json"
    judge_path.write_text(judge_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    _refresh_manifest(tmp_path)

    result = validator.validate_bundle(tmp_path)

    assert result["valid"] is False
    assert "judge:sha256" in result["failures"]


def test_validator_rejects_extra_artifact(tmp_path):
    _bundle(tmp_path)
    (tmp_path / "unbound.txt").write_text("unbound\n", encoding="utf-8")

    result = validator.validate_bundle(tmp_path)

    assert result["valid"] is False
    assert "bundle_manifest:artifact_set" in result["failures"]


def test_validator_has_no_scientific_verdict_authority_and_freezes_v1_sources(tmp_path):
    _bundle(tmp_path)
    result = validator.validate_bundle(tmp_path)
    repo = Path(__file__).resolve().parents[1]

    assert set(result) == {
        "schema_version",
        "valid",
        "gap_count",
        "failures",
        "receipt_sha256",
    }
    assert not ({"verdict", "scientific_status", "progressive"} & set(result))
    assert hashlib.sha256(
        (repo / "judges/arg5_targeted_negative_oracle.py").read_bytes()
    ).hexdigest() == validator.FROZEN_JUDGE_SHA256
    assert hashlib.sha256(
        (
            repo
            / "ooptdd_receipts/ARGUMENT_INTEGRITY/prereg_arg5_semantic_negative_20260801.json"
        ).read_bytes()
    ).hexdigest() == validator.FROZEN_PREREG_SHA256
