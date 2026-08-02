"""Hermetic contract and attack-regression tests for the readiness harness."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from c1verify import _ed25519 as independent_ed25519
from lakatos import temporal
from lakatos import write_cert
from ooptdd_receipts.PRODUCTION_L3_READINESS import (
    production_l3_readiness_receipt as receipt,
)
from server import production_readiness as harness


HERE = Path(__file__).resolve().parents[1] / "ooptdd_receipts" / "PRODUCTION_L3_READINESS"


def _canonical(value) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _flip_hex(value: str) -> str:
    return ("0" if value[0] != "0" else "1") + value[1:]


def _assert_not_ready(case: dict, failure: str) -> dict:
    report = harness.evaluate_readiness(case)
    assert report["status"] == "NOT_READY"
    assert report["harness_status"] == "NOT_RUN"
    assert report["production_ready"] is False
    assert report["l3_assurance"] == "UNAVAILABLE"
    assert failure in report["failures"]
    assert report["axes"]["correct"]["executed"] is False
    assert report["axes"]["correct"]["plan"]
    return report


def test_frozen_fixture_matches_builder_and_only_accepts_one_case():
    case = receipt.fixture_case()
    before = copy.deepcopy(case)

    report = harness.evaluate_readiness(case)

    assert case == receipt.build_fixture_case()
    assert case == before
    assert report["status"] == "CASE_ACCEPTED"
    assert report["harness_status"] == "NOT_RUN"
    assert report["deployment_status"] == "NOT_READY"
    assert report["production_ready"] is False
    assert report["l3_assurance"] == "UNAVAILABLE"
    assert report["storage"]["ok"] is True
    assert report["temporal"]["component_ok"] is True
    assert report["temporal"]["prediction_quorum"] is True
    assert report["temporal"]["verdict_quorum"] is True
    assert report["temporal"]["same_authority_set"] is True
    assert report["temporal"]["ordering_ok"] is True
    assert report["mutation_attempts"] == 0
    assert report["axes"]["correct"]["executed"] is False
    assert "CASE_ACCEPTED proves only" in report["claim_boundary"]
    assert "HARNESS_GREEN belongs only" in report["claim_boundary"]


def test_report_is_deterministic_bound_and_omits_authority_material():
    case = receipt.fixture_case()
    fixture_path = (HERE / "fixture.v1.json").resolve()
    file_sha = hashlib.sha256(fixture_path.read_bytes()).hexdigest()
    first = harness.evaluate_loaded_evidence(
        harness.load_evidence(fixture_path, file_sha)
    )
    second = harness.evaluate_loaded_evidence(
        harness.load_evidence(fixture_path, file_sha)
    )
    assert first == second

    body = dict(first)
    observed = body.pop("report_body_sha256")
    assert observed == hashlib.sha256(_canonical(body)).hexdigest()
    assert first["evidence_file_sha256"] == file_sha
    assert first["evidence_bytes_bound"] is True
    assert first["canonical_case_sha256"] == hashlib.sha256(_canonical(case)).hexdigest()

    encoded = json.dumps(first, sort_keys=True)
    temporal_evidence = case["temporal"]
    for anchor in temporal_evidence["sidecar"]["prediction_anchors"] + temporal_evidence[
        "sidecar"
    ]["verdict_anchors"]:
        assert anchor["signature"] not in encoded
        assert anchor["witness_did"] not in encoded
    for did in temporal_evidence["authority_policy"]["producer_dids"] + temporal_evidence[
        "authority_policy"
    ]["attestor_dids"]:
        assert did not in encoded
    assert case["storage"]["writer_fence"]["authority_public_key_hex"] not in encoded

    unbound = harness.evaluate_readiness(case)
    assert unbound["evidence_file_sha256"] is None
    assert unbound["evidence_bytes_bound"] is False


def test_loaded_evidence_rechecks_immutable_bytes_and_digest():
    case = receipt.fixture_case()
    raw = _canonical(case)
    digest = hashlib.sha256(raw).hexdigest()
    report = harness.evaluate_loaded_evidence(
        harness.LoadedEvidence(raw=raw, file_sha256=digest)
    )
    assert report["status"] == "CASE_ACCEPTED"
    assert report["evidence_bytes_bound"] is True

    with pytest.raises(harness.HarnessInputError, match="no longer match"):
        harness.evaluate_loaded_evidence(
            harness.LoadedEvidence(raw=raw + b" ", file_sha256=digest)
        )
    with pytest.raises(harness.HarnessInputError, match="lowercase SHA-256"):
        harness.evaluate_loaded_evidence(
            harness.LoadedEvidence(raw=raw, file_sha256="0" * 63)
        )


def test_unknown_fields_and_ambiguous_json_are_invalid(tmp_path):
    case = receipt.fixture_case()
    secret_key = "did:key:zSensitiveUnknownField"
    case["storage"]["runtime"][secret_key] = "must-not-be-accepted"
    with pytest.raises(harness.HarnessInputError, match="non-exact field set") as exc:
        harness.evaluate_readiness(case)
    assert secret_key not in str(exc.value)

    duplicate = tmp_path / "duplicate.json"
    duplicate_key = "did:key:zSensitiveDuplicate"
    duplicate.write_text(f'{{"{duplicate_key}":"a","{duplicate_key}":"b"}}')
    with pytest.raises(harness.HarnessInputError, match="duplicate JSON object key") as exc:
        harness.load_evidence(
            duplicate.resolve(), hashlib.sha256(duplicate.read_bytes()).hexdigest()
        )
    assert duplicate_key not in str(exc.value)


def test_evidence_size_and_temporal_cardinality_are_bounded(tmp_path):
    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b" " * (harness.MAX_EVIDENCE_BYTES + 1))
    digest = hashlib.sha256(oversized.read_bytes()).hexdigest()
    with pytest.raises(harness.HarnessInputError, match="bounded size"):
        harness.load_evidence(oversized.resolve(), digest)

    case = receipt.fixture_case()
    anchor = case["temporal"]["sidecar"]["prediction_anchors"][0]
    case["temporal"]["sidecar"]["prediction_anchors"] = [
        copy.deepcopy(anchor) for _ in range(harness.MAX_TEMPORAL_ANCHORS + 1)
    ]
    receipt._reseal_temporal(case)
    with pytest.raises(harness.HarnessInputError, match="bounded anchor count"):
        harness.evaluate_readiness(case)


@pytest.mark.parametrize(
    ("raw", "expected_error"),
    [
        pytest.param(
            b"[" * 10_000 + b"0" + b"]" * 10_000,
            "bounded nesting",
            id="deep-containers",
        ),
        pytest.param(
            b'{"x":' + b"9" * 5_000 + b"}",
            "not valid UTF-8 JSON",
            id="oversized-integer",
        ),
    ],
)
def test_pathological_json_is_normalized_to_invalid_without_echo(
    tmp_path, raw, expected_error
):
    evidence = tmp_path / "pathological.json"
    evidence.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    with pytest.raises(harness.HarnessInputError, match=expected_error) as exc:
        harness.load_evidence(evidence.resolve(), digest)
    assert "9999999999" not in str(exc.value)


@pytest.mark.parametrize(
    "timestamp",
    ["0001-01-01T00:00:00+23:59", "9999-12-31T23:59:59-23:59"],
)
def test_timestamp_normalization_overflow_is_invalid(timestamp):
    case = receipt.fixture_case()
    case["expected"]["evaluated_at"] = timestamp
    with pytest.raises(harness.HarnessInputError, match="bounded timezone-aware"):
        harness.evaluate_readiness(case)


def _predeploy_file_splice(case):
    case["storage"]["predeploy"]["file_sha256"] = "f" * 64


def _fence_key_pin_splice(case):
    case["expected"]["fence_authority_key_sha256"] = "f" * 64


def _predeploy_receipt_splice(case):
    case["storage"]["predeploy"]["receipt_sha256"] = "f" * 64


def _fence_signature_forgery(case):
    response = case["storage"]["writer_fence"]["signed_response"]
    response["signature"] = _flip_hex(response["signature"])


def _undrained_writer_projection(case):
    case["storage"]["writer_fence"]["writer_count"] = 1


def _stale_fence(case):
    case["storage"]["writer_fence"]["signed_response"][
        "verified_at"
    ] = "2026-08-02T01:00:20+00:00"
    receipt._reseal_fence(case)


def _near_expiry_fence(case):
    case["storage"]["writer_fence"]["signed_response"][
        "expires_at"
    ] = "2026-08-02T01:01:08+00:00"
    receipt._reseal_fence(case)


def _postgresql_target_splice(case):
    case["storage"]["postgresql_access"]["binding"]["target_sha256"] = "e" * 64


def _postgresql_overprivilege(case):
    case["storage"]["postgresql_access"]["runtime_table_privileges"][
        "public.history"
    ].append("UPDATE")


def _postgresql_owner_superuser(case):
    case["storage"]["postgresql_access"]["owner_role_attributes"][
        "superuser"
    ] = True


def _postgresql_migrator_createrole(case):
    case["storage"]["postgresql_access"]["migrator_role_attributes"][
        "createrole"
    ] = True


def _postgresql_object_owner_splice(case):
    case["storage"]["postgresql_access"]["object_owners"][
        "public.history"
    ] = "fixture_migrator"


def _neo4j_database_splice(case):
    case["storage"]["neo4j_access"]["database"] = "spliced_database"


def _neo4j_admin_privilege(case):
    case["storage"]["neo4j_access"]["runtime_effective_privileges"].append(
        "CONSTRAINT_MANAGEMENT"
    )


def _neo4j_builtin_public_role(case):
    case["storage"]["neo4j_access"]["runtime_roles"] = ["PUBLIC"]


def _runtime_migration_credential(case):
    case["storage"]["runtime"]["migration_environment_keys"] = [
        "LAKATOS_STORAGE_PG_MIGRATION_PASSWORD"
    ]


def _runtime_lease_splice(case):
    case["storage"]["runtime"]["writer_lease_id"] = "spliced-lease"


@pytest.mark.parametrize(
    ("mutate", "failure"),
    [
        (_predeploy_file_splice, "storage.predeploy.file_mismatch"),
        (_predeploy_receipt_splice, "storage.predeploy.receipt_mismatch"),
        (_fence_key_pin_splice, "storage.fence.authority_key_pin_mismatch"),
        (_fence_signature_forgery, "storage.fence.signature_invalid"),
        (_undrained_writer_projection, "storage.fence.writers_not_drained"),
        (_stale_fence, "storage.fence.verification_too_old"),
        (_near_expiry_fence, "storage.fence.expiry_margin_too_small"),
        (_postgresql_target_splice, "storage.postgresql.target_mismatch"),
        (_postgresql_overprivilege, "storage.postgresql.runtime_table_privileges"),
        (_postgresql_owner_superuser, "storage.postgresql.owner_role_attributes"),
        (_postgresql_migrator_createrole, "storage.postgresql.migrator_role_attributes"),
        (_postgresql_object_owner_splice, "storage.postgresql.object_ownership"),
        (_neo4j_database_splice, "storage.neo4j.database_mismatch"),
        (_neo4j_admin_privilege, "storage.neo4j.runtime_privileges"),
        (_neo4j_builtin_public_role, "storage.neo4j.builtin_role_used"),
        (_runtime_migration_credential, "storage.runtime.migration_credentials_present"),
        (_runtime_lease_splice, "storage.runtime.writer_lease_mismatch"),
    ],
)
def test_storage_authority_target_and_least_privilege_negatives(mutate, failure):
    case = receipt.fixture_case()
    mutate(case)
    report = _assert_not_ready(case, failure)
    assert report["storage"]["ok"] is False


def _forge_verdict_signature(case):
    anchor = case["temporal"]["sidecar"]["verdict_anchors"][0]
    anchor["signature"] = _flip_hex(anchor["signature"])
    receipt._reseal_temporal(case)


def _duplicate_prediction_authority(case):
    anchors = case["temporal"]["sidecar"]["prediction_anchors"]
    anchors[1] = copy.deepcopy(anchors[0])
    receipt._reseal_temporal(case)


def _wrong_anchor_channel(case):
    case["temporal"]["sidecar"]["verdict_anchors"][0]["channel"] = "server-clock"
    receipt._reseal_temporal(case)


def _role_overlap(case):
    policy = case["temporal"]["authority_policy"]
    policy["producer_dids"] = [policy["attestor_dids"][0]]
    receipt._reseal_temporal(case)


def _policy_hash_tamper(case):
    case["temporal"]["sidecar"]["authority_policy_sha256"] = "f" * 64


def _disjoint_endpoint_signers(case):
    verdict_sha = case["temporal"]["sidecar"]["verdict_receipt_sha256"]
    case["temporal"]["sidecar"]["verdict_anchors"] = [
        receipt._anchor("w3", verdict_sha, "2026-08-02T01:01:00+00:00"),
        receipt._anchor("w4", verdict_sha, "2026-08-02T01:01:04+00:00"),
    ]
    receipt._reseal_temporal(case)


def _reverse_all_anchor_time(case):
    verdict_sha = case["temporal"]["sidecar"]["verdict_receipt_sha256"]
    case["temporal"]["sidecar"]["verdict_anchors"] = [
        receipt._anchor("w1", verdict_sha, "2026-08-02T00:59:00+00:00"),
        receipt._anchor("w2", verdict_sha, "2026-08-02T00:59:03+00:00"),
    ]
    receipt._reseal_temporal(case)


def _runtime_head_splice(case):
    case["temporal"]["runtime_binding"]["verdict_receipt_sha256"] = "d" * 64


def _future_verdict_anchor(case):
    verdict_sha = case["temporal"]["sidecar"]["verdict_receipt_sha256"]
    case["temporal"]["sidecar"]["verdict_anchors"] = [
        receipt._anchor("w1", verdict_sha, "2026-08-02T01:01:06+00:00"),
        receipt._anchor("w2", verdict_sha, "2026-08-02T01:01:07+00:00"),
    ]
    receipt._reseal_temporal(case)


@pytest.mark.parametrize(
    ("mutate", "failure"),
    [
        (_forge_verdict_signature, "temporal.verdict_anchor_invalid"),
        (_duplicate_prediction_authority, "temporal.prediction_duplicate_authority"),
        (_wrong_anchor_channel, "temporal.verdict_channel_invalid"),
        (_role_overlap, "temporal.producer_attestor_role_overlap"),
        (_policy_hash_tamper, "temporal.authority_policy_sha_mismatch"),
        (_disjoint_endpoint_signers, "temporal.endpoint_authority_set_mismatch"),
        (_reverse_all_anchor_time, "temporal.all_anchor_ordering_not_strict"),
        (_runtime_head_splice, "temporal.runtime_verdict_receipt_mismatch"),
        (_future_verdict_anchor, "temporal.anchor_after_evaluation"),
    ],
)
def test_temporal_crypto_policy_relation_and_head_negatives(mutate, failure):
    case = receipt.fixture_case()
    mutate(case)
    report = _assert_not_ready(case, failure)
    assert report["temporal"]["component_ok"] is False
    assert report["temporal"]["l3_assurance"] == "UNAVAILABLE"
    if mutate is _runtime_head_splice:
        assert report["temporal"]["runtime_binding_ok"] is False


@pytest.mark.parametrize(
    "mutate",
    [
        lambda case: case["temporal"]["authority_policy"]["producer_dids"].append(
            "not-a-did"
        ),
        lambda case: case["temporal"]["sidecar"]["prediction_anchors"][0].__setitem__(
            "signature", 7
        ),
        lambda case: case["temporal"]["sidecar"]["prediction_anchors"][1].__setitem__(
            "witness_did",
            f" {case['temporal']['sidecar']['prediction_anchors'][0]['witness_did']} ",
        ),
    ],
)
def test_malformed_or_noncanonical_temporal_identity_is_invalid(mutate):
    case = receipt.fixture_case()
    mutate(case)
    with pytest.raises(harness.HarnessInputError):
        harness.evaluate_readiness(case)


def test_strict_ed25519_rejects_small_order_public_keys_and_r_points():
    identity = bytes.fromhex("01" + "00" * 31)
    order_two = bytes.fromhex("ec" + "ff" * 30 + "7f")
    order_two_point = write_cert._point_decompress(order_two)
    assert order_two_point is not None
    mixed_order = write_cert._point_compress(
        write_cert._point_add(write_cert._B, order_two_point)
    )
    valid_secret = bytes([101]) * 32
    valid_public = write_cert.ed25519_public_key(valid_secret)
    message = b"strict-ed25519-regression"
    valid_signature = write_cert.ed25519_sign(valid_secret, message)

    assert write_cert.ed25519_verify(valid_public, message, valid_signature)
    assert independent_ed25519.ed25519_verify(valid_public, message, valid_signature)
    for public_key in (identity, order_two, mixed_order):
        forged = identity + bytes(32)
        assert not write_cert.ed25519_public_key_is_strict(public_key)
        assert not independent_ed25519.ed25519_public_key_is_strict(public_key)
        assert not write_cert.ed25519_verify(public_key, message, forged)
        assert not independent_ed25519.ed25519_verify(public_key, message, forged)
    for non_profile_r in (identity, order_two, mixed_order):
        forged = non_profile_r + bytes(32)
        assert not write_cert.ed25519_verify(valid_public, message, forged)
        assert not independent_ed25519.ed25519_verify(valid_public, message, forged)


def test_temporal_anchor_primitive_rejects_wrong_channel_and_malformed_signature():
    secret = bytes([103]) * 32
    did = write_cert.did_key_encode(write_cert.ed25519_public_key(secret))
    receipt_sha = "a" * 64
    anchor = temporal.build_temporal_anchor(
        secret, receipt_sha, "2026-08-02T01:00:00+00:00", did
    )
    assert temporal.verify_temporal_anchor(
        anchor, expect_receipt_sha=receipt_sha, witness_allowlist=[did]
    ) == "2026-08-02T01:00:00+00:00"

    bad_channel = {**anchor, "channel": "server-clock"}
    with pytest.raises(temporal.AnchorInvalid):
        temporal.verify_temporal_anchor(
            bad_channel, expect_receipt_sha=receipt_sha, witness_allowlist=[did]
        )
    bad_signature = {**anchor, "signature": 7}
    with pytest.raises(temporal.AnchorInvalid):
        temporal.verify_temporal_anchor(
            bad_signature, expect_receipt_sha=receipt_sha, witness_allowlist=[did]
        )


def test_live_mode_is_explicitly_unsupported():
    case = receipt.fixture_case()
    case["mode"] = "live"

    report = harness.evaluate_readiness(case)

    assert report["status"] == "UNSUPPORTED"
    assert report["harness_status"] == "NOT_RUN"
    assert report["deployment_status"] == "NOT_READY"
    assert report["production_ready"] is False
    assert report["l3_assurance"] == "UNAVAILABLE"
    assert report["failures"] == ["mode.live_adapter_not_implemented"]


def test_cli_binds_raw_file_bytes_and_uses_distinct_exit_codes(tmp_path, capsys):
    case = receipt.fixture_case()
    pretty_file = tmp_path / "pretty.json"
    compact_file = tmp_path / "compact.json"
    pretty_file.write_bytes((HERE / "fixture.v1.json").read_bytes())
    compact_file.write_bytes(_canonical(case) + b"\n")
    pretty_sha = hashlib.sha256(pretty_file.read_bytes()).hexdigest()
    compact_sha = hashlib.sha256(compact_file.read_bytes()).hexdigest()
    assert pretty_sha != compact_sha

    assert harness.main([
        "--evidence", str(pretty_file.resolve()), "--evidence-sha256", pretty_sha
    ]) == 0
    pretty_report = json.loads(capsys.readouterr().out)
    assert pretty_report["status"] == "CASE_ACCEPTED"
    assert pretty_report["evidence_file_sha256"] == pretty_sha
    assert pretty_report["production_ready"] is False

    assert harness.main([
        "--evidence", str(compact_file.resolve()), "--evidence-sha256", compact_sha
    ]) == 0
    compact_report = json.loads(capsys.readouterr().out)
    assert compact_report["status"] == "CASE_ACCEPTED"
    assert compact_report["canonical_case_sha256"] == pretty_report[
        "canonical_case_sha256"
    ]
    assert compact_report["evidence_file_sha256"] != pretty_report[
        "evidence_file_sha256"
    ]
    assert compact_report["report_body_sha256"] != pretty_report["report_body_sha256"]

    assert harness.main([
        "--evidence", str(pretty_file.resolve()), "--evidence-sha256", "0" * 64
    ]) == 2
    error = json.loads(capsys.readouterr().err)
    assert error["schema_version"] == harness.ERROR_SCHEMA
    assert error["status"] == "INVALID"
    assert "SHA-256 mismatch" in error["error"]


def test_locked_suite_is_the_only_harness_green_source():
    manifest = json.loads((HERE / "harness.json").read_text(encoding="utf-8"))
    suite = receipt.run_harness_suite()
    assert suite["status"] == "HARNESS_GREEN"
    assert suite["production_ready"] is False
    assert suite["l3_assurance"] == "UNAVAILABLE"
    assert suite["events"] == [
        "locked_case_accepted_claim_bounded",
        "storage_authority_attacks_rejected",
        "temporal_crypto_policy_attacks_rejected",
        "temporal_relation_attacks_rejected",
        "live_authority_claim_fail_closed",
    ]
    assert suite["controls"] == manifest["suite"]["required_controls"]
    case_report = harness.evaluate_readiness(receipt.fixture_case())
    assert case_report["status"] == "CASE_ACCEPTED"
    assert case_report["harness_status"] == "NOT_RUN"


@pytest.mark.parametrize(
    "attack",
    [
        "negative-authority-overclaim",
        "negative-status-overclaim",
        "failures-string",
        "mutation-bool",
        "schema-drift",
        "mutation",
        "live",
    ],
)
def test_locked_suite_refuses_false_green_control_reports(monkeypatch, attack):
    real_evaluate = receipt.evaluate_readiness

    def attacked_evaluate(case):
        report = real_evaluate(case)
        report_modified = False
        failures = report.get("failures", ())
        if "storage.postgresql.owner_role_attributes" in failures:
            if attack == "negative-authority-overclaim":
                report = {**report, "production_ready": True, "l3_assurance": "L3"}
                report_modified = True
            elif attack == "negative-status-overclaim":
                report = {
                    **report,
                    "status": "HARNESS_GREEN",
                    "harness_status": "HARNESS_GREEN",
                }
                report_modified = True
            elif attack == "failures-string":
                report = {
                    **report,
                    "failures": "storage.postgresql.owner_role_attributes",
                }
                report_modified = True
            elif attack == "mutation-bool":
                report = {**report, "mutation_attempts": False}
                report_modified = True
            elif attack == "schema-drift":
                report = {**report, "schema_version": "drifted-report/v1"}
                report_modified = True
            elif attack == "mutation":
                case["expected"]["environment"] = "mutated-by-evaluator"
        elif attack == "live" and case.get("mode") == "live":
            report = {
                **report,
                "harness_status": "HARNESS_GREEN",
                "deployment_status": "READY",
                "l3_assurance": "L3",
            }
            report_modified = True
        if report_modified:
            body = dict(report)
            body.pop("report_body_sha256", None)
            report["report_body_sha256"] = hashlib.sha256(_canonical(body)).hexdigest()
        return report

    monkeypatch.setattr(receipt, "evaluate_readiness", attacked_evaluate)
    with pytest.raises(RuntimeError, match="readiness harness red"):
        receipt.run_harness_suite()


def test_locked_suite_checks_are_not_removed_by_optimized_python():
    source = (HERE / "production_l3_readiness_receipt.py").read_text(encoding="utf-8")
    assert not any(isinstance(node, ast.Assert) for node in ast.walk(ast.parse(source)))


def test_manifest_requirements_fixture_and_suite_events_are_exactly_bound():
    manifest = json.loads((HERE / "harness.json").read_text(encoding="utf-8"))
    requirements = yaml.safe_load((HERE / "requirements.yaml").read_text(encoding="utf-8"))
    requirement_ids = [item["id"] for item in requirements["requirements"]]
    required_events = [
        item["gate"][0]["event"] for item in requirements["requirements"]
    ]
    manifest_events = manifest["suite"]["required_events"]
    manifest_controls = manifest["suite"]["required_controls"]
    fixture_raw = (HERE / "fixture.v1.json").read_bytes()
    fixture = json.loads(fixture_raw)

    assert manifest["requirements"]["ids"] == requirement_ids
    assert [item["requirement_id"] for item in manifest_events] == requirement_ids
    assert [item["event"] for item in manifest_events] == required_events
    assert manifest_controls
    assert len(manifest_controls) == len(set(manifest_controls))
    assert all(
        isinstance(control_id, str) and control_id.count(".") >= 1
        for control_id in manifest_controls
    )
    assert manifest["tier"] == "L_IDE"
    assert manifest["targets"] == ["L_RT", "L_MC"]
    assert manifest["live_adapter"]["implemented"] is False
    assert manifest["system_under_test"]["symbol"] == "evaluate_readiness"
    assert manifest["system_under_test"]["entrypoint"] == "lakatotree-readiness-harness"
    assert manifest["suite"]["symbol"] == "run_harness_suite"
    assert manifest["fixture"]["file_sha256"] == hashlib.sha256(fixture_raw).hexdigest()
    assert manifest["fixture"]["canonical_case_sha256"] == hashlib.sha256(
        _canonical(fixture)
    ).hexdigest()
    report = harness.evaluate_loaded_evidence(
        harness.load_evidence(
            (HERE / "fixture.v1.json").resolve(),
            manifest["fixture"]["file_sha256"],
        )
    )
    assert report["report_body_sha256"] == manifest["fixture"][
        "expected_case_report_body_sha256"
    ]
