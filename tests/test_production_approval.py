"""Gate-5 review and separately signed approval receipt stay offline and exact."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib

from lakatos.write_cert import (
    did_key_encode,
    ed25519_public_key,
    ed25519_sign,
)
from server.contexts.tree.temporal_proof import TemporalProof
from server.production_approval import (
    APPROVAL_POLICY_SCHEMA,
    APPROVAL_RECEIPT_SCHEMA,
    APPROVAL_SCOPE,
    approval_policy_sha256,
    approval_receipt_signing_bytes,
    build_live_review,
    live_review_sha256,
    main,
    verify_external_approval,
)
from server.runtime_authority import VerifiedRuntimeSnapshot
from server.storage_access import (
    AccessPairProof,
    StorageAuditBundleProof,
    StorageAuditProof,
    canonical_json,
)


NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
_SECRETS = {
    name: bytes([value]) * 32
    for name, value in {
        "storage_pg": 71,
        "storage_neo": 72,
        "runtime": 73,
        "time": 74,
        "witness": 75,
        "approver": 76,
    }.items()
}
_DIDS = {
    name: did_key_encode(ed25519_public_key(secret))
    for name, secret in _SECRETS.items()
}


def _identity(name: str) -> str:
    return hashlib.sha256(_DIDS[name].encode("utf-8")).hexdigest()


def _bundle(phase: str) -> StorageAuditBundleProof:
    audit = StorageAuditProof(
        True, (), phase, "1" * 64, "2" * 64, "3" * 64, "4" * 64
    )
    return StorageAuditBundleProof(True, (), phase, audit, audit)


def _components(*, temporal_l3: bool = True):
    target = "a" * 64
    operation = "b" * 64
    artifact = "c" * 64
    policy_file = "d" * 64
    receipt_file = "e" * 64
    receipt = "f" * 64
    predeploy_bundle = "1" * 64
    startup_bundle = "2" * 64
    storage = AccessPairProof(
        "ACCESS_PAIR_VERIFIED",
        False,
        "NOT_READY",
        (),
        _bundle("predeploy"),
        _bundle("startup"),
        environment="production",
        target_sha256=target,
        operation_sha256=operation,
        artifact_identity_sha256=artifact,
        policy_file_sha256=policy_file,
        predeploy_receipt_file_sha256=receipt_file,
        predeploy_receipt_sha256=receipt,
        predeploy_bundle_file_sha256=predeploy_bundle,
        startup_bundle_file_sha256=startup_bundle,
        valid_until=(NOW + timedelta(minutes=3)).isoformat(),
        authority_identity_sha256s=(
            _identity("storage_neo"),
            _identity("storage_pg"),
        ),
    )
    runtime = VerifiedRuntimeSnapshot(
        canonical_response=b'{}',
        body_sha256="3" * 64,
        challenge_sha256="4" * 64,
        boot_id="5" * 64,
        artifact={"kind": "git", "source_commit": "6" * 40},
        artifact_identity_sha256=artifact,
        operation_sha256=operation,
        target_sha256=target,
        predeploy_receipt_file_sha256=receipt_file,
        predeploy_receipt_sha256=receipt,
        startup_bundle_file_sha256=startup_bundle,
        lease_id="critique-history-writer-v1",
        lease_owner_token_sha256="7" * 64,
        lease_generation=9,
        lease_postgresql_backend_pid=4242,
        lease_postgresql_advisory_key=(1279349588, 20260802),
        observed_at=(NOW - timedelta(seconds=1)).isoformat(),
        expires_at=(NOW + timedelta(minutes=2)).isoformat(),
        authority_did=_DIDS["runtime"],
        storage_access_policy_file_sha256=policy_file,
    )
    temporal = TemporalProof(
        component_ok=True,
        l3_eligible=temporal_l3,
        reason="independent_two_ended_temporal_verified",
        chain_ok=True,
        sidecar_sha256="8" * 64,
        authority_policy_sha256="9" * 64,
        receipt_graph_sha256="0" * 64,
        prediction_receipt_sha256="a" * 64,
        verdict_receipt_sha256="b" * 64,
        prediction_temporal_commitment_sha256="c" * 64,
        witness_dids=(_DIDS["witness"],),
        threshold=1,
        t1_latest=(NOW - timedelta(minutes=2)).isoformat(),
        t2_earliest=(NOW - timedelta(minutes=1)).isoformat(),
        independent_verifier="sha256:" + "d" * 64,
        time_authority="did-key-sha256:" + _identity("time"),
        independent_input_sha256="e" * 64,
        independent_valid_until=(NOW + timedelta(minutes=4)).isoformat(),
        authority_identity_sha256s=(
            _identity("time"),
            _identity("witness"),
        ),
    )
    return storage, runtime, temporal


def _review():
    storage, runtime, temporal = _components()
    return build_live_review(
        storage=storage,
        runtime=runtime,
        temporal=temporal,
        evaluated_at=NOW,
    )


def _policy(*, approver="approver"):
    return {
        "schema_version": APPROVAL_POLICY_SCHEMA,
        "environment": "production",
        "approval_scope": APPROVAL_SCOPE,
        "target_sha256": "a" * 64,
        "approver_did": _DIDS[approver],
        "max_lifetime_seconds": 60,
    }


def _receipt(review, policy, *, signer="approver", mutate=None):
    body = {
        "schema_version": APPROVAL_RECEIPT_SCHEMA,
        "approval_policy_sha256": approval_policy_sha256(policy),
        "live_review_sha256": live_review_sha256(review),
        "environment": "production",
        "approval_scope": APPROVAL_SCOPE,
        "target_sha256": review["target_sha256"],
        "operation_sha256": review["operation_sha256"],
        "artifact_identity_sha256": review["artifact_identity_sha256"],
        "nonce": "3" * 64,
        "approved_at": (NOW + timedelta(seconds=1)).isoformat(),
        "valid_until": (NOW + timedelta(seconds=30)).isoformat(),
        "signer_did": _DIDS[signer],
    }
    if mutate:
        mutate(body)
    receipt = {**body, "signature": ""}
    receipt["signature"] = ed25519_sign(
        _SECRETS[signer], approval_receipt_signing_bytes(receipt)
    ).hex()
    return receipt


def _verify(review, policy, receipt=None):
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


def test_verified_components_without_external_receipt_remain_exactly_not_ready():
    report = _verify(_review(), _policy())

    assert report["status"] == "NOT_READY"
    assert report["review_status"] == "REVIEW_VERIFIED_AWAITING_APPROVAL"
    assert report["production_ready"] is False
    assert report["deployment_status"] == "NOT_READY"
    assert report["l3_assurance"] == "PER_PROOF"
    assert report["approval_applied"] is False
    assert report["failures"] == ["approval.receipt_missing"]


def test_separately_signed_receipt_verifies_but_never_applies_deployment():
    review = _review()
    policy = _policy()
    report = _verify(review, policy, _receipt(review, policy))

    assert report["status"] == "APPROVAL_RECEIPT_VERIFIED"
    assert report["production_ready"] is True
    assert report["deployment_status"] == "APPROVED_NOT_APPLIED"
    assert report["approval_applied"] is False


def test_signature_and_cross_binding_splices_fail_closed():
    review = _review()
    policy = _policy()
    mutations = (
        lambda body: body.__setitem__("live_review_sha256", "0" * 64),
        lambda body: body.__setitem__("operation_sha256", "0" * 64),
        lambda body: body.__setitem__("approval_scope", "fixture-harness/v1"),
        lambda body: body.__setitem__(
            "valid_until", (NOW + timedelta(minutes=5)).isoformat()
        ),
    )

    for mutation in mutations:
        report = _verify(review, policy, _receipt(review, policy, mutate=mutation))
        assert report["status"] == "NOT_READY"
        assert report["production_ready"] is False

    tampered = _receipt(review, policy)
    tampered["signature"] = "0" * 128
    assert _verify(review, policy, tampered)["status"] == "NOT_READY"


def test_approver_must_be_distinct_from_every_component_authority():
    review = _review()
    policy = _policy(approver="runtime")
    receipt = _receipt(review, policy, signer="runtime")

    report = _verify(review, policy, receipt)

    assert report["status"] == "NOT_READY"
    assert report["production_ready"] is False


def test_live_review_rejects_non_l3_stale_or_cross_component_splices():
    storage, runtime, temporal = _components(temporal_l3=False)
    for changed_storage, changed_runtime, changed_temporal in (
        (storage, runtime, temporal),
        (
            storage,
            replace(runtime, operation_sha256="0" * 64),
            replace(temporal, l3_eligible=True),
        ),
        (
            replace(storage, valid_until=(NOW - timedelta(seconds=1)).isoformat()),
            runtime,
            replace(temporal, l3_eligible=True),
        ),
    ):
        try:
            build_live_review(
                storage=changed_storage,
                runtime=changed_runtime,
                temporal=changed_temporal,
                evaluated_at=NOW,
            )
        except ValueError:
            rejected = True
        else:
            rejected = False
        assert rejected is True


def test_unknown_or_noncanonical_review_cannot_become_ready():
    review = _review()
    policy = _policy()
    review_raw = b" " + canonical_json(review)
    policy_raw = canonical_json(policy)

    report = verify_external_approval(
        review_raw=review_raw,
        expected_review_file_sha256=hashlib.sha256(review_raw).hexdigest(),
        policy_raw=policy_raw,
        expected_policy_file_sha256=hashlib.sha256(policy_raw).hexdigest(),
        receipt_raw=None,
        expected_receipt_file_sha256=None,
        evaluated_at=NOW,
    )

    assert report["status"] == "NOT_READY"
    review["production_ready"] = True
    assert _verify(review, policy)["status"] == "NOT_READY"


def test_verifier_cli_without_receipt_returns_sanitized_not_ready(
    tmp_path, capsys
):
    review_raw = canonical_json(_review())
    policy_raw = canonical_json(_policy())
    review_path = (tmp_path / "review.json").resolve()
    policy_path = (tmp_path / "policy.json").resolve()
    review_path.write_bytes(review_raw)
    policy_path.write_bytes(policy_raw)
    review_path.chmod(0o400)
    policy_path.chmod(0o400)

    code = main([
        "--review", str(review_path),
        "--review-sha256", hashlib.sha256(review_raw).hexdigest(),
        "--policy", str(policy_path),
        "--policy-sha256", hashlib.sha256(policy_raw).hexdigest(),
        "--evaluated-at", (NOW + timedelta(seconds=2)).isoformat(),
    ])

    report = __import__("json").loads(capsys.readouterr().out)
    assert code == 1
    assert report["status"] == "NOT_READY"
    assert report["approval_applied"] is False
    assert "signature" not in report
    assert "approver_did" not in report
