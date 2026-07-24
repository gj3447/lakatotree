"""Consume an ooptdd efficacy record through LakatoTree's honesty boundary.

The producer owns measurements, never the verdict.  This adapter therefore
accepts only the portable ``lakato-evidence-record/v1`` contract, applies the
canonical validator and grounding predicate, checks that the preregistered
metric can be found in the measurement, and only then delegates judgement to
``record_judge`` (which calls LakatoTree's pure ``judge`` kernel).

The returned envelope is deliberately timestamp-free and contains no
candidate-specific constant.  Identical evidence objects serialize to
identical bytes; a favourable verdict is never a CLI success precondition.

Usage::

    python examples/ooptdd_efficacy_20260723_programme.py evidence.json
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lakatos.programme.evidence import (  # noqa: E402
    is_grounded,
    load_record,
    source_id,
    validate_record,
)
from lakatos.programme.record_judge import judge_record  # noqa: E402
from lakatos.verdict.judge import NovelTarget, Prediction, judge  # noqa: E402

OUTPUT_SCHEMA = "lakatotree-ooptdd-efficacy-judgement/v1"
_AUTHORED_VERDICT_KEYS = frozenset({"verdict", "progressive", "pass"})
_PRIMARY_METRIC = "unresolved_evidence_integrity_gaps"
_NOVEL_METRIC = "tier0_required_oracle_match_rate"
_INTEGRITY_SCHEMA = "ooptdd-efficacy-integrity-report/v1"
_BENCHMARK_SCHEMA = "ooptdd-arrival-benchmark/v0"
_SEQUENCE_SCHEMA = "ooptdd-efficacy-measurement-sequence/v1"
_DEEPEVAL_SCHEMA = "ooptdd-deepeval-heldout/v1"
_LOCK_SCHEMA = "ooptdd-efficacy-measurement-lock/v1"
_CI_SCHEMA = "ooptdd-actions-receipt/v1"
_TIER0_CLAIM_BOUNDARY = (
    "Deterministic gate-mechanics evidence only; not proof that evidence arrived in an "
    "independent external store. Tier-1 evidence is required for an arrival claim."
)
_TIER0_IDENTITY = {
    "benchmark_id": "ooptdd-arrival-v0",
    "benchmark_version": "0.1.0",
    "fixture_version": "arrival-v0-20260723",
    "tier": "tier0-mechanics",
    "independent": False,
    "claim_boundary": _TIER0_CLAIM_BOUNDARY,
}
_ARRIVAL_KEYS = frozenset(
    {
        "visibility_delay_ms",
        "waited_ms",
        "flushed",
        "extended_for_visibility",
        "confirm_rounds_run",
    }
)
_PREREGISTRATION_SCHEMAS = frozenset(
    {"lakatotree-preregistration/v1", "ooptdd-efficacy-preregistration/v1"}
)
_EXPECTED_GAPS = frozenset(
    {
        "nonvacuous_trajectory_mutation",
        "observation_first_aggregate_recomputation",
        "source_spec_and_file_binding",
        "deepeval_artifact_asserted_in_ci",
    }
)
_TIER0_SCENARIOS = (
    "silent-loss",
    "lag-within-window",
    "truly-absent",
    "late-offender-control",
    "late-offender-confirm",
    "backend-outage",
    "dependent-store-demotion",
    "external-corroboration",
    "trajectory-mutation",
)
_TIER0_EXPECTED = {
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
_TIER0_MUTATION = {
    "eligible": 5,
    "score": 1.0,
    "score_status": "measured",
    "canary_survived": False,
    "survivors": [],
}
_REQUIRED_ROLES = frozenset(
    {
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
    }
)
_JSON_ROLES = _REQUIRED_ROLES - {
    "tier0-positive-junit",
    "tier0-positive-markdown",
    "tier0-negative-junit",
    "tier0-negative-markdown",
    "tier0-restored-junit",
    "tier0-restored-markdown",
}
_LOCK_HASH_FIELDS = (
    "preregistration_sha256",
    "benchmark_definition_sha256",
    "code_manifest_sha256",
    "manifest_sha256",
    "gate_spec_sha256",
    "events_sha256",
    "runner_sha256",
    "deepeval_spec_sha256",
)


@dataclass(frozen=True)
class _BoundArtifact:
    role: str
    source: str
    sha256: str
    path: Path
    payload: bytes


def _finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _authored_verdict_paths(value: object, path: str = "$") -> list[str]:
    """Return exact verdict-like keys at any depth, in deterministic order."""
    found: list[str] = []
    if isinstance(value, Mapping):
        for key in sorted(value, key=str):
            child_path = f"{path}.{key}"
            if str(key).lower() in _AUTHORED_VERDICT_KEYS:
                found.append(child_path)
            found.extend(_authored_verdict_paths(value[key], child_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_authored_verdict_paths(item, f"{path}[{index}]"))
    return found


def _metric_alignment_error(record: dict[str, Any]) -> str | None:
    preregistration = record.get("preregistration") or {}
    measurement = record.get("measurement") or {}
    if not isinstance(preregistration, Mapping):
        return "preregistration must be an object"
    if not isinstance(measurement, Mapping):
        return "measurement must be an object"

    predicted = preregistration.get("predicted") or {}
    if not isinstance(predicted, Mapping):
        return "preregistration.predicted must be an object"
    metric = predicted.get("metric")
    if not isinstance(metric, str) or not metric.strip():
        return "preregistration.predicted.metric must be a non-empty string"

    if measurement.get("metric") == metric and _finite_number(measurement.get("value")):
        return None
    derived = measurement.get("derived") or {}
    if isinstance(derived, Mapping) and _finite_number(derived.get(metric)):
        return None
    return (
        f"predicted metric {metric!r} has no finite aligned measurement.value "
        "or measurement.derived entry"
    )


def _novel_measurement_error(record: dict[str, Any]) -> str | None:
    measurement = record.get("measurement") or {}
    if not isinstance(measurement, Mapping):
        return None
    novel = measurement.get("novel_measurement")
    if novel is None:
        return None
    if not isinstance(novel, Mapping):
        return "measurement.novel_measurement must be an object"
    if not isinstance(novel.get("metric"), str) or not novel["metric"].strip():
        return "novel measurement metric must be a non-empty string"
    if novel.get("direction") not in {"lower", "higher"}:
        return "novel measurement direction must be lower or higher"
    if not _finite_number(novel.get("threshold")) or not _finite_number(novel.get("value")):
        return "novel measurement threshold and value must be finite numbers"
    primary_sha = measurement.get("primary_source_sha256")
    novel_sha = novel.get("source_sha256")
    if not all(
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
        for value in (primary_sha, novel_sha)
    ):
        return "primary and novel source SHA-256 values must be lowercase 64-hex"
    if primary_sha == novel_sha:
        return "primary and novel measurements must have distinct source SHA-256 values"
    return None


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _same_number(left: object, right: object) -> bool:
    return _finite_number(left) and _finite_number(right) and float(left) == float(right)


def _canonical_sha256(value: object) -> str:
    payload = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _variant_id(seed: int, scenario_id: str, repeat: int) -> str:
    return hashlib.sha256(f"{seed}:{scenario_id}:{repeat}".encode()).hexdigest()[:16]


def _pass_hat_k(successes: int, attempts: int, k: int) -> float:
    if successes < k:
        return 0.0
    return math.comb(successes, k) / math.comb(attempts, k)


def _provenance_errors(
    role: str, provenance: object, lock: Mapping[str, Any]
) -> list[str]:
    if not isinstance(provenance, Mapping):
        return [f"{role} provenance must be an object"]
    errors: list[str] = []
    files = provenance.get("files")
    code_manifest = provenance.get("code_manifest")
    if not isinstance(files, Mapping):
        errors.append(f"{role} provenance.files must be an object")
        files = {}
    if not isinstance(code_manifest, Mapping) or not code_manifest:
        errors.append(f"{role} provenance.code_manifest must be a non-empty object")
        code_manifest = {}
    elif not all(
        isinstance(path, str) and path.startswith("ooptdd/") and _is_sha256(digest)
        for path, digest in code_manifest.items()
    ):
        errors.append(f"{role} provenance.code_manifest entries must be path-to-SHA256")

    fixture_files = {
        "manifest": files.get("manifest"),
        "trajectory_events": files.get("trajectory_events"),
        "trajectory_gate": files.get("trajectory_gate"),
    }
    if not all(_is_sha256(value) for value in fixture_files.values()) or not _is_sha256(
        files.get("runner")
    ):
        errors.append(f"{role} provenance.files lacks the frozen fixture/runner hashes")
    else:
        expected = {
            "code_manifest_sha256": _canonical_sha256(dict(code_manifest)),
            "dataset_sha256": _canonical_sha256(fixture_files),
            "benchmark_definition_sha256": _canonical_sha256(
                {"code_manifest": dict(code_manifest), "fixture_files": fixture_files}
            ),
            "item_ids_sha256": _canonical_sha256(list(_TIER0_SCENARIOS)),
        }
        for field, recomputed in expected.items():
            if provenance.get(field) != recomputed:
                errors.append(f"{role} provenance {field} is not content-derived")

    expected_bindings = {
        "benchmark_definition_sha256": provenance.get("benchmark_definition_sha256"),
        "code_manifest_sha256": provenance.get("code_manifest_sha256"),
        "manifest_sha256": files.get("manifest"),
        "gate_spec_sha256": files.get("trajectory_gate"),
        "events_sha256": files.get("trajectory_events"),
        "runner_sha256": files.get("runner"),
    }
    for lock_field, observed in expected_bindings.items():
        if observed != lock.get(lock_field):
            errors.append(f"{role} provenance {lock_field} does not match measurement-lock")
    return errors


def _read_bound_artifacts(
    record: dict[str, Any], artifact_root: Path
) -> tuple[dict[str, _BoundArtifact], list[str]]:
    """Resolve unique role bindings and verify every declared file byte-for-byte."""
    errors: list[str] = []
    artifacts: dict[str, _BoundArtifact] = {}
    sources: set[str] = set()
    root = artifact_root.resolve()
    provenance = record.get("provenance") or {}
    inputs = provenance.get("inputs") if isinstance(provenance, Mapping) else None
    if not isinstance(inputs, list) or not inputs:
        return artifacts, ["provenance.inputs must be a non-empty list of bound artifacts"]

    for index, item in enumerate(inputs):
        prefix = f"provenance.inputs[{index}]"
        if not isinstance(item, Mapping):
            errors.append(f"{prefix} must be an object")
            continue
        role = item.get("name")
        source = item.get("source")
        expected = item.get("sha256")
        if not isinstance(role, str) or not role:
            errors.append(f"{prefix}.name must be a non-empty artifact role")
            continue
        if role in artifacts:
            errors.append(f"duplicate provenance artifact role: {role}")
            continue
        if not isinstance(source, str) or not source or Path(source).is_absolute():
            errors.append(f"{prefix}.source must be a relative path")
            continue
        if source in sources:
            errors.append(f"duplicate provenance artifact source: {source}")
            continue
        sources.add(source)
        path = (root / source).resolve()
        if path != root and root not in path.parents:
            errors.append(f"{prefix} escapes artifact root")
            continue
        if not _is_sha256(expected):
            errors.append(f"{prefix}.sha256 must be lowercase 64-hex")
            continue
        try:
            payload = path.read_bytes()
        except OSError:
            errors.append(f"provenance input does not exist or is unreadable: {source}")
            continue
        observed = hashlib.sha256(payload).hexdigest()
        if observed != expected:
            errors.append(f"provenance input hash mismatch: {source}")
            continue
        artifacts[role] = _BoundArtifact(role, source, expected, path, payload)

    missing = sorted(_REQUIRED_ROLES - artifacts.keys())
    if missing:
        errors.append(f"missing required provenance artifact roles: {', '.join(missing)}")
    return artifacts, errors


def _parse_json_artifacts(
    artifacts: Mapping[str, _BoundArtifact]
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    documents: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for role in sorted(_JSON_ROLES):
        artifact = artifacts.get(role)
        if artifact is None:
            continue
        try:
            value = json.loads(artifact.payload)
        except (UnicodeError, json.JSONDecodeError):
            errors.append(f"{role} must be valid UTF-8 JSON")
            continue
        if not isinstance(value, dict):
            errors.append(f"{role} JSON must be an object")
            continue
        documents[role] = value
    return documents, errors


def _schema_errors(documents: Mapping[str, dict[str, Any]]) -> list[str]:
    expected = {
        "integrity-report": ("schema", _INTEGRITY_SCHEMA),
        "tier0-positive": ("schema", _BENCHMARK_SCHEMA),
        "tier0-negative": ("schema", _BENCHMARK_SCHEMA),
        "tier0-restored": ("schema", _BENCHMARK_SCHEMA),
        "measurement-sequence": ("schema", _SEQUENCE_SCHEMA),
        "deepeval-candidate": ("schema_version", _DEEPEVAL_SCHEMA),
        "deepeval-injected-mismatch": ("schema_version", _DEEPEVAL_SCHEMA),
        "measurement-lock": ("schema", _LOCK_SCHEMA),
        "github-actions-receipt": ("schema", _CI_SCHEMA),
    }
    errors: list[str] = []
    for role, (field, schema) in expected.items():
        document = documents.get(role)
        if document is not None and document.get(field) != schema:
            errors.append(f"{role} {field} must be {schema!r}")
    preregistration = documents.get("preregistration")
    if preregistration is not None:
        schema = preregistration.get("schema_version", preregistration.get("schema"))
        if schema not in _PREREGISTRATION_SCHEMAS:
            errors.append("preregistration artifact schema is not an accepted prospective schema")
    return errors


def _validate_lock(lock: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    head = lock.get("candidate_git_head")
    if (
        not isinstance(head, str)
        or len(head) not in {40, 64}
        or any(char not in "0123456789abcdef" for char in head)
    ):
        errors.append("measurement-lock candidate_git_head must be a lowercase git object id")
    if lock.get("candidate_dirty") is not False:
        errors.append("measurement-lock candidate_dirty must be exactly false")
    if lock.get("tier") != "tier0-mechanics":
        errors.append("measurement-lock tier must be 'tier0-mechanics'")
    seed = lock.get("seed")
    repetitions = lock.get("repetitions")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        errors.append("measurement-lock seed must be a non-negative integer")
    if isinstance(repetitions, bool) or not isinstance(repetitions, int) or repetitions < 1:
        errors.append("measurement-lock repetitions must be a positive integer")
    if not isinstance(lock.get("deepeval_version"), str) or not lock["deepeval_version"]:
        errors.append("measurement-lock deepeval_version must be a non-empty string")
    if (
        not isinstance(lock.get("registration_repository"), str)
        or not lock["registration_repository"].strip()
    ):
        errors.append("measurement-lock registration_repository must be non-empty")
    for field in _LOCK_HASH_FIELDS:
        if not _is_sha256(lock.get(field)):
            errors.append(f"measurement-lock {field} must be lowercase SHA-256")
    return errors


def _benchmark_observations(
    role: str, result: Mapping[str, Any]
) -> tuple[float | None, list[str], list[str]]:
    """Recompute the portable oracle rollups without importing ooptdd."""
    errors: list[str] = []
    rows = result.get("scenarios")
    if not isinstance(rows, list) or not rows:
        return None, [], [f"{role} scenarios must be a non-empty list"]
    if [row.get("id") if isinstance(row, Mapping) else None for row in rows] != list(
        _TIER0_SCENARIOS
    ):
        errors.append(f"{role} must contain the fixed Tier-0 scenario order")
    repetitions = result.get("repetitions")
    seen: set[str] = set()
    all_matches: list[bool] = []
    failure_ids: list[str] = []
    for index, row in enumerate(rows):
        prefix = f"{role}.scenarios[{index}]"
        if not isinstance(row, Mapping):
            errors.append(f"{prefix} must be an object")
            continue
        scenario_id = row.get("id")
        if not isinstance(scenario_id, str) or not scenario_id or scenario_id in seen:
            errors.append(f"{prefix}.id must be a unique non-empty string")
            continue
        seen.add(scenario_id)
        declared_expected = _TIER0_EXPECTED.get(scenario_id)
        if row.get("expected") != declared_expected:
            errors.append(f"{prefix}.expected does not match the frozen Tier-0 oracle")
        samples = row.get("samples")
        if not isinstance(samples, list) or not samples:
            errors.append(f"{prefix}.samples must be a non-empty list")
            continue
        if (
            isinstance(repetitions, bool)
            or not isinstance(repetitions, int)
            or len(samples) != repetitions
            or [
                sample.get("repeat") if isinstance(sample, Mapping) else None
                for sample in samples
            ]
            != list(range(repetitions))
        ):
            errors.append(f"{prefix}.samples must match locked repetition indices")
        matches: list[bool] = []
        for sample_index, sample in enumerate(samples):
            if not isinstance(sample, Mapping) or not isinstance(sample.get("oracle_match"), bool):
                errors.append(
                    f"{prefix}.samples[{sample_index}].oracle_match must be boolean"
                )
                continue
            if not isinstance(sample.get("expected"), str) or not isinstance(
                sample.get("observed"), str
            ):
                errors.append(
                    f"{prefix}.samples[{sample_index}] expected/observed must be strings"
                )
                continue
            if sample["expected"] != declared_expected:
                errors.append(
                    f"{prefix}.samples[{sample_index}].expected does not match "
                    "the frozen Tier-0 oracle"
                )
            match = sample["oracle_match"]
            derived = sample["observed"] == sample["expected"]
            if match is not derived:
                errors.append(
                    f"{prefix}.samples[{sample_index}] oracle_match is not observation-derived"
                )
            matches.append(match)
        attempts = len(matches)
        successes = sum(matches)
        rate = successes / attempts if attempts else None
        if row.get("attempts") != attempts:
            errors.append(f"{prefix}.attempts is not sample-derived")
        if row.get("oracle_matches") != successes:
            errors.append(f"{prefix}.oracle_matches is not sample-derived")
        if rate is None or not _same_number(row.get("oracle_match_rate"), rate):
            errors.append(f"{prefix}.oracle_match_rate is not sample-derived")
        elif rate != 1.0:
            failure_ids.append(scenario_id)
        all_matches.extend(matches)

    if not all_matches:
        return None, failure_ids, errors
    computed = sum(all_matches) / len(all_matches)
    metrics = result.get("metrics")
    required = metrics.get("required_oracle_match_rate") if isinstance(metrics, Mapping) else None
    stored = required.get("value") if isinstance(required, Mapping) else None
    if not _same_number(stored, computed):
        errors.append(f"{role} required_oracle_match_rate is not sample-derived")
    return computed, failure_ids, errors


def _validate_benchmarks(
    documents: Mapping[str, dict[str, Any]], lock: Mapping[str, Any]
) -> tuple[dict[str, float], dict[str, list[str]], list[str]]:
    rates: dict[str, float] = {}
    failures: dict[str, list[str]] = {}
    errors: list[str] = []
    roles = ("tier0-positive", "tier0-negative", "tier0-restored")
    for role in roles:
        result = documents.get(role)
        if result is None:
            continue
        rate, failed, local_errors = _benchmark_observations(role, result)
        errors.extend(local_errors)
        if rate is not None:
            rates[role] = rate
        failures[role] = failed
        if result.get("tier") != lock.get("tier"):
            errors.append(f"{role} tier does not match measurement-lock")
        if result.get("seed") != lock.get("seed"):
            errors.append(f"{role} seed does not match measurement-lock")
        if result.get("repetitions") != lock.get("repetitions"):
            errors.append(f"{role} repetitions do not match measurement-lock")
        if result.get("independent") is not False:
            errors.append(f"{role} must retain the Tier-0 dependent claim boundary")
        provenance = result.get("provenance")
        benchmark_sha = (
            provenance.get("benchmark_definition_sha256")
            if isinstance(provenance, Mapping)
            else None
        )
        if benchmark_sha != lock.get("benchmark_definition_sha256"):
            errors.append(f"{role} benchmark definition does not match measurement-lock")
        if not isinstance(provenance, Mapping):
            errors.append(f"{role} provenance must be an object")
        else:
            files = provenance.get("files")
            expected_bindings = {
                "code_manifest_sha256": provenance.get("code_manifest_sha256"),
                "manifest_sha256": files.get("manifest")
                if isinstance(files, Mapping)
                else None,
                "gate_spec_sha256": files.get("trajectory_gate")
                if isinstance(files, Mapping)
                else None,
                "events_sha256": files.get("trajectory_events")
                if isinstance(files, Mapping)
                else None,
                "runner_sha256": files.get("runner")
                if isinstance(files, Mapping)
                else None,
            }
            for lock_field, observed in expected_bindings.items():
                if observed != lock.get(lock_field):
                    errors.append(
                        f"{role} provenance {lock_field} does not match measurement-lock"
                    )
        conformance = result.get("conformance")
        if not isinstance(conformance, Mapping) or not all(
            isinstance(item, Mapping) and isinstance(item.get("passed"), bool)
            for item in conformance.values()
        ):
            errors.append(f"{role} conformance must contain boolean pass results")

    positive = documents.get("tier0-positive")
    negative = documents.get("tier0-negative")
    restored = documents.get("tier0-restored")
    if positive is not None:
        if positive.get("passed") is not True:
            errors.append("tier0-positive passed must be exactly true")
        if rates.get("tier0-positive") != 1.0 or failures.get("tier0-positive"):
            errors.append("tier0-positive must match every required oracle")
        if positive.get("fault_injection") is not None:
            errors.append("tier0-positive must not enable fault injection")
    if negative is not None:
        if negative.get("passed") is not False:
            errors.append("tier0-negative passed must be exactly false")
        if negative.get("fault_injection") != "disable-confirm-rounds":
            errors.append("tier0-negative must use disable-confirm-rounds fault injection")
        if failures.get("tier0-negative") != ["late-offender-confirm"]:
            errors.append("tier0-negative failure must localize to late-offender-confirm")
    if restored is not None:
        if restored.get("passed") is not True:
            errors.append("tier0-restored passed must be exactly true")
        if rates.get("tier0-restored") != 1.0 or failures.get("tier0-restored"):
            errors.append("tier0-restored must match every required oracle")
        if restored.get("fault_injection") is not None:
            errors.append("tier0-restored must not enable fault injection")
    if positive is not None and negative is not None:
        if positive.get("provenance") != negative.get("provenance"):
            errors.append("positive and negative benchmark provenance must be identical")
        positive_ids = [row.get("id") for row in positive.get("scenarios", []) if isinstance(row, Mapping)]
        negative_ids = [row.get("id") for row in negative.get("scenarios", []) if isinstance(row, Mapping)]
        if positive_ids != negative_ids:
            errors.append("positive and negative benchmark scenario order must match")
    return rates, failures, errors


def _deepeval_metrics(
    role: str, record: Mapping[str, Any], lock: Mapping[str, Any]
) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    source = record.get("source")
    spec = record.get("spec")
    environment = record.get("environment")
    if not isinstance(source, Mapping) or source.get("git_head") != lock.get(
        "candidate_git_head"
    ) or source.get("dirty") is not False:
        errors.append(f"{role} source must bind the clean locked candidate head")
    if not isinstance(spec, Mapping) or spec.get("sha256") != lock.get(
        "deepeval_spec_sha256"
    ):
        errors.append(f"{role} spec hash must match measurement-lock")
    if not isinstance(environment, Mapping) or environment.get("deepeval") != lock.get(
        "deepeval_version"
    ):
        errors.append(f"{role} DeepEval version must match measurement-lock")

    observations = record.get("observations")
    if not isinstance(observations, list):
        return None, [*errors, f"{role} observations must be a list"]
    expected_oracles = {
        "safe": (1.0, True),
        "destructive": (0.0, False),
        "corrupt": (0.0, False),
    }
    observed_names = [
        row.get("name") for row in observations if isinstance(row, Mapping)
    ]
    if len(observations) != 3 or set(observed_names) != set(expected_oracles):
        errors.append(f"{role} must contain the safe/destructive/corrupt oracle trio")
        return None, errors
    matched = 0
    actual_successes = 0
    for row in observations:
        if not isinstance(row, Mapping):
            errors.append(f"{role} observation must be an object")
            continue
        name = row.get("name")
        if name not in expected_oracles:
            continue
        expected_score, expected_success = expected_oracles[name]
        if not _same_number(row.get("expected_score"), expected_score) or row.get(
            "expected_success"
        ) is not expected_success:
            errors.append(f"{role} {name} expected oracle drifted")
        if not _finite_number(row.get("observed_score")) or not isinstance(
            row.get("observed_success"), bool
        ):
            errors.append(f"{role} {name} observed score/success has invalid types")
            continue
        derived = (
            float(row["observed_score"]) == float(row["expected_score"])
            and row["observed_success"] is row["expected_success"]
        )
        if row.get("matched") is not derived:
            errors.append(f"{role} {name} matched is not observation-derived")
        matched += int(derived)
        actual_successes += int(row["observed_success"] is True)
        if row.get("error") is not None:
            errors.append(f"{role} {name} contains an evaluation error")
    computed = {
        "deepeval_oracle_agreement_rate": matched / 3,
        "actual_deepeval_trajectory_pass_rate": matched / 3,
        "cases_total": 3,
        "cases_matched": matched,
        "actual_successes": actual_successes,
    }
    stored = record.get("metrics")
    if not isinstance(stored, Mapping):
        errors.append(f"{role} metrics must be an object")
    else:
        overlapping = set(stored) & set(computed)
        if not overlapping:
            errors.append(f"{role} stores none of the recomputable metrics")
        for key in sorted(overlapping):
            if stored[key] != computed[key]:
                errors.append(f"{role} stored metric {key} is not observation-derived")
    return computed, errors


def _validate_deepeval(
    documents: Mapping[str, dict[str, Any]], lock: Mapping[str, Any]
) -> tuple[dict[str, Any] | None, list[str]]:
    candidate = documents.get("deepeval-candidate")
    negative = documents.get("deepeval-injected-mismatch")
    errors: list[str] = []
    computed: dict[str, Any] | None = None
    if candidate is not None:
        computed, local = _deepeval_metrics("deepeval-candidate", candidate, lock)
        errors.extend(local)
        if computed is not None and computed["deepeval_oracle_agreement_rate"] != 1.0:
            errors.append("deepeval-candidate must agree with all frozen oracles")
    if candidate is not None and negative is not None:
        expected = copy.deepcopy(candidate)
        observations = expected.get("observations")
        safe = (
            [row for row in observations if isinstance(row, dict) and row.get("name") == "safe"]
            if isinstance(observations, list)
            else []
        )
        if len(safe) != 1 or safe[0].get("observed_success") is not True:
            errors.append("deepeval-candidate must contain one successful safe observation")
        else:
            safe[0]["observed_success"] = False
            if negative != expected:
                errors.append(
                    "deepeval-injected-mismatch must be the exact safe success-bit transform"
                )
    return computed, errors


def _validate_ci_receipt(receipt: Mapping[str, Any], expected_head: object) -> list[str]:
    errors: list[str] = []
    run_id = receipt.get("run_id")
    if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id <= 0:
        errors.append("github-actions-receipt run_id must be a positive integer")
    if (
        receipt.get("repository") != "gj3447/ooptdd"
        or receipt.get("workflow_path") != ".github/workflows/ci.yml"
        or receipt.get("head_sha") != expected_head
        or receipt.get("conclusion") != "success"
        or not isinstance(receipt.get("html_url"), str)
        or not isinstance(run_id, int)
        or f"/actions/runs/{run_id}" not in receipt.get("html_url", "")
    ):
        errors.append("github-actions-receipt does not bind a successful candidate CI run")
    jobs = receipt.get("jobs")
    qualification = [
        job
        for job in jobs
        if isinstance(job, Mapping) and job.get("name") == "lakatotree-qualification"
    ] if isinstance(jobs, list) else []
    if len(qualification) != 1 or qualification[0].get("conclusion") != "success":
        errors.append("github-actions-receipt lacks one successful qualification job")
    else:
        steps = qualification[0].get("steps")
        asserted = [
            step
            for step in steps
            if isinstance(step, Mapping)
            and step.get("name") == "Recompute and assert the DeepEval artifact"
            and step.get("conclusion") == "success"
        ] if isinstance(steps, list) else []
        if len(asserted) != 1:
            errors.append("github-actions-receipt lacks the successful DeepEval assertion step")
    artifacts = receipt.get("artifacts")
    artifact_rows = artifacts if isinstance(artifacts, list) else []
    for name in ("tier0-arrival-benchmark", "deepeval-heldout-v2"):
        matching = [
            item
            for item in artifact_rows
            if isinstance(item, Mapping) and item.get("name") == name
        ]
        if len(matching) != 1:
            errors.append(f"github-actions-receipt lacks one retained {name} artifact")
            continue
        digest = matching[0].get("digest")
        if (
            matching[0].get("expired") is not False
            or not isinstance(digest, str)
            or not digest.startswith("sha256:")
            or not _is_sha256(digest.removeprefix("sha256:"))
        ):
            errors.append(f"github-actions-receipt {name} digest is not a live SHA-256")
    return errors


def _artifact_meta_errors(
    label: str,
    meta: object,
    role: str,
    artifacts: Mapping[str, _BoundArtifact],
) -> list[str]:
    artifact = artifacts.get(role)
    if artifact is None:
        return []
    if not isinstance(meta, Mapping):
        return [f"{label} must be an artifact metadata object"]
    errors: list[str] = []
    if meta.get("file") != artifact.source:
        errors.append(f"{label}.file does not bind provenance role {role}")
    if meta.get("sha256") != artifact.sha256:
        errors.append(f"{label}.sha256 does not bind provenance role {role}")
    return errors


def _validate_sequence(
    sequence: Mapping[str, Any],
    artifacts: Mapping[str, _BoundArtifact],
    lock: Mapping[str, Any],
    preregistration: Mapping[str, Any],
    deepeval_metrics: Mapping[str, Any] | None,
) -> list[str]:
    errors: list[str] = []
    source = sequence.get("source")
    if not isinstance(source, Mapping) or source != {
        "git_head": lock.get("candidate_git_head"),
        "dirty": False,
    }:
        errors.append("measurement-sequence source does not bind the clean locked candidate")
    lock_artifact = artifacts.get("measurement-lock")
    prereg_artifact = artifacts.get("preregistration")
    if lock_artifact is not None and sequence.get(
        "measurement_lock_sha256"
    ) != lock_artifact.sha256:
        errors.append("measurement-sequence does not bind the measurement-lock artifact")
    if prereg_artifact is not None and sequence.get(
        "preregistration_sha256"
    ) != prereg_artifact.sha256:
        errors.append("measurement-sequence does not bind the preregistration artifact")
    if sequence.get("benchmark_definition_sha256") != lock.get(
        "benchmark_definition_sha256"
    ):
        errors.append("measurement-sequence benchmark definition does not match lock")

    measurements = sequence.get("measurements")
    if not isinstance(measurements, list) or [
        row.get("role") if isinstance(row, Mapping) else None for row in measurements
    ] != ["positive", "negative", "restored"]:
        errors.append("measurement-sequence roles/order must be positive, negative, restored")
    else:
        for row in measurements:
            role = row["role"]
            metas = row.get("artifacts")
            if not isinstance(metas, Mapping) or set(metas) != {"json", "junit", "markdown"}:
                errors.append(f"measurement-sequence {role} artifact set is incomplete")
                continue
            prefix = f"tier0-{role}"
            for kind in ("json", "junit", "markdown"):
                artifact_role = prefix if kind == "json" else f"{prefix}-{kind}"
                errors.extend(
                    _artifact_meta_errors(
                        f"measurement-sequence.{role}.{kind}",
                        metas.get(kind),
                        artifact_role,
                        artifacts,
                    )
                )

    deepeval = sequence.get("deepeval")
    if not isinstance(deepeval, Mapping):
        errors.append("measurement-sequence deepeval must be an object")
    else:
        errors.extend(
            _artifact_meta_errors(
                "measurement-sequence.deepeval.candidate",
                deepeval.get("candidate"),
                "deepeval-candidate",
                artifacts,
            )
        )
        errors.extend(
            _artifact_meta_errors(
                "measurement-sequence.deepeval.injected_mismatch",
                deepeval.get("injected_mismatch"),
                "deepeval-injected-mismatch",
                artifacts,
            )
        )
        if deepeval.get("injected_mismatch_rejected") is not True:
            errors.append("measurement-sequence must record rejection of DeepEval mismatch")
        if deepeval_metrics is not None and deepeval.get("computed_metrics") != dict(
            deepeval_metrics
        ):
            errors.append("measurement-sequence DeepEval metrics are not observation-derived")

    receipt = sequence.get("prospective_registration")
    if not isinstance(receipt, Mapping) or receipt.get(
        "schema"
    ) != "ooptdd-prospective-git-receipt/v1" or receipt.get(
        "preregistration_is_ancestor"
    ) is not True:
        errors.append("measurement-sequence lacks a prospective published-git receipt")
    else:
        repository = receipt.get("repository")
        if repository != lock.get("registration_repository"):
            errors.append("prospective receipt repository does not match measurement-lock")
        for role, artifact_role in (
            ("preregistration", "preregistration"),
            ("measurement_lock", "measurement-lock"),
        ):
            row = receipt.get(role)
            artifact = artifacts.get(artifact_role)
            if not isinstance(row, Mapping) or artifact is None:
                continue
            if row.get("sha256") != artifact.sha256:
                errors.append(f"prospective receipt {role} hash does not bind artifact")
            if not isinstance(row.get("published_refs"), list) or not row["published_refs"]:
                errors.append(f"prospective receipt {role} has no published refs")
            commit = row.get("commit")
            if (
                not isinstance(commit, str)
                or len(commit) not in {40, 64}
                or any(char not in "0123456789abcdef" for char in commit)
            ):
                errors.append(f"prospective receipt {role} commit is invalid")

    registered_at = preregistration.get("registered_at")
    chronology: list[object] = []
    if isinstance(measurements, list):
        chronology.extend(
            row.get("measured_at") for row in measurements if isinstance(row, Mapping)
        )
    if isinstance(deepeval, Mapping):
        chronology.append(deepeval.get("measured_at"))
    try:
        previous = datetime.fromisoformat(str(registered_at).replace("Z", "+00:00"))
        for value in chronology:
            current = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if current <= previous:
                raise ValueError
            previous = current
    except (TypeError, ValueError):
        errors.append("measurement-sequence chronology must be strictly after preregistration")
    return errors


def _validate_reports(
    artifacts: Mapping[str, _BoundArtifact],
    documents: Mapping[str, dict[str, Any]],
    failures: Mapping[str, list[str]],
) -> list[str]:
    errors: list[str] = []
    positive = artifacts.get("tier0-positive")
    restored = artifacts.get("tier0-restored")
    positive_junit = artifacts.get("tier0-positive-junit")
    restored_junit = artifacts.get("tier0-restored-junit")
    positive_markdown = artifacts.get("tier0-positive-markdown")
    restored_markdown = artifacts.get("tier0-restored-markdown")
    if positive is not None and restored is not None and positive.payload != restored.payload:
        errors.append("tier0-positive and tier0-restored JSON must be byte-identical")
    if (
        positive_junit is not None
        and restored_junit is not None
        and positive_junit.payload != restored_junit.payload
    ):
        errors.append("tier0-positive and tier0-restored JUnit must be byte-identical")
    if (
        positive_markdown is not None
        and restored_markdown is not None
        and positive_markdown.payload != restored_markdown.payload
    ):
        errors.append("tier0-positive and tier0-restored Markdown must be byte-identical")

    for polarity in ("positive", "negative", "restored"):
        role = f"tier0-{polarity}"
        junit = artifacts.get(f"{role}-junit")
        markdown = artifacts.get(f"{role}-markdown")
        benchmark = documents.get(role)
        if junit is not None:
            try:
                root = ElementTree.fromstring(junit.payload)
            except (ElementTree.ParseError, UnicodeError):
                errors.append(f"{role} JUnit must be well-formed XML")
            else:
                if root.tag != "testsuite" or root.get("name") != "ooptdd.arrival-benchmark":
                    errors.append(f"{role} JUnit must identify the arrival benchmark suite")
                testcases = root.findall("testcase")
                failure_names = [
                    case.get("name") for case in testcases if case.find("failure") is not None
                ]
                errors_count = sum(case.find("error") is not None for case in testcases)
                skipped_count = sum(case.find("skipped") is not None for case in testcases)
                try:
                    declared = {
                        "tests": int(root.get("tests", "-1")),
                        "failures": int(root.get("failures", "-1")),
                        "errors": int(root.get("errors", "-1")),
                        "skipped": int(root.get("skipped", "-1")),
                    }
                except ValueError:
                    errors.append(f"{role} JUnit counters must be integers")
                else:
                    observed = {
                        "tests": len(testcases),
                        "failures": len(failure_names),
                        "errors": errors_count,
                        "skipped": skipped_count,
                    }
                    if declared != observed:
                        errors.append(f"{role} JUnit counters are not testcase-derived")
                expected_failures = failures.get(role, [])
                if failure_names != expected_failures or errors_count != 0:
                    errors.append(f"{role} JUnit failure polarity does not match benchmark")
                if benchmark is not None:
                    scenario_ids = [
                        row.get("id")
                        for row in benchmark.get("scenarios", [])
                        if isinstance(row, Mapping)
                    ]
                    testcase_names = [case.get("name") for case in testcases]
                    if any(name not in testcase_names for name in scenario_ids):
                        errors.append(f"{role} JUnit omits benchmark scenarios")
        if markdown is not None:
            try:
                text = markdown.payload.decode("utf-8")
            except UnicodeError:
                errors.append(f"{role} Markdown must be UTF-8")
            else:
                expected_header = (
                    "# ooptdd arrival benchmark — PASS"
                    if polarity != "negative"
                    else "# ooptdd arrival benchmark — FAIL"
                )
                if not text.startswith(expected_header + "\n"):
                    errors.append(f"{role} Markdown pass/fail header does not match benchmark")
                if benchmark is not None and any(
                    str(row.get("id")) not in text
                    for row in benchmark.get("scenarios", [])
                    if isinstance(row, Mapping)
                ):
                    errors.append(f"{role} Markdown omits benchmark scenarios")
    return errors


def _validate_integrity(
    report: Mapping[str, Any],
    record: Mapping[str, Any],
    rates: Mapping[str, float],
    failures: Mapping[str, list[str]],
    artifacts: Mapping[str, _BoundArtifact],
) -> list[str]:
    errors: list[str] = []
    observations = report.get("observations")
    resolved_by_gap: dict[str, bool] = {}
    if not isinstance(observations, list):
        errors.append("integrity-report observations must be a list")
    else:
        for index, row in enumerate(observations):
            if not isinstance(row, Mapping):
                errors.append(f"integrity-report observation[{index}] must be an object")
                continue
            gap_id = row.get("gap_id")
            resolved = row.get("resolved")
            if not isinstance(gap_id, str) or gap_id in resolved_by_gap:
                errors.append("integrity-report gap ids must be unique strings")
                continue
            if not isinstance(resolved, bool):
                errors.append(f"integrity-report gap {gap_id} resolved must be boolean")
                continue
            resolved_by_gap[gap_id] = resolved
        if set(resolved_by_gap) != _EXPECTED_GAPS:
            errors.append("integrity-report must contain exactly the four preregistered gaps")
    unresolved = sum(not value for value in resolved_by_gap.values())
    if report.get("unresolved_evidence_integrity_gaps") != unresolved:
        errors.append("integrity-report unresolved count is not observation-derived")
    if unresolved != 0:
        errors.append("integrity-report leaves unresolved gaps above the preregistered target 0")
    if not _same_number(
        report.get("tier0_required_oracle_match_rate"), rates.get("tier0-positive")
    ):
        errors.append("integrity-report Tier-0 rate does not match positive benchmark")
    if report.get("negative_control_failures") != failures.get("tier0-negative"):
        errors.append("integrity-report negative failures do not match negative benchmark")
    if report.get("restored_byte_identical") is not True:
        errors.append("integrity-report restored_byte_identical must be exactly true")

    measurement = record.get("measurement")
    if not isinstance(measurement, Mapping):
        return errors
    primary = artifacts.get("integrity-report")
    novel_artifact = artifacts.get("tier0-positive")
    if measurement.get("metric") != _PRIMARY_METRIC:
        errors.append(f"measurement metric must be {_PRIMARY_METRIC!r}")
    if measurement.get("value") != unresolved:
        errors.append("record primary measurement value does not match integrity-report")
    if primary is not None and measurement.get("primary_source_sha256") != primary.sha256:
        errors.append("primary_source_sha256 must bind the parsed integrity-report role")
    derived = measurement.get("derived")
    if not isinstance(derived, Mapping) or not _same_number(
        derived.get(_NOVEL_METRIC), report.get(_NOVEL_METRIC)
    ):
        errors.append("record derived Tier-0 rate does not match integrity-report")
    novel = measurement.get("novel_measurement")
    if not isinstance(novel, Mapping):
        errors.append("measurement.novel_measurement must bind the Tier-0 positive artifact")
    else:
        if novel.get("metric") != _NOVEL_METRIC or not _same_number(
            novel.get("value"), report.get(_NOVEL_METRIC)
        ):
            errors.append("record novel measurement value does not match parsed artifacts")
        if novel_artifact is not None and novel.get("source_sha256") != novel_artifact.sha256:
            errors.append("novel source_sha256 must bind the parsed tier0-positive role")
    return errors


def _validate_preregistration(
    record: Mapping[str, Any], prereg: Mapping[str, Any]
) -> list[str]:
    errors: list[str] = []
    record_prereg = record.get("preregistration")
    measurement = record.get("measurement")
    if not isinstance(record_prereg, Mapping) or not isinstance(measurement, Mapping):
        return errors
    prediction = prereg.get("prediction")
    novel_target = prereg.get("novel_target")
    predicted = record_prereg.get("predicted")
    if not isinstance(prediction, Mapping) or not isinstance(predicted, Mapping):
        errors.append("preregistration prediction artifacts must be objects")
        return errors
    if record.get("programme") != prereg.get("programme"):
        errors.append("record programme does not match preregistration artifact")
    if record.get("conjecture") != prereg.get("branch"):
        errors.append("record conjecture does not match preregistration branch")
    comparisons = (
        (record_prereg.get("registered_at"), prereg.get("registered_at"), "registered_at"),
        (record_prereg.get("direction"), prediction.get("direction"), "direction"),
        (record_prereg.get("noise_band"), prediction.get("noise_band"), "noise_band"),
        (predicted.get("metric"), prediction.get("metric"), "predicted metric"),
        (predicted.get("value"), prediction.get("baseline"), "predicted baseline"),
        (record_prereg.get("kill_condition"), prereg.get("kill_condition"), "kill condition"),
    )
    for left, right, label in comparisons:
        if left != right:
            errors.append(f"record {label} does not match preregistration artifact")
    if prediction.get("metric") != _PRIMARY_METRIC or prediction.get("direction") != "lower":
        errors.append("preregistration artifact must predict the lower unresolved-gap metric")
    if not _same_number(prediction.get("target"), 0):
        errors.append("preregistration artifact target must be exactly 0")
    if not _same_number(record_prereg.get("target"), 0):
        errors.append("record preregistration target must be exactly 0")
    if not _same_number(record_prereg.get("max_acceptable"), 0):
        errors.append("record preregistration max_acceptable must be exactly 0")
    value = measurement.get("value")
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value > 0
    ):
        errors.append("unresolved gap count exceeds preregistered max_acceptable 0")

    novel = measurement.get("novel_measurement")
    if not isinstance(novel_target, Mapping) or not isinstance(novel, Mapping):
        errors.append("preregistered novel target and measurement must be objects")
    else:
        if novel_target.get("metric") != _NOVEL_METRIC or novel.get("metric") != _NOVEL_METRIC:
            errors.append("novel metric must be the preregistered Tier-0 oracle rate")
        if novel.get("direction") != "higher" or novel_target.get("direction", "higher") != "higher":
            errors.append("novel measurement direction must be higher")
        if not _same_number(novel_target.get("threshold"), 1) or not _same_number(
            novel.get("threshold"), 1
        ):
            errors.append("novel target threshold must be exactly 1")
        repetitions = novel_target.get("repetitions")
        if repetitions is not None and novel.get("repetitions") != repetitions:
            errors.append("novel measurement repetitions do not match preregistration")
    return errors


def _semantic_bundle_errors(
    record: dict[str, Any],
    artifacts: Mapping[str, _BoundArtifact],
    documents: Mapping[str, dict[str, Any]],
) -> list[str]:
    errors = _schema_errors(documents)
    lock = documents.get("measurement-lock")
    prereg = documents.get("preregistration")
    if lock is None or prereg is None:
        return errors
    errors.extend(_validate_lock(lock))
    errors.extend(_validate_preregistration(record, prereg))
    rates, failures, benchmark_errors = _validate_benchmarks(documents, lock)
    errors.extend(benchmark_errors)
    deepeval_metrics, deepeval_errors = _validate_deepeval(documents, lock)
    errors.extend(deepeval_errors)
    sequence = documents.get("measurement-sequence")
    if sequence is not None:
        errors.extend(
            _validate_sequence(sequence, artifacts, lock, prereg, deepeval_metrics)
        )
        candidate = documents.get("deepeval-candidate")
        sequence_deepeval = sequence.get("deepeval")
        if (
            candidate is not None
            and isinstance(sequence_deepeval, Mapping)
            and sequence_deepeval.get("measured_at") != candidate.get("measured_at")
        ):
            errors.append("measurement-sequence DeepEval timestamp does not match artifact")
    receipt = documents.get("github-actions-receipt")
    if receipt is not None:
        errors.extend(_validate_ci_receipt(receipt, lock.get("candidate_git_head")))
    integrity = documents.get("integrity-report")
    if integrity is not None:
        if integrity.get("candidate_git_head") != lock.get("candidate_git_head"):
            errors.append("integrity-report candidate head does not match measurement-lock")
        errors.extend(_validate_integrity(integrity, record, rates, failures, artifacts))
    errors.extend(_validate_reports(artifacts, documents, failures))

    positive = documents.get("tier0-positive")
    restored = documents.get("tier0-restored")
    if positive is not None and restored is not None and positive != restored:
        errors.append("tier0-positive and tier0-restored semantics must be identical")
    harness = record.get("harness")
    if isinstance(harness, Mapping):
        if harness.get("git_commit") != lock.get("candidate_git_head"):
            errors.append("record harness git_commit does not match measurement-lock")
        if harness.get("benchmark_definition_sha256") != lock.get(
            "benchmark_definition_sha256"
        ):
            errors.append("record harness benchmark definition does not match measurement-lock")
    return errors


def _artifact_binding_errors(record: dict[str, Any], artifact_root: Path) -> list[str]:
    """Verify required roles, file bytes, schemas, and cross-artifact semantics."""
    artifacts, errors = _read_bound_artifacts(record, artifact_root)
    documents, parse_errors = _parse_json_artifacts(artifacts)
    errors.extend(parse_errors)
    errors.extend(_semantic_bundle_errors(record, artifacts, documents))

    measurement = record.get("measurement") or {}
    if isinstance(measurement, Mapping):
        primary_sha = measurement.get("primary_source_sha256")
        novel = measurement.get("novel_measurement")
        if primary_sha is not None and primary_sha not in {
            artifact.sha256 for artifact in artifacts.values()
        }:
            errors.append("primary_source_sha256 does not bind a verified provenance input")
        if isinstance(novel, Mapping):
            novel_sha = novel.get("source_sha256")
            if novel_sha not in {artifact.sha256 for artifact in artifacts.values()}:
                errors.append("novel source_sha256 does not bind a verified provenance input")
            if primary_sha == novel_sha:
                errors.append("primary and novel sources resolve to the same artifact hash")
    return errors


def validation_errors(record: object, *, artifact_root: Path = _ROOT) -> list[str]:
    """Apply the canonical contract plus the programme's fail-closed guards."""
    if not isinstance(record, dict):
        return ["evidence record must be a JSON object"]

    try:
        errors = list(validate_record(record))
    except (AttributeError, TypeError, ValueError) as exc:
        # The v1 reference validator intentionally stays tiny and assumes object
        # members.  Its consumer boundary must still reject malformed JSON shapes
        # instead of crashing open.
        errors = [f"canonical validate_record could not validate shape: {type(exc).__name__}"]

    # The canonical validator rejects ``verdict`` at the two standard locations.
    # The recursive check also closes aliases nested in derived data or findings.
    for path in _authored_verdict_paths(record):
        errors.append(f"self-authored verdict field is forbidden: {path}")

    for field in ("preregistration", "measurement", "provenance", "harness"):
        if not isinstance(record.get(field), Mapping):
            errors.append(f"{field} must be an object")

    preregistration = record.get("preregistration") or {}
    if (
        not isinstance(preregistration, Mapping)
        or preregistration.get("registered_before_measurement") is not True
    ):
        errors.append("registered-before-measurement must be exactly true")

    # is_grounded includes validate_record and additionally requires the explicit
    # provenance.grounded flag; do not let an input pointer alone imply grounding.
    try:
        grounded = is_grounded(record)
    except (AttributeError, TypeError, ValueError):
        grounded = False
    if not grounded:
        errors.append("canonical is_grounded(record) check failed")
    provenance = record.get("provenance") or {}
    if not isinstance(provenance, Mapping) or provenance.get("grounded") is not True:
        errors.append("provenance.grounded must be exactly true")

    alignment_error = _metric_alignment_error(record)
    if alignment_error:
        errors.append(alignment_error)
    novelty_error = _novel_measurement_error(record)
    if novelty_error:
        errors.append(novelty_error)
    errors.extend(_artifact_binding_errors(record, artifact_root))

    # Preserve first occurrence while keeping stable validator/path order.
    return list(dict.fromkeys(errors))


def consume_record(
    record_or_path: Mapping[str, Any] | str | Path,
    *,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    """Validate evidence and derive a timestamp-free engine judgement.

    Invalid evidence never reaches ``judge_record``.  ``status='judged'`` means
    the engine ran; the resulting verdict may still be rejected or equivalent.
    """
    if isinstance(record_or_path, (str, Path)):
        record_path = Path(record_or_path)
        try:
            record: object = load_record(record_path)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return {
                "schema": OUTPUT_SCHEMA,
                "status": "invalid",
                "errors": [f"unreadable evidence record: {type(exc).__name__}"],
            }
        resolved_artifact_root = artifact_root or record_path.resolve().parent
    else:
        record = dict(record_or_path)
        resolved_artifact_root = artifact_root or _ROOT

    errors = validation_errors(record, artifact_root=resolved_artifact_root)
    if errors:
        result: dict[str, Any] = {
            "schema": OUTPUT_SCHEMA,
            "status": "invalid",
            "errors": errors,
        }
        if isinstance(record, dict):
            try:
                record_source = source_id(record)
            except (AttributeError, TypeError, ValueError):
                record_source = None
            result.update(
                programme=record.get("programme"),
                conjecture=record.get("conjecture"),
                source_record=record_source,
            )
        return result

    assert isinstance(record, dict)  # established by validation_errors
    judged = judge_record(record)
    if judged["status"] == "judged":
        measurement = record["measurement"]
        novel = measurement.get("novel_measurement")
        if isinstance(novel, Mapping):
            preregistration = record["preregistration"]
            prediction = Prediction(
                metric_name=judged["metric"],
                direction=judged["direction"],
                baseline_value=judged["baseline"],
                noise_band=float(preregistration.get("noise_band") or 0.0),
            )
            engine_verdict = judge(
                prediction,
                judged["measured"],
                NovelTarget(
                    metric_name=novel["metric"],
                    direction=novel["direction"],
                    threshold=float(novel["threshold"]),
                ),
                float(novel["value"]),
                measured_sha=measurement["primary_source_sha256"],
                novel_sha=novel["source_sha256"],
                require_independent_source=True,
            )
            judged = {
                **judged,
                "verdict": engine_verdict.verdict,
                "delta": engine_verdict.delta,
                "improved": engine_verdict.improved,
                "novel": engine_verdict.novel,
                "reason": engine_verdict.reason,
                "novel_metric": novel["metric"],
                "novel_measured": float(novel["value"]),
            }
    result = {
        "schema": OUTPUT_SCHEMA,
        "status": judged["status"],
        "programme": record.get("programme"),
        "conjecture": record.get("conjecture"),
        "source_record": judged.get("source_record", source_id(record)),
    }
    if judged["status"] == "judged":
        # Fixed projection: no clock, path, candidate SHA, or producer-authored
        # verdict enters this envelope.  Every value is emitted by record_judge.
        for key in (
            "verdict",
            "metric",
            "baseline",
            "baseline_key",
            "measured",
            "direction",
            "delta",
            "improved",
            "novel",
            "novel_metric",
            "novel_measured",
            "reason",
        ):
            result[key] = judged.get(key)
    elif judged["status"] == "abstain":
        for key in ("reason", "predicted_metric", "measurement_metric"):
            result[key] = judged.get(key)
    else:
        result["errors"] = judged.get("errors") or ["record_judge rejected the record"]
    return result


def canonical_json(result: Mapping[str, Any]) -> str:
    """Stable CLI representation; timestamps are neither read nor generated."""
    return json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail-closed LakatoTree consumer for an ooptdd efficacy evidence record"
    )
    parser.add_argument("record", type=Path)
    parser.add_argument("--artifact-root", type=Path)
    args = parser.parse_args(argv)
    result = consume_record(args.record, artifact_root=args.artifact_root)
    print(canonical_json(result))
    # A rejected/equivalent verdict is still a successful, honest judgement.
    # Only malformed evidence or an engine abstention makes the adapter fail.
    return 0 if result["status"] == "judged" else 2


if __name__ == "__main__":
    raise SystemExit(main())
