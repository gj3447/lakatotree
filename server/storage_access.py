"""Pure contracts for signed datastore access observations.

This module does not connect to a database, read environment variables, consult
the wall clock, or approve a deployment.  It validates one exact access policy
and independently signed PostgreSQL/Neo4j before/after observations.  Drift is
derived by comparing signed projections; no self-reported ``drift_free`` flag is
accepted.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

from lakatos.write_cert import (
    CertError,
    did_key_decode,
    did_key_encode,
    ed25519_public_key,
    ed25519_public_key_is_strict,
    ed25519_sign,
    ed25519_verify,
)
from server.settings import is_pinned_dns_name
from server.storage_protocol import (
    NEO4J_COMMUNITY_SUPPORTED_RELEASES,
    NEO4J_SUPPORTED_RELEASES,
)


ACCESS_POLICY_SCHEMA = "lakatotree-storage-access-policy/v1"
ACCESS_POLICY_ENVIRONMENTS = ("production", "development")
DATASTORE_ATTESTATION_SCHEMA = "lakatotree-datastore-audit-attestation/v2"
STORAGE_AUDIT_BUNDLE_SCHEMA = "lakatotree-storage-audit-bundle/v2"
DATASTORE_ATTESTATION_DOMAIN = DATASTORE_ATTESTATION_SCHEMA.encode("ascii") + b"\0"
STORES = ("postgresql", "neo4j")
PHASES = ("predeploy", "startup")
POSITIONS = ("before", "after")
MAX_OBSERVATION_BYTES = 512 * 1024
MAX_VALIDITY_SECONDS = 300
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_JSON_NESTING = 32

_ROLE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]{0,62}\Z")
_NEO_DATABASE_NAME = re.compile(
    r"(?=.{3,63}\Z)[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\Z"
)
_HEX = frozenset("0123456789abcdef")
_NEO_AUTH_SETTING_NAMES = (
    "dbms.security.auth_enabled",
    "dbms.security.authentication_providers",
    "dbms.security.authorization_providers",
    "dbms.security.abac.authorization_providers",
)
_NEO_BASE_AUTH_SETTING_NAMES = _NEO_AUTH_SETTING_NAMES[:3]
_PG_SAFE_ATTRIBUTE_KEYS = {
    "login", "superuser", "createdb", "createrole", "inherit",
    "bypassrls", "replication",
}
_PG_TABLES = (
    "public.history", "public.history_event_claims", "public.metric_snapshots",
    "public.lineage",
)
_PG_SEQUENCES = (
    "public.history_id_seq", "public.metric_snapshots_id_seq",
    "public.lineage_id_seq",
)
_PG_FACT_KEYS = {
    "database", "database_matches", "database_oid_sha256",
    "system_identifier_sha256", "transaction_read_only", "challenge_nonce_sha256",
    "current_actor_class", "current_actor_sha256", "session_actor_sha256",
    "roles_distinct", "roles", "objects", "public_schema_owner_class",
    "acl_projection_scope", "acl_projection_count", "acl_projection_sha256",
    "acl_projection", "grantable_acl_counts", "public_acl_entry_counts",
    "runtime_effective_role_sha256", "role_effective_membership_sha256",
    "role_inbound_membership_sha256",
    "migrator_owner_membership", "role_owned_user_object_count",
    "role_user_function_execute_count", "runtime_database_create",
    "runtime_database_temp", "runtime_schema_create", "runtime_schema_create_count",
    "runtime_schema_create_sha256", "runtime_schema_usage", "audit_principal_read_only",
    "runtime_out_of_contract_write_privilege_count",
    "runtime_out_of_contract_write_privilege_sha256",
    "runtime_out_of_contract_read_privilege_count",
    "runtime_out_of_contract_read_privilege_sha256",
    "audit_effective_role_sha256", "audit_database_create", "audit_database_temp",
    "audit_schema_create", "audit_schema_create_count", "audit_schema_create_sha256",
    "audit_data_read_privilege_count", "audit_data_read_privilege_sha256",
    "audit_write_privilege_count", "audit_write_privilege_sha256",
    "audit_column_write_privilege_count", "audit_column_write_privilege_sha256",
    "authority_boundary_deviation_count",
    "authority_boundary_deviation_sha256",
}
_NEO_FACT_KEYS = {
    "database", "challenge_nonce_sha256", "database_name_matches",
    "database_direct_local", "database_alias_count", "database_alias_sha256",
    "database_catalog_sha256",
    "database_id_sha256", "edition", "version", "enterprise",
    "current_actor_sha256", "role_sha256", "role_count",
    "effective_privilege_sha256", "effective_privilege_count",
    "effective_privileges", "audit_principal_read_only",
    "audit_unsafe_granted_action_count", "audit_unsafe_granted_action_sha256",
    "named_role_sha256", "named_role_privilege_sha256", "named_role_privileges",
    "public_role_binding_sha256", "custom_role_binding_ok",
    "named_user_role_sha256", "named_user_role_binding_ok",
    "named_role_assignee_sha256",
    "runtime_role_least_privilege", "migrator_role_least_privilege",
    "public_role_safe", "auth_settings", "auth_settings_sha256",
    "native_only_auth", "global_unsafe_privilege_count",
    "global_unsafe_privilege_sha256", "system_database_id_sha256",
    "system_last_committed_tx", "authorization_snapshot_stable",
    "read_query_count",
}
_NEO_COMMUNITY_READ_QUERY_COUNT = 9
_NEO_COMMUNITY_FACT_KEYS = {
    "database", "challenge_nonce_sha256", "database_name_matches",
    "database_direct_local", "database_alias_count", "database_alias_sha256",
    "database_catalog_sha256", "database_id_sha256", "edition", "version",
    "enterprise", "community_semantics", "rbac_available",
    "current_actor_sha256", "named_user_sha256", "named_user_suspended",
    "auth_settings", "auth_settings_sha256", "native_only_auth",
    "system_database_id_sha256", "system_last_committed_tx",
    "authorization_snapshot_stable", "read_query_count",
}


class StorageAccessError(ValueError):
    """An access policy or signed observation is ambiguous or invalid."""


@dataclass(frozen=True)
class AttestationVerification:
    ok: bool
    failures: tuple[str, ...]
    body_sha256: str | None
    observed_at: datetime | None


@dataclass(frozen=True)
class StorageAuditProof:
    ok: bool
    failures: tuple[str, ...]
    phase: str
    request_sha256: str | None
    before_body_sha256: str | None
    after_body_sha256: str | None
    observation_sha256: str | None


@dataclass(frozen=True)
class StorageAuditBundleProof:
    ok: bool
    failures: tuple[str, ...]
    phase: str
    postgresql: StorageAuditProof
    neo4j: StorageAuditProof


@dataclass(frozen=True)
class AccessPairProof:
    status: str
    production_ready: bool
    deployment_status: str
    failures: tuple[str, ...]
    predeploy: StorageAuditBundleProof
    startup: StorageAuditBundleProof
    environment: str | None = None
    target_sha256: str | None = None
    operation_sha256: str | None = None
    artifact_identity_sha256: str | None = None
    policy_file_sha256: str | None = None
    predeploy_receipt_file_sha256: str | None = None
    predeploy_receipt_sha256: str | None = None
    predeploy_bundle_file_sha256: str | None = None
    startup_bundle_file_sha256: str | None = None
    valid_until: str | None = None
    authority_identity_sha256s: tuple[str, ...] = ()


def canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise StorageAccessError("value must be finite canonical JSON") from exc


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def strict_json_loads(raw: bytes) -> Any:
    if not isinstance(raw, bytes) or len(raw) > MAX_DOCUMENT_BYTES:
        raise StorageAccessError("JSON document exceeds bounded bytes")
    depth = 0
    in_string = False
    escaped = False
    for byte in raw:
        if in_string:
            if escaped:
                escaped = False
            elif byte == 0x5C:
                escaped = True
            elif byte == 0x22:
                in_string = False
            continue
        if byte == 0x22:
            in_string = True
        elif byte in (0x5B, 0x7B):
            depth += 1
            if depth > MAX_JSON_NESTING:
                raise StorageAccessError("JSON document exceeds bounded nesting")
        elif byte in (0x5D, 0x7D):
            depth -= 1
            if depth < 0:
                raise StorageAccessError("JSON document has invalid nesting")

    def object_pairs(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise StorageAccessError("duplicate JSON object key")
            result[key] = item
        return result

    def reject_constant(token: str) -> None:
        raise StorageAccessError(f"non-finite JSON number is forbidden: {token}")

    try:
        return json.loads(
            raw, object_pairs_hook=object_pairs, parse_constant=reject_constant
        )
    except StorageAccessError:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise StorageAccessError("document is not valid UTF-8 JSON") from exc


def _exact_mapping(value: Any, *, path: str, keys: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise StorageAccessError(f"{path} has a non-exact field set")
    return value


def _text(value: Any, *, path: str, maximum: int = 256) -> str:
    if (
        not isinstance(value, str) or not value or value != value.strip()
        or len(value) > maximum or "\x00" in value
    ):
        raise StorageAccessError(f"{path} must be a bounded canonical string")
    return value


def _role(value: Any, *, path: str) -> str:
    value = _text(value, path=path, maximum=63)
    if not _ROLE_NAME.fullmatch(value):
        raise StorageAccessError(f"{path} must be a bounded role name")
    return value


def _sha(value: Any, *, path: str) -> str:
    if not (
        isinstance(value, str) and len(value) == 64
        and all(char in _HEX for char in value)
    ):
        raise StorageAccessError(f"{path} must be a lowercase SHA-256")
    return value


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in _HEX for char in value)
    )


def _parse_time(value: Any, *, path: str) -> datetime:
    value = _text(value, path=path, maximum=64)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, OverflowError) as exc:
        raise StorageAccessError(f"{path} must be timezone-aware ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise StorageAccessError(f"{path} must be timezone-aware ISO-8601")
    return parsed.astimezone(timezone.utc)


def validate_access_policy(value: Any) -> Mapping[str, Any]:
    policy = _exact_mapping(
        value,
        path="policy",
        keys={
            "schema_version", "environment", "attestors", "predeploy_authority",
            "postgresql", "neo4j",
        },
    )
    if policy["schema_version"] != ACCESS_POLICY_SCHEMA:
        raise StorageAccessError("policy.schema_version is unsupported")
    if policy["environment"] not in ACCESS_POLICY_ENVIRONMENTS:
        raise StorageAccessError(
            "policy.environment must be production or development"
        )
    attestors = _exact_mapping(
        policy["attestors"], path="policy.attestors", keys=set(STORES)
    )
    decoded_attestors = []
    for store in STORES:
        did = _text(
            attestors[store], path=f"policy.attestors.{store}", maximum=256
        )
        try:
            public = did_key_decode(did)
        except CertError as exc:
            raise StorageAccessError("policy attestor DID is invalid") from exc
        if did_key_encode(public) != did or not ed25519_public_key_is_strict(public):
            raise StorageAccessError("policy attestor DID is non-canonical")
        decoded_attestors.append(did)
    if len(set(decoded_attestors)) != len(decoded_attestors):
        raise StorageAccessError("policy datastore attestors must be distinct")
    predeploy = _exact_mapping(
        policy["predeploy_authority"],
        path="policy.predeploy_authority",
        keys={"fence_verifier_sha256", "fence_public_key_hex"},
    )
    _sha(
        predeploy["fence_verifier_sha256"],
        path="policy.predeploy_authority.fence_verifier_sha256",
    )
    fence_key = predeploy["fence_public_key_hex"]
    if not (
        isinstance(fence_key, str) and len(fence_key) == 64
        and all(char in _HEX for char in fence_key)
        and ed25519_public_key_is_strict(bytes.fromhex(fence_key))
    ):
        raise StorageAccessError("policy predeploy fence key is invalid")
    if fence_key in {
        did_key_decode(attestors[store]).hex() for store in STORES
    }:
        raise StorageAccessError(
            "policy predeploy fence authority must differ from datastore attestors"
        )
    pg = _exact_mapping(
        policy["postgresql"],
        path="policy.postgresql",
        keys={
            "host", "port", "database", "owner_role", "migrator_role", "runtime_role",
            "audit_role", "migrator_owner_membership", "runtime_profile_sha256",
            "runtime_ca_sha256",
        },
    )
    pg_host = _text(pg["host"], path="policy.postgresql.host", maximum=253)
    # Development may bind one literal LAN IP; production stays loopback-only.
    pg_host_requirement = (
        "one literal IP"
        if policy["environment"] == "development"
        else "one literal loopback IP"
    )
    try:
        pg_address = ipaddress.ip_address(pg_host)
    except ValueError as exc:
        raise StorageAccessError(
            f"policy.postgresql.host must be {pg_host_requirement}"
        ) from exc
    if policy["environment"] != "development" and not pg_address.is_loopback:
        raise StorageAccessError(
            "policy.postgresql.host must be one literal loopback IP"
        )
    if type(pg["port"]) is not int or not 1 <= pg["port"] <= 65535:
        raise StorageAccessError("policy.postgresql.port must be a TCP port")
    _sha(
        pg["runtime_profile_sha256"],
        path="policy.postgresql.runtime_profile_sha256",
    )
    _sha(pg["runtime_ca_sha256"], path="policy.postgresql.runtime_ca_sha256")
    _text(pg["database"], path="policy.postgresql.database", maximum=63)
    pg_roles = [
        _role(pg[field], path=f"policy.postgresql.{field}")
        for field in ("owner_role", "migrator_role", "runtime_role", "audit_role")
    ]
    if len(set(pg_roles)) != len(pg_roles):
        raise StorageAccessError("policy PostgreSQL roles must be pairwise distinct")
    membership = _exact_mapping(
        pg["migrator_owner_membership"],
        path="policy.postgresql.migrator_owner_membership",
        keys={"admin_option", "inherit_option", "set_option"},
    )
    if any(type(membership[field]) is not bool for field in membership):
        raise StorageAccessError("policy PostgreSQL membership options must be booleans")
    if membership != {
        "admin_option": False, "inherit_option": False, "set_option": True,
    }:
        raise StorageAccessError(
            "policy PostgreSQL migrator membership must be SET-only"
        )

    neo = _exact_mapping(
        policy["neo4j"],
        path="policy.neo4j",
        keys={
            "uri", "database", "audit_user", "audit_role", "migrator_user",
            "migrator_role", "runtime_user", "runtime_role",
        },
    )
    uri = _text(neo["uri"], path="policy.neo4j.uri", maximum=2048)
    parsed_uri = urlsplit(uri)
    try:
        parsed_port = parsed_uri.port
    except ValueError as exc:
        raise StorageAccessError("policy.neo4j.uri port is invalid") from exc
    if (
        parsed_uri.scheme != "bolt+s"
        or parsed_uri.username is not None
        or parsed_uri.password is not None
        or parsed_uri.hostname is None
        or parsed_port is None
        or parsed_uri.path not in {"", "/"}
        or parsed_uri.query
        or parsed_uri.fragment
    ):
        raise StorageAccessError(
            "policy.neo4j.uri must be one credential-free system-trusted Bolt URI"
        )
    try:
        ipaddress.ip_address(parsed_uri.hostname)
    except ValueError:
        if not is_pinned_dns_name(parsed_uri.hostname) or uri != uri.lower():
            raise StorageAccessError(
                "policy.neo4j.uri host must be one literal IP or lowercase "
                "pinned DNS name"
            ) from None
    neo_database = _text(
        neo["database"], path="policy.neo4j.database", maximum=63
    )
    if (
        _NEO_DATABASE_NAME.fullmatch(neo_database) is None
        or neo_database.startswith("system")
    ):
        raise StorageAccessError(
            "policy.neo4j.database must be one concrete canonical application database"
        )
    users = [
        _role(neo[field], path=f"policy.neo4j.{field}")
        for field in ("audit_user", "migrator_user", "runtime_user")
    ]
    roles = [
        _role(neo[field], path=f"policy.neo4j.{field}")
        for field in ("audit_role", "migrator_role", "runtime_role")
    ]
    if len(set(users)) != 3 or len(set(roles)) != 3:
        raise StorageAccessError(
            "policy Neo4j users and custom roles must be pairwise distinct"
        )
    builtins = {"admin", "architect", "editor", "publisher", "reader", "public"}
    if {role.lower() for role in roles} & builtins:
        raise StorageAccessError("policy Neo4j roles must not be built-in roles")
    return policy


def access_policy_sha256(value: Any) -> str:
    return sha256_bytes(canonical_json(validate_access_policy(value)))


_ATTESTATION_BODY_FIELDS = {
    "schema_version", "store", "phase", "position", "request_nonce",
    "request_sha256", "environment", "target_sha256",
    "operation_sha256", "access_policy_file_sha256",
    "predeploy_receipt_file_sha256", "predeploy_receipt_sha256", "target_binding",
    "previous_phase_bundle_file_sha256", "observation", "observed_at",
    "expires_at", "evidence_refs", "signer_did",
}

_EXPECTED_FIELDS = {
    "request_nonce", "request_sha256", "target_sha256",
    "target_details", "operation_sha256", "access_policy_file_sha256",
    "predeploy_receipt_file_sha256", "predeploy_receipt_sha256",
    "previous_phase_bundle_file_sha256",
}


def _validate_target_details(value: Any, policy: Mapping[str, Any]) -> Mapping[str, Any]:
    details = _exact_mapping(
        value, path="expected.target_details", keys=set(STORES)
    )
    pg = _exact_mapping(
        details["postgresql"],
        path="expected.target_details.postgresql",
        keys={
            "configured_host", "configured_port", "configured_database", "database",
            "database_oid", "server_address", "server_port", "server_version_num",
            "system_identifier",
        },
    )
    try:
        observed_server_ip = ipaddress.ip_address(str(pg["server_address"]))
        policy_server_ip = ipaddress.ip_address(
            str(policy["postgresql"]["host"])
        )
    except ValueError as exc:
        raise StorageAccessError(
            "PostgreSQL target binding must use one literal server IP"
        ) from exc
    if not (
        pg["configured_host"] == policy["postgresql"]["host"]
        and pg["configured_port"] == policy["postgresql"]["port"]
        and pg["configured_database"] == policy["postgresql"]["database"]
        and pg["database"] == policy["postgresql"]["database"]
        and observed_server_ip == policy_server_ip
        and type(pg["server_port"]) is int
        and pg["server_port"] == policy["postgresql"]["port"]
    ):
        raise StorageAccessError("PostgreSQL target binding differs from policy")
    for field in (
        "configured_host", "configured_database", "database", "database_oid",
        "server_address", "server_version_num", "system_identifier",
    ):
        _text(pg[field], path=f"expected.target_details.postgresql.{field}", maximum=256)
    neo = _exact_mapping(
        details["neo4j"],
        path="expected.target_details.neo4j",
        keys={"configured_uri", "configured_database", "database_id", "database_name"},
    )
    if not (
        neo["configured_uri"] == policy["neo4j"]["uri"]
        and neo["configured_database"] == policy["neo4j"]["database"]
        and neo["database_name"] == policy["neo4j"]["database"]
    ):
        raise StorageAccessError("Neo4j target binding differs from policy")
    for field in neo:
        _text(neo[field], path=f"expected.target_details.neo4j.{field}", maximum=2048)
    return details


def validate_expected(value: Any, policy: Mapping[str, Any]) -> Mapping[str, Any]:
    expected = _exact_mapping(value, path="expected", keys=set(_EXPECTED_FIELDS))
    _sha(expected["request_nonce"], path="expected.request_nonce")
    for field in (
        "request_sha256", "target_sha256", "operation_sha256",
        "access_policy_file_sha256", "predeploy_receipt_file_sha256",
        "predeploy_receipt_sha256",
    ):
        _sha(expected[field], path=f"expected.{field}")
    previous = expected["previous_phase_bundle_file_sha256"]
    if previous is not None:
        _sha(previous, path="expected.previous_phase_bundle_file_sha256")
    details = _validate_target_details(expected["target_details"], policy)
    if not hmac.compare_digest(
        expected["target_sha256"], sha256_bytes(canonical_json(details))
    ):
        raise StorageAccessError("expected target SHA differs from target details")
    return expected


def datastore_attestation_signing_bytes(body: Any) -> bytes:
    body = _exact_mapping(
        body, path="attestation.body", keys=set(_ATTESTATION_BODY_FIELDS)
    )
    if body["schema_version"] != DATASTORE_ATTESTATION_SCHEMA:
        raise StorageAccessError("attestation schema is unsupported")
    return DATASTORE_ATTESTATION_DOMAIN + canonical_json(body)


def seal_datastore_attestation(body: Mapping[str, Any], secret32: bytes) -> dict[str, Any]:
    public = ed25519_public_key(secret32)
    signer_did = did_key_encode(public)
    if body.get("signer_did") != signer_did:
        raise StorageAccessError("attestation signer_did differs from signing key")
    signature = ed25519_sign(secret32, datastore_attestation_signing_bytes(body))
    return {**dict(body), "signature": signature.hex()}


def _validate_observation_shape(value: Any) -> Mapping[str, Any]:
    observation = _exact_mapping(
        value, path="attestation.observation",
        keys={"status", "facts", "failure_codes"},
    )
    if observation["status"] != "OBSERVED":
        raise StorageAccessError("attestation observation must be OBSERVED")
    if not isinstance(observation["facts"], Mapping):
        raise StorageAccessError("attestation observation facts must be an object")
    if observation["failure_codes"] != []:
        raise StorageAccessError("attestation observation must have no failures")
    if len(canonical_json(observation)) > MAX_OBSERVATION_BYTES:
        raise StorageAccessError("attestation observation is too large")
    return observation


def _pg_role_attributes_ok(value: Any, *, login: bool) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == _PG_SAFE_ATTRIBUTE_KEYS
        and value.get("login") is login
        and all(
            value.get(field) is False
            for field in _PG_SAFE_ATTRIBUTE_KEYS - {"login"}
        )
    )


def _neo_privilege_rows(value: Any) -> list[Mapping[str, Any]] | None:
    if not isinstance(value, list) or len(value) > 64:
        return None
    keys = {"access", "action", "resource", "graph", "segment", "immutable"}
    if any(not isinstance(row, Mapping) or set(row) != keys for row in value):
        return None
    if any(
        not isinstance(item, str) or not item
        for row in value
        for key, item in row.items()
        if key != "immutable"
    ):
        return None
    if any(type(row["immutable"]) is not bool for row in value):
        return None
    if any(row["access"] not in {"GRANTED", "DENIED"} for row in value):
        return None
    return value


def _neo_audit_row_safe(row: Mapping[str, Any], database: str) -> bool:
    access = row.get("access")
    if access == "DENIED":
        return True
    if access != "GRANTED":
        return False
    if row.get("immutable") is not False:
        return False
    action = row.get("action")
    if action == "access":
        return (
            row.get("graph") in {database, "system"}
            and row.get("resource") == "database"
            and row.get("segment") == "database"
        )
    if action in {"show_alias", "show_database", "show_user", "show_privilege"}:
        return (
            row.get("graph") == "*"
            and row.get("resource") == "database"
            and row.get("segment") == "database"
        )
    if action == "show_setting":
        return (
            row.get("graph") == "*"
            and row.get("resource") == "database"
            and row.get("segment")
            in {f"SETTING({name})" for name in _NEO_AUTH_SETTING_NAMES}
        )
    return (
        action == "execute"
        and row.get("graph") == "*"
        and row.get("resource") == "database"
        and row.get("segment")
        in {"PROCEDURE(db.info)", "PROCEDURE(dbms.components)"}
    )


def _neo_action_scope_exact(
    action: str, rows: Sequence[Mapping[str, Any]], database: str
) -> bool:
    """Match the raw ``SHOW PRIVILEGES`` projection, not GRANT syntax."""

    if not rows or any(
        row.get("access") != "GRANTED"
        or row.get("action") != action
        or row.get("graph") != database
        for row in rows
    ):
        return False
    resources = {row.get("resource") for row in rows}
    segments = {row.get("segment") for row in rows}
    if action == "access":
        return len(rows) == 1 and resources == {"database"} and segments == {"database"}
    if action == "match":
        return resources == {"all_properties"} and (
            (len(rows) == 1 and segments == {"ELEMENT(*)"})
            or (len(rows) == 2 and segments == {"NODE(*)", "RELATIONSHIP(*)"})
        )
    if action == "write":
        return resources == {"graph"} and (
            (len(rows) == 1 and segments == {"ELEMENT(*)"})
            or (len(rows) == 2 and segments == {"NODE(*)", "RELATIONSHIP(*)"})
        )
    if action in {"constraint", "token"}:
        return len(rows) == 1 and resources == {"database"} and segments == {"database"}
    return False


def _neo_audit_rows_exact(
    rows: list[Mapping[str, Any]] | None, *, database: str, version: str
) -> bool:
    setting_names = (
        _NEO_AUTH_SETTING_NAMES
        if _neo_abac_setting_supported(version)
        else _NEO_BASE_AUTH_SETTING_NAMES
    )
    if rows is None or len(rows) != 8 + len(setting_names):
        return False
    identities = {
        tuple(row.get(field) for field in (
            "access", "action", "resource", "graph", "segment", "immutable"
        ))
        for row in rows
    }
    expected = {
        ("GRANTED", "access", "database", database, "database", False),
        ("GRANTED", "access", "database", "system", "database", False),
        ("GRANTED", "execute", "database", "*", "PROCEDURE(db.info)", False),
        ("GRANTED", "execute", "database", "*", "PROCEDURE(dbms.components)", False),
        ("GRANTED", "show_privilege", "database", "*", "database", False),
        ("GRANTED", "show_user", "database", "*", "database", False),
        ("GRANTED", "show_alias", "database", "*", "database", False),
        ("GRANTED", "show_database", "database", "*", "database", False),
        *{
            (
                "GRANTED", "show_setting", "database", "*",
                f"SETTING({name})", False,
            )
            for name in setting_names
        },
    }
    return identities == expected


def _neo_setting_list(value: Any) -> list[str] | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1].strip()
    if not text:
        return []
    items = [item.strip().strip("\"'") for item in text.split(",")]
    if any(not item or not re.fullmatch(r"[A-Za-z0-9_.-]+", item) for item in items):
        return None
    return items if len(items) == len(set(items)) else None


def _neo_abac_setting_supported(version: Any) -> bool:
    if not isinstance(version, str):
        return False
    match = re.fullmatch(r"(\d+)\.(\d+)(?:\.\d+)?", version.strip())
    if match is None:
        return False
    major, minor = (int(item) for item in match.groups())
    return major > 2026 or (major == 2026 and minor >= 3)


def _neo_version_supported(version: Any) -> bool:
    """Pin privilege/settings semantics to the audited 2026 release family."""

    if not isinstance(version, str):
        return False
    match = re.fullmatch(
        r"2026\.(\d{2})(?:\.(?:0|[1-9]\d*))?", version
    )
    return bool(
        match is not None
        and (2026, int(match.group(1))) in NEO4J_SUPPORTED_RELEASES
    )


def _neo_community_version_supported(version: Any) -> bool:
    """Pin community settings/SHOW semantics to the audited 2026 window."""

    if not isinstance(version, str):
        return False
    match = re.fullmatch(
        r"2026\.(\d{2})(?:\.(?:0|[1-9]\d*))?", version
    )
    return bool(
        match is not None
        and (2026, int(match.group(1))) in NEO4J_COMMUNITY_SUPPORTED_RELEASES
    )


def _neo_native_auth_settings_exact(value: Any, *, version: str) -> bool:
    setting_names = (
        _NEO_AUTH_SETTING_NAMES
        if _neo_abac_setting_supported(version)
        else _NEO_BASE_AUTH_SETTING_NAMES
    )
    if not isinstance(value, list) or len(value) != len(setting_names):
        return False
    rows: dict[str, Mapping[str, Any]] = {}
    for row in value:
        if not isinstance(row, Mapping) or set(row) != {"name", "value", "startup_value"}:
            return False
        name = row.get("name")
        if not isinstance(name, str) or name in rows:
            return False
        if not isinstance(row.get("value"), str) or not isinstance(row.get("startup_value"), str):
            return False
        if row["value"] != row["startup_value"]:
            return False
        rows[name] = row
    if set(rows) != set(setting_names):
        return False
    base_ok = (
        rows["dbms.security.auth_enabled"]["value"].strip().lower() == "true"
        and _neo_setting_list(rows["dbms.security.authentication_providers"]["value"]) == ["native"]
        and _neo_setting_list(rows["dbms.security.authorization_providers"]["value"]) == ["native"]
    )
    return base_ok and (
        not _neo_abac_setting_supported(version)
        or _neo_setting_list(rows["dbms.security.abac.authorization_providers"]["value"]) == []
    )


def _neo_role_rows_exact(
    rows: list[Mapping[str, Any]] | None, *, database: str, migrator: bool
) -> bool:
    if rows is None:
        return False
    expected = {"access", "match", "write"}
    if migrator:
        expected.update({"constraint", "token"})
    expected_rows = set()
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        if row.get("access") != "GRANTED" or row.get("immutable") is not False:
            return False
        action = row.get("action")
        if action not in expected or row.get("graph") != database:
            return False
        identity = tuple(row.get(field) for field in (
            "access", "action", "resource", "graph", "segment", "immutable"
        ))
        if identity in expected_rows:
            return False
        expected_rows.add(identity)
        grouped.setdefault(action, []).append(row)
    return set(grouped) == expected and all(
        _neo_action_scope_exact(action, action_rows, database)
        for action, action_rows in grouped.items()
    )


def _postgresql_projection_failures(
    facts: Mapping[str, Any], policy: Mapping[str, Any], request_nonce: str
) -> list[str]:
    if set(facts) != _PG_FACT_KEYS:
        return ["postgresql.fact_schema"]
    failures: list[str] = []
    pg = policy["postgresql"]
    roles = facts.get("roles")
    objects = facts.get("objects")
    memberships = facts.get("role_effective_membership_sha256")
    inbound_memberships = facts.get("role_inbound_membership_sha256")
    owned = facts.get("role_owned_user_object_count")
    functions = facts.get("role_user_function_execute_count")
    role_labels = {"owner", "migrator", "runtime", "audit"}
    count_fields = {
        "acl_projection_count", "runtime_schema_create_count",
        "runtime_out_of_contract_write_privilege_count",
        "runtime_out_of_contract_read_privilege_count",
        "audit_schema_create_count", "audit_data_read_privilege_count",
        "audit_write_privilege_count", "audit_column_write_privilege_count",
        "authority_boundary_deviation_count",
    }
    digest_fields = {
        "database_oid_sha256", "system_identifier_sha256",
        "challenge_nonce_sha256", "current_actor_sha256", "session_actor_sha256",
        "acl_projection_sha256", "runtime_schema_create_sha256",
        "runtime_out_of_contract_write_privilege_sha256",
        "runtime_out_of_contract_read_privilege_sha256",
        "audit_schema_create_sha256", "audit_data_read_privilege_sha256",
        "audit_write_privilege_sha256", "audit_column_write_privilege_sha256",
        "authority_boundary_deviation_sha256",
    }
    role_hashes = {
        label: sha256_bytes(str(pg[f"{label}_role"]).encode("utf-8"))
        for label in role_labels
    }
    checks: list[tuple[bool, str]] = [
        (
            all(type(facts[field]) is int and facts[field] >= 0 for field in count_fields),
            "postgresql.count_types",
        ),
        (
            all(_is_sha256(facts[field]) for field in digest_fields),
            "postgresql.digest_types",
        ),
        (facts["database"] == pg["database"], "postgresql.database"),
        (facts["database_matches"] is True, "postgresql.database_match"),
        (facts["transaction_read_only"] is True, "postgresql.transaction_read_only"),
        (
            facts["challenge_nonce_sha256"]
            == sha256_bytes(request_nonce.encode("ascii")),
            "postgresql.challenge_binding",
        ),
        (facts["roles_distinct"] is True, "postgresql.roles_distinct"),
        (facts["current_actor_class"] == "audit", "postgresql.current_actor_class"),
        (facts["current_actor_sha256"] == role_hashes["audit"], "postgresql.current_actor"),
        (facts["session_actor_sha256"] == role_hashes["audit"], "postgresql.session_actor"),
        (facts["audit_principal_read_only"] is True, "postgresql.audit_read_only"),
        (facts["audit_write_privilege_count"] == 0, "postgresql.audit_write_privilege"),
        (facts["audit_column_write_privilege_count"] == 0, "postgresql.audit_column_write_privilege"),
        (
            facts["authority_boundary_deviation_count"] == 0,
            "postgresql.authority_boundary_deviation",
        ),
        (facts["audit_database_create"] is False, "postgresql.audit_database_create"),
        (facts["audit_database_temp"] is False, "postgresql.audit_database_temp"),
        (facts["audit_schema_create"] is False, "postgresql.audit_schema_create"),
        (facts["audit_schema_create_count"] == 0, "postgresql.audit_schema_create_count"),
        (
            facts["audit_schema_create_sha256"] == sha256_bytes(canonical_json([])),
            "postgresql.audit_schema_create_digest",
        ),
        (facts["runtime_database_create"] is False, "postgresql.runtime_database_create"),
        (facts["runtime_database_temp"] is False, "postgresql.runtime_database_temp"),
        (facts["runtime_schema_create"] is False, "postgresql.runtime_schema_create"),
        (facts["runtime_schema_create_count"] == 0, "postgresql.runtime_schema_create_count"),
        (
            facts["runtime_schema_create_sha256"] == sha256_bytes(canonical_json([])),
            "postgresql.runtime_schema_create_digest",
        ),
        (facts["runtime_schema_usage"] is True, "postgresql.runtime_schema_usage"),
        (
            facts["runtime_out_of_contract_write_privilege_count"] == 0,
            "postgresql.runtime_out_of_contract_write_privilege",
        ),
        (
            facts["runtime_out_of_contract_read_privilege_count"] == 0,
            "postgresql.runtime_out_of_contract_read_privilege",
        ),
        (
            facts["audit_data_read_privilege_count"] == 0,
            "postgresql.audit_data_read_privilege",
        ),
        (facts["public_schema_owner_class"] == "owner", "postgresql.schema_owner"),
        (facts["acl_projection_scope"] == "contract-objects-v1", "postgresql.acl_scope"),
    ]
    if not isinstance(roles, Mapping) or set(roles) != role_labels:
        checks.append((False, "postgresql.role_projection"))
    else:
        for label in role_labels:
            role = roles[label]
            role_ok = (
                isinstance(role, Mapping)
                and set(role) == {"name_sha256", "present", "attributes"}
                and role.get("present") is True
                and role.get("name_sha256") == role_hashes[label]
                and _pg_role_attributes_ok(
                    role.get("attributes"), login=label != "owner"
                )
            )
            checks.append((role_ok, f"postgresql.{label}_attributes"))
    if not isinstance(memberships, Mapping) or set(memberships) != role_labels:
        checks.append((False, "postgresql.role_memberships"))
    else:
        expected_memberships = {
            "owner": {role_hashes["owner"]},
            "migrator": {role_hashes["migrator"], role_hashes["owner"]},
            "runtime": {role_hashes["runtime"]},
            "audit": {role_hashes["audit"]},
        }
        checks.append((
            all(
                isinstance(memberships[label], list)
                and len(memberships[label]) == len(expected_memberships[label])
                and set(memberships[label]) == expected_memberships[label]
                for label in role_labels
            ),
            "postgresql.role_memberships",
        ))
    checks.append((
        isinstance(inbound_memberships, Mapping)
        and set(inbound_memberships) == role_labels
        and inbound_memberships == {
            "owner": [role_hashes["migrator"]],
            "migrator": [],
            "runtime": [],
            "audit": [],
        },
        "postgresql.inbound_role_memberships",
    ))
    checks.append((
        facts["migrator_owner_membership"] == pg["migrator_owner_membership"],
        "postgresql.migrator_owner_membership",
    ))
    checks.append((
        isinstance(owned, Mapping) and set(owned) == role_labels
        and all(type(owned[label]) is int and owned[label] >= 0 for label in role_labels)
        and all(owned[label] == 0 for label in ("migrator", "runtime", "audit")),
        "postgresql.non_owner_ownership",
    ))
    checks.append((
        isinstance(functions, Mapping) and set(functions) == role_labels
        and all(type(functions[label]) is int and functions[label] >= 0 for label in role_labels)
        and all(functions[label] == 0 for label in role_labels),
        "postgresql.user_function_execute",
    ))
    expected_objects = set((*_PG_TABLES, *_PG_SEQUENCES))
    if not isinstance(objects, Mapping) or set(objects) != expected_objects:
        checks.append((False, "postgresql.objects"))
    else:
        for name in _PG_TABLES:
            item = objects[name]
            checks.append((
                isinstance(item, Mapping)
                and set(item) == {
                    "exists", "owner_class", "runtime_privileges",
                    "runtime_column_privilege_count",
                    "runtime_column_privilege_sha256",
                    "runtime_column_only_privileges",
                }
                and item.get("exists") is True
                and item.get("owner_class") == "owner"
                and item.get("runtime_privileges") == ["SELECT", "INSERT"]
                and type(item.get("runtime_column_privilege_count")) is int
                and item.get("runtime_column_privilege_count") >= 0
                and _is_sha256(item.get("runtime_column_privilege_sha256"))
                and item.get("runtime_column_only_privileges") == [],
                f"postgresql.object.{name}",
            ))
        for name in _PG_SEQUENCES:
            item = objects[name]
            checks.append((
                isinstance(item, Mapping)
                and set(item) == {"exists", "owner_class", "runtime_privileges"}
                and item.get("exists") is True
                and item.get("owner_class") == "owner"
                and item.get("runtime_privileges") == ["SELECT", "USAGE"],
                f"postgresql.object.{name}",
            ))
    acl = facts["acl_projection"]
    acl_valid = (
        isinstance(acl, list) and len(acl) <= 512
        and all(
            isinstance(row, Mapping)
            and set(row) == {"scope", "object_sha256", "grantor", "grantee", "privilege", "grantable"}
            and isinstance(row["scope"], str)
            and isinstance(row["object_sha256"], str)
            and isinstance(row["grantor"], str)
            and isinstance(row["grantee"], str)
            and isinstance(row["privilege"], str)
            and type(row["grantable"]) is bool
            for row in acl
        )
    )
    checks.append((acl_valid, "postgresql.acl_projection"))
    if acl_valid:
        allowed_non_owner_acl = {
            (
                "database",
                sha256_bytes(str(pg["database"]).encode("utf-8")),
                label,
                "CONNECT",
            )
            for label in ("migrator", "runtime", "audit")
        } | {
            ("schema", sha256_bytes(b"public"), "runtime", "USAGE")
        } | {
            ("relation", sha256_bytes(name.encode("utf-8")), "runtime", privilege)
            for name in _PG_TABLES
            for privilege in ("SELECT", "INSERT")
        } | {
            ("sequence", sha256_bytes(name.encode("utf-8")), "runtime", privilege)
            for name in _PG_SEQUENCES
            for privilege in ("SELECT", "USAGE")
        }
        checks.extend([
            (facts["acl_projection_count"] == len(acl), "postgresql.acl_count"),
            (facts["acl_projection_sha256"] == sha256_bytes(canonical_json(acl)), "postgresql.acl_digest"),
            (
                len({canonical_json(row) for row in acl}) == len(acl),
                "postgresql.acl_duplicates",
            ),
            (not any(row["grantee"] == "public" for row in acl), "postgresql.public_acl"),
            (
                not any(
                    row["grantee"] not in role_labels
                    or row["grantor"] != "owner"
                    for row in acl
                ),
                "postgresql.unknown_acl_principal",
            ),
            (
                not any(
                    row["grantee"] in {"migrator", "runtime", "audit"}
                    and row["grantable"] is True for row in acl
                ),
                "postgresql.grantable_acl",
            ),
            (
                not any(
                    row["grantee"] in {"migrator", "runtime", "audit"}
                    and (
                        row["scope"], row["object_sha256"],
                        row["grantee"], row["privilege"],
                    ) not in allowed_non_owner_acl
                    for row in acl
                ),
                "postgresql.non_owner_acl_scope",
            ),
            (
                {
                    (
                        row["scope"], row["object_sha256"],
                        row["grantee"], row["privilege"],
                    )
                    for row in acl
                    if row["grantee"] != "owner"
                }
                == allowed_non_owner_acl,
                "postgresql.required_acl",
            ),
        ])
    checks.extend([
        (
            facts["runtime_out_of_contract_write_privilege_sha256"]
            == sha256_bytes(canonical_json([])),
            "postgresql.runtime_out_of_contract_write_privilege_digest",
        ),
        (
            facts["runtime_out_of_contract_read_privilege_sha256"]
            == sha256_bytes(canonical_json([])),
            "postgresql.runtime_out_of_contract_read_privilege_digest",
        ),
        (
            facts["audit_data_read_privilege_sha256"]
            == sha256_bytes(canonical_json([])),
            "postgresql.audit_data_read_privilege_digest",
        ),
        (
            facts["audit_write_privilege_sha256"]
            == sha256_bytes(canonical_json([])),
            "postgresql.audit_write_privilege_digest",
        ),
        (
            facts["audit_column_write_privilege_sha256"]
            == sha256_bytes(canonical_json([])),
            "postgresql.audit_column_write_privilege_digest",
        ),
        (
            facts["authority_boundary_deviation_sha256"]
            == sha256_bytes(canonical_json([])),
            "postgresql.authority_boundary_deviation_digest",
        ),
        (
            isinstance(facts["grantable_acl_counts"], Mapping)
            and set(facts["grantable_acl_counts"]) == role_labels
            and all(
                type(facts["grantable_acl_counts"][label]) is int
                for label in role_labels
            )
            and all(facts["grantable_acl_counts"][label] == 0 for label in ("migrator", "runtime", "audit")),
            "postgresql.grantable_acl_counts",
        ),
        (
            isinstance(facts["public_acl_entry_counts"], Mapping)
            and set(facts["public_acl_entry_counts"]) == {"database", "schema", "relation", "sequence", "column"}
            and all(
                type(value) is int
                for value in facts["public_acl_entry_counts"].values()
            )
            and all(value == 0 for value in facts["public_acl_entry_counts"].values()),
            "postgresql.public_acl_counts",
        ),
    ])
    failures.extend(code for ok, code in checks if not ok)
    return failures


def _neo4j_community_projection_failures(
    facts: Mapping[str, Any], policy: Mapping[str, Any], request_nonce: str
) -> list[str]:
    """Verify the exact development-only Community fact schema.

    Community has no RBAC, so the projection attests identity, native-only
    auth, principal existence, and authority-snapshot stability instead of
    role bindings; it never claims ``audit_principal_read_only``.
    """

    neo = policy["neo4j"]
    failures: list[str] = []
    principal_labels = ("audit", "migrator", "runtime")
    expected_user_hashes = {
        label: sha256_bytes(str(neo[f"{label}_user"]).encode("utf-8"))
        for label in principal_labels
    }
    named_users = facts["named_user_sha256"]
    named_suspended = facts["named_user_suspended"]
    checks: list[tuple[bool, str]] = [
        (facts["database"] == neo["database"], "neo4j.database"),
        (facts["database_name_matches"] is True, "neo4j.database_match"),
        (facts["database_direct_local"] is True, "neo4j.database_direct_local"),
        (
            type(facts["database_alias_count"]) is int
            and facts["database_alias_count"] == 0,
            "neo4j.database_alias",
        ),
        (
            facts["database_alias_sha256"] == sha256_bytes(canonical_json([])),
            "neo4j.database_alias_digest",
        ),
        (
            _is_sha256(facts["database_catalog_sha256"]),
            "neo4j.database_catalog_digest",
        ),
        (
            facts["challenge_nonce_sha256"] == sha256_bytes(request_nonce.encode("ascii")),
            "neo4j.challenge_binding",
        ),
        (
            facts["enterprise"] is False
            and str(facts["edition"]).lower() == "community",
            "neo4j.community.edition",
        ),
        (facts["community_semantics"] is True, "neo4j.community.semantics"),
        (facts["rbac_available"] is False, "neo4j.community.rbac_available"),
        (
            _neo_community_version_supported(facts["version"]),
            "neo4j.community.version",
        ),
        (_is_sha256(facts["database_id_sha256"]), "neo4j.database_id"),
        (facts["current_actor_sha256"] == sha256_bytes(str(neo["audit_user"]).encode("utf-8")), "neo4j.current_actor"),
        (
            isinstance(named_users, Mapping)
            and set(named_users) == set(principal_labels)
            and all(
                named_users[label] == expected_user_hashes[label]
                for label in principal_labels
            ),
            "neo4j.community.named_users",
        ),
        (
            isinstance(named_suspended, Mapping)
            and set(named_suspended) == set(principal_labels)
            and all(
                named_suspended[label] is False for label in principal_labels
            ),
            "neo4j.community.named_user_suspended",
        ),
        (
            _neo_native_auth_settings_exact(
                facts["auth_settings"], version=facts["version"]
            ),
            "neo4j.native_only_auth_settings",
        ),
        (facts["native_only_auth"] is True, "neo4j.native_only_auth"),
        (
            facts["auth_settings_sha256"]
            == sha256_bytes(canonical_json(facts["auth_settings"])),
            "neo4j.auth_settings_digest",
        ),
        (
            _is_sha256(facts["system_database_id_sha256"]),
            "neo4j.system_database_id",
        ),
        (
            type(facts["system_last_committed_tx"]) is int
            and facts["system_last_committed_tx"] >= 0,
            "neo4j.system_last_committed_tx",
        ),
        (
            facts["authorization_snapshot_stable"] is True,
            "neo4j.authorization_snapshot",
        ),
        (
            type(facts["read_query_count"]) is int
            and facts["read_query_count"] == _NEO_COMMUNITY_READ_QUERY_COUNT,
            "neo4j.community.read_query_count",
        ),
    ]
    failures.extend(code for ok, code in checks if not ok)
    return failures


def _neo4j_projection_failures(
    facts: Mapping[str, Any], policy: Mapping[str, Any], request_nonce: str
) -> list[str]:
    if (
        policy["environment"] == "development"
        and isinstance(facts, Mapping)
        and set(facts) == _NEO_COMMUNITY_FACT_KEYS
        and facts["community_semantics"] is True
    ):
        # Development-only Community schema; an Enterprise-shaped facts object
        # still verifies below with the unchanged Enterprise checks.
        return _neo4j_community_projection_failures(facts, policy, request_nonce)
    if set(facts) != _NEO_FACT_KEYS:
        return ["neo4j.fact_schema"]
    neo = policy["neo4j"]
    failures: list[str] = []
    expected_role_hashes = {
        label: sha256_bytes(str(neo[f"{label}_role"]).encode("utf-8"))
        for label in ("audit", "migrator", "runtime")
    }
    expected_user_role_hashes = {
        label: {
            expected_role_hashes[label],
            sha256_bytes(b"PUBLIC"),
            sha256_bytes(b"public"),
        }
        for label in expected_role_hashes
    }
    named = facts["named_role_privileges"]
    named_valid = isinstance(named, Mapping) and set(named) == {
        "audit", "migrator", "runtime", "public"
    }
    named_rows = {
        label: _neo_privilege_rows(named[label]) if named_valid else None
        for label in ("audit", "migrator", "runtime", "public")
    }
    effective = _neo_privilege_rows(facts["effective_privileges"])
    unsafe_effective = (
        None if effective is None else [
            row for row in effective if not _neo_audit_row_safe(row, neo["database"])
        ]
    )
    role_digests = facts["named_role_privilege_sha256"]
    user_roles = facts["named_user_role_sha256"]
    role_assignees = facts["named_role_assignee_sha256"]
    checks: list[tuple[bool, str]] = [
        (facts["database"] == neo["database"], "neo4j.database"),
        (facts["database_name_matches"] is True, "neo4j.database_match"),
        (facts["database_direct_local"] is True, "neo4j.database_direct_local"),
        (
            type(facts["database_alias_count"]) is int
            and facts["database_alias_count"] == 0,
            "neo4j.database_alias",
        ),
        (
            facts["database_alias_sha256"] == sha256_bytes(canonical_json([])),
            "neo4j.database_alias_digest",
        ),
        (
            _is_sha256(facts["database_catalog_sha256"]),
            "neo4j.database_catalog_digest",
        ),
        (
            facts["challenge_nonce_sha256"] == sha256_bytes(request_nonce.encode("ascii")),
            "neo4j.challenge_binding",
        ),
        (facts["enterprise"] is True and str(facts["edition"]).lower() == "enterprise", "neo4j.enterprise"),
        (_neo_version_supported(facts["version"]), "neo4j.version"),
        (_is_sha256(facts["database_id_sha256"]), "neo4j.database_id"),
        (facts["current_actor_sha256"] == sha256_bytes(str(neo["audit_user"]).encode("utf-8")), "neo4j.current_actor"),
        (facts["audit_principal_read_only"] is True, "neo4j.audit_read_only"),
        (facts["custom_role_binding_ok"] is True, "neo4j.custom_role_binding"),
        (facts["named_user_role_binding_ok"] is True, "neo4j.user_role_binding"),
        (facts["named_role_sha256"] == expected_role_hashes, "neo4j.named_roles"),
        (
            isinstance(facts["role_sha256"], list)
            and len(facts["role_sha256"]) == 2
            and len(set(facts["role_sha256"])) == 2
            and expected_role_hashes["audit"] in facts["role_sha256"]
            and any(
                item in {sha256_bytes(b"PUBLIC"), sha256_bytes(b"public")}
                for item in facts["role_sha256"]
                if item != expected_role_hashes["audit"]
            ),
            "neo4j.current_roles",
        ),
        (
            type(facts["role_count"]) is int
            and facts["role_count"] == len(facts["role_sha256"]),
            "neo4j.role_count",
        ),
        (named_valid and all(rows is not None for rows in named_rows.values()), "neo4j.privilege_schema"),
        (_neo_role_rows_exact(named_rows["runtime"], database=neo["database"], migrator=False), "neo4j.runtime_privileges"),
        (_neo_role_rows_exact(named_rows["migrator"], database=neo["database"], migrator=True), "neo4j.migrator_privileges"),
        (
            _neo_audit_rows_exact(
                named_rows["audit"], database=neo["database"], version=facts["version"]
            ),
            "neo4j.audit_role_privileges",
        ),
        (named_rows["public"] == [], "neo4j.public_privileges"),
        (effective == named_rows["audit"], "neo4j.effective_privileges"),
        (effective is not None and unsafe_effective == [], "neo4j.audit_unsafe_action"),
        (
            type(facts["audit_unsafe_granted_action_count"]) is int
            and facts["audit_unsafe_granted_action_count"] == 0,
            "neo4j.audit_unsafe_count",
        ),
        (facts["runtime_role_least_privilege"] is True, "neo4j.runtime_least_privilege"),
        (facts["migrator_role_least_privilege"] is True, "neo4j.migrator_least_privilege"),
        (facts["public_role_safe"] is True, "neo4j.public_role_safe"),
        (
            _neo_native_auth_settings_exact(
                facts["auth_settings"], version=facts["version"]
            ),
            "neo4j.native_only_auth_settings",
        ),
        (facts["native_only_auth"] is True, "neo4j.native_only_auth"),
        (
            _is_sha256(facts["system_database_id_sha256"]),
            "neo4j.system_database_id",
        ),
        (
            type(facts["system_last_committed_tx"]) is int
            and facts["system_last_committed_tx"] >= 0,
            "neo4j.system_last_committed_tx",
        ),
        (
            facts["authorization_snapshot_stable"] is True,
            "neo4j.authorization_snapshot",
        ),
        (
            type(facts["global_unsafe_privilege_count"]) is int
            and facts["global_unsafe_privilege_count"] == 0,
            "neo4j.global_unsafe_privilege",
        ),
        (
            facts["global_unsafe_privilege_sha256"]
            == sha256_bytes(canonical_json([])),
            "neo4j.global_unsafe_privilege_digest",
        ),
        (
            facts["auth_settings_sha256"]
            == sha256_bytes(canonical_json(facts["auth_settings"])),
            "neo4j.auth_settings_digest",
        ),
        (
            type(facts["read_query_count"]) is int
            and facts["read_query_count"] == 12,
            "neo4j.read_query_count",
        ),
    ]
    if effective is not None:
        checks.extend([
            (
                type(facts["effective_privilege_count"]) is int
                and facts["effective_privilege_count"] == len(effective),
                "neo4j.effective_privilege_count",
            ),
            (facts["effective_privilege_sha256"] == sha256_bytes(canonical_json(effective)), "neo4j.effective_privilege_digest"),
            (facts["audit_unsafe_granted_action_sha256"] == sha256_bytes(canonical_json(unsafe_effective)), "neo4j.audit_unsafe_digest"),
        ])
    if named_valid:
        checks.extend([
            (
                isinstance(role_digests, Mapping)
                and set(role_digests) == {"audit", "migrator", "runtime"}
                and all(
                    role_digests[label] == sha256_bytes(canonical_json(named_rows[label]))
                    for label in ("audit", "migrator", "runtime")
                ),
                "neo4j.named_role_privilege_digest",
            ),
            (
                facts["public_role_binding_sha256"]
                == sha256_bytes(canonical_json(named_rows["public"])),
                "neo4j.public_role_digest",
            ),
        ])
    checks.append((
        isinstance(user_roles, Mapping) and set(user_roles) == {"audit", "migrator", "runtime"}
        and all(
            isinstance(user_roles[label], list)
            and len(user_roles[label]) == 2
            and len(set(user_roles[label])) == 2
            and all(_is_sha256(item) for item in user_roles[label])
            and expected_role_hashes[label] in user_roles[label]
            and any(item in expected_user_role_hashes[label] - {expected_role_hashes[label]} for item in user_roles[label])
            for label in ("audit", "migrator", "runtime")
        ),
        "neo4j.user_role_hashes",
    ))
    checks.append((
        isinstance(role_assignees, Mapping)
        and set(role_assignees) == {"audit", "migrator", "runtime"}
        and all(
            role_assignees[label] == [
                sha256_bytes(str(neo[f"{label}_user"]).encode("utf-8"))
            ]
            for label in ("audit", "migrator", "runtime")
        ),
        "neo4j.role_assignees",
    ))
    failures.extend(code for ok, code in checks if not ok)
    return failures


def _projection_failures(
    store: str,
    facts: Mapping[str, Any],
    policy: Mapping[str, Any],
    request_nonce: str,
    target_binding: Mapping[str, Any],
) -> list[str]:
    if store == "postgresql":
        failures = _postgresql_projection_failures(facts, policy, request_nonce)
        if not (
            facts.get("database_oid_sha256")
            == sha256_bytes(str(target_binding.get("database_oid")).encode("utf-8"))
        ):
            failures.append("postgresql.target_database_oid_binding")
        if not (
            facts.get("system_identifier_sha256")
            == sha256_bytes(
                str(target_binding.get("system_identifier")).encode("utf-8")
            )
        ):
            failures.append("postgresql.target_system_identifier_binding")
        return failures
    failures = _neo4j_projection_failures(facts, policy, request_nonce)
    if not (
        facts.get("database_id_sha256")
        == sha256_bytes(str(target_binding.get("database_id")).encode("utf-8"))
    ):
        failures.append("neo4j.target_database_id_binding")
    return failures


def verify_datastore_attestation(
    value: Any,
    *,
    policy: Mapping[str, Any],
    expected: Mapping[str, Any],
    expected_store: str,
    expected_phase: str,
    expected_position: str,
    expected_signer_did: str,
    evaluated_at: datetime,
) -> AttestationVerification:
    failures: list[str] = []
    try:
        policy = validate_access_policy(policy)
        expected = validate_expected(expected, policy)
        attestation = _exact_mapping(
            value,
            path="attestation",
            keys=set(_ATTESTATION_BODY_FIELDS) | {"signature"},
        )
        body = dict(attestation)
        signature_hex = body.pop("signature")
        datastore_attestation_signing_bytes(body)
        if not (
            isinstance(signature_hex, str) and len(signature_hex) == 128
            and all(char in _HEX for char in signature_hex)
        ):
            raise StorageAccessError("attestation signature must be lowercase Ed25519 hex")
        store = _text(body["store"], path="attestation.store")
        phase = _text(body["phase"], path="attestation.phase")
        position = _text(body["position"], path="attestation.position")
        if store not in STORES or phase not in PHASES or position not in POSITIONS:
            raise StorageAccessError("attestation store/phase/position is unsupported")
        _sha(body["request_nonce"], path="attestation.request_nonce")
        for field in (
            "request_sha256", "target_sha256", "operation_sha256",
            "access_policy_file_sha256", "predeploy_receipt_file_sha256",
            "predeploy_receipt_sha256",
        ):
            _sha(body[field], path=f"attestation.{field}")
        previous = body["previous_phase_bundle_file_sha256"]
        if previous is not None:
            _sha(previous, path="attestation.previous_phase_bundle_file_sha256")
        _text(body["environment"], path="attestation.environment", maximum=128)
        signer_did = _text(body["signer_did"], path="attestation.signer_did", maximum=256)
        observed_at = _parse_time(body["observed_at"], path="attestation.observed_at")
        expires_at = _parse_time(body["expires_at"], path="attestation.expires_at")
        refs = body["evidence_refs"]
        if (
            not isinstance(refs, list) or not refs or len(refs) > 32
            or any(not isinstance(item, str) or not item or len(item) > 512 for item in refs)
            or len(set(refs)) != len(refs)
        ):
            raise StorageAccessError("attestation evidence_refs are invalid")
        observation = _validate_observation_shape(body["observation"])
        target_binding = _exact_mapping(
            body["target_binding"],
            path="attestation.target_binding",
            keys=set(_validate_target_details(expected["target_details"], policy)[store]),
        )
        try:
            public = did_key_decode(signer_did)
        except CertError as exc:
            raise StorageAccessError("attestation signer DID is invalid") from exc
        signature_ok = (
            did_key_encode(public) == signer_did
            and ed25519_public_key_is_strict(public)
            and ed25519_verify(
                public,
                DATASTORE_ATTESTATION_DOMAIN + canonical_json(body),
                bytes.fromhex(signature_hex),
            )
        )
        checks = [
            (signature_ok, "signature_invalid"),
            (store == expected_store, "store_mismatch"),
            (phase == expected_phase, "phase_mismatch"),
            (position == expected_position, "position_mismatch"),
            (signer_did == expected_signer_did, "signer_mismatch"),
            (body["environment"] == policy["environment"], "environment_mismatch"),
            (
                target_binding == expected["target_details"][store],
                "target_binding_mismatch",
            ),
            (
                observed_at <= evaluated_at < expires_at
                and timedelta(0) < expires_at - observed_at <= timedelta(seconds=MAX_VALIDITY_SECONDS),
                "freshness_invalid",
            ),
        ]
        for field in (
            "request_nonce", "request_sha256", "target_sha256",
            "operation_sha256", "access_policy_file_sha256",
            "predeploy_receipt_file_sha256", "predeploy_receipt_sha256",
            "previous_phase_bundle_file_sha256",
        ):
            checks.append((body[field] == expected[field], f"{field}_mismatch"))
        failures.extend(code for ok, code in checks if not ok)
        failures.extend(
            _projection_failures(
                store,
                observation["facts"],
                policy,
                body["request_nonce"],
                target_binding,
            )
        )
        body_sha = sha256_bytes(canonical_json(body))
        return AttestationVerification(
            not failures, tuple(sorted(set(failures))), body_sha, observed_at
        )
    except (StorageAccessError, CertError, KeyError, ValueError, TypeError, OverflowError):
        return AttestationVerification(False, ("malformed",), None, None)


def verify_datastore_attestation_pair(
    before: Any,
    after: Any,
    *,
    policy: Mapping[str, Any],
    expected: Mapping[str, Any],
    store: str,
    phase: str,
    signer_did: str,
    evaluated_at: datetime,
) -> StorageAuditProof:
    before_result = verify_datastore_attestation(
        before, policy=policy, expected=expected, expected_store=store,
        expected_phase=phase, expected_position="before",
        expected_signer_did=signer_did, evaluated_at=evaluated_at,
    )
    after_result = verify_datastore_attestation(
        after, policy=policy, expected=expected, expected_store=store,
        expected_phase=phase, expected_position="after",
        expected_signer_did=signer_did, evaluated_at=evaluated_at,
    )
    failures = [
        *(f"before.{item}" for item in before_result.failures),
        *(f"after.{item}" for item in after_result.failures),
    ]
    observation_sha = None
    if before_result.ok and after_result.ok:
        before_observation = before["observation"]
        after_observation = after["observation"]
        before_sha = sha256_bytes(canonical_json(before_observation))
        after_sha = sha256_bytes(canonical_json(after_observation))
        if not hmac.compare_digest(before_sha, after_sha):
            failures.append("observation_drift")
        else:
            observation_sha = before_sha
        if not (
            before_result.observed_at is not None
            and after_result.observed_at is not None
            and before_result.observed_at <= after_result.observed_at
        ):
            failures.append("observation_order_invalid")
    return StorageAuditProof(
        not failures,
        tuple(sorted(set(failures))),
        phase,
        expected.get("request_sha256") if not failures else None,
        before_result.body_sha256,
        after_result.body_sha256,
        observation_sha,
    )


def build_attestation_body(
    *,
    store: str,
    phase: str,
    position: str,
    expected: Mapping[str, Any],
    environment: str,
    observation: Mapping[str, Any],
    target_binding: Mapping[str, Any],
    observed_at: str,
    expires_at: str,
    evidence_refs: Sequence[str],
    signer_did: str,
) -> dict[str, Any]:
    """Build an exact unsigned body; verification remains the authority."""

    return {
        "schema_version": DATASTORE_ATTESTATION_SCHEMA,
        "store": store,
        "phase": phase,
        "position": position,
        "request_nonce": expected["request_nonce"],
        "request_sha256": expected["request_sha256"],
        "environment": environment,
        "target_sha256": expected["target_sha256"],
        "operation_sha256": expected["operation_sha256"],
        "access_policy_file_sha256": expected["access_policy_file_sha256"],
        "predeploy_receipt_file_sha256": expected["predeploy_receipt_file_sha256"],
        "predeploy_receipt_sha256": expected["predeploy_receipt_sha256"],
        "previous_phase_bundle_file_sha256": expected["previous_phase_bundle_file_sha256"],
        "target_binding": dict(target_binding),
        "observation": dict(observation),
        "observed_at": observed_at,
        "expires_at": expires_at,
        "evidence_refs": list(evidence_refs),
        "signer_did": signer_did,
    }


def build_storage_audit_bundle(
    *,
    phase: str,
    request_nonce: str,
    request_sha256: str,
    previous_phase_bundle_file_sha256: str | None,
    postgresql_before: Mapping[str, Any],
    postgresql_after: Mapping[str, Any],
    neo4j_before: Mapping[str, Any],
    neo4j_after: Mapping[str, Any],
) -> dict[str, Any]:
    body = {
        "schema_version": STORAGE_AUDIT_BUNDLE_SCHEMA,
        "phase": phase,
        "request_nonce": request_nonce,
        "request_sha256": request_sha256,
        "previous_phase_bundle_file_sha256": previous_phase_bundle_file_sha256,
        "attestations": {
            "postgresql": {
                "before": dict(postgresql_before),
                "after": dict(postgresql_after),
            },
            "neo4j": {
                "before": dict(neo4j_before),
                "after": dict(neo4j_after),
            },
        },
    }
    return {**body, "bundle_sha256": sha256_bytes(canonical_json(body))}


def verify_storage_audit_bundle(
    value: Any,
    *,
    policy: Mapping[str, Any],
    expected: Mapping[str, Any],
    phase: str,
    signer_dids: Mapping[str, str],
    evaluated_at: datetime,
) -> StorageAuditBundleProof:
    failures: list[str] = []
    empty_pg = StorageAuditProof(False, ("bundle.malformed",), phase, None, None, None, None)
    empty_neo = StorageAuditProof(False, ("bundle.malformed",), phase, None, None, None, None)
    try:
        bundle = _exact_mapping(
            value,
            path="bundle",
            keys={
                "schema_version", "phase", "request_nonce", "request_sha256",
                "previous_phase_bundle_file_sha256", "attestations", "bundle_sha256",
            },
        )
        bundle_body = dict(bundle)
        bundle_sha = bundle_body.pop("bundle_sha256")
        _sha(bundle_sha, path="bundle.bundle_sha256")
        if not hmac.compare_digest(
            bundle_sha, sha256_bytes(canonical_json(bundle_body))
        ):
            raise StorageAccessError("bundle self digest is invalid")
        if bundle["schema_version"] != STORAGE_AUDIT_BUNDLE_SCHEMA:
            raise StorageAccessError("bundle schema is unsupported")
        if bundle["phase"] != phase or phase not in PHASES:
            raise StorageAccessError("bundle phase mismatch")
        _sha(bundle["request_nonce"], path="bundle.request_nonce")
        _sha(bundle["request_sha256"], path="bundle.request_sha256")
        previous = bundle["previous_phase_bundle_file_sha256"]
        if previous is not None:
            _sha(previous, path="bundle.previous_phase_bundle_file_sha256")
        if bundle["request_nonce"] != expected["request_nonce"]:
            failures.append("bundle.request_nonce_mismatch")
        if bundle["request_sha256"] != expected["request_sha256"]:
            failures.append("bundle.request_sha256_mismatch")
        if previous != expected["previous_phase_bundle_file_sha256"]:
            failures.append("bundle.previous_phase_binding_mismatch")
        if phase == "predeploy" and previous is not None:
            failures.append("bundle.predeploy_previous_phase_forbidden")
        if phase == "startup" and previous is None:
            failures.append("bundle.startup_previous_phase_required")
        if (
            set(signer_dids) != set(STORES)
            or len(set(signer_dids.values())) != 2
            or dict(signer_dids) != dict(policy["attestors"])
        ):
            failures.append("bundle.store_signers_not_separated")
        attestations = _exact_mapping(
            bundle["attestations"], path="bundle.attestations", keys=set(STORES)
        )
        pairs: dict[str, Mapping[str, Any]] = {}
        for store in STORES:
            pairs[store] = _exact_mapping(
                attestations[store],
                path=f"bundle.attestations.{store}",
                keys=set(POSITIONS),
            )
        pg_proof = verify_datastore_attestation_pair(
            pairs["postgresql"]["before"], pairs["postgresql"]["after"],
            policy=policy, expected=expected, store="postgresql", phase=phase,
            signer_did=signer_dids["postgresql"], evaluated_at=evaluated_at,
        )
        neo_proof = verify_datastore_attestation_pair(
            pairs["neo4j"]["before"], pairs["neo4j"]["after"],
            policy=policy, expected=expected, store="neo4j", phase=phase,
            signer_did=signer_dids["neo4j"], evaluated_at=evaluated_at,
        )
        failures.extend(f"postgresql.{item}" for item in pg_proof.failures)
        failures.extend(f"neo4j.{item}" for item in neo_proof.failures)
        observation_times = {
            (store, position): _parse_time(
                pairs[store][position]["observed_at"],
                path=f"bundle.{store}.{position}.observed_at",
            )
            for store in STORES
            for position in POSITIONS
        }
        if not (
            observation_times[("postgresql", "before")]
            <= observation_times[("neo4j", "before")]
            <= observation_times[("postgresql", "after")]
            <= observation_times[("neo4j", "after")]
        ):
            failures.append("bundle.cross_store_observation_order_invalid")
        return StorageAuditBundleProof(
            not failures, tuple(sorted(set(failures))), phase, pg_proof, neo_proof
        )
    except (StorageAccessError, KeyError, TypeError, ValueError):
        return StorageAuditBundleProof(
            False, ("bundle.malformed",), phase, empty_pg, empty_neo
        )


def verify_access_attestation_pair(
    predeploy_bundle: Any,
    startup_bundle: Any,
    *,
    predeploy_bundle_file_sha256: str,
    policy: Mapping[str, Any],
    expected_predeploy: Mapping[str, Any],
    expected_startup: Mapping[str, Any],
    signer_dids: Mapping[str, str],
    evaluated_at: datetime,
) -> AccessPairProof:
    """Verify the signed phase pair without granting production approval."""

    failures: list[str] = []
    try:
        _sha(predeploy_bundle_file_sha256, path="predeploy_bundle_file_sha256")
        observed_predeploy_sha = sha256_bytes(canonical_json(predeploy_bundle))
        if not hmac.compare_digest(
            observed_predeploy_sha, predeploy_bundle_file_sha256
        ):
            failures.append("predeploy.bundle_raw_sha_mismatch")
        predeploy_after_times = [
            _parse_time(
                predeploy_bundle["attestations"][store]["after"]["observed_at"],
                path=f"predeploy.{store}.after.observed_at",
            )
            for store in STORES
        ]
        predeploy_evaluated_at = max(predeploy_after_times)
    except (KeyError, TypeError, StorageAccessError, ValueError):
        predeploy_evaluated_at = evaluated_at
        failures.append("predeploy.bundle_time_malformed")
    predeploy = verify_storage_audit_bundle(
        predeploy_bundle,
        policy=policy,
        expected=expected_predeploy,
        phase="predeploy",
        signer_dids=signer_dids,
        evaluated_at=predeploy_evaluated_at,
    )
    startup = verify_storage_audit_bundle(
        startup_bundle,
        policy=policy,
        expected=expected_startup,
        phase="startup",
        signer_dids=signer_dids,
        evaluated_at=evaluated_at,
    )
    failures.extend(f"predeploy.{item}" for item in predeploy.failures)
    failures.extend(f"startup.{item}" for item in startup.failures)
    if expected_startup.get("previous_phase_bundle_file_sha256") != predeploy_bundle_file_sha256:
        failures.append("startup.predeploy_bundle_sha_mismatch")
    if expected_predeploy.get("request_nonce") == expected_startup.get("request_nonce"):
        failures.append("phase_nonce_reused")
    for field in (
        "target_sha256", "operation_sha256",
        "access_policy_file_sha256", "predeploy_receipt_file_sha256",
        "predeploy_receipt_sha256",
    ):
        if expected_predeploy.get(field) != expected_startup.get(field):
            failures.append(f"phase_{field}_drift")
    if predeploy.ok and startup.ok:
        for store in STORES:
            def stable_projection(bundle: Mapping[str, Any]) -> str:
                observation = dict(
                    bundle["attestations"][store]["before"]["observation"]
                )
                facts = dict(observation["facts"])
                facts.pop("challenge_nonce_sha256", None)
                observation["facts"] = facts
                return sha256_bytes(canonical_json(observation))

            predeploy_projection = stable_projection(predeploy_bundle)
            startup_projection = stable_projection(startup_bundle)
            if not (
                isinstance(predeploy_projection, str)
                and isinstance(startup_projection, str)
                and hmac.compare_digest(predeploy_projection, startup_projection)
            ):
                failures.append(f"{store}.phase_projection_drift")
        try:
            startup_before_times = [
                _parse_time(
                    startup_bundle["attestations"][store]["before"]["observed_at"],
                    path=f"startup.{store}.before.observed_at",
                )
                for store in STORES
            ]
            predeploy_expiry = min(
                _parse_time(
                    predeploy_bundle["attestations"][store][position]["expires_at"],
                    path=f"predeploy.{store}.{position}.expires_at",
                )
                for store in STORES
                for position in POSITIONS
            )
            if not (
                predeploy_evaluated_at <= min(startup_before_times)
                and max(startup_before_times) < predeploy_expiry
            ):
                failures.append("phase_handoff_window_invalid")
        except (KeyError, TypeError, StorageAccessError, ValueError):
            failures.append("phase_handoff_time_malformed")
    failures = sorted(set(failures))
    status = "ACCESS_PAIR_VERIFIED" if not failures else "NOT_READY"
    # A verified development pair is honestly self-labelled and can never be
    # promoted: production_ready stays False and the deployment status names
    # the development boundary instead of the production NOT_READY shape.
    deployment_status = (
        "DEVELOPMENT_ONLY"
        if (
            status == "ACCESS_PAIR_VERIFIED"
            and isinstance(policy, Mapping)
            and policy.get("environment") == "development"
        )
        else "NOT_READY"
    )
    return AccessPairProof(
        status,
        False,
        deployment_status,
        tuple(failures),
        predeploy,
        startup,
    )


def _expected_from_bundle(
    bundle: Mapping[str, Any], policy: Mapping[str, Any]
) -> Mapping[str, Any]:
    bundle = _exact_mapping(
        bundle,
        path="bundle",
        keys={
            "schema_version", "phase", "request_nonce", "request_sha256",
            "previous_phase_bundle_file_sha256", "attestations", "bundle_sha256",
        },
    )
    attestations = _exact_mapping(
        bundle["attestations"], path="bundle.attestations", keys=set(STORES)
    )
    first_by_store: dict[str, Mapping[str, Any]] = {}
    for store in STORES:
        pair = _exact_mapping(
            attestations[store],
            path=f"bundle.attestations.{store}",
            keys=set(POSITIONS),
        )
        first_by_store[store] = _exact_mapping(
            pair["before"],
            path=f"bundle.attestations.{store}.before",
            keys=set(_ATTESTATION_BODY_FIELDS) | {"signature"},
        )
    first = first_by_store["postgresql"]
    expected = {
        "request_nonce": bundle["request_nonce"],
        "request_sha256": bundle["request_sha256"],
        "target_sha256": first["target_sha256"],
        "target_details": {
            store: dict(first_by_store[store]["target_binding"])
            for store in STORES
        },
        "operation_sha256": first["operation_sha256"],
        "access_policy_file_sha256": first["access_policy_file_sha256"],
        "predeploy_receipt_file_sha256": first["predeploy_receipt_file_sha256"],
        "predeploy_receipt_sha256": first["predeploy_receipt_sha256"],
        "previous_phase_bundle_file_sha256": bundle[
            "previous_phase_bundle_file_sha256"
        ],
    }
    return validate_expected(expected, policy)


def verify_access_attestation_pair_bytes(
    predeploy_raw: bytes,
    startup_raw: bytes,
    *,
    expected_predeploy_file_sha256: str,
    expected_startup_file_sha256: str,
    policy_raw: bytes,
    expected_policy_file_sha256: str,
    predeploy_receipt_raw: bytes,
    expected_predeploy_receipt_file_sha256: str,
    evaluated_at: datetime,
) -> AccessPairProof:
    """Strictly hash, parse, and verify the complete pinned access phase pair."""

    empty = StorageAuditBundleProof(
        False,
        ("bundle.malformed",),
        "predeploy",
        StorageAuditProof(False, ("bundle.malformed",), "predeploy", None, None, None, None),
        StorageAuditProof(False, ("bundle.malformed",), "predeploy", None, None, None, None),
    )
    try:
        for value, path in (
            (expected_predeploy_file_sha256, "expected_predeploy_file_sha256"),
            (expected_startup_file_sha256, "expected_startup_file_sha256"),
            (expected_policy_file_sha256, "expected_policy_file_sha256"),
            (
                expected_predeploy_receipt_file_sha256,
                "expected_predeploy_receipt_file_sha256",
            ),
        ):
            _sha(value, path=path)
        actual_predeploy_sha = sha256_bytes(predeploy_raw)
        actual_startup_sha = sha256_bytes(startup_raw)
        actual_policy_sha = sha256_bytes(policy_raw)
        actual_receipt_sha = sha256_bytes(predeploy_receipt_raw)
        if not all((
            hmac.compare_digest(actual_predeploy_sha, expected_predeploy_file_sha256),
            hmac.compare_digest(actual_startup_sha, expected_startup_file_sha256),
            hmac.compare_digest(actual_policy_sha, expected_policy_file_sha256),
            hmac.compare_digest(
                actual_receipt_sha, expected_predeploy_receipt_file_sha256
            ),
        )):
            raise StorageAccessError("pinned access artifact SHA mismatch")
        policy_value = strict_json_loads(policy_raw)
        policy = validate_access_policy(policy_value)
        predeploy_bundle = strict_json_loads(predeploy_raw)
        startup_bundle = strict_json_loads(startup_raw)
        receipt = strict_json_loads(predeploy_receipt_raw)
        if not all(isinstance(item, Mapping) for item in (
            predeploy_bundle, startup_bundle, receipt
        )):
            raise StorageAccessError("access artifact root must be an object")
        if not (
            canonical_json(predeploy_bundle) == predeploy_raw
            and canonical_json(startup_bundle) == startup_raw
        ):
            raise StorageAccessError("access bundles must use canonical JSON bytes")
        expected_predeploy = _expected_from_bundle(predeploy_bundle, policy)
        expected_startup = _expected_from_bundle(startup_bundle, policy)
        if not (
            expected_predeploy["access_policy_file_sha256"] == actual_policy_sha
            and expected_startup["access_policy_file_sha256"] == actual_policy_sha
            and expected_predeploy["predeploy_receipt_file_sha256"] == actual_receipt_sha
            and expected_startup["predeploy_receipt_file_sha256"] == actual_receipt_sha
        ):
            raise StorageAccessError("signed bundle artifact binding mismatch")
        receipt_body = dict(receipt)
        receipt_self_sha = receipt_body.get("receipt_sha256")
        if not (
            expected_predeploy["predeploy_receipt_sha256"] == receipt_self_sha
            and expected_startup["predeploy_receipt_sha256"] == receipt_self_sha
        ):
            raise StorageAccessError("signed bundle receipt identity mismatch")
        from server.storage_predeploy import (  # local: remains base-wheel importable
            _artifact_identity,
            operation_identity,
            principal_bindings,
            verify_predeploy_receipt_document,
        )

        artifact = _artifact_identity()
        operation = operation_identity(artifact)
        if not (
            operation.get("sha256") == expected_predeploy["operation_sha256"]
            and operation.get("sha256") == expected_startup["operation_sha256"]
        ):
            raise StorageAccessError(
                "signed operation differs from the measured running artifact"
            )
        verified_receipt = verify_predeploy_receipt_document(
            dict(receipt),
            file_sha256=actual_receipt_sha,
            expected_file_sha256=expected_predeploy_receipt_file_sha256,
            expected_environment=policy["environment"],
            expected_fence_verifier_sha256=policy["predeploy_authority"][
                "fence_verifier_sha256"
            ],
            expected_fence_public_key_hex=policy["predeploy_authority"][
                "fence_public_key_hex"
            ],
            artifact=artifact,
            operation=operation,
            target={
                "sha256": expected_predeploy["target_sha256"],
                "details": expected_predeploy["target_details"],
            },
            evaluated_at=evaluated_at,
            expected_principals=principal_bindings(
                postgresql_migrator=policy["postgresql"]["migrator_role"],
                postgresql_runtime=policy["postgresql"]["runtime_role"],
                neo4j_migrator=policy["neo4j"]["migrator_user"],
                neo4j_runtime=policy["neo4j"]["runtime_user"],
            ),
        )
        if verified_receipt["operation_sha256"] != expected_predeploy["operation_sha256"]:
            raise StorageAccessError("predeploy operation differs from signed bundle")
        proof = verify_access_attestation_pair(
            predeploy_bundle,
            startup_bundle,
            predeploy_bundle_file_sha256=actual_predeploy_sha,
            policy=policy,
            expected_predeploy=expected_predeploy,
            expected_startup=expected_startup,
            signer_dids=policy["attestors"],
            evaluated_at=evaluated_at,
        )
        if proof.status != "ACCESS_PAIR_VERIFIED":
            return proof
        expiries = [
            _parse_time(
                bundle["attestations"][store][position]["expires_at"],
                path=f"{phase}.{store}.{position}.expires_at",
            )
            for phase, bundle in (
                ("predeploy", predeploy_bundle),
                ("startup", startup_bundle),
            )
            for store in STORES
            for position in POSITIONS
        ]
        return replace(
            proof,
            environment=policy["environment"],
            target_sha256=expected_startup["target_sha256"],
            operation_sha256=expected_startup["operation_sha256"],
            artifact_identity_sha256=sha256_bytes(
                canonical_json(operation["artifact"])
            ),
            policy_file_sha256=actual_policy_sha,
            predeploy_receipt_file_sha256=actual_receipt_sha,
            predeploy_receipt_sha256=receipt_self_sha,
            predeploy_bundle_file_sha256=actual_predeploy_sha,
            startup_bundle_file_sha256=actual_startup_sha,
            valid_until=min(expiries).isoformat(),
            authority_identity_sha256s=tuple(sorted(
                sha256_bytes(did.encode("utf-8"))
                for did in policy["attestors"].values()
            )),
        )
    except Exception:  # noqa: BLE001 - verifier boundary always returns typed NOT_READY
        startup_empty = StorageAuditBundleProof(
            False,
            ("bundle.malformed",),
            "startup",
            StorageAuditProof(False, ("bundle.malformed",), "startup", None, None, None, None),
            StorageAuditProof(False, ("bundle.malformed",), "startup", None, None, None, None),
        )
        return AccessPairProof(
            "NOT_READY", False, "NOT_READY", ("access_pair.malformed",),
            empty, startup_empty,
        )
