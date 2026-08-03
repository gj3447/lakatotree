"""Pure verifier for a boot-bound, externally signed runtime-writer snapshot.

The application is not the runtime authority.  It creates a fresh challenge,
verifies an independently signed response, and caches the resulting immutable
proof.  This module performs no I/O, lease acquisition, deployment approval, or
datastore mutation.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any, Mapping, Sequence

from lakatos.write_cert import (
    did_key_encode,
    ed25519_public_key_is_strict,
    ed25519_verify,
)


RUNTIME_CHALLENGE_SCHEMA = "lakatotree-runtime-snapshot-challenge/v1"
RUNTIME_SNAPSHOT_SCHEMA = "lakatotree-runtime-authority-snapshot/v1"
RUNTIME_SIGNATURE_DOMAIN = b"lakatotree-runtime-authority-snapshot/v1\0"
RUNTIME_EFFECT_SCOPE = "critique-history-ledger/v1"
RUNTIME_ENVIRONMENTS = ("production", "development")
MAX_RUNTIME_SNAPSHOT_BYTES = 64 * 1024
MAX_SNAPSHOT_LIFETIME_SECONDS = 300
MAX_SNAPSHOT_AGE_SECONDS = 30
MIN_COMMIT_MARGIN_SECONDS = 2

_SHA_FIELDS = {
    "operation_sha256",
    "target_sha256",
    "storage_access_policy_file_sha256",
    "predeploy_receipt_file_sha256",
    "predeploy_receipt_sha256",
    "startup_bundle_file_sha256",
    "historical_drain_lease_id_sha256",
}
_CHALLENGE_FIELDS = {
    "schema_version",
    "nonce",
    "environment",
    "effect_scope",
    "boot_id",
    "artifact",
    "artifact_identity_sha256",
    *_SHA_FIELDS,
    "runtime_writer_lease",
    "workers",
}
_RESPONSE_BODY_FIELDS = {
    "schema_version",
    "challenge_sha256",
    "nonce",
    "environment",
    "effect_scope",
    "active",
    "boot_id",
    "artifact",
    "artifact_identity_sha256",
    *_SHA_FIELDS,
    "runtime_writer_lease",
    "workers",
    "observed_at",
    "expires_at",
    "evidence_refs",
}
_LEASE_FIELDS = {
    "lease_id",
    "owner_token_sha256",
    "generation",
    "postgresql_backend_pid",
    "postgresql_advisory_key",
}
_WORKER_FIELDS = {"worker_id", "boot_id"}


class RuntimeAuthorityError(ValueError):
    """The candidate cannot authorize this runtime writer."""


def canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise RuntimeAuthorityError("runtime authority JSON is not canonical") from exc


def strict_json_loads(raw: bytes) -> Any:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_RUNTIME_SNAPSHOT_BYTES:
        raise RuntimeAuthorityError("runtime authority response size is invalid")

    def pairs(items: Sequence[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise RuntimeAuthorityError("runtime authority JSON has duplicate keys")
            result[key] = value
        return result

    def reject_constant(_token: str) -> None:
        raise RuntimeAuthorityError("runtime authority JSON has a non-finite number")

    try:
        return json.loads(
            raw,
            object_pairs_hook=pairs,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeAuthorityError("runtime authority response is invalid JSON") from exc


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha(value: Any, *, field: str) -> str:
    if not (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    ):
        raise RuntimeAuthorityError(f"{field} must be a lowercase SHA-256")
    return value


def _bounded_text(value: Any, *, field: str, maximum: int = 256) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
        or "\x00" in value
    ):
        raise RuntimeAuthorityError(f"{field} must be a bounded canonical string")
    return value


def _time(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or len(value) > 64:
        raise RuntimeAuthorityError(f"{field} must be a timezone-aware timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, OverflowError) as exc:
        raise RuntimeAuthorityError(f"{field} must be a valid timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RuntimeAuthorityError(f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _artifact(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RuntimeAuthorityError("artifact must be an object")
    artifact = dict(value)
    kind = artifact.get("kind")
    if kind == "git":
        if set(artifact) != {"kind", "source_commit"}:
            raise RuntimeAuthorityError("Git artifact has a non-exact field set")
        commit = artifact["source_commit"]
        if not (
            isinstance(commit, str)
            and len(commit) == 40
            and all(char in "0123456789abcdef" for char in commit)
        ):
            raise RuntimeAuthorityError("Git artifact commit is not canonical")
    elif kind == "wheel-record":
        if set(artifact) != {
            "kind",
            "version",
            "installed_manifest_sha256",
            "record_verified_files",
            "stable_files",
        }:
            raise RuntimeAuthorityError("wheel artifact has a non-exact field set")
        _bounded_text(artifact["version"], field="artifact.version", maximum=128)
        _sha(
            artifact["installed_manifest_sha256"],
            field="artifact.installed_manifest_sha256",
        )
        for field in ("record_verified_files", "stable_files"):
            if type(artifact[field]) is not int or artifact[field] < 1:
                raise RuntimeAuthorityError(f"artifact.{field} must be positive")
        if artifact["record_verified_files"] > artifact["stable_files"]:
            raise RuntimeAuthorityError("wheel RECORD coverage is impossible")
    else:
        raise RuntimeAuthorityError("artifact kind is unsupported")
    return artifact


def artifact_identity_sha256(artifact: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json(_artifact(artifact)))


def _lease(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _LEASE_FIELDS:
        raise RuntimeAuthorityError("runtime writer lease has a non-exact field set")
    lease = dict(value)
    _bounded_text(lease["lease_id"], field="runtime_writer_lease.lease_id")
    _sha(
        lease["owner_token_sha256"],
        field="runtime_writer_lease.owner_token_sha256",
    )
    if type(lease["generation"]) is not int or lease["generation"] < 1:
        raise RuntimeAuthorityError("runtime writer lease generation is invalid")
    if (
        type(lease["postgresql_backend_pid"]) is not int
        or lease["postgresql_backend_pid"] < 1
    ):
        raise RuntimeAuthorityError("runtime writer PostgreSQL backend is invalid")
    key = lease["postgresql_advisory_key"]
    if not (
        isinstance(key, list)
        and len(key) == 2
        and all(type(item) is int and -(2**31) <= item < 2**31 for item in key)
    ):
        raise RuntimeAuthorityError("runtime writer advisory key is invalid")
    return lease


def _workers(value: Any, *, boot_id: str) -> tuple[dict[str, str], ...]:
    if not isinstance(value, list) or len(value) != 1:
        raise RuntimeAuthorityError("runtime worker inventory must contain one worker")
    worker = value[0]
    if not isinstance(worker, Mapping) or set(worker) != _WORKER_FIELDS:
        raise RuntimeAuthorityError("runtime worker has a non-exact field set")
    worker = dict(worker)
    _sha(worker["worker_id"], field="workers[0].worker_id")
    if worker["boot_id"] != boot_id:
        raise RuntimeAuthorityError("runtime worker belongs to another boot")
    return (worker,)


def validate_challenge(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _CHALLENGE_FIELDS:
        raise RuntimeAuthorityError("runtime challenge has a non-exact field set")
    challenge = dict(value)
    if challenge["schema_version"] != RUNTIME_CHALLENGE_SCHEMA:
        raise RuntimeAuthorityError("runtime challenge schema is unsupported")
    _sha(challenge["nonce"], field="nonce")
    if challenge["environment"] not in RUNTIME_ENVIRONMENTS:
        raise RuntimeAuthorityError(
            "runtime challenge environment must be production or development"
        )
    if challenge["effect_scope"] != RUNTIME_EFFECT_SCOPE:
        raise RuntimeAuthorityError("runtime challenge effect scope is unsupported")
    _sha(challenge["boot_id"], field="boot_id")
    artifact = _artifact(challenge["artifact"])
    if challenge["artifact_identity_sha256"] != artifact_identity_sha256(artifact):
        raise RuntimeAuthorityError("runtime artifact identity digest mismatches")
    for field in _SHA_FIELDS | {"artifact_identity_sha256"}:
        _sha(challenge[field], field=field)
    lease = _lease(challenge["runtime_writer_lease"])
    workers = _workers(challenge["workers"], boot_id=challenge["boot_id"])
    if challenge["historical_drain_lease_id_sha256"] == sha256_bytes(
        lease["lease_id"].encode("utf-8")
    ):
        raise RuntimeAuthorityError("historical drain lease cannot be the runtime lease")
    challenge["artifact"] = artifact
    challenge["runtime_writer_lease"] = lease
    challenge["workers"] = [dict(item) for item in workers]
    return challenge


def build_runtime_challenge(
    *,
    nonce: str,
    environment: str,
    boot_id: str,
    artifact: Mapping[str, Any],
    operation_sha256: str,
    target_sha256: str,
    storage_access_policy_file_sha256: str,
    predeploy_receipt_file_sha256: str,
    predeploy_receipt_sha256: str,
    startup_bundle_file_sha256: str,
    historical_drain_lease_id_sha256: str,
    runtime_writer_lease: Mapping[str, Any],
    workers: Sequence[Mapping[str, str]],
) -> dict[str, Any]:
    artifact_value = dict(artifact)
    return validate_challenge({
        "schema_version": RUNTIME_CHALLENGE_SCHEMA,
        "nonce": nonce,
        "environment": environment,
        "effect_scope": RUNTIME_EFFECT_SCOPE,
        "boot_id": boot_id,
        "artifact": artifact_value,
        "artifact_identity_sha256": artifact_identity_sha256(artifact_value),
        "operation_sha256": operation_sha256,
        "target_sha256": target_sha256,
        "storage_access_policy_file_sha256": storage_access_policy_file_sha256,
        "predeploy_receipt_file_sha256": predeploy_receipt_file_sha256,
        "predeploy_receipt_sha256": predeploy_receipt_sha256,
        "startup_bundle_file_sha256": startup_bundle_file_sha256,
        "historical_drain_lease_id_sha256": historical_drain_lease_id_sha256,
        "runtime_writer_lease": dict(runtime_writer_lease),
        "workers": [dict(item) for item in workers],
    })


def challenge_sha256(challenge: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json(validate_challenge(challenge)))


def signing_bytes(body: Mapping[str, Any]) -> bytes:
    if not isinstance(body, Mapping) or "signature" in body:
        raise RuntimeAuthorityError("runtime snapshot signing body is invalid")
    return RUNTIME_SIGNATURE_DOMAIN + canonical_json(dict(body))


def _public_key(value: Any) -> bytes:
    _sha(value, field="runtime authority public key")
    return bytes.fromhex(value)


@dataclass(frozen=True)
class VerifiedRuntimeSnapshot:
    canonical_response: bytes
    body_sha256: str
    challenge_sha256: str
    boot_id: str
    artifact: Mapping[str, Any]
    artifact_identity_sha256: str
    operation_sha256: str
    target_sha256: str
    predeploy_receipt_file_sha256: str
    predeploy_receipt_sha256: str
    startup_bundle_file_sha256: str
    lease_id: str
    lease_owner_token_sha256: str
    lease_generation: int
    lease_postgresql_backend_pid: int
    lease_postgresql_advisory_key: tuple[int, int]
    observed_at: str
    expires_at: str
    environment: str
    authority_did: str | None = None
    storage_access_policy_file_sha256: str | None = None

    def public_report(self) -> dict[str, Any]:
        """Return a bounded projection without nonce, signature, key, path, or token."""

        return {
            "ok": True,
            "schema_version": RUNTIME_SNAPSHOT_SCHEMA,
            "environment": self.environment,
            "body_sha256": self.body_sha256,
            "challenge_sha256": self.challenge_sha256,
            "artifact_kind": self.artifact["kind"],
            "artifact_identity_sha256": self.artifact_identity_sha256,
            "operation_sha256": self.operation_sha256,
            "target_sha256": self.target_sha256,
            "predeploy_receipt_file_sha256": self.predeploy_receipt_file_sha256,
            "storage_access_policy_file_sha256": (
                self.storage_access_policy_file_sha256
            ),
            "startup_bundle_file_sha256": self.startup_bundle_file_sha256,
            "runtime_lease_id_sha256": sha256_bytes(self.lease_id.encode("utf-8")),
            "runtime_lease_generation": self.lease_generation,
            "worker_count": 1,
            "boot_id_sha256": sha256_bytes(self.boot_id.encode("ascii")),
            "observed_at": self.observed_at,
            "expires_at": self.expires_at,
            "production_ready": False,
            # A development snapshot is honestly self-labelled and keeps the
            # production NOT_READY shape unreachable for it.
            "deployment_status": (
                "DEVELOPMENT_ONLY"
                if self.environment == "development"
                else "NOT_READY"
            ),
            "failures": [],
        }


def verify_runtime_snapshot(
    raw_response: bytes,
    *,
    challenge: Mapping[str, Any],
    public_key_hex: str,
    evaluated_at: datetime,
    authority_not_after: datetime,
) -> VerifiedRuntimeSnapshot:
    """Strictly verify one response against the exact fresh challenge."""

    challenge_value = validate_challenge(challenge)
    response = strict_json_loads(raw_response)
    if not isinstance(response, Mapping) or set(response) != {
        *_RESPONSE_BODY_FIELDS,
        "signature",
    }:
        raise RuntimeAuthorityError("runtime snapshot has a non-exact field set")
    signature = response["signature"]
    if not (
        isinstance(signature, str)
        and len(signature) == 128
        and all(char in "0123456789abcdef" for char in signature)
    ):
        raise RuntimeAuthorityError("runtime snapshot signature is malformed")
    body = dict(response)
    body.pop("signature")
    if body["schema_version"] != RUNTIME_SNAPSHOT_SCHEMA:
        raise RuntimeAuthorityError("runtime snapshot schema is unsupported")
    public_key = _public_key(public_key_hex)
    if not (
        ed25519_public_key_is_strict(public_key)
        and ed25519_verify(public_key, signing_bytes(body), bytes.fromhex(signature))
    ):
        raise RuntimeAuthorityError("runtime authority signature is invalid")

    expected_challenge_sha = challenge_sha256(challenge_value)
    if body["challenge_sha256"] != expected_challenge_sha:
        raise RuntimeAuthorityError("runtime snapshot challenge digest mismatches")
    _sha(body["challenge_sha256"], field="challenge_sha256")
    if body["active"] is not True:
        raise RuntimeAuthorityError("runtime authority did not observe an active writer")
    for field in (
        "nonce",
        "environment",
        "effect_scope",
        "boot_id",
        "artifact",
        "artifact_identity_sha256",
        *_SHA_FIELDS,
        "runtime_writer_lease",
        "workers",
    ):
        if body[field] != challenge_value[field]:
            raise RuntimeAuthorityError(f"runtime snapshot binding mismatches: {field}")
    _artifact(body["artifact"])
    lease = _lease(body["runtime_writer_lease"])
    _workers(body["workers"], boot_id=body["boot_id"])
    evidence = body["evidence_refs"]
    if not (
        isinstance(evidence, list)
        and 1 <= len(evidence) <= 16
        and all(
            isinstance(item, str)
            and len(item) == 64
            and all(char in "0123456789abcdef" for char in item)
            for item in evidence
        )
    ):
        raise RuntimeAuthorityError(
            "runtime snapshot evidence references must be SHA-256 digests"
        )
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise RuntimeAuthorityError("runtime snapshot evaluation time is naive")
    if authority_not_after.tzinfo is None or authority_not_after.utcoffset() is None:
        raise RuntimeAuthorityError("runtime snapshot outer authority time is naive")
    now = evaluated_at.astimezone(timezone.utc)
    outer_expiry = authority_not_after.astimezone(timezone.utc)
    observed = _time(body["observed_at"], field="observed_at")
    expires = _time(body["expires_at"], field="expires_at")
    if not (
        observed <= now < expires <= outer_expiry
        and now - observed <= timedelta(seconds=MAX_SNAPSHOT_AGE_SECONDS)
        and expires - observed <= timedelta(seconds=MAX_SNAPSHOT_LIFETIME_SECONDS)
        and expires - now >= timedelta(seconds=MIN_COMMIT_MARGIN_SECONDS)
    ):
        raise RuntimeAuthorityError("runtime snapshot is stale or exceeds its authority")
    canonical_response = canonical_json(dict(response))
    body_digest = sha256_bytes(canonical_json(body))
    return VerifiedRuntimeSnapshot(
        canonical_response=canonical_response,
        body_sha256=body_digest,
        challenge_sha256=expected_challenge_sha,
        boot_id=body["boot_id"],
        artifact=dict(body["artifact"]),
        artifact_identity_sha256=body["artifact_identity_sha256"],
        operation_sha256=body["operation_sha256"],
        target_sha256=body["target_sha256"],
        predeploy_receipt_file_sha256=body["predeploy_receipt_file_sha256"],
        predeploy_receipt_sha256=body["predeploy_receipt_sha256"],
        startup_bundle_file_sha256=body["startup_bundle_file_sha256"],
        lease_id=lease["lease_id"],
        lease_owner_token_sha256=lease["owner_token_sha256"],
        lease_generation=lease["generation"],
        lease_postgresql_backend_pid=lease["postgresql_backend_pid"],
        lease_postgresql_advisory_key=tuple(
            lease["postgresql_advisory_key"]
        ),
        observed_at=body["observed_at"],
        expires_at=body["expires_at"],
        environment=body["environment"],
        authority_did=did_key_encode(public_key),
        storage_access_policy_file_sha256=body[
            "storage_access_policy_file_sha256"
        ],
    )


def challenge_from_published_snapshot(raw_response: bytes) -> dict[str, Any]:
    """Reconstruct the signed challenge fields from a public cached envelope.

    This is for independent read-only collectors.  It does not mint, renew, or
    authorize a snapshot; :func:`verify_runtime_snapshot` still verifies the
    signature, exact digest, bounded lifetime, and every reconstructed field.
    """

    response = strict_json_loads(raw_response)
    if not isinstance(response, Mapping) or set(response) != {
        *_RESPONSE_BODY_FIELDS,
        "signature",
    }:
        raise RuntimeAuthorityError("runtime snapshot has a non-exact field set")
    return validate_challenge({
        "schema_version": RUNTIME_CHALLENGE_SCHEMA,
        **{
            field: response[field]
            for field in _CHALLENGE_FIELDS
            if field != "schema_version"
        },
    })


def verify_published_runtime_snapshot(
    raw_response: bytes,
    *,
    public_key_hex: str,
    expected_artifact: Mapping[str, Any],
    evaluated_at: datetime,
) -> VerifiedRuntimeSnapshot:
    """Verify a cached public proof without treating collection as approval."""

    challenge = challenge_from_published_snapshot(raw_response)
    response = strict_json_loads(raw_response)
    authority_not_after = _time(response.get("expires_at"), field="expires_at")
    proof = verify_runtime_snapshot(
        raw_response,
        challenge=challenge,
        public_key_hex=public_key_hex,
        evaluated_at=evaluated_at,
        authority_not_after=authority_not_after,
    )
    expected = _artifact(expected_artifact)
    if (
        proof.artifact != expected
        or proof.artifact_identity_sha256 != artifact_identity_sha256(expected)
    ):
        raise RuntimeAuthorityError("runtime snapshot artifact mismatches collector pin")
    return proof


def snapshot_is_current(
    proof: VerifiedRuntimeSnapshot,
    *,
    boot_id: str,
    lease: Mapping[str, Any],
    evaluated_at: datetime,
    commit_margin_seconds: int = 0,
) -> bool:
    """Pure O(1) operation/final-guard check over an already verified proof."""

    if type(commit_margin_seconds) is not int or commit_margin_seconds < 0:
        return False
    try:
        current_lease = _lease(lease)
        expires = _time(proof.expires_at, field="expires_at")
    except RuntimeAuthorityError:
        return False
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        return False
    return (
        proof.boot_id == boot_id
        and proof.lease_id == current_lease["lease_id"]
        and proof.lease_owner_token_sha256
        == current_lease["owner_token_sha256"]
        and proof.lease_generation == current_lease["generation"]
        and proof.lease_postgresql_backend_pid
        == current_lease["postgresql_backend_pid"]
        and proof.lease_postgresql_advisory_key
        == tuple(current_lease["postgresql_advisory_key"])
        and evaluated_at.astimezone(timezone.utc)
        + timedelta(seconds=commit_margin_seconds)
        < expires
    )


def _load_pinned_file(path: Path, expected_sha256: str, *, maximum: int) -> bytes:
    _sha(expected_sha256, field="pinned file SHA-256")
    if not path.is_absolute():
        raise RuntimeAuthorityError("pinned file path must be absolute")
    try:
        before = path.lstat()
        if path.resolve(strict=True) != path:
            raise RuntimeAuthorityError("pinned file path must be canonical")
    except OSError as exc:
        raise RuntimeAuthorityError("pinned file is unavailable") from exc
    if (
        stat.S_ISLNK(before.st_mode)
        or not stat.S_ISREG(before.st_mode)
        or before.st_size > maximum
    ):
        raise RuntimeAuthorityError("pinned file identity is unsafe")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        raw = os.pread(descriptor, maximum + 1, 0)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    identity = lambda info: (info.st_dev, info.st_ino, info.st_size)  # noqa: E731
    if (
        identity(before) != identity(opened)
        or identity(opened) != identity(after)
        or len(raw) > maximum
        or not hmac.compare_digest(sha256_bytes(raw), expected_sha256)
    ):
        raise RuntimeAuthorityError("pinned file changed or mismatched")
    return raw


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify one cached runtime-authority snapshot. This command never "
            "signs, refreshes, approves, or mutates deployment state."
        )
    )
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--snapshot-sha256", required=True)
    parser.add_argument("--expected-artifact", required=True, type=Path)
    parser.add_argument("--expected-artifact-sha256", required=True)
    parser.add_argument("--public-key-hex", required=True)
    parser.add_argument("--evaluated-at", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        snapshot = _load_pinned_file(
            args.snapshot, args.snapshot_sha256, maximum=MAX_RUNTIME_SNAPSHOT_BYTES
        )
        artifact_raw = _load_pinned_file(
            args.expected_artifact,
            args.expected_artifact_sha256,
            maximum=4096,
        )
        artifact = strict_json_loads(artifact_raw)
        evaluated_at = _time(args.evaluated_at, field="evaluated_at")
        proof = verify_published_runtime_snapshot(
            snapshot,
            public_key_hex=args.public_key_hex,
            expected_artifact=artifact,
            evaluated_at=evaluated_at,
        )
        report = proof.public_report()
    except (OSError, RuntimeAuthorityError) as exc:
        report = {
            "ok": False,
            "status": "NOT_READY",
            "production_ready": False,
            "deployment_status": "NOT_READY",
            "failures": ["runtime.snapshot.invalid"],
        }
        del exc
    sys.stdout.write(
        json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n"
    )
    return 0 if report.get("ok") is True else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
