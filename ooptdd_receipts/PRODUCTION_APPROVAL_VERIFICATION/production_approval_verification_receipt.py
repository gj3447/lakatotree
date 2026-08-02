"""OOPTDD receipt for the offline Gate-5 external-approval boundary."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lakatos.write_cert import (  # noqa: E402
    did_key_encode,
    ed25519_public_key,
    ed25519_sign,
)
from server.contexts.tree.temporal_proof import TemporalProof  # noqa: E402
from server.production_approval import (  # noqa: E402
    APPROVAL_POLICY_SCHEMA,
    APPROVAL_RECEIPT_SCHEMA,
    APPROVAL_SCOPE,
    ProductionApprovalError,
    approval_policy_sha256,
    approval_receipt_signing_bytes,
    build_live_review,
    live_review_sha256,
    verify_external_approval,
)
from server.runtime_authority import VerifiedRuntimeSnapshot  # noqa: E402
from server.storage_access import (  # noqa: E402
    AccessPairProof,
    StorageAuditBundleProof,
    StorageAuditProof,
    canonical_json,
)


NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
_SECRETS = {
    name: bytes([value]) * 32
    for name, value in {
        "runtime": 81,
        "time": 82,
        "approver": 83,
    }.items()
}
_DIDS = {
    name: did_key_encode(ed25519_public_key(secret))
    for name, secret in _SECRETS.items()
}


def _require(condition: bool, message) -> None:
    if not condition:
        raise RuntimeError(f"production approval harness red: {message}")


def _event(cid: str, name: str) -> dict:
    return {
        "cid": cid,
        "correlation_id": cid,
        "cycle_id": cid,
        "service": "lakatotree.production_approval",
        "event": name,
    }


def _identity(did: str) -> str:
    return hashlib.sha256(did.encode("utf-8")).hexdigest()


def _bundle(phase: str) -> StorageAuditBundleProof:
    audit = StorageAuditProof(
        True, (), phase, "1" * 64, "2" * 64, "3" * 64, "4" * 64
    )
    return StorageAuditBundleProof(True, (), phase, audit, audit)


def _components():
    storage = AccessPairProof(
        "ACCESS_PAIR_VERIFIED",
        False,
        "NOT_READY",
        (),
        _bundle("predeploy"),
        _bundle("startup"),
        environment="production",
        target_sha256="a" * 64,
        operation_sha256="b" * 64,
        artifact_identity_sha256="c" * 64,
        policy_file_sha256="d" * 64,
        predeploy_receipt_file_sha256="e" * 64,
        predeploy_receipt_sha256="f" * 64,
        predeploy_bundle_file_sha256="1" * 64,
        startup_bundle_file_sha256="2" * 64,
        valid_until=(NOW + timedelta(minutes=3)).isoformat(),
        authority_identity_sha256s=("3" * 64, "4" * 64),
    )
    runtime = VerifiedRuntimeSnapshot(
        canonical_response=b"{}",
        body_sha256="5" * 64,
        challenge_sha256="6" * 64,
        boot_id="7" * 64,
        artifact={"kind": "git", "source_commit": "8" * 40},
        artifact_identity_sha256="c" * 64,
        operation_sha256="b" * 64,
        target_sha256="a" * 64,
        predeploy_receipt_file_sha256="e" * 64,
        predeploy_receipt_sha256="f" * 64,
        startup_bundle_file_sha256="2" * 64,
        lease_id="critique-history-writer-v1",
        lease_owner_token_sha256="9" * 64,
        lease_generation=1,
        lease_postgresql_backend_pid=4242,
        lease_postgresql_advisory_key=(1279349588, 20260802),
        observed_at=(NOW - timedelta(seconds=1)).isoformat(),
        expires_at=(NOW + timedelta(minutes=2)).isoformat(),
        authority_did=_DIDS["runtime"],
        storage_access_policy_file_sha256="d" * 64,
    )
    time_identity = _identity(_DIDS["time"])
    temporal = TemporalProof(
        component_ok=True,
        l3_eligible=True,
        reason="independent_two_ended_temporal_verified",
        chain_ok=True,
        sidecar_sha256="a" * 64,
        authority_policy_sha256="b" * 64,
        receipt_graph_sha256="c" * 64,
        prediction_receipt_sha256="d" * 64,
        verdict_receipt_sha256="e" * 64,
        prediction_temporal_commitment_sha256="f" * 64,
        independent_verifier="sha256:" + "1" * 64,
        time_authority="did-key-sha256:" + time_identity,
        independent_input_sha256="2" * 64,
        independent_valid_until=(NOW + timedelta(minutes=4)).isoformat(),
        authority_identity_sha256s=(time_identity, "6" * 64),
    )
    return storage, runtime, temporal


def _policy(*, runtime_as_approver: bool = False) -> dict:
    return {
        "schema_version": APPROVAL_POLICY_SCHEMA,
        "environment": "production",
        "approval_scope": APPROVAL_SCOPE,
        "target_sha256": "a" * 64,
        "approver_did": _DIDS["runtime" if runtime_as_approver else "approver"],
        "max_lifetime_seconds": 60,
    }


def _receipt(review, policy, *, signer="approver", mutate=None) -> dict:
    body = {
        "schema_version": APPROVAL_RECEIPT_SCHEMA,
        "approval_policy_sha256": approval_policy_sha256(policy),
        "live_review_sha256": live_review_sha256(review),
        "environment": "production",
        "approval_scope": APPROVAL_SCOPE,
        "target_sha256": review["target_sha256"],
        "operation_sha256": review["operation_sha256"],
        "artifact_identity_sha256": review["artifact_identity_sha256"],
        "nonce": "7" * 64,
        "approved_at": (NOW + timedelta(seconds=1)).isoformat(),
        "valid_until": (NOW + timedelta(seconds=30)).isoformat(),
        "signer_did": _DIDS[signer],
    }
    if mutate is not None:
        mutate(body)
    receipt = {**body, "signature": ""}
    receipt["signature"] = ed25519_sign(
        _SECRETS[signer], approval_receipt_signing_bytes(receipt)
    ).hex()
    return receipt


def _verify(review, policy, receipt=None) -> dict:
    review_raw = canonical_json(review)
    policy_raw = canonical_json(policy)
    receipt_raw = canonical_json(receipt) if receipt is not None else None
    return verify_external_approval(
        review_raw=review_raw,
        expected_review_file_sha256=hashlib.sha256(review_raw).hexdigest(),
        policy_raw=policy_raw,
        expected_policy_file_sha256=hashlib.sha256(policy_raw).hexdigest(),
        receipt_raw=receipt_raw,
        expected_receipt_file_sha256=(
            hashlib.sha256(receipt_raw).hexdigest() if receipt_raw else None
        ),
        evaluated_at=NOW + timedelta(seconds=2),
    )


def verify(backend, cid):
    manifest = json.loads(
        Path(__file__).with_name("harness.json").read_text(encoding="utf-8")
    )
    required = set(manifest["required_controls"])
    executed: set[str] = set()

    def control(name: str, condition: bool, message) -> None:
        _require(name in required, f"undeclared control: {name}")
        _require(name not in executed, f"duplicate control: {name}")
        _require(condition, message)
        executed.add(name)

    storage, runtime, temporal = _components()
    review = build_live_review(
        storage=storage,
        runtime=runtime,
        temporal=temporal,
        evaluated_at=NOW,
    )
    control(
        "review.components_exact",
        review["target_sha256"] == storage.target_sha256
        and review["runtime"]["body_sha256"] == runtime.body_sha256
        and review["temporal"]["verdict_receipt_sha256"]
        == temporal.verdict_receipt_sha256,
        review,
    )
    try:
        build_live_review(
            storage=storage,
            runtime=replace(runtime, target_sha256="0" * 64),
            temporal=temporal,
            evaluated_at=NOW,
        )
    except ProductionApprovalError:
        component_splice_rejected = True
    else:
        component_splice_rejected = False
    control(
        "review.component_splice",
        component_splice_rejected,
        "cross-component target splice accepted",
    )
    backend.ship([_event(cid, "live_review_components_exactly_bound")])

    policy = _policy()
    missing = _verify(review, policy)
    control(
        "approval.missing_receipt",
        missing["status"] == "NOT_READY"
        and missing["production_ready"] is False
        and missing["failures"] == ["approval.receipt_missing"],
        missing,
    )
    backend.ship([_event(cid, "missing_external_approval_fail_closed")])

    honest_receipt = _receipt(review, policy)
    verified = _verify(review, policy, honest_receipt)
    tampered = dict(honest_receipt)
    tampered["signature"] = "0" * 128
    control(
        "approval.signature_splice",
        _verify(review, policy, tampered)["status"] == "NOT_READY",
        "signature splice accepted",
    )
    bound_splice = _receipt(
        review,
        policy,
        mutate=lambda body: body.__setitem__("live_review_sha256", "0" * 64),
    )
    control(
        "approval.review_binding_splice",
        _verify(review, policy, bound_splice)["status"] == "NOT_READY",
        "review binding splice accepted",
    )
    overlap_policy = _policy(runtime_as_approver=True)
    overlap_receipt = _receipt(
        review, overlap_policy, signer="runtime"
    )
    control(
        "approval.role_overlap",
        _verify(review, overlap_policy, overlap_receipt)["status"] == "NOT_READY",
        "component authority self-approved deployment",
    )
    backend.ship([_event(cid, "approval_signature_and_splices_rejected")])

    control(
        "claim.never_applied",
        verified["status"] == "APPROVAL_RECEIPT_VERIFIED"
        and verified["deployment_status"] == "APPROVED_NOT_APPLIED"
        and verified["approval_applied"] is False
        and verified["l3_assurance"] == "PER_PROOF",
        verified,
    )
    backend.ship([_event(cid, "approval_verifier_never_applies_deployment")])

    control(
        "manifest.exact_control_set",
        executed | {"manifest.exact_control_set"} == required,
        {"missing": sorted(required - executed), "unexpected": sorted(executed - required)},
    )
    _require(executed == required, "executed control manifest drift")
