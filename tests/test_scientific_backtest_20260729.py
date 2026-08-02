from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

import pytest

from lakatos.backtest import (
    ANCHOR_SCHEMA_VERSION,
    ALLOWLIST_SCHEMA_VERSION,
    BLIND_ATTESTATION_SCHEMA_VERSION,
    CHRONOLOGY_RECEIPT_SCHEMA_VERSION,
    EXPOSURE_ATTESTATION_SCHEMA_VERSION,
    ORDERING_ATTESTATION_SCHEMA_VERSION,
    PILOT_SCHEMA_VERSION,
    REPLAYER_ALLOWLIST_SCHEMA_VERSION,
    analyze_decisions,
    blind_attestation_bytes,
    build_replay_attestation_payload,
    build_backtest_measurement_lock,
    evaluate_case,
    exposure_attestation_bytes,
    finalize_backtest_result_lock,
    joint_confirmatory_power_plan,
    load_manifest,
    mcnemar_exact_two_sided,
    newcombe_paired_difference_ci,
    ordering_attestation_bytes,
    project_device_input,
    required_discordant_pairs,
    replay_attestation_bytes,
    run_manifest,
    run_locked_manifest,
    validate_manifest,
    validate_manifest_path,
    verify_backtest_measurement_lock,
    verify_independent_replay,
)
from lakatos.grounding import wilson_lower_bound
from lakatos.io.envfp import environment_fingerprint, fingerprint_sha
from lakatos.measurement_lock import lock_key, lock_sha
from lakatos.temporal import build_temporal_anchor
from lakatos.write_cert import did_key_encode, ed25519_public_key, ed25519_sign


_PRODUCER_SECRET = bytes([210]) * 32
_CURATOR_SECRETS = (bytes([211]) * 32, bytes([212]) * 32)
_REPLAYER_SECRET = bytes([213]) * 32
PRODUCER_DID = did_key_encode(ed25519_public_key(_PRODUCER_SECRET))
CURATOR_DIDS = [did_key_encode(ed25519_public_key(value)) for value in _CURATOR_SECRETS]
REPLAYER_DID = did_key_encode(ed25519_public_key(_REPLAYER_SECRET))
PILOT_N = 100
PILOT_D = 100
PILOT_FLOOR = wilson_lower_bound(PILOT_D, PILOT_N)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _case(
    case_id: str,
    *,
    truth: str,
    preregistered: bool = True,
    novel: bool = True,
    exposed: bool = False,
    source_class: str = "external",
) -> dict:
    row = {
        "case_id": case_id,
        "source_class": source_class,
        "ground_truth": truth,
        "ground_truth_evidence": [f"evidence:{case_id}:a", f"evidence:{case_id}:b"],
        "adjudicator_ids": list(CURATOR_DIDS),
        "exposure_status": "development_exposed" if exposed else "sealed_holdout",
        "sampling_unit_id": f"sampling:{case_id}",
        "component_id": f"component:{case_id}",
        "source_entity_ids": [f"source:{case_id}"],
        "prediction_registered_before_measurement": preregistered,
        "chronology": {
            "prediction_registered_at": (
                "2026-07-28T00:00:00+00:00" if preregistered
                else "2026-07-28T02:00:00+00:00"
            ),
            "measurement_observed_at": "2026-07-28T01:00:00+00:00",
            "prediction_receipt_path": f"chronology/{case_id}.prediction.json",
            "prediction_receipt_sha256": _sha(f"prediction-receipt:{case_id}"),
            "measurement_receipt_path": f"chronology/{case_id}.measurement.json",
            "measurement_receipt_sha256": _sha(f"measurement-receipt:{case_id}"),
            "ordering_attestation_path": f"chronology/{case_id}.ordering.json",
            "ordering_attestation_sha256": _sha(f"ordering:{case_id}"),
        },
        "prediction": {
            "metric_name": "primary_error",
            "direction": "lower",
            "baseline_value": 1.0,
            "noise_band": 0.0,
            "scale_type": "ratio",
        },
        "measurement": {
            "value": 0.5,
            "source_sha256": _sha(f"measurement:{case_id}"),
        },
    }
    if novel:
        row["novel_target"] = {
            "metric_name": "heldout_error",
            "direction": "lower",
            "threshold": 0.4,
            "measured": 0.3,
            "source_sha256": _sha(f"novel:{case_id}"),
        }
    device_input = {
        "prediction_registered_before_measurement": row[
            "prediction_registered_before_measurement"
        ],
        "prediction": row["prediction"],
        "measurement": row["measurement"],
        "novel_target": row.get("novel_target"),
    }
    row["case_package_sha256"] = hashlib.sha256(
        json.dumps(
            device_input,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    return row


def _manifest(
    cases: list[dict], *, status: str = "sealed", phase: str = "development"
) -> dict:
    manifest = {
        "schema_version": "lakatotree-scientific-backtest/v1",
        "experiment_id": "sealed-holdout-example",
        "phase": phase,
        "status": status,
        "measurement_started": False,
        "protocol": {
            "familywise_alpha": 0.05,
            "pairwise_alpha": 0.025,
            "min_power": 0.8,
            "conditional_accuracy_advantage": 0.8,
            "accuracy_discordance_rate_floor": (
                PILOT_FLOOR if phase == "confirmatory" else 1.0
            ),
            "min_sensitivity_wilson_lb": 0.7,
            "sensitivity_alternative": 0.9,
        },
        "cases": copy.deepcopy(cases),
    }
    if phase == "confirmatory":
        manifest["preregistration"] = {
            "frozen_at": "2026-07-29T00:00:00+00:00",
            "code_commit": "a" * 40,
            "sampling_frame": "prospectively sampled external research claims",
            "target_population": "unseen external progressive and nonprogressive claims",
            "pilot_receipt": {"path": "pilot.json", "sha256": _sha("pilot")},
            "producer_did": PRODUCER_DID,
            "curator_dids": list(CURATOR_DIDS),
            "replayer_allowlist": {"path": "replayers.json", "sha256": _sha("replayers")},
            "blind_adjudication": {
                "completed_at": "2026-07-28T23:00:00+00:00",
                "attestation_path": "blind.json",
                "attestation_sha256": _sha("blind"),
                "device_outputs_seen": False,
            },
            "prior_exposure": {
                "attestation_path": "exposure.json",
                "attestation_sha256": _sha("exposure"),
                "holdout_exposed_to_developers": False,
            },
            "temporal_anchor": {
                "receipt_path": "anchor.json",
                "witness_allowlist_path": "witnesses.json",
                "witness_allowlist_sha256": _sha("witnesses"),
                "threshold": 2,
            },
        }
    return manifest


def _confirmatory_cases() -> list[dict]:
    cases = [_case(f"p-{i}", truth="progressive") for i in range(48)]
    cases += [_case(f"n-{i}", truth="nonprogressive", novel=False) for i in range(48)]
    cases += [
        _case(
            f"s-{i}", truth="nonprogressive", novel=False,
            source_class="synthetic_sabotage",
        )
        for i in range(32)
    ]
    for case in cases:
        case["case_package_path"] = f"packages/{case['case_id']}.json"
    return cases


def _json_sha(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def _write_json_artifact(path: Path, value: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prepare_confirmatory(
    tmp_path: Path, cases: list[dict] | None = None
) -> tuple[Path, dict]:
    manifest = _manifest(cases or _confirmatory_cases(), phase="confirmatory")
    prereg = manifest["preregistration"]
    for case in manifest["cases"]:
        case["case_package_path"] = f"packages/{case['case_id']}.json"
        case["case_package_sha256"] = _write_json_artifact(
            tmp_path / case["case_package_path"], project_device_input(case)
        )
        chronology = case["chronology"]
        novel = case.get("novel_target")
        novel_spec = None if not isinstance(novel, dict) else {
            key: novel[key]
            for key in ("metric_name", "direction", "threshold", "novelty_sense")
            if key in novel
        }
        prediction_payload = {
            "case_id": case["case_id"],
            "prediction_registered_before_measurement": case[
                "prediction_registered_before_measurement"
            ],
            "prediction": case["prediction"],
            "novel_target_spec": novel_spec,
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
        chronology["prediction_receipt_sha256"] = _write_json_artifact(
            tmp_path / chronology["prediction_receipt_path"], pred_receipt
        )
        chronology["measurement_receipt_sha256"] = _write_json_artifact(
            tmp_path / chronology["measurement_receipt_path"], measurement_receipt
        )
        ordering = {
            "schema_version": ORDERING_ATTESTATION_SCHEMA_VERSION,
            "case_id": case["case_id"],
            "prediction_receipt_sha256": chronology["prediction_receipt_sha256"],
            "measurement_receipt_sha256": chronology["measurement_receipt_sha256"],
            "prediction_registered_at": chronology["prediction_registered_at"],
            "measurement_observed_at": chronology["measurement_observed_at"],
            "strictly_before": True,
            "attestor_dids": case["adjudicator_ids"],
        }
        ordering_message = ordering_attestation_bytes(ordering)
        ordering["attestor_signatures"] = {
            did: ed25519_sign(secret, ordering_message).hex()
            for did, secret in zip(CURATOR_DIDS, _CURATOR_SECRETS)
        }
        chronology["ordering_attestation_sha256"] = _write_json_artifact(
            tmp_path / chronology["ordering_attestation_path"], ordering
        )

    contrast = {
        "total_pairs": PILOT_N,
        "discordant_pairs": PILOT_D,
        "observed_discordance_rate": PILOT_D / PILOT_N,
        "wilson95_lower": PILOT_FLOOR,
    }
    pilot = {
        "schema_version": PILOT_SCHEMA_VERSION,
        "source_phase": "development",
        "total_pilot_cases": PILOT_N,
        "contrasts": {
            "lakatotree_vs_naive": dict(contrast),
            "lakatotree_vs_popper_like": dict(contrast),
        },
        "accuracy_discordance_rate_floor": PILOT_FLOOR,
        "pilot_cases": [
            {
                "sampling_unit_id": f"pilot-sampling:{index}",
                "component_id": f"pilot-component:{index}",
                "source_entity_ids": [f"pilot-source:{index}"],
            }
            for index in range(PILOT_N)
        ],
        "source_entity_ids": [f"pilot-source:{index}" for index in range(PILOT_N)],
        "component_ids": [f"pilot-component:{index}" for index in range(PILOT_N)],
    }
    prereg["pilot_receipt"]["sha256"] = _write_json_artifact(
        tmp_path / "pilot.json", pilot
    )
    external = [case for case in manifest["cases"] if case["source_class"] == "external"]
    ground_truth_assignment = [
        {
            "case_id": case["case_id"],
            "ground_truth": case["ground_truth"],
            "ground_truth_evidence": case["ground_truth_evidence"],
        }
        for case in external
    ]
    blind = {
        "schema_version": BLIND_ATTESTATION_SCHEMA_VERSION,
        "completed_at": prereg["blind_adjudication"]["completed_at"],
        "curator_dids": list(CURATOR_DIDS),
        "device_outputs_seen": False,
        "rubric_sha256": _sha("independent-ground-truth-rubric"),
        "raw_labels_sha256": _sha("sealed-raw-labels"),
        "consensus_rule": "unanimous-two-curator-consensus",
        "ground_truth_assignment_sha256": _json_sha(ground_truth_assignment),
    }
    blind_message = blind_attestation_bytes(blind)
    blind["curator_signatures"] = {
        did: ed25519_sign(secret, blind_message).hex()
        for did, secret in zip(CURATOR_DIDS, _CURATOR_SECRETS)
    }
    prereg["blind_adjudication"]["attestation_sha256"] = _write_json_artifact(
        tmp_path / "blind.json", blind
    )
    identities = {
        "sampling_unit_ids": sorted(case["sampling_unit_id"] for case in external),
        "component_ids": sorted(case["component_id"] for case in external),
        "source_entity_ids": sorted(
            value for case in external for value in case["source_entity_ids"]
        ),
    }
    exposure = {
        "schema_version": EXPOSURE_ATTESTATION_SCHEMA_VERSION,
        "holdout_exposed_to_developers": False,
        "holdout_identity_sha256": _json_sha(identities),
        "curator_dids": list(CURATOR_DIDS),
    }
    exposure_message = exposure_attestation_bytes(exposure)
    exposure["curator_signatures"] = {
        did: ed25519_sign(secret, exposure_message).hex()
        for did, secret in zip(CURATOR_DIDS, _CURATOR_SECRETS)
    }
    prereg["prior_exposure"]["attestation_sha256"] = _write_json_artifact(
        tmp_path / "exposure.json", exposure
    )
    replayers = {
        "schema_version": REPLAYER_ALLOWLIST_SCHEMA_VERSION,
        "replayer_dids": [REPLAYER_DID],
        "owner": "independent-replay-board",
        "separation_attestation_sha256": _sha("replayer-separation"),
    }
    prereg["replayer_allowlist"]["sha256"] = _write_json_artifact(
        tmp_path / "replayers.json", replayers
    )
    secrets = (bytes([241]) * 32, bytes([242]) * 32)
    dids = [did_key_encode(ed25519_public_key(secret)) for secret in secrets]
    allowlist = {
        "schema_version": ALLOWLIST_SCHEMA_VERSION,
        "witness_dids": dids,
        "owner": "independent-confirmatory-review-board",
        "separation_attestation_sha256": _sha("separation-attestation"),
    }
    allowlist_path = tmp_path / "witnesses.json"
    prereg["temporal_anchor"]["witness_allowlist_sha256"] = _write_json_artifact(
        allowlist_path, allowlist
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    lock = build_backtest_measurement_lock(manifest_path)
    anchors = [
        build_temporal_anchor(
            secret,
            lock["measurement_lock_sha"],
            f"2026-07-29T00:00:0{index}+00:00",
            did,
        )
        for index, (secret, did) in enumerate(zip(secrets, dids), start=1)
    ]
    anchor_set_sha = hashlib.sha256(
        json.dumps(anchors, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    receipt = {
        "schema_version": ANCHOR_SCHEMA_VERSION,
        "target_kind": "measurement_lock_sha256",
        "target_sha256": lock["measurement_lock_sha"],
        "threshold": 2,
        "anchors": anchors,
        "anchor_set_sha256": anchor_set_sha,
        "exact_readback": {
            "readback_at": "2026-07-29T00:00:10+00:00",
            "returned_target_sha256": lock["measurement_lock_sha"],
            "returned_anchor_set_sha256": anchor_set_sha,
        },
    }
    (tmp_path / "anchor.json").write_text(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    return manifest_path, lock


def test_confirmatory_manifest_rejects_unsealed_or_exposed_cases():
    cases = _confirmatory_cases()

    assert validate_manifest(_manifest(cases, phase="confirmatory")) == []

    unsealed = _manifest(cases, status="draft", phase="confirmatory")
    assert "confirmatory manifest must be sealed before measurement" in validate_manifest(unsealed)

    exposed = copy.deepcopy(cases)
    exposed[-1]["exposure_status"] = "development_exposed"
    errors = validate_manifest(_manifest(exposed, phase="confirmatory"))
    assert any("confirmatory case is not a sealed holdout" in error for error in errors)


def test_confirmatory_rejects_pseudoreplicated_sampling_units_and_sources():
    cases = _confirmatory_cases()
    external = [case for case in cases if case["source_class"] == "external"]
    external[1]["sampling_unit_id"] = external[0]["sampling_unit_id"]
    external[1]["component_id"] = external[0]["component_id"]
    external[1]["source_entity_ids"] = list(external[0]["source_entity_ids"])
    external[1]["case_package_sha256"] = external[0]["case_package_sha256"]
    external[1]["measurement"]["source_sha256"] = external[0]["measurement"]["source_sha256"]
    errors = validate_manifest(_manifest(cases, phase="confirmatory"))
    assert any("sampling_unit_id values must be pairwise unique" in error for error in errors)
    assert "confirmatory external source_entity_ids must be pairwise nonoverlapping" in errors
    assert "confirmatory external measurement source sha256 values must be unique" in errors


def test_confirmatory_rejects_cross_case_measurement_novel_source_reuse():
    cases = _confirmatory_cases()
    external = [case for case in cases if case["source_class"] == "external"]
    external[1]["novel_target"]["source_sha256"] = external[0]["measurement"][
        "source_sha256"
    ]
    errors = validate_manifest(_manifest(cases, phase="confirmatory"))
    assert any("jointly nonoverlapping" in error for error in errors)


def test_blind_adjudication_must_precede_manifest_freeze():
    manifest = _manifest(_confirmatory_cases(), phase="confirmatory")
    manifest["preregistration"]["blind_adjudication"]["completed_at"] = manifest[
        "preregistration"
    ]["frozen_at"]
    assert "blind adjudication must complete strictly before manifest freeze" in validate_manifest(
        manifest
    )


def test_three_real_adapters_separate_improvement_preregistration_and_novelty():
    no_novel = evaluate_case(_case("no-novel", truth="nonprogressive", novel=False))
    assert no_novel["naive"]["progressive"] is True
    assert no_novel["popper_like"]["progressive"] is True
    assert no_novel["lakatotree"]["progressive"] is False
    assert no_novel["lakatotree"]["verdict"] == "partial"

    posthoc = evaluate_case(
        _case("posthoc", truth="nonprogressive", preregistered=False, novel=True)
    )
    assert posthoc["naive"]["progressive"] is True
    assert posthoc["popper_like"]["progressive"] is False
    assert posthoc["lakatotree"]["progressive"] is False
    assert posthoc["lakatotree"]["verdict"] == "invalid_posthoc"

    corroborated = evaluate_case(_case("corroborated", truth="progressive", novel=True))
    assert all(row["progressive"] for row in corroborated.values())


def test_device_projection_structurally_excludes_ground_truth_and_adjudicators():
    case = _case("blind", truth="nonprogressive")
    case["measurement"]["ground_truth"] = "leak"
    case["prediction"]["adjudicator_ids"] = ["nested-judge"]
    projected = project_device_input(case)
    assert set(projected) == {
        "prediction_registered_before_measurement",
        "prediction",
        "measurement",
        "novel_target",
    }
    assert "ground_truth" not in json.dumps(projected)
    assert "judge-a" not in json.dumps(projected)
    assert "nested-judge" not in json.dumps(projected)


def test_exact_mcnemar_boundary_matches_bonferroni_contract():
    assert mcnemar_exact_two_sided(5, 0) == 0.0625
    assert mcnemar_exact_two_sided(6, 0) == 0.03125
    assert mcnemar_exact_two_sided(7, 0) == 0.015625
    assert mcnemar_exact_two_sided(0, 0) == 1.0


def test_exact_mcnemar_large_n_is_finite_and_does_not_overflow():
    p_value = mcnemar_exact_two_sided(1_400, 600)
    assert math.isfinite(p_value)
    assert 0.0 <= p_value <= 1.0


def test_power_plan_is_not_confused_with_mathematical_significance_minimum():
    plan = required_discordant_pairs(
        conditional_advantage=0.8,
        alpha=0.025,
        target_power=0.8,
    )
    assert plan["required_discordant_pairs"] == 24
    assert math.isclose(plan["achieved_power"], 0.811071055118881)
    assert math.isclose(plan["previous_power"], 0.6946870879933336)


def test_joint_power_plan_mixes_discordance_and_sensitivity_at_actual_n():
    underpowered = joint_confirmatory_power_plan(
        external_cases=48,
        discordance_rate_floor=0.5,
        conditional_advantage=0.8,
        pairwise_alpha=0.025,
        sensitivity_alternative=0.9,
        sensitivity_wilson_floor=0.7,
        joint_target_power=0.8,
    )
    assert underpowered["comparison_component_power"] < 0.8
    assert underpowered["passed"] is False

    powered = joint_confirmatory_power_plan(
        external_cases=96,
        discordance_rate_floor=PILOT_FLOOR,
        conditional_advantage=0.8,
        pairwise_alpha=0.025,
        sensitivity_alternative=0.9,
        sensitivity_wilson_floor=0.7,
        joint_target_power=0.8,
    )
    assert powered["component_power_target"] == pytest.approx(14 / 15)
    assert powered["joint_power_lower_bound"] >= 0.8
    assert powered["passed"] is True


def test_newcombe_method10_paired_risk_difference_fixture():
    # Newcombe (1998) paired method-10 Table III fixture.  First arm has
    # 36+12 events, second has 36+2 events, so first-minus-second is +0.20.
    interval = newcombe_paired_difference_ci(
        both_event=36,
        first_only=12,
        second_only=2,
        neither=0,
        alpha=0.05,
    )
    assert math.isclose(interval["difference"], 0.2)
    assert math.isclose(interval["lower"], 0.0569267, abs_tol=1e-6)
    assert math.isclose(interval["upper"], 0.3404303, abs_tol=1e-6)


def test_analysis_requires_both_superiority_contrasts_and_positive_recall_gate():
    cases = [_case(f"p-{i}", truth="progressive") for i in range(9)]
    cases += [_case(f"n-{i}", truth="nonprogressive") for i in range(40)]
    decisions = {}
    for case in cases:
        if case["ground_truth"] == "progressive":
            decisions[case["case_id"]] = {
                arm: {"progressive": True, "verdict": "progressive"}
                for arm in ("naive", "popper_like", "lakatotree")
            }
        else:
            decisions[case["case_id"]] = {
                "naive": {"progressive": True, "verdict": "progressive"},
                "popper_like": {"progressive": True, "verdict": "progressive"},
                "lakatotree": {"progressive": False, "verdict": "partial"},
            }

    result = analyze_decisions(_manifest(cases), decisions)
    assert result["status"] == "SUPPORTED"
    assert result["sensitivity_gate"]["passed"] is True
    assert result["comparisons"]["lakatotree_vs_naive"]["passed"] is True
    assert result["comparisons"]["lakatotree_vs_popper_like"]["passed"] is True
    json.dumps(result, allow_nan=False)

    no_popper_advantage = copy.deepcopy(decisions)
    for case in cases:
        if case["ground_truth"] == "nonprogressive":
            no_popper_advantage[case["case_id"]]["popper_like"]["progressive"] = False
    failed = analyze_decisions(_manifest(cases), no_popper_advantage)
    assert failed["status"] == "NOT_SUPPORTED"
    assert failed["comparisons"]["lakatotree_vs_popper_like"]["passed"] is False


def test_underpowered_run_is_inconclusive_not_a_positive_claim():
    cases = [_case(f"p-{i}", truth="progressive") for i in range(9)]
    cases += [_case(f"n-{i}", truth="nonprogressive") for i in range(6)]
    manifest = _manifest(cases)
    manifest["protocol"]["accuracy_discordance_rate_floor"] = 1.0
    decisions = {}
    for case in cases:
        positive = case["ground_truth"] == "progressive"
        decisions[case["case_id"]] = {
            "naive": {"progressive": True, "verdict": "progressive"},
            "popper_like": {"progressive": True, "verdict": "progressive"},
            "lakatotree": {
                "progressive": positive,
                "verdict": "progressive" if positive else "partial",
            },
        }
    result = analyze_decisions(manifest, decisions)
    assert result["status"] == "INCONCLUSIVE_UNDERPOWERED"
    assert result["comparisons"]["lakatotree_vs_naive"]["p_value"] == 0.03125


def test_well_powered_null_is_not_hidden_by_other_underpowered_contrast():
    cases = [_case(f"p-{i}", truth="progressive") for i in range(34)]
    cases += [_case(f"n-{i}", truth="nonprogressive") for i in range(34)]
    decisions = {}
    for index, case in enumerate(cases):
        truth = case["ground_truth"] == "progressive"
        lkt_correct = not (case["ground_truth"] == "nonprogressive" and index < 50)
        naive_correct = lkt_correct
        if lkt_correct and 50 <= index < 57:
            naive_correct = False
        popper_correct = lkt_correct
        if not lkt_correct:
            popper_correct = True
        elif 50 <= index < 68:
            popper_correct = False

        def decision(correct: bool) -> dict:
            progressive = truth if correct else not truth
            return {
                "progressive": progressive,
                "verdict": "progressive" if progressive else "nonprogressive",
            }

        decisions[case["case_id"]] = {
            "naive": decision(naive_correct),
            "popper_like": decision(popper_correct),
            "lakatotree": decision(lkt_correct),
        }

    result = analyze_decisions(_manifest(cases), decisions)
    naive = result["comparisons"]["lakatotree_vs_naive"]
    popper = result["comparisons"]["lakatotree_vs_popper_like"]
    assert naive["power_adequate"] is False
    assert popper["power_adequate"] is True
    assert popper["significant"] is False
    assert result["status"] == "NOT_SUPPORTED"


def test_canonical_measurement_lock_detects_case_package_tampering(tmp_path):
    case = _case("locked", truth="progressive")
    package = tmp_path / "case.json"
    package.write_text(
        json.dumps(project_device_input(case), sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    case["case_package_path"] = str(package)
    case["case_package_sha256"] = hashlib.sha256(package.read_bytes()).hexdigest()
    manifest = _manifest([case])
    manifest["phase"] = "development"
    manifest["status"] = "sealed"
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")

    lock = build_backtest_measurement_lock(manifest_path)
    assert lock["measurement_lock_sha"]
    assert lock["measurement_lock_key"]
    assert verify_backtest_measurement_lock(lock, manifest_path=manifest_path) == []

    package.write_text('{"sealed":false}\n', encoding="utf-8")
    errors = verify_backtest_measurement_lock(lock, manifest_path=manifest_path)
    assert "stale_inputs" in errors


def test_final_result_lock_binds_output_without_changing_input_cache_key(tmp_path):
    _, pre = _prepare_confirmatory(tmp_path)

    final = finalize_backtest_result_lock(
        pre, result_sha256=_sha("result-bytes"), result_status="NOT_SUPPORTED"
    )
    assert final["measurement_lock_sha"] != pre["measurement_lock_sha"]
    assert final["measurement_lock_key"] == pre["measurement_lock_key"]
    assert final["measurement_lock"]["outs"] == [
        {"name": "backtest_result_sha256", "value": _sha("result-bytes")}
    ]
    assert final["measurement_lock"]["measurement_grade"] == "producer_generated"
    assert final["measurement_lock"]["replay_status"] == "pending"

    with pytest.raises(ValueError, match="invalid or non-scientific"):
        finalize_backtest_result_lock(
            pre, result_sha256=_sha("invalid"), result_status="INVALID_MEASUREMENT_LOCK"
        )


def test_confirmatory_execution_requires_real_external_quorum_and_public_api_cannot_bypass(tmp_path):
    manifest_path, lock = _prepare_confirmatory(tmp_path)
    manifest = load_manifest(manifest_path)
    assert run_manifest(manifest)["status"] == "INVALID_CONFIRMATORY_GATE"

    good = run_locked_manifest(manifest_path, lock=lock)
    assert good["status"] == "SUPPORTED"
    assert good["claim_eligible"] is False
    assert good["claim_grade"] == "producer_generated/pending"
    assert good["premeasurement_evidence"]["temporal_anchor_verified"] is True
    assert good["premeasurement_evidence"]["witness_threshold"] == 2

    receipt_path = tmp_path / "anchor.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["anchors"] = receipt["anchors"][:1]
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    bad = run_locked_manifest(manifest_path, lock=lock)
    assert bad["status"] == "INVALID_TEMPORAL_ANCHOR"


def test_confirmatory_requires_role_separated_witnesses_and_signed_provenance(tmp_path):
    manifest_path, lock = _prepare_confirmatory(tmp_path)
    original_manifest_bytes = manifest_path.read_bytes()
    original_manifest = json.loads(original_manifest_bytes)
    dep_names = {dep["path"] for dep in lock["measurement_lock"]["deps"]}
    assert "repo:lakatos/write_cert.py" in dep_names
    assert validate_manifest_path(manifest_path) == []

    witness_path = tmp_path / original_manifest["preregistration"]["temporal_anchor"][
        "witness_allowlist_path"
    ]
    original_witness_bytes = witness_path.read_bytes()
    overlap = {
        "schema_version": ALLOWLIST_SCHEMA_VERSION,
        "witness_dids": [PRODUCER_DID, CURATOR_DIDS[0]],
        "owner": "invalid-overlapping-role-fixture",
        "separation_attestation_sha256": _sha("invalid-overlap"),
    }
    overlap_manifest = copy.deepcopy(original_manifest)
    overlap_manifest["preregistration"]["temporal_anchor"][
        "witness_allowlist_sha256"
    ] = _write_json_artifact(witness_path, overlap)
    manifest_path.write_text(json.dumps(overlap_manifest, sort_keys=True), encoding="utf-8")
    with pytest.raises(ValueError, match="witness DIDs must be distinct"):
        build_backtest_measurement_lock(manifest_path)
    witness_path.write_bytes(original_witness_bytes)
    manifest_path.write_bytes(original_manifest_bytes)

    signed_artifacts = [
        (
            original_manifest["preregistration"]["blind_adjudication"]["attestation_path"],
            "curator_signatures",
            lambda value, sha: value["preregistration"]["blind_adjudication"].__setitem__(
                "attestation_sha256", sha
            ),
        ),
        (
            original_manifest["preregistration"]["prior_exposure"]["attestation_path"],
            "curator_signatures",
            lambda value, sha: value["preregistration"]["prior_exposure"].__setitem__(
                "attestation_sha256", sha
            ),
        ),
        (
            original_manifest["cases"][0]["chronology"]["ordering_attestation_path"],
            "attestor_signatures",
            lambda value, sha: value["cases"][0]["chronology"].__setitem__(
                "ordering_attestation_sha256", sha
            ),
        ),
    ]
    for relative_path, signature_field, bind_sha in signed_artifacts:
        artifact_path = tmp_path / relative_path
        original_artifact_bytes = artifact_path.read_bytes()
        artifact = json.loads(original_artifact_bytes)
        first_did = next(iter(artifact[signature_field]))
        artifact[signature_field][first_did] = "00" * 64
        tampered_manifest = copy.deepcopy(original_manifest)
        bind_sha(tampered_manifest, _write_json_artifact(artifact_path, artifact))
        manifest_path.write_text(
            json.dumps(tampered_manifest, sort_keys=True), encoding="utf-8"
        )
        assert any(
            "signature invalid" in error
            for error in validate_manifest_path(manifest_path)
        )
        with pytest.raises(ValueError, match="signature invalid"):
            build_backtest_measurement_lock(manifest_path)
        artifact_path.write_bytes(original_artifact_bytes)
        manifest_path.write_bytes(original_manifest_bytes)


def test_forged_empty_dependency_lock_is_rejected(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_manifest([_case("x", truth="progressive")])))
    wrapper = build_backtest_measurement_lock(manifest_path)
    forged = copy.deepcopy(wrapper)
    forged["measurement_lock"]["deps"] = []
    forged["measurement_lock_sha"] = lock_sha(forged["measurement_lock"])
    forged["measurement_lock_key"] = lock_key(forged["measurement_lock"])
    errors = verify_backtest_measurement_lock(forged, manifest_path=manifest_path)
    assert "required_dependency_set_mismatch" in errors


def test_lock_binds_manifest_protocol_judge_analyzer_cli_and_environment(tmp_path):
    case = _case("dependency-lock", truth="progressive")
    manifest = _manifest([case])
    manifest["phase"] = "development"
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    lock = build_backtest_measurement_lock(manifest_path)
    names = {Path(dep["path"]).name for dep in lock["measurement_lock"]["deps"]}
    logical_paths = {dep["path"] for dep in lock["measurement_lock"]["deps"]}
    assert {
        "manifest",
        "judge.py",
        "grounding.py",
        "backtest.py",
        "backtest_cli.py",
        "measurement_lock.py",
        "temporal.py",
        "write_cert.py",
        "envfp.py",
        "scientific_backtest_manifest.v1.schema.json",
        "scientific_backtest_anchor.v1.schema.json",
        "scientific_backtest_provenance.v1.schema.json",
        "scientific_backtest_protocol.v1.json",
    } <= names
    assert {
        "repo:lakatos/io/__init__.py",
        "repo:lakatos/verdict/__init__.py",
        "repo:lakatos/write_cert.py",
    } <= logical_paths
    assert len(lock["measurement_lock"]["env_sha"]) == 64
    assert lock["environment_fingerprint"]


def test_strict_manifest_loader_rejects_duplicate_keys_and_nonfinite_values(tmp_path):
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"phase":"development","phase":"confirmatory"}', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON key"):
        load_manifest(duplicate)

    nonfinite = tmp_path / "nonfinite.json"
    nonfinite.write_text('{"value":NaN}', encoding="utf-8")
    with pytest.raises(ValueError, match="non-finite JSON constant"):
        load_manifest(nonfinite)


def test_runtime_validator_rejects_extra_fields_blank_adjudicators_and_fake_sabotage():
    manifest = _manifest([_case("strict", truth="nonprogressive")])
    manifest["cases"][0]["measurement"]["ground_truth"] = "nested-leak"
    manifest["cases"][0]["adjudicator_ids"] = ["judge-a", " "]
    errors = validate_manifest(manifest)
    assert any("measurement contains unsupported field: ground_truth" in error for error in errors)
    assert any("unique non-blank strings" in error for error in errors)

    confirmatory = _manifest(_confirmatory_cases(), phase="confirmatory")
    confirmatory["cases"][-1]["ground_truth"] = "progressive"
    errors = validate_manifest(confirmatory)
    assert "synthetic_sabotage cases must be ground-truth nonprogressive" in errors


def test_confirmatory_chronology_and_frozen_thresholds_are_fail_closed():
    manifest = _manifest(_confirmatory_cases(), phase="confirmatory")
    manifest["cases"][0]["chronology"]["prediction_registered_at"] = (
        "2026-07-28T03:00:00+00:00"
    )
    manifest["protocol"]["pairwise_alpha"] = 0.49
    errors = validate_manifest(manifest)
    assert any("chronology contradicts preregistration boolean" in error for error in errors)
    assert "confirmatory protocol.pairwise_alpha must equal frozen value 0.025" in errors

    naive_time = _manifest(_confirmatory_cases(), phase="confirmatory")
    naive_time["preregistration"]["frozen_at"] = "2026-07-29T00:00:00"
    assert (
        "preregistration.frozen_at must be an ISO-8601 timestamp"
        in validate_manifest(naive_time)
    )

    equal_time = _manifest(_confirmatory_cases(), phase="confirmatory")
    equal_time["cases"][0]["chronology"]["measurement_observed_at"] = (
        equal_time["cases"][0]["chronology"]["prediction_registered_at"]
    )
    assert any(
        "chronology contradicts preregistration boolean" in error
        for error in validate_manifest(equal_time)
    )


def test_packaged_manifest_schema_matches_confirmatory_runtime_basics():
    from jsonschema import Draft202012Validator

    schema_path = Path(__file__).resolve().parents[1] / "lakatos" / "resources" / (
        "scientific_backtest_manifest.v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    invalid = _manifest(_confirmatory_cases(), phase="confirmatory")
    invalid["status"] = "draft"
    invalid["measurement_started"] = True
    schema_errors = list(Draft202012Validator(schema).iter_errors(invalid))
    assert schema_errors
    runtime_errors = validate_manifest(invalid)
    assert "confirmatory manifest must be sealed before measurement" in runtime_errors

    invalid_case = _manifest(_confirmatory_cases(), phase="confirmatory")
    invalid_case["cases"][0]["source_class"] = "dogfood"
    invalid_case["cases"][0]["exposure_status"] = "development_exposed"
    assert list(Draft202012Validator(schema).iter_errors(invalid_case))
    runtime_errors = validate_manifest(invalid_case)
    assert "confirmatory manifest forbids dogfood cases" in runtime_errors
    assert any("not a sealed holdout" in error for error in runtime_errors)


def test_external_package_must_equal_the_device_input_it_claims_to_bind(tmp_path):
    case = _case("package-mismatch", truth="progressive")
    package = tmp_path / "case.json"
    package.write_text('{"unrelated":"but honestly hashed"}', encoding="utf-8")
    case["case_package_path"] = str(package)
    case["case_package_sha256"] = hashlib.sha256(package.read_bytes()).hexdigest()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_manifest([case])), encoding="utf-8")
    with pytest.raises(ValueError, match="do not encode the evaluated device_input"):
        build_backtest_measurement_lock(manifest_path)


def test_machine_pilot_receipt_must_match_manifest_power_floor(tmp_path):
    manifest_path, _ = _prepare_confirmatory(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pilot_path = tmp_path / manifest["preregistration"]["pilot_receipt"]["path"]
    pilot = json.loads(pilot_path.read_text(encoding="utf-8"))
    pilot["accuracy_discordance_rate_floor"] = 0.5
    manifest["preregistration"]["pilot_receipt"]["sha256"] = _write_json_artifact(
        pilot_path, pilot
    )
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    with pytest.raises(ValueError, match="pilot conservative discordance floor mismatch"):
        build_backtest_measurement_lock(manifest_path)

    pilot["accuracy_discordance_rate_floor"] = PILOT_FLOOR
    pilot["pilot_cases"] = []
    pilot["source_entity_ids"] = []
    pilot["component_ids"] = []
    pilot["contrasts"]["lakatotree_vs_naive"]["total_pairs"] = PILOT_N - 1
    manifest["preregistration"]["pilot_receipt"]["sha256"] = _write_json_artifact(
        pilot_path, pilot
    )
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    with pytest.raises(ValueError, match="total_pairs must equal|pilot cases must provide"):
        build_backtest_measurement_lock(manifest_path)


def test_chronology_receipt_must_bind_case_timestamp_and_payload(tmp_path):
    manifest_path, _ = _prepare_confirmatory(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    case = manifest["cases"][0]
    chronology = case["chronology"]
    pred_path = tmp_path / chronology["prediction_receipt_path"]
    pred_receipt = json.loads(pred_path.read_text(encoding="utf-8"))
    pred_receipt["payload_sha256"] = _sha("unrelated-prediction")
    chronology["prediction_receipt_sha256"] = _write_json_artifact(pred_path, pred_receipt)
    ordering_path = tmp_path / chronology["ordering_attestation_path"]
    ordering = json.loads(ordering_path.read_text(encoding="utf-8"))
    ordering["prediction_receipt_sha256"] = chronology["prediction_receipt_sha256"]
    chronology["ordering_attestation_sha256"] = _write_json_artifact(
        ordering_path, ordering
    )
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    with pytest.raises(ValueError, match="prediction receipt semantic mismatch"):
        build_backtest_measurement_lock(manifest_path)


def test_development_phase_cannot_emit_a_scientific_supported_status():
    manifest = _manifest([_case("dev-only", truth="progressive")])
    result = run_manifest(manifest)
    assert result["status"] == "DEVELOPMENT_ONLY"
    assert result["claim_eligible"] is False
    assert result["development_analysis_status"] in {
        "SUPPORTED", "NOT_SUPPORTED", "INCONCLUSIVE_UNDERPOWERED"
    }


def test_machine_readable_manifest_schema_tracks_runtime_contract():
    schema_path = Path(__file__).resolve().parents[1] / "lakatos" / "resources" / (
        "scientific_backtest_manifest.v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["properties"]["schema_version"]["const"] == (
        "lakatotree-scientific-backtest/v1"
    )
    assert schema["$defs"]["case"]["properties"]["ground_truth"]["enum"] == [
        "progressive",
        "nonprogressive",
    ]
    assert "preregistration" in schema["properties"]


def test_cli_lock_run_and_final_receipt_roundtrip(tmp_path):
    manifest_path, _ = _prepare_confirmatory(tmp_path)
    repo = Path(__file__).resolve().parents[1]
    lock_path = tmp_path / "lock.json"
    result_path = tmp_path / "result.json"
    receipt_path = tmp_path / "receipt.json"

    subprocess.run(
        [
            sys.executable,
            "-m",
            "lakatos.backtest_cli",
            "lock",
            str(manifest_path),
            "--output",
            str(lock_path),
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "lakatos.backtest_cli",
            "run",
            str(manifest_path),
            "--lock",
            str(lock_path),
            "--output",
            str(result_path),
            "--receipt-output",
            str(receipt_path),
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    summary = json.loads(run.stdout)
    result = json.loads(result_path.read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert summary["status"] == result["status"] == "SUPPORTED"
    assert summary["claim_eligible"] is result["claim_eligible"] is False
    assert receipt["claim_eligible"] is False
    assert receipt["claim_grade"] == "producer_generated/pending"
    assert receipt["result_sha256"] == summary["result_sha256"]
    assert receipt["measurement_lock"]["replay_status"] == "pending"
    assert receipt["measurement_lock_key"] == json.loads(
        lock_path.read_text(encoding="utf-8")
    )["measurement_lock_key"]
    locked = json.loads(lock_path.read_text(encoding="utf-8"))
    replay_payload = build_replay_attestation_payload(
        measurement_lock_key=locked["measurement_lock_key"],
        producer_result_sha256=receipt["result_sha256"],
        result_status=receipt["result_status"],
        replay_environment_sha256=fingerprint_sha(environment_fingerprint()),
        producer_did=PRODUCER_DID,
        replayer_did=REPLAYER_DID,
    )
    replay_signature = ed25519_sign(
        _REPLAYER_SECRET, replay_attestation_bytes(replay_payload)
    ).hex()

    verified = verify_independent_replay(
        manifest_path,
        lock=locked,
        producer_result_path=result_path,
        producer_receipt=receipt,
        replayer_did=REPLAYER_DID,
        replay_signature_hex=replay_signature,
    )
    assert verified["measurement_lock"]["measurement_grade"] == "externally_signed_replay"
    assert verified["measurement_lock"]["replay_status"] == "verified"
    assert verified["replay_result_sha256"] == verified["result_sha256"]
    assert verified["claim_eligible"] is True
    assert verified["claim_grade"] == "externally_signed_replay/verified"

    with pytest.raises(ValueError, match="outside the preregistered allow-list"):
        verify_independent_replay(
            manifest_path,
            lock=locked,
            producer_result_path=result_path,
            producer_receipt=receipt,
            replayer_did=PRODUCER_DID,
            replay_signature_hex="00" * 64,
        )
    with pytest.raises(ValueError, match="signature does not bind"):
        verify_independent_replay(
            manifest_path,
            lock=locked,
            producer_result_path=result_path,
            producer_receipt=receipt,
            replayer_did=REPLAYER_DID,
            replay_signature_hex="00" * 64,
        )

    forged_receipt = copy.deepcopy(receipt)
    forged_receipt["measurement_lock_sha"] = _sha("forged-producer-lock")
    with pytest.raises(ValueError, match="honest pending-replay"):
        verify_independent_replay(
            manifest_path,
            lock=locked,
            producer_result_path=result_path,
            producer_receipt=forged_receipt,
            replayer_did=REPLAYER_DID,
            replay_signature_hex=replay_signature,
        )

    false_status = copy.deepcopy(receipt)
    false_status["result_status"] = "NOT_SUPPORTED"
    with pytest.raises(ValueError, match="status does not match"):
        verify_independent_replay(
            manifest_path,
            lock=locked,
            producer_result_path=result_path,
            producer_receipt=false_status,
            replayer_did=REPLAYER_DID,
            replay_signature_hex=replay_signature,
        )


def test_cli_invalid_run_does_not_emit_scientific_receipt(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_manifest([_case("invalid", truth="progressive")])))
    lock = build_backtest_measurement_lock(manifest_path)
    lock["measurement_lock"]["deps"] = []
    lock["measurement_lock_sha"] = lock_sha(lock["measurement_lock"])
    lock["measurement_lock_key"] = lock_key(lock["measurement_lock"])
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(json.dumps(lock))
    result_path = tmp_path / "result.json"
    receipt_path = tmp_path / "must-not-exist.json"
    repo = Path(__file__).resolve().parents[1]
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "lakatos.backtest_cli",
            "run",
            str(manifest_path),
            "--lock",
            str(lock_path),
            "--output",
            str(result_path),
            "--receipt-output",
            str(receipt_path),
        ],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 2
    assert json.loads(result_path.read_text())["status"] == "INVALID_MEASUREMENT_LOCK"
    assert not receipt_path.exists()


def test_verified_negative_result_is_publishable_but_not_positive_claim_eligible(tmp_path):
    cases = _confirmatory_cases()
    for case in cases:
        if case["ground_truth"] == "progressive":
            case.pop("novel_target", None)
    manifest_path, lock = _prepare_confirmatory(tmp_path, cases)
    result = run_locked_manifest(manifest_path, lock=lock)
    assert result["status"] == "NOT_SUPPORTED"
    result_path = tmp_path / "negative-result.json"
    result_bytes = (
        json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")
    result_path.write_bytes(result_bytes)
    result_sha = hashlib.sha256(result_bytes).hexdigest()
    receipt = finalize_backtest_result_lock(
        lock, result_sha256=result_sha, result_status=result["status"]
    )
    payload = build_replay_attestation_payload(
        measurement_lock_key=lock["measurement_lock_key"],
        producer_result_sha256=result_sha,
        result_status=result["status"],
        replay_environment_sha256=fingerprint_sha(environment_fingerprint()),
        producer_did=PRODUCER_DID,
        replayer_did=REPLAYER_DID,
    )
    signature = ed25519_sign(_REPLAYER_SECRET, replay_attestation_bytes(payload)).hex()
    verified = verify_independent_replay(
        manifest_path,
        lock=lock,
        producer_result_path=result_path,
        producer_receipt=receipt,
        replayer_did=REPLAYER_DID,
        replay_signature_hex=signature,
    )
    assert verified["scientific_result_verified"] is True
    assert verified["publication_eligible"] is True
    assert verified["claim_eligible"] is False


def test_cli_outputs_are_create_only_and_cannot_alias_locked_inputs(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    original = json.dumps(_manifest([_case("alias", truth="progressive")]))
    manifest_path.write_text(original, encoding="utf-8")
    repo = Path(__file__).resolve().parents[1]
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "lakatos.backtest_cli",
            "lock",
            str(manifest_path),
            "--output",
            str(manifest_path),
        ],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    assert run.returncode != 0
    assert manifest_path.read_text(encoding="utf-8") == original
