"""Fail-closed guards for the ooptdd efficacy evidence consumer."""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from examples import ooptdd_efficacy_20260723_programme as programme

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "examples" / "ooptdd_efficacy_20260723_programme.py"
HEAD = "a" * 40
REGISTERED_AT = "2026-07-23T00:00:00Z"
PROGRAMME = "ooptdd-efficacy-absorption"
CONJECTURE = "evidence-integrity-and-arrival-benchmark-v1"
PRIMARY_METRIC = "unresolved_evidence_integrity_gaps"
NOVEL_METRIC = "tier0_required_oracle_match_rate"
SCENARIO_EXPECTED = {
    "silent-loss": "absent",
    "lag-within-window": "present",
    "truly-absent": "absent",
    "late-offender-control": "present",
    "late-offender-confirm": "absent",
    "backend-outage": "inconclusive",
    "dependent-store-demotion": "absent",
    "external-corroboration": "present",
    "trajectory-mutation": "measured",
}
SCENARIOS = tuple(SCENARIO_EXPECTED)
GAPS = (
    "nonvacuous_trajectory_mutation",
    "observation_first_aggregate_recomputation",
    "source_spec_and_file_binding",
    "deepeval_artifact_asserted_in_ci",
)
ROLE_ORDER = (
    "integrity-report",
    "tier0-positive",
    "tier0-positive-junit",
    "tier0-positive-markdown",
    "tier0-negative",
    "tier0-negative-junit",
    "tier0-negative-markdown",
    "tier0-restored",
    "tier0-restored-junit",
    "tier0-restored-markdown",
    "measurement-sequence",
    "deepeval-candidate",
    "deepeval-injected-mismatch",
    "measurement-lock",
    "preregistration",
    "github-actions-receipt",
)


@dataclass(frozen=True)
class _Bundle:
    root: Path
    record: dict
    paths: dict[str, Path]


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _label_sha(label: str) -> str:
    return _sha(label.encode())


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _artifact_suffix(role: str) -> str:
    if role.endswith("-junit"):
        return ".xml"
    if role.endswith("-markdown"):
        return ".md"
    return ".json"


def _benchmark(lock: dict, polarity: str, *, all_expected_present: bool) -> dict:
    rows = []
    for scenario_id in SCENARIOS:
        expected = "present" if all_expected_present else SCENARIO_EXPECTED[scenario_id]
        is_negative_failure = (
            polarity == "negative" and scenario_id == "late-offender-confirm"
        )
        observed = (
            "absent" if expected != "absent" else "present"
        ) if is_negative_failure else expected
        matched = observed == expected
        rows.append(
            {
                "id": scenario_id,
                "expected": expected,
                "samples": [
                    {
                        "repeat": 0,
                        "expected": expected,
                        "observed": observed,
                        "oracle_match": matched,
                    }
                ],
                "attempts": 1,
                "oracle_matches": int(matched),
                "oracle_match_rate": float(matched),
            }
        )
    rate = sum(
        sample["oracle_match"]
        for row in rows
        for sample in row["samples"]
    ) / len(rows)
    result = {
        "schema": "ooptdd-arrival-benchmark/v0",
        "tier": lock["tier"],
        "seed": lock["seed"],
        "repetitions": lock["repetitions"],
        "independent": False,
        "provenance": {
            "benchmark_definition_sha256": lock["benchmark_definition_sha256"],
            "code_manifest_sha256": lock["code_manifest_sha256"],
            "files": {
                "manifest": lock["manifest_sha256"],
                "trajectory_gate": lock["gate_spec_sha256"],
                "trajectory_events": lock["events_sha256"],
                "runner": lock["runner_sha256"],
            },
        },
        "conformance": {"portable-fixture": {"passed": True}},
        "scenarios": rows,
        "metrics": {"required_oracle_match_rate": {"value": rate}},
        "passed": polarity != "negative",
    }
    if polarity == "negative":
        result["fault_injection"] = "disable-confirm-rounds"
    return result


def _junit(*, failed: bool) -> bytes:
    cases = []
    for scenario_id in SCENARIOS:
        if failed and scenario_id == "late-offender-confirm":
            cases.append(f'<testcase name="{scenario_id}"><failure /></testcase>')
        else:
            cases.append(f'<testcase name="{scenario_id}" />')
    failures = int(failed)
    return (
        f'<testsuite name="ooptdd.arrival-benchmark" tests="{len(SCENARIOS)}" '
        f'failures="{failures}" errors="0" skipped="0">'
        + "".join(cases)
        + "</testsuite>\n"
    ).encode()


def _markdown(*, failed: bool) -> bytes:
    status = "FAIL" if failed else "PASS"
    lines = [f"# ooptdd arrival benchmark — {status}", *SCENARIOS]
    return ("\n".join(lines) + "\n").encode()


def _build_bundle(
    root: Path,
    *,
    baseline: float = 4.0,
    all_expected_present: bool = False,
) -> _Bundle:
    paths: dict[str, Path] = {}
    hashes: dict[str, str] = {}

    def store(role: str, value: object, *, raw: bool = False) -> None:
        payload = value if raw else _json_bytes(value)
        assert isinstance(payload, bytes)
        path = root / f"{role}{_artifact_suffix(role)}"
        path.write_bytes(payload)
        paths[role] = path
        hashes[role] = _sha(payload)

    def meta(role: str) -> dict:
        return {"file": paths[role].name, "sha256": hashes[role]}

    kill_condition = "any unresolved integrity gap remains"
    preregistration = {
        "schema_version": "lakatotree-preregistration/v1",
        "programme": PROGRAMME,
        "branch": CONJECTURE,
        "registered_at": REGISTERED_AT,
        "prediction": {
            "metric": PRIMARY_METRIC,
            "direction": "lower",
            "baseline": baseline,
            "target": 0.0,
            "noise_band": 0.0,
        },
        "novel_target": {
            "metric": NOVEL_METRIC,
            "direction": "higher",
            "threshold": 1.0,
            "repetitions": 1,
        },
        "kill_condition": kill_condition,
    }
    store("preregistration", preregistration)

    lock = {
        "schema": "ooptdd-efficacy-measurement-lock/v1",
        "candidate_git_head": HEAD,
        "candidate_dirty": False,
        "tier": "tier0-mechanics",
        "seed": 7,
        "repetitions": 1,
        "deepeval_version": "3.5.0",
        "registration_repository": "gj3447/ooptdd",
        "preregistration_sha256": hashes["preregistration"],
        "benchmark_definition_sha256": _label_sha("benchmark-definition"),
        "code_manifest_sha256": _label_sha("code-manifest"),
        "manifest_sha256": _label_sha("manifest"),
        "gate_spec_sha256": _label_sha("gate-spec"),
        "events_sha256": _label_sha("events"),
        "runner_sha256": _label_sha("runner"),
        "deepeval_spec_sha256": _label_sha("deepeval-spec"),
    }
    store("measurement-lock", lock)

    positive = _benchmark(
        lock, "positive", all_expected_present=all_expected_present
    )
    negative = _benchmark(
        lock, "negative", all_expected_present=all_expected_present
    )
    store("tier0-positive", positive)
    store("tier0-negative", negative)
    store("tier0-restored", positive)
    store("tier0-positive-junit", _junit(failed=False), raw=True)
    store("tier0-negative-junit", _junit(failed=True), raw=True)
    store("tier0-restored-junit", _junit(failed=False), raw=True)
    store("tier0-positive-markdown", _markdown(failed=False), raw=True)
    store("tier0-negative-markdown", _markdown(failed=True), raw=True)
    store("tier0-restored-markdown", _markdown(failed=False), raw=True)

    candidate_metrics = {
        "deepeval_oracle_agreement_rate": 1.0,
        "actual_deepeval_trajectory_pass_rate": 1.0,
        "cases_total": 3,
        "cases_matched": 3,
        "actual_successes": 1,
    }
    deepeval_candidate = {
        "schema_version": "ooptdd-deepeval-heldout/v1",
        "source": {"git_head": HEAD, "dirty": False},
        "spec": {"sha256": lock["deepeval_spec_sha256"]},
        "environment": {"deepeval": lock["deepeval_version"]},
        "measured_at": "2026-07-23T00:04:00Z",
        "observations": [
            {
                "name": "safe",
                "expected_score": 1.0,
                "expected_success": True,
                "observed_score": 1.0,
                "observed_success": True,
                "matched": True,
            },
            {
                "name": "destructive",
                "expected_score": 0.0,
                "expected_success": False,
                "observed_score": 0.0,
                "observed_success": False,
                "matched": True,
            },
            {
                "name": "corrupt",
                "expected_score": 0.0,
                "expected_success": False,
                "observed_score": 0.0,
                "observed_success": False,
                "matched": True,
            },
        ],
        "metrics": candidate_metrics,
    }
    deepeval_mismatch = copy.deepcopy(deepeval_candidate)
    deepeval_mismatch["observations"][0]["observed_success"] = False
    store("deepeval-candidate", deepeval_candidate)
    store("deepeval-injected-mismatch", deepeval_mismatch)

    integrity_report = {
        "schema": "ooptdd-efficacy-integrity-report/v1",
        "candidate_git_head": HEAD,
        "observations": [
            {"gap_id": gap_id, "resolved": True} for gap_id in GAPS
        ],
        "unresolved_evidence_integrity_gaps": 0,
        "tier0_required_oracle_match_rate": 1.0,
        "negative_control_failures": ["late-offender-confirm"],
        "restored_byte_identical": True,
    }
    store("integrity-report", integrity_report)

    ci_receipt = {
        "schema": "ooptdd-actions-receipt/v1",
        "run_id": 123,
        "repository": "gj3447/ooptdd",
        "workflow_path": ".github/workflows/ci.yml",
        "head_sha": HEAD,
        "conclusion": "success",
        "html_url": "https://github.com/gj3447/ooptdd/actions/runs/123",
        "jobs": [
            {
                "name": "lakatotree-qualification",
                "conclusion": "success",
                "steps": [
                    {
                        "name": "Recompute and assert the DeepEval artifact",
                        "conclusion": "success",
                    }
                ],
            }
        ],
        "artifacts": [
            {
                "name": "tier0-arrival-benchmark",
                "expired": False,
                "digest": f"sha256:{_label_sha('arrival-artifact')}",
            },
            {
                "name": "deepeval-heldout-v2",
                "expired": False,
                "digest": f"sha256:{_label_sha('deepeval-artifact')}",
            },
        ],
    }
    store("github-actions-receipt", ci_receipt)

    sequence = {
        "schema": "ooptdd-efficacy-measurement-sequence/v1",
        "source": {"git_head": HEAD, "dirty": False},
        "measurement_lock_sha256": hashes["measurement-lock"],
        "preregistration_sha256": hashes["preregistration"],
        "benchmark_definition_sha256": lock["benchmark_definition_sha256"],
        "measurements": [
            {
                "role": polarity,
                "measured_at": f"2026-07-23T00:0{index}:00Z",
                "artifacts": {
                    "json": meta(f"tier0-{polarity}"),
                    "junit": meta(f"tier0-{polarity}-junit"),
                    "markdown": meta(f"tier0-{polarity}-markdown"),
                },
            }
            for index, polarity in enumerate(
                ("positive", "negative", "restored"), start=1
            )
        ],
        "deepeval": {
            "candidate": meta("deepeval-candidate"),
            "injected_mismatch": meta("deepeval-injected-mismatch"),
            "injected_mismatch_rejected": True,
            "computed_metrics": candidate_metrics,
            "measured_at": deepeval_candidate["measured_at"],
        },
        "prospective_registration": {
            "schema": "ooptdd-prospective-git-receipt/v1",
            "preregistration_is_ancestor": True,
            "repository": lock["registration_repository"],
            "preregistration": {
                "sha256": hashes["preregistration"],
                "published_refs": ["refs/heads/main"],
                "commit": "b" * 40,
            },
            "measurement_lock": {
                "sha256": hashes["measurement-lock"],
                "published_refs": ["refs/heads/main"],
                "commit": "c" * 40,
            },
        },
    }
    store("measurement-sequence", sequence)

    record = {
        "schema": "lakato-evidence-record/v1",
        "programme": PROGRAMME,
        "conjecture": CONJECTURE,
        "preregistration": {
            "registered_before_measurement": True,
            "registered_at": REGISTERED_AT,
            "direction": "lower",
            "noise_band": 0.0,
            "target": 0.0,
            "max_acceptable": 0.0,
            "predicted": {
                "metric": PRIMARY_METRIC,
                "value": baseline,
                "unit": "count",
            },
            "kill_condition": kill_condition,
        },
        "measurement": {
            "metric": PRIMARY_METRIC,
            "value": 0,
            "unit": "count",
            "primary_source_sha256": hashes["integrity-report"],
            "derived": {NOVEL_METRIC: 1.0},
            "novel_measurement": {
                "metric": NOVEL_METRIC,
                "direction": "higher",
                "threshold": 1.0,
                "value": 1.0,
                "repetitions": 1,
                "source_sha256": hashes["tier0-positive"],
            },
        },
        "provenance": {
            "grounded": True,
            "inputs": [
                {
                    "name": role,
                    "source": paths[role].name,
                    "sha256": hashes[role],
                }
                for role in ROLE_ORDER
            ],
        },
        "harness": {
            "script": "scripts/build_ooptdd_efficacy_evidence.py",
            "git_commit": HEAD,
            "env": "python3.12",
            "benchmark_definition_sha256": lock["benchmark_definition_sha256"],
        },
    }
    return _Bundle(root=root, record=record, paths=paths)


def _input_for(record: dict, role: str) -> dict:
    return next(item for item in record["provenance"]["inputs"] if item["name"] == role)


def _consume(bundle: _Bundle) -> dict:
    return programme.consume_record(bundle.record, artifact_root=bundle.root)


def test_grounded_aligned_record_is_judged_by_engine_without_timestamp(tmp_path):
    bundle = _build_bundle(tmp_path)
    result = _consume(bundle)
    assert result["status"] == "judged"
    assert result["verdict"] == "progressive"
    assert result["metric"] == PRIMARY_METRIC
    assert result["measured"] == 0.0
    serialized = programme.canonical_json(result)
    assert serialized == programme.canonical_json(_consume(bundle))
    assert "timestamp" not in serialized.lower()


def test_unfavourable_engine_verdict_is_not_rewritten_or_treated_as_cli_failure(
    tmp_path,
):
    bundle = _build_bundle(tmp_path, baseline=-1.0)
    result = _consume(bundle)
    assert result["status"] == "judged"
    assert result["verdict"] == "rejected"

    path = tmp_path / "record.json"
    path.write_text(json.dumps(bundle.record), encoding="utf-8")
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
    bundle = _build_bundle(tmp_path)
    compact = tmp_path / "compact.json"
    pretty = tmp_path / "pretty.json"
    compact.write_text(
        json.dumps(bundle.record, separators=(",", ":")), encoding="utf-8"
    )
    pretty.write_text(json.dumps(bundle.record, indent=4), encoding="utf-8")

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
def test_invalid_records_fail_before_record_judge(
    tmp_path, monkeypatch, mutate, needle
):
    bundle = _build_bundle(tmp_path)
    mutate(bundle.record)

    def forbidden_call(_record):  # pragma: no cover - a call is the failure
        raise AssertionError("invalid evidence reached record_judge")

    monkeypatch.setattr(programme, "judge_record", forbidden_call)
    result = _consume(bundle)
    assert result["status"] == "invalid"
    assert needle in " ".join(result["errors"])


def test_derived_metric_alignment_does_not_bypass_primary_artifact_binding(tmp_path):
    bundle = _build_bundle(tmp_path)
    bundle.record["measurement"] = {
        "metric": NOVEL_METRIC,
        "value": 1.0,
        "derived": {PRIMARY_METRIC: 0.0},
    }
    result = _consume(bundle)
    assert result["status"] == "invalid"
    assert f"measurement metric must be '{PRIMARY_METRIC}'" in " ".join(
        result["errors"]
    )


def test_distinct_preregistered_novel_measurement_can_make_progressive(tmp_path):
    result = _consume(_build_bundle(tmp_path))
    assert result["status"] == "judged"
    assert result["verdict"] == "progressive"
    assert result["novel"] is True
    assert result["novel_metric"] == NOVEL_METRIC


def test_novel_measurement_must_be_a_distinct_bound_artifact(tmp_path):
    bundle = _build_bundle(tmp_path)
    bundle.record["measurement"]["novel_measurement"]["source_sha256"] = (
        bundle.record["measurement"]["primary_source_sha256"]
    )
    result = _consume(bundle)
    assert result["status"] == "invalid"
    assert "distinct source SHA-256" in " ".join(result["errors"])


@pytest.mark.parametrize("mode", ["missing", "hash"])
def test_missing_or_hash_forged_provenance_never_reaches_judge(
    tmp_path, monkeypatch, mode
):
    bundle = _build_bundle(tmp_path)
    item = _input_for(bundle.record, "integrity-report")
    if mode == "missing":
        item["source"] = "definitely-missing.json"
    else:
        item["sha256"] = "0" * 64

    def forbidden_call(_record):  # pragma: no cover - a call is the failure
        raise AssertionError("unbound evidence reached record_judge")

    monkeypatch.setattr(programme, "judge_record", forbidden_call)
    result = _consume(bundle)
    assert result["status"] == "invalid"
    needle = "does not exist" if mode == "missing" else "hash mismatch"
    assert needle in " ".join(result["errors"])


def test_missing_required_role_fails_even_when_the_artifact_file_exists(
    tmp_path, monkeypatch
):
    bundle = _build_bundle(tmp_path)
    bundle.record["provenance"]["inputs"] = [
        item
        for item in bundle.record["provenance"]["inputs"]
        if item["name"] != "github-actions-receipt"
    ]

    def forbidden_call(_record):  # pragma: no cover - a call is the failure
        raise AssertionError("incomplete role bundle reached record_judge")

    monkeypatch.setattr(programme, "judge_record", forbidden_call)
    result = _consume(bundle)
    errors = " ".join(result["errors"])
    assert result["status"] == "invalid"
    assert "missing required provenance artifact roles" in errors
    assert "github-actions-receipt" in errors


def test_all_present_expected_value_forgery_fails_with_every_role_bound(
    tmp_path, monkeypatch
):
    bundle = _build_bundle(tmp_path, all_expected_present=True)
    assert len(bundle.record["provenance"]["inputs"]) == len(ROLE_ORDER) == 16

    def forbidden_call(_record):  # pragma: no cover - a call is the failure
        raise AssertionError("forged oracle bundle reached record_judge")

    monkeypatch.setattr(programme, "judge_record", forbidden_call)
    result = _consume(bundle)
    errors = " ".join(result["errors"])
    assert result["status"] == "invalid"
    assert "expected does not match the frozen Tier-0 oracle" in errors
    assert "missing required provenance artifact roles" not in errors
    assert "hash mismatch" not in errors


@pytest.mark.parametrize(
    "field,needle",
    [
        ("target", "record preregistration target must be exactly 0"),
        ("max_acceptable", "record preregistration max_acceptable must be exactly 0"),
    ],
)
def test_target_or_max_acceptable_cannot_be_relaxed_after_registration(
    tmp_path, monkeypatch, field, needle
):
    bundle = _build_bundle(tmp_path)
    bundle.record["preregistration"][field] = 1.0

    def forbidden_call(_record):  # pragma: no cover - a call is the failure
        raise AssertionError("relaxed target reached record_judge")

    monkeypatch.setattr(programme, "judge_record", forbidden_call)
    result = _consume(bundle)
    assert result["status"] == "invalid"
    assert needle in " ".join(result["errors"])


def test_artifact_byte_forgery_is_rejected_before_judgement(tmp_path, monkeypatch):
    bundle = _build_bundle(tmp_path)
    path = bundle.paths["integrity-report"]
    path.write_bytes(path.read_bytes() + b"\n")

    def forbidden_call(_record):  # pragma: no cover - a call is the failure
        raise AssertionError("tampered artifact reached record_judge")

    monkeypatch.setattr(programme, "judge_record", forbidden_call)
    result = _consume(bundle)
    assert result["status"] == "invalid"
    assert "provenance input hash mismatch" in " ".join(result["errors"])


def test_rehashed_artifact_value_forgery_is_recomputed_from_observations(
    tmp_path, monkeypatch
):
    bundle = _build_bundle(tmp_path)
    path = bundle.paths["integrity-report"]
    report = json.loads(path.read_text())
    report["unresolved_evidence_integrity_gaps"] = 1
    path.write_bytes(_json_bytes(report))
    forged_sha = _sha(path.read_bytes())
    _input_for(bundle.record, "integrity-report")["sha256"] = forged_sha
    bundle.record["measurement"]["primary_source_sha256"] = forged_sha

    def forbidden_call(_record):  # pragma: no cover - a call is the failure
        raise AssertionError("rehashed summary forgery reached record_judge")

    monkeypatch.setattr(programme, "judge_record", forbidden_call)
    result = _consume(bundle)
    errors = " ".join(result["errors"])
    assert result["status"] == "invalid"
    assert "unresolved count is not observation-derived" in errors
    assert "hash mismatch" not in errors


def test_non_finite_or_boolean_aligned_values_are_rejected(tmp_path):
    bundle = _build_bundle(tmp_path)
    for value in (float("nan"), float("inf"), True):
        record = copy.deepcopy(bundle.record)
        record["measurement"]["value"] = value
        result = programme.consume_record(record, artifact_root=tmp_path)
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
def test_malformed_nested_shapes_fail_closed_instead_of_crashing(
    tmp_path, field, value
):
    bundle = _build_bundle(tmp_path)
    bundle.record[field] = value
    result = _consume(bundle)
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
