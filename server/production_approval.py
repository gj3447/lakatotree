"""Offline Gate-5 live-review and external deployment-approval verifier.

This module can assemble a canonical review from already verified Gate 1, Gate
2 and per-proof Gate 4 objects, then verify a separately administered approval
receipt.  It never signs, deploys, restarts, refreshes authority, connects to a
datastore, or mutates application state.  A verified receipt means approved but
not applied; it is deliberately not wired into ``/readyz``.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
from pathlib import Path
import stat
import sys
from typing import Any, Mapping, Sequence

from lakatos.write_cert import (
    CertError,
    did_key_decode,
    did_key_encode,
    ed25519_public_key_is_strict,
    ed25519_verify,
)
from server.contexts.tree.temporal_proof import TemporalProof
from server.runtime_authority import VerifiedRuntimeSnapshot
from server.storage_access import (
    AccessPairProof,
    MAX_DOCUMENT_BYTES,
    canonical_json,
    strict_json_loads,
)


LIVE_REVIEW_SCHEMA = "lakatotree-production-live-review/v1"
APPROVAL_POLICY_SCHEMA = "lakatotree-production-approval-policy/v1"
APPROVAL_RECEIPT_SCHEMA = "lakatotree-production-approval-receipt/v1"
APPROVAL_REPORT_SCHEMA = "lakatotree-production-approval-report/v1"
APPROVAL_SCOPE = "exact-production-deployment/v1"

LIVE_REVIEW_DOMAIN = b"lakatotree-production-live-review/v1\0"
APPROVAL_POLICY_DOMAIN = b"lakatotree-production-approval-policy/v1\0"
APPROVAL_RECEIPT_DOMAIN = b"lakatotree-production-approval-receipt/v1\0"
MAX_APPROVAL_LIFETIME_SECONDS = 300

_HEX = frozenset("0123456789abcdef")
_LIVE_REVIEW_KEYS = frozenset({
    "schema_version",
    "environment",
    "target_sha256",
    "operation_sha256",
    "artifact_identity_sha256",
    "evaluated_at",
    "valid_until",
    "storage",
    "runtime",
    "temporal",
    "authority_identity_sha256s",
})
_STORAGE_KEYS = frozenset({
    "policy_file_sha256",
    "predeploy_receipt_file_sha256",
    "predeploy_receipt_sha256",
    "predeploy_bundle_file_sha256",
    "startup_bundle_file_sha256",
    "valid_until",
})
_RUNTIME_KEYS = frozenset({
    "body_sha256",
    "challenge_sha256",
    "boot_id_sha256",
    "runtime_lease_id_sha256",
    "runtime_lease_generation",
    "startup_bundle_file_sha256",
    "authority_identity_sha256",
    "expires_at",
})
_TEMPORAL_KEYS = frozenset({
    "independent_input_sha256",
    "sidecar_sha256",
    "authority_policy_sha256",
    "receipt_graph_sha256",
    "prediction_receipt_sha256",
    "verdict_receipt_sha256",
    "prediction_temporal_commitment_sha256",
    "independent_verifier",
    "time_authority",
    "valid_until",
})
_POLICY_KEYS = frozenset({
    "schema_version",
    "environment",
    "approval_scope",
    "target_sha256",
    "approver_did",
    "max_lifetime_seconds",
})
_RECEIPT_BODY_KEYS = frozenset({
    "schema_version",
    "approval_policy_sha256",
    "live_review_sha256",
    "environment",
    "approval_scope",
    "target_sha256",
    "operation_sha256",
    "artifact_identity_sha256",
    "nonce",
    "approved_at",
    "valid_until",
    "signer_did",
})


class ProductionApprovalError(ValueError):
    """The live review or approval receipt is malformed, stale, or spliced."""


def _mapping(value: Any, *, keys: frozenset[str], path: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ProductionApprovalError(f"{path}.field_set")
    return dict(value)


def _sha(value: Any, *, path: str) -> str:
    if not (
        isinstance(value, str)
        and len(value) == 64
        and all(char in _HEX for char in value)
    ):
        raise ProductionApprovalError(f"{path}.sha256")
    return value


def _time(value: Any, *, path: str) -> datetime:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise ProductionApprovalError(f"{path}.timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError, OverflowError) as exc:
        raise ProductionApprovalError(f"{path}.timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProductionApprovalError(f"{path}.timezone")
    return parsed.astimezone(timezone.utc)


def _did(value: Any, *, path: str) -> tuple[str, bytes]:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ProductionApprovalError(f"{path}.did")
    try:
        public = did_key_decode(value)
    except (CertError, ValueError, TypeError, AttributeError) as exc:
        raise ProductionApprovalError(f"{path}.did") from exc
    if did_key_encode(public) != value or not ed25519_public_key_is_strict(public):
        raise ProductionApprovalError(f"{path}.did")
    return value, public


def _identity_sha(did: str) -> str:
    return hashlib.sha256(did.encode("utf-8")).hexdigest()


def live_review_sha256(review: Mapping[str, Any]) -> str:
    return hashlib.sha256(LIVE_REVIEW_DOMAIN + canonical_json(dict(review))).hexdigest()


def approval_policy_sha256(policy: Mapping[str, Any]) -> str:
    return hashlib.sha256(APPROVAL_POLICY_DOMAIN + canonical_json(dict(policy))).hexdigest()


def approval_receipt_signing_bytes(receipt: Mapping[str, Any]) -> bytes:
    body = dict(receipt)
    body.pop("signature", None)
    _mapping(body, keys=_RECEIPT_BODY_KEYS, path="approval_receipt.body")
    return APPROVAL_RECEIPT_DOMAIN + canonical_json(body)


def _validated_review(value: Any) -> dict[str, Any]:
    review = _mapping(value, keys=_LIVE_REVIEW_KEYS, path="live_review")
    if review["schema_version"] != LIVE_REVIEW_SCHEMA:
        raise ProductionApprovalError("live_review.schema")
    if review["environment"] != "production":
        raise ProductionApprovalError("live_review.environment")
    for field in ("target_sha256", "operation_sha256", "artifact_identity_sha256"):
        _sha(review[field], path=f"live_review.{field}")
    evaluated_at = _time(review["evaluated_at"], path="live_review.evaluated_at")
    valid_until = _time(review["valid_until"], path="live_review.valid_until")
    storage = _mapping(review["storage"], keys=_STORAGE_KEYS, path="live_review.storage")
    runtime = _mapping(review["runtime"], keys=_RUNTIME_KEYS, path="live_review.runtime")
    temporal = _mapping(review["temporal"], keys=_TEMPORAL_KEYS, path="live_review.temporal")
    for field in _STORAGE_KEYS - {"valid_until"}:
        _sha(storage[field], path=f"live_review.storage.{field}")
    for field in _RUNTIME_KEYS - {"runtime_lease_generation", "expires_at"}:
        _sha(runtime[field], path=f"live_review.runtime.{field}")
    if type(runtime["runtime_lease_generation"]) is not int or runtime[
        "runtime_lease_generation"
    ] < 1:
        raise ProductionApprovalError("live_review.runtime.lease_generation")
    for field in _TEMPORAL_KEYS - {
        "independent_verifier", "time_authority", "valid_until"
    }:
        _sha(temporal[field], path=f"live_review.temporal.{field}")
    if not (
        isinstance(temporal["independent_verifier"], str)
        and temporal["independent_verifier"].startswith("sha256:")
        and _sha(
            temporal["independent_verifier"][7:],
            path="live_review.temporal.independent_verifier",
        )
        and isinstance(temporal["time_authority"], str)
        and temporal["time_authority"].startswith("did-key-sha256:")
        and _sha(
            temporal["time_authority"][15:],
            path="live_review.temporal.time_authority",
        )
    ):
        raise ProductionApprovalError("live_review.temporal.authority_identity")
    authority_ids = review["authority_identity_sha256s"]
    if not (
        isinstance(authority_ids, list)
        and authority_ids
        and all(_sha(item, path="live_review.authority_identity") for item in authority_ids)
        and authority_ids == sorted(authority_ids)
        and len(authority_ids) == len(set(authority_ids))
        and runtime["authority_identity_sha256"] in authority_ids
        and temporal["time_authority"][15:] in authority_ids
    ):
        raise ProductionApprovalError("live_review.authority_identity_set")
    component_expiries = (
        _time(storage["valid_until"], path="live_review.storage.valid_until"),
        _time(runtime["expires_at"], path="live_review.runtime.expires_at"),
        _time(temporal["valid_until"], path="live_review.temporal.valid_until"),
    )
    if not (
        evaluated_at < valid_until
        and valid_until == min(component_expiries)
    ):
        raise ProductionApprovalError("live_review.validity_intersection")
    return review


def build_live_review(
    *,
    storage: AccessPairProof,
    runtime: VerifiedRuntimeSnapshot,
    temporal: TemporalProof,
    evaluated_at: datetime,
) -> dict[str, Any]:
    """Build one exact cross-component review; no approval is inferred."""

    if not isinstance(storage, AccessPairProof):
        raise ProductionApprovalError("storage.proof_type")
    if not isinstance(runtime, VerifiedRuntimeSnapshot):
        raise ProductionApprovalError("runtime.proof_type")
    if not isinstance(temporal, TemporalProof):
        raise ProductionApprovalError("temporal.proof_type")
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ProductionApprovalError("live_review.evaluation_time")
    now = evaluated_at.astimezone(timezone.utc)
    storage_values = (
        storage.target_sha256,
        storage.operation_sha256,
        storage.artifact_identity_sha256,
        storage.policy_file_sha256,
        storage.predeploy_receipt_file_sha256,
        storage.predeploy_receipt_sha256,
        storage.predeploy_bundle_file_sha256,
        storage.startup_bundle_file_sha256,
    )
    temporal_values = (
        temporal.independent_input_sha256,
        temporal.sidecar_sha256,
        temporal.authority_policy_sha256,
        temporal.receipt_graph_sha256,
        temporal.prediction_receipt_sha256,
        temporal.verdict_receipt_sha256,
        temporal.prediction_temporal_commitment_sha256,
    )
    if not (
        storage.status == "ACCESS_PAIR_VERIFIED"
        and storage.production_ready is False
        and storage.deployment_status == "NOT_READY"
        and not storage.failures
        and storage.environment == "production"
        and all(_sha(value, path="storage.binding") for value in storage_values)
        and storage.valid_until
    ):
        raise ProductionApprovalError("storage.not_verified")
    if not (
        temporal.component_ok is True
        and temporal.chain_ok is True
        and temporal.l3_eligible is True
        and all(_sha(value, path="temporal.binding") for value in temporal_values)
        and isinstance(temporal.independent_verifier, str)
        and isinstance(temporal.time_authority, str)
        and temporal.independent_valid_until
        and temporal.authority_identity_sha256s
    ):
        raise ProductionApprovalError("temporal.not_l3")
    if not runtime.authority_did or not runtime.storage_access_policy_file_sha256:
        raise ProductionApprovalError("runtime.authority_identity_missing")
    runtime_authority_did, _public = _did(
        runtime.authority_did, path="runtime.authority_did"
    )
    if not (
        storage.target_sha256 == runtime.target_sha256
        and storage.operation_sha256 == runtime.operation_sha256
        and storage.artifact_identity_sha256 == runtime.artifact_identity_sha256
        and storage.policy_file_sha256
        == runtime.storage_access_policy_file_sha256
        and storage.predeploy_receipt_file_sha256
        == runtime.predeploy_receipt_file_sha256
        and storage.predeploy_receipt_sha256 == runtime.predeploy_receipt_sha256
        and storage.startup_bundle_file_sha256
        == runtime.startup_bundle_file_sha256
    ):
        raise ProductionApprovalError("live_review.component_binding_splice")
    expiries = (
        _time(storage.valid_until, path="storage.valid_until"),
        _time(runtime.expires_at, path="runtime.expires_at"),
        _time(temporal.independent_valid_until, path="temporal.valid_until"),
    )
    valid_until = min(expiries)
    if not now < valid_until:
        raise ProductionApprovalError("live_review.component_expired")
    authority_ids = tuple(sorted({
        *storage.authority_identity_sha256s,
        _identity_sha(runtime_authority_did),
        *temporal.authority_identity_sha256s,
    }))
    if not authority_ids:
        raise ProductionApprovalError("live_review.authority_identity_set")
    review = {
        "schema_version": LIVE_REVIEW_SCHEMA,
        "environment": "production",
        "target_sha256": storage.target_sha256,
        "operation_sha256": storage.operation_sha256,
        "artifact_identity_sha256": storage.artifact_identity_sha256,
        "evaluated_at": now.isoformat(),
        "valid_until": valid_until.isoformat(),
        "storage": {
            "policy_file_sha256": storage.policy_file_sha256,
            "predeploy_receipt_file_sha256": storage.predeploy_receipt_file_sha256,
            "predeploy_receipt_sha256": storage.predeploy_receipt_sha256,
            "predeploy_bundle_file_sha256": storage.predeploy_bundle_file_sha256,
            "startup_bundle_file_sha256": storage.startup_bundle_file_sha256,
            "valid_until": storage.valid_until,
        },
        "runtime": {
            "body_sha256": runtime.body_sha256,
            "challenge_sha256": runtime.challenge_sha256,
            "boot_id_sha256": hashlib.sha256(runtime.boot_id.encode("utf-8")).hexdigest(),
            "runtime_lease_id_sha256": hashlib.sha256(
                runtime.lease_id.encode("utf-8")
            ).hexdigest(),
            "runtime_lease_generation": runtime.lease_generation,
            "startup_bundle_file_sha256": runtime.startup_bundle_file_sha256,
            "authority_identity_sha256": _identity_sha(runtime_authority_did),
            "expires_at": runtime.expires_at,
        },
        "temporal": {
            "independent_input_sha256": temporal.independent_input_sha256,
            "sidecar_sha256": temporal.sidecar_sha256,
            "authority_policy_sha256": temporal.authority_policy_sha256,
            "receipt_graph_sha256": temporal.receipt_graph_sha256,
            "prediction_receipt_sha256": temporal.prediction_receipt_sha256,
            "verdict_receipt_sha256": temporal.verdict_receipt_sha256,
            "prediction_temporal_commitment_sha256": (
                temporal.prediction_temporal_commitment_sha256
            ),
            "independent_verifier": temporal.independent_verifier,
            "time_authority": temporal.time_authority,
            "valid_until": temporal.independent_valid_until,
        },
        "authority_identity_sha256s": list(authority_ids),
    }
    return _validated_review(review)


def _validated_policy(value: Any) -> dict[str, Any]:
    policy = _mapping(value, keys=_POLICY_KEYS, path="approval_policy")
    if not (
        policy["schema_version"] == APPROVAL_POLICY_SCHEMA
        and policy["environment"] == "production"
        and policy["approval_scope"] == APPROVAL_SCOPE
    ):
        raise ProductionApprovalError("approval_policy.scope")
    _sha(policy["target_sha256"], path="approval_policy.target_sha256")
    _did(policy["approver_did"], path="approval_policy.approver_did")
    lifetime = policy["max_lifetime_seconds"]
    if type(lifetime) is not int or not 1 <= lifetime <= MAX_APPROVAL_LIFETIME_SECONDS:
        raise ProductionApprovalError("approval_policy.max_lifetime")
    return policy


def _not_ready(
    *failures: str,
    review_sha256: str | None = None,
    policy_sha256: str | None = None,
    review_status: str = "REVIEW_UNVERIFIED",
) -> dict[str, Any]:
    return {
        "schema_version": APPROVAL_REPORT_SCHEMA,
        "status": "NOT_READY",
        "review_status": review_status,
        "production_ready": False,
        "deployment_status": "NOT_READY",
        "l3_assurance": "PER_PROOF" if review_sha256 else "UNAVAILABLE",
        "approval_applied": False,
        "live_review_sha256": review_sha256,
        "approval_policy_sha256": policy_sha256,
        "failures": sorted(set(failures)) or ["approval.unverified"],
    }


def verify_external_approval(
    *,
    review_raw: bytes,
    expected_review_file_sha256: str,
    policy_raw: bytes,
    expected_policy_file_sha256: str,
    receipt_raw: bytes | None,
    expected_receipt_file_sha256: str | None,
    evaluated_at: datetime,
) -> dict[str, Any]:
    """Verify exact pinned evidence; never apply the approved deployment."""

    try:
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise ProductionApprovalError("approval.evaluation_time")
        now = evaluated_at.astimezone(timezone.utc)
        for raw, expected, path in (
            (review_raw, expected_review_file_sha256, "live_review"),
            (policy_raw, expected_policy_file_sha256, "approval_policy"),
        ):
            _sha(expected, path=f"{path}.file_sha256")
            if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), expected):
                raise ProductionApprovalError(f"{path}.file_sha256_mismatch")
        review_value = strict_json_loads(review_raw)
        policy_value = strict_json_loads(policy_raw)
        if not (
            canonical_json(review_value) == review_raw
            and canonical_json(policy_value) == policy_raw
        ):
            raise ProductionApprovalError("approval.noncanonical_input")
        review = _validated_review(review_value)
        policy = _validated_policy(policy_value)
        review_sha = live_review_sha256(review)
        policy_sha = approval_policy_sha256(policy)
        if not (
            policy["target_sha256"] == review["target_sha256"]
            and policy["environment"] == review["environment"]
            and now < _time(review["valid_until"], path="live_review.valid_until")
        ):
            raise ProductionApprovalError("approval.review_policy_binding")
        if receipt_raw is None:
            if expected_receipt_file_sha256 is not None:
                raise ProductionApprovalError("approval.receipt_pin_without_receipt")
            return _not_ready(
                "approval.receipt_missing",
                review_sha256=review_sha,
                policy_sha256=policy_sha,
                review_status="REVIEW_VERIFIED_AWAITING_APPROVAL",
            )
        if expected_receipt_file_sha256 is None:
            raise ProductionApprovalError("approval.receipt_pin_missing")
        _sha(expected_receipt_file_sha256, path="approval_receipt.file_sha256")
        if not hmac.compare_digest(
            hashlib.sha256(receipt_raw).hexdigest(), expected_receipt_file_sha256
        ):
            raise ProductionApprovalError("approval_receipt.file_sha256_mismatch")
        receipt_value = strict_json_loads(receipt_raw)
        if canonical_json(receipt_value) != receipt_raw:
            raise ProductionApprovalError("approval_receipt.noncanonical")
        receipt = _mapping(
            receipt_value,
            keys=_RECEIPT_BODY_KEYS | {"signature"},
            path="approval_receipt",
        )
        body = dict(receipt)
        signature = body.pop("signature")
        signer, public = _did(body["signer_did"], path="approval_receipt.signer_did")
        if not (
            body["schema_version"] == APPROVAL_RECEIPT_SCHEMA
            and body["approval_policy_sha256"] == policy_sha
            and body["live_review_sha256"] == review_sha
            and body["environment"] == review["environment"]
            and body["approval_scope"] == policy["approval_scope"]
            and body["target_sha256"] == review["target_sha256"]
            and body["operation_sha256"] == review["operation_sha256"]
            and body["artifact_identity_sha256"]
            == review["artifact_identity_sha256"]
            and signer == policy["approver_did"]
            and _identity_sha(signer) not in review["authority_identity_sha256s"]
        ):
            raise ProductionApprovalError("approval_receipt.binding")
        _sha(body["nonce"], path="approval_receipt.nonce")
        approved_at = _time(body["approved_at"], path="approval_receipt.approved_at")
        valid_until = _time(body["valid_until"], path="approval_receipt.valid_until")
        review_evaluated_at = _time(
            review["evaluated_at"], path="live_review.evaluated_at"
        )
        review_valid_until = _time(
            review["valid_until"], path="live_review.valid_until"
        )
        if not (
            review_evaluated_at <= approved_at <= now < valid_until <= review_valid_until
            and timedelta(0) < valid_until - approved_at
            <= timedelta(seconds=policy["max_lifetime_seconds"])
        ):
            raise ProductionApprovalError("approval_receipt.validity")
        if not (
            isinstance(signature, str)
            and len(signature) == 128
            and all(char in _HEX for char in signature)
            and ed25519_verify(
                public,
                approval_receipt_signing_bytes(receipt),
                bytes.fromhex(signature),
            )
        ):
            raise ProductionApprovalError("approval_receipt.signature")
        return {
            "schema_version": APPROVAL_REPORT_SCHEMA,
            "status": "APPROVAL_RECEIPT_VERIFIED",
            "review_status": "REVIEW_VERIFIED",
            "production_ready": True,
            "deployment_status": "APPROVED_NOT_APPLIED",
            "l3_assurance": "PER_PROOF",
            "approval_applied": False,
            "live_review_sha256": review_sha,
            "approval_policy_sha256": policy_sha,
            "failures": [],
        }
    except (ProductionApprovalError, CertError, ValueError, TypeError, KeyError):
        return _not_ready("approval.verification_failed")


def _load_pinned(path_value: str, sha_value: str, *, label: str) -> bytes:
    _sha(sha_value, path=f"{label}.file_sha256")
    path = Path(path_value)
    if not path.is_absolute():
        raise ProductionApprovalError(f"{label}.path_absolute")
    try:
        before = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ProductionApprovalError(f"{label}.unavailable") from exc
    if (
        resolved != path
        or stat.S_ISLNK(before.st_mode)
        or not stat.S_ISREG(before.st_mode)
        or bool(before.st_mode & 0o222)
        or not 0 < before.st_size <= MAX_DOCUMENT_BYTES
    ):
        raise ProductionApprovalError(f"{label}.unsafe_file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        raw = os.pread(descriptor, MAX_DOCUMENT_BYTES + 1, 0)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if not (
        stat.S_ISREG(opened.st_mode)
        and not bool(opened.st_mode & 0o222)
        and (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
        == (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        and len(raw) == opened.st_size
        and hmac.compare_digest(hashlib.sha256(raw).hexdigest(), sha_value)
    ):
        raise ProductionApprovalError(f"{label}.changed_or_mismatched")
    return raw


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify a pinned Gate-5 live review and external approval receipt"
    )
    parser.add_argument("--review", required=True)
    parser.add_argument("--review-sha256", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--policy-sha256", required=True)
    parser.add_argument("--receipt")
    parser.add_argument("--receipt-sha256")
    parser.add_argument("--evaluated-at", required=True)
    args = parser.parse_args(argv)
    try:
        review_raw = _load_pinned(args.review, args.review_sha256, label="live_review")
        policy_raw = _load_pinned(args.policy, args.policy_sha256, label="approval_policy")
        if bool(args.receipt) != bool(args.receipt_sha256):
            raise ProductionApprovalError("approval.receipt_arguments_partial")
        receipt_raw = (
            _load_pinned(args.receipt, args.receipt_sha256, label="approval_receipt")
            if args.receipt
            else None
        )
        evaluated_at = _time(args.evaluated_at, path="approval.evaluated_at")
        report = verify_external_approval(
            review_raw=review_raw,
            expected_review_file_sha256=args.review_sha256,
            policy_raw=policy_raw,
            expected_policy_file_sha256=args.policy_sha256,
            receipt_raw=receipt_raw,
            expected_receipt_file_sha256=args.receipt_sha256,
            evaluated_at=evaluated_at,
        )
    except (ProductionApprovalError, OSError, ValueError, TypeError):
        report = _not_ready("approval.input_unavailable")
    sys.stdout.buffer.write(canonical_json(report) + b"\n")
    sys.stdout.buffer.flush()
    return 0 if report["status"] == "APPROVAL_RECEIPT_VERIFIED" else 1


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())


__all__ = [
    "APPROVAL_POLICY_SCHEMA",
    "APPROVAL_RECEIPT_SCHEMA",
    "APPROVAL_REPORT_SCHEMA",
    "APPROVAL_SCOPE",
    "LIVE_REVIEW_SCHEMA",
    "ProductionApprovalError",
    "approval_policy_sha256",
    "approval_receipt_signing_bytes",
    "build_live_review",
    "live_review_sha256",
    "main",
    "verify_external_approval",
]
