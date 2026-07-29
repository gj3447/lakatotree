"""Scientific backtest primitives for LakatoTree.

This module deliberately separates three questions which the historical C3
fixture conflated:

* did a primary metric improve (``naive``),
* was that improvement prospectively registered (``popper_like``), and
* did the real LakatoTree judge also corroborate independent excess content
  (``lakatotree``).

The module does not ship a confirmatory corpus and it never manufactures a
scientific verdict.  It validates an externally adjudicated sealed manifest,
runs the real :func:`lakatos.verdict.judge.judge` kernel, and reports paired
binary statistics.  Existing named C3 examples are development-only.
"""
from __future__ import annotations

import hashlib
import json
import math
import copy
import re
from datetime import datetime
from pathlib import Path
from statistics import NormalDist
from typing import Any

from lakatos.grounding import wilson_lower_bound
from lakatos.io.envfp import environment_fingerprint, fingerprint_sha
from lakatos.measurement_lock import (
    build_measurement_lock as _build_canonical_measurement_lock,
    lock_dirty,
    lock_key,
    lock_sha,
)
from lakatos.temporal import (
    AnchorInvalid,
    anchor_ordering_ok,
    anchor_strict_ordering_ok,
    verify_temporal_quorum,
)
from lakatos.verdict.judge import NovelTarget, Prediction, judge
from lakatos.write_cert import did_key_decode, ed25519_verify


SCHEMA_VERSION = "lakatotree-scientific-backtest/v1"
LOCK_SCHEMA_VERSION = "lakatotree-scientific-backtest-lock/v2"
ANCHOR_SCHEMA_VERSION = "lakatotree-scientific-backtest-anchor/v1"
ALLOWLIST_SCHEMA_VERSION = "lakatotree-witness-allowlist/v1"
PILOT_SCHEMA_VERSION = "lakatotree-scientific-backtest-pilot/v1"
CHRONOLOGY_RECEIPT_SCHEMA_VERSION = "lakatotree-chronology-receipt/v1"
ORDERING_ATTESTATION_SCHEMA_VERSION = "lakatotree-ordering-attestation/v1"
REPLAYER_ALLOWLIST_SCHEMA_VERSION = "lakatotree-replayer-allowlist/v1"
BLIND_ATTESTATION_SCHEMA_VERSION = "lakatotree-blind-adjudication/v1"
EXPOSURE_ATTESTATION_SCHEMA_VERSION = "lakatotree-prior-exposure/v1"
ARMS = ("naive", "popper_like", "lakatotree")
GROUND_TRUTHS = ("progressive", "nonprogressive")
SOURCE_CLASSES = ("dogfood", "external", "synthetic_sabotage")
RESULT_STATUSES = frozenset({"SUPPORTED", "NOT_SUPPORTED", "INCONCLUSIVE_UNDERPOWERED"})
BACKTEST_COMMAND = "python -m lakatos.backtest_cli run"

_REPO_ROOT = Path(__file__).resolve().parents[1]
_REQUIRED_REPO_DEPS = (
    "lakatos/__init__.py",
    "lakatos/backtest.py",
    "lakatos/backtest_cli.py",
    "lakatos/grounding.py",
    "lakatos/io/__init__.py",
    "lakatos/io/envfp.py",
    "lakatos/measurement_lock.py",
    "lakatos/resources/scientific_backtest_anchor.v1.schema.json",
    "lakatos/resources/scientific_backtest_chronology.v1.schema.json",
    "lakatos/resources/scientific_backtest_manifest.v1.schema.json",
    "lakatos/resources/scientific_backtest_pilot.v1.schema.json",
    "lakatos/resources/scientific_backtest_provenance.v1.schema.json",
    "lakatos/resources/scientific_backtest_protocol.v1.json",
    "lakatos/resources/scientific_backtest_replayer_allowlist.v1.schema.json",
    "lakatos/temporal.py",
    "lakatos/verdict/__init__.py",
    "lakatos/verdict/judge.py",
    "lakatos/write_cert.py",
)

_TOP_LEVEL_KEYS = {
    "schema_version", "experiment_id", "phase", "status", "measurement_started",
    "protocol", "preregistration", "cases",
}
_PROTOCOL_KEYS = {
    "familywise_alpha", "pairwise_alpha", "min_power",
    "conditional_accuracy_advantage", "accuracy_discordance_rate_floor",
    "min_sensitivity_wilson_lb", "sensitivity_alternative",
}
_CASE_KEYS = {
    "case_id", "source_class", "ground_truth", "ground_truth_evidence",
    "adjudicator_ids", "exposure_status", "case_package_path", "case_package_sha256",
    "prediction_registered_before_measurement", "chronology", "prediction", "measurement",
    "novel_target", "sampling_unit_id", "component_id", "source_entity_ids",
}
_PREDICTION_KEYS = {"metric_name", "direction", "baseline_value", "noise_band", "scale_type"}
_MEASUREMENT_KEYS = {"value", "source_sha256"}
_NOVEL_KEYS = {"metric_name", "direction", "threshold", "measured", "source_sha256", "novelty_sense"}
_CHRONOLOGY_KEYS = {
    "prediction_registered_at", "measurement_observed_at", "prediction_receipt_path",
    "prediction_receipt_sha256", "measurement_receipt_path", "measurement_receipt_sha256",
    "ordering_attestation_path", "ordering_attestation_sha256",
}
_PREREGISTRATION_KEYS = {
    "frozen_at", "code_commit", "sampling_frame", "target_population", "pilot_receipt",
    "blind_adjudication", "prior_exposure", "temporal_anchor", "producer_did",
    "curator_dids", "replayer_allowlist",
}

_REPLAY_ATTESTATION_DOMAIN = b"lakatotree-independent-replay/v1\n"
_BLIND_ATTESTATION_DOMAIN = b"lakatotree-blind-adjudication/v1\n"
_EXPOSURE_ATTESTATION_DOMAIN = b"lakatotree-prior-exposure/v1\n"
_ORDERING_ATTESTATION_DOMAIN = b"lakatotree-ordering-attestation/v1\n"


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _canonical_json_file_bytes(value: Any) -> bytes:
    return _canonical_json_bytes(value) + b"\n"


def _extra_keys(value: Any, allowed: set[str], label: str) -> list[str]:
    if not isinstance(value, dict):
        return []
    return [f"{label} contains unsupported field: {key}" for key in sorted(set(value) - allowed)]


def _valid_iso8601(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _valid_relative_path(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts


def _valid_did(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        did_key_decode(value.strip())
    except (TypeError, ValueError):
        return False
    return True


def _sha_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _prediction_receipt_payload(case: dict) -> dict:
    novel = case.get("novel_target")
    novel_spec = None
    if isinstance(novel, dict):
        novel_spec = {
            key: novel.get(key)
            for key in ("metric_name", "direction", "threshold", "novelty_sense")
            if key in novel
        }
    return {
        "case_id": case.get("case_id"),
        "prediction_registered_before_measurement": case.get(
            "prediction_registered_before_measurement"
        ),
        "prediction": case.get("prediction"),
        "novel_target_spec": novel_spec,
    }


def _measurement_receipt_payload(case: dict) -> dict:
    novel = case.get("novel_target")
    novel_observation = None
    if isinstance(novel, dict):
        novel_observation = {
            "measured": novel.get("measured"),
            "source_sha256": novel.get("source_sha256"),
        }
    return {
        "case_id": case.get("case_id"),
        "measurement": case.get("measurement"),
        "novel_observation": novel_observation,
    }


def _ground_truth_assignment(cases: list[dict]) -> list[dict]:
    return [
        {
            "case_id": case.get("case_id"),
            "ground_truth": case.get("ground_truth"),
            "ground_truth_evidence": case.get("ground_truth_evidence"),
        }
        for case in cases
        if case.get("source_class") == "external"
    ]


def _holdout_identity_payload(cases: list[dict]) -> dict:
    external = [case for case in cases if case.get("source_class") == "external"]
    return {
        "sampling_unit_ids": sorted(case.get("sampling_unit_id") for case in external),
        "component_ids": sorted(case.get("component_id") for case in external),
        "source_entity_ids": sorted(
            entity
            for case in external
            for entity in (case.get("source_entity_ids") or [])
        ),
    }


def build_replay_attestation_payload(
    *,
    measurement_lock_key: str,
    producer_result_sha256: str,
    result_status: str,
    replay_environment_sha256: str,
    producer_did: str,
    replayer_did: str,
) -> dict[str, str]:
    """Canonical payload an allow-listed external replayer must sign."""

    return {
        "measurement_lock_key": measurement_lock_key,
        "producer_result_sha256": producer_result_sha256,
        "result_status": result_status,
        "replay_environment_sha256": replay_environment_sha256,
        "producer_did": producer_did,
        "replayer_did": replayer_did,
    }


def replay_attestation_bytes(payload: dict) -> bytes:
    return _REPLAY_ATTESTATION_DOMAIN + _canonical_json_bytes(payload)


def _signed_attestation_bytes(
    domain: bytes, attestation: dict, signature_field: str
) -> bytes:
    if not isinstance(attestation, dict):
        raise ValueError("attestation must be an object")
    unsigned = {
        key: value for key, value in attestation.items() if key != signature_field
    }
    return domain + _canonical_json_bytes(unsigned)


def blind_attestation_bytes(attestation: dict) -> bytes:
    """Canonical curator-signed blind-ground-truth statement."""

    return _signed_attestation_bytes(
        _BLIND_ATTESTATION_DOMAIN, attestation, "curator_signatures"
    )


def exposure_attestation_bytes(attestation: dict) -> bytes:
    """Canonical curator-signed prior-exposure statement."""

    return _signed_attestation_bytes(
        _EXPOSURE_ATTESTATION_DOMAIN, attestation, "curator_signatures"
    )


def ordering_attestation_bytes(attestation: dict) -> bytes:
    """Canonical adjudicator-signed prediction-before-measurement statement."""

    return _signed_attestation_bytes(
        _ORDERING_ATTESTATION_DOMAIN, attestation, "attestor_signatures"
    )


def _signature_errors(
    *,
    dids: Any,
    signatures: Any,
    message: bytes,
    label: str,
) -> list[str]:
    """Verify one Ed25519 signature from every declared role DID."""

    if (
        not isinstance(dids, list)
        or not dids
        or len(dids) != len(set(dids))
        or any(not _valid_did(value) for value in dids)
    ):
        return [f"{label} signer DIDs are invalid"]
    if not isinstance(signatures, dict) or set(signatures) != set(dids):
        return [f"{label} signatures must cover every declared DID exactly once"]
    errors: list[str] = []
    for did in dids:
        raw = signatures.get(did)
        try:
            signature = bytes.fromhex(raw) if isinstance(raw, str) else b""
            valid = len(signature) == 64 and ed25519_verify(
                did_key_decode(did), message, signature
            )
        except (TypeError, ValueError):
            valid = False
        if not valid:
            errors.append(f"{label} signature invalid for {did}")
    return errors


def project_device_input(case: dict) -> dict:
    """Project the only fields visible to an experimental device.

    Ground truth, source class, adjudicator identity, and evidence references
    are structurally absent.  Returning a deep copy also prevents an adapter
    from mutating the sealed manifest through a shared nested object.
    """

    prediction = case.get("prediction") if isinstance(case.get("prediction"), dict) else {}
    measurement = case.get("measurement") if isinstance(case.get("measurement"), dict) else {}
    novel = case.get("novel_target")
    projected_novel = None
    if isinstance(novel, dict):
        projected_novel = {key: novel.get(key) for key in _NOVEL_KEYS if key in novel}
    chronology = case.get("chronology")
    preregistered = case.get("prediction_registered_before_measurement")
    if isinstance(chronology, dict):
        preregistered = anchor_strict_ordering_ok(
            chronology.get("prediction_registered_at", ""),
            chronology.get("measurement_observed_at", ""),
        )
    return copy.deepcopy({
        "prediction_registered_before_measurement": preregistered,
        "prediction": {key: prediction.get(key) for key in _PREDICTION_KEYS if key in prediction},
        "measurement": {key: measurement.get(key) for key in _MEASUREMENT_KEYS if key in measurement},
        "novel_target": projected_novel,
    })


def _inline_device_sha256(case: dict) -> str:
    return hashlib.sha256(_canonical_json_bytes(project_device_input(case))).hexdigest()


def _strict_object(pairs: list[tuple[str, Any]]) -> dict:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate JSON key: {key}")
        out[key] = value
    return out


def _reject_json_constant(value: str):
    raise ValueError(f"non-finite JSON constant is forbidden: {value}")


def load_manifest(path: str | Path) -> dict:
    """Load JSON without duplicate-key or NaN/Infinity ambiguity."""

    raw = Path(path).expanduser().resolve().read_text(encoding="utf-8")
    parsed = json.loads(
        raw,
        object_pairs_hook=_strict_object,
        parse_constant=_reject_json_constant,
    )
    if not isinstance(parsed, dict):
        raise ValueError("manifest must be a JSON object")
    return parsed


def _load_json_object(path: Path) -> dict:
    parsed = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_strict_object,
        parse_constant=_reject_json_constant,
    )
    if not isinstance(parsed, dict):
        raise ValueError(f"expected JSON object: {path}")
    return parsed


def _validate_artifact_ref(value: Any, label: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{label} must be an object"]
    errors = _extra_keys(value, {"path", "sha256"}, label)
    if not _valid_relative_path(value.get("path")):
        errors.append(f"{label}.path must be a non-escaping relative path")
    if not _is_sha256(value.get("sha256")):
        errors.append(f"{label}.sha256 must be a sha256 hex digest")
    return errors


def _validate_preregistration(prereg: dict) -> list[str]:
    errors = _validate_artifact_ref(
        prereg.get("pilot_receipt"), "preregistration.pilot_receipt"
    )
    errors.extend(_validate_artifact_ref(
        prereg.get("replayer_allowlist"), "preregistration.replayer_allowlist"
    ))
    producer_did = prereg.get("producer_did")
    curator_dids = prereg.get("curator_dids")
    if not _valid_did(producer_did):
        errors.append("preregistration.producer_did must be a valid did:key")
    if (
        not isinstance(curator_dids, list)
        or len(curator_dids) < 2
        or len(curator_dids) != len(set(curator_dids))
        or any(not _valid_did(value) for value in curator_dids)
    ):
        errors.append("preregistration.curator_dids must contain two unique valid did:key values")
    elif producer_did in curator_dids:
        errors.append("producer_did must be distinct from curator_dids")
    blind = prereg.get("blind_adjudication")
    if not isinstance(blind, dict):
        errors.append("preregistration.blind_adjudication must be an object")
    else:
        errors.extend(_extra_keys(
            blind,
            {"completed_at", "attestation_path", "attestation_sha256", "device_outputs_seen"},
            "preregistration.blind_adjudication",
        ))
        if not _valid_iso8601(blind.get("completed_at")):
            errors.append("preregistration.blind_adjudication.completed_at must be ISO-8601")
        if not _valid_relative_path(blind.get("attestation_path")):
            errors.append("preregistration.blind_adjudication.attestation_path must be relative")
        if not _is_sha256(blind.get("attestation_sha256")):
            errors.append("preregistration.blind_adjudication.attestation_sha256 must be sha256")
        if blind.get("device_outputs_seen") is not False:
            errors.append("blind adjudication must attest device_outputs_seen=false before freeze")
        if (
            _valid_iso8601(blind.get("completed_at"))
            and _valid_iso8601(prereg.get("frozen_at"))
            and not anchor_strict_ordering_ok(
                blind["completed_at"], prereg["frozen_at"]
            )
        ):
            errors.append("blind adjudication must complete strictly before manifest freeze")
    exposure = prereg.get("prior_exposure")
    if not isinstance(exposure, dict):
        errors.append("preregistration.prior_exposure must be an object")
    else:
        errors.extend(_extra_keys(
            exposure,
            {"attestation_path", "attestation_sha256", "holdout_exposed_to_developers"},
            "preregistration.prior_exposure",
        ))
        if not _valid_relative_path(exposure.get("attestation_path")):
            errors.append("preregistration.prior_exposure.attestation_path must be relative")
        if not _is_sha256(exposure.get("attestation_sha256")):
            errors.append("preregistration.prior_exposure.attestation_sha256 must be sha256")
        if exposure.get("holdout_exposed_to_developers") is not False:
            errors.append("confirmatory holdout must attest no prior developer exposure")
    anchor = prereg.get("temporal_anchor")
    if not isinstance(anchor, dict):
        errors.append("preregistration.temporal_anchor must be an object")
    else:
        errors.extend(_extra_keys(
            anchor,
            {"receipt_path", "witness_allowlist_path", "witness_allowlist_sha256", "threshold"},
            "preregistration.temporal_anchor",
        ))
        for field in ("receipt_path", "witness_allowlist_path"):
            if not _valid_relative_path(anchor.get(field)):
                errors.append(f"preregistration.temporal_anchor.{field} must be relative")
        if not _is_sha256(anchor.get("witness_allowlist_sha256")):
            errors.append("preregistration.temporal_anchor.witness_allowlist_sha256 must be sha256")
        threshold = anchor.get("threshold")
        if not isinstance(threshold, int) or isinstance(threshold, bool) or threshold < 2:
            errors.append("preregistration.temporal_anchor.threshold must be an integer >= 2")
    return errors


def validate_manifest(manifest: dict) -> list[str]:
    """Return all fail-closed structural errors in a backtest manifest.

    Confirmatory manifests must also satisfy the preregistered joint power
    plan computed from class-balanced case count and the pilot discordance
    floor.  The observed run is checked again by :func:`analyze_decisions`;
    an unexpectedly underpowered result remains visible as
    ``INCONCLUSIVE_UNDERPOWERED`` instead of disappearing.
    """

    errors: list[str] = []
    if not isinstance(manifest, dict):
        return ["manifest must be a JSON object"]
    errors.extend(_extra_keys(manifest, _TOP_LEVEL_KEYS, "manifest"))
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if not isinstance(manifest.get("experiment_id"), str) or not manifest["experiment_id"].strip():
        errors.append("experiment_id is required")

    phase = manifest.get("phase")
    if phase not in ("development", "confirmatory"):
        errors.append("phase must be development or confirmatory")
    if manifest.get("status") not in ("draft", "sealed"):
        errors.append("status must be draft or sealed")
    if phase == "confirmatory" and manifest.get("status") != "sealed":
        errors.append("confirmatory manifest must be sealed before measurement")
    if phase == "confirmatory" and manifest.get("measurement_started") is not False:
        errors.append("confirmatory manifest must record measurement_started=false at freeze")

    protocol = manifest.get("protocol")
    if not isinstance(protocol, dict):
        errors.append("protocol must be an object")
        protocol = {}
    errors.extend(_extra_keys(protocol, _PROTOCOL_KEYS, "protocol"))
    familywise = protocol.get("familywise_alpha")
    pairwise = protocol.get("pairwise_alpha")
    if not _finite_number(familywise) or not 0 < familywise < 1:
        errors.append("protocol.familywise_alpha must be between 0 and 1")
    if not _finite_number(pairwise) or not 0 < pairwise < 1:
        errors.append("protocol.pairwise_alpha must be between 0 and 1")
    elif _finite_number(familywise) and pairwise > familywise / 2 + 1e-12:
        errors.append("pairwise_alpha must not exceed Bonferroni familywise_alpha/2")
    min_power = protocol.get("min_power")
    if not _finite_number(min_power) or not 0 < min_power < 1:
        errors.append("protocol.min_power must be between 0 and 1")
    advantage = protocol.get("conditional_accuracy_advantage")
    if not _finite_number(advantage) or not 0.5 < advantage < 1:
        errors.append("protocol.conditional_accuracy_advantage must be between 0.5 and 1")
    discordance_rate = protocol.get("accuracy_discordance_rate_floor")
    if not _finite_number(discordance_rate) or not 0 < discordance_rate <= 1:
        errors.append("protocol.accuracy_discordance_rate_floor must be in (0, 1]")
    sensitivity_floor = protocol.get("min_sensitivity_wilson_lb")
    if not _finite_number(sensitivity_floor) or not 0 <= sensitivity_floor <= 1:
        errors.append("protocol.min_sensitivity_wilson_lb must be in [0, 1]")
    sensitivity_alternative = protocol.get("sensitivity_alternative")
    if not _finite_number(sensitivity_alternative) or not 0 < sensitivity_alternative <= 1:
        errors.append("protocol.sensitivity_alternative must be in (0, 1]")
    if phase == "confirmatory":
        fixed = {
            "familywise_alpha": 0.05,
            "pairwise_alpha": 0.025,
            "min_power": 0.8,
            "conditional_accuracy_advantage": 0.8,
            "min_sensitivity_wilson_lb": 0.7,
            "sensitivity_alternative": 0.9,
        }
        for key, expected in fixed.items():
            if protocol.get(key) != expected:
                errors.append(f"confirmatory protocol.{key} must equal frozen value {expected}")

    prereg = manifest.get("preregistration")
    if prereg is not None and not isinstance(prereg, dict):
        errors.append("preregistration must be an object")
        prereg = {}
    if isinstance(prereg, dict):
        errors.extend(_extra_keys(prereg, _PREREGISTRATION_KEYS, "preregistration"))
    if phase == "confirmatory":
        if not isinstance(prereg, dict):
            errors.append("confirmatory manifest requires preregistration provenance")
            prereg = {}
        if not _valid_iso8601(prereg.get("frozen_at")):
            errors.append("preregistration.frozen_at must be an ISO-8601 timestamp")
        code_commit = prereg.get("code_commit")
        if not isinstance(code_commit, str) or not re.fullmatch(r"[0-9a-fA-F]{40,64}", code_commit):
            errors.append("preregistration.code_commit must be a 40-64 digit hex commit id")
        for field in ("sampling_frame", "target_population"):
            if not isinstance(prereg.get(field), str) or not prereg[field].strip():
                errors.append(f"preregistration.{field} is required")
        errors.extend(_validate_preregistration(prereg))

    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        errors.append("cases must be a non-empty list")
        return errors

    seen: set[str] = set()
    chronology_paths: set[str] = set()
    for index, case in enumerate(cases):
        prefix = f"cases[{index}]"
        if not isinstance(case, dict):
            errors.append(f"{prefix} must be an object")
            continue
        errors.extend(_extra_keys(case, _CASE_KEYS, prefix))
        case_id = case.get("case_id")
        case_id = case_id.strip() if isinstance(case_id, str) else ""
        if not case_id:
            errors.append(f"{prefix}.case_id is required")
        elif case_id in seen:
            errors.append(f"duplicate case_id: {case_id}")
        seen.add(case_id)
        if case.get("source_class") not in SOURCE_CLASSES:
            errors.append(f"{prefix}.source_class must be one of {SOURCE_CLASSES}")
        if case.get("ground_truth") not in GROUND_TRUTHS:
            errors.append(f"{prefix}.ground_truth must be one of {GROUND_TRUTHS}")
        evidence = case.get("ground_truth_evidence")
        if (
            not isinstance(evidence, list) or not evidence
            or any(not isinstance(item, str) or not item.strip() for item in evidence)
        ):
            errors.append(f"{prefix}.ground_truth_evidence must be non-empty")
        adjudicators = case.get("adjudicator_ids")
        valid_adjudicators = (
            isinstance(adjudicators, list)
            and all(isinstance(item, str) and item.strip() for item in adjudicators)
            and len({item.strip() for item in adjudicators}) == len(adjudicators)
        )
        if not valid_adjudicators:
            errors.append(f"{prefix}.adjudicator_ids must contain unique non-blank strings")
        if case.get("source_class") == "external" and (
            not valid_adjudicators or len(adjudicators) < 2
        ):
            errors.append(f"{prefix} external ground truth requires two independent adjudicators")
        if phase == "confirmatory" and (
            not valid_adjudicators or len(adjudicators) < 2
        ):
            errors.append(f"{prefix} confirmatory chronology requires two signed adjudicators")
        if phase == "confirmatory" and case.get("exposure_status") != "sealed_holdout":
            errors.append(f"{prefix} confirmatory case is not a sealed holdout")
        if phase == "confirmatory":
            for field in ("sampling_unit_id", "component_id"):
                if not isinstance(case.get(field), str) or not case[field].strip():
                    errors.append(f"{prefix}.{field} is required for confirmatory cases")
            source_entities = case.get("source_entity_ids")
            if (
                not isinstance(source_entities, list)
                or not source_entities
                or len(source_entities) != len(set(source_entities))
                or any(not isinstance(value, str) or not value.strip() for value in source_entities)
            ):
                errors.append(
                    f"{prefix}.source_entity_ids must contain unique non-blank ids"
                )
            if not _valid_relative_path(case.get("case_package_path")):
                errors.append(
                    f"{prefix}.case_package_path must be a non-escaping relative path"
                )
            if isinstance(prereg, dict) and isinstance(prereg.get("curator_dids"), list):
                if not valid_adjudicators or not set(adjudicators).issubset(
                    set(prereg["curator_dids"])
                ):
                    errors.append(f"{prefix}.adjudicator_ids must be preregistered curator_dids")
        if not _is_sha256(case.get("case_package_sha256")):
            errors.append(f"{prefix}.case_package_sha256 must be a sha256 hex digest")
        elif not case.get("case_package_path") and (
            case.get("case_package_sha256") != _inline_device_sha256(case)
        ):
            errors.append(
                f"{prefix}.case_package_sha256 does not bind the canonical inline device_input"
            )
        if case.get("case_package_path") is not None and (
            not isinstance(case.get("case_package_path"), str)
            or not case["case_package_path"].strip()
        ):
            errors.append(f"{prefix}.case_package_path must be a non-blank string")
        if not isinstance(case.get("prediction_registered_before_measurement"), bool):
            errors.append(f"{prefix}.prediction_registered_before_measurement must be boolean")
        chronology = case.get("chronology")
        if phase == "confirmatory":
            if not isinstance(chronology, dict):
                errors.append(f"{prefix}.chronology is required for confirmatory cases")
            else:
                errors.extend(_extra_keys(chronology, _CHRONOLOGY_KEYS, f"{prefix}.chronology"))
                pred_at = chronology.get("prediction_registered_at")
                measured_at = chronology.get("measurement_observed_at")
                if not _valid_iso8601(pred_at) or not _valid_iso8601(measured_at):
                    errors.append(f"{prefix}.chronology timestamps must be ISO-8601")
                derived = anchor_strict_ordering_ok(pred_at or "", measured_at or "")
                if case.get("prediction_registered_before_measurement") is not derived:
                    errors.append(f"{prefix}.prediction chronology contradicts preregistration boolean")
                for stem in ("prediction", "measurement", "ordering_attestation"):
                    raw_path = chronology.get(f"{stem}_receipt_path")
                    if stem == "ordering_attestation":
                        raw_path = chronology.get("ordering_attestation_path")
                    if not _valid_relative_path(raw_path):
                        errors.append(f"{prefix}.chronology.{stem}_path must be relative")
                    elif raw_path in chronology_paths:
                        errors.append(f"duplicate chronology receipt path: {raw_path}")
                    else:
                        chronology_paths.add(raw_path)
                    sha_field = (
                        "ordering_attestation_sha256"
                        if stem == "ordering_attestation"
                        else f"{stem}_receipt_sha256"
                    )
                    if not _is_sha256(chronology.get(sha_field)):
                        errors.append(f"{prefix}.chronology.{sha_field} must be sha256")

        pred = case.get("prediction")
        if not isinstance(pred, dict):
            errors.append(f"{prefix}.prediction must be an object")
        else:
            errors.extend(_extra_keys(pred, _PREDICTION_KEYS, f"{prefix}.prediction"))
            if not str(pred.get("metric_name") or "").strip():
                errors.append(f"{prefix}.prediction.metric_name is required")
            if pred.get("direction") not in ("lower", "higher"):
                errors.append(f"{prefix}.prediction.direction must be lower or higher")
            if not _finite_number(pred.get("baseline_value")):
                errors.append(f"{prefix}.prediction.baseline_value must be finite")
            if not _finite_number(pred.get("noise_band")) or pred.get("noise_band", -1) < 0:
                errors.append(f"{prefix}.prediction.noise_band must be finite and nonnegative")
            if pred.get("scale_type", "ratio") not in ("ratio", "interval", "ordinal"):
                errors.append(f"{prefix}.prediction.scale_type is invalid")

        measurement = case.get("measurement")
        if not isinstance(measurement, dict):
            errors.append(f"{prefix}.measurement must be an object")
        else:
            errors.extend(_extra_keys(measurement, _MEASUREMENT_KEYS, f"{prefix}.measurement"))
            if not _finite_number(measurement.get("value")):
                errors.append(f"{prefix}.measurement.value must be finite")
            if not _is_sha256(measurement.get("source_sha256")):
                errors.append(f"{prefix}.measurement.source_sha256 must be sha256")

        novel = case.get("novel_target")
        if novel is not None:
            if not isinstance(novel, dict):
                errors.append(f"{prefix}.novel_target must be an object or null")
            else:
                errors.extend(_extra_keys(novel, _NOVEL_KEYS, f"{prefix}.novel_target"))
                if not str(novel.get("metric_name") or "").strip():
                    errors.append(f"{prefix}.novel_target.metric_name is required")
                if novel.get("direction") not in ("lower", "higher"):
                    errors.append(f"{prefix}.novel_target.direction must be lower or higher")
                if not _finite_number(novel.get("threshold")):
                    errors.append(f"{prefix}.novel_target.threshold must be finite")
                if not _finite_number(novel.get("measured")):
                    errors.append(f"{prefix}.novel_target.measured must be finite")
                if not _is_sha256(novel.get("source_sha256")):
                    errors.append(f"{prefix}.novel_target.source_sha256 must be sha256")
                elif isinstance(measurement, dict) and (
                    novel.get("source_sha256") == measurement.get("source_sha256")
                ):
                    errors.append(f"{prefix}.novel_target must have an independent source sha256")

    if phase == "confirmatory":
        if any(case.get("source_class") == "dogfood" for case in cases if isinstance(case, dict)):
            errors.append("confirmatory manifest forbids dogfood cases")
        if any(
            case.get("source_class") == "synthetic_sabotage"
            and case.get("ground_truth") != "nonprogressive"
            for case in cases if isinstance(case, dict)
        ):
            errors.append("synthetic_sabotage cases must be ground-truth nonprogressive")
        external = [
            case for case in cases
            if isinstance(case, dict) and case.get("source_class") == "external"
        ]
        positives = sum(case.get("ground_truth") == "progressive" for case in external)
        negatives = sum(case.get("ground_truth") == "nonprogressive" for case in external)
        synthetic = sum(
            case.get("source_class") == "synthetic_sabotage" for case in cases if isinstance(case, dict)
        )
        if positives != negatives:
            errors.append(
                "confirmatory external holdout must be class-balanced for the paired accuracy estimand"
            )
        if positives < 9:
            errors.append(
                "confirmatory external holdout requires at least 9 true-progressive cases"
            )
        if synthetic / len(cases) < 0.25:
            errors.append("confirmatory synthetic_sabotage share must be at least 25%")
        for field in ("sampling_unit_id", "component_id", "case_package_sha256"):
            values = [case.get(field) for case in external]
            if len(values) != len(set(values)):
                errors.append(f"confirmatory external {field} values must be pairwise unique")
        source_entities = [
            entity for case in external for entity in (case.get("source_entity_ids") or [])
        ]
        if len(source_entities) != len(set(source_entities)):
            errors.append("confirmatory external source_entity_ids must be pairwise nonoverlapping")
        measurement_sources = [
            (case.get("measurement") or {}).get("source_sha256") for case in external
        ]
        if len(measurement_sources) != len(set(measurement_sources)):
            errors.append("confirmatory external measurement source sha256 values must be unique")
        novel_sources = [
            case["novel_target"].get("source_sha256")
            for case in external
            if isinstance(case.get("novel_target"), dict)
        ]
        if len(novel_sources) != len(set(novel_sources)):
            errors.append("confirmatory external novel source sha256 values must be unique")
        all_observation_sources = measurement_sources + novel_sources
        if len(all_observation_sources) != len(set(all_observation_sources)):
            errors.append(
                "confirmatory external measurement and novel source sha256 values "
                "must be jointly nonoverlapping"
            )
        if (
            _finite_number(advantage)
            and _finite_number(pairwise)
            and _finite_number(min_power)
            and _finite_number(discordance_rate)
            and 0.5 < advantage < 1
            and 0 < pairwise < 1
            and 0 < min_power < 1
            and 0 < discordance_rate <= 1
            and _finite_number(sensitivity_alternative)
            and 0 < sensitivity_alternative <= 1
            and _finite_number(sensitivity_floor)
        ):
            plan = joint_confirmatory_power_plan(
                external_cases=len(external),
                discordance_rate_floor=float(discordance_rate),
                conditional_advantage=float(advantage),
                pairwise_alpha=float(pairwise),
                sensitivity_alternative=float(sensitivity_alternative),
                sensitivity_wilson_floor=float(sensitivity_floor),
                joint_target_power=float(min_power),
            ) if len(external) >= 2 and len(external) % 2 == 0 else {"passed": False}
            if not plan["passed"]:
                errors.append(
                    "confirmatory external cases fail the exact three-gate joint power plan"
                )
    return errors


def _prediction(case: dict) -> Prediction:
    raw = case["prediction"]
    return Prediction(
        metric_name=raw["metric_name"],
        direction=raw["direction"],
        baseline_value=float(raw["baseline_value"]),
        noise_band=float(raw.get("noise_band", 0.0)),
        scale_type=raw.get("scale_type", "ratio"),
    )


def evaluate_case(case: dict) -> dict[str, dict[str, Any]]:
    """Run the three locked adapters over one common case package.

    The primary improvement calculation and the LakatoTree verdict both use
    the production ``judge`` kernel.  ``popper_like`` is intentionally named as
    an internal single-layer baseline; it is not a claim about the external
    POPPER system.
    """

    device_input = project_device_input(case)
    pred = _prediction(device_input)
    measured = float(device_input["measurement"]["value"])
    primary = judge(pred, measured)
    preregistered = bool(device_input.get("prediction_registered_before_measurement"))
    out: dict[str, dict[str, Any]] = {
        "naive": {
            "progressive": primary.improved,
            "verdict": "progressive" if primary.improved else "nonprogressive",
            "reason": "primary improvement only",
        },
        "popper_like": {
            "progressive": bool(preregistered and primary.improved),
            "verdict": (
                "progressive" if preregistered and primary.improved
                else "invalid_posthoc" if not preregistered
                else "nonprogressive"
            ),
            "reason": "prospective primary prediction only; novelty not scored",
        },
    }

    if not preregistered:
        out["lakatotree"] = {
            "progressive": False,
            "verdict": "invalid_posthoc",
            "reason": "prediction was not registered before measurement",
        }
        return out

    raw_novel = device_input.get("novel_target")
    novel_target = None
    novel_measured = None
    novel_sha = ""
    if raw_novel is not None:
        novel_target = NovelTarget(
            metric_name=raw_novel["metric_name"],
            direction=raw_novel["direction"],
            threshold=float(raw_novel["threshold"]),
            novelty_sense=raw_novel.get("novelty_sense", "zahar_use_novelty"),
        )
        novel_measured = float(raw_novel["measured"])
        novel_sha = raw_novel["source_sha256"]
    verdict = judge(
        pred,
        measured,
        novel_target=novel_target,
        novel_measured=novel_measured,
        measured_sha=device_input["measurement"]["source_sha256"],
        novel_sha=novel_sha,
        require_independent_source=True,
    )
    out["lakatotree"] = {
        "progressive": verdict.verdict == "progressive",
        "verdict": verdict.verdict,
        "reason": verdict.reason,
    }
    return out


def mcnemar_exact_two_sided(favorable: int, reverse: int) -> float:
    """Two-sided exact McNemar p-value from discordant paired outcomes."""

    if favorable < 0 or reverse < 0:
        raise ValueError("discordant counts must be nonnegative")
    n = favorable + reverse
    if n == 0:
        return 1.0
    tail = min(favorable, reverse)
    if n < 1_000:
        return min(
            1.0,
            2.0 * sum(math.comb(n, i) for i in range(tail + 1)) / (1 << n),
        )
    log_terms = [
        math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1)
        - n * math.log(2.0)
        for i in range(tail + 1)
    ]
    largest = max(log_terms)
    probability = 2.0 * math.exp(largest) * sum(
        math.exp(value - largest) for value in log_terms
    )
    return min(1.0, probability)


def _binomial_probability(n: int, k: int, p: float) -> float:
    if k < 0 or k > n or not 0 <= p <= 1:
        return 0.0
    if p == 0:
        return 1.0 if k == 0 else 0.0
    if p == 1:
        return 1.0 if k == n else 0.0
    log_probability = (
        math.lgamma(n + 1)
        - math.lgamma(k + 1)
        - math.lgamma(n - k + 1)
        + k * math.log(p)
        + (n - k) * math.log1p(-p)
    )
    return math.exp(log_probability)


def _directional_exact_power(n: int, p: float, alpha: float) -> float:
    return sum(
        _binomial_probability(n, k, p)
        for k in range(n + 1)
        if k > n / 2 and mcnemar_exact_two_sided(k, n - k) <= alpha
    )


def required_discordant_pairs(
    *, conditional_advantage: float, alpha: float, target_power: float, max_pairs: int = 10_000
) -> dict[str, Any]:
    """Exact power plan for the directional half of a two-sided McNemar test."""

    if not 0.5 < conditional_advantage < 1:
        raise ValueError("conditional_advantage must be in (0.5, 1)")
    if not 0 < alpha < 1 or not 0 < target_power < 1:
        raise ValueError("alpha and target_power must be in (0, 1)")
    previous = 0.0
    for n in range(1, max_pairs + 1):
        power = _directional_exact_power(n, conditional_advantage, alpha)
        if power >= target_power:
            return {
                "required_discordant_pairs": n,
                "achieved_power": power,
                "previous_power": previous,
                "conditional_advantage": conditional_advantage,
                "alpha": alpha,
                "target_power": target_power,
            }
        previous = power
    raise ValueError(f"target power not reached within {max_pairs} discordant pairs")


def unconditional_mcnemar_power(
    *,
    total_pairs: int,
    discordance_rate_floor: float,
    conditional_advantage: float,
    alpha: float,
) -> float:
    """Exact power after mixing over D~Binomial(total_pairs, discordance_rate)."""

    if not isinstance(total_pairs, int) or total_pairs < 1:
        raise ValueError("total_pairs must be a positive integer")
    if not 0 < discordance_rate_floor <= 1:
        raise ValueError("discordance_rate_floor must be in (0, 1]")
    return sum(
        _binomial_probability(total_pairs, discordant, discordance_rate_floor)
        * _directional_exact_power(discordant, conditional_advantage, alpha)
        for discordant in range(total_pairs + 1)
    )


def sensitivity_gate_power(
    *, total_positive: int, true_sensitivity: float, wilson_lower_threshold: float
) -> float:
    """Exact probability that the preregistered Wilson sensitivity gate passes."""

    if not isinstance(total_positive, int) or total_positive < 1:
        raise ValueError("total_positive must be a positive integer")
    if not 0 < true_sensitivity <= 1 or not 0 <= wilson_lower_threshold < 1:
        raise ValueError("invalid sensitivity power parameters")
    return sum(
        _binomial_probability(total_positive, correct, true_sensitivity)
        for correct in range(total_positive + 1)
        if wilson_lower_bound(correct, total_positive) >= wilson_lower_threshold
    )


def joint_confirmatory_power_plan(
    *,
    external_cases: int,
    discordance_rate_floor: float,
    conditional_advantage: float,
    pairwise_alpha: float,
    sensitivity_alternative: float,
    sensitivity_wilson_floor: float,
    joint_target_power: float,
) -> dict[str, Any]:
    """Three-gate union-bound plan with no independence assumption between gates."""

    if external_cases < 2 or external_cases % 2:
        raise ValueError("external_cases must be an even class-balanced count")
    component_target = 1.0 - (1.0 - joint_target_power) / 3.0
    comparison_power = unconditional_mcnemar_power(
        total_pairs=external_cases,
        discordance_rate_floor=discordance_rate_floor,
        conditional_advantage=conditional_advantage,
        alpha=pairwise_alpha,
    )
    sensitivity_power = sensitivity_gate_power(
        total_positive=external_cases // 2,
        true_sensitivity=sensitivity_alternative,
        wilson_lower_threshold=sensitivity_wilson_floor,
    )
    joint_lower = max(0.0, 2.0 * comparison_power + sensitivity_power - 2.0)
    return {
        "external_cases": external_cases,
        "component_power_target": component_target,
        "comparison_component_power": comparison_power,
        "sensitivity_component_power": sensitivity_power,
        "joint_power_lower_bound": joint_lower,
        "joint_target_power": joint_target_power,
        "passed": bool(
            comparison_power >= component_target
            and sensitivity_power >= component_target
            and joint_lower >= joint_target_power
        ),
    }


def _wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    phat = k / n
    denom = 1.0 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    half = z * math.sqrt((phat * (1 - phat) + z * z / (4 * n)) / n) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def newcombe_paired_difference_ci(
    *,
    both_event: int,
    first_only: int,
    second_only: int,
    neither: int,
    alpha: float = 0.05,
) -> dict[str, float]:
    """Newcombe (1998) method-10 CI for paired proportions.

    The effect is ``P(first event) - P(second event)``.  In the primary
    backtest, ``event`` means a classification error, so a negative interval
    for LakatoTree-minus-control favors LakatoTree.
    """

    counts = (both_event, first_only, second_only, neither)
    if any(not isinstance(value, int) or value < 0 for value in counts):
        raise ValueError("paired table counts must be nonnegative integers")
    if not 0 < alpha < 1:
        raise ValueError("alpha must be in (0, 1)")
    n = sum(counts)
    if n == 0:
        raise ValueError("paired table must contain at least one pair")
    p_first = (both_event + first_only) / n
    p_second = (both_event + second_only) / n
    difference = p_first - p_second
    # Newcombe's published table uses the conventional z=1.96 at 95%; retain
    # that exact reproducibility fixture while supporting other alpha levels.
    z = 1.96 if math.isclose(alpha, 0.05) else NormalDist().inv_cdf(1.0 - alpha / 2.0)
    first_l, first_u = _wilson_interval(both_event + first_only, n, z=z)
    second_l, second_u = _wilson_interval(both_event + second_only, n, z=z)

    numerator = both_event * neither - first_only * second_only
    if numerator > 0:
        numerator = max(numerator - n / 2.0, 0.0)
    denominator = math.sqrt(
        (both_event + first_only)
        * (second_only + neither)
        * (both_event + second_only)
        * (first_only + neither)
    )
    rho = numerator / denominator if denominator else 0.0
    dl_first, du_first = p_first - first_l, first_u - p_first
    dl_second, du_second = p_second - second_l, second_u - p_second
    lower_width = math.sqrt(max(
        0.0,
        dl_first * dl_first - 2.0 * rho * dl_first * du_second + du_second * du_second,
    ))
    upper_width = math.sqrt(max(
        0.0,
        du_first * du_first - 2.0 * rho * du_first * dl_second + dl_second * dl_second,
    ))
    return {
        "difference": difference,
        "lower": max(-1.0, difference - lower_width),
        "upper": min(1.0, difference + upper_width),
        "alpha": alpha,
    }


def _binomial_cdf(k: int, n: int, p: float) -> float:
    return sum(_binomial_probability(n, i, p) for i in range(k + 1))


def _binomial_survival(k: int, n: int, p: float) -> float:
    return sum(_binomial_probability(n, i, p) for i in range(k, n + 1))


def _clopper_pearson(k: int, n: int, alpha: float) -> tuple[float, float]:
    if n <= 0:
        return 0.0, 1.0
    tail = alpha / 2.0
    if k == 0:
        lower = 0.0
    else:
        lo, hi = 0.0, 1.0
        for _ in range(80):
            mid = (lo + hi) / 2.0
            if _binomial_survival(k, n, mid) < tail:
                lo = mid
            else:
                hi = mid
        lower = (lo + hi) / 2.0
    if k == n:
        upper = 1.0
    else:
        lo, hi = 0.0, 1.0
        for _ in range(80):
            mid = (lo + hi) / 2.0
            if _binomial_cdf(k, n, mid) > tail:
                lo = mid
            else:
                hi = mid
        upper = (lo + hi) / 2.0
    return lower, upper


def _odds(value: float) -> float | str:
    if value >= 1.0:
        return "infinity"
    if value <= 0.0:
        return 0.0
    return value / (1.0 - value)


def _arm_summary(cases: list[dict], decisions: dict, arm: str) -> dict[str, Any]:
    tp = fn = fp = tn = 0
    for case in cases:
        positive = case["ground_truth"] == "progressive"
        predicted = bool(decisions[case["case_id"]][arm]["progressive"])
        if positive and predicted:
            tp += 1
        elif positive:
            fn += 1
        elif predicted:
            fp += 1
        else:
            tn += 1
    positive_n, negative_n = tp + fn, fp + tn
    fpr_ci = _wilson_interval(fp, negative_n)
    sensitivity_ci = _wilson_interval(tp, positive_n)
    return {
        "true_positive": tp,
        "false_negative": fn,
        "false_positive": fp,
        "true_negative": tn,
        "positive_n": positive_n,
        "negative_n": negative_n,
        "false_progressive_rate": fp / negative_n if negative_n else None,
        "false_progressive_rate_wilson95": list(fpr_ci),
        "sensitivity": tp / positive_n if positive_n else None,
        "sensitivity_wilson95": list(sensitivity_ci),
        "accuracy": (tp + tn) / len(cases) if cases else None,
    }


def analyze_decisions(manifest: dict, decisions: dict[str, dict]) -> dict[str, Any]:
    """Analyze a sealed paired run without upgrading an underpowered result."""

    errors = validate_manifest(manifest)
    cases = manifest.get("cases") or []
    for case in cases:
        case_id = case.get("case_id")
        row = decisions.get(case_id)
        if not isinstance(row, dict):
            errors.append(f"missing decisions for case {case_id}")
            continue
        for arm in ARMS:
            if not isinstance(row.get(arm), dict) or not isinstance(row[arm].get("progressive"), bool):
                errors.append(f"case {case_id} missing boolean decision for arm {arm}")
    if errors:
        return {"schema_version": SCHEMA_VERSION, "status": "INVALID", "errors": errors}

    protocol = manifest["protocol"]
    component_power_target = 1.0 - (1.0 - float(protocol["min_power"])) / 3.0
    plan = required_discordant_pairs(
        conditional_advantage=float(protocol["conditional_accuracy_advantage"]),
        alpha=float(protocol["pairwise_alpha"]),
        target_power=component_power_target,
    )
    external = [case for case in cases if case["source_class"] == "external"]
    primary_cases = external or cases
    sabotage = [case for case in cases if case["source_class"] == "synthetic_sabotage"]
    arms = {arm: _arm_summary(primary_cases, decisions, arm) for arm in ARMS}
    lkt = arms["lakatotree"]
    sensitivity_lb = wilson_lower_bound(lkt["true_positive"], lkt["positive_n"])
    sensitivity_gate = {
        "wilson95_lower": sensitivity_lb,
        "threshold": float(protocol["min_sensitivity_wilson_lb"]),
        "passed": sensitivity_lb >= float(protocol["min_sensitivity_wilson_lb"]),
        "correct_name": "true_progressive_sensitivity",
    }

    comparisons: dict[str, dict[str, Any]] = {}
    for baseline in ("naive", "popper_like"):
        favorable = reverse = both_error = both_correct = 0
        for case in primary_cases:
            row = decisions[case["case_id"]]
            truth = case["ground_truth"] == "progressive"
            base_correct = bool(row[baseline]["progressive"]) == truth
            lkt_correct = bool(row["lakatotree"]["progressive"]) == truth
            favorable += int(lkt_correct and not base_correct)
            reverse += int(base_correct and not lkt_correct)
            both_error += int(not base_correct and not lkt_correct)
            both_correct += int(base_correct and lkt_correct)
        discordant = favorable + reverse
        p_value = mcnemar_exact_two_sided(favorable, reverse)
        conditional_ci = _clopper_pearson(
            favorable, discordant, float(protocol["pairwise_alpha"])
        ) if discordant else (0.0, 1.0)
        power_adequate = discordant >= plan["required_discordant_pairs"]
        direction_ok = favorable > reverse
        significant = p_value <= float(protocol["pairwise_alpha"])
        paired_rd = newcombe_paired_difference_ci(
            both_event=both_error,
            first_only=reverse,
            second_only=favorable,
            neither=both_correct,
            alpha=float(protocol["pairwise_alpha"]),
        ) if primary_cases else None
        comparisons[f"lakatotree_vs_{baseline}"] = {
            "favorable_discordance": favorable,
            "reverse_discordance": reverse,
            "discordant_pairs": discordant,
            "required_discordant_pairs": plan["required_discordant_pairs"],
            "power_adequate": power_adequate,
            "p_value": p_value,
            "alpha": float(protocol["pairwise_alpha"]),
            "paired_error_risk_difference_lakatotree_minus_control": paired_rd,
            "matched_odds_ratio_lakatotree_only_correct_over_control_only_correct": (
                "infinity" if reverse == 0 and favorable > 0 else
                favorable / reverse if reverse else None
            ),
            "matched_odds_ratio_lakatotree_only_correct_over_control_only_correct_exact_ci": [
                _odds(conditional_ci[0]), _odds(conditional_ci[1])
            ],
            "direction_ok": direction_ok,
            "significant": significant,
            "passed": bool(direction_ok and significant and power_adequate),
        }

    if not sensitivity_gate["passed"] or any(
        not comparison["direction_ok"] for comparison in comparisons.values()
    ):
        status = "NOT_SUPPORTED"
    elif any(
        comparison["power_adequate"] and not comparison["significant"]
        for comparison in comparisons.values()
    ):
        status = "NOT_SUPPORTED"
    elif any(not comparison["power_adequate"] for comparison in comparisons.values()):
        status = "INCONCLUSIVE_UNDERPOWERED"
    elif all(comparison["passed"] for comparison in comparisons.values()):
        status = "SUPPORTED"
    else:
        status = "NOT_SUPPORTED"
    return {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": manifest["experiment_id"],
        "status": status,
        "arms": arms,
        "sensitivity_gate": sensitivity_gate,
        "power_plan": plan,
        "design_power_plan": joint_confirmatory_power_plan(
            external_cases=len(external),
            discordance_rate_floor=float(protocol["accuracy_discordance_rate_floor"]),
            conditional_advantage=float(protocol["conditional_accuracy_advantage"]),
            pairwise_alpha=float(protocol["pairwise_alpha"]),
            sensitivity_alternative=float(protocol["sensitivity_alternative"]),
            sensitivity_wilson_floor=float(protocol["min_sensitivity_wilson_lb"]),
            joint_target_power=float(protocol["min_power"]),
        ) if external and len(external) % 2 == 0 else None,
        "comparisons": comparisons,
        "primary_population": "external_class_balanced_holdout" if external else "development_cases",
        "synthetic_sabotage_stress": {
            arm: _arm_summary(sabotage, decisions, arm) for arm in ARMS
        } if sabotage else None,
        "claim_boundary": (
            "retrospective paired classification accuracy only; no prospective productivity claim"
        ),
    }


def run_manifest(manifest: dict) -> dict[str, Any]:
    """Run development data only; confirmatory execution must use the locked gate."""

    errors = validate_manifest(manifest)
    if errors:
        return {"schema_version": SCHEMA_VERSION, "status": "INVALID", "errors": errors}
    if manifest.get("phase") == "confirmatory":
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "INVALID_CONFIRMATORY_GATE",
            "errors": ["confirmatory manifests require MeasurementLock and external witness quorum"],
        }
    return _execute_manifest(manifest)


def _execute_manifest(manifest: dict) -> dict[str, Any]:
    decisions = {case["case_id"]: evaluate_case(case) for case in manifest["cases"]}
    result = analyze_decisions(manifest, decisions)
    result["decisions"] = decisions
    result["phase"] = manifest["phase"]
    result["claim_eligible"] = False
    result["claim_grade"] = (
        "producer_generated/pending"
        if manifest["phase"] == "confirmatory"
        else "development_only/not_eligible"
    )
    if manifest["phase"] != "confirmatory" and result.get("status") != "INVALID":
        result["development_analysis_status"] = result["status"]
        result["status"] = "DEVELOPMENT_ONLY"
    return result


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_package(manifest_path: Path, raw_path: str, *, confirmatory: bool) -> Path:
    candidate = Path(raw_path).expanduser()
    if confirmatory and candidate.is_absolute():
        raise ValueError("confirmatory case_package_path must be relative to the manifest")
    resolved = (manifest_path.parent / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    if confirmatory and manifest_path.parent not in (resolved, *resolved.parents):
        raise ValueError("confirmatory case_package_path escapes the manifest directory")
    return resolved


def _resolve_manifest_relative(manifest_path: Path, raw_path: str) -> Path:
    if not _valid_relative_path(raw_path):
        raise ValueError(f"artifact path must be a non-escaping relative path: {raw_path!r}")
    resolved = (manifest_path.parent / raw_path).resolve()
    if manifest_path.parent not in (resolved, *resolved.parents):
        raise ValueError(f"artifact path escapes manifest directory: {raw_path}")
    return resolved


def _dependency_map(manifest_path: Path, manifest: dict) -> dict[str, Path]:
    deps = {f"repo:{relative}": _REPO_ROOT / relative for relative in _REQUIRED_REPO_DEPS}
    deps["manifest"] = manifest_path
    for case in manifest.get("cases") or []:
        raw = case.get("case_package_path")
        if raw:
            deps[f"case:{case.get('case_id')}"] = _resolve_package(
                manifest_path, raw, confirmatory=manifest.get("phase") == "confirmatory"
            )
        chronology = case.get("chronology")
        if manifest.get("phase") == "confirmatory" and isinstance(chronology, dict):
            for stem in ("prediction", "measurement"):
                deps[f"chronology:{case.get('case_id')}:{stem}"] = _resolve_manifest_relative(
                    manifest_path, chronology[f"{stem}_receipt_path"]
                )
            deps[f"chronology:{case.get('case_id')}:ordering"] = _resolve_manifest_relative(
                manifest_path, chronology["ordering_attestation_path"]
            )
    if manifest.get("phase") == "confirmatory":
        prereg = manifest["preregistration"]
        refs = {
            "provenance:pilot_receipt": prereg["pilot_receipt"],
            "provenance:blind_adjudication": {
                "path": prereg["blind_adjudication"]["attestation_path"],
                "sha256": prereg["blind_adjudication"]["attestation_sha256"],
            },
            "provenance:prior_exposure": {
                "path": prereg["prior_exposure"]["attestation_path"],
                "sha256": prereg["prior_exposure"]["attestation_sha256"],
            },
            "provenance:witness_allowlist": {
                "path": prereg["temporal_anchor"]["witness_allowlist_path"],
                "sha256": prereg["temporal_anchor"]["witness_allowlist_sha256"],
            },
            "provenance:replayer_allowlist": prereg["replayer_allowlist"],
        }
        for label, ref in refs.items():
            deps[label] = _resolve_manifest_relative(manifest_path, ref["path"])
    return deps


def _current_dependencies(manifest_path: Path, manifest: dict) -> list[dict]:
    mapping = _dependency_map(manifest_path, manifest)
    out = []
    for label, path in sorted(mapping.items()):
        out.append({"path": label, "sha256": _sha256_file(path) if path.is_file() else None})
    return out


def _expected_artifact_hashes(manifest: dict) -> dict[str, str]:
    expected = {}
    for case in manifest.get("cases") or []:
        if case.get("case_package_path"):
            expected[f"case:{case.get('case_id')}"] = case.get("case_package_sha256")
        chronology = case.get("chronology")
        if manifest.get("phase") == "confirmatory" and isinstance(chronology, dict):
            for stem in ("prediction", "measurement"):
                expected[f"chronology:{case.get('case_id')}:{stem}"] = chronology[
                    f"{stem}_receipt_sha256"
                ]
            expected[f"chronology:{case.get('case_id')}:ordering"] = chronology[
                "ordering_attestation_sha256"
            ]
    if manifest.get("phase") == "confirmatory":
        prereg = manifest["preregistration"]
        expected.update({
            "provenance:pilot_receipt": prereg["pilot_receipt"]["sha256"],
            "provenance:blind_adjudication": prereg["blind_adjudication"]["attestation_sha256"],
            "provenance:prior_exposure": prereg["prior_exposure"]["attestation_sha256"],
            "provenance:witness_allowlist": prereg["temporal_anchor"]["witness_allowlist_sha256"],
            "provenance:replayer_allowlist": prereg["replayer_allowlist"]["sha256"],
        })
    return expected


def _validate_confirmatory_artifacts(manifest_path: Path, manifest: dict) -> list[str]:
    """Parse and cross-bind every external confirmatory provenance artifact."""

    if manifest.get("phase") != "confirmatory":
        return []
    errors: list[str] = []
    prereg = manifest["preregistration"]
    cases = manifest["cases"]

    try:
        pilot = _load_json_object(
            _resolve_manifest_relative(manifest_path, prereg["pilot_receipt"]["path"])
        )
        expected_pilot_keys = {
            "schema_version", "source_phase", "total_pilot_cases", "contrasts",
            "accuracy_discordance_rate_floor", "pilot_cases", "source_entity_ids",
            "component_ids",
        }
        if set(pilot) != expected_pilot_keys:
            errors.append("pilot receipt schema fields mismatch")
        elif pilot.get("schema_version") != PILOT_SCHEMA_VERSION or pilot.get("source_phase") != "development":
            errors.append("pilot receipt must be a development-only v1 receipt")
        else:
            total = pilot.get("total_pilot_cases")
            contrasts = pilot.get("contrasts")
            expected_contrasts = {"lakatotree_vs_naive", "lakatotree_vs_popper_like"}
            if not isinstance(total, int) or isinstance(total, bool) or total < 1:
                errors.append("pilot total_pilot_cases must be a positive integer")
            if not isinstance(contrasts, dict) or set(contrasts) != expected_contrasts:
                errors.append("pilot contrasts must contain both preregistered comparisons")
            else:
                lower_bounds: list[float] = []
                for name in sorted(expected_contrasts):
                    row = contrasts[name]
                    if not isinstance(row, dict) or set(row) != {
                        "total_pairs", "discordant_pairs", "observed_discordance_rate",
                        "wilson95_lower",
                    }:
                        errors.append(f"pilot contrast {name} fields mismatch")
                        continue
                    n = row.get("total_pairs")
                    d = row.get("discordant_pairs")
                    if (
                        not isinstance(n, int) or isinstance(n, bool) or n < 1
                        or not isinstance(d, int) or isinstance(d, bool) or not 0 <= d <= n
                    ):
                        errors.append(f"pilot contrast {name} counts are invalid")
                        continue
                    if n != total:
                        errors.append(
                            f"pilot contrast {name} total_pairs must equal total_pilot_cases"
                        )
                    observed = d / n
                    lower = wilson_lower_bound(d, n)
                    if not _finite_number(row.get("observed_discordance_rate")) or not math.isclose(
                        float(row["observed_discordance_rate"]), observed, abs_tol=1e-12
                    ):
                        errors.append(f"pilot contrast {name} observed rate mismatch")
                    if not _finite_number(row.get("wilson95_lower")) or not math.isclose(
                        float(row["wilson95_lower"]), lower, abs_tol=1e-12
                    ):
                        errors.append(f"pilot contrast {name} Wilson lower mismatch")
                    lower_bounds.append(lower)
                if len(lower_bounds) == 2:
                    floor = min(lower_bounds)
                    if not _finite_number(pilot.get("accuracy_discordance_rate_floor")) or not math.isclose(
                        float(pilot["accuracy_discordance_rate_floor"]), floor, abs_tol=1e-12
                    ):
                        errors.append("pilot conservative discordance floor mismatch")
                    if not math.isclose(
                        float(manifest["protocol"]["accuracy_discordance_rate_floor"]),
                        floor,
                        abs_tol=1e-12,
                    ):
                        errors.append("manifest discordance floor does not match pilot receipt")
            pilot_cases = pilot.get("pilot_cases")
            pilot_sources = pilot.get("source_entity_ids")
            pilot_components = pilot.get("component_ids")
            derived_sources: list[str] = []
            derived_components: list[str] = []
            derived_sampling_units: list[str] = []
            valid_pilot_cases = (
                isinstance(pilot_cases, list)
                and isinstance(total, int)
                and len(pilot_cases) == total
            )
            if valid_pilot_cases:
                for row in pilot_cases:
                    if not isinstance(row, dict) or set(row) != {
                        "sampling_unit_id", "component_id", "source_entity_ids"
                    }:
                        valid_pilot_cases = False
                        break
                    sampling_unit = row.get("sampling_unit_id")
                    component = row.get("component_id")
                    sources = row.get("source_entity_ids")
                    if (
                        not isinstance(sampling_unit, str) or not sampling_unit.strip()
                        or not isinstance(component, str) or not component.strip()
                        or not isinstance(sources, list) or not sources
                        or len(sources) != len(set(sources))
                        or any(not isinstance(value, str) or not value.strip() for value in sources)
                    ):
                        valid_pilot_cases = False
                        break
                    derived_sampling_units.append(sampling_unit)
                    derived_components.append(component)
                    derived_sources.extend(sources)
            if (
                not valid_pilot_cases
                or len(derived_sampling_units) != len(set(derived_sampling_units))
                or len(derived_components) != len(set(derived_components))
                or len(derived_sources) != len(set(derived_sources))
                or pilot_components != derived_components
                or pilot_sources != derived_sources
            ):
                errors.append(
                    "pilot cases must provide total-matched, pairwise independent "
                    "sampling/source/component provenance"
                )
            else:
                holdout_sampling_units = {
                    case.get("sampling_unit_id") for case in cases
                }
                holdout_sources = {
                    value for case in cases for value in (case.get("source_entity_ids") or [])
                }
                holdout_components = {case.get("component_id") for case in cases}
                if holdout_sampling_units.intersection(derived_sampling_units):
                    errors.append("pilot and confirmatory sampling_unit_ids overlap")
                if holdout_sources.intersection(pilot_sources):
                    errors.append("pilot and confirmatory source_entity_ids overlap")
                if holdout_components.intersection(pilot_components):
                    errors.append("pilot and confirmatory component_ids overlap")
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        errors.append(f"pilot receipt invalid: {exc}")

    try:
        replay_allowlist = _load_json_object(
            _resolve_manifest_relative(manifest_path, prereg["replayer_allowlist"]["path"])
        )
        if set(replay_allowlist) != {
            "schema_version", "replayer_dids", "owner", "separation_attestation_sha256"
        }:
            errors.append("replayer allow-list schema fields mismatch")
        replayers = replay_allowlist.get("replayer_dids")
        if (
            replay_allowlist.get("schema_version") != REPLAYER_ALLOWLIST_SCHEMA_VERSION
            or not isinstance(replayers, list) or not replayers
            or len(replayers) != len(set(replayers))
            or any(not _valid_did(value) for value in replayers)
            or not str(replay_allowlist.get("owner") or "").strip()
            or not _is_sha256(replay_allowlist.get("separation_attestation_sha256"))
        ):
            errors.append("invalid replayer allow-list")
        witness_document = _load_json_object(
            _resolve_manifest_relative(
                manifest_path, prereg["temporal_anchor"]["witness_allowlist_path"]
            )
        )
        witness_allowlist = witness_document.get("witness_dids") or []
        if set(witness_document) != {
            "schema_version", "witness_dids", "owner", "separation_attestation_sha256"
        } or (
            witness_document.get("schema_version") != ALLOWLIST_SCHEMA_VERSION
            or not isinstance(witness_allowlist, list)
            or len(witness_allowlist) < prereg["temporal_anchor"]["threshold"]
            or len(witness_allowlist) != len(set(witness_allowlist))
            or any(not _valid_did(value) for value in witness_allowlist)
            or not str(witness_document.get("owner") or "").strip()
            or not _is_sha256(witness_document.get("separation_attestation_sha256"))
        ):
            errors.append("invalid witness allow-list")
        protected_roles = {prereg["producer_did"], *prereg["curator_dids"]}
        if protected_roles.intersection(witness_allowlist):
            errors.append("witness DIDs must be distinct from producer and curator DIDs")
        forbidden = {
            prereg["producer_did"], *prereg["curator_dids"], *witness_allowlist
        }
        if isinstance(replayers, list) and forbidden.intersection(replayers):
            errors.append("replayer DIDs must be distinct from producer, curators, and witnesses")
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        errors.append(f"replayer role provenance invalid: {exc}")

    try:
        blind = _load_json_object(
            _resolve_manifest_relative(
                manifest_path, prereg["blind_adjudication"]["attestation_path"]
            )
        )
        if set(blind) != {
            "schema_version", "completed_at", "curator_dids", "device_outputs_seen",
            "rubric_sha256", "raw_labels_sha256", "consensus_rule",
            "ground_truth_assignment_sha256", "curator_signatures",
        }:
            errors.append("blind adjudication attestation fields mismatch")
        elif (
            blind.get("schema_version") != BLIND_ATTESTATION_SCHEMA_VERSION
            or blind.get("completed_at") != prereg["blind_adjudication"]["completed_at"]
            or blind.get("curator_dids") != prereg["curator_dids"]
            or blind.get("device_outputs_seen") is not False
            or not _is_sha256(blind.get("rubric_sha256"))
            or not _is_sha256(blind.get("raw_labels_sha256"))
            or not str(blind.get("consensus_rule") or "").strip()
            or blind.get("ground_truth_assignment_sha256")
            != _sha_json(_ground_truth_assignment(cases))
        ):
            errors.append("blind adjudication attestation does not bind ground truth")
        else:
            errors.extend(_signature_errors(
                dids=blind["curator_dids"],
                signatures=blind["curator_signatures"],
                message=blind_attestation_bytes(blind),
                label="blind adjudication curator",
            ))
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        errors.append(f"blind adjudication attestation invalid: {exc}")

    try:
        exposure = _load_json_object(
            _resolve_manifest_relative(
                manifest_path, prereg["prior_exposure"]["attestation_path"]
            )
        )
        if set(exposure) != {
            "schema_version", "holdout_exposed_to_developers", "holdout_identity_sha256",
            "curator_dids", "curator_signatures",
        } or (
            exposure.get("schema_version") != EXPOSURE_ATTESTATION_SCHEMA_VERSION
            or exposure.get("holdout_exposed_to_developers") is not False
            or exposure.get("curator_dids") != prereg["curator_dids"]
            or exposure.get("holdout_identity_sha256")
            != _sha_json(_holdout_identity_payload(cases))
        ):
            errors.append("prior-exposure attestation does not bind holdout identities")
        else:
            errors.extend(_signature_errors(
                dids=exposure["curator_dids"],
                signatures=exposure["curator_signatures"],
                message=exposure_attestation_bytes(exposure),
                label="prior-exposure curator",
            ))
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        errors.append(f"prior-exposure attestation invalid: {exc}")

    for case in cases:
        case_id = case["case_id"]
        chronology = case["chronology"]
        try:
            package = _load_json_object(
                _resolve_package(manifest_path, case["case_package_path"], confirmatory=True)
            )
            if package != project_device_input(case):
                errors.append(f"case {case_id} package does not equal evaluated device_input")
            pred_receipt = _load_json_object(_resolve_manifest_relative(
                manifest_path, chronology["prediction_receipt_path"]
            ))
            measure_receipt = _load_json_object(_resolve_manifest_relative(
                manifest_path, chronology["measurement_receipt_path"]
            ))
            ordering = _load_json_object(_resolve_manifest_relative(
                manifest_path, chronology["ordering_attestation_path"]
            ))
            expected_receipt_keys = {
                "schema_version", "receipt_kind", "case_id", "recorded_at", "payload_sha256"
            }
            if set(pred_receipt) != expected_receipt_keys or (
                pred_receipt.get("schema_version") != CHRONOLOGY_RECEIPT_SCHEMA_VERSION
                or pred_receipt.get("receipt_kind") != "prediction_registration"
                or pred_receipt.get("case_id") != case_id
                or pred_receipt.get("recorded_at") != chronology["prediction_registered_at"]
                or pred_receipt.get("payload_sha256") != _sha_json(_prediction_receipt_payload(case))
            ):
                errors.append(f"case {case_id} prediction receipt semantic mismatch")
            if set(measure_receipt) != expected_receipt_keys or (
                measure_receipt.get("schema_version") != CHRONOLOGY_RECEIPT_SCHEMA_VERSION
                or measure_receipt.get("receipt_kind") != "measurement_observation"
                or measure_receipt.get("case_id") != case_id
                or measure_receipt.get("recorded_at") != chronology["measurement_observed_at"]
                or measure_receipt.get("payload_sha256") != _sha_json(_measurement_receipt_payload(case))
            ):
                errors.append(f"case {case_id} measurement receipt semantic mismatch")
            expected_ordering_keys = {
                "schema_version", "case_id", "prediction_receipt_sha256",
                "measurement_receipt_sha256", "prediction_registered_at",
                "measurement_observed_at", "strictly_before", "attestor_dids",
                "attestor_signatures",
            }
            if set(ordering) != expected_ordering_keys or (
                ordering.get("schema_version") != ORDERING_ATTESTATION_SCHEMA_VERSION
                or ordering.get("case_id") != case_id
                or ordering.get("prediction_receipt_sha256")
                != chronology["prediction_receipt_sha256"]
                or ordering.get("measurement_receipt_sha256")
                != chronology["measurement_receipt_sha256"]
                or ordering.get("prediction_registered_at")
                != chronology["prediction_registered_at"]
                or ordering.get("measurement_observed_at")
                != chronology["measurement_observed_at"]
                or ordering.get("strictly_before") is not True
                or ordering.get("attestor_dids") != case["adjudicator_ids"]
                or not anchor_strict_ordering_ok(
                    ordering.get("prediction_registered_at", ""),
                    ordering.get("measurement_observed_at", ""),
                )
            ):
                errors.append(f"case {case_id} ordering attestation semantic mismatch")
            else:
                errors.extend(_signature_errors(
                    dids=ordering["attestor_dids"],
                    signatures=ordering["attestor_signatures"],
                    message=ordering_attestation_bytes(ordering),
                    label=f"case {case_id} ordering attestor",
                ))
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            errors.append(f"case {case_id} confirmatory artifact invalid: {exc}")
    return errors


def validate_manifest_path(manifest_path: str | Path) -> list[str]:
    """Validate structure plus every referenced artifact and declared digest."""

    path = Path(manifest_path).expanduser().resolve()
    try:
        manifest = load_manifest(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"manifest load failed: {exc}"]
    errors = validate_manifest(manifest)
    if errors:
        return errors
    errors.extend(_validate_confirmatory_artifacts(path, manifest))
    try:
        current = _current_dependencies(path, manifest)
        current_by_name = {item["path"]: item["sha256"] for item in current}
        for item in current:
            if item["sha256"] is None:
                errors.append(f"referenced dependency is missing: {item['path']}")
        for label, expected in _expected_artifact_hashes(manifest).items():
            if current_by_name.get(label) != expected:
                errors.append(f"declared artifact sha256 mismatch: {label}")
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        errors.append(f"artifact dependency validation failed: {exc}")
    return list(dict.fromkeys(errors))


def build_backtest_measurement_lock(
    manifest_path: str | Path,
) -> dict[str, Any]:
    """Build the canonical :mod:`lakatos.measurement_lock` input seal.

    This is an integrity lock, not proof of time.  Before any device executes,
    a confirmatory caller must obtain the protocol's out-of-band witness quorum
    over the returned premeasurement-lock SHA and then call
    :func:`run_locked_manifest` with the unchanged wrapper.
    """

    path = Path(manifest_path).expanduser().resolve()
    manifest = load_manifest(path)
    errors = validate_manifest(manifest)
    errors.extend(_validate_confirmatory_artifacts(path, manifest))
    if errors:
        raise ValueError("invalid manifest: " + "; ".join(errors))
    deps = _current_dependencies(path, manifest)
    for dep in deps:
        if dep["sha256"] is None:
            raise ValueError(f"locked dependency is missing: {dep['path']}")
    for label, expected in _expected_artifact_hashes(manifest).items():
        actual = next(dep["sha256"] for dep in deps if dep["path"] == label)
        if actual != expected:
            raise ValueError(f"{label} sha256 mismatch: expected {expected}, got {actual}")
    for case in manifest.get("cases") or []:
        raw = case.get("case_package_path")
        if raw:
            package_path = _resolve_package(
                path, raw, confirmatory=manifest.get("phase") == "confirmatory"
            )
            try:
                package_input = _load_json_object(package_path)
            except (ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"case {case.get('case_id')} package is not strict JSON: {exc}") from exc
            if package_input != project_device_input(case):
                raise ValueError(
                    f"case {case.get('case_id')} package bytes do not encode the evaluated device_input"
                )
    manifest_sha = _sha256_file(path)
    env = environment_fingerprint()
    env_sha = fingerprint_sha(env)
    canonical_lock = _build_canonical_measurement_lock(
        cmd=BACKTEST_COMMAND,
        deps=deps,
        params={
            "schema_version": SCHEMA_VERSION,
            "experiment_id": manifest.get("experiment_id"),
            "phase": manifest.get("phase"),
            "expected_manifest_sha256": manifest_sha,
            "pairwise_alpha": (manifest.get("protocol") or {}).get("pairwise_alpha"),
            "dependency_layout": "portable-logical-paths/v1",
        },
        env_sha=env_sha,
        outs=[{"name": "backtest_result_sha256", "value": None}],
        measurement_grade="preregistered",
        replay_status="pending",
    )
    return {
        "schema_version": LOCK_SCHEMA_VERSION,
        "experiment_id": manifest.get("experiment_id"),
        "expected_manifest_sha256": manifest_sha,
        "environment_fingerprint": env,
        "measurement_lock": canonical_lock,
        "measurement_lock_sha": lock_sha(canonical_lock),
        "measurement_lock_key": lock_key(canonical_lock),
    }


def verify_backtest_measurement_lock(
    wrapper: dict, *, manifest_path: str | Path
) -> list[str]:
    """Verify wrapper identity plus canonical dependency/env dirtiness."""

    errors: list[str] = []
    if wrapper.get("schema_version") != LOCK_SCHEMA_VERSION:
        errors.append("invalid_lock_schema")
    canonical = wrapper.get("measurement_lock")
    if not isinstance(canonical, dict):
        return errors + ["missing_measurement_lock"]
    if lock_sha(canonical) != wrapper.get("measurement_lock_sha"):
        errors.append("measurement_lock_sha_mismatch")
    if lock_key(canonical) != wrapper.get("measurement_lock_key"):
        errors.append("measurement_lock_key_mismatch")
    path = Path(manifest_path).expanduser().resolve()
    try:
        manifest = load_manifest(path)
        current_deps = _current_dependencies(path, manifest)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return list(dict.fromkeys(errors + [f"dependency_resolution_failed:{exc}"]))
    locked_names = {str(dep.get("path") or "") for dep in canonical.get("deps") or []}
    current_names = {dep["path"] for dep in current_deps}
    if locked_names != current_names:
        errors.append("required_dependency_set_mismatch")
    current_by_name = {dep["path"]: dep["sha256"] for dep in current_deps}
    for label, declared_sha in _expected_artifact_hashes(manifest).items():
        if current_by_name.get(label) != declared_sha:
            errors.append(f"declared_artifact_sha_mismatch:{label}")
    env = environment_fingerprint()
    current_env_sha = fingerprint_sha(env)
    if wrapper.get("environment_fingerprint") != env:
        errors.append("environment_fingerprint_mismatch")
    if canonical.get("env_sha") != current_env_sha:
        errors.append("environment_sha_mismatch")
    if canonical.get("cmd") != BACKTEST_COMMAND:
        errors.append("measurement_command_mismatch")
    if canonical.get("measurement_grade") != "preregistered" or canonical.get("replay_status") != "pending":
        errors.append("premeasurement_state_mismatch")
    if canonical.get("outs") != [{"name": "backtest_result_sha256", "value": None}]:
        errors.append("premeasurement_outputs_mismatch")
    actual_manifest_sha = _sha256_file(path)
    if wrapper.get("expected_manifest_sha256") != actual_manifest_sha:
        errors.append("manifest_sha_mismatch")
    expected_params = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": manifest.get("experiment_id"),
        "phase": manifest.get("phase"),
        "expected_manifest_sha256": actual_manifest_sha,
        "pairwise_alpha": (manifest.get("protocol") or {}).get("pairwise_alpha"),
        "dependency_layout": "portable-logical-paths/v1",
    }
    if canonical.get("params") != expected_params:
        errors.append("measurement_params_mismatch")
    errors.extend(lock_dirty(
        canonical,
        current_deps=current_deps,
        current_env_sha=current_env_sha,
    ))
    return list(dict.fromkeys(errors))


def finalize_backtest_result_lock(
    premeasurement_wrapper: dict, *, result_sha256: str, result_status: str
) -> dict[str, Any]:
    """Bind producer output honestly; replay remains pending until byte comparison."""

    if not _is_sha256(result_sha256):
        raise ValueError("result_sha256 must be a sha256 hex digest")
    if result_status not in RESULT_STATUSES:
        raise ValueError("invalid or non-scientific results cannot receive a result receipt")
    pre = premeasurement_wrapper.get("measurement_lock")
    if not isinstance(pre, dict):
        raise ValueError("premeasurement wrapper has no canonical measurement_lock")
    if (pre.get("params") or {}).get("phase") != "confirmatory":
        raise ValueError("scientific result receipts require a confirmatory premeasurement lock")
    final_lock = _build_canonical_measurement_lock(
        cmd=pre.get("cmd", ""),
        deps=pre.get("deps") or [],
        params=pre.get("params") or {},
        env_sha=pre.get("env_sha"),
        outs=[{"name": "backtest_result_sha256", "value": result_sha256}],
        measurement_grade="producer_generated",
        replay_status="pending",
    )
    return {
        **premeasurement_wrapper,
        "measurement_lock": final_lock,
        "measurement_lock_sha": lock_sha(final_lock),
        "measurement_lock_key": lock_key(final_lock),
        "result_sha256": result_sha256,
        "result_status": result_status,
        "scientific_result_verified": False,
        "publication_eligible": False,
        "claim_eligible": False,
        "claim_grade": "producer_generated/pending",
    }


def _verify_anchor_receipt(manifest_path: Path, manifest: dict, wrapper: dict) -> dict[str, Any]:
    policy = manifest["preregistration"]["temporal_anchor"]
    allowlist_path = _resolve_manifest_relative(manifest_path, policy["witness_allowlist_path"])
    if _sha256_file(allowlist_path) != policy["witness_allowlist_sha256"]:
        raise AnchorInvalid("witness allow-list sha256 mismatch")
    allowlist = _load_json_object(allowlist_path)
    if set(allowlist) != {"schema_version", "witness_dids", "owner", "separation_attestation_sha256"}:
        raise AnchorInvalid("witness allow-list schema fields mismatch")
    witnesses = allowlist.get("witness_dids")
    if (
        allowlist.get("schema_version") != ALLOWLIST_SCHEMA_VERSION
        or not isinstance(witnesses, list)
        or len(witnesses) != len(set(witnesses))
        or any(not _valid_did(item) for item in witnesses)
        or not str(allowlist.get("owner") or "").strip()
        or not _is_sha256(allowlist.get("separation_attestation_sha256"))
    ):
        raise AnchorInvalid("invalid out-of-band witness allow-list")
    protected_roles = {
        manifest["preregistration"]["producer_did"],
        *manifest["preregistration"]["curator_dids"],
    }
    if protected_roles.intersection(witnesses):
        raise AnchorInvalid("witness DIDs overlap producer or curator roles")
    receipt_path = _resolve_manifest_relative(manifest_path, policy["receipt_path"])
    receipt = _load_json_object(receipt_path)
    if set(receipt) != {
        "schema_version", "target_kind", "target_sha256", "threshold", "anchors",
        "anchor_set_sha256", "exact_readback",
    }:
        raise AnchorInvalid("anchor receipt schema fields mismatch")
    target = wrapper.get("measurement_lock_sha")
    anchors = receipt.get("anchors")
    threshold = receipt.get("threshold")
    if receipt.get("schema_version") != ANCHOR_SCHEMA_VERSION:
        raise AnchorInvalid("anchor receipt schema version mismatch")
    if receipt.get("target_kind") != "measurement_lock_sha256" or receipt.get("target_sha256") != target:
        raise AnchorInvalid("anchor receipt targets a different premeasurement lock")
    if threshold != policy["threshold"] or not isinstance(anchors, list):
        raise AnchorInvalid("anchor threshold or anchors mismatch")
    anchor_set_sha = hashlib.sha256(_canonical_json_bytes(anchors)).hexdigest()
    if receipt.get("anchor_set_sha256") != anchor_set_sha:
        raise AnchorInvalid("anchor set exact-readback hash mismatch")
    readback = receipt.get("exact_readback")
    if not isinstance(readback, dict) or set(readback) != {
        "readback_at", "returned_target_sha256", "returned_anchor_set_sha256"
    }:
        raise AnchorInvalid("exact readback record missing or malformed")
    if (
        readback.get("returned_target_sha256") != target
        or readback.get("returned_anchor_set_sha256") != anchor_set_sha
        or not _valid_iso8601(readback.get("readback_at"))
    ):
        raise AnchorInvalid("exact readback does not match the signed anchor set")
    anchored_at = verify_temporal_quorum(
        anchors,
        expect_receipt_sha=target,
        witness_allowlist=witnesses,
        threshold=threshold,
    )
    if not anchor_ordering_ok(manifest["preregistration"]["frozen_at"], anchored_at):
        raise AnchorInvalid("anchor predates manifest freeze")
    if not anchor_ordering_ok(anchored_at, readback["readback_at"]):
        raise AnchorInvalid("exact readback predates witness quorum")
    return {
        "temporal_anchor_verified": True,
        "witness_threshold": threshold,
        "anchored_at": anchored_at,
        "anchor_receipt_sha256": _sha256_file(receipt_path),
        "anchor_set_sha256": anchor_set_sha,
    }


def run_locked_manifest(
    manifest_path: str | Path,
    *,
    lock: dict,
) -> dict[str, Any]:
    """Execute only after canonical lock and, for confirmation, external quorum verify."""

    path = Path(manifest_path).expanduser().resolve()
    try:
        initial_bytes = path.read_bytes()
        manifest = json.loads(
            initial_bytes.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_json_constant,
        )
        if not isinstance(manifest, dict):
            raise ValueError("manifest must be a JSON object")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"schema_version": SCHEMA_VERSION, "status": "INVALID", "errors": [str(exc)]}
    manifest_errors = validate_manifest(manifest)
    manifest_errors.extend(_validate_confirmatory_artifacts(path, manifest))
    if manifest_errors:
        return {"schema_version": SCHEMA_VERSION, "status": "INVALID", "errors": manifest_errors}
    lock_errors = verify_backtest_measurement_lock(lock, manifest_path=path)
    if lock_errors:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "INVALID_MEASUREMENT_LOCK",
            "errors": lock_errors,
        }
    if path.read_bytes() != initial_bytes:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "INVALID_MEASUREMENT_LOCK",
            "errors": ["manifest_changed_during_verification"],
        }
    evidence = {"temporal_anchor_verified": False, "phase": manifest["phase"]}
    if manifest["phase"] == "confirmatory":
        try:
            evidence.update(_verify_anchor_receipt(path, manifest, lock))
        except (AnchorInvalid, OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            return {
                "schema_version": SCHEMA_VERSION,
                "status": "INVALID_TEMPORAL_ANCHOR",
                "errors": [str(exc)],
            }
    result = _execute_manifest(manifest)
    post_errors = verify_backtest_measurement_lock(lock, manifest_path=path)
    if path.read_bytes() != initial_bytes or post_errors:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "INVALID_MEASUREMENT_LOCK",
            "errors": list(dict.fromkeys(
                (["manifest_changed_during_execution"] if path.read_bytes() != initial_bytes else [])
                + post_errors
            )),
        }
    result["premeasurement_evidence"] = evidence
    return result


def verify_independent_replay(
    manifest_path: str | Path,
    *,
    lock: dict,
    producer_result_path: str | Path,
    producer_receipt: dict,
    replayer_did: str,
    replay_signature_hex: str,
) -> dict[str, Any]:
    """Rerun bytes and verify an allow-listed, role-separated replayer signature."""

    if not _valid_did(replayer_did):
        raise ValueError("replayer_did must be a valid did:key")
    producer_path = Path(producer_result_path).expanduser().resolve()
    producer_sha = _sha256_file(producer_path)
    if producer_receipt.get("result_sha256") != producer_sha:
        raise ValueError("producer result bytes do not match producer receipt")
    producer_lock = producer_receipt.get("measurement_lock") or {}
    if (
        producer_receipt.get("schema_version") != lock.get("schema_version")
        or producer_receipt.get("expected_manifest_sha256")
        != lock.get("expected_manifest_sha256")
        or producer_receipt.get("environment_fingerprint")
        != lock.get("environment_fingerprint")
        or producer_receipt.get("scientific_result_verified") is not False
        or producer_receipt.get("publication_eligible") is not False
        or producer_receipt.get("claim_eligible") is not False
        or producer_receipt.get("claim_grade") != "producer_generated/pending"
        or producer_lock.get("measurement_grade") != "producer_generated"
        or producer_lock.get("replay_status") != "pending"
        or lock_sha(producer_lock) != producer_receipt.get("measurement_lock_sha")
        or lock_key(producer_lock) != producer_receipt.get("measurement_lock_key")
        or producer_receipt.get("measurement_lock_key") != lock.get("measurement_lock_key")
        or producer_lock.get("outs")
        != [{"name": "backtest_result_sha256", "value": producer_sha}]
    ):
        raise ValueError("producer receipt is not an honest pending-replay receipt")
    replay_result = run_locked_manifest(manifest_path, lock=lock)
    if replay_result.get("status") not in RESULT_STATUSES:
        raise ValueError(f"independent replay did not produce a scientific result: {replay_result.get('status')}")
    if producer_receipt.get("result_status") != replay_result.get("status"):
        raise ValueError("producer result status does not match independent replay")
    replay_bytes = _canonical_json_file_bytes(replay_result)
    replay_sha = hashlib.sha256(replay_bytes).hexdigest()
    if replay_sha != producer_sha or replay_bytes != producer_path.read_bytes():
        raise ValueError("independent replay is not byte-identical to producer result")
    manifest_path_resolved = Path(manifest_path).expanduser().resolve()
    manifest = load_manifest(manifest_path_resolved)
    prereg = manifest["preregistration"]
    allowlist = _load_json_object(_resolve_manifest_relative(
        manifest_path_resolved, prereg["replayer_allowlist"]["path"]
    ))
    if replayer_did not in (allowlist.get("replayer_dids") or []):
        raise ValueError("replayer DID is outside the preregistered allow-list")
    witness_dids = _load_json_object(_resolve_manifest_relative(
        manifest_path_resolved, prereg["temporal_anchor"]["witness_allowlist_path"]
    )).get("witness_dids") or []
    if replayer_did in {
        prereg["producer_did"], *prereg["curator_dids"], *witness_dids
    }:
        raise ValueError("replayer DID is not role-separated")
    replay_env_sha = fingerprint_sha(environment_fingerprint())
    attestation_payload = build_replay_attestation_payload(
        measurement_lock_key=lock["measurement_lock_key"],
        producer_result_sha256=producer_sha,
        result_status=replay_result["status"],
        replay_environment_sha256=replay_env_sha,
        producer_did=prereg["producer_did"],
        replayer_did=replayer_did,
    )
    try:
        signature = bytes.fromhex(replay_signature_hex)
        signature_ok = ed25519_verify(
            did_key_decode(replayer_did), replay_attestation_bytes(attestation_payload), signature
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"replayer signature parsing failed: {exc}") from exc
    if not signature_ok:
        raise ValueError("replayer signature does not bind the replay result")
    pre = lock["measurement_lock"]
    final_lock = _build_canonical_measurement_lock(
        cmd=pre["cmd"],
        deps=pre["deps"],
        params=pre["params"],
        env_sha=pre["env_sha"],
        outs=[{"name": "backtest_result_sha256", "value": producer_sha}],
        measurement_grade="externally_signed_replay",
        replay_status="verified",
    )
    return {
        **producer_receipt,
        "measurement_lock": final_lock,
        "measurement_lock_sha": lock_sha(final_lock),
        "measurement_lock_key": lock_key(final_lock),
        "replayer_did": replayer_did,
        "replay_signature": replay_signature_hex,
        "replay_attestation_payload_sha256": _sha_json(attestation_payload),
        "replay_environment_sha256": replay_env_sha,
        "replay_result_sha256": replay_sha,
        "scientific_result_verified": True,
        "publication_eligible": True,
        "claim_eligible": replay_result["status"] == "SUPPORTED",
        "claim_grade": "externally_signed_replay/verified",
    }
