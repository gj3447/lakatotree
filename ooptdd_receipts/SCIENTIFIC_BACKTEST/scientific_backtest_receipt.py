"""OOPTDD receipt for the premeasurement scientific-backtest infrastructure.

``LKT_SCI_BACKTEST_INJECT=collapse-adapters`` simulates removal of the novelty
gate by replacing the real LakatoTree trace with the naive trace.  The locked
SBT-2 requirement must then turn RED.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lakatos.backtest import (  # noqa: E402
    ANCHOR_SCHEMA_VERSION,
    ALLOWLIST_SCHEMA_VERSION,
    BLIND_ATTESTATION_SCHEMA_VERSION,
    CHRONOLOGY_RECEIPT_SCHEMA_VERSION,
    EXPOSURE_ATTESTATION_SCHEMA_VERSION,
    ORDERING_ATTESTATION_SCHEMA_VERSION,
    PILOT_SCHEMA_VERSION,
    REPLAYER_ALLOWLIST_SCHEMA_VERSION,
    blind_attestation_bytes,
    build_backtest_measurement_lock,
    evaluate_case,
    exposure_attestation_bytes,
    finalize_backtest_result_lock,
    joint_confirmatory_power_plan,
    mcnemar_exact_two_sided,
    newcombe_paired_difference_ci,
    ordering_attestation_bytes,
    project_device_input,
    required_discordant_pairs,
    run_manifest,
    run_locked_manifest,
    validate_manifest,
    verify_backtest_measurement_lock,
)
from lakatos.grounding import wilson_lower_bound  # noqa: E402
from lakatos.measurement_lock import lock_key, lock_sha  # noqa: E402
from lakatos.temporal import build_temporal_anchor  # noqa: E402
from lakatos.write_cert import (  # noqa: E402
    did_key_encode,
    ed25519_public_key,
    ed25519_sign,
)


_PRODUCER_SECRET = bytes([220]) * 32
_CURATOR_SECRETS = (bytes([221]) * 32, bytes([222]) * 32)
_REPLAYER_SECRET = bytes([223]) * 32
_PRODUCER_DID = did_key_encode(ed25519_public_key(_PRODUCER_SECRET))
_CURATOR_DIDS = [
    did_key_encode(ed25519_public_key(secret)) for secret in _CURATOR_SECRETS
]
_REPLAYER_DID = did_key_encode(ed25519_public_key(_REPLAYER_SECRET))
_PILOT_N = 100
_PILOT_D = 100
_PILOT_FLOOR = wilson_lower_bound(_PILOT_D, _PILOT_N)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_sha(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _write_json(path: Path, value: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _case(package_path: Path) -> dict:
    case = {
        "case_id": "ooptdd-no-novel",
        "source_class": "synthetic_sabotage",
        "ground_truth": "nonprogressive",
        "ground_truth_evidence": ["locked sabotage definition"],
        "adjudicator_ids": ["fixture-author"],
        "exposure_status": "development_exposed",
        "case_package_path": str(package_path),
        "prediction_registered_before_measurement": True,
        "prediction": {
            "metric_name": "error",
            "direction": "lower",
            "baseline_value": 1.0,
            "noise_band": 0.0,
            "scale_type": "ratio",
        },
        "measurement": {"value": 0.5, "source_sha256": _sha("measurement")},
    }
    package_path.write_text(
        json.dumps(project_device_input(case), sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    case["case_package_sha256"] = hashlib.sha256(package_path.read_bytes()).hexdigest()
    return case


def _manifest(case: dict) -> dict:
    return {
        "schema_version": "lakatotree-scientific-backtest/v1",
        "experiment_id": "ooptdd-development-fixture",
        "phase": "development",
        "status": "sealed",
        "measurement_started": False,
        "protocol": {
            "familywise_alpha": 0.05,
            "pairwise_alpha": 0.025,
            "min_power": 0.8,
            "conditional_accuracy_advantage": 0.8,
            "accuracy_discordance_rate_floor": 1.0,
            "min_sensitivity_wilson_lb": 0.7,
            "sensitivity_alternative": 0.9,
        },
        "cases": [case],
    }


def _inline_case(case_id: str, truth: str, source_class: str, novel: bool) -> dict:
    case = {
        "case_id": case_id,
        "source_class": source_class,
        "ground_truth": truth,
        "ground_truth_evidence": [f"sealed:{case_id}"],
        "adjudicator_ids": list(_CURATOR_DIDS),
        "exposure_status": "sealed_holdout",
        "sampling_unit_id": f"sampling:{case_id}",
        "component_id": f"component:{case_id}",
        "source_entity_ids": [f"source:{case_id}"],
        "prediction_registered_before_measurement": True,
        "chronology": {
            "prediction_registered_at": "2026-07-28T00:00:00+00:00",
            "measurement_observed_at": "2026-07-28T01:00:00+00:00",
            "prediction_receipt_path": f"chronology/{case_id}.prediction.json",
            "prediction_receipt_sha256": _sha(f"prediction-receipt:{case_id}"),
            "measurement_receipt_path": f"chronology/{case_id}.measurement.json",
            "measurement_receipt_sha256": _sha(f"measurement-receipt:{case_id}"),
            "ordering_attestation_path": f"chronology/{case_id}.ordering.json",
            "ordering_attestation_sha256": _sha(f"ordering:{case_id}"),
        },
        "prediction": {
            "metric_name": "error", "direction": "lower", "baseline_value": 1.0,
            "noise_band": 0.0, "scale_type": "ratio",
        },
        "measurement": {"value": 0.5, "source_sha256": _sha(f"measurement:{case_id}")},
    }
    if novel:
        case["novel_target"] = {
            "metric_name": "heldout_error", "direction": "lower", "threshold": 0.4,
            "measured": 0.3, "source_sha256": _sha(f"novel:{case_id}"),
        }
    device = project_device_input(case)
    case["case_package_sha256"] = hashlib.sha256(
        json.dumps(device, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    return case


def _confirmatory_manifest(root: Path) -> dict:
    cases = [_inline_case(f"p-{i}", "progressive", "external", True) for i in range(48)]
    cases += [_inline_case(f"n-{i}", "nonprogressive", "external", False) for i in range(48)]
    cases += [
        _inline_case(f"s-{i}", "nonprogressive", "synthetic_sabotage", False)
        for i in range(32)
    ]
    for case in cases:
        case["case_package_path"] = f"packages/{case['case_id']}.json"
        case["case_package_sha256"] = _write_json(
            root / case["case_package_path"], project_device_input(case)
        )
        chronology = case["chronology"]
        novel = case.get("novel_target")
        prediction_payload = {
            "case_id": case["case_id"],
            "prediction_registered_before_measurement": True,
            "prediction": case["prediction"],
            "novel_target_spec": None if not isinstance(novel, dict) else {
                key: novel[key]
                for key in ("metric_name", "direction", "threshold", "novelty_sense")
                if key in novel
            },
        }
        measurement_payload = {
            "case_id": case["case_id"],
            "measurement": case["measurement"],
            "novel_observation": None if not isinstance(novel, dict) else {
                "measured": novel["measured"], "source_sha256": novel["source_sha256"]
            },
        }
        pred_receipt = {
            "schema_version": CHRONOLOGY_RECEIPT_SCHEMA_VERSION,
            "receipt_kind": "prediction_registration",
            "case_id": case["case_id"],
            "recorded_at": chronology["prediction_registered_at"],
            "payload_sha256": _json_sha(prediction_payload),
        }
        measurement_receipt = {
            "schema_version": CHRONOLOGY_RECEIPT_SCHEMA_VERSION,
            "receipt_kind": "measurement_observation",
            "case_id": case["case_id"],
            "recorded_at": chronology["measurement_observed_at"],
            "payload_sha256": _json_sha(measurement_payload),
        }
        chronology["prediction_receipt_sha256"] = _write_json(
            root / chronology["prediction_receipt_path"], pred_receipt
        )
        chronology["measurement_receipt_sha256"] = _write_json(
            root / chronology["measurement_receipt_path"], measurement_receipt
        )
        ordering = {
            "schema_version": ORDERING_ATTESTATION_SCHEMA_VERSION,
            "case_id": case["case_id"],
            "prediction_receipt_sha256": chronology["prediction_receipt_sha256"],
            "measurement_receipt_sha256": chronology["measurement_receipt_sha256"],
            "prediction_registered_at": chronology["prediction_registered_at"],
            "measurement_observed_at": chronology["measurement_observed_at"],
            "strictly_before": True,
            "attestor_dids": list(_CURATOR_DIDS),
        }
        ordering_message = ordering_attestation_bytes(ordering)
        ordering["attestor_signatures"] = {
            did: ed25519_sign(secret, ordering_message).hex()
            for did, secret in zip(_CURATOR_DIDS, _CURATOR_SECRETS)
        }
        chronology["ordering_attestation_sha256"] = _write_json(
            root / chronology["ordering_attestation_path"], ordering
        )
    contrast = {
        "total_pairs": _PILOT_N,
        "discordant_pairs": _PILOT_D,
        "observed_discordance_rate": 1.0,
        "wilson95_lower": _PILOT_FLOOR,
    }
    pilot_sha = _write_json(root / "pilot.json", {
        "schema_version": PILOT_SCHEMA_VERSION,
        "source_phase": "development",
        "total_pilot_cases": _PILOT_N,
        "contrasts": {
            "lakatotree_vs_naive": dict(contrast),
            "lakatotree_vs_popper_like": dict(contrast),
        },
        "accuracy_discordance_rate_floor": _PILOT_FLOOR,
        "pilot_cases": [
            {
                "sampling_unit_id": f"pilot-sampling:{i}",
                "component_id": f"pilot-component:{i}",
                "source_entity_ids": [f"pilot-source:{i}"],
            }
            for i in range(_PILOT_N)
        ],
        "source_entity_ids": [f"pilot-source:{i}" for i in range(_PILOT_N)],
        "component_ids": [f"pilot-component:{i}" for i in range(_PILOT_N)],
    })
    external = [case for case in cases if case["source_class"] == "external"]
    blind = {
        "schema_version": BLIND_ATTESTATION_SCHEMA_VERSION,
        "completed_at": "2026-07-28T23:00:00+00:00",
        "curator_dids": list(_CURATOR_DIDS),
        "device_outputs_seen": False,
        "rubric_sha256": _sha("ooptdd-rubric"),
        "raw_labels_sha256": _sha("ooptdd-raw-labels"),
        "consensus_rule": "unanimous-two-curator-consensus",
        "ground_truth_assignment_sha256": _json_sha([
            {
                "case_id": case["case_id"],
                "ground_truth": case["ground_truth"],
                "ground_truth_evidence": case["ground_truth_evidence"],
            }
            for case in external
        ]),
    }
    blind_message = blind_attestation_bytes(blind)
    blind["curator_signatures"] = {
        did: ed25519_sign(secret, blind_message).hex()
        for did, secret in zip(_CURATOR_DIDS, _CURATOR_SECRETS)
    }
    blind_sha = _write_json(root / "blind.json", blind)
    exposure = {
        "schema_version": EXPOSURE_ATTESTATION_SCHEMA_VERSION,
        "holdout_exposed_to_developers": False,
        "holdout_identity_sha256": _json_sha({
            "sampling_unit_ids": sorted(case["sampling_unit_id"] for case in external),
            "component_ids": sorted(case["component_id"] for case in external),
            "source_entity_ids": sorted(
                value for case in external for value in case["source_entity_ids"]
            ),
        }),
        "curator_dids": list(_CURATOR_DIDS),
    }
    exposure_message = exposure_attestation_bytes(exposure)
    exposure["curator_signatures"] = {
        did: ed25519_sign(secret, exposure_message).hex()
        for did, secret in zip(_CURATOR_DIDS, _CURATOR_SECRETS)
    }
    exposure_sha = _write_json(root / "exposure.json", exposure)
    replayer_sha = _write_json(root / "replayers.json", {
        "schema_version": REPLAYER_ALLOWLIST_SCHEMA_VERSION,
        "replayer_dids": [_REPLAYER_DID],
        "owner": "ooptdd-independent-replay-board",
        "separation_attestation_sha256": _sha("replayer-separation"),
    })
    dids = [
        did_key_encode(ed25519_public_key(bytes([value]) * 32)) for value in (231, 232)
    ]
    allowlist = {
        "schema_version": ALLOWLIST_SCHEMA_VERSION,
        "witness_dids": dids,
        "owner": "ooptdd-independent-witness-fixture",
        "separation_attestation_sha256": _sha("separation"),
    }
    allowlist_path = root / "witnesses.json"
    allowlist_sha = _write_json(allowlist_path, allowlist)
    return {
        "schema_version": "lakatotree-scientific-backtest/v1",
        "experiment_id": "ooptdd-anchor-gate",
        "phase": "confirmatory",
        "status": "sealed",
        "measurement_started": False,
        "protocol": {
            "familywise_alpha": 0.05,
            "pairwise_alpha": 0.025,
            "min_power": 0.8,
            "conditional_accuracy_advantage": 0.8,
            "accuracy_discordance_rate_floor": _PILOT_FLOOR,
            "min_sensitivity_wilson_lb": 0.7,
            "sensitivity_alternative": 0.9,
        },
        "preregistration": {
            "frozen_at": "2026-07-29T00:00:00+00:00",
            "code_commit": "a" * 40,
            "sampling_frame": "ooptdd sealed external fixture",
            "target_population": "ooptdd external claims",
            "pilot_receipt": {"path": "pilot.json", "sha256": pilot_sha},
            "producer_did": _PRODUCER_DID,
            "curator_dids": list(_CURATOR_DIDS),
            "replayer_allowlist": {"path": "replayers.json", "sha256": replayer_sha},
            "blind_adjudication": {
                "completed_at": "2026-07-28T23:00:00+00:00",
                "attestation_path": "blind.json",
                "attestation_sha256": blind_sha,
                "device_outputs_seen": False,
            },
            "prior_exposure": {
                "attestation_path": "exposure.json",
                "attestation_sha256": exposure_sha,
                "holdout_exposed_to_developers": False,
            },
            "temporal_anchor": {
                "receipt_path": "anchor.json",
                "witness_allowlist_path": "witnesses.json",
                "witness_allowlist_sha256": allowlist_sha,
                "threshold": 2,
            },
        },
        "cases": cases,
    }


def _event(cid: str, name: str, **attrs):
    return {
        "cid": cid,
        "correlation_id": cid,
        "cycle_id": cid,
        "service": "lakatos.scientific_backtest",
        "event": name,
        **attrs,
    }


def verify(backend, cid):
    with tempfile.TemporaryDirectory(prefix="lkt-sbt-") as tmp:
        root = Path(tmp)
        package = root / "case.json"
        case = _case(package)
        manifest_path = root / "manifest.json"
        manifest_path.write_text(
            json.dumps(_manifest(case), sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        lock = build_backtest_measurement_lock(manifest_path)

        confirmatory_path = root / "confirmatory.json"
        confirmatory_manifest = _confirmatory_manifest(root)
        confirmatory_path.write_text(
            json.dumps(confirmatory_manifest, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        confirmatory_lock = build_backtest_measurement_lock(confirmatory_path)
        witness_secrets = (bytes([231]) * 32, bytes([232]) * 32)
        witness_dids = [
            did_key_encode(ed25519_public_key(secret)) for secret in witness_secrets
        ]
        anchors = [
            build_temporal_anchor(
                secret,
                confirmatory_lock["measurement_lock_sha"],
                f"2026-07-29T00:00:0{index}+00:00",
                did,
            )
            for index, (secret, did) in enumerate(
                zip(witness_secrets, witness_dids), start=1
            )
        ]
        anchor_set_sha = _json_sha(anchors)
        _write_json(root / "anchor.json", {
            "schema_version": ANCHOR_SCHEMA_VERSION,
            "target_kind": "measurement_lock_sha256",
            "target_sha256": confirmatory_lock["measurement_lock_sha"],
            "threshold": 2,
            "anchors": anchors,
            "anchor_set_sha256": anchor_set_sha,
            "exact_readback": {
                "readback_at": "2026-07-29T00:00:10+00:00",
                "returned_target_sha256": confirmatory_lock["measurement_lock_sha"],
                "returned_anchor_set_sha256": anchor_set_sha,
            },
        })
        anchored = run_locked_manifest(confirmatory_path, lock=confirmatory_lock)
        assert anchored["status"] == "SUPPORTED", anchored
        original_confirmatory = confirmatory_path.read_bytes()
        tampered_manifest = copy.deepcopy(confirmatory_manifest)
        tampered_manifest["experiment_id"] = "post-lock-manifest-tamper"
        confirmatory_path.write_text(
            json.dumps(tampered_manifest, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        temporal = run_locked_manifest(confirmatory_path, lock=confirmatory_lock)
        assert temporal["status"] == "INVALID_MEASUREMENT_LOCK", temporal
        confirmatory_path.write_bytes(original_confirmatory)
        backend.ship([_event(
            cid,
            "temporal_anchor_tamper_rejected",
            expected_manifest_sha256=confirmatory_lock["expected_manifest_sha256"],
        )])
        first_case = confirmatory_manifest["cases"][0]
        prediction_path = root / first_case["chronology"]["prediction_receipt_path"]
        original_prediction = prediction_path.read_bytes()
        tampered_prediction = json.loads(original_prediction)
        tampered_prediction["payload_sha256"] = _sha("unrelated-payload")
        prediction_path.write_text(json.dumps(tampered_prediction), encoding="utf-8")
        chronology_tamper = run_locked_manifest(confirmatory_path, lock=confirmatory_lock)
        assert chronology_tamper["status"] == "INVALID", chronology_tamper
        prediction_path.write_bytes(original_prediction)
        backend.ship([_event(cid, "chronology_semantic_tamper_rejected")])

        duplicate = copy.deepcopy(confirmatory_manifest)
        external = [case for case in duplicate["cases"] if case["source_class"] == "external"]
        for field in ("sampling_unit_id", "component_id", "source_entity_ids", "case_package_sha256"):
            external[1][field] = copy.deepcopy(external[0][field])
        assert any(
            "pairwise" in error or "nonoverlapping" in error
            for error in validate_manifest(duplicate)
        )
        underpowered_plan = joint_confirmatory_power_plan(
            external_cases=48,
            discordance_rate_floor=0.5,
            conditional_advantage=0.8,
            pairwise_alpha=0.025,
            sensitivity_alternative=0.9,
            sensitivity_wilson_floor=0.7,
            joint_target_power=0.8,
        )
        assert underpowered_plan["passed"] is False
        underpowered = copy.deepcopy(confirmatory_manifest)
        underpowered["protocol"]["accuracy_discordance_rate_floor"] = 0.5
        underpowered_external = [
            case for case in underpowered["cases"] if case["source_class"] == "external"
        ]
        underpowered_sabotage = [
            case for case in underpowered["cases"]
            if case["source_class"] == "synthetic_sabotage"
        ]
        underpowered["cases"] = (
            underpowered_external[:24]
            + underpowered_external[48:72]
            + underpowered_sabotage[:16]
        )
        underpowered_errors = validate_manifest(underpowered)
        assert any("joint power plan" in error for error in underpowered_errors)
        underpowered_path = root / "underpowered.json"
        underpowered_path.write_text(
            json.dumps(underpowered, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        try:
            build_backtest_measurement_lock(underpowered_path)
        except ValueError as exc:
            assert "joint power plan" in str(exc)
        else:
            raise AssertionError("underpowered confirmatory manifest received a lock")
        backend.ship([_event(cid, "sampling_independence_and_joint_power_rejected")])

        locked_dep_names = {
            dep["path"] for dep in confirmatory_lock["measurement_lock"]["deps"]
        }
        assert {
            "repo:lakatos/io/__init__.py",
            "repo:lakatos/verdict/__init__.py",
            "repo:lakatos/write_cert.py",
        } <= locked_dep_names
        witness_path = root / "witnesses.json"
        original_witnesses = witness_path.read_bytes()
        overlapping_witnesses = {
            "schema_version": ALLOWLIST_SCHEMA_VERSION,
            "witness_dids": [_PRODUCER_DID, _CURATOR_DIDS[0]],
            "owner": "invalid-overlapping-roles",
            "separation_attestation_sha256": _sha("invalid-overlap"),
        }
        overlap_manifest = copy.deepcopy(confirmatory_manifest)
        overlap_manifest["preregistration"]["temporal_anchor"][
            "witness_allowlist_sha256"
        ] = _write_json(witness_path, overlapping_witnesses)
        overlap_path = root / "overlap.json"
        overlap_path.write_text(
            json.dumps(overlap_manifest, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        try:
            build_backtest_measurement_lock(overlap_path)
        except ValueError as exc:
            assert "witness DIDs must be distinct" in str(exc)
        else:
            raise AssertionError("producer/curator witness overlap received a lock")
        witness_path.write_bytes(original_witnesses)

        blind_path = root / "blind.json"
        original_blind = blind_path.read_bytes()
        invalid_blind = json.loads(original_blind)
        first_curator = next(iter(invalid_blind["curator_signatures"]))
        invalid_blind["curator_signatures"][first_curator] = "00" * 64
        invalid_signature_manifest = copy.deepcopy(confirmatory_manifest)
        invalid_signature_manifest["preregistration"]["blind_adjudication"][
            "attestation_sha256"
        ] = _write_json(blind_path, invalid_blind)
        invalid_signature_path = root / "invalid-signature.json"
        invalid_signature_path.write_text(
            json.dumps(
                invalid_signature_manifest, sort_keys=True, separators=(",", ":")
            ),
            encoding="utf-8",
        )
        try:
            build_backtest_measurement_lock(invalid_signature_path)
        except ValueError as exc:
            assert "signature invalid" in str(exc)
        else:
            raise AssertionError("invalid curator signature received a lock")
        blind_path.write_bytes(original_blind)
        backend.ship([_event(cid, "signed_roles_and_crypto_dependency_bound")])

        device_input = project_device_input(case)
        assert "ground_truth" not in json.dumps(device_input)
        traces = evaluate_case(case)
        if os.getenv("LKT_SCI_BACKTEST_INJECT") == "collapse-adapters":
            traces["lakatotree"] = dict(traces["naive"])
        assert traces["naive"]["progressive"] is True
        assert traces["popper_like"]["progressive"] is True
        assert traces["lakatotree"]["progressive"] is False, (
            "collapsed LakatoTree trace no longer rejects improvement "
            "without novel corroboration"
        )
        assert traces["lakatotree"]["verdict"] == "partial"
        backend.ship([_event(
            cid,
            "three_adapter_trace_distinct",
            naive=traces["naive"]["verdict"],
            popper_like=traces["popper_like"]["verdict"],
            lakatotree=traces["lakatotree"]["verdict"],
        )])

        plan = required_discordant_pairs(
            conditional_advantage=0.8, alpha=0.025, target_power=0.8
        )
        interval = newcombe_paired_difference_ci(
            both_event=36, first_only=12, second_only=2, neither=0, alpha=0.05
        )
        assert mcnemar_exact_two_sided(7, 0) == 0.015625
        assert mcnemar_exact_two_sided(6, 0) == 0.03125
        assert plan["required_discordant_pairs"] == 24
        assert math.isclose(plan["achieved_power"], 0.811071055118881)
        assert math.isclose(interval["lower"], 0.0569267, abs_tol=1e-6)
        assert math.isclose(interval["upper"], 0.3404303, abs_tol=1e-6)
        backend.ship([_event(
            cid,
            "paired_statistics_golden_reproduced",
            required_discordant_pairs=24,
        )])

        package.write_text('{"sealed":false}\n', encoding="utf-8")
        dirty = verify_backtest_measurement_lock(lock, manifest_path=manifest_path)
        assert "stale_inputs" in dirty, dirty
        backend.ship([_event(cid, "canonical_measurement_lock_tamper_red")])

        dev = run_manifest(_manifest(case))
        assert dev["status"] == "DEVELOPMENT_ONLY" and dev["claim_eligible"] is False
        try:
            finalize_backtest_result_lock(
                lock,
                result_sha256=_sha("development-result"),
                result_status="SUPPORTED",
            )
        except ValueError:
            pass
        else:
            raise AssertionError("development output received a scientific receipt")
        try:
            finalize_backtest_result_lock(
                confirmatory_lock,
                result_sha256=_sha("invalid-result"),
                result_status="INVALID_MEASUREMENT_LOCK",
            )
        except ValueError:
            pass
        else:
            raise AssertionError("invalid output received a scientific receipt")
        pending = finalize_backtest_result_lock(
            confirmatory_lock,
            result_sha256=_sha("unreplayed-result"),
            result_status="SUPPORTED",
        )
        assert pending["measurement_lock"]["measurement_grade"] == "producer_generated"
        assert pending["measurement_lock"]["replay_status"] == "pending"
        assert pending["claim_eligible"] is False
        assert pending["claim_grade"] == "producer_generated/pending"
        forged = copy.deepcopy(lock)
        forged["measurement_lock"]["deps"] = []
        forged["measurement_lock_sha"] = lock_sha(forged["measurement_lock"])
        forged["measurement_lock_key"] = lock_key(forged["measurement_lock"])
        assert "required_dependency_set_mismatch" in verify_backtest_measurement_lock(
            forged, manifest_path=manifest_path
        )
        backend.ship([_event(cid, "scientific_claim_grade_fail_closed")])

        mismatch_package = root / "unrelated-case.json"
        mismatch_package.write_text('{"unrelated":true}', encoding="utf-8")
        mismatch_case = _case(root / "bound-case.json")
        mismatch_case["case_package_path"] = str(mismatch_package)
        mismatch_case["case_package_sha256"] = hashlib.sha256(
            mismatch_package.read_bytes()
        ).hexdigest()
        mismatch_manifest = root / "mismatch-manifest.json"
        mismatch_manifest.write_text(
            json.dumps(_manifest(mismatch_case), sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        try:
            build_backtest_measurement_lock(mismatch_manifest)
        except ValueError as exc:
            assert "evaluated device_input" in str(exc)
        else:
            raise AssertionError("unrelated case package was accepted")
        chronology_bad = _confirmatory_manifest(root)
        chronology_bad["cases"][0]["chronology"]["prediction_registered_at"] = (
            "2026-07-28T02:00:00+00:00"
        )
        assert any(
            "chronology contradicts preregistration boolean" in error
            for error in validate_manifest(chronology_bad)
        )
        backend.ship([_event(cid, "device_input_and_chronology_bound")])
