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
import json
import math
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

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


def validation_errors(record: object) -> list[str]:
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

    # Preserve first occurrence while keeping stable validator/path order.
    return list(dict.fromkeys(errors))


def consume_record(record_or_path: Mapping[str, Any] | str | Path) -> dict[str, Any]:
    """Validate evidence and derive a timestamp-free engine judgement.

    Invalid evidence never reaches ``judge_record``.  ``status='judged'`` means
    the engine ran; the resulting verdict may still be rejected or equivalent.
    """
    if isinstance(record_or_path, (str, Path)):
        try:
            record: object = load_record(record_or_path)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return {
                "schema": OUTPUT_SCHEMA,
                "status": "invalid",
                "errors": [f"unreadable evidence record: {type(exc).__name__}"],
            }
    else:
        record = dict(record_or_path)

    errors = validation_errors(record)
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
    args = parser.parse_args(argv)
    result = consume_record(args.record)
    print(canonical_json(result))
    # A rejected/equivalent verdict is still a successful, honest judgement.
    # Only malformed evidence or an engine abstention makes the adapter fail.
    return 0 if result["status"] == "judged" else 2


if __name__ == "__main__":
    raise SystemExit(main())
