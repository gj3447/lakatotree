"""Fail-closed guards for the ooptdd efficacy evidence consumer."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from examples import ooptdd_efficacy_20260723_programme as programme

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "examples" / "ooptdd_efficacy_20260723_programme.py"


def _record(*, measured: float = 0.0) -> dict:
    return {
        "schema": "lakato-evidence-record/v1",
        "programme": "ooptdd-efficacy-absorption",
        "conjecture": "evidence-integrity-and-arrival-benchmark-v1",
        "preregistration": {
            "registered_before_measurement": True,
            "direction": "lower",
            "predicted": {
                "metric": "unresolved_evidence_integrity_gaps",
                "value": 4.0,
                "unit": "count",
            },
            "kill_condition": "any unresolved integrity gap remains",
        },
        "measurement": {
            "metric": "unresolved_evidence_integrity_gaps",
            "value": measured,
            "unit": "count",
        },
        "provenance": {
            "grounded": True,
            "inputs": [
                {
                    "name": "recomputed-integrity-report",
                    "source": "artifacts/integrity-report.json",
                    "sha256": "digest-supplied-by-evidence-producer",
                }
            ],
        },
        "harness": {
            "script": "scripts/build_ooptdd_efficacy_evidence.py",
            "git_commit": "candidate-supplied-by-evidence-producer",
            "env": "python3.12",
        },
    }


def test_grounded_aligned_record_is_judged_by_engine_without_timestamp():
    result = programme.consume_record(_record())
    assert result["status"] == "judged"
    assert result["metric"] == "unresolved_evidence_integrity_gaps"
    assert result["measured"] == 0.0
    serialized = programme.canonical_json(result)
    assert serialized == programme.canonical_json(programme.consume_record(_record()))
    assert "timestamp" not in serialized.lower()


def test_unfavourable_engine_verdict_is_not_rewritten_or_treated_as_cli_failure(tmp_path):
    record = _record(measured=6.0)
    result = programme.consume_record(record)
    assert result["status"] == "judged"
    assert result["verdict"] == "rejected"

    path = tmp_path / "record.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), str(path)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert json.loads(completed.stdout)["verdict"] == "rejected"


def test_cli_bytes_are_independent_of_input_path_and_json_formatting(tmp_path):
    compact = tmp_path / "compact.json"
    pretty = tmp_path / "pretty.json"
    compact.write_text(json.dumps(_record(), separators=(",", ":")), encoding="utf-8")
    pretty.write_text(json.dumps(_record(), indent=4), encoding="utf-8")

    outputs = []
    for path in (compact, pretty):
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), str(path)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
        outputs.append(completed.stdout)
    assert outputs[0] == outputs[1]


@pytest.mark.parametrize(
    "mutate,needle",
    [
        (lambda rec: rec.update(verdict="progressive"), "verdict"),
        (
            lambda rec: rec["measurement"].update(derived={"pass": True}),
            "$.measurement.derived.pass",
        ),
        (
            lambda rec: rec["preregistration"].update(
                registered_before_measurement=False
            ),
            "registered-before-measurement",
        ),
        (lambda rec: rec["provenance"].update(grounded=False), "is_grounded"),
        (
            lambda rec: rec["provenance"].update(grounded="yes"),
            "exactly true",
        ),
        (
            lambda rec: rec["provenance"].update(inputs=[]),
            "grounding",
        ),
        (
            lambda rec: rec["measurement"].update(metric="different_metric"),
            "no finite aligned measurement",
        ),
    ],
)
def test_invalid_records_fail_before_record_judge(monkeypatch, mutate, needle):
    record = _record()
    mutate(record)

    def forbidden_call(_record):  # pragma: no cover - a call is the failure
        raise AssertionError("invalid evidence reached record_judge")

    monkeypatch.setattr(programme, "judge_record", forbidden_call)
    result = programme.consume_record(record)
    assert result["status"] == "invalid"
    assert needle in " ".join(result["errors"])


def test_predicted_metric_may_be_supplied_by_finite_derived_measurement():
    record = _record()
    record["measurement"] = {
        "metric": "tier0_required_oracle_match_rate",
        "value": 1.0,
        "derived": {"unresolved_evidence_integrity_gaps": 0.0},
    }
    result = programme.consume_record(record)
    assert result["status"] == "judged"
    assert result["metric"] == "unresolved_evidence_integrity_gaps"
    assert result["measured"] == 0.0


def test_distinct_preregistered_novel_measurement_can_make_progressive():
    record = _record()
    record["measurement"].update(
        primary_source_sha256="a" * 64,
        novel_measurement={
            "metric": "tier0_required_oracle_match_rate",
            "direction": "higher",
            "threshold": 1.0,
            "value": 1.0,
            "source_sha256": "b" * 64,
        },
    )
    result = programme.consume_record(record)
    assert result["status"] == "judged"
    assert result["verdict"] == "progressive"
    assert result["novel"] is True
    assert result["novel_metric"] == "tier0_required_oracle_match_rate"


def test_novel_measurement_must_be_a_distinct_bound_artifact():
    record = _record()
    record["measurement"].update(
        primary_source_sha256="a" * 64,
        novel_measurement={
            "metric": "tier0_required_oracle_match_rate",
            "direction": "higher",
            "threshold": 1.0,
            "value": 1.0,
            "source_sha256": "a" * 64,
        },
    )
    result = programme.consume_record(record)
    assert result["status"] == "invalid"
    assert "distinct source SHA-256" in " ".join(result["errors"])


def test_non_finite_or_boolean_aligned_values_are_rejected():
    for value in (float("nan"), float("inf"), True):
        record = copy.deepcopy(_record())
        record["measurement"]["value"] = value
        result = programme.consume_record(record)
        assert result["status"] == "invalid"
        assert "no finite aligned measurement" in " ".join(result["errors"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("preregistration", []),
        ("measurement", "not-an-object"),
        ("provenance", ["not-an-object"]),
        ("harness", "not-an-object"),
    ],
)
def test_malformed_nested_shapes_fail_closed_instead_of_crashing(field, value):
    record = _record()
    record[field] = value
    result = programme.consume_record(record)
    assert result["status"] == "invalid"
    assert result["errors"]


def test_unreadable_json_fails_closed_without_echoing_path(tmp_path):
    path = tmp_path / "secret-name.json"
    path.write_text("{not json", encoding="utf-8")
    result = programme.consume_record(path)
    assert result == {
        "schema": programme.OUTPUT_SCHEMA,
        "status": "invalid",
        "errors": ["unreadable evidence record: JSONDecodeError"],
    }
