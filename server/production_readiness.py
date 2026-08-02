"""Credential-free case evaluator for the production/L3 readiness harness.

The evaluator is a dependency-free L_IDE control over future L_RT/L_MC live
adapters.  It consumes a strictly shaped case; the installed CLI additionally
binds exact raw bytes to a caller-supplied SHA-256 before local cryptographic and
semantic verification. It does so without reading environment variables,
opening sockets, consulting a wall clock, spawning processes, or mutating state.

``CASE_ACCEPTED`` means one case is internally consistent.  Only the separately
locked OOPTDD suite runs the positive fixture and every declared negative control;
that suite, not this function, may use the phrase ``HARNESS_GREEN``.  No path in
this module grants production approval or runtime VAL L3.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import stat
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from lakatos.temporal import AnchorInvalid, verify_temporal_anchor
from lakatos.write_cert import (
    CertError,
    did_key_decode,
    did_key_encode,
    ed25519_public_key_is_strict,
    ed25519_verify,
)
from server.storage_protocol import (
    FENCE_RESPONSE_FIELDS,
    FENCE_SIGNATURE_DOMAIN,
    FENCE_VERIFICATION_SCHEMA,
    STORAGE_CONTRACT_ID,
)


CASE_SCHEMA = "lakatotree-production-l3-readiness-case/v1"
CASE_REPORT_SCHEMA = "lakatotree-production-l3-readiness-case-report/v1"
ERROR_SCHEMA = "lakatotree-production-l3-readiness-error/v1"
SIDECAR_SCHEMA = "lakatotree-two-ended-temporal-sidecar/v1"
AUTHORITY_POLICY_SCHEMA = "lakatotree-temporal-authority-policy/v1"
TEMPORAL_BINDING_SCHEMA = "lakatotree-temporal-runtime-binding/v1"
PG_ACCESS_SCHEMA = "lakatotree-postgresql-access-projection/v1"
NEO4J_ACCESS_SCHEMA = "lakatotree-neo4j-access-projection/v1"
RUNTIME_SCHEMA = "lakatotree-runtime-readiness-projection/v1"
HARNESS_TIER = "L_IDE"
TARGET_TIERS = ("L_RT", "L_MC")
MAX_EVIDENCE_BYTES = 2 * 1024 * 1024
MAX_LIST_ITEMS = 64
MAX_TEMPORAL_ANCHORS = 32
MAX_JSON_NESTING = 64
CLAIM_BOUNDARY = (
    "CASE_ACCEPTED proves only that one exact case is internally consistent. A raw-byte "
    "digest binding exists only when evidence_bytes_bound is true; the installed CLI "
    "additionally enforces an absolute, regular, non-symlink input path. "
    "It does not prove that the locked negative-control suite ran, inspect a live "
    "deployment, authorize a writer drain, establish real database role separation, "
    "or enable runtime VAL L3. HARNESS_GREEN belongs only to the separately locked "
    "OOPTDD suite, and production_ready remains false until independently audited live "
    "adapters exist."
)

_PG_TABLES = (
    "public.history",
    "public.history_event_claims",
    "public.metric_snapshots",
    "public.lineage",
)
_PG_SEQUENCES = (
    "public.history_id_seq",
    "public.metric_snapshots_id_seq",
    "public.lineage_id_seq",
)
_PG_ROLE_ATTRIBUTE_KEYS = {
    "login",
    "superuser",
    "createdb",
    "createrole",
    "inherit",
    "bypassrls",
    "replication",
}
_NEO4J_BUILTIN_ADMIN_ROLES = {
    "admin",
    "architect",
    "editor",
    "publisher",
    "reader",
    "public",
}
_ANCHOR_KEYS = {"witness_did", "digest", "gen_time", "signature", "channel"}


class HarnessInputError(ValueError):
    """The evidence envelope is ambiguous or not the declared schema."""


@dataclass(frozen=True)
class LoadedEvidence:
    """Immutable evidence bytes plus the digest they must match at evaluation time."""

    raw: bytes
    file_sha256: str


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise HarnessInputError("evidence must be finite canonical JSON") from exc


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _exact_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _strict_json_loads(value: bytes) -> Any:
    depth = 0
    in_string = False
    escaped = False
    for byte in value:
        if in_string:
            if escaped:
                escaped = False
            elif byte == 0x5C:  # backslash
                escaped = True
            elif byte == 0x22:  # quote
                in_string = False
            continue
        if byte == 0x22:
            in_string = True
        elif byte in (0x5B, 0x7B):  # [ {
            depth += 1
            if depth > MAX_JSON_NESTING:
                raise HarnessInputError("evidence JSON exceeds bounded nesting")
        elif byte in (0x5D, 0x7D) and depth:  # ] }
            depth -= 1

    def object_pairs(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise HarnessInputError("duplicate JSON object key")
            result[key] = item
        return result

    def reject_constant(token: str):
        raise HarnessInputError(f"non-finite JSON number is forbidden: {token}")

    try:
        return json.loads(
            value,
            object_pairs_hook=object_pairs,
            parse_constant=reject_constant,
        )
    except HarnessInputError:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise HarnessInputError("evidence is not valid UTF-8 JSON") from exc


def _exact_mapping(value: Any, *, path: str, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise HarnessInputError(f"{path} must be an object")
    observed = set(value)
    if observed != keys:
        missing = sorted(keys - observed)
        unknown = sorted(observed - keys)
        raise HarnessInputError(
            f"{path} has a non-exact field set; missing={missing}, "
            f"unknown_count={len(unknown)}"
        )
    return value


def _text(value: Any, *, path: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
    ):
        raise HarnessInputError(f"{path} must be a canonical non-empty string")
    return value


def _sha(value: Any, *, path: str) -> str:
    if not _exact_sha256(value):
        raise HarnessInputError(f"{path} must be a lowercase SHA-256")
    return value


def _lower_hex(value: Any, *, path: str, size: int) -> str:
    if not (
        isinstance(value, str)
        and len(value) == size * 2
        and all(char in "0123456789abcdef" for char in value)
    ):
        raise HarnessInputError(f"{path} must be {size}-byte lowercase hex")
    return value


def _boolean(value: Any, *, path: str) -> bool:
    if type(value) is not bool:
        raise HarnessInputError(f"{path} must be a boolean")
    return value


def _nonnegative_int(value: Any, *, path: str) -> int:
    if type(value) is not int or value < 0:
        raise HarnessInputError(f"{path} must be a non-negative integer")
    return value


def _string_list(value: Any, *, path: str, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        qualifier = "non-empty " if not allow_empty else ""
        raise HarnessInputError(f"{path} must be a {qualifier}list")
    if len(value) > MAX_LIST_ITEMS:
        raise HarnessInputError(f"{path} exceeds the bounded list size")
    return [_text(item, path=f"{path}[{index}]") for index, item in enumerate(value)]


def _canonical_did(value: Any, *, path: str) -> tuple[str, bytes]:
    did = _text(value, path=path)
    try:
        public_key = did_key_decode(did)
    except (CertError, ValueError, TypeError, AttributeError) as exc:
        raise HarnessInputError(f"{path} must be canonical Ed25519 did:key") from exc
    if did_key_encode(public_key) != did or not ed25519_public_key_is_strict(public_key):
        raise HarnessInputError(f"{path} must be canonical prime-subgroup Ed25519 did:key")
    return did, public_key


def _canonical_did_list(
    value: Any,
    *,
    path: str,
    allow_empty: bool = True,
) -> tuple[list[str], list[bytes]]:
    values = _string_list(value, path=path, allow_empty=allow_empty)
    parsed = [
        _canonical_did(item, path=f"{path}[{index}]")
        for index, item in enumerate(values)
    ]
    return [item[0] for item in parsed], [item[1] for item in parsed]


def _parse_time(value: Any, *, path: str) -> datetime:
    timestamp = _text(value, path=path)
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("timezone-aware timestamp required")
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise HarnessInputError(
            f"{path} must be a bounded timezone-aware ISO-8601 timestamp"
        ) from exc


def _record(failures: list[str], condition: bool, code: str) -> bool:
    if not condition:
        failures.append(code)
        return False
    return True


def _domain_sha256(domain: bytes, value: Any) -> str:
    return _sha256(domain + _canonical(value))


def temporal_authority_policy_sha256(policy: Mapping[str, Any]) -> str:
    return _domain_sha256(b"lakatotree-temporal-authority-policy/v1\0", policy)


def temporal_sidecar_sha256(sidecar: Mapping[str, Any]) -> str:
    return _domain_sha256(b"lakatotree-two-ended-temporal-sidecar/v1\0", sidecar)


def _binding(
    value: Any,
    *,
    path: str,
    expected: Mapping[str, Any],
    failures: list[str],
    prefix: str,
) -> dict[str, Any]:
    binding = _exact_mapping(
        value,
        path=path,
        keys={"target_sha256", "operation_sha256", "predeploy_file_sha256"},
    )
    for field in binding:
        _sha(binding[field], path=f"{path}.{field}")
    _record(
        failures,
        hmac.compare_digest(binding["target_sha256"], expected["target_sha256"]),
        f"{prefix}.target_mismatch",
    )
    _record(
        failures,
        hmac.compare_digest(binding["operation_sha256"], expected["operation_sha256"]),
        f"{prefix}.operation_mismatch",
    )
    _record(
        failures,
        hmac.compare_digest(
            binding["predeploy_file_sha256"], expected["predeploy_file_sha256"]
        ),
        f"{prefix}.predeploy_receipt_mismatch",
    )
    return binding


def _privilege_map(
    value: Any,
    *,
    path: str,
    expected_objects: Sequence[str],
) -> dict[str, list[str]]:
    mapping = _exact_mapping(value, path=path, keys=set(expected_objects))
    return {
        object_name: _string_list(mapping[object_name], path=f"{path}.{object_name}")
        for object_name in expected_objects
    }


def _evaluate_predeploy(
    value: Any,
    *,
    expected: Mapping[str, Any],
    evaluated_at: datetime,
    failures: list[str],
) -> tuple[dict[str, Any], datetime]:
    predeploy = _exact_mapping(
        value,
        path="storage.predeploy",
        keys={
            "ok",
            "contract_id",
            "file_sha256",
            "receipt_sha256",
            "environment",
            "created_at",
            "target_sha256",
            "operation_sha256",
        },
    )
    _boolean(predeploy["ok"], path="storage.predeploy.ok")
    _text(predeploy["contract_id"], path="storage.predeploy.contract_id")
    _text(predeploy["environment"], path="storage.predeploy.environment")
    for field in ("file_sha256", "receipt_sha256", "target_sha256", "operation_sha256"):
        _sha(predeploy[field], path=f"storage.predeploy.{field}")
    created_at = _parse_time(predeploy["created_at"], path="storage.predeploy.created_at")
    local: list[str] = []
    _record(local, predeploy["ok"] is True, "storage.predeploy.not_verified")
    _record(
        local,
        predeploy["contract_id"] == expected["contract_id"],
        "storage.predeploy.contract_mismatch",
    )
    _record(
        local,
        predeploy["environment"] == expected["environment"],
        "storage.predeploy.environment_mismatch",
    )
    for field in (
        "target_sha256",
        "operation_sha256",
        "file_sha256",
        "receipt_sha256",
    ):
        expected_name = {
            "file_sha256": "predeploy_file_sha256",
            "receipt_sha256": "predeploy_receipt_sha256",
        }.get(field, field)
        _record(
            local,
            hmac.compare_digest(predeploy[field], expected[expected_name]),
            f"storage.predeploy.{field.removesuffix('_sha256')}_mismatch",
        )
    _record(
        local,
        created_at <= evaluated_at,
        "storage.predeploy.created_after_evaluation",
    )
    failures.extend(local)
    return {"ok": not local}, created_at


def _evaluate_writer_fence(
    value: Any,
    *,
    expected: Mapping[str, Any],
    evaluated_at: datetime,
    predeploy_created_at: datetime,
    failures: list[str],
) -> dict[str, Any]:
    fence = _exact_mapping(
        value,
        path="storage.writer_fence",
        keys={
            "authority_public_key_hex",
            "authority_key_sha256",
            "nonce_reuse_count",
            "listener_count",
            "replica_count",
            "writer_count",
            "signed_response",
        },
    )
    public_key_hex = _lower_hex(
        fence["authority_public_key_hex"],
        path="storage.writer_fence.authority_public_key_hex",
        size=32,
    )
    public_key = bytes.fromhex(public_key_hex)
    authority_key_sha256 = _sha256(public_key)
    _sha(
        fence["authority_key_sha256"],
        path="storage.writer_fence.authority_key_sha256",
    )
    for field in ("nonce_reuse_count", "listener_count", "replica_count", "writer_count"):
        _nonnegative_int(fence[field], path=f"storage.writer_fence.{field}")
    response = _exact_mapping(
        fence["signed_response"],
        path="storage.writer_fence.signed_response",
        keys=set(FENCE_RESPONSE_FIELDS),
    )
    signature_hex = _lower_hex(
        response["signature"],
        path="storage.writer_fence.signed_response.signature",
        size=64,
    )
    signed_body = dict(response)
    signed_body.pop("signature")
    for field in (
        "schema_version",
        "nonce",
        "environment",
        "lease_id",
        "verified_at",
        "expires_at",
    ):
        _text(signed_body[field], path=f"storage.writer_fence.signed_response.{field}")
    _boolean(
        signed_body["active"], path="storage.writer_fence.signed_response.active"
    )
    for field in ("target_sha256", "operation_sha256", "drain_receipt_sha256"):
        _sha(signed_body[field], path=f"storage.writer_fence.signed_response.{field}")
    _lower_hex(
        signed_body["nonce"],
        path="storage.writer_fence.signed_response.nonce",
        size=32,
    )
    evidence_refs = _string_list(
        signed_body["evidence_refs"],
        path="storage.writer_fence.signed_response.evidence_refs",
        allow_empty=False,
    )
    verified_at = _parse_time(
        signed_body["verified_at"],
        path="storage.writer_fence.signed_response.verified_at",
    )
    expires_at = _parse_time(
        signed_body["expires_at"],
        path="storage.writer_fence.signed_response.expires_at",
    )
    signature_valid = (
        ed25519_public_key_is_strict(public_key)
        and ed25519_verify(
            public_key,
            FENCE_SIGNATURE_DOMAIN + _canonical(signed_body),
            bytes.fromhex(signature_hex),
        )
    )
    local: list[str] = []
    _record(
        local,
        hmac.compare_digest(authority_key_sha256, fence["authority_key_sha256"]),
        "storage.fence.authority_key_self_mismatch",
    )
    _record(
        local,
        hmac.compare_digest(
            authority_key_sha256, expected["fence_authority_key_sha256"]
        ),
        "storage.fence.authority_key_pin_mismatch",
    )
    _record(local, signature_valid, "storage.fence.signature_invalid")
    _record(
        local,
        signed_body["schema_version"] == FENCE_VERIFICATION_SCHEMA,
        "storage.fence.schema_mismatch",
    )
    _record(local, signed_body["active"] is True, "storage.fence.inactive")
    for field in ("environment", "target_sha256", "operation_sha256"):
        _record(
            local,
            hmac.compare_digest(str(signed_body[field]), str(expected[field])),
            f"storage.fence.{field.removesuffix('_sha256')}_mismatch",
        )
    _record(
        local,
        hmac.compare_digest(signed_body["nonce"], expected["fence_nonce"]),
        "storage.fence.nonce_mismatch",
    )
    _record(
        local,
        signed_body["lease_id"] == expected["writer_lease_id"],
        "storage.fence.lease_mismatch",
    )
    _record(
        local,
        hmac.compare_digest(
            signed_body["drain_receipt_sha256"], expected["writer_drain_receipt_sha256"]
        ),
        "storage.fence.drain_receipt_mismatch",
    )
    _record(local, fence["nonce_reuse_count"] == 0, "storage.fence.nonce_replayed")
    _record(local, fence["listener_count"] == 0, "storage.fence.listeners_not_drained")
    _record(local, fence["replica_count"] == 0, "storage.fence.replicas_not_drained")
    _record(local, fence["writer_count"] == 0, "storage.fence.writers_not_drained")
    _record(
        local,
        len(set(evidence_refs)) == len(evidence_refs),
        "storage.fence.duplicate_evidence_ref",
    )
    _record(
        local,
        verified_at <= predeploy_created_at <= evaluated_at < expires_at,
        "storage.fence.time_window_invalid",
    )
    _record(
        local,
        timedelta(0) < expires_at - verified_at <= timedelta(seconds=60),
        "storage.fence.validity_window_too_large",
    )
    _record(
        local,
        evaluated_at - verified_at <= timedelta(seconds=30),
        "storage.fence.verification_too_old",
    )
    _record(
        local,
        expires_at - evaluated_at >= timedelta(seconds=5),
        "storage.fence.expiry_margin_too_small",
    )
    failures.extend(local)
    return {
        "ok": not local,
        "signature_valid": signature_valid,
        "evidence_ref_count": len(evidence_refs),
    }


def _evaluate_postgresql_access(
    value: Any,
    *,
    expected: Mapping[str, Any],
    failures: list[str],
) -> dict[str, Any]:
    pg = _exact_mapping(
        value,
        path="storage.postgresql_access",
        keys={
            "schema_version",
            "binding",
            "database",
            "owner_role",
            "owner_can_login",
            "owner_role_attributes",
            "migrator_role",
            "migrator_role_attributes",
            "runtime_role",
            "predeploy_actor",
            "startup_actor",
            "runtime_role_attributes",
            "runtime_table_privileges",
            "runtime_sequence_privileges",
            "runtime_schema_privileges",
            "runtime_owns_objects",
            "runtime_ddl",
            "object_owners",
            "public_grants",
            "role_memberships",
        },
    )
    local: list[str] = []
    _text(pg["schema_version"], path="storage.postgresql_access.schema_version")
    _binding(
        pg["binding"],
        path="storage.postgresql_access.binding",
        expected=expected,
        failures=local,
        prefix="storage.postgresql",
    )
    for field in (
        "database",
        "owner_role",
        "migrator_role",
        "runtime_role",
        "predeploy_actor",
        "startup_actor",
    ):
        _text(pg[field], path=f"storage.postgresql_access.{field}")
    _boolean(pg["owner_can_login"], path="storage.postgresql_access.owner_can_login")
    _boolean(pg["runtime_owns_objects"], path="storage.postgresql_access.runtime_owns_objects")
    _boolean(pg["runtime_ddl"], path="storage.postgresql_access.runtime_ddl")
    owner_attributes = _exact_mapping(
        pg["owner_role_attributes"],
        path="storage.postgresql_access.owner_role_attributes",
        keys=_PG_ROLE_ATTRIBUTE_KEYS,
    )
    migrator_attributes = _exact_mapping(
        pg["migrator_role_attributes"],
        path="storage.postgresql_access.migrator_role_attributes",
        keys=_PG_ROLE_ATTRIBUTE_KEYS,
    )
    attributes = _exact_mapping(
        pg["runtime_role_attributes"],
        path="storage.postgresql_access.runtime_role_attributes",
        keys=_PG_ROLE_ATTRIBUTE_KEYS,
    )
    for role_name, role_attributes in (
        ("owner", owner_attributes),
        ("migrator", migrator_attributes),
        ("runtime", attributes),
    ):
        for field in role_attributes:
            _boolean(
                role_attributes[field],
                path=f"storage.postgresql_access.{role_name}_role_attributes.{field}",
            )
    table_privileges = _privilege_map(
        pg["runtime_table_privileges"],
        path="storage.postgresql_access.runtime_table_privileges",
        expected_objects=_PG_TABLES,
    )
    sequence_privileges = _privilege_map(
        pg["runtime_sequence_privileges"],
        path="storage.postgresql_access.runtime_sequence_privileges",
        expected_objects=_PG_SEQUENCES,
    )
    schema_privileges = _privilege_map(
        pg["runtime_schema_privileges"],
        path="storage.postgresql_access.runtime_schema_privileges",
        expected_objects=("public",),
    )
    object_names = (*_PG_TABLES, *_PG_SEQUENCES, "public")
    object_owners = _exact_mapping(
        pg["object_owners"],
        path="storage.postgresql_access.object_owners",
        keys=set(object_names),
    )
    for object_name in object_names:
        _text(
            object_owners[object_name],
            path=f"storage.postgresql_access.object_owners.{object_name}",
        )
    public_grants = _string_list(
        pg["public_grants"], path="storage.postgresql_access.public_grants"
    )
    role_memberships = _string_list(
        pg["role_memberships"], path="storage.postgresql_access.role_memberships"
    )
    _record(local, pg["schema_version"] == PG_ACCESS_SCHEMA,
            "storage.postgresql.schema_mismatch")
    _record(local, pg["database"] == expected["postgresql_database"],
            "storage.postgresql.database_mismatch")
    roles = {pg["owner_role"], pg["migrator_role"], pg["runtime_role"]}
    _record(local, len(roles) == 3, "storage.postgresql.roles_not_separated")
    _record(local, pg["owner_can_login"] is False, "storage.postgresql.owner_can_login")
    _record(
        local,
        all(owner_attributes[field] is False for field in _PG_ROLE_ATTRIBUTE_KEYS),
        "storage.postgresql.owner_role_attributes",
    )
    _record(
        local,
        migrator_attributes["login"] is True
        and all(
            migrator_attributes[field] is False
            for field in _PG_ROLE_ATTRIBUTE_KEYS - {"login"}
        ),
        "storage.postgresql.migrator_role_attributes",
    )
    _record(local, pg["predeploy_actor"] == pg["migrator_role"],
            "storage.postgresql.predeploy_actor_mismatch")
    _record(local, pg["startup_actor"] == pg["runtime_role"],
            "storage.postgresql.startup_actor_mismatch")
    _record(local, attributes["login"] is True,
            "storage.postgresql.runtime_login_missing")
    _record(
        local,
        all(attributes[field] is False for field in _PG_ROLE_ATTRIBUTE_KEYS - {"login"}),
        "storage.postgresql.runtime_role_attributes",
    )
    _record(local, pg["runtime_owns_objects"] is False,
            "storage.postgresql.runtime_owns_objects")
    _record(local, pg["runtime_ddl"] is False,
            "storage.postgresql.runtime_has_ddl")
    _record(
        local,
        all(set(items) == {"SELECT", "INSERT"} and len(items) == 2
            for items in table_privileges.values()),
        "storage.postgresql.runtime_table_privileges",
    )
    _record(
        local,
        all(set(items) == {"SELECT", "USAGE"} and len(items) == 2
            for items in sequence_privileges.values()),
        "storage.postgresql.runtime_sequence_privileges",
    )
    _record(local, schema_privileges["public"] == ["USAGE"],
            "storage.postgresql.runtime_schema_privileges")
    _record(
        local,
        all(object_owners[object_name] == pg["owner_role"] for object_name in object_names),
        "storage.postgresql.object_ownership",
    )
    _record(local, not public_grants, "storage.postgresql.public_grants_present")
    _record(local, not role_memberships, "storage.postgresql.role_membership_present")
    failures.extend(local)
    return {
        "ok": not local,
        "roles_separated": len(roles) == 3,
        "object_ownership_bound": all(
            object_owners[object_name] == pg["owner_role"] for object_name in object_names
        ),
    }


def _evaluate_neo4j_access(
    value: Any,
    *,
    expected: Mapping[str, Any],
    failures: list[str],
) -> dict[str, Any]:
    neo = _exact_mapping(
        value,
        path="storage.neo4j_access",
        keys={
            "schema_version",
            "binding",
            "edition",
            "database",
            "migrator_principal",
            "runtime_principal",
            "predeploy_actor",
            "startup_actor",
            "runtime_roles",
            "migrator_roles",
            "runtime_effective_privileges",
            "migrator_effective_privileges",
            "built_in_admin_roles",
            "public_role_bindings",
        },
    )
    local: list[str] = []
    _text(neo["schema_version"], path="storage.neo4j_access.schema_version")
    _binding(
        neo["binding"],
        path="storage.neo4j_access.binding",
        expected=expected,
        failures=local,
        prefix="storage.neo4j",
    )
    for field in (
        "edition",
        "database",
        "migrator_principal",
        "runtime_principal",
        "predeploy_actor",
        "startup_actor",
    ):
        _text(neo[field], path=f"storage.neo4j_access.{field}")
    runtime_roles = _string_list(
        neo["runtime_roles"], path="storage.neo4j_access.runtime_roles", allow_empty=False
    )
    migrator_roles = _string_list(
        neo["migrator_roles"], path="storage.neo4j_access.migrator_roles", allow_empty=False
    )
    runtime_privileges = _string_list(
        neo["runtime_effective_privileges"],
        path="storage.neo4j_access.runtime_effective_privileges",
    )
    migrator_privileges = _string_list(
        neo["migrator_effective_privileges"],
        path="storage.neo4j_access.migrator_effective_privileges",
    )
    built_in_admin_roles = _string_list(
        neo["built_in_admin_roles"], path="storage.neo4j_access.built_in_admin_roles"
    )
    public_role_bindings = _string_list(
        neo["public_role_bindings"], path="storage.neo4j_access.public_role_bindings"
    )
    _record(local, neo["schema_version"] == NEO4J_ACCESS_SCHEMA,
            "storage.neo4j.schema_mismatch")
    _record(local, neo["edition"].lower() == "enterprise",
            "storage.neo4j.enterprise_rbac_unavailable")
    _record(local, neo["database"] == expected["neo4j_database"],
            "storage.neo4j.database_mismatch")
    _record(local, neo["migrator_principal"] != neo["runtime_principal"],
            "storage.neo4j.principals_not_separated")
    _record(local, neo["predeploy_actor"] == neo["migrator_principal"],
            "storage.neo4j.predeploy_actor_mismatch")
    _record(local, neo["startup_actor"] == neo["runtime_principal"],
            "storage.neo4j.startup_actor_mismatch")
    _record(local, len(set(runtime_roles)) == len(runtime_roles),
            "storage.neo4j.runtime_roles_not_unique")
    _record(local, len(set(migrator_roles)) == len(migrator_roles),
            "storage.neo4j.migrator_roles_not_unique")
    _record(local, not (set(runtime_roles) & set(migrator_roles)),
            "storage.neo4j.roles_not_separated")
    _record(
        local,
        not (
            {role.lower() for role in (*runtime_roles, *migrator_roles)}
            & _NEO4J_BUILTIN_ADMIN_ROLES
        ),
        "storage.neo4j.builtin_role_used",
    )
    _record(
        local,
        set(runtime_privileges) == {"ACCESS_DATABASE", "MATCH", "WRITE"}
        and len(runtime_privileges) == 3,
        "storage.neo4j.runtime_privileges",
    )
    _record(
        local,
        set(migrator_privileges)
        == {"ACCESS_DATABASE", "MATCH", "WRITE", "CONSTRAINT_MANAGEMENT"}
        and len(migrator_privileges) == 4,
        "storage.neo4j.migrator_privileges",
    )
    _record(local, not built_in_admin_roles, "storage.neo4j.builtin_admin_role_present")
    _record(local, not public_role_bindings, "storage.neo4j.public_role_binding_present")
    failures.extend(local)
    return {"ok": not local, "enterprise": neo["edition"].lower() == "enterprise"}


def _evaluate_runtime(
    value: Any,
    *,
    expected: Mapping[str, Any],
    failures: list[str],
) -> dict[str, Any]:
    runtime = _exact_mapping(
        value,
        path="storage.runtime",
        keys={
            "schema_version",
            "binding",
            "worker_count",
            "readyz",
            "storage_authority_current",
            "writer_lease_current",
            "writer_lease_id",
            "migration_environment_keys",
            "pending_outbox",
            "reconcile_conflicts",
            "reconcile_replay_count",
        },
    )
    local: list[str] = []
    _text(runtime["schema_version"], path="storage.runtime.schema_version")
    _text(runtime["writer_lease_id"], path="storage.runtime.writer_lease_id")
    _binding(
        runtime["binding"],
        path="storage.runtime.binding",
        expected=expected,
        failures=local,
        prefix="storage.runtime",
    )
    for field in ("readyz", "storage_authority_current", "writer_lease_current"):
        _boolean(runtime[field], path=f"storage.runtime.{field}")
    for field in ("worker_count", "pending_outbox", "reconcile_conflicts",
                  "reconcile_replay_count"):
        _nonnegative_int(runtime[field], path=f"storage.runtime.{field}")
    migration_keys = _string_list(
        runtime["migration_environment_keys"],
        path="storage.runtime.migration_environment_keys",
    )
    _record(local, runtime["schema_version"] == RUNTIME_SCHEMA,
            "storage.runtime.schema_mismatch")
    _record(local, runtime["worker_count"] == 1, "storage.runtime.worker_count_not_one")
    _record(local, runtime["readyz"] is True, "storage.runtime.readyz_not_green")
    _record(local, runtime["storage_authority_current"] is True,
            "storage.runtime.authority_stale")
    _record(local, runtime["writer_lease_current"] is True,
            "storage.runtime.writer_lease_lost")
    _record(local, runtime["writer_lease_id"] == expected["writer_lease_id"],
            "storage.runtime.writer_lease_mismatch")
    _record(local, not migration_keys, "storage.runtime.migration_credentials_present")
    _record(local, runtime["pending_outbox"] == 0, "storage.runtime.pending_outbox")
    _record(local, runtime["reconcile_conflicts"] == 0,
            "storage.runtime.reconcile_conflicts")
    _record(local, runtime["reconcile_replay_count"] == 0,
            "storage.runtime.reconcile_not_idempotent")
    failures.extend(local)
    return {"ok": not local, "worker_count": runtime["worker_count"]}


def _evaluate_storage(
    value: Any,
    *,
    expected: Mapping[str, Any],
    evaluated_at: datetime,
) -> tuple[dict[str, Any], list[str]]:
    storage = _exact_mapping(
        value,
        path="storage",
        keys={"predeploy", "writer_fence", "postgresql_access", "neo4j_access", "runtime"},
    )
    failures: list[str] = []
    predeploy, created_at = _evaluate_predeploy(
        storage["predeploy"], expected=expected, evaluated_at=evaluated_at, failures=failures
    )
    fence = _evaluate_writer_fence(
        storage["writer_fence"],
        expected=expected,
        evaluated_at=evaluated_at,
        predeploy_created_at=created_at,
        failures=failures,
    )
    pg = _evaluate_postgresql_access(
        storage["postgresql_access"], expected=expected, failures=failures
    )
    neo = _evaluate_neo4j_access(
        storage["neo4j_access"], expected=expected, failures=failures
    )
    runtime = _evaluate_runtime(storage["runtime"], expected=expected, failures=failures)
    return {
        "ok": not failures,
        "predeploy": predeploy,
        "writer_fence": fence,
        "postgresql_access": pg,
        "neo4j_access": neo,
        "runtime": runtime,
    }, failures


def _verified_anchor_times(
    anchors: Any,
    *,
    endpoint: str,
    receipt_sha256: str,
    allowlist: list[str],
    failures: list[str],
) -> dict[str, datetime]:
    if not isinstance(anchors, list):
        raise HarnessInputError(f"temporal.sidecar.{endpoint}_anchors must be a list")
    if len(anchors) > MAX_TEMPORAL_ANCHORS:
        raise HarnessInputError(
            f"temporal.sidecar.{endpoint}_anchors exceeds the bounded anchor count"
        )
    times: dict[str, datetime] = {}
    for index, raw_anchor in enumerate(anchors):
        path = f"temporal.sidecar.{endpoint}_anchors[{index}]"
        anchor = _exact_mapping(raw_anchor, path=path, keys=_ANCHOR_KEYS)
        witness, public_key = _canonical_did(
            anchor["witness_did"], path=f"{path}.witness_did"
        )
        key_identity = public_key.hex()
        _sha(anchor["digest"], path=f"{path}.digest")
        _parse_time(anchor["gen_time"], path=f"{path}.gen_time")
        _lower_hex(anchor["signature"], path=f"{path}.signature", size=64)
        channel = _text(anchor["channel"], path=f"{path}.channel")
        if key_identity in times:
            failures.append(f"temporal.{endpoint}_duplicate_authority")
            continue
        if channel != "ed25519-witness":
            failures.append(f"temporal.{endpoint}_channel_invalid")
        try:
            gen_time = verify_temporal_anchor(
                anchor,
                expect_receipt_sha=receipt_sha256,
                witness_allowlist=allowlist,
            )
        except AnchorInvalid:
            failures.append(f"temporal.{endpoint}_anchor_invalid")
            continue
        times[key_identity] = _parse_time(gen_time, path=f"{path}.gen_time")
        if did_key_encode(public_key) != witness:
            failures.append(f"temporal.{endpoint}_authority_noncanonical")
    return times


def _evaluate_temporal(
    value: Any,
    *,
    expected: Mapping[str, Any],
    evaluated_at: datetime,
) -> tuple[dict[str, Any], list[str]]:
    failures: list[str] = []
    temporal = _exact_mapping(
        value,
        path="temporal",
        keys={"authority_policy", "sidecar", "runtime_binding"},
    )
    policy = _exact_mapping(
        temporal["authority_policy"],
        path="temporal.authority_policy",
        keys={
            "schema_version",
            "threshold",
            "witness_allowlist",
            "producer_dids",
            "attestor_dids",
            "endpoint_signer_rule",
            "evidence_refs",
        },
    )
    _text(policy["schema_version"], path="temporal.authority_policy.schema_version")
    threshold = _nonnegative_int(
        policy["threshold"], path="temporal.authority_policy.threshold"
    )
    allowlist, allowlist_keys = _canonical_did_list(
        policy["witness_allowlist"],
        path="temporal.authority_policy.witness_allowlist",
        allow_empty=False,
    )
    producer_dids, producer_keys = _canonical_did_list(
        policy["producer_dids"],
        path="temporal.authority_policy.producer_dids",
        allow_empty=False,
    )
    attestor_dids, attestor_keys = _canonical_did_list(
        policy["attestor_dids"],
        path="temporal.authority_policy.attestor_dids",
        allow_empty=False,
    )
    signer_rule = _text(
        policy["endpoint_signer_rule"],
        path="temporal.authority_policy.endpoint_signer_rule",
    )
    policy_evidence = _string_list(
        policy["evidence_refs"],
        path="temporal.authority_policy.evidence_refs",
        allow_empty=False,
    )
    allow_key_ids = [key.hex() for key in allowlist_keys]
    producer_key_ids = [key.hex() for key in producer_keys]
    attestor_key_ids = [key.hex() for key in attestor_keys]
    _record(failures, policy["schema_version"] == AUTHORITY_POLICY_SCHEMA,
            "temporal.authority_policy_schema_mismatch")
    _record(failures, threshold >= 2, "temporal.threshold_below_two")
    _record(failures, len(set(allow_key_ids)) == len(allow_key_ids),
            "temporal.authority_allowlist_not_unique")
    _record(failures, len(allow_key_ids) >= threshold,
            "temporal.authority_policy_too_small")
    _record(failures, len(set(producer_key_ids)) == len(producer_key_ids),
            "temporal.producer_roles_not_unique")
    _record(failures, len(set(attestor_key_ids)) == len(attestor_key_ids),
            "temporal.attestor_roles_not_unique")
    _record(failures, not (set(producer_key_ids) & set(attestor_key_ids)),
            "temporal.producer_attestor_role_overlap")
    forbidden = set(producer_key_ids) | set(attestor_key_ids)
    _record(failures, not (set(allow_key_ids) & forbidden),
            "temporal.authority_role_overlap")
    _record(failures, signer_rule == "same-authority-set",
            "temporal.endpoint_signer_rule_unsupported")
    _record(failures, len(set(policy_evidence)) == len(policy_evidence),
            "temporal.policy_evidence_not_unique")
    policy_sha256 = temporal_authority_policy_sha256(policy)

    sidecar = _exact_mapping(
        temporal["sidecar"],
        path="temporal.sidecar",
        keys={
            "schema_version",
            "authority_policy_sha256",
            "threshold",
            "witness_allowlist",
            "prediction_receipt_sha256",
            "verdict_receipt_sha256",
            "receipt_graph_sha256",
            "prediction_anchors",
            "verdict_anchors",
        },
    )
    _text(sidecar["schema_version"], path="temporal.sidecar.schema_version")
    for field in (
        "authority_policy_sha256",
        "prediction_receipt_sha256",
        "verdict_receipt_sha256",
        "receipt_graph_sha256",
    ):
        _sha(sidecar[field], path=f"temporal.sidecar.{field}")
    sidecar_threshold = _nonnegative_int(
        sidecar["threshold"], path="temporal.sidecar.threshold"
    )
    sidecar_allowlist, sidecar_allowlist_keys = _canonical_did_list(
        sidecar["witness_allowlist"],
        path="temporal.sidecar.witness_allowlist",
        allow_empty=False,
    )
    sidecar_allow_key_ids = [key.hex() for key in sidecar_allowlist_keys]
    _record(failures, sidecar["schema_version"] == SIDECAR_SCHEMA,
            "temporal.sidecar_schema_mismatch")
    _record(failures, hmac.compare_digest(sidecar["authority_policy_sha256"], policy_sha256),
            "temporal.authority_policy_sha_mismatch")
    _record(failures, sidecar_threshold == threshold, "temporal.threshold_policy_mismatch")
    _record(failures, sidecar_allow_key_ids == allow_key_ids,
            "temporal.allowlist_policy_mismatch")
    for field in ("prediction_receipt_sha256", "verdict_receipt_sha256",
                  "receipt_graph_sha256"):
        _record(
            failures,
            hmac.compare_digest(sidecar[field], expected[field]),
            f"temporal.{field.removesuffix('_sha256')}_mismatch",
        )
    sidecar_sha256 = temporal_sidecar_sha256(sidecar)
    _record(failures, hmac.compare_digest(sidecar_sha256, expected["temporal_sidecar_sha256"]),
            "temporal.sidecar_sha_mismatch")

    binding = _exact_mapping(
        temporal["runtime_binding"],
        path="temporal.runtime_binding",
        keys={
            "schema_version",
            "prediction_receipt_sha256",
            "verdict_receipt_sha256",
            "sidecar_sha256",
            "receipt_graph_sha256",
            "readback_ok",
        },
    )
    _text(binding["schema_version"], path="temporal.runtime_binding.schema_version")
    for field in ("prediction_receipt_sha256", "verdict_receipt_sha256",
                  "sidecar_sha256", "receipt_graph_sha256"):
        _sha(binding[field], path=f"temporal.runtime_binding.{field}")
    _boolean(binding["readback_ok"], path="temporal.runtime_binding.readback_ok")
    binding_failures: list[str] = []
    _record(binding_failures, binding["schema_version"] == TEMPORAL_BINDING_SCHEMA,
            "temporal.runtime_binding_schema_mismatch")
    _record(binding_failures, binding["readback_ok"] is True,
            "temporal.runtime_binding_readback_failed")
    for binding_field, source_field in (
        ("prediction_receipt_sha256", "prediction_receipt_sha256"),
        ("verdict_receipt_sha256", "verdict_receipt_sha256"),
        ("receipt_graph_sha256", "receipt_graph_sha256"),
    ):
        _record(
            binding_failures,
            hmac.compare_digest(binding[binding_field], expected[source_field]),
            f"temporal.runtime_{binding_field.removesuffix('_sha256')}_mismatch",
        )
    _record(binding_failures, hmac.compare_digest(binding["sidecar_sha256"], sidecar_sha256),
            "temporal.runtime_sidecar_mismatch")
    failures.extend(binding_failures)
    runtime_binding_ok = not binding_failures

    prediction_times = _verified_anchor_times(
        sidecar["prediction_anchors"],
        endpoint="prediction",
        receipt_sha256=sidecar["prediction_receipt_sha256"],
        allowlist=sidecar_allowlist,
        failures=failures,
    )
    verdict_times = _verified_anchor_times(
        sidecar["verdict_anchors"],
        endpoint="verdict",
        receipt_sha256=sidecar["verdict_receipt_sha256"],
        allowlist=sidecar_allowlist,
        failures=failures,
    )
    prediction_signers = set(prediction_times)
    verdict_signers = set(verdict_times)
    prediction_quorum = len(prediction_signers) >= threshold
    verdict_quorum = len(verdict_signers) >= threshold
    same_authority_set = prediction_signers == verdict_signers
    _record(failures, prediction_quorum, "temporal.prediction_quorum_missing")
    _record(failures, verdict_quorum, "temporal.verdict_quorum_missing")
    _record(failures, same_authority_set, "temporal.endpoint_authority_set_mismatch")
    anchors_not_after_evaluation = all(
        timestamp <= evaluated_at
        for timestamp in (*prediction_times.values(), *verdict_times.values())
    )
    _record(
        failures,
        anchors_not_after_evaluation,
        "temporal.anchor_after_evaluation",
    )
    ordering_ok = False
    if prediction_times and verdict_times and same_authority_set:
        ordering_ok = max(prediction_times.values()) < min(verdict_times.values())
    _record(failures, ordering_ok, "temporal.all_anchor_ordering_not_strict")
    return {
        "component_ok": not failures,
        "l3_assurance": "UNAVAILABLE",
        "proof_model": "same-authority-set-all-anchor-strict-interval",
        "threshold": threshold,
        "prediction_authority_count": len(prediction_signers),
        "verdict_authority_count": len(verdict_signers),
        "prediction_quorum": prediction_quorum,
        "verdict_quorum": verdict_quorum,
        "same_authority_set": same_authority_set,
        "ordering_ok": ordering_ok,
        "anchors_not_after_evaluation": anchors_not_after_evaluation,
        "runtime_binding_ok": runtime_binding_ok,
        "authority_policy_sha256": policy_sha256,
        "sidecar_sha256": sidecar_sha256,
        "producer_role_count": len(producer_dids),
        "attestor_role_count": len(attestor_dids),
    }, failures


def _correction_plan(failures: Sequence[str]) -> list[str]:
    plans: list[str] = []
    mappings = (
        ("storage.predeploy.", "Regenerate and independently pin the exact target-bound predeploy receipt."),
        ("storage.fence.", "Restore the external writer-drain authority and obtain a fresh signed fence response."),
        ("storage.postgresql.", "Apply and read back the NOLOGIN owner plus separate least-privilege migrator/runtime roles."),
        ("storage.neo4j.", "Use Neo4j Enterprise custom roles and read back database-scoped effective privileges."),
        ("storage.runtime.", "Drain or reconcile runtime state, then repeat exact readiness and lease readback."),
        ("temporal.", "Reissue the policy-bound two-ended sidecar over current receipt-graph heads."),
    )
    for prefix, plan in mappings:
        if any(item.startswith(prefix) for item in failures) and plan not in plans:
            plans.append(plan)
    plans.append(
        "Run the locked negative-control suite; implement and independently audit live adapters before production approval."
    )
    return plans


def _seal_report(report: dict[str, Any]) -> dict[str, Any]:
    return {**report, "report_body_sha256": _sha256(_canonical(report))}


def _unsupported_report(
    *,
    canonical_case_sha256: str,
) -> dict[str, Any]:
    failure = "mode.live_adapter_not_implemented"
    return _seal_report({
        "schema_version": CASE_REPORT_SCHEMA,
        "status": "UNSUPPORTED",
        "harness_status": "NOT_RUN",
        "deployment_status": "NOT_READY",
        "production_ready": False,
        "l3_assurance": "UNAVAILABLE",
        "mode": "live",
        "harness_tier": HARNESS_TIER,
        "target_tiers": list(TARGET_TIERS),
        "claim_boundary": CLAIM_BOUNDARY,
        "axes": {
            "inform": {"ok": True},
            "constrain": {"ok": True, "network_access": False, "mutation_allowed": False},
            "verify": {"ok": False, "failures": [failure]},
            "correct": {"executed": False, "plan": _correction_plan([failure])},
        },
        "storage": {"ok": False},
        "temporal": {"component_ok": False, "l3_assurance": "UNAVAILABLE"},
        "failures": [failure],
        "mutation_attempts": 0,
        "canonical_case_sha256": canonical_case_sha256,
        "evidence_file_sha256": None,
        "evidence_bytes_bound": False,
    })


def evaluate_readiness(case_value: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate one case; never claim harness-suite or production readiness."""

    case = _exact_mapping(
        case_value,
        path="case",
        keys={"schema_version", "mode", "expected", "storage", "temporal"},
    )
    if case["schema_version"] != CASE_SCHEMA:
        raise HarnessInputError("case.schema_version is unsupported")
    mode = _text(case["mode"], path="case.mode")
    if mode not in {"fixture", "live"}:
        raise HarnessInputError("case.mode must be fixture or live")
    canonical_case = _canonical(case)
    if len(canonical_case) > MAX_EVIDENCE_BYTES:
        raise HarnessInputError("canonical case exceeds the bounded evidence size")
    canonical_case_sha256 = _sha256(canonical_case)
    if mode == "live":
        return _unsupported_report(canonical_case_sha256=canonical_case_sha256)

    expected = _exact_mapping(
        case["expected"],
        path="expected",
        keys={
            "contract_id",
            "environment",
            "operation_sha256",
            "target_sha256",
            "predeploy_file_sha256",
            "predeploy_receipt_sha256",
            "fence_authority_key_sha256",
            "fence_nonce",
            "writer_lease_id",
            "writer_drain_receipt_sha256",
            "postgresql_database",
            "neo4j_database",
            "prediction_receipt_sha256",
            "verdict_receipt_sha256",
            "temporal_sidecar_sha256",
            "receipt_graph_sha256",
            "evaluated_at",
        },
    )
    for field in (
        "contract_id",
        "environment",
        "writer_lease_id",
        "postgresql_database",
        "neo4j_database",
    ):
        _text(expected[field], path=f"expected.{field}")
    for field in (
        "operation_sha256",
        "target_sha256",
        "predeploy_file_sha256",
        "predeploy_receipt_sha256",
        "fence_authority_key_sha256",
        "writer_drain_receipt_sha256",
        "prediction_receipt_sha256",
        "verdict_receipt_sha256",
        "temporal_sidecar_sha256",
        "receipt_graph_sha256",
    ):
        _sha(expected[field], path=f"expected.{field}")
    _lower_hex(expected["fence_nonce"], path="expected.fence_nonce", size=32)
    evaluated_at = _parse_time(expected["evaluated_at"], path="expected.evaluated_at")
    failures: list[str] = []
    _record(failures, expected["contract_id"] == STORAGE_CONTRACT_ID,
            "storage.expected.contract_mismatch")
    storage, storage_failures = _evaluate_storage(
        case["storage"], expected=expected, evaluated_at=evaluated_at
    )
    temporal, temporal_failures = _evaluate_temporal(
        case["temporal"], expected=expected, evaluated_at=evaluated_at
    )
    failures = sorted(set(failures + storage_failures + temporal_failures))
    accepted = not failures
    report = {
        "schema_version": CASE_REPORT_SCHEMA,
        "status": "CASE_ACCEPTED" if accepted else "NOT_READY",
        "harness_status": "NOT_RUN",
        "deployment_status": "NOT_READY",
        "production_ready": False,
        "l3_assurance": "UNAVAILABLE",
        "mode": mode,
        "harness_tier": HARNESS_TIER,
        "target_tiers": list(TARGET_TIERS),
        "claim_boundary": CLAIM_BOUNDARY,
        "axes": {
            "inform": {
                "ok": True,
                "contract_id": expected["contract_id"],
                "operation_sha256": expected["operation_sha256"],
                "target_sha256": expected["target_sha256"],
            },
            "constrain": {
                "ok": True,
                "network_access": False,
                "mutation_allowed": False,
                "live_authority_claim_allowed": False,
            },
            "verify": {"ok": accepted, "failures": failures},
            "correct": {"executed": False, "plan": _correction_plan(failures)},
        },
        "storage": storage,
        "temporal": temporal,
        "failures": failures,
        "mutation_attempts": 0,
        "canonical_case_sha256": canonical_case_sha256,
        "evidence_file_sha256": None,
        "evidence_bytes_bound": False,
    }
    return _seal_report(report)


def load_evidence(path: Path, expected_file_sha256: str) -> LoadedEvidence:
    """Load one exact, independently SHA-pinned JSON fixture."""

    if not path.is_absolute():
        raise HarnessInputError("--evidence must be an absolute path")
    try:
        resolved = path.resolve(strict=True)
        info = path.lstat()
    except OSError as exc:
        raise HarnessInputError("evidence file is unavailable") from exc
    if resolved != path or stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise HarnessInputError("evidence must be a non-symlink regular file")
    if info.st_size > MAX_EVIDENCE_BYTES:
        raise HarnessInputError("evidence file exceeds the bounded size")
    if not _exact_sha256(expected_file_sha256):
        raise HarnessInputError("--evidence-sha256 must be a lowercase SHA-256")
    raw = path.read_bytes()
    if len(raw) > MAX_EVIDENCE_BYTES:
        raise HarnessInputError("evidence file exceeds the bounded size")
    actual_file_sha256 = _sha256(raw)
    if not hmac.compare_digest(actual_file_sha256, expected_file_sha256):
        raise HarnessInputError("evidence file SHA-256 mismatch")
    value = _strict_json_loads(raw)
    if not isinstance(value, dict):
        raise HarnessInputError("evidence root must be an object")
    return LoadedEvidence(raw=raw, file_sha256=actual_file_sha256)


def evaluate_loaded_evidence(evidence: LoadedEvidence) -> dict[str, Any]:
    """Evaluate only evidence that passed :func:`load_evidence` byte verification."""

    if type(evidence) is not LoadedEvidence:
        raise HarnessInputError("evidence must be a LoadedEvidence value")
    if not isinstance(evidence.raw, bytes):
        raise HarnessInputError("loaded evidence bytes are invalid")
    if len(evidence.raw) > MAX_EVIDENCE_BYTES:
        raise HarnessInputError("loaded evidence bytes exceed the bounded size")
    _sha(evidence.file_sha256, path="loaded_evidence.file_sha256")
    if not hmac.compare_digest(_sha256(evidence.raw), evidence.file_sha256):
        raise HarnessInputError("loaded evidence bytes no longer match their SHA-256")
    case = _strict_json_loads(evidence.raw)
    if not isinstance(case, dict):
        raise HarnessInputError("evidence root must be an object")
    report = evaluate_readiness(case)
    body = dict(report)
    body.pop("report_body_sha256")
    body["evidence_file_sha256"] = evidence.file_sha256
    body["evidence_bytes_bound"] = True
    return _seal_report(body)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate one credential-free LakatoTree readiness-harness fixture. "
            "CASE_ACCEPTED is not HARNESS_GREEN or production approval."
        )
    )
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--evidence-sha256", required=True)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        evidence = load_evidence(args.evidence, args.evidence_sha256)
        report = evaluate_loaded_evidence(evidence)
    except (HarnessInputError, OSError) as exc:
        print(
            json.dumps(
                {"schema_version": ERROR_SCHEMA, "status": "INVALID", "error": str(exc)},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            report,
            ensure_ascii=False,
            sort_keys=True,
            indent=2 if args.pretty else None,
        )
    )
    if report["status"] == "CASE_ACCEPTED":
        return 0
    if report["status"] == "NOT_READY":
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
