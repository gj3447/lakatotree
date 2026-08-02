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


REQUEST_SCHEMA = "lakatotree-production-readiness-collection-request/v1"
EVIDENCE_SCHEMA = "lakatotree-production-readiness-live-evidence/v1"
WRITE_RECEIPT_SCHEMA = "lakatotree-production-readiness-live-write-receipt/v1"
ERROR_SCHEMA = "lakatotree-production-readiness-live-error/v1"
MAX_REQUEST_BYTES = 64 * 1024
MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
MAX_RESPONSE_BYTES = 64 * 1024
MAX_HTTP_HEADER_BYTES = 16 * 1024
MAX_JSON_NESTING = 64
MAX_FACT_ITEMS = 256
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
_SERVICE_STATES = frozenset({"ok", "down", "degraded", "unknown"})
_SERVICE_NAMES = frozenset({"pg", "neo4j", "mongo"})
_AUTH_POSTURES = frozenset({"token_required", "loopback_only", "disabled"})
_FRESHNESS_STATES = frozenset({"on", "off"})
_PREDEPLOY_SCHEMA = "lakatotree-storage-predeploy-receipt/v4"
_STORAGE_CONTRACT = "lakatotree-storage-contract/v1"
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
    request = _exact_mapping(
        value,
        path="request",
        keys={"schema_version", "target_id", "timeout_seconds", "adapters"},
    )
    if request["schema_version"] != REQUEST_SCHEMA:
        raise CollectionInputError("request.schema_version is unsupported")
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
            keys={"base_url", "expected_git_sha"},
        )
        _validate_runtime_url(runtime["base_url"])
        git_sha = _text(
            runtime["expected_git_sha"],
            path="request.adapters.runtime.expected_git_sha",
            maximum=64,
        )
        if not (7 <= len(git_sha) <= 64 and all(char in _HEX for char in git_sha)):
            raise CollectionInputError(
                "request.adapters.runtime.expected_git_sha must be lowercase hexadecimal"
            )

    postgresql = adapters["postgresql"]
    if postgresql is not None:
        postgresql = _exact_mapping(
            postgresql,
            path="request.adapters.postgresql",
            keys={"database", "owner_role", "migrator_role", "runtime_role"},
        )
        _text(postgresql["database"], path="request.adapters.postgresql.database", maximum=63)
        for field in ("owner_role", "migrator_role", "runtime_role"):
            _role_name(postgresql[field], path=f"request.adapters.postgresql.{field}")

    neo4j = adapters["neo4j"]
    if neo4j is not None:
        neo4j = _exact_mapping(
            neo4j,
            path="request.adapters.neo4j",
            keys={"database"},
        )
        _text(neo4j["database"], path="request.adapters.neo4j.database", maximum=63)

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
    return (
        isinstance(observed, str)
        and 7 <= len(observed) <= 64
        and all(char in _HEX for char in observed)
        and (observed == expected or (len(observed) < len(expected) and expected.startswith(observed)))
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
    expected_git_sha = str(config["expected_git_sha"])
    observations: dict[str, tuple[int, bytes, Mapping[str, Any]]] = {}
    failures: list[str] = []
    deadline = time.monotonic() + timeout
    for name, path in (
        ("healthz", "/healthz"),
        ("readyz", "/readyz"),
        ("version", "/version"),
        ("outbox", "/api/ops/outbox-status"),
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
            "boot_matches_expected": _git_sha_match(boot_git_sha, expected_git_sha),
            "disk_matches_expected": _git_sha_match(disk_head_sha, expected_git_sha),
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
    return AdapterResult(
        "OBSERVED" if not failures else "PARTIAL",
        facts,
        tuple(sorted(failures)),
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
    psycopg2: Any, dsn: str, database: str
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
        ipaddress.ip_address(hostaddr)
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
            "options": "-c default_transaction_read_only=on",
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
            psycopg2, dsn, str(config["database"])
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
    cancel_timer = None
    failures: list[str] = []
    system_identifier = None
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
        connection.set_session(readonly=True, autocommit=False)
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('statement_timeout', %s, true)", (f"{max(1, int(remaining * 1000))}ms",))
            cursor.execute("SELECT current_database(), current_user, session_user, current_setting('transaction_read_only')")
            database, current_user, session_user, transaction_read_only = cursor.fetchone()
            cursor.execute(
                "SELECT inet_server_addr()::text, inet_server_port(), "
                "current_setting('server_version_num')"
            )
            server_address, server_port, server_version_num = cursor.fetchone()
            cursor.execute(
                "SELECT oid::text FROM pg_catalog.pg_database WHERE datname=current_database()"
            )
            database_oid = cursor.fetchone()[0]
            cursor.execute("SAVEPOINT readiness_cluster_identity")
            try:
                cursor.execute("SELECT system_identifier::text FROM pg_control_system()")
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
                "SELECT n.nspname || '.' || c.relname, c.relkind, pg_get_userbyid(c.relowner) "
                "FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='public' AND c.relname = ANY(%s) ORDER BY 1",
                ([name.split(".", 1)[1] for name in (*_PG_TABLES, *_PG_SEQUENCES)],),
            )
            object_rows = {row[0]: row for row in cursor.fetchall()}
            cursor.execute(
                "SELECT nspname, pg_get_userbyid(nspowner) FROM pg_catalog.pg_namespace WHERE nspname='public'"
            )
            schema_row = cursor.fetchone()
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
                (roles["runtime"],),
            )
            membership_digests = [
                _sha256(str(row[0]).encode("utf-8"))
                for row in _bounded_cursor_rows(cursor, maximum=64)
            ]
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
                " ) x WHERE d.datname=current_database()"
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
                "     CASE WHEN c.relkind='S' THEN 'S'::\"char\" ELSE 'r'::\"char\" END,"
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
            public_acl_entry_counts = {
                scope: sum(
                    1
                    for entry in acl_projection
                    if entry["scope"] == scope and entry["grantee"] == "public"
                )
                for scope in ("database", "schema", "relation", "sequence", "column")
            }
            if roles["runtime"] in role_rows:
                cursor.execute(
                    "SELECT has_database_privilege(%s, current_database(), 'CREATE'), "
                    "has_schema_privilege(%s, 'public', 'CREATE'), "
                    "has_schema_privilege(%s, 'public', 'USAGE')",
                    (roles["runtime"], roles["runtime"], roles["runtime"]),
                )
                database_create, schema_create, schema_usage = cursor.fetchone()
            else:
                database_create = schema_create = schema_usage = False

            objects: dict[str, Any] = {}
            for object_name in _PG_TABLES:
                row = object_rows.get(object_name)
                privileges: list[str] = []
                column_pairs: list[list[str]] = []
                if row is not None and roles["runtime"] in role_rows:
                    for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
                        cursor.execute(
                            "SELECT has_table_privilege(%s, %s, %s)",
                            (roles["runtime"], object_name, privilege),
                        )
                        if cursor.fetchone()[0] is True:
                            privileges.append(privilege)
                    cursor.execute(
                        "SELECT a.attname,"
                        " has_column_privilege(%s, c.oid, a.attnum, 'SELECT'),"
                        " has_column_privilege(%s, c.oid, a.attnum, 'INSERT'),"
                        " has_column_privilege(%s, c.oid, a.attnum, 'UPDATE'),"
                        " has_column_privilege(%s, c.oid, a.attnum, 'REFERENCES')"
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
                    "owner_class": _principal_class(row[2], roles) if row is not None else None,
                    "runtime_privileges": privileges,
                    "runtime_column_privilege_count": len(column_pairs),
                    "runtime_column_privilege_sha256": _sha256(_canonical(column_pairs)),
                    "runtime_column_only_privileges": column_only,
                }
            for object_name in _PG_SEQUENCES:
                row = object_rows.get(object_name)
                privileges = []
                if row is not None and roles["runtime"] in role_rows:
                    for privilege in ("SELECT", "USAGE", "UPDATE"):
                        cursor.execute(
                            "SELECT has_sequence_privilege(%s, %s, %s)",
                            (roles["runtime"], object_name, privilege),
                        )
                        if cursor.fetchone()[0] is True:
                            privileges.append(privilege)
                objects[object_name] = {
                    "exists": row is not None,
                    "owner_class": _principal_class(row[2], roles) if row is not None else None,
                    "runtime_privileges": privileges,
                }
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
        "current_actor_class": _principal_class(current_user, roles),
        "current_actor_sha256": _sha256(str(current_user).encode("utf-8")),
        "session_actor_sha256": _sha256(str(session_user).encode("utf-8")),
        "roles_distinct": len(set(roles.values())) == 3,
        "roles": role_facts,
        "objects": objects,
        "public_schema_owner_class": (
            _principal_class(schema_row[1], roles) if schema_row is not None else None
        ),
        "acl_projection_scope": "contract-objects-v1",
        "acl_projection_count": len(acl_projection),
        "acl_projection_sha256": _sha256(_canonical(acl_projection)),
        "public_acl_entry_counts": public_acl_entry_counts,
        "runtime_effective_role_sha256": membership_digests,
        "runtime_database_create": bool(database_create),
        "runtime_schema_create": bool(schema_create),
        "runtime_schema_usage": bool(schema_usage),
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


def _neo_rows(session: Any, query: str, timeout: float) -> list[dict[str, Any]]:
    from neo4j import Query

    rows: list[dict[str, Any]] = []
    for record in session.run(Query(query, timeout=timeout)):
        if len(rows) >= 64:
            raise _PortUnavailable("Neo4j readback exceeds bounded row count")
        rows.append(dict(record))
    return rows


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
        try:
            with driver.session(database="system", default_access_mode=READ_ACCESS) as session:
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
                        "SHOW USER PRIVILEGES YIELD access, action, resource, graph, segment "
                        "RETURN access, action, resource, graph, segment ORDER BY access, action, resource, graph, segment",
                        remaining(),
                    )
                except Exception:
                    failures.append("neo4j.effective_privileges.unavailable")
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
    facts = {
        "database": str(config["database"]),
        "database_name_matches": database_identity.get("name") == config["database"],
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
        "audit_principal_read_only": "UNVERIFIED",
        "read_query_count": 4,
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
    drain = body.get("writer_drain")
    live_fence = drain.get("live_fence") if isinstance(drain, Mapping) else None
    environment = body.get("environment")
    facts = {
        "file_sha256": _sha256(raw),
        "file_read_only": not bool(info.st_mode & 0o222),
        "schema_matches_expected": body.get("schema_version") == _PREDEPLOY_SCHEMA,
        "contract_matches_expected": body.get("contract_id") == _STORAGE_CONTRACT,
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
            "receipt_identity_valid": bool(
                facts["schema_matches_expected"]
                and facts["contract_matches_expected"]
                and facts["self_digest_valid"]
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
) -> Any:
    if count is None:
        count = [0]
    count[0] += 1
    if count[0] > MAX_FACT_ITEMS or depth > 16:
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
            )
        return result
    if isinstance(value, (list, tuple)):
        if len(value) > 64:
            raise CollectionInputError("adapter fact list exceeds bounded cardinality")
        return [
            _safe_facts(
                item,
                sensitive_values=sensitive_values,
                depth=depth + 1,
                count=count,
            )
            for item in value
        ]
    raise CollectionInputError("adapter facts must be finite JSON values")


def _normalize_result(
    name: str,
    result: Any,
    *,
    sensitive_values: frozenset[str] = frozenset(),
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
    facts = _safe_facts(result.facts, sensitive_values=sensitive_values)
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
        or predeploy.get("receipt_identity_valid") is not True
        or not _exact_sha256(predeploy.get("target_sha256"))
    ):
        return "UNVERIFIED", None
    body = {
        "postgresql": dict(pg),
        "neo4j": dict(neo),
    }
    observed = _sha256(_canonical(body))
    return (
        "MATCHED_SEQUENTIAL"
        if hmac.compare_digest(observed, str(predeploy["target_sha256"]))
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
                    name, result, sensitive_values=sensitive_values
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
        "schema_version": EVIDENCE_SCHEMA,
        "status": "COLLECTION_COMPLETE" if complete else "COLLECTION_INCOMPLETE",
        "claim_boundary": CLAIM_BOUNDARY,
        "target_id": request["target_id"],
        "request_file_sha256": request_file_sha256,
        "request_bytes_bound": request_bytes_bound is True,
        "collector_profile": (
            "builtin-read-only-v1" if builtin_ports else "in-process-unattested"
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
