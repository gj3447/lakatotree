"""Locked OOPTDD suite for the production/L3 readiness case evaluator."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
FIXTURE_PATH = HERE / "fixture.v1.json"
HARNESS_PATH = HERE / "harness.json"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from lakatos.temporal import anchor_digest, build_temporal_anchor  # noqa: E402
from lakatos.write_cert import (  # noqa: E402
    did_key_encode,
    ed25519_public_key,
    ed25519_sign,
)
from server.production_readiness import (  # noqa: E402
    AUTHORITY_POLICY_SCHEMA,
    CASE_REPORT_SCHEMA,
    CASE_SCHEMA,
    HarnessInputError,
    NEO4J_ACCESS_SCHEMA,
    PG_ACCESS_SCHEMA,
    RUNTIME_SCHEMA,
    SIDECAR_SCHEMA,
    TEMPORAL_BINDING_SCHEMA,
    evaluate_loaded_evidence,
    evaluate_readiness,
    load_evidence,
    temporal_authority_policy_sha256,
    temporal_sidecar_sha256,
)
from server.storage_protocol import (  # noqa: E402
    FENCE_SIGNATURE_DOMAIN,
    FENCE_VERIFICATION_SCHEMA,
    STORAGE_CONTRACT_ID,
)


_SECRETS = {
    "fence": bytes([13]) * 32,
    "w1": bytes([31]) * 32,
    "w2": bytes([47]) * 32,
    "w3": bytes([53]) * 32,
    "w4": bytes([59]) * 32,
    "producer": bytes([61]) * 32,
    "attestor": bytes([79]) * 32,
}
_DIDS = {
    name: did_key_encode(ed25519_public_key(secret))
    for name, secret in _SECRETS.items()
    if name != "fence"
}


def _canonical(value) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _require(condition: bool, message: str) -> None:
    """Optimization-safe harness assertion; never stripped by ``python -O``."""

    if not condition:
        raise RuntimeError(f"production/L3 readiness harness red: {message}")


def _anchor(name: str, receipt_sha256: str, timestamp: str) -> dict:
    return build_temporal_anchor(
        _SECRETS[name], receipt_sha256, timestamp, _DIDS[name]
    )


def _binding(expected: dict) -> dict:
    return {
        "target_sha256": expected["target_sha256"],
        "operation_sha256": expected["operation_sha256"],
        "predeploy_file_sha256": expected["predeploy_file_sha256"],
    }


def _pg_role_attributes(*, login: bool) -> dict:
    return {
        "login": login,
        "superuser": False,
        "createdb": False,
        "createrole": False,
        "inherit": False,
        "bypassrls": False,
        "replication": False,
    }


def build_fixture_case() -> dict:
    """Deterministically build the source fixture; the suite consumes its frozen JSON."""

    prediction_sha = _sha("production-l3-fixture-prediction-receipt")
    verdict_sha = _sha("production-l3-fixture-verdict-receipt")
    operation_sha = _sha("production-l3-fixture-operation")
    target_sha = _sha("production-l3-fixture-target")
    predeploy_file_sha = _sha("production-l3-fixture-predeploy-file")
    predeploy_receipt_sha = _sha("production-l3-fixture-predeploy-receipt")
    drain_sha = _sha("production-l3-fixture-writer-drain")
    receipt_graph_sha = _sha("production-l3-fixture-receipt-graph")
    fence_public_key = ed25519_public_key(_SECRETS["fence"])
    fence_key_sha = hashlib.sha256(fence_public_key).hexdigest()
    policy = {
        "schema_version": AUTHORITY_POLICY_SCHEMA,
        "threshold": 2,
        "witness_allowlist": [
            _DIDS["w1"],
            _DIDS["w2"],
            _DIDS["w3"],
            _DIDS["w4"],
        ],
        "producer_dids": [_DIDS["producer"]],
        "attestor_dids": [_DIDS["attestor"]],
        "endpoint_signer_rule": "same-authority-set",
        "evidence_refs": ["fixture://authority-policy/exact-readback"],
    }
    sidecar = {
        "schema_version": SIDECAR_SCHEMA,
        "authority_policy_sha256": temporal_authority_policy_sha256(policy),
        "threshold": policy["threshold"],
        "witness_allowlist": list(policy["witness_allowlist"]),
        "prediction_receipt_sha256": prediction_sha,
        "verdict_receipt_sha256": verdict_sha,
        "receipt_graph_sha256": receipt_graph_sha,
        "prediction_anchors": [
            _anchor("w1", prediction_sha, "2026-08-02T01:00:00+00:00"),
            _anchor("w2", prediction_sha, "2026-08-02T01:00:03+00:00"),
        ],
        "verdict_anchors": [
            _anchor("w1", verdict_sha, "2026-08-02T01:01:00+00:00"),
            _anchor("w2", verdict_sha, "2026-08-02T01:01:04+00:00"),
        ],
    }
    sidecar_sha = temporal_sidecar_sha256(sidecar)
    expected = {
        "contract_id": STORAGE_CONTRACT_ID,
        "environment": "fixture",
        "operation_sha256": operation_sha,
        "target_sha256": target_sha,
        "predeploy_file_sha256": predeploy_file_sha,
        "predeploy_receipt_sha256": predeploy_receipt_sha,
        "fence_authority_key_sha256": fence_key_sha,
        "fence_nonce": "1" * 64,
        "writer_lease_id": "fixture-lease-1",
        "writer_drain_receipt_sha256": drain_sha,
        "postgresql_database": "fixture_pg",
        "neo4j_database": "fixture_neo",
        "prediction_receipt_sha256": prediction_sha,
        "verdict_receipt_sha256": verdict_sha,
        "temporal_sidecar_sha256": sidecar_sha,
        "receipt_graph_sha256": receipt_graph_sha,
        "evaluated_at": "2026-08-02T01:01:05+00:00",
    }
    fence_body = {
        "schema_version": FENCE_VERIFICATION_SCHEMA,
        "active": True,
        "nonce": expected["fence_nonce"],
        "environment": expected["environment"],
        "target_sha256": target_sha,
        "operation_sha256": operation_sha,
        "lease_id": expected["writer_lease_id"],
        "drain_receipt_sha256": drain_sha,
        "verified_at": "2026-08-02T01:00:50+00:00",
        "expires_at": "2026-08-02T01:01:20+00:00",
        "evidence_refs": ["fixture://writer-lease/exact-readback"],
    }
    fence_signature = ed25519_sign(
        _SECRETS["fence"], FENCE_SIGNATURE_DOMAIN + _canonical(fence_body)
    ).hex()
    pg_table_privileges = {
        name: ["INSERT", "SELECT"]
        for name in (
            "public.history",
            "public.history_event_claims",
            "public.metric_snapshots",
            "public.lineage",
        )
    }
    pg_sequence_privileges = {
        name: ["SELECT", "USAGE"]
        for name in (
            "public.history_id_seq",
            "public.metric_snapshots_id_seq",
            "public.lineage_id_seq",
        )
    }
    pg_object_owners = {
        name: "fixture_owner"
        for name in (
            *pg_table_privileges,
            *pg_sequence_privileges,
            "public",
        )
    }
    return {
        "schema_version": CASE_SCHEMA,
        "mode": "fixture",
        "expected": expected,
        "storage": {
            "predeploy": {
                "ok": True,
                "contract_id": STORAGE_CONTRACT_ID,
                "file_sha256": predeploy_file_sha,
                "receipt_sha256": predeploy_receipt_sha,
                "environment": expected["environment"],
                "created_at": "2026-08-02T01:00:52+00:00",
                "target_sha256": target_sha,
                "operation_sha256": operation_sha,
            },
            "writer_fence": {
                "authority_public_key_hex": fence_public_key.hex(),
                "authority_key_sha256": fence_key_sha,
                "nonce_reuse_count": 0,
                "listener_count": 0,
                "replica_count": 0,
                "writer_count": 0,
                "signed_response": {**fence_body, "signature": fence_signature},
            },
            "postgresql_access": {
                "schema_version": PG_ACCESS_SCHEMA,
                "binding": _binding(expected),
                "database": expected["postgresql_database"],
                "owner_role": "fixture_owner",
                "owner_can_login": False,
                "owner_role_attributes": _pg_role_attributes(login=False),
                "migrator_role": "fixture_migrator",
                "migrator_role_attributes": _pg_role_attributes(login=True),
                "runtime_role": "fixture_runtime",
                "predeploy_actor": "fixture_migrator",
                "startup_actor": "fixture_runtime",
                "runtime_role_attributes": _pg_role_attributes(login=True),
                "runtime_table_privileges": pg_table_privileges,
                "runtime_sequence_privileges": pg_sequence_privileges,
                "runtime_schema_privileges": {"public": ["USAGE"]},
                "runtime_owns_objects": False,
                "runtime_ddl": False,
                "object_owners": pg_object_owners,
                "public_grants": [],
                "role_memberships": [],
            },
            "neo4j_access": {
                "schema_version": NEO4J_ACCESS_SCHEMA,
                "binding": _binding(expected),
                "edition": "enterprise",
                "database": expected["neo4j_database"],
                "migrator_principal": "fixture_neo_migrator",
                "runtime_principal": "fixture_neo_runtime",
                "predeploy_actor": "fixture_neo_migrator",
                "startup_actor": "fixture_neo_runtime",
                "runtime_roles": ["fixture_lakatotree_runtime"],
                "migrator_roles": ["fixture_lakatotree_migrator"],
                "runtime_effective_privileges": ["ACCESS_DATABASE", "MATCH", "WRITE"],
                "migrator_effective_privileges": [
                    "ACCESS_DATABASE",
                    "CONSTRAINT_MANAGEMENT",
                    "MATCH",
                    "WRITE",
                ],
                "built_in_admin_roles": [],
                "public_role_bindings": [],
            },
            "runtime": {
                "schema_version": RUNTIME_SCHEMA,
                "binding": _binding(expected),
                "worker_count": 1,
                "readyz": True,
                "storage_authority_current": True,
                "writer_lease_current": True,
                "writer_lease_id": expected["writer_lease_id"],
                "migration_environment_keys": [],
                "pending_outbox": 0,
                "reconcile_conflicts": 0,
                "reconcile_replay_count": 0,
            },
        },
        "temporal": {
            "authority_policy": policy,
            "sidecar": sidecar,
            "runtime_binding": {
                "schema_version": TEMPORAL_BINDING_SCHEMA,
                "prediction_receipt_sha256": prediction_sha,
                "verdict_receipt_sha256": verdict_sha,
                "sidecar_sha256": sidecar_sha,
                "receipt_graph_sha256": receipt_graph_sha,
                "readback_ok": True,
            },
        },
    }


def fixture_case() -> dict:
    """Load the immutable suite fixture and verify every manifest pin.

    The builder exists to make review and regeneration deterministic, but the
    harness never silently falls back to it.  A missing or drifted frozen file is
    a red harness, not permission to manufacture new evidence at run time.
    """

    if not FIXTURE_PATH.is_file():
        raise AssertionError(f"locked fixture missing: {FIXTURE_PATH}")
    raw = FIXTURE_PATH.read_bytes()
    manifest = json.loads(HARNESS_PATH.read_text(encoding="utf-8"))
    fixture_contract = manifest["fixture"]
    _require(
        hashlib.sha256(raw).hexdigest() == fixture_contract["file_sha256"],
        "frozen fixture file SHA drift",
    )
    value = json.loads(raw)
    _require(
        hashlib.sha256(_canonical(value)).hexdigest()
        == fixture_contract["canonical_case_sha256"],
        "frozen fixture canonical SHA drift",
    )
    _require(value == build_fixture_case(), "frozen fixture differs from builder")
    return value


def _reseal_temporal(case: dict) -> None:
    policy = case["temporal"]["authority_policy"]
    sidecar = case["temporal"]["sidecar"]
    sidecar["authority_policy_sha256"] = temporal_authority_policy_sha256(policy)
    sidecar_sha = temporal_sidecar_sha256(sidecar)
    case["expected"]["temporal_sidecar_sha256"] = sidecar_sha
    case["temporal"]["runtime_binding"]["sidecar_sha256"] = sidecar_sha


def _reseal_fence(case: dict) -> None:
    response = case["storage"]["writer_fence"]["signed_response"]
    body = dict(response)
    body.pop("signature", None)
    response["signature"] = ed25519_sign(
        _SECRETS["fence"], FENCE_SIGNATURE_DOMAIN + _canonical(body)
    ).hex()


def _event(cid: str, name: str, **attrs) -> dict:
    return {
        "cid": cid,
        "correlation_id": cid,
        "cycle_id": cid,
        "service": "lakatos.production_l3_readiness",
        "event": name,
        **attrs,
    }


def _not_accepted(case: dict, required_failure: str | None = None) -> bool:
    before = copy.deepcopy(case)
    try:
        report = evaluate_readiness(case)
    except HarnessInputError:
        return required_failure is None and case == before
    if case != before or report.get("mutation_attempts") != 0:
        return False
    if required_failure is None:
        return False
    return _bounded_case_report(
        report,
        status="NOT_READY",
        mode="fixture",
        required_failure=required_failure,
    )


def _bounded_case_report(
    report: object,
    *,
    status: str,
    mode: str,
    required_failure: str,
    exact_failures: bool = False,
) -> bool:
    if not isinstance(report, dict):
        return False
    failures = report.get("failures")
    axes = report.get("axes")
    correct = axes.get("correct") if isinstance(axes, dict) else None
    digest = report.get("report_body_sha256")
    if (
        not isinstance(failures, list)
        or not all(isinstance(item, str) for item in failures)
        or not isinstance(correct, dict)
        or not isinstance(digest, str)
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
    ):
        return False
    body = dict(report)
    body.pop("report_body_sha256", None)
    try:
        digest_ok = hashlib.sha256(_canonical(body)).hexdigest() == digest
    except (TypeError, ValueError, RecursionError):
        return False
    failure_ok = (
        failures == [required_failure]
        if exact_failures
        else required_failure in failures
    )
    return (
        report.get("schema_version") == CASE_REPORT_SCHEMA
        and report.get("status") == status
        and report.get("harness_status") == "NOT_RUN"
        and report.get("deployment_status") == "NOT_READY"
        and report.get("production_ready") is False
        and report.get("l3_assurance") == "UNAVAILABLE"
        and report.get("mode") == mode
        and report.get("evidence_file_sha256") is None
        and report.get("evidence_bytes_bound") is False
        and type(report.get("mutation_attempts")) is int
        and report.get("mutation_attempts") == 0
        and correct.get("executed") is False
        and failure_ok
        and digest_ok
    )


def _verify_controls(
    controls: list[tuple[str, dict, str | None]],
    *,
    executed: list[str],
) -> None:
    """Execute each named negative control before recording its stable ID."""

    for control_id, case, required_failure in controls:
        _require(control_id not in executed, f"duplicate control ID: {control_id}")
        _require(
            _not_accepted(case, required_failure),
            f"negative control escaped: {control_id}",
        )
        executed.append(control_id)


def run_harness_suite() -> dict:
    """Run the locked positive and negative controls without external authority.

    This function is the sole source of ``HARNESS_GREEN``.  The case evaluator
    deliberately cannot emit that status.
    """

    manifest = json.loads(HARNESS_PATH.read_text(encoding="utf-8"))
    positive = fixture_case()
    fixture_file_sha256 = manifest["fixture"]["file_sha256"]
    loaded = load_evidence(FIXTURE_PATH.resolve(), fixture_file_sha256)
    _require(
        json.loads(loaded.raw) == positive,
        "loaded fixture differs from locked case",
    )
    report = evaluate_loaded_evidence(loaded)
    _require(report["status"] == "CASE_ACCEPTED", "positive case was not accepted")
    _require(report["harness_status"] == "NOT_RUN", "case claimed suite execution")
    _require(report["production_ready"] is False, "case claimed production readiness")
    _require(report["l3_assurance"] == "UNAVAILABLE", "case claimed runtime L3")
    _require(report["mutation_attempts"] == 0, "case reported mutation attempts")
    _require(report["storage"]["ok"] is True, "positive storage component failed")
    _require(
        report["temporal"]["component_ok"] is True,
        "positive temporal component failed",
    )
    _require(
        report["report_body_sha256"]
        == manifest["fixture"]["expected_case_report_body_sha256"],
        "positive case report digest drift",
    )
    events = ["locked_case_accepted_claim_bounded"]
    executed_controls: list[str] = []

    storage_controls = []
    changed = fixture_case()
    changed["storage"]["predeploy"]["file_sha256"] = "f" * 64
    storage_controls.append(
        ("storage.predeploy_file_pin", changed, "storage.predeploy.file_mismatch")
    )
    changed = fixture_case()
    changed["storage"]["predeploy"]["receipt_sha256"] = "f" * 64
    storage_controls.append(
        (
            "storage.predeploy_receipt_pin",
            changed,
            "storage.predeploy.receipt_mismatch",
        )
    )
    changed = fixture_case()
    changed["storage"]["writer_fence"]["authority_key_sha256"] = "e" * 64
    storage_controls.append(
        (
            "storage.fence_authority_self_binding",
            changed,
            "storage.fence.authority_key_self_mismatch",
        )
    )
    changed = fixture_case()
    changed["expected"]["fence_authority_key_sha256"] = "f" * 64
    storage_controls.append(
        (
            "storage.fence_authority_expected_pin",
            changed,
            "storage.fence.authority_key_pin_mismatch",
        )
    )
    changed = fixture_case()
    signature = changed["storage"]["writer_fence"]["signed_response"]["signature"]
    changed["storage"]["writer_fence"]["signed_response"]["signature"] = (
        ("0" if signature[0] != "0" else "1") + signature[1:]
    )
    storage_controls.append(
        ("storage.fence_signature", changed, "storage.fence.signature_invalid")
    )
    changed = fixture_case()
    changed["storage"]["writer_fence"]["writer_count"] = 1
    storage_controls.append(
        (
            "storage.fence_zero_writer_projection",
            changed,
            "storage.fence.writers_not_drained",
        )
    )
    changed = fixture_case()
    changed["storage"]["writer_fence"]["signed_response"][
        "verified_at"
    ] = "2026-08-02T01:00:20+00:00"
    _reseal_fence(changed)
    storage_controls.append(
        ("storage.fence_freshness", changed, "storage.fence.verification_too_old")
    )
    changed = fixture_case()
    changed["storage"]["writer_fence"]["signed_response"][
        "expires_at"
    ] = "2026-08-02T01:01:08+00:00"
    _reseal_fence(changed)
    storage_controls.append(
        (
            "storage.fence_expiry_margin",
            changed,
            "storage.fence.expiry_margin_too_small",
        )
    )
    changed = fixture_case()
    changed["storage"]["postgresql_access"]["binding"]["target_sha256"] = "e" * 64
    storage_controls.append(
        (
            "storage.postgresql_target_binding",
            changed,
            "storage.postgresql.target_mismatch",
        )
    )
    changed = fixture_case()
    changed["storage"]["postgresql_access"]["runtime_table_privileges"][
        "public.history"
    ].append("UPDATE")
    storage_controls.append(
        (
            "storage.postgresql_runtime_overprivilege",
            changed,
            "storage.postgresql.runtime_table_privileges",
        )
    )
    changed = fixture_case()
    changed["storage"]["postgresql_access"]["owner_role_attributes"][
        "superuser"
    ] = True
    storage_controls.append(
        (
            "storage.postgresql_owner_attributes",
            changed,
            "storage.postgresql.owner_role_attributes",
        )
    )
    changed = fixture_case()
    changed["storage"]["postgresql_access"]["migrator_role_attributes"][
        "createrole"
    ] = True
    storage_controls.append(
        (
            "storage.postgresql_migrator_attributes",
            changed,
            "storage.postgresql.migrator_role_attributes",
        )
    )
    changed = fixture_case()
    changed["storage"]["postgresql_access"]["object_owners"][
        "public.history"
    ] = "fixture_migrator"
    storage_controls.append(
        (
            "storage.postgresql_object_ownership",
            changed,
            "storage.postgresql.object_ownership",
        )
    )
    changed = fixture_case()
    changed["storage"]["neo4j_access"]["database"] = "spliced_database"
    storage_controls.append(
        (
            "storage.neo4j_database_binding",
            changed,
            "storage.neo4j.database_mismatch",
        )
    )
    changed = fixture_case()
    changed["storage"]["neo4j_access"]["runtime_effective_privileges"].append(
        "CONSTRAINT_MANAGEMENT"
    )
    storage_controls.append(
        (
            "storage.neo4j_runtime_overprivilege",
            changed,
            "storage.neo4j.runtime_privileges",
        )
    )
    changed = fixture_case()
    changed["storage"]["neo4j_access"]["runtime_roles"] = ["PUBLIC"]
    storage_controls.append(
        (
            "storage.neo4j_builtin_public_role",
            changed,
            "storage.neo4j.builtin_role_used",
        )
    )
    changed = fixture_case()
    changed["storage"]["runtime"]["migration_environment_keys"] = [
        "LAKATOS_STORAGE_PG_MIGRATION_PASSWORD"
    ]
    storage_controls.append(
        (
            "storage.runtime_migration_credentials",
            changed,
            "storage.runtime.migration_credentials_present",
        )
    )
    changed = fixture_case()
    changed["storage"]["runtime"]["writer_lease_id"] = "spliced-lease"
    storage_controls.append(
        (
            "storage.runtime_lease_binding",
            changed,
            "storage.runtime.writer_lease_mismatch",
        )
    )
    _verify_controls(storage_controls, executed=executed_controls)
    events.append("storage_authority_attacks_rejected")

    temporal_controls = []
    changed = fixture_case()
    anchor = changed["temporal"]["sidecar"]["verdict_anchors"][0]
    anchor["signature"] = ("0" if anchor["signature"][0] != "0" else "1") + anchor[
        "signature"
    ][1:]
    _reseal_temporal(changed)
    temporal_controls.append(
        ("temporal.verdict_signature", changed, "temporal.verdict_anchor_invalid")
    )
    changed = fixture_case()
    changed["temporal"]["sidecar"]["prediction_anchors"][1] = copy.deepcopy(
        changed["temporal"]["sidecar"]["prediction_anchors"][0]
    )
    _reseal_temporal(changed)
    temporal_controls.append(
        (
            "temporal.prediction_duplicate_authority",
            changed,
            "temporal.prediction_duplicate_authority",
        )
    )
    changed = fixture_case()
    changed["temporal"]["sidecar"]["verdict_anchors"][0]["channel"] = "server-clock"
    _reseal_temporal(changed)
    temporal_controls.append(
        ("temporal.anchor_channel", changed, "temporal.verdict_channel_invalid")
    )
    changed = fixture_case()
    changed["temporal"]["authority_policy"]["producer_dids"] = [
        changed["temporal"]["authority_policy"]["attestor_dids"][0]
    ]
    _reseal_temporal(changed)
    temporal_controls.append(
        (
            "temporal.producer_attestor_disjoint",
            changed,
            "temporal.producer_attestor_role_overlap",
        )
    )
    changed = fixture_case()
    changed["temporal"]["sidecar"]["authority_policy_sha256"] = "f" * 64
    temporal_controls.append(
        (
            "temporal.policy_digest_binding",
            changed,
            "temporal.authority_policy_sha_mismatch",
        )
    )
    _verify_controls(temporal_controls, executed=executed_controls)

    malformed = fixture_case()
    did = malformed["temporal"]["sidecar"]["prediction_anchors"][0]["witness_did"]
    malformed["temporal"]["sidecar"]["prediction_anchors"][1]["witness_did"] = f" {did} "
    _reseal_temporal(malformed)
    _verify_controls(
        [("temporal.noncanonical_witness_alias", malformed, None)],
        executed=executed_controls,
    )

    small_order = fixture_case()
    identity = bytes.fromhex("01" + "00" * 31)
    order_two = bytes.fromhex("ec" + "ff" * 30 + "7f")
    low_dids = [did_key_encode(identity), did_key_encode(order_two)]
    small_order["temporal"]["authority_policy"]["witness_allowlist"] = low_dids
    small_order["temporal"]["sidecar"]["witness_allowlist"] = low_dids
    for endpoint, receipt_field, timestamp in (
        ("prediction", "prediction_receipt_sha256", "2026-08-02T01:00:00+00:00"),
        ("verdict", "verdict_receipt_sha256", "2026-08-02T01:01:00+00:00"),
    ):
        receipt_sha = small_order["temporal"]["sidecar"][receipt_field]
        small_order["temporal"]["sidecar"][f"{endpoint}_anchors"] = [
            {
                "witness_did": low_did,
                "digest": anchor_digest(receipt_sha),
                "gen_time": timestamp,
                "signature": (identity + bytes(32)).hex(),
                "channel": "ed25519-witness",
            }
            for low_did in low_dids
        ]
    _reseal_temporal(small_order)
    _verify_controls(
        [("temporal.small_order_keys", small_order, None)],
        executed=executed_controls,
    )
    events.append("temporal_crypto_policy_attacks_rejected")

    relation_controls = []
    changed = fixture_case()
    verdict_sha = changed["temporal"]["sidecar"]["verdict_receipt_sha256"]
    changed["temporal"]["sidecar"]["verdict_anchors"] = [
        _anchor("w3", verdict_sha, "2026-08-02T01:01:00+00:00"),
        _anchor("w4", verdict_sha, "2026-08-02T01:01:04+00:00"),
    ]
    _reseal_temporal(changed)
    relation_controls.append(
        (
            "temporal.endpoint_signer_set",
            changed,
            "temporal.endpoint_authority_set_mismatch",
        )
    )
    changed = fixture_case()
    changed["temporal"]["sidecar"]["verdict_anchors"] = [
        _anchor("w1", verdict_sha, "2026-08-02T00:59:00+00:00"),
        _anchor("w2", verdict_sha, "2026-08-02T00:59:03+00:00"),
    ]
    _reseal_temporal(changed)
    relation_controls.append(
        (
            "temporal.all_anchor_ordering",
            changed,
            "temporal.all_anchor_ordering_not_strict",
        )
    )
    changed = fixture_case()
    changed["temporal"]["sidecar"]["verdict_anchors"] = [
        _anchor("w1", verdict_sha, "2026-08-02T01:01:06+00:00"),
        _anchor("w2", verdict_sha, "2026-08-02T01:01:07+00:00"),
    ]
    _reseal_temporal(changed)
    relation_controls.append(
        (
            "temporal.anchor_not_after_evaluation",
            changed,
            "temporal.anchor_after_evaluation",
        )
    )
    changed = fixture_case()
    changed["temporal"]["runtime_binding"]["verdict_receipt_sha256"] = "d" * 64
    relation_controls.append(
        (
            "temporal.runtime_head_binding",
            changed,
            "temporal.runtime_verdict_receipt_mismatch",
        )
    )
    _verify_controls(relation_controls, executed=executed_controls)
    events.append("temporal_relation_attacks_rejected")

    live = fixture_case()
    live["mode"] = "live"
    live_before = copy.deepcopy(live)
    unsupported = evaluate_readiness(live)
    _require(
        live == live_before
        and _bounded_case_report(
            unsupported,
            status="UNSUPPORTED",
            mode="live",
            required_failure="mode.live_adapter_not_implemented",
            exact_failures=True,
        ),
        "live mode did not fail closed with bounded claims",
    )
    executed_controls.append("live.adapter_fail_closed")
    events.append("live_authority_claim_fail_closed")

    declared_events = [
        item["event"] for item in manifest["suite"]["required_events"]
    ]
    _require(events == declared_events, "suite event declaration drift")
    _require(
        executed_controls == manifest["suite"]["required_controls"],
        "suite control declaration drift",
    )
    return {
        "schema_version": "lakatotree-production-l3-readiness-suite-report/v1",
        "status": "HARNESS_GREEN",
        "production_ready": False,
        "l3_assurance": "UNAVAILABLE",
        "fixture_file_sha256": fixture_file_sha256,
        "canonical_case_sha256": report["canonical_case_sha256"],
        "case_report_body_sha256": report["report_body_sha256"],
        "events": events,
        "controls": executed_controls,
    }


def verify(backend, cid):
    suite_report = run_harness_suite()
    _require(suite_report["status"] == "HARNESS_GREEN", "suite did not become green")
    for event_name in suite_report["events"]:
        backend.ship([_event(cid, event_name)])
