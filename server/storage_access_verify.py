"""Pinned raw-byte verifier for the signed datastore access phase pair.

This surface is deliberately read-only.  It does not connect to a datastore,
load audit credentials, approve a deploy, or mutate runtime state.  Supported
production launchers use its exit status as a static evidence preflight; the
application repeats the same verification before opening readiness or critique
writer authority.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from server.settings import ServerSettings
from server.storage_access import (
    MAX_DOCUMENT_BYTES,
    strict_json_loads,
    validate_access_policy,
    verify_access_attestation_pair_bytes,
)
from server.storage_protocol import STORAGE_CONTRACT_ID


_FORBIDDEN_RUNTIME_AUTHORITY_ENV = {
    "LAKATOS_STORAGE_PG_MIGRATION_USER",
    "LAKATOS_STORAGE_PG_MIGRATION_PASSWORD",
    "LAKATOS_STORAGE_PG_MIGRATION_DSN",
    "LAKATOS_STORAGE_NEO4J_MIGRATION_URI",
    "LAKATOS_STORAGE_NEO4J_MIGRATION_USER",
    "LAKATOS_STORAGE_NEO4J_MIGRATION_PASSWORD",
    "LAKATOTREE_READINESS_PG_DSN",
    "LAKATOTREE_READINESS_NEO4J_URI",
    "LAKATOTREE_READINESS_NEO4J_USER",
    "LAKATOTREE_READINESS_NEO4J_PASSWORD",
}


class _PinnedArtifactError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _exact_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _load_pinned_raw(path_value: Any, sha_value: Any, *, label: str) -> bytes:
    if not isinstance(path_value, str) or not path_value:
        raise _PinnedArtifactError(f"storage_access.{label}.path_missing")
    if not _exact_sha256(sha_value):
        raise _PinnedArtifactError(f"storage_access.{label}.sha256_missing")
    path = Path(path_value)
    if not path.is_absolute():
        raise _PinnedArtifactError(f"storage_access.{label}.path_invalid")
    try:
        info = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise _PinnedArtifactError(
            f"storage_access.{label}.unavailable"
        ) from exc
    if (
        resolved != path
        or stat.S_ISLNK(info.st_mode)
        or not stat.S_ISREG(info.st_mode)
        or bool(info.st_mode & 0o222)
        or info.st_size > MAX_DOCUMENT_BYTES
    ):
        raise _PinnedArtifactError(f"storage_access.{label}.unsafe_file")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise _PinnedArtifactError(
            f"storage_access.{label}.unavailable"
        ) from exc
    try:
        opened = os.fstat(descriptor)
        if (
            (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)
            or not stat.S_ISREG(opened.st_mode)
            or bool(opened.st_mode & 0o222)
            or opened.st_size > MAX_DOCUMENT_BYTES
        ):
            raise _PinnedArtifactError(f"storage_access.{label}.changed_during_open")
        raw = os.pread(descriptor, MAX_DOCUMENT_BYTES + 1, 0)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        len(raw) > MAX_DOCUMENT_BYTES
        or (after.st_dev, after.st_ino, after.st_size)
        != (opened.st_dev, opened.st_ino, opened.st_size)
    ):
        raise _PinnedArtifactError(f"storage_access.{label}.changed_during_read")
    if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), sha_value):
        raise _PinnedArtifactError(f"storage_access.{label}.sha256_mismatch")
    return raw


def _not_ready(*failures: str) -> dict[str, Any]:
    return {
        "contract_id": STORAGE_CONTRACT_ID,
        "ok": False,
        "status": "NOT_READY",
        "production_ready": False,
        "deployment_status": "NOT_READY",
        "failures": sorted(set(failures)) or ["storage_access.unverified"],
        "valid_until": None,
    }


def verify_pinned_storage_access(
    settings: ServerSettings,
    *,
    evaluated_at: datetime | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Verify the exact policy, receipt, and phase-pair files named by settings."""

    try:
        environ = os.environ if environ is None else environ
        migration_values = (
            getattr(settings, "pg_migration_dsn", None),
            getattr(settings, "pg_migration_user", None),
            getattr(settings, "pg_migration_password", None),
            getattr(settings, "neo4j_migration_uri", None),
            getattr(settings, "neo4j_migration_user", None),
            getattr(settings, "neo4j_migration_password", None),
        )
        if any(value is not None for value in migration_values) or any(
            key in environ for key in _FORBIDDEN_RUNTIME_AUTHORITY_ENV
        ):
            return _not_ready("storage_access.one_shot_authority_present")
        artifacts = {
            "policy": _load_pinned_raw(
                settings.storage_access_policy,
                settings.storage_access_policy_sha256,
                label="policy",
            ),
            "receipt": _load_pinned_raw(
                settings.storage_predeploy_receipt,
                settings.storage_predeploy_receipt_sha256,
                label="predeploy_receipt",
            ),
            "predeploy": _load_pinned_raw(
                settings.storage_access_predeploy_bundle,
                settings.storage_access_predeploy_bundle_sha256,
                label="predeploy_bundle",
            ),
            "startup": _load_pinned_raw(
                settings.storage_access_startup_bundle,
                settings.storage_access_startup_bundle_sha256,
                label="startup_bundle",
            ),
        }
        evaluated_at = evaluated_at or datetime.now(timezone.utc)
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            return _not_ready("storage_access.evaluation_time_invalid")
        evaluated_at = evaluated_at.astimezone(timezone.utc)
        policy = validate_access_policy(strict_json_loads(artifacts["policy"]))
        runtime_pg_binding = settings.pg_runtime_binding()
        runtime_binding_ok = (
            policy["environment"] == settings.storage_environment
            and policy["postgresql"]["host"] == settings.pg_host
            and policy["postgresql"]["port"] == settings.pg_port
            and policy["postgresql"]["database"] == settings.pg_db
            and policy["postgresql"]["runtime_role"] == settings.pg_user
            and policy["postgresql"]["runtime_profile_sha256"]
            == runtime_pg_binding["profile_sha256"]
            and policy["postgresql"]["runtime_ca_sha256"]
            == runtime_pg_binding["ca_sha256"]
            and policy["neo4j"]["uri"] == settings.neo4j_uri
            and policy["neo4j"]["database"] == settings.neo4j_database
            and policy["neo4j"]["runtime_user"] == settings.neo4j_user
            and policy["predeploy_authority"]["fence_verifier_sha256"]
            == settings.storage_fence_verifier_sha256
            and policy["predeploy_authority"]["fence_public_key_hex"]
            == settings.storage_fence_public_key_hex
        )
        if not runtime_binding_ok:
            return _not_ready("storage_access.runtime_binding_mismatch")
        proof = verify_access_attestation_pair_bytes(
            artifacts["predeploy"],
            artifacts["startup"],
            expected_predeploy_file_sha256=(
                settings.storage_access_predeploy_bundle_sha256 or ""
            ),
            expected_startup_file_sha256=(
                settings.storage_access_startup_bundle_sha256 or ""
            ),
            policy_raw=artifacts["policy"],
            expected_policy_file_sha256=(
                settings.storage_access_policy_sha256 or ""
            ),
            predeploy_receipt_raw=artifacts["receipt"],
            expected_predeploy_receipt_file_sha256=(
                settings.storage_predeploy_receipt_sha256 or ""
            ),
            evaluated_at=evaluated_at,
        )
        ok = proof.status == "ACCESS_PAIR_VERIFIED"
        valid_until = None
        if ok:
            startup = strict_json_loads(artifacts["startup"])
            expiry_values = [
                startup["attestations"][store][position]["expires_at"]
                for store in ("postgresql", "neo4j")
                for position in ("before", "after")
            ]
            expiries = [
                datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
                    timezone.utc
                )
                for value in expiry_values
            ]
            valid_until = min(expiries).isoformat()
        return {
            "contract_id": STORAGE_CONTRACT_ID,
            "ok": ok,
            "status": proof.status if ok else "NOT_READY",
            "production_ready": False,
            # A verified development pair reports DEVELOPMENT_ONLY here so no
            # consumer expecting the production NOT_READY shape accepts it.
            "deployment_status": (
                getattr(proof, "deployment_status", "NOT_READY")
                if ok
                else "NOT_READY"
            ),
            "failures": [] if ok else list(proof.failures),
            "valid_until": valid_until,
            **(
                {
                    "environment": getattr(proof, "environment", None),
                    "policy_file_sha256": settings.storage_access_policy_sha256,
                    "predeploy_receipt_file_sha256": (
                        settings.storage_predeploy_receipt_sha256
                    ),
                    "predeploy_bundle_file_sha256": (
                        settings.storage_access_predeploy_bundle_sha256
                    ),
                    "startup_bundle_file_sha256": (
                        settings.storage_access_startup_bundle_sha256
                    ),
                    "target_sha256": getattr(proof, "target_sha256", None),
                    "operation_sha256": getattr(proof, "operation_sha256", None),
                    "artifact_identity_sha256": getattr(
                        proof, "artifact_identity_sha256", None
                    ),
                    "predeploy_receipt_sha256": getattr(
                        proof, "predeploy_receipt_sha256", None
                    ),
                }
                if ok
                else {}
            ),
        }
    except _PinnedArtifactError as exc:
        return _not_ready(exc.code)
    except Exception:  # noqa: BLE001 - never expose paths, signatures, or parser details
        return _not_ready("storage_access.verifier_failed")


def _parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description="Verify the pinned signed datastore access phase pair from runtime env"
    )


def main(argv: Sequence[str] | None = None) -> int:
    _parser().parse_args(argv)
    report = verify_pinned_storage_access(ServerSettings.from_env())
    sys.stdout.write(
        json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    )
    return 0 if report["status"] == "ACCESS_PAIR_VERIFIED" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
