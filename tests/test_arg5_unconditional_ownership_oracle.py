"""Adversarial synthetic tests for the frozen ARG-5 v2 judge."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET

from judges import arg5_unconditional_ownership_oracle as oracle
from tests._argument_integrity_v2_fixture import (
    build_bundle,
    rebind_judge_input,
    sha,
    write_json,
)


def _judge(root, protocol_path, activation_path):
    return oracle.judge(
        root, protocol_path=protocol_path, activation_path=activation_path
    )


def test_oracle_accepts_exact_preregistered_semantic_sequence(tmp_path):
    root, protocol_path, activation_path = build_bundle(tmp_path)

    result = _judge(root, protocol_path, activation_path)

    assert result["metric"] == 0
    assert result["status"] == "PASS"
    assert result["scientific_status"] == "UNJUDGED"
    assert result["failures"] == []


def test_oracle_rejects_missing_full_raw_idempotent_signature(tmp_path):
    root, protocol_path, activation_path = build_bundle(tmp_path)
    xml_path = root / "negative.junit.xml"
    tree = ET.parse(xml_path)
    failure = next(tree.getroot().iter("failure"))
    failure.text = "semantic schedule mismatch\nassert 0 == 1"
    tree.write(xml_path, encoding="unicode")
    phase_path = root / "negative.json"
    phase = json.loads(phase_path.read_text(encoding="utf-8"))
    phase["junit_sha256"] = sha(xml_path)
    write_json(phase_path, phase)
    rebind_judge_input(root, "negative.junit.xml")
    rebind_judge_input(root, "negative.json")

    result = _judge(root, protocol_path, activation_path)

    assert result["metric"] > 0
    assert "negative_unconditional_ownership:required_marker:idempotent" in result[
        "failures"
    ]


def test_oracle_scans_infrastructure_marker_beyond_summary_truncation(tmp_path):
    root, protocol_path, activation_path = build_bundle(tmp_path)
    xml_path = root / "negative.junit.xml"
    tree = ET.parse(xml_path)
    failure = next(tree.getroot().iter("failure"))
    failure.text = (
        "AssertionError\nassert 0 == 1\nidempotent\n"
        + "x" * 700
        + "OperationalError"
    )
    tree.write(xml_path, encoding="unicode")
    phase_path = root / "negative.json"
    phase = json.loads(phase_path.read_text(encoding="utf-8"))
    phase["junit_sha256"] = sha(xml_path)
    write_json(phase_path, phase)
    rebind_judge_input(root, "negative.junit.xml")
    rebind_judge_input(root, "negative.json")

    result = _judge(root, protocol_path, activation_path)

    assert "negative_unconditional_ownership:raw_infrastructure_marker" in result[
        "failures"
    ]


def test_oracle_rejects_boolean_exit_code_even_when_producer_accepts(tmp_path):
    root, protocol_path, activation_path = build_bundle(tmp_path)
    phase_path = root / "positive.json"
    phase = json.loads(phase_path.read_text(encoding="utf-8"))
    phase["exit_code"] = False
    phase["accepted"] = True
    write_json(phase_path, phase)
    rebind_judge_input(root, "positive.json")

    result = _judge(root, protocol_path, activation_path)

    assert "positive:exit_code" in result["failures"]


def test_oracle_rejects_assignment_marker_drift_after_rehash(tmp_path):
    root, protocol_path, activation_path = build_bundle(tmp_path)
    mutation_path = root / "mutation.json"
    mutation = json.loads(mutation_path.read_text(encoding="utf-8"))
    mutation["assignment_after_count"] = 0
    write_json(mutation_path, mutation)
    rebind_judge_input(root, "mutation.json")

    result = _judge(root, protocol_path, activation_path)

    assert "mutation:assignment_after_count" in result["failures"]
