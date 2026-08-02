"""Structural false-green attacks against the ARG-5 v2 bundle validator."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import pytest

from judges import argument_integrity_bundle_validator_v2 as validator
from tests._argument_integrity_v2_fixture import (
    build_bundle,
    activate_frozen_toolchain,
    rebind_judge_input,
    refresh_manifest,
    sha,
    write_json,
)


@pytest.fixture(autouse=True)
def _frozen_arg5_toolchain(tmp_path, monkeypatch):
    activate_frozen_toolchain(tmp_path, monkeypatch)


def _validate(root, protocol_path, activation_path):
    return validator.validate_bundle(
        root, protocol_path=protocol_path, activation_path=activation_path
    )


def _rebind_fake_pass(root, protocol, *, activation_sha=None):
    judge_input_sha = sha(root / "judge_input.json")
    judge_path = root / "judge.json"
    judge = json.loads(judge_path.read_text(encoding="utf-8"))
    judge["metric"] = 0
    judge["status"] = "PASS"
    judge["failures"] = []
    judge["judge_input_sha256"] = judge_input_sha
    if activation_sha is not None:
        judge["activation_sha256"] = activation_sha
    write_json(judge_path, judge)
    receipt_path = root / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["complete"] = True
    receipt["judge_input_sha256"] = judge_input_sha
    receipt["judge"]["result_sha256"] = sha(judge_path)
    receipt["judge"]["metric"] = 0
    receipt["judge"]["exit_code"] = 0
    if activation_sha is not None:
        receipt["activation_sha256"] = activation_sha
    write_json(receipt_path, receipt)
    refresh_manifest(root, protocol)


def test_validator_accepts_exact_bundle_without_issuing_verdict(tmp_path):
    root, protocol_path, activation_path = build_bundle(tmp_path)

    result = _validate(root, protocol_path, activation_path)

    assert result["valid"] is True
    assert result["gap_count"] == 0
    assert result["failures"] == []
    assert set(result) == {
        "schema_version",
        "valid",
        "gap_count",
        "failures",
        "receipt_sha256",
    }


def test_validator_rejects_rehashed_fake_boolean_zero_judge(tmp_path):
    root, protocol_path, activation_path = build_bundle(tmp_path)
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    judge_path = root / "judge.json"
    judge = json.loads(judge_path.read_text(encoding="utf-8"))
    judge["metric"] = False
    write_json(judge_path, judge)
    receipt_path = root / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["judge"]["metric"] = False
    receipt["judge"]["result_sha256"] = sha(judge_path)
    write_json(receipt_path, receipt)
    refresh_manifest(root, protocol)

    result = _validate(root, protocol_path, activation_path)

    assert result["valid"] is False
    assert "judge:frozen_replay" in result["failures"]
    assert "judge:result:metric" in result["failures"]
    assert "receipt:judge:metric" in result["failures"]


def test_validator_recomputes_raw_junit_despite_forged_pass_summary(tmp_path):
    root, protocol_path, activation_path = build_bundle(tmp_path)
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    xml_path = root / "positive.junit.xml"
    tree = ET.parse(xml_path)
    case = next(tree.getroot().iter("testcase"))
    failure = ET.SubElement(case, "failure", {"message": "hidden failure"})
    failure.text = "x" * 700 + "OperationalError"
    tree.write(xml_path, encoding="unicode")
    phase_path = root / "positive.json"
    phase = json.loads(phase_path.read_text(encoding="utf-8"))
    phase["accepted"] = True
    phase["junit_sha256"] = sha(xml_path)
    write_json(phase_path, phase)
    rebind_judge_input(root, "positive.junit.xml")
    rebind_judge_input(root, "positive.json")
    _rebind_fake_pass(root, protocol)

    result = _validate(root, protocol_path, activation_path)

    assert "positive:raw_infrastructure_marker" in result["failures"]
    assert "positive:raw_summary_mismatch" in result["failures"]
    assert "judge:frozen_replay" in result["failures"]


def test_validator_rejects_nested_extra_and_symlinked_artifacts(tmp_path):
    root, protocol_path, activation_path = build_bundle(tmp_path)
    nested = root / "nested"
    nested.mkdir()
    (nested / "smuggled.txt").write_text("extra", encoding="utf-8")

    nested_result = _validate(root, protocol_path, activation_path)

    assert "bundle_manifest:artifact_set" in nested_result["failures"]
    assert "bundle_manifest:non_regular_entry" in nested_result["failures"]

    (nested / "smuggled.txt").unlink()
    nested.rmdir()
    target = tmp_path / "outside-positive.json"
    target.write_bytes((root / "positive.json").read_bytes())
    (root / "positive.json").unlink()
    (root / "positive.json").symlink_to(target)

    symlink_result = _validate(root, protocol_path, activation_path)

    assert "bundle_manifest:non_regular_entry" in symlink_result["failures"]
