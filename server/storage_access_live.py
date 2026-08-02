"""One-shot producer for signed PostgreSQL/Neo4j access-audit bundles.

The process uses dedicated read-only audit principals, signs each datastore's
before/after projection separately, and publishes one digest-bound bundle.  It
never provisions roles, runs migrations, opens readiness, or approves a deploy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import stat
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlsplit

from lakatos.write_cert import did_key_encode, ed25519_public_key
from server import production_readiness_live as live
from server.storage_access import (
    ACCESS_POLICY_SCHEMA,
    PHASES,
    STORAGE_AUDIT_BUNDLE_SCHEMA,
    STORES,
    StorageAccessError,
    build_attestation_body,
    build_storage_audit_bundle,
    canonical_json,
    seal_datastore_attestation,
    validate_access_policy,
    _expected_from_bundle,
    verify_access_attestation_pair_bytes,
    verify_storage_audit_bundle,
)
from server.storage_predeploy import RECEIPT_SCHEMA as PREDEPLOY_RECEIPT_SCHEMA
from server.storage_predeploy import (
    _artifact_identity,
    operation_identity,
    principal_bindings,
    verify_predeploy_receipt_document,
)
from server.storage_protocol import STORAGE_CONTRACT_ID


REQUEST_SCHEMA = "lakatotree-storage-audit-request/v2"
WRITE_RECEIPT_SCHEMA = "lakatotree-storage-audit-write-receipt/v1"
CLAIM_BOUNDARY = (
    "A verified storage-audit bundle proves that two separately signed, bounded "
    "read-only projections per datastore matched during one phase. It does not "
    "prove that no change-and-revert occurred between observations, establish a "
    "current runtime writer lease, authorize migration/restart, approve production, "
    "or establish VAL L3. The verifier is stateless: it rejects cross-phase nonce "
    "reuse but may reevaluate the same valid pair until its signed expiry."
)
MAX_ACCESS_FACT_ITEMS = 8192


class StorageAuditCollectionError(ValueError):
    """A request, key, datastore projection, or publication is not trustworthy."""


def _sha(value: Any, *, path: str) -> str:
    if not (
        isinstance(value, str) and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    ):
        raise StorageAuditCollectionError(f"{path} must be a lowercase SHA-256")
    return value


def _text(value: Any, *, path: str, maximum: int = 256) -> str:
    if (
        not isinstance(value, str) or not value or value != value.strip()
        or len(value) > maximum or "\x00" in value
    ):
        raise StorageAuditCollectionError(f"{path} must be a bounded canonical string")
    return value


def _file_ref(value: Any, *, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"path", "file_sha256"}:
        raise StorageAuditCollectionError(f"{path} must be an exact pinned-file reference")
    file_path = _text(value["path"], path=f"{path}.path", maximum=4096)
    if not Path(file_path).is_absolute():
        raise StorageAuditCollectionError(f"{path}.path must be absolute")
    _sha(value["file_sha256"], path=f"{path}.file_sha256")
    return value


def validate_request(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "schema_version", "phase", "request_nonce", "environment",
        "target_sha256", "operation_sha256", "access_policy",
        "predeploy_receipt", "previous_phase_bundle", "timeout_seconds",
    }:
        raise StorageAuditCollectionError("request has a non-exact field set")
    if value["schema_version"] != REQUEST_SCHEMA:
        raise StorageAuditCollectionError("request schema is unsupported")
    _sha(value["request_nonce"], path="request.request_nonce")
    phase = _text(value["phase"], path="request.phase")
    if phase not in PHASES:
        raise StorageAuditCollectionError("request phase is unsupported")
    if value["environment"] != "production":
        raise StorageAuditCollectionError("request.environment must be production")
    _sha(value["target_sha256"], path="request.target_sha256")
    _sha(value["operation_sha256"], path="request.operation_sha256")
    _file_ref(value["access_policy"], path="request.access_policy")
    _file_ref(value["predeploy_receipt"], path="request.predeploy_receipt")
    previous = value["previous_phase_bundle"]
    if phase == "predeploy" and previous is not None:
        raise StorageAuditCollectionError("predeploy request cannot bind a prior phase")
    if phase == "startup":
        _file_ref(previous, path="request.previous_phase_bundle")
    timeout = value["timeout_seconds"]
    if type(timeout) is not int or not 2 <= timeout <= 10:
        raise StorageAuditCollectionError("request.timeout_seconds must be from 2 to 10")
    return value


def load_signing_seed(path: Path) -> bytes:
    """Load one raw seed from a private, owner-controlled, non-symlink file."""

    if not path.is_absolute():
        raise StorageAuditCollectionError("signing-key path must be absolute")
    try:
        resolved = path.resolve(strict=True)
        info = path.lstat()
    except OSError as exc:
        raise StorageAuditCollectionError("signing key is unavailable") from exc
    if (
        resolved != path
        or stat.S_ISLNK(info.st_mode)
        or not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or bool(info.st_mode & 0o077)
        or stat.S_IMODE(info.st_mode) not in {0o400, 0o600}
        or info.st_size != 32
    ):
        raise StorageAuditCollectionError("signing key is not a private raw Ed25519 seed")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise StorageAuditCollectionError("signing key cannot be opened safely") from exc
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            raise StorageAuditCollectionError("signing key changed during open")
        seed = os.read(fd, 33)
    finally:
        os.close(fd)
    if len(seed) != 32:
        raise StorageAuditCollectionError("signing key must contain exactly 32 raw bytes")
    return seed


def _pinned_json(ref: Mapping[str, Any]) -> tuple[bytes, Mapping[str, Any]]:
    try:
        raw, value, info = live._load_pinned_json(
            Path(str(ref["path"])), str(ref["file_sha256"]),
            max_bytes=live.MAX_ARTIFACT_BYTES,
        )
    except (live.CollectionInputError, OSError) as exc:
        raise StorageAuditCollectionError("pinned JSON artifact is unavailable") from exc
    if not isinstance(value, Mapping):
        raise StorageAuditCollectionError("pinned JSON artifact must be an object")
    if info.st_mode & 0o222:
        raise StorageAuditCollectionError("pinned JSON artifact must be read-only")
    return raw, value


def _normalized_observation(
    store: str,
    config: Mapping[str, Any],
    timeout: float,
    environ: Mapping[str, str],
    ports: live.CollectorPorts,
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    port = ports.postgresql if store == "postgresql" else ports.neo4j
    try:
        result = port(config, timeout, environ)
        sensitive_values: set[str] = set()
        for key, value in environ.items():
            if not isinstance(value, str) or not value:
                continue
            if key == live.POSTGRESQL_DSN_ENV:
                sensitive_values.add(value)
                try:
                    parsed = urlsplit(value)
                    if parsed.username:
                        sensitive_values.add(parsed.username)
                    if parsed.password:
                        sensitive_values.add(parsed.password)
                except ValueError:
                    pass
                try:
                    for token in shlex.split(value):
                        name, separator, authority = token.partition("=")
                        if separator and name.lower() in {"user", "password"} and authority:
                            sensitive_values.add(authority)
                except ValueError:
                    pass
            elif key in {
                live.NEO4J_URI_ENV, live.NEO4J_USER_ENV, live.NEO4J_PASSWORD_ENV
            }:
                sensitive_values.add(value)
        sensitive = frozenset(sensitive_values)
        normalized = live._normalize_result(
            store,
            result,
            sensitive_values=sensitive,
            max_fact_items=MAX_ACCESS_FACT_ITEMS,
            max_list_items=512,
        )
    except Exception as exc:  # noqa: BLE001 - never reflect driver/credential details
        raise StorageAuditCollectionError(f"{store} audit collection failed") from exc
    if normalized["status"] != "OBSERVED":
        raise StorageAuditCollectionError(f"{store} audit observation is incomplete")
    if normalized["facts"].get("audit_principal_read_only") is not True:
        raise StorageAuditCollectionError(f"{store} audit principal is not read-only")
    if not isinstance(result.binding_material, Mapping):
        raise StorageAuditCollectionError(f"{store} target binding is unavailable")
    return normalized, dict(result.binding_material)


def collect_signed_storage_audit(
    request: Mapping[str, Any],
    *,
    request_file_sha256: str,
    signing_seeds: Mapping[str, bytes],
    ports: live.CollectorPorts | None = None,
    environ: Mapping[str, str] | None = None,
    now: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    request = validate_request(request)
    request_file_sha256 = _sha(request_file_sha256, path="request_file_sha256")
    ports = ports or live.default_ports()
    environ = dict(os.environ if environ is None else environ)
    now = now or (lambda: datetime.now(timezone.utc))

    policy_raw, policy_value = _pinned_json(request["access_policy"])
    try:
        policy = validate_access_policy(policy_value)
    except StorageAccessError as exc:
        raise StorageAuditCollectionError("access policy is invalid") from exc
    if (
        policy["schema_version"] != ACCESS_POLICY_SCHEMA
        or policy["environment"] != request["environment"]
    ):
        raise StorageAuditCollectionError("access policy differs from request")
    if set(signing_seeds) != set(STORES):
        raise StorageAuditCollectionError("both datastore signing seeds are required")
    signer_dids = {
        store: did_key_encode(ed25519_public_key(signing_seeds[store]))
        for store in STORES
    }
    if signer_dids != dict(policy["attestors"]):
        raise StorageAuditCollectionError("signing keys differ from access policy pins")

    configs = {
        "postgresql": {
            "host": policy["postgresql"]["host"],
            "port": policy["postgresql"]["port"],
            "database": policy["postgresql"]["database"],
            "owner_role": policy["postgresql"]["owner_role"],
            "migrator_role": policy["postgresql"]["migrator_role"],
            "runtime_role": policy["postgresql"]["runtime_role"],
            "audit_role": policy["postgresql"]["audit_role"],
            "challenge_nonce": request["request_nonce"],
        },
        "neo4j": {
            "database": policy["neo4j"]["database"],
            "audit_user": policy["neo4j"]["audit_user"],
            "audit_role": policy["neo4j"]["audit_role"],
            "migrator_user": policy["neo4j"]["migrator_user"],
            "migrator_role": policy["neo4j"]["migrator_role"],
            "runtime_user": policy["neo4j"]["runtime_user"],
            "runtime_role": policy["neo4j"]["runtime_role"],
            "challenge_nonce": request["request_nonce"],
        },
    }
    observations: dict[str, dict[str, Mapping[str, Any]]] = {
        store: {} for store in STORES
    }
    bindings: dict[str, dict[str, Mapping[str, Any]]] = {store: {} for store in STORES}
    observed_times: dict[str, dict[str, datetime]] = {store: {} for store in STORES}
    for store in STORES:
        observations[store]["before"], bindings[store]["before"] = _normalized_observation(
            store, configs[store], request["timeout_seconds"], environ, ports
        )
        observed_times[store]["before"] = now().astimezone(timezone.utc)

    predeploy_raw, predeploy = _pinned_json(request["predeploy_receipt"])
    predeploy_receipt_sha = predeploy.get("receipt_sha256")

    previous_file_sha = None
    previous_raw = None
    if request["phase"] == "startup":
        previous_raw, previous = _pinned_json(request["previous_phase_bundle"])
        previous_body = dict(previous)
        previous_bundle_sha = previous_body.pop("bundle_sha256", None)
        if (
                previous.get("schema_version") != STORAGE_AUDIT_BUNDLE_SCHEMA
            or previous.get("phase") != "predeploy"
            or not isinstance(previous_bundle_sha, str)
            or previous_bundle_sha != hashlib.sha256(canonical_json(previous_body)).hexdigest()
        ):
            raise StorageAuditCollectionError("startup prior-phase bundle is invalid")
        previous_file_sha = hashlib.sha256(previous_raw).hexdigest()
        try:
            previous_expected = _expected_from_bundle(previous, policy)
            previous_proof = verify_storage_audit_bundle(
                previous,
                policy=policy,
                expected=previous_expected,
                phase="predeploy",
                signer_dids=policy["attestors"],
                evaluated_at=now().astimezone(timezone.utc),
            )
        except (StorageAccessError, KeyError, TypeError, ValueError) as exc:
            raise StorageAuditCollectionError(
                "startup prior-phase signatures are invalid"
            ) from exc
        if not previous_proof.ok:
            raise StorageAuditCollectionError(
                "startup prior-phase signatures are invalid"
            )

    for store in STORES:
        observations[store]["after"], bindings[store]["after"] = _normalized_observation(
            store, configs[store], request["timeout_seconds"], environ, ports
        )
        observed_times[store]["after"] = now().astimezone(timezone.utc)

    if any(bindings[store]["before"] != bindings[store]["after"] for store in STORES):
        raise StorageAuditCollectionError("datastore target binding drifted during audit")
    target_details = {store: dict(bindings[store]["before"]) for store in STORES}
    target_sha = hashlib.sha256(canonical_json(target_details)).hexdigest()
    if target_sha != request["target_sha256"]:
        raise StorageAuditCollectionError("live datastore target differs from request")
    artifact = _artifact_identity()
    operation = operation_identity(artifact)
    if operation.get("sha256") != request["operation_sha256"]:
        raise StorageAuditCollectionError("installed migration operation differs from request")
    try:
        verified_predeploy = verify_predeploy_receipt_document(
            predeploy,
            file_sha256=hashlib.sha256(predeploy_raw).hexdigest(),
            expected_file_sha256=request["predeploy_receipt"]["file_sha256"],
            expected_environment=request["environment"],
            expected_fence_verifier_sha256=policy["predeploy_authority"][
                "fence_verifier_sha256"
            ],
            expected_fence_public_key_hex=policy["predeploy_authority"][
                "fence_public_key_hex"
            ],
            artifact=artifact,
            operation=operation,
            target={"sha256": target_sha, "details": target_details},
            evaluated_at=max(
                store_times["after"] for store_times in observed_times.values()
            ),
            expected_principals=principal_bindings(
                postgresql_migrator=policy["postgresql"]["migrator_role"],
                postgresql_runtime=policy["postgresql"]["runtime_role"],
                neo4j_migrator=policy["neo4j"]["migrator_user"],
                neo4j_runtime=policy["neo4j"]["runtime_user"],
            ),
        )
    except (RuntimeError, ValueError) as exc:
        raise StorageAuditCollectionError("predeploy receipt binding is invalid") from exc
    predeploy_receipt_sha = verified_predeploy["receipt_sha256"]

    expected = {
        "request_nonce": request["request_nonce"],
        "request_sha256": request_file_sha256,
        "target_sha256": target_sha,
        "target_details": target_details,
        "operation_sha256": request["operation_sha256"],
        "access_policy_file_sha256": hashlib.sha256(policy_raw).hexdigest(),
        "predeploy_receipt_file_sha256": hashlib.sha256(predeploy_raw).hexdigest(),
        "predeploy_receipt_sha256": predeploy_receipt_sha,
        "previous_phase_bundle_file_sha256": previous_file_sha,
    }
    signed: dict[str, dict[str, Mapping[str, Any]]] = {store: {} for store in STORES}
    for store in STORES:
        for position in ("before", "after"):
            observed_at = observed_times[store][position]
            body = build_attestation_body(
                store=store,
                phase=request["phase"],
                position=position,
                expected=expected,
                environment=request["environment"],
                observation=observations[store][position],
                target_binding=bindings[store][position],
                observed_at=observed_at.isoformat(),
                expires_at=(observed_at + timedelta(seconds=300)).isoformat(),
                evidence_refs=[
                    f"request-sha256:{request_file_sha256}",
                    f"policy-sha256:{expected['access_policy_file_sha256']}",
                    f"predeploy-sha256:{expected['predeploy_receipt_file_sha256']}",
                ],
                signer_did=signer_dids[store],
            )
            signed[store][position] = seal_datastore_attestation(
                body, signing_seeds[store]
            )
    bundle = build_storage_audit_bundle(
        phase=request["phase"],
        request_nonce=request["request_nonce"],
        request_sha256=request_file_sha256,
        previous_phase_bundle_file_sha256=previous_file_sha,
        postgresql_before=signed["postgresql"]["before"],
        postgresql_after=signed["postgresql"]["after"],
        neo4j_before=signed["neo4j"]["before"],
        neo4j_after=signed["neo4j"]["after"],
    )
    evaluated_at = max(
        store_times["after"] for store_times in observed_times.values()
    )
    if request["phase"] == "startup":
        startup_raw = canonical_json(bundle)
        pair = verify_access_attestation_pair_bytes(
            previous_raw or b"",
            startup_raw,
            expected_predeploy_file_sha256=previous_file_sha or "",
            expected_startup_file_sha256=hashlib.sha256(startup_raw).hexdigest(),
            policy_raw=policy_raw,
            expected_policy_file_sha256=request["access_policy"]["file_sha256"],
            predeploy_receipt_raw=predeploy_raw,
            expected_predeploy_receipt_file_sha256=request["predeploy_receipt"][
                "file_sha256"
            ],
            evaluated_at=evaluated_at,
        )
        if pair.status != "ACCESS_PAIR_VERIFIED":
            raise StorageAuditCollectionError(
                "signed storage phase pair failed self-verification: "
                + ",".join(pair.failures)
            )
    else:
        proof = verify_storage_audit_bundle(
            bundle,
            policy=policy,
            expected=expected,
            phase=request["phase"],
            signer_dids=signer_dids,
            evaluated_at=evaluated_at,
        )
        if not proof.ok:
            raise StorageAuditCollectionError(
                "signed storage audit failed self-verification"
            )
    return bundle


def _publish_read_only(path: Path, document: Mapping[str, Any]) -> str:
    digest = live._publish_once(path, document)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        os.fchmod(fd, 0o400)
        os.fsync(fd)
        if stat.S_IMODE(os.fstat(fd).st_mode) != 0o400:
            raise StorageAuditCollectionError("bundle mode readback failed")
        raw = os.pread(fd, live.MAX_ARTIFACT_BYTES + 1, 0)
    finally:
        os.close(fd)
    if hashlib.sha256(raw).hexdigest() != digest:
        raise StorageAuditCollectionError("bundle exact readback failed")
    parent_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)
    return digest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--request-sha256", required=True)
    parser.add_argument("--postgresql-signing-key", required=True, type=Path)
    parser.add_argument("--neo4j-signing-key", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        request_raw, request_value, _request_info = live._load_pinned_json(
            args.request, args.request_sha256, max_bytes=live.MAX_REQUEST_BYTES
        )
        request = validate_request(request_value)
        request_file_sha256 = hashlib.sha256(request_raw).hexdigest()
        bundle = collect_signed_storage_audit(
            request,
            request_file_sha256=request_file_sha256,
            signing_seeds={
                "postgresql": load_signing_seed(args.postgresql_signing_key),
                "neo4j": load_signing_seed(args.neo4j_signing_key),
            },
        )
        file_sha = _publish_read_only(args.output, bundle)
        print(json.dumps({
            "schema_version": WRITE_RECEIPT_SCHEMA,
            "status": "WRITTEN",
            "phase": request["phase"],
            "bundle_file_sha256": file_sha,
            "claim_boundary": CLAIM_BOUNDARY,
        }, sort_keys=True))
        return 0
    except Exception:  # noqa: BLE001 - CLI must not expose credentials/paths/details
        print(json.dumps({
            "schema_version": WRITE_RECEIPT_SCHEMA,
            "status": "INVALID",
            "claim_boundary": CLAIM_BOUNDARY,
        }, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
