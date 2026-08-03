"""Read-only live evidence collector for the production/L3 readiness harness.

This module is a capability shell around :mod:`server.production_readiness`, not
an approval engine.  It collects bounded, credential-redacted observations from
an explicitly pinned request and writes a canonical evidence bundle exactly
once.  It deliberately has no code path that emits ``production_ready``,
``HARNESS_GREEN``, or an L3 verdict.

The deterministic reviewer remains dependency-free.  PostgreSQL and Neo4j
drivers are imported lazily only when their adapters are configured.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import ipaddress
import json
import os
import re
import socket
import stat
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit

from server.storage_protocol import NEO4J_SUPPORTED_RELEASES, STORAGE_CONTRACT_ID
from server.runtime_authority import (
    RUNTIME_EFFECT_SCOPE,
    RuntimeAuthorityError,
    artifact_identity_sha256,
    verify_published_runtime_snapshot,
)


REQUEST_SCHEMA = "lakatotree-production-readiness-collection-request/v1"
REQUEST_SCHEMA_V2 = "lakatotree-production-readiness-collection-request/v2"
REQUEST_SCHEMA_V3 = "lakatotree-production-readiness-collection-request/v3"
EVIDENCE_SCHEMA = "lakatotree-production-readiness-live-evidence/v1"
EVIDENCE_SCHEMA_V2 = "lakatotree-production-readiness-live-evidence/v2"
WRITE_RECEIPT_SCHEMA = "lakatotree-production-readiness-live-write-receipt/v1"
ERROR_SCHEMA = "lakatotree-production-readiness-live-error/v1"
MAX_REQUEST_BYTES = 64 * 1024
MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
MAX_RESPONSE_BYTES = 64 * 1024
MAX_HTTP_HEADER_BYTES = 16 * 1024
MAX_JSON_NESTING = 64
MAX_FACT_ITEMS = 256
MAX_RBAC_FACT_ITEMS = 8192
ADAPTER_NAMES = ("runtime", "postgresql", "neo4j", "predeploy", "temporal")
ADAPTER_STATUSES = frozenset({"OBSERVED", "PARTIAL", "NOT_CONFIGURED", "UNAVAILABLE"})
CLAIM_BOUNDARY = (
    "COLLECTION_COMPLETE means only that every configured read-only source returned a "
    "bounded observation. COLLECTION_INCOMPLETE means at least one required source was "
    "missing, partial, or unavailable. Collection status is never production approval. "
    "The collector does not attest that sequential observations form one coherent "
    "snapshot. Neither status evaluates readiness, runs the "
    "locked negative-control suite, authorizes a deployment, or establishes runtime L3."
)

_TARGET_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_ROLE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]{0,62}\Z")
_NEO_DATABASE_NAME = re.compile(
    r"(?=.{3,63}\Z)[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\Z"
)
_FAILURE_CODE = re.compile(r"[a-z][a-z0-9_.-]{0,127}\Z")
_HEX = frozenset("0123456789abcdef")
_SECRET_MARKERS = ("password", "secret", "credential", "token", "private_key", "dsn", "uri", "url")
POSTGRESQL_DSN_ENV = "LAKATOTREE_READINESS_PG_DSN"
NEO4J_URI_ENV = "LAKATOTREE_READINESS_NEO4J_URI"
NEO4J_USER_ENV = "LAKATOTREE_READINESS_NEO4J_USER"
NEO4J_PASSWORD_ENV = "LAKATOTREE_READINESS_NEO4J_PASSWORD"
_ADAPTER_ENV_KEYS = {
    "runtime": (),
    "postgresql": (POSTGRESQL_DSN_ENV,),
    "neo4j": (NEO4J_URI_ENV, NEO4J_USER_ENV, NEO4J_PASSWORD_ENV),
    "predeploy": (),
    "temporal": (),
}
_RUNTIME_STATES = frozenset({"ok", "healthy", "degraded", "unhealthy", "ready", "not_ready"})
_SERVICE_STATES = frozenset({
    "ok", "down", "degraded", "unknown", "lost", "disabled", "unverified",
})
_SERVICE_NAMES = frozenset({
    "pg", "neo4j", "mongo", "writer_lease", "critique_history",
    "runtime_authority",
})
_AUTH_POSTURES = frozenset({
    "token_required", "loopback_only", "disabled", "open",
    "irreversible_attested",
})
_FRESHNESS_STATES = frozenset({"on", "off", "opt_out"})
_PREDEPLOY_SCHEMA = "lakatotree-storage-predeploy-receipt/v5"
_TEMPORAL_SCHEMAS = {
    "authority_policy": "lakatotree-temporal-authority-policy/v1",
    "sidecar": "lakatotree-two-ended-temporal-sidecar/v1",
    "runtime_binding": "lakatotree-temporal-runtime-binding/v1",
}
_TEMPORAL_SIDECAR_DOMAIN = b"lakatotree-two-ended-temporal-sidecar/v1\0"
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
_PG16_17_LARGE_OBJECT_ROUTINES = (
    "pg_catalog.lo_close(pg_catalog.int4)",
    "pg_catalog.lo_creat(pg_catalog.int4)",
    "pg_catalog.lo_create(pg_catalog.oid)",
    "pg_catalog.lo_export(pg_catalog.oid,pg_catalog.text)",
    "pg_catalog.lo_from_bytea(pg_catalog.oid,pg_catalog.bytea)",
    "pg_catalog.lo_get(pg_catalog.oid)",
    "pg_catalog.lo_get(pg_catalog.oid,pg_catalog.int8,pg_catalog.int4)",
    "pg_catalog.lo_import(pg_catalog.text)",
    "pg_catalog.lo_import(pg_catalog.text,pg_catalog.oid)",
    "pg_catalog.lo_lseek(pg_catalog.int4,pg_catalog.int4,pg_catalog.int4)",
    "pg_catalog.lo_lseek64(pg_catalog.int4,pg_catalog.int8,pg_catalog.int4)",
    "pg_catalog.lo_open(pg_catalog.oid,pg_catalog.int4)",
    "pg_catalog.lo_put(pg_catalog.oid,pg_catalog.int8,pg_catalog.bytea)",
    "pg_catalog.lo_tell(pg_catalog.int4)",
    "pg_catalog.lo_tell64(pg_catalog.int4)",
    "pg_catalog.lo_truncate(pg_catalog.int4,pg_catalog.int4)",
    "pg_catalog.lo_truncate64(pg_catalog.int4,pg_catalog.int8)",
    "pg_catalog.lo_unlink(pg_catalog.oid)",
    "pg_catalog.loread(pg_catalog.int4,pg_catalog.int4)",
    "pg_catalog.lowrite(pg_catalog.int4,pg_catalog.bytea)",
)
# PostgreSQL 16/17 initdb grant PUBLIC SELECT on this exact information_schema
# inventory but does not record those grants in pg_init_privs.  The identity
# allowlist prevents a newly granted low-OID system object from masquerading as
# that baseline.  Object OID, bootstrap owner, relkind and exact ACL are checked
# again in the collector query.
_PG16_17_INFORMATION_SCHEMA_PUBLIC_SELECT = frozenset({
    "administrable_role_authorizations", "applicable_roles", "attributes",
    "character_sets", "check_constraint_routine_usage", "check_constraints",
    "collation_character_set_applicability", "collations",
    "column_column_usage", "column_domain_usage", "column_options",
    "column_privileges", "column_udt_usage", "columns",
    "constraint_column_usage", "constraint_table_usage",
    "data_type_privileges", "domain_constraints", "domain_udt_usage",
    "domains", "element_types", "enabled_roles",
    "foreign_data_wrapper_options", "foreign_data_wrappers",
    "foreign_server_options", "foreign_servers", "foreign_table_options",
    "foreign_tables", "information_schema_catalog_name", "key_column_usage",
    "parameters", "referential_constraints", "role_column_grants",
    "role_routine_grants", "role_table_grants", "role_udt_grants",
    "role_usage_grants", "routine_column_usage", "routine_privileges",
    "routine_routine_usage", "routine_sequence_usage", "routine_table_usage",
    "routines", "schemata", "sequences", "sql_features",
    "sql_implementation_info", "sql_sizing", "table_constraints",
    "table_privileges", "tables", "triggered_update_columns", "triggers",
    "udt_privileges", "usage_privileges", "user_defined_types",
    "user_mapping_options", "user_mappings", "view_column_usage",
    "view_routine_usage", "view_table_usage", "views",
})
_PG16_17_INFORMATION_SCHEMA_PUBLIC_SELECT_RELATIONS = frozenset({
    "sql_features", "sql_implementation_info", "sql_sizing",
})
_PG16_17_INFORMATION_SCHEMA_PUBLIC_SELECT_VIEWS = tuple(sorted(
    _PG16_17_INFORMATION_SCHEMA_PUBLIC_SELECT
    - _PG16_17_INFORMATION_SCHEMA_PUBLIC_SELECT_RELATIONS
))
_PG16_17_INFORMATION_SCHEMA_PUBLIC_SELECT_RELATIONS = tuple(sorted(
    _PG16_17_INFORMATION_SCHEMA_PUBLIC_SELECT_RELATIONS
))
_NEO_AUTH_SETTING_NAMES = (
    "dbms.security.auth_enabled",
    "dbms.security.authentication_providers",
    "dbms.security.authorization_providers",
    "dbms.security.abac.authorization_providers",
)
_NEO_BASE_AUTH_SETTING_NAMES = _NEO_AUTH_SETTING_NAMES[:3]


class CollectionInputError(ValueError):
    """The collection request or output target is unsafe or ambiguous."""


class _PortUnavailable(RuntimeError):
    """Internal sentinel whose message is never serialized."""


class PublicationInDoubt(RuntimeError):
    """The final path may exist, but durable exact publication was not confirmed."""


@dataclass(frozen=True)
class LoadedRequest:
    raw: bytes
    file_sha256: str
    value: Mapping[str, Any]


@dataclass(frozen=True)
class AdapterResult:
    status: str
    facts: Mapping[str, Any]
    failure_codes: tuple[str, ...] = ()
    binding_material: Mapping[str, Any] | None = None


Port = Callable[[Mapping[str, Any], float, Mapping[str, str]], AdapterResult]


@dataclass(frozen=True)
class CollectorPorts:
    runtime: Port
    postgresql: Port
    neo4j: Port
    predeploy: Port
    temporal: Port


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
        raise CollectionInputError("value must be finite canonical JSON") from exc


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _exact_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in _HEX for char in value)


def _strict_json_loads(raw: bytes) -> Any:
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
                raise CollectionInputError("JSON exceeds bounded nesting")
        elif byte in (0x5D, 0x7D) and depth:
            depth -= 1

    def object_pairs(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise CollectionInputError("duplicate JSON object key")
            result[key] = item
        return result

    def reject_constant(token: str):
        raise CollectionInputError(f"non-finite JSON number is forbidden: {token}")

    try:
        return json.loads(raw, object_pairs_hook=object_pairs, parse_constant=reject_constant)
    except CollectionInputError:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise CollectionInputError("file is not valid UTF-8 JSON") from exc


def _exact_mapping(value: Any, *, path: str, keys: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise CollectionInputError(f"{path} has a non-exact field set")
    return value


def _text(value: Any, *, path: str, maximum: int = 256) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum or "\x00" in value:
        raise CollectionInputError(f"{path} must be a bounded non-empty string")
    return value


def _sha(value: Any, *, path: str) -> str:
    if not _exact_sha256(value):
        raise CollectionInputError(f"{path} must be a lowercase SHA-256")
    return value


def _role_name(value: Any, *, path: str) -> str:
    value = _text(value, path=path, maximum=63)
    if not _ROLE_NAME.fullmatch(value):
        raise CollectionInputError(f"{path} must be a bounded database role name")
    return value


def _validate_runtime_url(value: Any) -> str:
    value = _text(value, path="request.adapters.runtime.base_url", maximum=512)
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise CollectionInputError(
            "request.adapters.runtime.base_url must be a credential-free loopback HTTP origin"
        )
    try:
        port = parsed.port
    except ValueError as exc:
        raise CollectionInputError("request.adapters.runtime.base_url has an invalid port") from exc
    if port is None or not (1 <= port <= 65535):
        raise CollectionInputError("request.adapters.runtime.base_url must include a valid port")
    return value.rstrip("/")


def _validate_file_config(value: Any, *, path: str) -> Mapping[str, Any]:
    config = _exact_mapping(value, path=path, keys={"path", "file_sha256"})
    _text(config["path"], path=f"{path}.path", maximum=4096)
    _sha(config["file_sha256"], path=f"{path}.file_sha256")
    return config


def _open_verified_directory(path: Path, expected: os.stat_result, *, error: str) -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = -1
    try:
        fd = os.open(path, flags)
        observed = os.fstat(fd)
    except OSError as exc:
        if fd >= 0:
            os.close(fd)
        raise CollectionInputError(error) from exc
    if (
        not stat.S_ISDIR(observed.st_mode)
        or observed.st_dev != expected.st_dev
        or observed.st_ino != expected.st_ino
    ):
        os.close(fd)
        raise CollectionInputError(error)
    return fd


def validate_request(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CollectionInputError("request must be an object")
    schema = value.get("schema_version")
    if schema not in {REQUEST_SCHEMA, REQUEST_SCHEMA_V2, REQUEST_SCHEMA_V3}:
        raise CollectionInputError("request.schema_version is unsupported")
    request_v2 = schema in {REQUEST_SCHEMA_V2, REQUEST_SCHEMA_V3}
    request_v3 = schema == REQUEST_SCHEMA_V3
    request = _exact_mapping(
        value,
        path="request",
        keys={
            "schema_version", "target_id", "timeout_seconds", "adapters",
            *({"challenge_nonce"} if request_v2 else set()),
        },
    )
    if request_v2:
        _sha(request["challenge_nonce"], path="request.challenge_nonce")
    target_id = _text(request["target_id"], path="request.target_id", maximum=128)
    if not _TARGET_ID.fullmatch(target_id):
        raise CollectionInputError("request.target_id has an invalid format")
    timeout = request["timeout_seconds"]
    if type(timeout) is not int or not (1 <= timeout <= 10):
        raise CollectionInputError("request.timeout_seconds must be an integer from 1 to 10")
    adapters = _exact_mapping(
        request["adapters"], path="request.adapters", keys=set(ADAPTER_NAMES)
    )

    runtime = adapters["runtime"]
    if runtime is not None:
        runtime = _exact_mapping(
            runtime,
            path="request.adapters.runtime",
            keys=(
                {
                    "base_url",
                    "expected_artifact",
                    "runtime_authority_public_key_hex",
                }
                if request_v3
                else {"base_url", "expected_git_sha"}
            ),
        )
        _validate_runtime_url(runtime["base_url"])
        if request_v3:
            _sha(
                runtime["runtime_authority_public_key_hex"],
                path="request.adapters.runtime.runtime_authority_public_key_hex",
            )
            try:
                artifact_identity_sha256(runtime["expected_artifact"])
            except RuntimeAuthorityError as exc:
                raise CollectionInputError(
                    "request.adapters.runtime.expected_artifact is invalid"
                ) from exc
        else:
            git_sha = _text(
                runtime["expected_git_sha"],
                path="request.adapters.runtime.expected_git_sha",
                maximum=64,
            )
            if not (7 <= len(git_sha) <= 64 and all(char in _HEX for char in git_sha)):
                raise CollectionInputError(
                    "request.adapters.runtime.expected_git_sha must be lowercase hexadecimal"
                )
            if request_v2 and len(git_sha) != 40:
                raise CollectionInputError(
                    "request v2 runtime expected_git_sha must be a full Git SHA"
                )

    postgresql = adapters["postgresql"]
    if postgresql is not None:
        postgresql = _exact_mapping(
            postgresql,
            path="request.adapters.postgresql",
            keys={
                "database", "owner_role", "migrator_role", "runtime_role",
                *({"audit_role", "host", "port"} if request_v2 else set()),
            },
        )
        _text(postgresql["database"], path="request.adapters.postgresql.database", maximum=63)
        if request_v2:
            host = _text(
                postgresql["host"],
                path="request.adapters.postgresql.host",
                maximum=64,
            )
            try:
                address = ipaddress.ip_address(host)
            except ValueError as exc:
                raise CollectionInputError(
                    "request.adapters.postgresql.host must be a literal loopback IP"
                ) from exc
            if not address.is_loopback:
                raise CollectionInputError(
                    "request.adapters.postgresql.host must be a literal loopback IP"
                )
            if (
                type(postgresql["port"]) is not int
                or not 1 <= postgresql["port"] <= 65535
            ):
                raise CollectionInputError(
                    "request.adapters.postgresql.port must be a TCP port"
                )
        role_fields = ["owner_role", "migrator_role", "runtime_role"]
        if request_v2:
            role_fields.append("audit_role")
        for field in role_fields:
            _role_name(postgresql[field], path=f"request.adapters.postgresql.{field}")
        if len({postgresql[field] for field in role_fields}) != len(role_fields):
            raise CollectionInputError(
                "request.adapters.postgresql roles must be pairwise distinct"
            )

    neo4j = adapters["neo4j"]
    if neo4j is not None:
        neo4j = _exact_mapping(
            neo4j,
            path="request.adapters.neo4j",
            keys={
                "database",
                *(
                    {"audit_user", "audit_role", "migrator_role", "runtime_role"}
                    | {"migrator_user", "runtime_user"}
                    if request_v2 else set()
                ),
            },
        )
        neo4j_database = _text(
            neo4j["database"],
            path="request.adapters.neo4j.database",
            maximum=63,
        )
        if (
            _NEO_DATABASE_NAME.fullmatch(neo4j_database) is None
            or neo4j_database.startswith("system")
        ):
            raise CollectionInputError(
                "request.adapters.neo4j.database must be one concrete canonical application database"
            )
        if request_v2:
            for field in (
                "audit_user", "audit_role", "migrator_user", "migrator_role",
                "runtime_user", "runtime_role",
            ):
                _role_name(neo4j[field], path=f"request.adapters.neo4j.{field}")
            if len({neo4j[field] for field in (
                "audit_user", "migrator_user", "runtime_user"
            )}) != 3:
                raise CollectionInputError(
                    "request.adapters.neo4j users must be pairwise distinct"
                )
            if len({neo4j[field] for field in ("audit_role", "migrator_role", "runtime_role")}) != 3:
                raise CollectionInputError(
                    "request.adapters.neo4j custom roles must be pairwise distinct"
                )
            if any(
                str(neo4j[field]).lower() in {"admin", "architect", "editor", "publisher", "reader", "public"}
                for field in ("audit_role", "migrator_role", "runtime_role")
            ):
                raise CollectionInputError(
                    "request.adapters.neo4j roles must be custom roles"
                )

    if adapters["predeploy"] is not None:
        _validate_file_config(adapters["predeploy"], path="request.adapters.predeploy")

    temporal = adapters["temporal"]
    if temporal is not None:
        temporal = _exact_mapping(
            temporal,
            path="request.adapters.temporal",
            keys={"authority_policy", "sidecar", "runtime_binding"},
        )
        for field in ("authority_policy", "sidecar", "runtime_binding"):
            _validate_file_config(
                temporal[field], path=f"request.adapters.temporal.{field}"
            )
    return request


def _load_pinned_json(path: Path, expected_sha256: str, *, max_bytes: int) -> tuple[bytes, Any, os.stat_result]:
    if not path.is_absolute():
        raise CollectionInputError("pinned JSON path must be absolute")
    try:
        resolved = path.resolve(strict=True)
        parent = path.parent
        resolved_parent = parent.resolve(strict=True)
        parent_info = parent.lstat()
    except OSError as exc:
        raise CollectionInputError("pinned JSON file is unavailable") from exc
    if (
        resolved != path
        or resolved_parent != parent
        or stat.S_ISLNK(parent_info.st_mode)
        or not stat.S_ISDIR(parent_info.st_mode)
    ):
        raise CollectionInputError("pinned JSON must be a non-symlink regular file")
    parent_fd = _open_verified_directory(
        parent, parent_info, error="pinned JSON parent changed during open"
    )
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path.name, flags, dir_fd=parent_fd)
    except OSError as exc:
        os.close(parent_fd)
        raise CollectionInputError("pinned JSON file is unavailable") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise CollectionInputError("pinned JSON must be a non-symlink regular file")
        if info.st_size > max_bytes:
            raise CollectionInputError("pinned JSON exceeds bounded size")
        stream = os.fdopen(fd, "rb", closefd=True)
        fd = -1
        with stream:
            raw = stream.read(max_bytes + 1)
    finally:
        if fd >= 0:
            os.close(fd)
        os.close(parent_fd)
    if len(raw) > max_bytes:
        raise CollectionInputError("pinned JSON exceeds bounded size")
    if not _exact_sha256(expected_sha256):
        raise CollectionInputError("pinned JSON digest must be a lowercase SHA-256")
    if not hmac.compare_digest(_sha256(raw), expected_sha256):
        raise CollectionInputError("pinned JSON SHA-256 mismatch")
    return raw, _strict_json_loads(raw), info


def load_request(path: Path, expected_file_sha256: str) -> LoadedRequest:
    raw, value, _info = _load_pinned_json(
        path, expected_file_sha256, max_bytes=MAX_REQUEST_BYTES
    )
    if not isinstance(value, Mapping):
        raise CollectionInputError("request root must be an object")
    return LoadedRequest(
        raw=raw,
        file_sha256=expected_file_sha256,
        value=validate_request(value),
    )


def _runtime_fetch(
    url: str,
    *,
    timeout: float,
) -> tuple[int, bytes, Mapping[str, Any]]:
    parsed = urlsplit(url)
    host = parsed.hostname
    port = parsed.port
    if host is None or port is None:
        raise _PortUnavailable("runtime endpoint is invalid")
    ip = ipaddress.ip_address(host)
    family = socket.AF_INET6 if ip.version == 6 else socket.AF_INET
    address = (host, port, 0, 0) if family == socket.AF_INET6 else (host, port)
    host_header = f"[{host}]:{port}" if family == socket.AF_INET6 else f"{host}:{port}"
    target = parsed.path or "/"
    request = (
        f"GET {target} HTTP/1.1\r\n"
        f"Host: {host_header}\r\n"
        "Accept: application/json\r\n"
        "User-Agent: lakatotree-readiness-collect/1\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii")
    deadline = time.monotonic() + timeout
    wire = bytearray()
    header_end = None
    content_length = None

    def remaining() -> float:
        value = deadline - time.monotonic()
        if value <= 0:
            raise _PortUnavailable("runtime endpoint absolute deadline exhausted")
        return value

    try:
        with socket.socket(family, socket.SOCK_STREAM) as stream:
            stream.settimeout(remaining())
            stream.connect(address)
            stream.settimeout(remaining())
            stream.sendall(request)
            while True:
                stream.settimeout(remaining())
                chunk = stream.recv(65536)
                if not chunk:
                    if header_end is None or content_length is None:
                        raise _PortUnavailable("runtime response ended before bounded framing")
                    if len(wire) - header_end != content_length:
                        raise _PortUnavailable("runtime response body is truncated")
                    break
                wire.extend(chunk)
                if header_end is None:
                    marker = wire.find(b"\r\n\r\n")
                    if marker < 0:
                        if len(wire) > MAX_HTTP_HEADER_BYTES:
                            raise _PortUnavailable("runtime response headers exceed limit")
                        continue
                    header_end = marker + 4
                    if header_end > MAX_HTTP_HEADER_BYTES:
                        raise _PortUnavailable("runtime response headers exceed limit")
                    try:
                        lines = bytes(wire[:marker]).decode("iso-8859-1").split("\r\n")
                    except UnicodeDecodeError as exc:
                        raise _PortUnavailable("runtime response headers are invalid") from exc
                    status_parts = lines[0].split(" ", 2)
                    if (
                        len(status_parts) < 2
                        or status_parts[0] not in {"HTTP/1.0", "HTTP/1.1"}
                        or len(status_parts[1]) != 3
                        or not status_parts[1].isdigit()
                    ):
                        raise _PortUnavailable("runtime response status line is invalid")
                    status_code = int(status_parts[1])
                    headers: dict[str, list[str]] = {}
                    for line in lines[1:]:
                        if not line or line[0] in " \t" or ":" not in line:
                            raise _PortUnavailable("runtime response header is ambiguous")
                        name, value = line.split(":", 1)
                        if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name):
                            raise _PortUnavailable("runtime response header name is invalid")
                        headers.setdefault(name.lower(), []).append(value.strip())
                    if "transfer-encoding" in headers:
                        raise _PortUnavailable("runtime chunked response is unsupported")
                    lengths = headers.get("content-length", [])
                    if len(lengths) != 1 or not lengths[0].isdigit():
                        raise _PortUnavailable("runtime response requires exact content length")
                    content_length = int(lengths[0])
                    if content_length > MAX_RESPONSE_BYTES:
                        raise _PortUnavailable("runtime response exceeds limit")
                if header_end is not None and content_length is not None:
                    observed_length = len(wire) - header_end
                    if observed_length == content_length:
                        break
                    if observed_length > content_length:
                        raise _PortUnavailable("runtime response has trailing bytes")
    except _PortUnavailable:
        raise
    except (OSError, TimeoutError, ValueError) as exc:
        raise _PortUnavailable("runtime endpoint unavailable") from exc
    remaining()
    if header_end is None or content_length is None:
        raise _PortUnavailable("runtime response framing is unavailable")
    raw = bytes(wire[header_end:])
    try:
        value = _strict_json_loads(raw)
    except CollectionInputError as exc:
        raise _PortUnavailable("runtime response is invalid JSON") from exc
    if not isinstance(value, Mapping):
        raise _PortUnavailable("runtime response root is not an object")
    return status_code, raw, value


def _optional_text(value: Any, maximum: int = 128) -> str | None:
    return value if isinstance(value, str) and len(value) <= maximum and "\x00" not in value else None


def _optional_enum(value: Any, allowed: frozenset[str]) -> str | None:
    return value if isinstance(value, str) and value in allowed else None


def _optional_bool(value: Any) -> bool | None:
    return value if type(value) is bool else None


def _optional_timestamp(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat()


def _services(value: Any) -> dict[str, str] | None:
    if not isinstance(value, Mapping) or len(value) > 16:
        return None
    result: dict[str, str] = {}
    for key, item in value.items():
        if (
            not isinstance(key, str)
            or key not in _SERVICE_NAMES
            or not isinstance(item, str)
            or item not in _SERVICE_STATES
        ):
            return None
        result[key] = item
    return dict(sorted(result.items()))


def _git_sha_match(observed: Any, expected: str) -> bool:
    """Match a full identity, while preserving the legacy v1 short-SHA wire."""

    if not (
        isinstance(observed, str)
        and isinstance(expected, str)
        and 7 <= len(observed) <= 40
        and 7 <= len(expected) <= 40
        and all(char in _HEX for char in observed)
        and all(char in _HEX for char in expected)
    ):
        return False
    return observed == expected or (
        len(expected) < 40
        and len(observed) == 40
        and observed.startswith(expected)
    )


def _optional_git_sha(value: Any) -> str | None:
    return (
        value
        if isinstance(value, str)
        and 7 <= len(value) <= 64
        and all(char in _HEX for char in value)
        else None
    )


def collect_runtime(config: Mapping[str, Any], timeout: float, environ: Mapping[str, str]) -> AdapterResult:
    del environ
    base_url = _validate_runtime_url(config["base_url"])
    runtime_v3 = "expected_artifact" in config
    expected_git_sha = (
        None if runtime_v3 else str(config["expected_git_sha"])
    )
    observations: dict[str, tuple[int, bytes, Mapping[str, Any]]] = {}
    failures: list[str] = []
    deadline = time.monotonic() + timeout
    for name, path in (
        ("healthz", "/healthz"),
        ("readyz", "/readyz"),
        ("version", "/version"),
        ("outbox", "/api/ops/outbox-status"),
        *(
            (("runtime_authority", "/api/ops/runtime-authority-snapshot"),)
            if runtime_v3
            else ()
        ),
    ):
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _PortUnavailable("runtime collection deadline exhausted")
            observations[name] = _runtime_fetch(
                base_url + path, timeout=remaining
            )
        except _PortUnavailable:
            failures.append(f"runtime.{name}.unavailable")

    facts: dict[str, Any] = {"endpoint_sha256": _sha256(base_url.encode("utf-8"))}
    for name in ("healthz", "readyz"):
        observed = observations.get(name)
        if observed is None:
            facts[name] = None
            continue
        status_code, raw, body = observed
        facts[name] = {
            "http_status": status_code,
            "body_sha256": _sha256(raw),
            "state": _optional_enum(body.get("status"), _RUNTIME_STATES),
            "services": _services(body.get("services")),
        }
    observed_version = observations.get("version")
    if observed_version is None:
        facts["version"] = None
    else:
        status_code, raw, body = observed_version
        boot_git_sha = _optional_git_sha(body.get("boot_git_sha"))
        disk_head_sha = _optional_git_sha(body.get("disk_head_sha"))
        facts["version"] = {
            "http_status": status_code,
            "body_sha256": _sha256(raw),
            "boot_git_sha": boot_git_sha,
            "disk_head_sha": disk_head_sha,
            "boot_matches_expected": (
                None
                if expected_git_sha is None
                else _git_sha_match(boot_git_sha, expected_git_sha)
            ),
            "disk_matches_expected": (
                None
                if expected_git_sha is None
                else _git_sha_match(disk_head_sha, expected_git_sha)
            ),
            "stale": _optional_bool(body.get("stale")),
            "identity_verified": _optional_bool(body.get("identity_verified")),
            "auth_posture": _optional_enum(body.get("auth_posture"), _AUTH_POSTURES),
            "freshness_gate": _optional_enum(body.get("freshness_gate"), _FRESHNESS_STATES),
        }
    observed_outbox = observations.get("outbox")
    if observed_outbox is None:
        facts["outbox"] = None
    else:
        status_code, raw, body = observed_outbox
        pending = body.get("pending")
        facts["outbox"] = {
            "http_status": status_code,
            "body_sha256": _sha256(raw),
            "pending": pending if type(pending) is int and pending >= 0 else None,
        }
    binding_material = None
    if runtime_v3:
        observed_authority = observations.get("runtime_authority")
        if observed_authority is None:
            facts["runtime_authority"] = None
        else:
            status_code, raw, _body = observed_authority
            try:
                if status_code != 200:
                    raise RuntimeAuthorityError(
                        "runtime authority endpoint did not return a proof"
                    )
                proof = verify_published_runtime_snapshot(
                    raw,
                    public_key_hex=str(config["runtime_authority_public_key_hex"]),
                    expected_artifact=config["expected_artifact"],
                    evaluated_at=datetime.now(timezone.utc),
                )
                report = proof.public_report()
                facts["runtime_authority"] = {
                    "http_status": status_code,
                    "status": "VERIFIED_SIGNED_SNAPSHOT",
                    "body_sha256": report["body_sha256"],
                    "challenge_sha256": report["challenge_sha256"],
                    "artifact_kind": report["artifact_kind"],
                    "artifact_identity_sha256": report[
                        "artifact_identity_sha256"
                    ],
                    "operation_sha256": report["operation_sha256"],
                    "target_sha256": report["target_sha256"],
                    "predeploy_receipt_file_sha256": report[
                        "predeploy_receipt_file_sha256"
                    ],
                    "startup_bundle_file_sha256": report[
                        "startup_bundle_file_sha256"
                    ],
                    "runtime_lease_id_sha256": report[
                        "runtime_lease_id_sha256"
                    ],
                    "runtime_lease_generation": report[
                        "runtime_lease_generation"
                    ],
                    "worker_count": report["worker_count"],
                    "boot_id_sha256": report["boot_id_sha256"],
                    "observed_at": report["observed_at"],
                    "expires_at": report["expires_at"],
                    "effect_scope": RUNTIME_EFFECT_SCOPE,
                }
                binding_material = {
                    "artifact_identity_sha256": proof.artifact_identity_sha256,
                    "operation_sha256": proof.operation_sha256,
                    "target_sha256": proof.target_sha256,
                    "predeploy_receipt_file_sha256": (
                        proof.predeploy_receipt_file_sha256
                    ),
                }
            except RuntimeAuthorityError:
                failures.append("runtime.authority.invalid")
                facts["runtime_authority"] = {
                    "http_status": status_code,
                    "status": "INVALID",
                }
    return AdapterResult(
        "OBSERVED" if not failures else "PARTIAL",
        facts,
        tuple(sorted(failures)),
        binding_material,
    )


def _role_attributes(row: Sequence[Any]) -> dict[str, bool]:
    return {
        "login": bool(row[1]),
        "superuser": bool(row[2]),
        "createdb": bool(row[3]),
        "createrole": bool(row[4]),
        "inherit": bool(row[5]),
        "bypassrls": bool(row[6]),
        "replication": bool(row[7]),
    }


def _cancel_noexcept(connection: Any) -> None:
    """Cancel a timed-out PG call without leaking a driver exception from a timer thread."""

    try:
        connection.cancel()
    except Exception:
        pass


def _bounded_cursor_rows(cursor: Any, *, maximum: int = 512) -> list[Sequence[Any]]:
    rows = cursor.fetchmany(maximum + 1)
    if len(rows) > maximum:
        raise _PortUnavailable("PostgreSQL catalog projection exceeds bounded rows")
    return rows


def _validated_pg_endpoint(
    psycopg2: Any,
    dsn: str,
    database: str,
    *,
    expected_host: str | None = None,
    expected_port: int | None = None,
) -> tuple[str, int, dict[str, str]]:
    """Return explicit TLS conninfo with no libpq ambient-authority fallback."""

    try:
        parsed = psycopg2.extensions.parse_dsn(dsn)
    except Exception as exc:
        raise _PortUnavailable("PostgreSQL DSN is invalid") from exc
    required = {
        "host",
        "hostaddr",
        "port",
        "dbname",
        "user",
        "password",
        "sslmode",
        "sslrootcert",
    }
    if set(parsed) != required:
        raise _PortUnavailable("PostgreSQL DSN must use the exact explicit TLS field set")
    host = parsed.get("host")
    hostaddr = parsed.get("hostaddr")
    port_text = parsed.get("port")
    if not isinstance(host, str) or not host or "," in host:
        raise _PortUnavailable("PostgreSQL requires one pinned endpoint")
    if not isinstance(hostaddr, str) or not hostaddr or "," in hostaddr:
        raise _PortUnavailable("PostgreSQL requires one pinned hostaddr")
    try:
        hostaddr_ip = ipaddress.ip_address(hostaddr)
    except ValueError as exc:
        raise _PortUnavailable("PostgreSQL hostaddr must be a literal IP") from exc
    if not isinstance(port_text, str) or not port_text or "," in port_text:
        raise _PortUnavailable("PostgreSQL requires one pinned port")
    try:
        port = int(port_text)
    except ValueError as exc:
        raise _PortUnavailable("PostgreSQL port is invalid") from exc
    if not (1 <= port <= 65535):
        raise _PortUnavailable("PostgreSQL port is invalid")
    if expected_host is not None:
        try:
            expected_ip = ipaddress.ip_address(expected_host)
            certificate_host_ip = ipaddress.ip_address(host)
        except ValueError as exc:
            raise _PortUnavailable(
                "PostgreSQL v2 target must use one literal IP"
            ) from exc
        if not (
            expected_ip.is_loopback
            and certificate_host_ip == expected_ip
            and hostaddr_ip == expected_ip
            and type(expected_port) is int
            and port == expected_port
        ):
            raise _PortUnavailable(
                "PostgreSQL DSN endpoint differs from the v2 pinned target"
            )
    if parsed.get("dbname") != database:
        raise _PortUnavailable("PostgreSQL DSN database is not request-pinned")
    if not parsed.get("user") or not parsed.get("password"):
        raise _PortUnavailable("PostgreSQL DSN must pin one audit principal")
    if parsed.get("sslmode") != "verify-full" or parsed.get("sslrootcert") != "system":
        raise _PortUnavailable("PostgreSQL requires system-root verify-full TLS")
    parameters = dict(parsed)
    parameters.update(
        {
            "application_name": "lakatotree-readiness-collect",
            "options": (
                "-c search_path=pg_catalog "
                "-c default_transaction_read_only=on"
            ),
            "channel_binding": "require",
            "target_session_attrs": "read-only",
            "gssencmode": "disable",
            "load_balance_hosts": "disable",
            "require_auth": "scram-sha-256",
            "sslcertmode": "disable",
            "sslnegotiation": "postgres",
            "ssl_min_protocol_version": "TLSv1.2",
            "ssl_max_protocol_version": "TLSv1.3",
            "sslcert": "",
            "sslkey": "",
            "sslpassword": "",
        }
    )
    return host, port, parameters


def _acl_principal(value: Any, roles: Mapping[str, str]) -> str:
    if value == "PUBLIC":
        return "public"
    for label, role in roles.items():
        if value == role:
            return label
    return "sha256:" + _sha256(str(value).encode("utf-8"))


def _collect_postgresql_impl(
    config: Mapping[str, Any],
    timeout: float,
    environ: Mapping[str, str],
    *,
    injected_connection: Any | None = None,
    injected_endpoint: tuple[str, int] | None = None,
) -> AdapterResult:
    if timeout < 2:
        return AdapterResult("UNAVAILABLE", {}, ("postgresql.deadline_exhausted",))
    owns_connection = injected_connection is None
    connection = injected_connection
    connection_parameters = None
    if owns_connection:
        dsn = environ.get(POSTGRESQL_DSN_ENV)
        if not dsn:
            return AdapterResult("UNAVAILABLE", {}, ("postgresql.auth_material_unavailable",))
        if any(key.startswith("PG") for key in os.environ):
            return AdapterResult("UNAVAILABLE", {}, ("postgresql.ambient_authority_present",))
        try:
            import psycopg2
        except ModuleNotFoundError:
            return AdapterResult("UNAVAILABLE", {}, ("postgresql.dependency_unavailable",))
        configured_host, configured_port, connection_parameters = _validated_pg_endpoint(
            psycopg2,
            dsn,
            str(config["database"]),
            expected_host=(str(config["host"]) if "host" in config else None),
            expected_port=(config.get("port") if "host" in config else None),
        )
    else:
        if (
            injected_endpoint is None
            or not isinstance(injected_endpoint[0], str)
            or type(injected_endpoint[1]) is not int
        ):
            raise _PortUnavailable("injected PostgreSQL test endpoint is invalid")
        configured_host, configured_port = injected_endpoint
    roles = {
        "owner": str(config["owner_role"]),
        "migrator": str(config["migrator_role"]),
        "runtime": str(config["runtime_role"]),
    }
    if "audit_role" in config:
        roles["audit"] = str(config["audit_role"])
    cancel_timer = None
    failures: list[str] = []
    authority_boundary_deviations: list[list[str | int]] = []
    system_identifier = None
    challenge_nonce = config.get("challenge_nonce")
    challenge_bound = challenge_nonce is not None
    if challenge_bound and not _exact_sha256(challenge_nonce):
        raise _PortUnavailable("PostgreSQL audit challenge nonce is invalid")
    deadline = time.monotonic() + timeout
    try:
        if owns_connection:
            connection = psycopg2.connect(
                **connection_parameters,
                connect_timeout=max(2, min(10, int(timeout + 0.999))),
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _PortUnavailable("PostgreSQL collection deadline exhausted")
        cancel_timer = threading.Timer(remaining, _cancel_noexcept, (connection,))
        cancel_timer.daemon = True
        cancel_timer.start()
        connection.set_session(
            readonly=True,
            autocommit=False,
            isolation_level="REPEATABLE READ",
        )
        with connection.cursor() as cursor:
            if challenge_bound:
                cursor.execute("SELECT %s::text AS readiness_challenge", (challenge_nonce,))
                challenge_row = cursor.fetchone()
                if challenge_row != (challenge_nonce,):
                    raise _PortUnavailable("PostgreSQL audit challenge was not echoed")
            cursor.execute(
                "SELECT pg_catalog.set_config('statement_timeout', %s, true)",
                (f"{max(1, int(remaining * 1000))}ms",),
            )
            cursor.execute(
                "SELECT pg_catalog.current_database(), current_user, session_user, "
                "pg_catalog.current_setting('transaction_read_only'), "
                "pg_catalog.current_setting('search_path'), "
                "pg_catalog.current_setting('transaction_isolation')"
            )
            (
                database, current_user, session_user, transaction_read_only,
                observed_search_path, observed_isolation,
            ) = cursor.fetchone()
            if observed_search_path != "pg_catalog":
                raise _PortUnavailable(
                    "PostgreSQL audit search_path differs from pg_catalog"
                )
            if str(observed_isolation).lower() != "repeatable read":
                raise _PortUnavailable(
                    "PostgreSQL audit transaction is not REPEATABLE READ"
                )
            cursor.execute(
                "SELECT pg_catalog.host(pg_catalog.inet_server_addr()), "
                "pg_catalog.inet_server_port(), "
                "pg_catalog.current_setting('server_version_num')"
            )
            server_address, server_port, server_version_num = cursor.fetchone()
            try:
                server_version_int = int(server_version_num)
            except (TypeError, ValueError) as exc:
                raise _PortUnavailable(
                    "PostgreSQL server_version_num is invalid"
                ) from exc
            table_mutation_privileges = [
                "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER",
            ]
            if server_version_int >= 170000:
                table_mutation_privileges.append("MAINTAIN")
            if "host" in config:
                try:
                    observed_server_ip = ipaddress.ip_address(str(server_address))
                    expected_server_ip = ipaddress.ip_address(str(config["host"]))
                except ValueError as exc:
                    raise _PortUnavailable(
                        "PostgreSQL live server address is not a pinned IP"
                    ) from exc
                if not (
                    observed_server_ip == expected_server_ip
                    and type(server_port) is int
                    and server_port == config["port"]
                ):
                    raise _PortUnavailable(
                        "PostgreSQL live server endpoint differs from the pinned target"
                    )
            cursor.execute(
                "SELECT oid::text FROM pg_catalog.pg_database "
                "WHERE datname=pg_catalog.current_database()"
            )
            database_oid = cursor.fetchone()[0]
            cursor.execute("SAVEPOINT readiness_cluster_identity")
            try:
                cursor.execute(
                    "SELECT system_identifier::text "
                    "FROM pg_catalog.pg_control_system()"
                )
                system_identifier = cursor.fetchone()[0]
            except Exception:
                cursor.execute("ROLLBACK TO SAVEPOINT readiness_cluster_identity")
                failures.append("postgresql.cluster_identity.unavailable")
            finally:
                cursor.execute("RELEASE SAVEPOINT readiness_cluster_identity")
            cursor.execute(
                "SELECT rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, "
                "rolinherit, rolbypassrls, rolreplication FROM pg_catalog.pg_roles "
                "WHERE rolname = ANY(%s) ORDER BY rolname",
                (list(roles.values()),),
            )
            role_rows = {row[0]: row for row in cursor.fetchall()}
            cursor.execute(
                "SELECT n.nspname || '.' || c.relname, c.oid, c.relkind, "
                "pg_catalog.pg_get_userbyid(c.relowner) "
                "FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='public' AND c.relname = ANY(%s) ORDER BY 1",
                ([name.split(".", 1)[1] for name in (*_PG_TABLES, *_PG_SEQUENCES)],),
            )
            object_rows = {row[0]: row for row in cursor.fetchall()}
            cursor.execute(
                "SELECT nspname, pg_catalog.pg_get_userbyid(nspowner) "
                "FROM pg_catalog.pg_namespace WHERE nspname='public'"
            )
            schema_row = cursor.fetchone()
            membership_digests_by_label: dict[str, list[str]] = {}
            inbound_membership_digests_by_label: dict[str, list[str]] = {}
            membership_labels = tuple(roles) if "audit" in roles else ("runtime",)
            for membership_label in membership_labels:
                cursor.execute(
                    "WITH RECURSIVE membership(roleid, path) AS ("
                    " SELECT oid, ARRAY[oid] FROM pg_catalog.pg_roles WHERE rolname=%s"
                    " UNION ALL"
                    " SELECT m.roleid, membership.path || m.roleid"
                    " FROM pg_catalog.pg_auth_members m"
                    " JOIN membership ON membership.roleid=m.member"
                    " WHERE NOT m.roleid=ANY(membership.path)"
                    ") SELECT DISTINCT r.rolname FROM membership"
                    " JOIN pg_catalog.pg_roles r ON r.oid=membership.roleid ORDER BY r.rolname",
                    (roles[membership_label],),
                )
                membership_digests_by_label[membership_label] = [
                    _sha256(str(row[0]).encode("utf-8"))
                    for row in _bounded_cursor_rows(cursor, maximum=64)
                ]
            if "audit" in roles:
                for protected_label, protected_role in roles.items():
                    cursor.execute(
                        "WITH RECURSIVE protected AS ("
                        " SELECT oid FROM pg_catalog.pg_roles WHERE rolname=%s"
                        "), assignees(member_oid, path) AS ("
                        " SELECT m.member, ARRAY[m.roleid, m.member]"
                        " FROM pg_catalog.pg_auth_members m"
                        " WHERE m.roleid=(SELECT oid FROM protected)"
                        " UNION ALL"
                        " SELECT m.member, a.path || m.member"
                        " FROM pg_catalog.pg_auth_members m"
                        " JOIN assignees a ON m.roleid=a.member_oid"
                        " WHERE NOT m.member=ANY(a.path)"
                        ") SELECT DISTINCT r.rolname FROM assignees a"
                        " JOIN pg_catalog.pg_roles r ON r.oid=a.member_oid"
                        " ORDER BY r.rolname",
                        (protected_role,),
                    )
                    inbound_membership_digests_by_label[protected_label] = [
                        _sha256(str(row[0]).encode("utf-8"))
                        for row in _bounded_cursor_rows(cursor, maximum=64)
                    ]
            migrator_owner_membership = None
            if "audit" in roles:
                cursor.execute(
                    "SELECT m.admin_option, m.inherit_option, m.set_option "
                    "FROM pg_catalog.pg_auth_members m "
                    "JOIN pg_catalog.pg_roles parent ON parent.oid=m.roleid "
                    "JOIN pg_catalog.pg_roles member ON member.oid=m.member "
                    "WHERE parent.rolname=%s AND member.rolname=%s",
                    (roles["owner"], roles["migrator"]),
                )
                membership_rows = _bounded_cursor_rows(cursor, maximum=2)
                if len(membership_rows) == 1:
                    membership_row = membership_rows[0]
                    migrator_owner_membership = {
                        "admin_option": bool(membership_row[0]),
                        "inherit_option": bool(membership_row[1]),
                        "set_option": bool(membership_row[2]),
                    }
            relation_names = [
                name.split(".", 1)[1] for name in (*_PG_TABLES, *_PG_SEQUENCES)
            ]
            cursor.execute(
                "WITH acl_entries AS ("
                " SELECT 'database'::text AS scope, d.datname::text AS object_name,"
                " x.grantor, x.grantee, x.privilege_type, x.is_grantable"
                " FROM pg_catalog.pg_database d"
                " CROSS JOIN LATERAL pg_catalog.aclexplode("
                "   COALESCE(d.datacl, pg_catalog.acldefault('d'::\"char\", d.datdba))"
                " ) x WHERE d.datname=pg_catalog.current_database()"
                " UNION ALL"
                " SELECT 'schema', n.nspname, x.grantor, x.grantee,"
                " x.privilege_type, x.is_grantable"
                " FROM pg_catalog.pg_namespace n"
                " CROSS JOIN LATERAL pg_catalog.aclexplode("
                "   COALESCE(n.nspacl, pg_catalog.acldefault('n'::\"char\", n.nspowner))"
                " ) x WHERE n.nspname='public'"
                " UNION ALL"
                " SELECT CASE WHEN c.relkind='S' THEN 'sequence' ELSE 'relation' END,"
                " n.nspname || '.' || c.relname, x.grantor, x.grantee,"
                " x.privilege_type, x.is_grantable"
                " FROM pg_catalog.pg_class c"
                " JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace"
                " CROSS JOIN LATERAL pg_catalog.aclexplode(COALESCE("
                "   c.relacl, pg_catalog.acldefault("
                "     CASE WHEN c.relkind='S' THEN 's'::\"char\" ELSE 'r'::\"char\" END,"
                "     c.relowner))) x"
                " WHERE n.nspname='public' AND c.relname=ANY(%s)"
                " UNION ALL"
                " SELECT 'column', n.nspname || '.' || c.relname || '.' || a.attname,"
                " x.grantor, x.grantee, x.privilege_type, x.is_grantable"
                " FROM pg_catalog.pg_attribute a"
                " JOIN pg_catalog.pg_class c ON c.oid=a.attrelid"
                " JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace"
                " CROSS JOIN LATERAL pg_catalog.aclexplode(a.attacl) x"
                " WHERE n.nspname='public' AND c.relname=ANY(%s)"
                " AND a.attnum>0 AND NOT a.attisdropped"
                ") SELECT scope, object_name,"
                " pg_catalog.pg_get_userbyid(grantor),"
                " CASE WHEN grantee=0 THEN 'PUBLIC' ELSE pg_catalog.pg_get_userbyid(grantee) END,"
                " privilege_type, is_grantable FROM acl_entries"
                " ORDER BY scope, object_name, 3, 4, privilege_type, is_grantable",
                (relation_names, relation_names),
            )
            acl_rows = _bounded_cursor_rows(cursor)
            acl_projection = [
                {
                    "scope": str(row[0]),
                    "object_sha256": _sha256(str(row[1]).encode("utf-8")),
                    "grantor": _acl_principal(row[2], roles),
                    "grantee": _acl_principal(row[3], roles),
                    "privilege": str(row[4]),
                    "grantable": bool(row[5]),
                }
                for row in acl_rows
            ]
            grantable_acl_counts = {
                label: sum(
                    1 for entry in acl_projection
                    if entry["grantee"] == label and entry["grantable"] is True
                )
                for label in roles
            }
            public_acl_entry_counts = {
                scope: sum(
                    1
                    for entry in acl_projection
                    if entry["scope"] == scope and entry["grantee"] == "public"
                )
                for scope in ("database", "schema", "relation", "sequence", "column")
            }
            role_scope_privileges: dict[
                str, tuple[bool, bool, bool, int, str]
            ] = {}
            for privilege_label in (
                "runtime", *( ("audit",) if "audit" in roles else () )
            ):
                if roles[privilege_label] in role_rows:
                    cursor.execute(
                        "SELECT pg_catalog.has_database_privilege("
                        "%s, pg_catalog.current_database(), 'CREATE'), "
                        "pg_catalog.has_database_privilege("
                        "%s, pg_catalog.current_database(), 'TEMPORARY'), "
                        "pg_catalog.has_schema_privilege(%s, 'public', 'USAGE')",
                        (
                            roles[privilege_label],
                            roles[privilege_label],
                            roles[privilege_label],
                        ),
                    )
                    database_create_value, database_temp_value, public_usage_value = (
                        bool(value) for value in cursor.fetchone()
                    )
                    cursor.execute(
                        "SELECT nspname FROM pg_catalog.pg_namespace "
                        "WHERE nspname !~ '^pg_' AND nspname<>'information_schema' "
                        "AND pg_catalog.has_schema_privilege("
                        "%s, oid, 'CREATE') ORDER BY nspname",
                        (roles[privilege_label],),
                    )
                    create_schema_hashes = [
                        _sha256(str(row[0]).encode("utf-8"))
                        for row in _bounded_cursor_rows(cursor, maximum=128)
                    ]
                    role_scope_privileges[privilege_label] = (
                        database_create_value,
                        database_temp_value,
                        public_usage_value,
                        len(create_schema_hashes),
                        _sha256(_canonical(create_schema_hashes)),
                    )
                else:
                    role_scope_privileges[privilege_label] = (
                        False, False, False, 0, _sha256(_canonical([]))
                    )
            (
                database_create,
                database_temp,
                schema_usage,
                runtime_schema_create_count,
                runtime_schema_create_sha256,
            ) = role_scope_privileges["runtime"]
            schema_create = runtime_schema_create_count > 0

            objects: dict[str, Any] = {}
            audit_write_privileges: list[list[str]] = []
            audit_column_write_privileges: list[list[str]] = []
            for object_name in _PG_TABLES:
                row = object_rows.get(object_name)
                privileges: list[str] = []
                column_pairs: list[list[str]] = []
                if row is not None and roles["runtime"] in role_rows:
                    for privilege in ("SELECT", *table_mutation_privileges):
                        cursor.execute(
                            "SELECT pg_catalog.has_table_privilege(%s, %s, %s)",
                            (roles["runtime"], row[1], privilege),
                        )
                        if cursor.fetchone()[0] is True:
                            privileges.append(privilege)
                    cursor.execute(
                        "SELECT a.attname,"
                        " pg_catalog.has_column_privilege(%s, c.oid, a.attnum, 'SELECT'),"
                        " pg_catalog.has_column_privilege(%s, c.oid, a.attnum, 'INSERT'),"
                        " pg_catalog.has_column_privilege(%s, c.oid, a.attnum, 'UPDATE'),"
                        " pg_catalog.has_column_privilege(%s, c.oid, a.attnum, 'REFERENCES')"
                        " FROM pg_catalog.pg_attribute a"
                        " JOIN pg_catalog.pg_class c ON c.oid=a.attrelid"
                        " JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace"
                        " WHERE n.nspname=%s AND c.relname=%s"
                        " AND a.attnum>0 AND NOT a.attisdropped ORDER BY a.attnum",
                        (
                            roles["runtime"],
                            roles["runtime"],
                            roles["runtime"],
                            roles["runtime"],
                            object_name.split(".", 1)[0],
                            object_name.split(".", 1)[1],
                        ),
                    )
                    for column_row in _bounded_cursor_rows(cursor, maximum=128):
                        for privilege, granted in zip(
                            ("SELECT", "INSERT", "UPDATE", "REFERENCES"),
                            column_row[1:],
                            strict=True,
                        ):
                            if granted is True:
                                column_pairs.append(
                                    [_sha256(str(column_row[0]).encode("utf-8")), privilege]
                                )
                column_only = sorted(
                    {
                        privilege
                        for _column_sha, privilege in column_pairs
                        if privilege not in privileges
                    }
                )
                objects[object_name] = {
                    "exists": row is not None,
                    "owner_class": _principal_class(row[3], roles) if row is not None else None,
                    "runtime_privileges": privileges,
                    "runtime_column_privilege_count": len(column_pairs),
                    "runtime_column_privilege_sha256": _sha256(_canonical(column_pairs)),
                    "runtime_column_only_privileges": column_only,
                }
                if "audit" in roles and roles["audit"] in role_rows and row is not None:
                    for privilege in table_mutation_privileges:
                        cursor.execute(
                            "SELECT pg_catalog.has_table_privilege(%s, %s, %s)",
                            (roles["audit"], row[1], privilege),
                        )
                        if cursor.fetchone()[0] is True:
                            audit_write_privileges.append([object_name, privilege])
                    cursor.execute(
                        "SELECT a.attname,"
                        " pg_catalog.has_column_privilege(%s, c.oid, a.attnum, 'INSERT'),"
                        " pg_catalog.has_column_privilege(%s, c.oid, a.attnum, 'UPDATE'),"
                        " pg_catalog.has_column_privilege(%s, c.oid, a.attnum, 'REFERENCES')"
                        " FROM pg_catalog.pg_attribute a"
                        " JOIN pg_catalog.pg_class c ON c.oid=a.attrelid"
                        " JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace"
                        " WHERE n.nspname=%s AND c.relname=%s"
                        " AND a.attnum>0 AND NOT a.attisdropped ORDER BY a.attnum",
                        (
                            roles["audit"], roles["audit"], roles["audit"],
                            object_name.split(".", 1)[0], object_name.split(".", 1)[1],
                        ),
                    )
                    for column_row in _bounded_cursor_rows(cursor, maximum=128):
                        for privilege, granted in zip(
                            ("INSERT", "UPDATE", "REFERENCES"),
                            column_row[1:],
                            strict=True,
                        ):
                            if granted is True:
                                audit_column_write_privileges.append([
                                    object_name,
                                    _sha256(str(column_row[0]).encode("utf-8")),
                                    privilege,
                                ])
            for object_name in _PG_SEQUENCES:
                row = object_rows.get(object_name)
                privileges = []
                if row is not None and roles["runtime"] in role_rows:
                    for privilege in ("SELECT", "USAGE", "UPDATE"):
                        cursor.execute(
                            "SELECT pg_catalog.has_sequence_privilege(%s, %s, %s)",
                            (roles["runtime"], row[1], privilege),
                        )
                        if cursor.fetchone()[0] is True:
                            privileges.append(privilege)
                objects[object_name] = {
                    "exists": row is not None,
                    "owner_class": _principal_class(row[3], roles) if row is not None else None,
                    "runtime_privileges": privileges,
                }
                if "audit" in roles and roles["audit"] in role_rows and row is not None:
                    cursor.execute(
                        "SELECT pg_catalog.has_sequence_privilege("
                        "%s, %s, 'UPDATE')",
                        (roles["audit"], row[1]),
                    )
                    if cursor.fetchone()[0] is True:
                        audit_write_privileges.append([object_name, "UPDATE"])
            effective_mutations: dict[str, list[list[str | None]]] = {}
            effective_reads: dict[str, list[list[str]]] = {}
            for label in ("runtime", *( ("audit",) if "audit" in roles else () )):
                cursor.execute(
                    "WITH user_relations AS ("
                    " SELECT c.oid, n.nspname, c.relname, c.relkind"
                    " FROM pg_catalog.pg_class c"
                    " JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace"
                    " WHERE n.nspname !~ '^pg_' AND n.nspname<>'information_schema'"
                    " AND c.relkind IN ('r','p','v','m','f','S')"
                    "), table_grants AS ("
                    " SELECT 'relation'::text AS scope, nspname||'.'||relname AS object_name,"
                    " NULL::text AS column_name, privilege"
                    " FROM user_relations"
                    " CROSS JOIN pg_catalog.unnest(%s::text[]) AS p(privilege)"
                    " WHERE CASE WHEN relkind<>'S' THEN"
                    " pg_catalog.has_table_privilege(%s, oid, privilege)"
                    " ELSE false END"
                    "), sequence_grants AS ("
                    " SELECT 'sequence', nspname||'.'||relname, NULL::text, 'UPDATE'::text"
                    " FROM user_relations WHERE CASE WHEN relkind='S' THEN"
                    " pg_catalog.has_sequence_privilege(%s, oid, 'UPDATE')"
                    " ELSE false END"
                    "), column_grants AS ("
                    " SELECT 'column', r.nspname||'.'||r.relname, a.attname, privilege"
                    " FROM user_relations r"
                    " JOIN pg_catalog.pg_attribute a ON a.attrelid=r.oid"
                    " CROSS JOIN (VALUES ('INSERT'),('UPDATE'),('REFERENCES')) AS p(privilege)"
                    " WHERE a.attnum>0 AND NOT a.attisdropped"
                    " AND CASE WHEN r.relkind<>'S' THEN"
                    " pg_catalog.has_column_privilege("
                    "%s, r.oid, a.attnum, privilege)"
                    " AND NOT pg_catalog.has_table_privilege("
                    "%s, r.oid, privilege) ELSE false END"
                    ") SELECT scope, object_name, column_name, privilege FROM ("
                    " SELECT * FROM table_grants UNION ALL SELECT * FROM sequence_grants"
                    " UNION ALL SELECT * FROM column_grants"
                    ") effective ORDER BY scope, object_name, column_name, privilege",
                    (
                        table_mutation_privileges,
                        roles[label], roles[label], roles[label], roles[label],
                    ),
                )
                effective_mutations[label] = [
                    [
                        str(row[0]),
                        _sha256(str(row[1]).encode("utf-8")),
                        (
                            _sha256(str(row[2]).encode("utf-8"))
                            if row[2] is not None else None
                        ),
                        str(row[3]),
                    ]
                    for row in _bounded_cursor_rows(cursor, maximum=2048)
                ]
                cursor.execute(
                    "WITH user_relations AS ("
                    " SELECT c.oid, n.nspname, c.relname, c.relkind"
                    " FROM pg_catalog.pg_class c"
                    " JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace"
                    " WHERE n.nspname !~ '^pg_' AND n.nspname<>'information_schema'"
                    " AND c.relkind IN ('r','p','v','m','f','S')"
                    "), relation_reads AS ("
                    " SELECT 'relation'::text AS scope, nspname||'.'||relname AS object_name,"
                    " 'SELECT'::text AS privilege FROM user_relations"
                    " WHERE CASE WHEN relkind<>'S' THEN"
                    " pg_catalog.has_table_privilege(%s, oid, 'SELECT')"
                    " ELSE false END"
                    "), sequence_reads AS ("
                    " SELECT 'sequence', nspname||'.'||relname, privilege"
                    " FROM user_relations"
                    " CROSS JOIN (VALUES ('SELECT'),('USAGE')) AS p(privilege)"
                    " WHERE CASE WHEN relkind='S' THEN"
                    " pg_catalog.has_sequence_privilege(%s, oid, privilege)"
                    " ELSE false END"
                    "), column_reads AS ("
                    " SELECT 'column', r.nspname||'.'||r.relname||'.'||a.attname,"
                    " 'SELECT'::text FROM user_relations r"
                    " JOIN pg_catalog.pg_attribute a ON a.attrelid=r.oid"
                    " WHERE a.attnum>0 AND NOT a.attisdropped"
                    " AND CASE WHEN r.relkind<>'S' THEN"
                    " pg_catalog.has_column_privilege("
                    "%s, r.oid, a.attnum, 'SELECT')"
                    " AND NOT pg_catalog.has_table_privilege("
                    "%s, r.oid, 'SELECT') ELSE false END"
                    "), schema_reads AS ("
                    " SELECT 'schema', nspname, 'USAGE'::text"
                    " FROM pg_catalog.pg_namespace"
                    " WHERE nspname !~ '^pg_' AND nspname<>'information_schema'"
                    " AND pg_catalog.has_schema_privilege(%s, oid, 'USAGE')"
                    ") SELECT scope, object_name, privilege FROM ("
                    " SELECT * FROM relation_reads UNION ALL SELECT * FROM sequence_reads"
                    " UNION ALL SELECT * FROM column_reads UNION ALL SELECT * FROM schema_reads"
                    ") effective ORDER BY scope, object_name, privilege",
                    (
                        roles[label], roles[label], roles[label], roles[label],
                        roles[label],
                    ),
                )
                effective_reads[label] = [
                    [
                        str(row[0]),
                        _sha256(str(row[1]).encode("utf-8")),
                        str(row[2]),
                    ]
                    for row in _bounded_cursor_rows(cursor, maximum=2048)
                ]
            runtime_allowed_mutations = {
                (
                    "relation",
                    _sha256(name.encode("utf-8")),
                    None,
                    "INSERT",
                )
                for name in _PG_TABLES
            }
            runtime_out_of_contract_write_privileges = [
                row
                for row in effective_mutations["runtime"]
                if tuple(row) not in runtime_allowed_mutations
            ]
            runtime_allowed_reads = {
                ("relation", _sha256(name.encode("utf-8")), "SELECT")
                for name in _PG_TABLES
            } | {
                ("sequence", _sha256(name.encode("utf-8")), privilege)
                for name in _PG_SEQUENCES
                for privilege in ("SELECT", "USAGE")
            } | {("schema", _sha256(b"public"), "USAGE")}
            runtime_out_of_contract_read_privileges = [
                row
                for row in effective_reads["runtime"]
                if tuple(row) not in runtime_allowed_reads
            ]
            if "audit" in roles:
                audit_write_privileges = list(effective_mutations["audit"])
                audit_column_write_privileges = [
                    row for row in audit_write_privileges if row[0] == "column"
                ]
                audit_data_read_privileges = list(effective_reads["audit"])
            else:
                runtime_out_of_contract_write_privileges = []
                runtime_out_of_contract_read_privileges = []
                audit_data_read_privileges = []
            role_owned_user_object_count: dict[str, int] = {}
            role_user_function_execute_count: dict[str, int] = {}
            if "audit" in roles:
                for label, role_name in roles.items():
                    cursor.execute(
                        "WITH target_role AS (SELECT oid FROM pg_catalog.pg_roles WHERE rolname=%s) "
                        "SELECT "
                        " (SELECT count(*) FROM pg_catalog.pg_database d WHERE d.datdba=(SELECT oid FROM target_role) AND d.datname=pg_catalog.current_database()) +"
                        " (SELECT count(*) FROM pg_catalog.pg_namespace n WHERE n.nspowner=(SELECT oid FROM target_role) AND n.nspname !~ '^pg_' AND n.nspname<>'information_schema') +"
                        " (SELECT count(*) FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE c.relowner=(SELECT oid FROM target_role) AND n.nspname !~ '^pg_' AND n.nspname<>'information_schema') +"
                        " (SELECT count(*) FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace WHERE p.proowner=(SELECT oid FROM target_role) AND n.nspname !~ '^pg_' AND n.nspname<>'information_schema') +"
                        " (SELECT count(*) FROM pg_catalog.pg_type t JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace WHERE t.typowner=(SELECT oid FROM target_role) AND n.nspname !~ '^pg_' AND n.nspname<>'information_schema')",
                        (role_name,),
                    )
                    role_owned_user_object_count[label] = int(cursor.fetchone()[0])
                    cursor.execute(
                        "SELECT count(*) FROM pg_catalog.pg_proc p "
                        "JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace "
                        "WHERE n.nspname !~ '^pg_' AND n.nspname<>'information_schema' "
                        "AND pg_catalog.has_function_privilege("
                        "%s, p.oid, 'EXECUTE')",
                        (role_name,),
                    )
                    role_user_function_execute_count[label] = int(cursor.fetchone()[0])

                # `pg_shdepend` is the cluster catalogue's complete role-to-object
                # dependency spine.  The three non-owner application roles may
                # depend only on the current database and the runtime role's exact
                # application schema/relations.  Privilege kind is checked again
                # by the ACL/effective-privilege projections below.
                cursor.execute(
                    "WITH db AS ("
                    " SELECT oid FROM pg_catalog.pg_database"
                    " WHERE datname=pg_catalog.current_database()"
                    "), protected(label, role_oid) AS ("
                    " SELECT v.label, r.oid FROM (VALUES"
                    " ('migrator', %s::name), ('runtime', %s::name),"
                    " ('audit', %s::name)) v(label, rolname)"
                    " JOIN pg_catalog.pg_roles r ON r.rolname=v.rolname"
                    "), application_relations AS ("
                    " SELECT c.oid FROM pg_catalog.pg_class c"
                    " JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace"
                    " WHERE n.nspname='public' AND c.relname=ANY(%s)"
                    "), application_schema AS ("
                    " SELECT oid FROM pg_catalog.pg_namespace WHERE nspname='public'"
                    ")"
                    " SELECT p.label, d.classid::regclass::text, d.objid::text,"
                    " d.objsubid, d.deptype"
                    " FROM protected p JOIN pg_catalog.pg_shdepend d"
                    " ON d.refclassid='pg_catalog.pg_authid'::regclass"
                    " AND d.refobjid=p.role_oid"
                    " WHERE d.dbid IN (0, (SELECT oid FROM db))"
                    " AND d.deptype IN ('o','a','r','i')"
                    " AND NOT (d.deptype='a' AND ("
                    "   (d.classid='pg_catalog.pg_database'::regclass"
                    "    AND d.objid=(SELECT oid FROM db) AND d.objsubid=0)"
                    "   OR (p.label='runtime'"
                    "    AND d.classid='pg_catalog.pg_namespace'::regclass"
                    "    AND d.objid=(SELECT oid FROM application_schema)"
                    "    AND d.objsubid=0)"
                    "   OR (p.label='runtime'"
                    "    AND d.classid='pg_catalog.pg_class'::regclass"
                    "    AND d.objid IN (SELECT oid FROM application_relations)"
                    "    AND d.objsubid=0)"
                    " )) ORDER BY 1,2,3,4,5",
                    (
                        roles["migrator"], roles["runtime"], roles["audit"],
                        relation_names,
                    ),
                )
                for row in _bounded_cursor_rows(cursor, maximum=512):
                    authority_boundary_deviations.append([
                        "role_dependency",
                        str(row[0]),
                        _sha256(f"{row[1]}:{row[2]}:{row[3]}".encode("utf-8")),
                        str(row[4]),
                    ])

                # Positive ACL deltas on system objects are authority additions;
                # revocations are intentionally ignored.  pg_init_privs preserves
                # initdb/extension ACLs and acldefault supplies the true baseline
                # when no explicit initial ACL exists.
                cursor.execute(
                    "WITH protected(label, oid) AS ("
                    " SELECT v.label, r.oid FROM (VALUES"
                    " ('owner', %s::name), ('migrator', %s::name),"
                    " ('runtime', %s::name), ('audit', %s::name))"
                    " v(label, rolname)"
                    " JOIN pg_catalog.pg_roles r ON r.rolname=v.rolname"
                    "), objs(scope,classoid,objoid,objsubid,cur_acl,init_acl) AS ("
                    " SELECT 'schema','pg_catalog.pg_namespace'::regclass,"
                    " n.oid,0,"
                    " COALESCE(n.nspacl,pg_catalog.acldefault("
                    "   'n'::\"char\",n.nspowner)),"
                    " COALESCE(i.initprivs,CASE WHEN"
                    "   n.nspname='information_schema' AND n.oid<16384"
                    "   AND n.nspowner=10 THEN pg_catalog.array_append("
                    "     pg_catalog.acldefault('n'::\"char\",n.nspowner),"
                    "     pg_catalog.makeaclitem(0,n.nspowner,'USAGE',false))"
                    "   ELSE pg_catalog.acldefault("
                    "     'n'::\"char\",n.nspowner) END)"
                    " FROM pg_catalog.pg_namespace n"
                    " LEFT JOIN pg_catalog.pg_init_privs i"
                    " ON i.classoid='pg_catalog.pg_namespace'::regclass"
                    " AND i.objoid=n.oid AND i.objsubid=0"
                    " WHERE n.nspname IN ('pg_catalog','information_schema')"
                    " UNION ALL"
                    " SELECT 'relation','pg_catalog.pg_class'::regclass,c.oid,0,"
                    " COALESCE(c.relacl,pg_catalog.acldefault("
                    "   CASE WHEN c.relkind='S' THEN 's'::\"char\""
                    "   ELSE 'r'::\"char\" END,c.relowner)),"
                    " COALESCE(i.initprivs,CASE WHEN"
                    "   n.nspname='information_schema' AND c.oid<16384"
                    "   AND c.relowner=10 AND ("
                    "     (c.relkind='v' AND c.relname=ANY(%s)) OR"
                    "     (c.relkind='r' AND c.relname=ANY(%s))"
                    "   ) THEN pg_catalog.array_append("
                    "     pg_catalog.acldefault('r'::\"char\",c.relowner),"
                    "     pg_catalog.makeaclitem(0,c.relowner,'SELECT',false))"
                    "   ELSE pg_catalog.acldefault("
                    "     CASE WHEN c.relkind='S' THEN 's'::\"char\""
                    "     ELSE 'r'::\"char\" END,c.relowner) END)"
                    " FROM pg_catalog.pg_class c"
                    " JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace"
                    " LEFT JOIN pg_catalog.pg_init_privs i"
                    " ON i.classoid='pg_catalog.pg_class'::regclass"
                    " AND i.objoid=c.oid AND i.objsubid=0"
                    " WHERE n.nspname IN ('pg_catalog','information_schema')"
                    " AND c.relkind IN ('r','p','v','m','f','S')"
                    " UNION ALL"
                    " SELECT 'column','pg_catalog.pg_class'::regclass,c.oid,a.attnum,"
                    " a.attacl,i.initprivs"
                    " FROM pg_catalog.pg_attribute a"
                    " JOIN pg_catalog.pg_class c ON c.oid=a.attrelid"
                    " JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace"
                    " LEFT JOIN pg_catalog.pg_init_privs i"
                    " ON i.classoid='pg_catalog.pg_class'::regclass"
                    " AND i.objoid=c.oid AND i.objsubid=a.attnum"
                    " WHERE n.nspname IN ('pg_catalog','information_schema')"
                    " AND a.attnum>0 AND NOT a.attisdropped"
                    " UNION ALL"
                    " SELECT 'routine','pg_catalog.pg_proc'::regclass,p.oid,0,"
                    " COALESCE(p.proacl,pg_catalog.acldefault('f',p.proowner)),"
                    " COALESCE(i.initprivs,pg_catalog.acldefault('f',p.proowner))"
                    " FROM pg_catalog.pg_proc p"
                    " JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace"
                    " LEFT JOIN pg_catalog.pg_init_privs i"
                    " ON i.classoid='pg_catalog.pg_proc'::regclass"
                    " AND i.objoid=p.oid AND i.objsubid=0"
                    " WHERE n.nspname IN ('pg_catalog','information_schema')"
                    "), cur AS ("
                    " SELECT o.scope,o.classoid,o.objoid,o.objsubid,x.grantee,"
                    " x.privilege_type,x.is_grantable FROM objs o"
                    " CROSS JOIN LATERAL pg_catalog.aclexplode(o.cur_acl) x"
                    " WHERE x.grantee=0 OR x.grantee IN (SELECT oid FROM protected)"
                    "), base AS ("
                    " SELECT o.scope,o.classoid,o.objoid,o.objsubid,x.grantee,"
                    " x.privilege_type,x.is_grantable FROM objs o"
                    " CROSS JOIN LATERAL pg_catalog.aclexplode(o.init_acl) x"
                    " WHERE x.grantee=0 OR x.grantee IN (SELECT oid FROM protected)"
                    "), delta AS (SELECT * FROM cur EXCEPT SELECT * FROM base)"
                    " SELECT COALESCE(p.label,'public'),d.scope,"
                    " d.classoid::regclass::text,d.objoid::text,d.objsubid,"
                    " d.privilege_type,d.is_grantable"
                    " FROM delta d LEFT JOIN protected p ON p.oid=d.grantee"
                    " ORDER BY 1,2,3,4,5,6,7",
                    (
                        *tuple(
                            roles[label]
                            for label in ("owner", "migrator", "runtime", "audit")
                        ),
                        list(_PG16_17_INFORMATION_SCHEMA_PUBLIC_SELECT_VIEWS)
                        if 160000 <= server_version_int < 180000 else [],
                        list(_PG16_17_INFORMATION_SCHEMA_PUBLIC_SELECT_RELATIONS)
                        if 160000 <= server_version_int < 180000 else [],
                    ),
                )
                for row in _bounded_cursor_rows(cursor, maximum=4096):
                    authority_boundary_deviations.append([
                        "system_acl_delta",
                        str(row[0]),
                        str(row[1]),
                        _sha256(f"{row[2]}:{row[3]}:{row[4]}".encode("utf-8")),
                        str(row[5]),
                        int(bool(row[6])),
                    ])

                # Supported initdbs have no post-bootstrap routines in the two
                # system namespaces and no built-in SECURITY DEFINER/proconfig
                # routines there.  A default-PUBLIC function in pg_catalog can
                # otherwise turn an apparently read-only audit login directly
                # into its superuser owner.
                cursor.execute(
                    "SELECT n.nspname,p.oid::text,p.prosecdef,"
                    " p.proconfig IS NOT NULL"
                    " FROM pg_catalog.pg_proc p"
                    " JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace"
                    " WHERE n.nspname IN ('pg_catalog','information_schema')"
                    " AND (p.oid>=16384 OR p.prosecdef"
                    "      OR p.proconfig IS NOT NULL)"
                    " ORDER BY 1,2"
                )
                for row in _bounded_cursor_rows(cursor, maximum=512):
                    authority_boundary_deviations.append([
                        "system_routine_authority", str(row[0]),
                        _sha256(str(row[1]).encode("utf-8")),
                        int(bool(row[2])), int(bool(row[3])),
                    ])

                # Default ACLs are future authority.  Any default owned by a
                # protected principal, or any default grant to PUBLIC/a
                # protected principal, can silently widen the next object
                # created after this audit.  The exact supported posture is no
                # matching pg_default_acl row at all.
                cursor.execute(
                    "WITH protected(label,oid) AS ("
                    " SELECT v.label,r.oid FROM (VALUES"
                    " ('owner',%s::name),('migrator',%s::name),"
                    " ('runtime',%s::name),('audit',%s::name))"
                    " v(label,rolname) JOIN pg_catalog.pg_roles r"
                    " ON r.rolname=v.rolname"
                    ") SELECT COALESCE(o.label,'other'),"
                    " COALESCE(g.label,CASE WHEN x.grantee=0"
                    " THEN 'public' ELSE 'other' END),"
                    " d.defaclnamespace::text,d.defaclobjtype::text,"
                    " x.privilege_type,x.is_grantable"
                    " FROM pg_catalog.pg_default_acl d"
                    " CROSS JOIN LATERAL"
                    " pg_catalog.aclexplode(d.defaclacl) x"
                    " LEFT JOIN protected o ON o.oid=d.defaclrole"
                    " LEFT JOIN protected g ON g.oid=x.grantee"
                    " WHERE o.oid IS NOT NULL OR x.grantee=0"
                    " OR g.oid IS NOT NULL"
                    " ORDER BY 1,2,3,4,5,6",
                    tuple(
                        roles[label]
                        for label in ("owner", "migrator", "runtime", "audit")
                    ),
                )
                for row in _bounded_cursor_rows(cursor, maximum=512):
                    authority_boundary_deviations.append([
                        "default_acl", str(row[0]), str(row[1]),
                        _sha256(
                            f"{row[2]}:{row[3]}".encode("utf-8")
                        ),
                        str(row[4]), int(bool(row[5])),
                    ])

                # ALTER ROLE / ALTER DATABASE defaults can silently alter every
                # future connection.  The runtime supplies its posture explicitly,
                # so the only exact and auditable database/role default is none.
                cursor.execute(
                    "WITH protected(oid) AS ("
                    " SELECT oid FROM pg_catalog.pg_roles WHERE rolname=ANY(%s)"
                    "), db AS ("
                    " SELECT oid FROM pg_catalog.pg_database"
                    " WHERE datname=pg_catalog.current_database()"
                    ") SELECT s.setdatabase::text,s.setrole::text,c.setting"
                    " FROM pg_catalog.pg_db_role_setting s"
                    " CROSS JOIN LATERAL pg_catalog.unnest(s.setconfig) c(setting)"
                    " WHERE s.setdatabase IN (0,(SELECT oid FROM db))"
                    " AND (s.setrole=0 OR s.setrole IN (SELECT oid FROM protected))"
                    " ORDER BY 1,2,3",
                    (list(roles.values()),),
                )
                for row in _bounded_cursor_rows(cursor, maximum=256):
                    authority_boundary_deviations.append([
                        "connection_default",
                        _sha256(f"{row[0]}:{row[1]}".encode("utf-8")),
                        _sha256(str(row[2]).encode("utf-8")),
                    ])

                if not 160000 <= server_version_int < 180000:
                    authority_boundary_deviations.append([
                        "unsupported_server_version", "server_version",
                        _sha256(str(server_version_num).encode("utf-8")),
                    ])
                if server_version_int < 150000:
                    authority_boundary_deviations.append([
                        "parameter_acl_unavailable", "server_version",
                        _sha256(str(server_version_num).encode("utf-8")),
                    ])
                else:
                    for label, role_name in roles.items():
                        cursor.execute(
                            "SELECT p.parname,v.privilege"
                            " FROM pg_catalog.pg_parameter_acl p"
                            " CROSS JOIN (VALUES ('SET'),('ALTER SYSTEM'))"
                            " v(privilege)"
                            " WHERE pg_catalog.has_parameter_privilege("
                            "%s,p.parname,v.privilege) ORDER BY 1,2",
                            (role_name,),
                        )
                        for row in _bounded_cursor_rows(cursor, maximum=256):
                            authority_boundary_deviations.append([
                                "parameter_acl", label,
                                _sha256(str(row[0]).encode("utf-8")), str(row[1]),
                            ])

                cursor.execute(
                    "SELECT oid::text FROM pg_catalog.pg_largeobject_metadata"
                    " ORDER BY oid"
                )
                for row in _bounded_cursor_rows(cursor, maximum=512):
                    authority_boundary_deviations.append([
                        "large_object", "database",
                        _sha256(str(row[0]).encode("utf-8")),
                    ])
                cursor.execute(
                    "SELECT pg_catalog.current_setting('lo_compat_privileges')"
                )
                lo_compat_privileges = str(cursor.fetchone()[0]).lower()
                if lo_compat_privileges != "off":
                    authority_boundary_deviations.append([
                        "large_object_compatibility", "database",
                        _sha256(lo_compat_privileges.encode("utf-8")),
                    ])
                cursor.execute(
                    "WITH expected AS ("
                    " SELECT pg_catalog.to_regprocedure(signature)::oid AS oid"
                    " FROM pg_catalog.unnest(%s::text[]) signature"
                    "), observed AS ("
                    " SELECT p.oid,p.proowner,p.prokind,p.prosecdef,p.proconfig"
                    " FROM pg_catalog.pg_proc p"
                    " JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace"
                    " WHERE n.nspname='pg_catalog'"
                    " AND (pg_catalog.left(p.proname,3)='lo_'"
                    "      OR p.proname IN ('loread','lowrite'))"
                    ") SELECT"
                    " (SELECT pg_catalog.array_agg(oid ORDER BY oid) FROM expected),"
                    " (SELECT pg_catalog.array_agg(oid ORDER BY oid) FROM observed),"
                    " (SELECT count(*) FROM observed WHERE oid>=16384"
                    "   OR proowner<>10 OR prokind<>'f' OR prosecdef"
                    "   OR proconfig IS NOT NULL)",
                    (list(_PG16_17_LARGE_OBJECT_ROUTINES),),
                )
                inventory_row = cursor.fetchone()
                if not (
                    isinstance(inventory_row, tuple)
                    and len(inventory_row) == 3
                    and inventory_row[0] == inventory_row[1]
                    and len(inventory_row[0] or [])
                    == len(_PG16_17_LARGE_OBJECT_ROUTINES)
                    and inventory_row[2] == 0
                ):
                    authority_boundary_deviations.append([
                        "large_object_inventory", "database",
                        _sha256(_canonical(inventory_row)),
                    ])
                for label, role_name in roles.items():
                    cursor.execute(
                        "SELECT p.oid::text,p.proname"
                        " FROM pg_catalog.pg_proc p"
                        " JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace"
                        " WHERE n.nspname='pg_catalog'"
                        " AND (pg_catalog.left(p.proname,3)='lo_'"
                        "      OR p.proname IN ('loread','lowrite'))"
                        " AND pg_catalog.has_function_privilege(%s,p.oid,'EXECUTE')"
                        " ORDER BY p.oid",
                        (role_name,),
                    )
                    for row in _bounded_cursor_rows(cursor, maximum=256):
                        authority_boundary_deviations.append([
                            "large_object_execute", label,
                            _sha256(str(row[0]).encode("utf-8")), str(row[1]),
                        ])
                authority_boundary_deviations.sort(
                    key=lambda row: _canonical(row)
                )
        connection.rollback()
    except Exception as exc:
        if connection is not None:
            try:
                connection.rollback()
            except Exception:
                pass
        raise _PortUnavailable("PostgreSQL readback failed") from exc
    finally:
        if cancel_timer is not None:
            cancel_timer.cancel()
        if owns_connection and connection is not None:
            connection.close()

    role_facts = {}
    for label, role in roles.items():
        row = role_rows.get(role)
        role_facts[label] = {
            "name_sha256": _sha256(role.encode("utf-8")),
            "present": row is not None,
            "attributes": _role_attributes(row) if row is not None else None,
        }
    audit_attributes = role_facts.get("audit", {}).get("attributes")
    (
        audit_database_create,
        audit_database_temp,
        _audit_schema_usage,
        audit_schema_create_count,
        audit_schema_create_sha256,
    ) = role_scope_privileges.get(
        "audit", (False, False, False, 0, _sha256(_canonical([])))
    )
    audit_schema_create = audit_schema_create_count > 0
    audit_memberships = membership_digests_by_label.get("audit", [])
    audit_read_only = None
    if "audit" in roles:
        audit_read_only = bool(
            current_user == roles["audit"]
            and session_user == roles["audit"]
            and isinstance(audit_attributes, Mapping)
            and audit_attributes.get("login") is True
            and all(
                audit_attributes.get(field) is False
                for field in (
                    "superuser", "createdb", "createrole", "inherit",
                    "bypassrls", "replication",
                )
            )
            and not audit_database_create
            and not audit_database_temp
            and not audit_schema_create
            and not audit_data_read_privileges
            and not audit_write_privileges
            and not audit_column_write_privileges
            and not authority_boundary_deviations
            and len(audit_memberships) == 1
            and audit_memberships[0] == _sha256(roles["audit"].encode("utf-8"))
        )
    facts = {
        "database": str(config["database"]),
        "database_matches": database == config["database"],
        "database_oid_sha256": _sha256(str(database_oid).encode("utf-8")),
        "system_identifier_sha256": (
            _sha256(str(system_identifier).encode("utf-8"))
            if system_identifier is not None
            else None
        ),
        "transaction_read_only": str(transaction_read_only).lower() == "on",
        "challenge_nonce_sha256": (
            _sha256(str(challenge_nonce).encode("ascii")) if challenge_bound else None
        ),
        "current_actor_class": _principal_class(current_user, roles),
        "current_actor_sha256": _sha256(str(current_user).encode("utf-8")),
        "session_actor_sha256": _sha256(str(session_user).encode("utf-8")),
        "roles_distinct": len(set(roles.values())) == len(roles),
        "roles": role_facts,
        "objects": objects,
        "public_schema_owner_class": (
            _principal_class(schema_row[1], roles) if schema_row is not None else None
        ),
        "acl_projection_scope": "contract-objects-v1",
        "acl_projection_count": len(acl_projection),
        "acl_projection_sha256": _sha256(_canonical(acl_projection)),
        "acl_projection": acl_projection,
        "grantable_acl_counts": grantable_acl_counts,
        "public_acl_entry_counts": public_acl_entry_counts,
        "runtime_effective_role_sha256": membership_digests_by_label["runtime"],
        "role_effective_membership_sha256": (
            membership_digests_by_label if "audit" in roles else None
        ),
        "role_inbound_membership_sha256": (
            inbound_membership_digests_by_label if "audit" in roles else None
        ),
        "migrator_owner_membership": (
            migrator_owner_membership if "audit" in roles else None
        ),
        "role_owned_user_object_count": (
            role_owned_user_object_count if "audit" in roles else None
        ),
        "role_user_function_execute_count": (
            role_user_function_execute_count if "audit" in roles else None
        ),
        "runtime_database_create": bool(database_create),
        "runtime_database_temp": bool(database_temp),
        "runtime_schema_create": bool(schema_create),
        "runtime_schema_create_count": runtime_schema_create_count,
        "runtime_schema_create_sha256": runtime_schema_create_sha256,
        "runtime_schema_usage": bool(schema_usage),
        "runtime_out_of_contract_write_privilege_count": (
            len(runtime_out_of_contract_write_privileges)
            if "audit" in roles else None
        ),
        "runtime_out_of_contract_write_privilege_sha256": (
            _sha256(_canonical(sorted(runtime_out_of_contract_write_privileges)))
            if "audit" in roles else None
        ),
        "runtime_out_of_contract_read_privilege_count": (
            len(runtime_out_of_contract_read_privileges)
            if "audit" in roles else None
        ),
        "runtime_out_of_contract_read_privilege_sha256": (
            _sha256(_canonical(sorted(runtime_out_of_contract_read_privileges)))
            if "audit" in roles else None
        ),
        "authority_boundary_deviation_count": (
            len(authority_boundary_deviations) if "audit" in roles else None
        ),
        "authority_boundary_deviation_sha256": (
            _sha256(_canonical(authority_boundary_deviations))
            if "audit" in roles else None
        ),
        "audit_principal_read_only": audit_read_only,
        "audit_effective_role_sha256": audit_memberships if "audit" in roles else None,
        "audit_database_create": audit_database_create if "audit" in roles else None,
        "audit_database_temp": audit_database_temp if "audit" in roles else None,
        "audit_schema_create": audit_schema_create if "audit" in roles else None,
        "audit_schema_create_count": (
            audit_schema_create_count if "audit" in roles else None
        ),
        "audit_schema_create_sha256": (
            audit_schema_create_sha256 if "audit" in roles else None
        ),
        "audit_data_read_privilege_count": (
            len(audit_data_read_privileges) if "audit" in roles else None
        ),
        "audit_data_read_privilege_sha256": (
            _sha256(_canonical(sorted(audit_data_read_privileges)))
            if "audit" in roles else None
        ),
        "audit_write_privilege_count": (
            len(audit_write_privileges) if "audit" in roles else None
        ),
        "audit_write_privilege_sha256": (
            _sha256(_canonical(sorted(audit_write_privileges)))
            if "audit" in roles else None
        ),
        "audit_column_write_privilege_count": (
            len(audit_column_write_privileges) if "audit" in roles else None
        ),
        "audit_column_write_privilege_sha256": (
            _sha256(_canonical(sorted(audit_column_write_privileges)))
            if "audit" in roles else None
        ),
    }
    return AdapterResult(
        "OBSERVED" if not failures else "PARTIAL",
        facts,
        tuple(sorted(failures)),
        {
            "configured_host": configured_host,
            "configured_port": configured_port,
            "configured_database": str(config["database"]),
            "database": database,
            "database_oid": str(database_oid),
            "server_address": server_address,
            "server_port": server_port,
            "server_version_num": str(server_version_num),
            "system_identifier": (
                str(system_identifier) if system_identifier is not None else None
            ),
        },
    )


def collect_postgresql(
    config: Mapping[str, Any], timeout: float, environ: Mapping[str, str]
) -> AdapterResult:
    return _collect_postgresql_impl(config, timeout, environ)


def _principal_class(value: Any, roles: Mapping[str, str]) -> str:
    for label, role in roles.items():
        if value == role:
            return label
    return "other"


def _neo_audit_privilege_row_is_safe(row: Mapping[str, Any], database: str) -> bool:
    """Conservatively classify one effective audit privilege row."""

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


def _neo_named_role_privileges_are_exact(
    rows: Sequence[Mapping[str, Any]], *, database: str, migrator: bool
) -> bool:
    allowed = {"access", "match", "write"}
    if migrator:
        allowed.update({"constraint", "token"})
    identities: set[tuple[Any, ...]] = set()
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        if row.get("access") != "GRANTED" or row.get("immutable") is not False:
            return False
        action = row.get("action")
        if action not in allowed or str(row.get("graph", "")) != database:
            return False
        identity = tuple(row.get(field) for field in (
            "access", "action", "resource", "graph", "segment", "immutable"
        ))
        if identity in identities:
            return False
        identities.add(identity)
        grouped.setdefault(action, []).append(row)
    return set(grouped) == allowed and all(
        _neo_action_scope_exact(action, action_rows, database)
        for action, action_rows in grouped.items()
    )


def _neo_action_scope_exact(
    action: str, rows: Sequence[Mapping[str, Any]], database: str
) -> bool:
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


def _neo_audit_privileges_are_exact(
    rows: Sequence[Mapping[str, Any]], *, database: str, version: str
) -> bool:
    setting_names = (
        _NEO_AUTH_SETTING_NAMES
        if _neo_abac_setting_supported(version)
        else _NEO_BASE_AUTH_SETTING_NAMES
    )
    if len(rows) != 8 + len(setting_names):
        return False
    identities = {
        tuple(row.get(field) for field in (
            "access", "action", "resource", "graph", "segment", "immutable"
        ))
        for row in rows
    }
    return identities == {
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
    if not isinstance(version, str):
        return False
    match = re.fullmatch(
        r"2026\.(\d{2})(?:\.(?:0|[1-9]\d*))?", version
    )
    return bool(
        match is not None
        and (2026, int(match.group(1))) in NEO4J_SUPPORTED_RELEASES
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


def _neo_privilege_projection(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "access": row.get("access"),
            "action": row.get("action"),
            "resource": row.get("resource"),
            "graph": row.get("graph"),
            "segment": row.get("segment"),
            "immutable": row.get("immutable"),
        }
        for row in rows
    ]


def _neo_rows(
    session: Any, query: str, timeout: float, *, maximum: int = 64,
    **params: Any,
) -> list[dict[str, Any]]:
    from neo4j import Query

    rows: list[dict[str, Any]] = []
    for record in session.run(Query(query, timeout=timeout), **params):
        if len(rows) >= maximum:
            raise _PortUnavailable("Neo4j readback exceeds bounded row count")
        rows.append(dict(record))
    return rows


def _neo_system_authority_marker(
    session: Any, timeout: float
) -> dict[str, Any] | None:
    rows = _neo_rows(
        session,
        "SHOW DATABASE system "
        "YIELD name, type, databaseID, currentStatus, writer, "
        "lastCommittedTxn, replicationLag "
        "WHERE writer = true "
        "RETURN name, type, databaseID AS database_id, "
        "currentStatus AS current_status, writer, "
        "lastCommittedTxn AS last_committed_tx, "
        "replicationLag AS replication_lag",
        timeout,
        maximum=2,
    )
    if len(rows) != 1:
        return None
    row = rows[0]
    database_id = row.get("database_id")
    last_committed_tx = row.get("last_committed_tx")
    replication_lag = row.get("replication_lag")
    if not (
        row.get("name") == "system"
        and row.get("type") == "system"
        and row.get("current_status") == "online"
        and row.get("writer") is True
        and isinstance(database_id, str)
        and bool(database_id)
        and type(last_committed_tx) is int
        and last_committed_tx >= 0
        and type(replication_lag) is int
        and replication_lag == 0
    ):
        return None
    return {
        "database_id": database_id,
        "last_committed_tx": last_committed_tx,
    }


def _validated_neo_uri(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "bolt+s"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.hostname is None
    ):
        raise _PortUnavailable(
            "Neo4j URI must be one credential-free system-trusted Bolt TLS endpoint"
        )
    try:
        port = parsed.port
    except ValueError as exc:
        raise _PortUnavailable("Neo4j URI port is invalid") from exc
    if port is None or not (1 <= port <= 65535):
        raise _PortUnavailable("Neo4j URI must include one pinned port")
    try:
        ipaddress.ip_address(parsed.hostname)
    except ValueError as exc:
        raise _PortUnavailable("Neo4j URI host must be one literal IP") from exc
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    return urlunsplit((parsed.scheme, f"{host}:{port}", parsed.path, "", ""))


def _collect_neo4j_impl(
    config: Mapping[str, Any],
    timeout: float,
    environ: Mapping[str, str],
    *,
    injected_driver: Any | None = None,
    injected_uri: str | None = None,
) -> AdapterResult:
    owns_driver = injected_driver is None
    driver = injected_driver
    user = password = None
    if owns_driver:
        uri = environ.get(NEO4J_URI_ENV)
        user = environ.get(NEO4J_USER_ENV)
        password = environ.get(NEO4J_PASSWORD_ENV)
        if not uri or not user or not password:
            return AdapterResult("UNAVAILABLE", {}, ("neo4j.auth_material_unavailable",))
        configured_uri = _validated_neo_uri(uri)
    else:
        if not isinstance(injected_uri, str) or not injected_uri:
            raise _PortUnavailable("injected Neo4j test endpoint is invalid")
        configured_uri = injected_uri
    try:
        from neo4j import GraphDatabase, READ_ACCESS
    except ModuleNotFoundError:
        return AdapterResult("UNAVAILABLE", {}, ("neo4j.dependency_unavailable",))

    failures: list[str] = []
    deadline = time.monotonic() + timeout
    challenge_nonce = config.get("challenge_nonce")
    challenge_bound = challenge_nonce is not None
    if challenge_bound and not _exact_sha256(challenge_nonce):
        raise _PortUnavailable("Neo4j audit challenge nonce is invalid")

    def remaining() -> float:
        value = deadline - time.monotonic()
        if value <= 0:
            raise _PortUnavailable("Neo4j collection deadline exhausted")
        return value

    try:
        if owns_driver:
            driver = GraphDatabase.driver(
                configured_uri,
                auth=(user, password),
                connection_timeout=float(timeout),
                connection_acquisition_timeout=float(timeout),
            )
            driver.verify_connectivity()
        with driver.session(
            database=str(config["database"]), default_access_mode=READ_ACCESS
        ) as session:
            if challenge_bound:
                challenge_rows = _neo_rows(
                    session,
                    "RETURN $challenge_nonce AS challenge_nonce",
                    remaining(),
                    challenge_nonce=challenge_nonce,
                )
                if challenge_rows != [{"challenge_nonce": challenge_nonce}]:
                    raise _PortUnavailable("Neo4j audit challenge was not echoed")
            components = _neo_rows(
                session,
                "CALL dbms.components() YIELD versions, edition "
                "RETURN versions[0] AS version, edition",
                remaining(),
            )
            database_rows = _neo_rows(
                session,
                "CALL db.info() YIELD id, name RETURN id, name",
                remaining(),
            )
        component_candidates = [
            row
            for row in components
            if isinstance(row.get("edition"), str)
            and bool(row.get("edition"))
            and isinstance(row.get("version"), str)
            and bool(row.get("version"))
        ]
        if len(component_candidates) != 1:
            raise _PortUnavailable("Neo4j component readback was ambiguous")
        component = component_candidates[0]
        if len(database_rows) != 1:
            raise _PortUnavailable("Neo4j database identity readback was ambiguous")
        database_identity = database_rows[0]
        current_user = None
        roles: list[str] | None = None
        privilege_rows: list[dict[str, Any]] | None = None
        named_privilege_rows: list[dict[str, Any]] | None = None
        all_privilege_rows: list[dict[str, Any]] | None = None
        named_user_rows: list[dict[str, Any]] | None = None
        auth_setting_rows: list[dict[str, Any]] | None = None
        alias_rows: list[dict[str, Any]] | None = None
        database_catalog_rows: list[dict[str, Any]] | None = None
        system_marker_before: dict[str, Any] | None = None
        system_marker_after: dict[str, Any] | None = None
        try:
            with driver.session(database="system", default_access_mode=READ_ACCESS) as session:
                system_marker_before = _neo_system_authority_marker(
                    session, remaining()
                )
                user_rows = _neo_rows(
                    session,
                    "SHOW CURRENT USER YIELD user, roles RETURN user, roles",
                    remaining(),
                )
                if len(user_rows) == 1:
                    current_user = user_rows[0].get("user")
                    raw_roles = user_rows[0].get("roles")
                    if isinstance(raw_roles, list) and all(isinstance(role, str) for role in raw_roles):
                        roles = sorted(set(raw_roles))
                    else:
                        failures.append("neo4j.current_user.roles_unavailable")
                else:
                    failures.append("neo4j.current_user.ambiguous")
                try:
                    privilege_rows = _neo_rows(
                        session,
                        "SHOW USER PRIVILEGES YIELD access, action, resource, graph, segment, immutable "
                        "RETURN access, action, resource, graph, segment, immutable "
                        "ORDER BY access, action, resource, graph, segment, immutable",
                        remaining(),
                    )
                except Exception:
                    failures.append("neo4j.effective_privileges.unavailable")
                if all(
                    field in config
                    for field in (
                        "audit_user", "audit_role", "migrator_user", "migrator_role",
                        "runtime_user", "runtime_role",
                    )
                ):
                    try:
                        alias_rows = _neo_rows(
                            session,
                            "SHOW ALIASES FOR DATABASE "
                            "YIELD name, database, location "
                            "WHERE name = $database "
                            "RETURN name, database, location ORDER BY name",
                            remaining(),
                            database=str(config["database"]),
                        )
                        database_catalog_rows = _neo_rows(
                            session,
                            "SHOW DATABASES YIELD name, type, currentStatus "
                            "WHERE name = $database "
                            "RETURN name, type, currentStatus AS current_status "
                            "ORDER BY name",
                            remaining(),
                            database=str(config["database"]),
                        )
                        auth_setting_rows = _neo_rows(
                            session,
                            "SHOW SETTINGS $setting_names "
                            "YIELD name, value, startupValue "
                            "RETURN name, value, startupValue AS startup_value ORDER BY name",
                            remaining(),
                            setting_names=list(_NEO_AUTH_SETTING_NAMES),
                        )
                        named_user_rows = _neo_rows(
                            session,
                            "SHOW USERS YIELD user, roles, suspended "
                            "RETURN user, roles, suspended ORDER BY user",
                            remaining(),
                        )
                        all_privilege_rows = _neo_rows(
                            session,
                            "SHOW PRIVILEGES "
                            "YIELD role, access, action, resource, graph, segment, immutable "
                            "RETURN role, access, action, resource, graph, segment, immutable "
                            "ORDER BY role, access, action, resource, graph, segment, immutable",
                            remaining(),
                            maximum=4096,
                        )
                        declared_roles = {
                            str(config["audit_role"]).lower(),
                            str(config["migrator_role"]).lower(),
                            str(config["runtime_role"]).lower(),
                            "public",
                        }
                        named_privilege_rows = [
                            row for row in all_privilege_rows
                            if str(row.get("role", "")).lower() in declared_roles
                        ]
                    except Exception:
                        failures.append("neo4j.named_role_privileges.unavailable")
                system_marker_after = _neo_system_authority_marker(
                    session, remaining()
                )
        except Exception:
            failures.append("neo4j.current_user.unavailable")
    except _PortUnavailable:
        raise
    except Exception as exc:
        raise _PortUnavailable("Neo4j readback failed") from exc
    finally:
        if owns_driver and driver is not None:
            driver.close()

    edition = _optional_text(component.get("edition"), maximum=64)
    version = _optional_text(component.get("version"), maximum=64)
    if current_user is None:
        current_user_sha256 = None
    else:
        current_user_sha256 = _sha256(str(current_user).encode("utf-8"))
    if privilege_rows is None:
        privilege_sha256 = None
        privilege_count = None
    else:
        privilege_sha256 = _sha256(_canonical(privilege_rows))
        privilege_count = len(privilege_rows)
    role_hashes = None if roles is None else sorted(
        _sha256(role.encode("utf-8")) for role in roles
    )
    named_roles = None
    named_role_privilege_sha256 = None
    named_role_privileges = None
    public_role_binding_sha256 = None
    custom_role_binding_ok = None
    named_user_role_sha256 = None
    named_role_assignee_sha256 = None
    named_user_role_binding_ok = None
    runtime_role_least_privilege = None
    migrator_role_least_privilege = None
    public_role_safe = None
    auth_settings = None
    auth_settings_sha256 = None
    native_only_auth = None
    database_direct_local = None
    database_alias_projection = None
    database_catalog_projection = None
    global_unsafe_privileges = None
    effective_privilege_projection = None
    audit_unsafe_rows: list[dict[str, Any]] = []
    audit_read_only = None
    authorization_snapshot_stable = bool(
        system_marker_before is not None
        and system_marker_before == system_marker_after
    )
    if not authorization_snapshot_stable:
        failures.append("neo4j.authorization_snapshot.unstable")
    if all(
        field in config
        for field in (
            "audit_user", "audit_role", "migrator_user", "migrator_role",
            "runtime_user", "runtime_role",
        )
    ):
        named_roles = {
            label: _sha256(str(config[f"{label}_role"]).encode("utf-8"))
            for label in ("audit", "migrator", "runtime")
        }
        custom_role_binding_ok = bool(
            roles is not None
            and {role for role in roles if role.upper() != "PUBLIC"}
            == {str(config["audit_role"])}
        )
        if alias_rows is not None and database_catalog_rows is not None:
            database_alias_projection = [
                {
                    "name_sha256": _sha256(str(row.get("name")).encode("utf-8")),
                    "database_sha256": _sha256(
                        str(row.get("database")).encode("utf-8")
                    ),
                    "location": row.get("location"),
                }
                for row in alias_rows
            ]
            database_catalog_projection = [
                {
                    "name_sha256": _sha256(str(row.get("name")).encode("utf-8")),
                    "type": row.get("type"),
                    "current_status": row.get("current_status"),
                }
                for row in database_catalog_rows
            ]
            database_direct_local = bool(
                database_alias_projection == []
                and database_catalog_projection == [{
                    "name_sha256": _sha256(
                        str(config["database"]).encode("utf-8")
                    ),
                    "type": "standard",
                    "current_status": "online",
                }]
            )
        if named_privilege_rows is not None:
            grouped: dict[str, list[dict[str, Any]]] = {
                "audit": [], "migrator": [], "runtime": [], "public": [],
            }
            reverse_roles = {
                str(config["audit_role"]).lower(): "audit",
                str(config["migrator_role"]).lower(): "migrator",
                str(config["runtime_role"]).lower(): "runtime",
                "public": "public",
            }
            for row in named_privilege_rows:
                label = reverse_roles.get(str(row.get("role")).lower())
                if label is not None:
                    grouped[label].append(row)
            named_role_privileges = {
                label: _neo_privilege_projection(rows_for_role)
                for label, rows_for_role in grouped.items()
            }
            named_role_privilege_sha256 = {
                label: _sha256(_canonical(named_role_privileges[label]))
                for label, rows_for_role in grouped.items()
                if label != "public"
            }
            public_role_binding_sha256 = _sha256(
                _canonical(named_role_privileges["public"])
            )
            runtime_role_least_privilege = _neo_named_role_privileges_are_exact(
                named_role_privileges["runtime"],
                database=str(config["database"]),
                migrator=False,
            )
            migrator_role_least_privilege = _neo_named_role_privileges_are_exact(
                named_role_privileges["migrator"],
                database=str(config["database"]),
                migrator=True,
            )
            public_role_safe = named_role_privileges["public"] == []
        if auth_setting_rows is not None:
            auth_settings = [
                {
                    "name": row.get("name"),
                    "value": row.get("value"),
                    "startup_value": row.get("startup_value"),
                }
                for row in auth_setting_rows
            ]
            auth_settings_sha256 = _sha256(_canonical(auth_settings))
            native_only_auth = _neo_native_auth_settings_exact(
                auth_settings, version=str(version)
            )
        if named_user_rows is not None:
            users_by_name = {
                str(row.get("user")): {
                    "roles": row.get("roles"),
                    "suspended": row.get("suspended"),
                }
                for row in named_user_rows
                if isinstance(row.get("user"), str)
            }
            named_user_role_sha256 = {}
            named_role_assignee_sha256 = {
                label: sorted(
                    _sha256(user_name.encode("utf-8"))
                    for user_name, user_state in users_by_name.items()
                    for raw_user_roles in (user_state.get("roles"),)
                    if user_state.get("suspended") is False
                    if isinstance(raw_user_roles, list)
                    and all(isinstance(role, str) for role in raw_user_roles)
                    and str(config[f"{label}_role"]) in raw_user_roles
                )
                for label in ("audit", "migrator", "runtime")
            }
            binding_checks = []
            for label in ("audit", "migrator", "runtime"):
                user_state = users_by_name.get(str(config[f"{label}_user"]))
                raw_user_roles = (
                    user_state.get("roles")
                    if isinstance(user_state, Mapping)
                    and user_state.get("suspended") is False
                    else None
                )
                user_roles = (
                    sorted(set(raw_user_roles))
                    if isinstance(raw_user_roles, list)
                    and all(isinstance(role, str) for role in raw_user_roles)
                    else None
                )
                named_user_role_sha256[label] = (
                    None
                    if user_roles is None
                    else [_sha256(role.encode("utf-8")) for role in user_roles]
                )
                binding_checks.append(
                    user_roles is not None
                    and {role for role in user_roles if role.upper() != "PUBLIC"}
                    == {str(config[f"{label}_role"])}
                )
            named_user_role_binding_ok = all(binding_checks)
            if all_privilege_rows is not None:
                active_roles = {
                    role.lower()
                    for user_state in users_by_name.values()
                    if user_state.get("suspended") is False
                    and isinstance(user_state.get("roles"), list)
                    for role in user_state["roles"]
                    if isinstance(role, str)
                }
                declared_roles = {
                    str(config[f"{label}_role"]).lower()
                    for label in ("audit", "migrator", "runtime")
                } | {"public"}
                global_unsafe_privileges = []
                for row in all_privilege_rows:
                    role = row.get("role")
                    role_key = role.lower() if isinstance(role, str) else None
                    if role_key not in active_roles or role_key in declared_roles:
                        continue
                    access = row.get("access")
                    if access == "DENIED":
                        continue
                    global_unsafe_privileges.append({
                        "role_sha256": (
                            _sha256(role.encode("utf-8"))
                            if isinstance(role, str) else None
                        ),
                        "access": access,
                        "action": row.get("action"),
                        "resource": row.get("resource"),
                        "graph": row.get("graph"),
                        "segment": row.get("segment"),
                        "immutable": row.get("immutable"),
                    })
        if privilege_rows is not None:
            effective_privilege_projection = _neo_privilege_projection(privilege_rows)
            for row in privilege_rows:
                if not _neo_audit_privilege_row_is_safe(row, str(config["database"])):
                    audit_unsafe_rows.append(row)
        audit_read_only = bool(
            isinstance(edition, str)
            and edition.lower() == "enterprise"
            and _neo_version_supported(version)
            and current_user == config["audit_user"]
            and custom_role_binding_ok is True
            and privilege_rows is not None
            and named_privilege_rows is not None
            and named_user_role_binding_ok is True
            and named_role_assignee_sha256 == {
                label: [
                    _sha256(str(config[f"{label}_user"]).encode("utf-8"))
                ]
                for label in ("audit", "migrator", "runtime")
            }
            and public_role_safe is True
            and native_only_auth is True
            and database_direct_local is True
            and global_unsafe_privileges == []
            and authorization_snapshot_stable
            and _neo_audit_privileges_are_exact(
                named_role_privileges["audit"], database=str(config["database"]),
                version=str(version),
            )
            and effective_privilege_projection == named_role_privileges["audit"]
            and not audit_unsafe_rows
        )
    facts = {
        "database": str(config["database"]),
        "challenge_nonce_sha256": (
            _sha256(str(challenge_nonce).encode("ascii")) if challenge_bound else None
        ),
        "database_name_matches": database_identity.get("name") == config["database"],
        "database_direct_local": database_direct_local,
        "database_alias_count": (
            len(database_alias_projection)
            if database_alias_projection is not None else None
        ),
        "database_alias_sha256": (
            _sha256(_canonical(database_alias_projection))
            if database_alias_projection is not None else None
        ),
        "database_catalog_sha256": (
            _sha256(_canonical(database_catalog_projection))
            if database_catalog_projection is not None else None
        ),
        "database_id_sha256": (
            _sha256(str(database_identity["id"]).encode("utf-8"))
            if database_identity.get("id") is not None
            else None
        ),
        "edition": edition,
        "version": version,
        "enterprise": isinstance(edition, str) and edition.lower() == "enterprise",
        "current_actor_sha256": current_user_sha256,
        "role_sha256": role_hashes,
        "role_count": None if roles is None else len(roles),
        "effective_privilege_sha256": privilege_sha256,
        "effective_privilege_count": privilege_count,
        "effective_privileges": effective_privilege_projection,
        "audit_principal_read_only": audit_read_only,
        "audit_unsafe_granted_action_count": (
            len(audit_unsafe_rows) if named_roles is not None else None
        ),
        "audit_unsafe_granted_action_sha256": (
            _sha256(_canonical(audit_unsafe_rows)) if named_roles is not None else None
        ),
        "named_role_sha256": named_roles,
        "named_role_privilege_sha256": named_role_privilege_sha256,
        "named_role_privileges": named_role_privileges,
        "public_role_binding_sha256": public_role_binding_sha256,
        "custom_role_binding_ok": custom_role_binding_ok,
        "named_user_role_sha256": named_user_role_sha256,
        "named_role_assignee_sha256": named_role_assignee_sha256,
        "named_user_role_binding_ok": named_user_role_binding_ok,
        "runtime_role_least_privilege": runtime_role_least_privilege,
        "migrator_role_least_privilege": migrator_role_least_privilege,
        "public_role_safe": public_role_safe,
        "auth_settings": auth_settings,
        "auth_settings_sha256": auth_settings_sha256,
        "native_only_auth": native_only_auth,
        "global_unsafe_privilege_count": (
            len(global_unsafe_privileges)
            if global_unsafe_privileges is not None else None
        ),
        "global_unsafe_privilege_sha256": (
            _sha256(_canonical(global_unsafe_privileges))
            if global_unsafe_privileges is not None else None
        ),
        "system_database_id_sha256": (
            _sha256(system_marker_before["database_id"].encode("utf-8"))
            if system_marker_before is not None else None
        ),
        "system_last_committed_tx": (
            system_marker_before["last_committed_tx"]
            if system_marker_before is not None else None
        ),
        "authorization_snapshot_stable": authorization_snapshot_stable,
        "read_query_count": (
            (11 if named_roles is not None else 6) + int(challenge_bound)
        ),
    }
    return AdapterResult(
        "OBSERVED" if not failures else "PARTIAL",
        facts,
        tuple(sorted(set(failures))),
        {
            "configured_uri": configured_uri,
            "configured_database": str(config["database"]),
            "database_id": database_identity.get("id"),
            "database_name": database_identity.get("name"),
        },
    )


def collect_neo4j(
    config: Mapping[str, Any], timeout: float, environ: Mapping[str, str]
) -> AdapterResult:
    return _collect_neo4j_impl(config, timeout, environ)


def collect_predeploy(config: Mapping[str, Any], timeout: float, environ: Mapping[str, str]) -> AdapterResult:
    del timeout, environ
    raw, value, info = _load_pinned_json(
        Path(str(config["path"])), str(config["file_sha256"]), max_bytes=MAX_ARTIFACT_BYTES
    )
    if not isinstance(value, Mapping):
        raise _PortUnavailable("predeploy receipt root is not an object")
    body = dict(value)
    self_digest = body.pop("receipt_sha256", None)
    operation = body.get("operation")
    operation_sha256 = operation.get("sha256") if isinstance(operation, Mapping) else None
    artifact = body.get("artifact")
    try:
        artifact_sha256 = artifact_identity_sha256(artifact)
    except RuntimeAuthorityError:
        artifact_sha256 = None
    drain = body.get("writer_drain")
    live_fence = drain.get("live_fence") if isinstance(drain, Mapping) else None
    environment = body.get("environment")
    facts = {
        "file_sha256": _sha256(raw),
        "file_read_only": not bool(info.st_mode & 0o222),
        "schema_matches_expected": body.get("schema_version") == _PREDEPLOY_SCHEMA,
        "contract_matches_expected": body.get("contract_id") == STORAGE_CONTRACT_ID,
        "environment_sha256": (
            _sha256(environment.encode("utf-8")) if isinstance(environment, str) else None
        ),
        "target_sha256": body.get("target_sha256") if _exact_sha256(body.get("target_sha256")) else None,
        "operation_sha256": operation_sha256 if _exact_sha256(operation_sha256) else None,
        "created_at": _optional_timestamp(body.get("created_at")),
        "self_digest_valid": (
            _exact_sha256(self_digest)
            and hmac.compare_digest(str(self_digest), _sha256(_canonical(body)))
        ),
        "writer_drain_present": isinstance(drain, Mapping),
        "live_fence_present": isinstance(live_fence, Mapping),
        "signed_fence_present": (
            isinstance(live_fence, Mapping)
            and isinstance(live_fence.get("signed_response"), Mapping)
            and isinstance(live_fence["signed_response"].get("signature"), str)
        ),
    }
    return AdapterResult(
        "OBSERVED",
        facts,
        (),
        {
            "target_sha256": facts["target_sha256"],
            "operation_sha256": facts["operation_sha256"],
            "artifact_identity_sha256": artifact_sha256,
            "predeploy_receipt_file_sha256": facts["file_sha256"],
            "structural_receipt_identity_valid": bool(
                facts["schema_matches_expected"]
                and facts["contract_matches_expected"]
                and facts["self_digest_valid"]
                and artifact_sha256 is not None
                and facts["operation_sha256"] is not None
            ),
        },
    )


def collect_temporal(config: Mapping[str, Any], timeout: float, environ: Mapping[str, str]) -> AdapterResult:
    del timeout, environ
    values: dict[str, Mapping[str, Any]] = {}
    facts: dict[str, Any] = {}
    for field in ("authority_policy", "sidecar", "runtime_binding"):
        item = config[field]
        raw, value, _info = _load_pinned_json(
            Path(str(item["path"])), str(item["file_sha256"]), max_bytes=MAX_ARTIFACT_BYTES
        )
        if not isinstance(value, Mapping):
            raise _PortUnavailable("temporal artifact root is not an object")
        values[field] = value
        facts[f"{field}_file_sha256"] = _sha256(raw)
        facts[f"{field}_schema_matches_expected"] = (
            value.get("schema_version") == _TEMPORAL_SCHEMAS[field]
        )
    sidecar = values["sidecar"]
    prediction_anchors = sidecar.get("prediction_anchors")
    verdict_anchors = sidecar.get("verdict_anchors")
    binding = values["runtime_binding"]
    sidecar_domain_sha256 = _sha256(_TEMPORAL_SIDECAR_DOMAIN + _canonical(sidecar))
    bound_sidecar_sha256 = binding.get("sidecar_sha256")
    facts.update({
        "prediction_anchor_count": len(prediction_anchors) if isinstance(prediction_anchors, list) else None,
        "verdict_anchor_count": len(verdict_anchors) if isinstance(verdict_anchors, list) else None,
        "bound_sidecar_sha256": (
            bound_sidecar_sha256
            if _exact_sha256(bound_sidecar_sha256)
            else None
        ),
        "sidecar_domain_sha256": sidecar_domain_sha256,
        "sidecar_binding_matches": (
            _exact_sha256(bound_sidecar_sha256)
            and hmac.compare_digest(str(bound_sidecar_sha256), sidecar_domain_sha256)
        ),
        "receipt_graph_sha256": (
            binding.get("receipt_graph_sha256")
            if _exact_sha256(binding.get("receipt_graph_sha256"))
            else None
        ),
    })
    return AdapterResult("OBSERVED", facts)


def default_ports() -> CollectorPorts:
    return CollectorPorts(
        runtime=collect_runtime,
        postgresql=collect_postgresql,
        neo4j=collect_neo4j,
        predeploy=collect_predeploy,
        temporal=collect_temporal,
    )


def _safe_facts(
    value: Any,
    *,
    sensitive_values: frozenset[str],
    depth: int = 0,
    count: list[int] | None = None,
    max_items: int = MAX_FACT_ITEMS,
    max_list_items: int = 64,
) -> Any:
    if count is None:
        count = [0]
    count[0] += 1
    if count[0] > max_items or depth > 16:
        raise CollectionInputError("adapter facts exceed bounded structure")
    if value is None or type(value) in {bool, int, str}:
        if isinstance(value, str):
            if len(value) > 4096:
                raise CollectionInputError("adapter fact string exceeds bounded size")
            lowered = value.lower()
            if "-----begin private key" in lowered or "bearer " in lowered or re.search(r"\w+://[^/@\s]+:[^/@\s]+@", value):
                raise CollectionInputError("adapter facts contain authority material")
            if any(secret and secret in value for secret in sensitive_values):
                raise CollectionInputError("adapter facts reflect authority material")
        return value
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 128:
                raise CollectionInputError("adapter fact keys must be bounded strings")
            lowered = key.lower()
            if any(marker in lowered for marker in _SECRET_MARKERS):
                raise CollectionInputError("adapter facts contain a forbidden authority field")
            if any(secret and secret in key for secret in sensitive_values):
                raise CollectionInputError("adapter fact keys reflect authority material")
            result[key] = _safe_facts(
                item,
                sensitive_values=sensitive_values,
                depth=depth + 1,
                count=count,
                max_items=max_items,
                max_list_items=max_list_items,
            )
        return result
    if isinstance(value, (list, tuple)):
        if len(value) > max_list_items:
            raise CollectionInputError("adapter fact list exceeds bounded cardinality")
        return [
            _safe_facts(
                item,
                sensitive_values=sensitive_values,
                depth=depth + 1,
                count=count,
                max_items=max_items,
                max_list_items=max_list_items,
            )
            for item in value
        ]
    raise CollectionInputError("adapter facts must be finite JSON values")


def _normalize_result(
    name: str,
    result: Any,
    *,
    sensitive_values: frozenset[str] = frozenset(),
    max_fact_items: int = MAX_FACT_ITEMS,
    max_list_items: int = 64,
) -> dict[str, Any]:
    if type(result) is not AdapterResult or result.status not in ADAPTER_STATUSES:
        raise CollectionInputError("adapter returned an invalid result contract")
    codes = []
    for code in result.failure_codes:
        if not isinstance(code, str) or not _FAILURE_CODE.fullmatch(code):
            raise CollectionInputError("adapter returned an invalid failure code")
        codes.append(code)
    if len(codes) != len(set(codes)):
        raise CollectionInputError("adapter returned duplicate failure codes")
    facts = _safe_facts(
        result.facts,
        sensitive_values=sensitive_values,
        max_items=max_fact_items,
        max_list_items=max_list_items,
    )
    if not isinstance(facts, Mapping):
        raise CollectionInputError("adapter facts root must be an object")
    if result.status == "OBSERVED" and codes:
        raise CollectionInputError("observed adapter result cannot carry failures")
    if result.status != "OBSERVED" and not codes:
        raise CollectionInputError("non-observed adapter result requires a failure code")
    return {"status": result.status, "facts": facts, "failure_codes": sorted(codes)}


def _cross_source_target(
    binding_materials: Mapping[str, Mapping[str, Any]],
) -> tuple[str, str | None]:
    pg = binding_materials.get("postgresql")
    neo = binding_materials.get("neo4j")
    predeploy = binding_materials.get("predeploy")
    if not all(isinstance(item, Mapping) for item in (pg, neo, predeploy)):
        return "UNVERIFIED", None
    if (
        pg.get("system_identifier") is None
        or not isinstance(neo.get("database_id"), str)
        or not neo.get("database_id")
        or not isinstance(neo.get("database_name"), str)
        or predeploy.get("structural_receipt_identity_valid") is not True
        or not _exact_sha256(predeploy.get("target_sha256"))
    ):
        return "UNVERIFIED", None
    body = {
        "postgresql": dict(pg),
        "neo4j": dict(neo),
    }
    observed = _sha256(_canonical(body))
    runtime = binding_materials.get("runtime")
    runtime_matches = (
        not isinstance(runtime, Mapping)
        or (
            runtime.get("target_sha256") == predeploy.get("target_sha256")
            and runtime.get("operation_sha256") == predeploy.get("operation_sha256")
            and runtime.get("artifact_identity_sha256")
            == predeploy.get("artifact_identity_sha256")
            and runtime.get("predeploy_receipt_file_sha256")
            == predeploy.get("predeploy_receipt_file_sha256")
        )
    )
    return (
        "MATCHED_SEQUENTIAL"
        if (
            hmac.compare_digest(observed, str(predeploy["target_sha256"]))
            and runtime_matches
        )
        else "MISMATCH",
        observed,
    )


def _collect_live_evidence(
    request_value: Mapping[str, Any],
    *,
    request_file_sha256: str,
    ports: CollectorPorts | None = None,
    environ: Mapping[str, str] | None = None,
    now: Callable[[], datetime] | None = None,
    request_bytes_bound: bool,
) -> dict[str, Any]:
    request = validate_request(request_value)
    _sha(request_file_sha256, path="request_file_sha256")
    builtin_ports = ports is None
    ports = default_ports() if ports is None else ports
    if type(ports) is not CollectorPorts:
        raise CollectionInputError("ports must be a CollectorPorts value")
    environ = os.environ if environ is None else environ
    clock = (lambda: datetime.now(timezone.utc)) if now is None else now
    observed_at = clock()
    if not isinstance(observed_at, datetime) or observed_at.tzinfo is None:
        raise CollectionInputError("collector clock must return a timezone-aware datetime")
    observed_at = observed_at.astimezone(timezone.utc)
    adapters = request["adapters"]
    timeout = float(request["timeout_seconds"])
    deadline = time.monotonic() + timeout
    results: dict[str, Any] = {}
    binding_materials: dict[str, Mapping[str, Any]] = {}
    failures: list[str] = []
    for name in ADAPTER_NAMES:
        config = adapters[name]
        if config is None:
            result = AdapterResult(
                "NOT_CONFIGURED", {}, (f"{name}.not_configured",)
            )
            normalized = _normalize_result(name, result)
        else:
            port = getattr(ports, name)
            if (
                request["schema_version"] in {REQUEST_SCHEMA_V2, REQUEST_SCHEMA_V3}
                and name in {"postgresql", "neo4j"}
            ):
                config = {**dict(config), "challenge_nonce": request["challenge_nonce"]}
            adapter_environ = {
                key: environ[key]
                for key in _ADAPTER_ENV_KEYS[name]
                if key in environ
            }
            if name == "runtime":
                secret_keys = ()
            elif name == "postgresql":
                secret_keys = (POSTGRESQL_DSN_ENV,)
            elif name == "neo4j":
                secret_keys = (NEO4J_PASSWORD_ENV,)
            else:
                secret_keys = ()
            sensitive_values = frozenset(
                adapter_environ[key]
                for key in secret_keys
                if adapter_environ.get(key)
            )
            try:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise _PortUnavailable("collection deadline exhausted")
                result = port(config, remaining, adapter_environ)
                if (
                    builtin_ports
                    and type(result) is AdapterResult
                    and isinstance(result.binding_material, Mapping)
                ):
                    binding_materials[name] = result.binding_material
                normalized = _normalize_result(
                    name,
                    result,
                    sensitive_values=sensitive_values,
                    max_fact_items=(
                        MAX_RBAC_FACT_ITEMS
                        if request["schema_version"] in {REQUEST_SCHEMA_V2, REQUEST_SCHEMA_V3}
                        and name in {"postgresql", "neo4j"}
                        else MAX_FACT_ITEMS
                    ),
                    max_list_items=(
                        512
                        if request["schema_version"] in {REQUEST_SCHEMA_V2, REQUEST_SCHEMA_V3}
                        and name in {"postgresql", "neo4j"}
                        else 64
                    ),
                )
            except Exception:
                normalized = {
                    "status": "UNAVAILABLE",
                    "facts": {},
                    "failure_codes": [f"{name}.collection_failed"],
                }
        results[name] = normalized
        failures.extend(normalized["failure_codes"])
    cross_source_binding, observed_target_sha256 = _cross_source_target(binding_materials)
    if cross_source_binding == "MISMATCH":
        failures.append("cross_source.target_mismatch")
    complete = (
        all(results[name]["status"] == "OBSERVED" for name in ADAPTER_NAMES)
        and cross_source_binding != "MISMATCH"
    )
    body = {
        "schema_version": (
            EVIDENCE_SCHEMA_V2
            if request["schema_version"] == REQUEST_SCHEMA_V3
            else EVIDENCE_SCHEMA
        ),
        "status": "COLLECTION_COMPLETE" if complete else "COLLECTION_INCOMPLETE",
        "claim_boundary": CLAIM_BOUNDARY,
        "target_id": request["target_id"],
        "request_file_sha256": request_file_sha256,
        "request_bytes_bound": request_bytes_bound is True,
        "collector_profile": (
            (
                "builtin-read-only-v2"
                if request["schema_version"] == REQUEST_SCHEMA_V3
                else "builtin-read-only-v1"
            )
            if builtin_ports
            else "in-process-unattested"
        ),
        "verification_status": "UNVERIFIED",
        "snapshot_coherence": "UNATTESTED",
        "cross_source_binding": cross_source_binding,
        "observed_target_sha256": observed_target_sha256,
        "collected_at": observed_at.isoformat(),
        "adapter_order": list(ADAPTER_NAMES),
        "adapters": results,
        "collection_failures": sorted(set(failures)),
    }
    return {**body, "evidence_body_sha256": _sha256(_canonical(body))}


def collect_live_evidence(
    request_value: Mapping[str, Any],
    *,
    request_file_sha256: str,
    ports: CollectorPorts | None = None,
    environ: Mapping[str, str] | None = None,
    now: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Collect an in-process, explicitly byte-unbound observation bundle."""

    return _collect_live_evidence(
        request_value,
        request_file_sha256=request_file_sha256,
        ports=ports,
        environ=environ,
        now=now,
        request_bytes_bound=False,
    )


def collect_loaded_request(
    loaded: LoadedRequest,
    *,
    ports: CollectorPorts | None = None,
    environ: Mapping[str, str] | None = None,
    now: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Reparse immutable request bytes immediately before collecting evidence."""

    if type(loaded) is not LoadedRequest or not isinstance(loaded.raw, bytes):
        raise CollectionInputError("request must be a LoadedRequest value")
    _sha(loaded.file_sha256, path="loaded_request.file_sha256")
    if not hmac.compare_digest(_sha256(loaded.raw), loaded.file_sha256):
        raise CollectionInputError("loaded request bytes no longer match their SHA-256")
    value = _strict_json_loads(loaded.raw)
    if not isinstance(value, Mapping):
        raise CollectionInputError("request root must be an object")
    return _collect_live_evidence(
        value,
        request_file_sha256=loaded.file_sha256,
        ports=ports,
        environ=environ,
        now=now,
        request_bytes_bound=True,
    )


def _publish_once(path: Path, document: Mapping[str, Any]) -> str:
    if not path.is_absolute():
        raise CollectionInputError("--output must be an absolute path")
    parent = path.parent
    try:
        resolved_parent = parent.resolve(strict=True)
        parent_info = parent.lstat()
    except OSError as exc:
        raise CollectionInputError("output parent is unavailable") from exc
    if resolved_parent != parent or stat.S_ISLNK(parent_info.st_mode) or not stat.S_ISDIR(parent_info.st_mode):
        raise CollectionInputError("output parent must be a non-symlink directory")
    if parent_info.st_uid != os.geteuid() or parent_info.st_mode & 0o022:
        raise CollectionInputError(
            "output parent must be owner-controlled and not group/other writable"
        )
    raw = _canonical(document)
    if len(raw) > MAX_ARTIFACT_BYTES:
        raise CollectionInputError("output evidence exceeds bounded size")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    parent_fd = _open_verified_directory(
        parent, parent_info, error="output parent changed during open"
    )
    pending_name = f".{path.name}.pending.{os.getpid()}.{os.urandom(16).hex()}"
    pending_created = False
    published = False
    try:
        fd = os.open(pending_name, flags, 0o600, dir_fd=parent_fd)
        pending_created = True
        with os.fdopen(fd, "wb", closefd=True) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
            pending_info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(pending_info.st_mode)
            or stat.S_IMODE(pending_info.st_mode) != 0o600
            or pending_info.st_uid != os.geteuid()
            or pending_info.st_nlink != 1
            or pending_info.st_size != len(raw)
        ):
            raise CollectionInputError("pending output identity is unsafe")
        try:
            os.link(
                pending_name,
                path.name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except FileExistsError as exc:
            raise CollectionInputError("output already exists") from exc
        except OSError as exc:
            raise CollectionInputError("output cannot be published atomically") from exc
        published = True
        try:
            os.unlink(pending_name, dir_fd=parent_fd)
            pending_created = False
            os.fsync(parent_fd)
            read_flags = os.O_RDONLY
            if hasattr(os, "O_NOFOLLOW"):
                read_flags |= os.O_NOFOLLOW
            final_fd = os.open(path.name, read_flags, dir_fd=parent_fd)
            try:
                final_info = os.fstat(final_fd)
                observed = bytearray()
                while len(observed) <= len(raw):
                    chunk = os.read(final_fd, min(65536, len(raw) + 1 - len(observed)))
                    if not chunk:
                        break
                    observed.extend(chunk)
            finally:
                os.close(final_fd)
            if (
                final_info.st_dev != pending_info.st_dev
                or final_info.st_ino != pending_info.st_ino
                or final_info.st_nlink != 1
                or final_info.st_uid != os.geteuid()
                or stat.S_IMODE(final_info.st_mode) != 0o600
                or bytes(observed) != raw
            ):
                raise PublicationInDoubt(
                    "published output failed exact inode and byte readback"
                )
        except PublicationInDoubt:
            raise
        except OSError as exc:
            raise PublicationInDoubt(
                "published output durability or exact readback is in doubt"
            ) from exc
    finally:
        if pending_created:
            try:
                os.unlink(pending_name, dir_fd=parent_fd)
            except OSError:
                pass
        try:
            os.close(parent_fd)
        except OSError:
            if not published:
                raise
    return _sha256(raw)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Collect bounded read-only production-readiness observations. "
            "Collection status is never production approval or runtime L3."
        )
    )
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--request-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        loaded = load_request(args.request, args.request_sha256)
        evidence = collect_loaded_request(loaded)
        output_sha256 = _publish_once(args.output, evidence)
    except PublicationInDoubt as exc:
        print(
            json.dumps(
                {
                    "schema_version": ERROR_SCHEMA,
                    "status": "PUBLICATION_IN_DOUBT",
                    "error": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 3
    except (CollectionInputError, OSError) as exc:
        print(
            json.dumps(
                {"schema_version": ERROR_SCHEMA, "status": "INVALID", "error": str(exc)},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    receipt = {
        "schema_version": WRITE_RECEIPT_SCHEMA,
        "status": "WRITTEN",
        "collection_status": evidence["status"],
        "output_sha256": output_sha256,
    }
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0 if evidence["status"] == "COLLECTION_COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
