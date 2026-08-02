"""Installable, target-bound predeploy coordinator for storage contract v1."""

from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import hmac
import importlib.metadata
import importlib.resources
import json
import os
import secrets
import shlex
import stat
import subprocess
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from lakatos.io.reconcile import validate_history_record
from server.settings import ServerSettings
from server.storage_contract import (
    CONTRACT_ID,
    inspect_neo_outbox_contract,
    inspect_pg_history_contract,
    pg_projection_rows,
)


DRAIN_SCHEMA = "lakatotree-writer-drain/v2"
RECEIPT_SCHEMA = "lakatotree-storage-predeploy-receipt/v4"
NORMALIZATION_RECEIPT_SCHEMA = (
    "lakatotree-neo4j-outbox-payload-normalization/v1"
)
NORMALIZATION_PROJECTION_DOMAIN = (
    b"lakatotree-neo4j-outbox-payload-projection/v1\0"
)
FENCE_VERIFICATION_SCHEMA = "lakatotree-writer-fence-verification/v2"
FENCE_SIGNATURE_DOMAIN = FENCE_VERIFICATION_SCHEMA.encode("ascii") + b"\0"
FENCE_EXECUTION_IDENTITY_SCHEMA = "lakatotree-fence-execution-identity/v1"
RESOURCE_PACKAGE = "server.storage_migrations"
PG_RESOURCE = "critique_history_v1.sql"
NEO_RESOURCE = "outbox_identity_v1.cypher"
NEO_CONNECTION_ACQUISITION_SECONDS = 2.0
NEO_LEASE_MARGIN_SECONDS = 2.0
FENCE_RESPONSE_FIELDS = {
    "schema_version", "active", "nonce", "environment", "target_sha256",
    "operation_sha256", "lease_id", "drain_receipt_sha256", "verified_at",
    "expires_at", "evidence_refs", "signature",
}


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _strict_json_loads(value: str | bytes | bytearray) -> Any:
    """Decode security-bound JSON while rejecting ambiguity and non-finite values."""

    def object_pairs(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON object key: {key!r}")
            result[key] = item
        return result

    def reject_constant(token: str):
        raise ValueError(f"non-finite JSON number is forbidden: {token}")

    return json.loads(
        value,
        object_pairs_hook=object_pairs,
        parse_constant=reject_constant,
    )


def _fence_signing_payload(body: dict[str, Any]) -> bytes:
    """Normative v2 Ed25519 message: schema domain, NUL, canonical JSON."""

    if not isinstance(body, dict) or "signature" in body:
        raise ValueError("fence signing body must exclude signature")
    return FENCE_SIGNATURE_DOMAIN + _canonical(body)


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _ed25519_public_key_bytes(value: Any) -> bytes:
    """Parse the deployment-pinned raw Ed25519 public key without normalization."""

    if not (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    ):
        raise ValueError(
            "writer-fence authority public key must be 32-byte lowercase hex"
        )
    return bytes.fromhex(value)


def _fence_authority_sha256(public_key_hex: Any) -> str:
    return _sha_bytes(_ed25519_public_key_bytes(public_key_hex))


def _verify_fence_response_signature(
    response: Any,
    public_key_hex: Any,
) -> dict[str, Any]:
    """Verify an exact signed response and return its signed JSON body."""

    if not isinstance(response, dict):
        raise RuntimeError("writer-fence verifier response must be an object")
    signature_hex = response.get("signature")
    if not (
        isinstance(signature_hex, str)
        and len(signature_hex) == 128
        and all(char in "0123456789abcdef" for char in signature_hex)
    ):
        raise RuntimeError("writer-fence verifier response lacks an Ed25519 signature")
    signed_body = dict(response)
    signed_body.pop("signature")
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "storage predeploy signature verification requires: "
            "pip install 'lakatotree[storage]'"
        ) from exc
    try:
        Ed25519PublicKey.from_public_bytes(
            _ed25519_public_key_bytes(public_key_hex)
        ).verify(bytes.fromhex(signature_hex), _fence_signing_payload(signed_body))
    except (InvalidSignature, ValueError) as exc:
        raise RuntimeError("writer-fence authority signature is invalid") from exc
    return signed_body


def _resource_bytes(name: str) -> bytes:
    return importlib.resources.files(RESOURCE_PACKAGE).joinpath(name).read_bytes()


def migration_sources(resources: dict[str, bytes] | None = None) -> dict[str, str]:
    resources = resources or {
        name: _resource_bytes(name) for name in (PG_RESOURCE, NEO_RESOURCE)
    }
    return {
        name: _sha_bytes(resources[name])
        for name in (PG_RESOURCE, NEO_RESOURCE)
    }


def _artifact_identity() -> dict[str, Any]:
    """Bind the operation to either an installed wheel RECORD or a clean Git commit."""

    root = Path(__file__).resolve().parents[1]
    if (root / ".git").exists():
        status = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=root, check=True, text=True, capture_output=True,
        )
        if status.stdout:
            raise RuntimeError("predeploy requires a clean committed Git worktree")
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True,
            text=True, capture_output=True,
        ).stdout.strip()
        if not re_full_sha(commit):
            raise RuntimeError("unable to bind predeploy to a full source commit")
        return {"kind": "git", "source_commit": commit}

    try:
        distribution = importlib.metadata.distribution("lakatotree")
        installed_manifest: dict[str, str] = {}
        record_verified = 0
        for item in distribution.files or ():
            # Bytecode is generated after installation and is not deployment
            # identity. Importing the app must not change its own fingerprint.
            if str(item).endswith(".pyc") or "__pycache__" in Path(str(item)).parts:
                continue
            path = distribution.locate_file(item)
            if not Path(path).is_file() or Path(path).is_symlink():
                raise RuntimeError(f"installed distribution file is missing/non-regular: {item}")
            content = Path(path).read_bytes()
            actual_sha256 = _sha_bytes(content)
            recorded = item.hash
            if recorded is not None:
                try:
                    digest = hashlib.new(recorded.mode, content).digest()
                except (TypeError, ValueError) as exc:
                    raise RuntimeError(f"unsupported RECORD hash for {item}") from exc
                encoded = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
                if not hmac.compare_digest(encoded, recorded.value):
                    raise RuntimeError(f"installed file fails RECORD verification: {item}")
                record_verified += 1
            item_path = Path(str(item))
            volatile_dist_info = (
                any(part.endswith(".dist-info") for part in item_path.parts)
                and item_path.name in {
                    "RECORD", "INSTALLER", "REQUESTED", "direct_url.json",
                }
            )
            if ".." not in item_path.parts and not volatile_dist_info:
                installed_manifest[str(item)] = actual_sha256
        module_item = "server/storage_predeploy.py"
        module_path = Path(distribution.locate_file(module_item)).resolve(strict=True)
        if module_path != Path(__file__).resolve() or module_item not in installed_manifest:
            raise RuntimeError("loaded storage coordinator is not from the identified wheel")
        return {
            "kind": "wheel-record",
            "version": distribution.version,
            "installed_manifest_sha256": _sha_bytes(_canonical(installed_manifest)),
            "record_verified_files": record_verified,
            "stable_files": len(installed_manifest),
        }
    except (FileNotFoundError, importlib.metadata.PackageNotFoundError):
        raise RuntimeError("installed wheel lacks a readable RECORD identity")


def re_full_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 40 and all(
        char in "0123456789abcdef" for char in value
    )


def operation_identity(
    artifact: dict[str, Any] | None = None,
    resources: dict[str, bytes] | None = None,
) -> dict[str, Any]:
    body = {
        "contract_id": CONTRACT_ID,
        "artifact": artifact or _artifact_identity(),
        "migration_sources": migration_sources(resources),
    }
    return {**body, "sha256": _sha_bytes(_canonical(body))}


def _safe_neo_uri(value: str | None) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeError("NEO4J_URI is required")
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port is not None else ""
    return urlunsplit((parsed.scheme, host + port, parsed.path, parsed.query, ""))


def _neo_query(
    driver: Any,
    query: str,
    *,
    timeout_seconds: float = 10.0,
    deadline: datetime | None = None,
    **params: Any,
) -> list[dict[str, Any]]:
    try:
        from neo4j import Query
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "storage predeploy requires the 'storage' or 'server' package extra"
        ) from exc
    with driver.session() as session:
        effective_timeout = timeout_seconds
        if deadline is not None:
            remaining = (
                deadline - datetime.now(timezone.utc)
            ).total_seconds() - (
                NEO_CONNECTION_ACQUISITION_SECONDS + NEO_LEASE_MARGIN_SECONDS
            )
            if remaining <= 0:
                raise RuntimeError(
                    "writer-fence lease expired before Neo4j query acquisition"
                )
            effective_timeout = min(effective_timeout, remaining)
        return session.run(
            Query(query, timeout=effective_timeout), **params
        ).data()


def _database_clients():
    try:
        import psycopg2
        from server.adapters.neo4j import LazyNeo4jDriver
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "storage predeploy requires: pip install 'lakatotree[storage]'"
        ) from exc
    return psycopg2, LazyNeo4jDriver


def target_identity(
    settings: ServerSettings,
    connection: Any,
    driver: Any,
) -> dict[str, Any]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT current_database() AS database, "
            "(SELECT oid::text FROM pg_database "
            " WHERE datname=current_database()) AS database_oid, "
            "inet_server_addr()::text AS server_address, "
            "inet_server_port() AS server_port, "
            "current_setting('server_version_num') AS server_version_num, "
            "(SELECT system_identifier::text FROM pg_control_system()) AS system_identifier"
        )
        names = [item.name if hasattr(item, "name") else item[0] for item in cursor.description]
        pg = dict(zip(names, cursor.fetchone(), strict=True))
    neo_rows = _neo_query(
        driver,
        "CALL db.info() YIELD id, name RETURN id, name",
    )
    if not (
        len(neo_rows) == 1
        and isinstance(neo_rows[0].get("id"), str)
        and neo_rows[0].get("id")
        and isinstance(neo_rows[0].get("name"), str)
    ):
        raise RuntimeError("Neo4j target lacks a stable db.info identity")
    configured_neo_database = settings.require_neo4j_database()
    if neo_rows[0]["name"] != configured_neo_database:
        raise RuntimeError("Neo4j db.info name differs from NEO4J_DATABASE")
    body = {
        "postgresql": {
            "configured_host": settings.pg_host,
            "configured_port": settings.pg_port,
            "configured_database": settings.pg_db,
            "database": pg["database"],
            "database_oid": pg["database_oid"],
            "server_address": pg["server_address"],
            "server_port": pg["server_port"],
            "server_version_num": pg["server_version_num"],
            "system_identifier": pg["system_identifier"],
        },
        "neo4j": {
            "configured_uri": _safe_neo_uri(settings.neo4j_uri),
            "configured_database": configured_neo_database,
            "database_id": neo_rows[0]["id"],
            "database_name": neo_rows[0]["name"],
        },
    }
    return {"sha256": _sha_bytes(_canonical(body)), "details": body}


def _parse_time(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def validate_drain_receipt(
    path: Path,
    environment: str,
    target_sha256: str,
    operation_sha256: str,
    now: datetime,
    *,
    expected_file_sha256: str | None = None,
) -> dict[str, Any]:
    raw = path.read_bytes()
    file_sha = _sha_bytes(raw)
    if expected_file_sha256 is not None and file_sha != expected_file_sha256:
        raise ValueError("writer-drain receipt changed during apply")
    doc = _strict_json_loads(raw)
    if not isinstance(doc, dict):
        raise ValueError("drain receipt must be an object")
    verified_at = _parse_time(doc.get("verified_at"), "verified_at")
    expires_at = _parse_time(doc.get("expires_at"), "expires_at")
    evidence = doc.get("evidence_refs")
    valid = (
        doc.get("schema_version") == DRAIN_SCHEMA
        and doc.get("environment") == environment
        and doc.get("contract_id") == CONTRACT_ID
        and doc.get("target_sha256") == target_sha256
        and doc.get("operation_sha256") == operation_sha256
        and isinstance(doc.get("lease_id"), str) and bool(doc.get("lease_id"))
        and doc.get("writers_drained") is True
        and type(doc.get("listener_count")) is int
        and doc.get("listener_count") == 0
        and type(doc.get("replica_count")) is int
        and doc.get("replica_count") == 0
        and isinstance(evidence, list) and bool(evidence)
        and all(isinstance(item, str) and item for item in evidence)
        and verified_at <= now < expires_at
        and (expires_at - verified_at).total_seconds() <= 900
        and (now - verified_at).total_seconds() <= 900
        and (expires_at - now).total_seconds() >= 10
    )
    if not valid:
        raise ValueError("writer-drain receipt is stale, incomplete, or target-mismatched")
    return {
        "sha256": file_sha,
        "schema_version": DRAIN_SCHEMA,
        "environment": environment,
        "lease_id": doc["lease_id"],
        "verified_at": verified_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "target_sha256": target_sha256,
        "operation_sha256": operation_sha256,
        "evidence_refs": list(evidence),
    }


def _revalidate_drain(
    path: Path,
    environment: str,
    target_sha: str,
    operation_sha: str,
    original_sha: str,
    fence_verifier: Path,
    fence_verifier_sha256: str,
    fence_public_key_hex: str,
) -> dict[str, Any]:
    drain = validate_drain_receipt(
        path, environment, target_sha, operation_sha,
        datetime.now(timezone.utc), expected_file_sha256=original_sha,
    )
    drain["live_fence"] = verify_live_fence(
        fence_verifier,
        fence_verifier_sha256,
        drain,
        fence_public_key_hex,
    )
    return drain


def _executable_bytes(path: Path, label: str) -> tuple[Path, bytes]:
    if not path.is_absolute():
        raise ValueError(f"{label} path must be absolute")
    resolved = path.resolve(strict=True)
    if (
        resolved != path
        or not resolved.is_file()
        or resolved.is_symlink()
        or not os.access(resolved, os.X_OK)
    ):
        raise ValueError(f"{label} must be an executable, non-symlink regular file")
    descriptor = os.open(resolved, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o111 == 0:
            raise ValueError(f"{label} descriptor is not executable and regular")
        with os.fdopen(os.dup(descriptor), "rb") as handle:
            return resolved, handle.read()
    finally:
        os.close(descriptor)


def fence_verifier_identity(executable: Path) -> dict[str, Any]:
    """Bind the verifier bytes and its direct shebang interpreter, if any."""

    resolved, verifier_bytes = _executable_bytes(executable, "fence verifier")
    first_line = verifier_bytes.splitlines()[0] if verifier_bytes else b""
    interpreter: dict[str, Any] | None = None
    if first_line.startswith(b"#!"):
        try:
            tokens = shlex.split(first_line[2:].decode("ascii").strip())
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError("fence verifier has an invalid shebang") from exc
        if tokens and Path(tokens[0]).name == "env":
            raise ValueError("fence verifier may not select its interpreter via env")
        if len(tokens) != 1:
            raise ValueError(
                "fence verifier shebang must name one direct absolute interpreter"
            )
        interpreter_path = Path(tokens[0])
        interpreter_resolved, interpreter_bytes = _executable_bytes(
            interpreter_path, "fence verifier interpreter"
        )
        interpreter = {
            "path": str(interpreter_resolved),
            "sha256": _sha_bytes(interpreter_bytes),
        }
    body = {
        "schema_version": FENCE_EXECUTION_IDENTITY_SCHEMA,
        "path": str(resolved),
        "verifier_content_sha256": _sha_bytes(verifier_bytes),
        "interpreter": interpreter,
    }
    return {**body, "sha256": _sha_bytes(_canonical(body))}


def verify_live_fence(
    executable: Path,
    expected_sha256: str,
    drain: dict[str, Any],
    authority_public_key_hex: str,
) -> dict[str, Any]:
    """Challenge a pinned external authority that owns the actual writer lease.

    The executable and direct interpreter hashes are defense in depth.  The
    authority is the Ed25519 signature: an altered interpreter closure may emit
    JSON, but it cannot mint a response for the fresh nonce without the remote
    lease authority's private key.
    """

    identity = fence_verifier_identity(executable)
    _resolved, verifier_bytes = _executable_bytes(executable, "fence verifier")
    if not (
        _exact_sha256(expected_sha256)
        and hmac.compare_digest(identity["sha256"], expected_sha256)
    ):
        raise ValueError("fence verifier execution identity hash mismatch")
    if identity["verifier_content_sha256"] != _sha_bytes(verifier_bytes):
        raise ValueError("fence verifier changed while establishing identity")
    nonce = secrets.token_hex(32)
    request = {
        "schema_version": FENCE_VERIFICATION_SCHEMA,
        "nonce": nonce,
        "environment": drain["environment"],
        "target_sha256": drain["target_sha256"],
        "operation_sha256": drain["operation_sha256"],
        "lease_id": drain["lease_id"],
        "drain_receipt_sha256": drain["sha256"],
    }
    # macOS mounts ``/dev/fd`` non-executable.  Execute an exact private copy
    # with a minimal environment; the configured pathname can change after this
    # point without changing the bytes that answer the nonce challenge.
    with tempfile.TemporaryDirectory(prefix="lakatotree-fence-") as temp_dir:
        temp_path = Path(temp_dir) / "verifier"
        temp_fd = os.open(
            temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o500
        )
        try:
            with os.fdopen(temp_fd, "wb", closefd=False) as handle:
                handle.write(verifier_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            os.fchmod(temp_fd, 0o500)
        finally:
            os.close(temp_fd)
        if _sha_bytes(temp_path.read_bytes()) != identity["verifier_content_sha256"]:
            raise RuntimeError("private fence verifier copy failed readback")
        completed = subprocess.run(
            [str(temp_path)],
            input=_canonical(request),
            capture_output=True,
            timeout=5,
            check=False,
            env={
                "PATH": "/usr/bin:/bin",
                "PYTHONPATH": "",
                "PYTHONNOUSERSITE": "1",
                "LANG": "C",
                "LC_ALL": "C",
            },
        )
    interpreter = identity.get("interpreter")
    if isinstance(interpreter, dict):
        _, interpreter_bytes = _executable_bytes(
            Path(interpreter["path"]), "fence verifier interpreter"
        )
        if _sha_bytes(interpreter_bytes) != interpreter.get("sha256"):
            raise RuntimeError("fence verifier interpreter changed during execution")
    if completed.returncode != 0 or completed.stderr:
        raise RuntimeError("external writer-fence verifier rejected the lease")
    try:
        response = _strict_json_loads(completed.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError("writer-fence verifier returned invalid JSON") from exc
    signed_response = _verify_fence_response_signature(
        response, authority_public_key_hex
    )
    now = datetime.now(timezone.utc)
    verified_at = _parse_time(
        signed_response.get("verified_at"), "fence.verified_at"
    )
    expires_at = _parse_time(
        signed_response.get("expires_at"), "fence.expires_at"
    )
    drain_verified_at = _parse_time(
        drain.get("verified_at"), "drain.verified_at"
    )
    drain_expires_at = _parse_time(
        drain.get("expires_at"), "drain.expires_at"
    )
    evidence = signed_response.get("evidence_refs")
    valid = (
        set(response) == FENCE_RESPONSE_FIELDS
        and signed_response.get("schema_version") == FENCE_VERIFICATION_SCHEMA
        and signed_response.get("active") is True
        and signed_response.get("nonce") == nonce
        and signed_response.get("environment") == request["environment"]
        and signed_response.get("target_sha256") == request["target_sha256"]
        and signed_response.get("operation_sha256") == request["operation_sha256"]
        and signed_response.get("lease_id") == request["lease_id"]
        and signed_response.get("drain_receipt_sha256") == request["drain_receipt_sha256"]
        and isinstance(evidence, list) and bool(evidence)
        and all(isinstance(item, str) and item for item in evidence)
        and verified_at <= now < expires_at
        and drain_verified_at <= verified_at
        and expires_at <= drain_expires_at
        and (now - verified_at).total_seconds() <= 30
        and (expires_at - now).total_seconds() >= 5
        and (expires_at - verified_at).total_seconds() <= 60
    )
    if not valid:
        raise RuntimeError("writer-fence verifier did not prove a current exact lease")
    return {
        "schema_version": FENCE_VERIFICATION_SCHEMA,
        "verifier_sha256": identity["sha256"],
        "verifier_content_sha256": identity["verifier_content_sha256"],
        "interpreter": identity["interpreter"],
        "authority_key_sha256": _fence_authority_sha256(
            authority_public_key_hex
        ),
        "signed_response": response,
        # Keep the authority's exact signed spelling.  Parsing above is for
        # temporal comparison only; normalizing Z or an offset here would make
        # the wrapper disagree with the signed body at runtime readback.
        "verified_at": signed_response["verified_at"],
        "expires_at": signed_response["expires_at"],
        "evidence_refs": list(evidence),
    }


def _migration_cypher(source: bytes) -> list[str]:
    lines = [
        line for line in source.decode("utf-8").splitlines()
        if not line.lstrip().startswith("//")
    ]
    return [
        statement.strip()
        for statement in "\n".join(lines).split(";")
        if statement.strip()
    ]


def _open_absolute_directory_no_symlinks(
    path: Path,
    *,
    create: bool,
    forbidden_identity: tuple[int, int] | None = None,
) -> int:
    """Open an absolute directory component-by-component without traversal.

    ``Path.resolve`` is only an observation and can race with a rename.  This
    helper instead walks from a trusted root descriptor and applies
    ``O_NOFOLLOW`` at every component.  The returned descriptor is the
    authority used to reserve the receipt leaf with ``openat`` semantics.
    """

    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("receipt directory must be absolute and contain no '..'")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(
        os, "O_CLOEXEC", 0
    )
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path.anchor, flags)
    try:
        if forbidden_identity is not None:
            root_info = os.fstat(descriptor)
            if (root_info.st_dev, root_info.st_ino) == forbidden_identity:
                raise ValueError(
                    "--receipt-out must be outside the source checkout"
                )
        for component in path.parts[1:]:
            try:
                child = os.open(
                    component, flags | nofollow, dir_fd=descriptor
                )
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(component, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    # A concurrent creator is acceptable only if the exact
                    # component now opens as a real directory below.
                    pass
                child = os.open(
                    component, flags | nofollow, dir_fd=descriptor
                )
            except OSError as exc:
                raise ValueError(
                    "receipt path parents must be non-symlink directories"
                ) from exc
            info = os.fstat(child)
            if not stat.S_ISDIR(info.st_mode):
                os.close(child)
                raise ValueError(
                    "receipt path parents must be non-symlink directories"
                )
            if (
                forbidden_identity is not None
                and (info.st_dev, info.st_ino) == forbidden_identity
            ):
                os.close(child)
                raise ValueError(
                    "--receipt-out must be outside the source checkout"
                )
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


class _ReceiptReservation:
    """Crash-released target lock plus an invisible, recoverable pending inode."""

    def __init__(self, path: Path):
        if not path.is_absolute():
            raise ValueError("--receipt-out must be an absolute path")
        if path.anchor != os.sep:
            raise ValueError("--receipt-out must use one canonical POSIX root")
        if ".." in path.parts:
            raise ValueError("--receipt-out may not contain '..'")
        if not path.name:
            raise ValueError("--receipt-out must name a receipt file")
        if path.name.startswith("."):
            raise ValueError("--receipt-out may not use the reserved dotfile namespace")

        checkout = Path(__file__).resolve().parents[1]
        checkout_info = checkout.stat()
        checkout_identity = self._identity(checkout_info)
        try:
            path.relative_to(checkout)
        except ValueError:
            pass
        else:
            raise ValueError("--receipt-out must be outside the source checkout")

        self.path = path
        self.parent_fd = _open_absolute_directory_no_symlinks(
            path.parent,
            create=True,
            forbidden_identity=checkout_identity,
        )
        parent_info = os.fstat(self.parent_fd)
        canonical_parent = path.parent.resolve(strict=True)
        if (
            canonical_parent != path.parent
            or self._identity(canonical_parent.stat())
                != self._identity(parent_info)
        ):
            os.close(self.parent_fd)
            self.parent_fd = -1
            raise ValueError("--receipt-out must use a canonical physical path")
        try:
            (canonical_parent / path.name).relative_to(checkout)
        except ValueError:
            pass
        else:
            os.close(self.parent_fd)
            self.parent_fd = -1
            raise ValueError("--receipt-out must be outside the source checkout")
        if (
            parent_info.st_uid != os.geteuid()
            or stat.S_IMODE(parent_info.st_mode) & 0o077
        ):
            os.close(self.parent_fd)
            self.parent_fd = -1
            raise ValueError(
                "receipt parent must be owned by the current user and private"
            )
        self.parent_identity = self._identity(parent_info)
        self.lock_name = f".{path.name}.lock"
        self.pending_name = (
            f".{path.name}.pending-{secrets.token_hex(16)}"
        )
        self.lock_fd = -1
        self.lock_identity: tuple[int, int] | None = None
        self.pending_fd = -1
        self.pending_identity: tuple[int, int] | None = None
        self.final_linked = False
        self.published = False
        try:
            lock_flags = (
                os.O_RDWR
                | os.O_CREAT
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0)
            )
            self.lock_fd = os.open(
                self.lock_name, lock_flags, 0o600, dir_fd=self.parent_fd
            )
            lock_info = os.fstat(self.lock_fd)
            if not (
                stat.S_ISREG(lock_info.st_mode)
                and lock_info.st_uid == os.geteuid()
                and lock_info.st_nlink == 1
                and stat.S_IMODE(lock_info.st_mode) & 0o077 == 0
            ):
                raise ValueError("receipt lock is not a private regular file")
            self.lock_identity = self._identity(lock_info)
            try:
                fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("receipt target is already reserved") from exc

            self._require_final_absent()
            self._recover_manifest_pending()
            self.pending_name = (
                f".{path.name}.pending-{secrets.token_hex(16)}"
            )
            self._write_lock_manifest(identity=None, probe=None)
            pending_flags = lock_flags | os.O_EXCL
            self.pending_fd = os.open(
                self.pending_name,
                pending_flags,
                0o600,
                dir_fd=self.parent_fd,
            )
            pending_info = os.fstat(self.pending_fd)
            if not (
                stat.S_ISREG(pending_info.st_mode)
                and pending_info.st_uid == os.geteuid()
                and pending_info.st_nlink == 1
                and stat.S_IMODE(pending_info.st_mode) & 0o077 == 0
            ):
                raise ValueError("receipt pending inode is not private and regular")
            self.pending_identity = self._identity(pending_info)
            self._write_lock_manifest(identity=self.pending_identity, probe=None)
            self._preflight_publication_primitives()
            os.fsync(self.parent_fd)
            self.verify(expect_empty=True)
        except PermissionError as exc:
            self.abort(suppress_errors=True)
            raise ValueError("receipt parent is not writable") from exc
        except BaseException:
            self.abort(suppress_errors=True)
            raise

    @staticmethod
    def _identity(info: os.stat_result) -> tuple[int, int]:
        return (info.st_dev, info.st_ino)

    def _require_final_absent(self) -> None:
        try:
            os.stat(
                self.path.name,
                dir_fd=self.parent_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return
        raise FileExistsError(f"receipt already exists: {self.path}")

    def _write_all_at(self, descriptor: int, payload: bytes) -> None:
        os.ftruncate(descriptor, 0)
        offset = 0
        view = memoryview(payload)
        while offset < len(view):
            written = os.pwrite(descriptor, view[offset:], offset)
            if written <= 0:
                raise RuntimeError("receipt sidecar write made no progress")
            offset += written
        os.fsync(descriptor)

    def _write_lock_manifest(
        self,
        *,
        identity: tuple[int, int] | None,
        probe: str | None,
    ) -> None:
        manifest = {
            "schema_version": "lakatotree-receipt-reservation/v1",
            "target": self.path.name,
            "pending": self.pending_name,
            "identity": list(identity) if identity is not None else None,
            "probe": probe,
        }
        self._write_all_at(self.lock_fd, _canonical(manifest) + b"\n")

    def _clear_lock_manifest(self) -> None:
        self._write_all_at(self.lock_fd, b"")

    def _recover_manifest_pending(self) -> None:
        """Remove only the exact crash orphan named by this target's sidecar."""

        lock_info = os.fstat(self.lock_fd)
        if lock_info.st_size == 0:
            return
        if lock_info.st_size > 4096:
            self._clear_lock_manifest()
            return
        raw = os.pread(self.lock_fd, lock_info.st_size, 0)
        try:
            manifest = _strict_json_loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            # The sidecar is only a deletion capability.  A torn hint must not
            # authorize cleanup, but it must not permanently brick this target.
            self._clear_lock_manifest()
            return
        if not isinstance(manifest, dict) or set(manifest) != {
            "schema_version", "target", "pending", "identity", "probe"
        }:
            self._clear_lock_manifest()
            return
        pending = manifest.get("pending")
        prefix = f".{self.path.name}.pending-"
        suffix = pending[len(prefix):] if isinstance(pending, str) else ""
        probe = manifest.get("probe")
        probe_prefix = f".{self.path.name}.probe-"
        probe_suffix = (
            probe[len(probe_prefix):] if isinstance(probe, str) else ""
        )
        probe_ok = probe is None or (
            isinstance(probe, str)
            and probe.startswith(probe_prefix)
            and len(probe_suffix) == 32
            and all(char in "0123456789abcdef" for char in probe_suffix)
        )
        identity = manifest.get("identity")
        identity_ok = identity is None or (
            isinstance(identity, list)
            and len(identity) == 2
            and all(type(item) is int and item >= 0 for item in identity)
        )
        if (
            manifest.get("schema_version")
                != "lakatotree-receipt-reservation/v1"
            or manifest.get("target") != self.path.name
            or not isinstance(pending, str)
            or not pending.startswith(prefix)
            or len(suffix) != 32
            or any(char not in "0123456789abcdef" for char in suffix)
            or not identity_ok
            or not probe_ok
        ):
            self._clear_lock_manifest()
            return
        try:
            leaf = os.stat(
                pending,
                dir_fd=self.parent_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            self._clear_lock_manifest()
            return
        observed_identity = self._identity(leaf)
        if (
            not stat.S_ISREG(leaf.st_mode)
            or leaf.st_uid != os.geteuid()
            or leaf.st_nlink < 1
            or stat.S_IMODE(leaf.st_mode) & 0o077
            or (identity is not None and tuple(identity) != observed_identity)
        ):
            self._clear_lock_manifest()
            return
        if probe is not None:
            try:
                probe_leaf = os.stat(
                    probe,
                    dir_fd=self.parent_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                pass
            else:
                if (
                    stat.S_ISREG(probe_leaf.st_mode)
                    and probe_leaf.st_uid == os.geteuid()
                    and self._identity(probe_leaf) == observed_identity
                ):
                    os.unlink(probe, dir_fd=self.parent_fd)
        os.unlink(pending, dir_fd=self.parent_fd)
        os.fsync(self.parent_fd)
        self._clear_lock_manifest()

    def _preflight_publication_primitives(self) -> None:
        """Prove chmod and hard-link publication work before any DB mutation."""

        probe_name = f".{self.path.name}.probe-{secrets.token_hex(16)}"
        linked = False
        try:
            os.fchmod(self.pending_fd, 0o400)
            os.fsync(self.pending_fd)
            if stat.S_IMODE(os.fstat(self.pending_fd).st_mode) != 0o400:
                raise RuntimeError("receipt filesystem did not preserve read-only mode")
            os.fchmod(self.pending_fd, 0o600)
            os.fsync(self.pending_fd)
            if stat.S_IMODE(os.fstat(self.pending_fd).st_mode) != 0o600:
                raise RuntimeError("receipt filesystem did not restore private mode")
            self._write_lock_manifest(
                identity=self.pending_identity,
                probe=probe_name,
            )
            os.link(
                self.pending_name,
                probe_name,
                src_dir_fd=self.parent_fd,
                dst_dir_fd=self.parent_fd,
                follow_symlinks=False,
            )
            linked = True
            probe_info = os.stat(
                probe_name,
                dir_fd=self.parent_fd,
                follow_symlinks=False,
            )
            if (
                self._identity(probe_info) != self.pending_identity
                or os.fstat(self.pending_fd).st_nlink != 2
            ):
                raise RuntimeError("receipt filesystem hard-link probe diverged")
        except OSError as exc:
            raise ValueError(
                "receipt filesystem lacks durable chmod/hard-link support"
            ) from exc
        finally:
            if linked:
                os.unlink(probe_name, dir_fd=self.parent_fd)
                os.fsync(self.parent_fd)
                self._write_lock_manifest(
                    identity=self.pending_identity,
                    probe=None,
                )
        if os.fstat(self.pending_fd).st_nlink != 1:
            raise RuntimeError("receipt filesystem hard-link cleanup diverged")

    def verify(self, *, expect_empty: bool) -> None:
        if (
            self.lock_fd < 0
            or self.lock_identity is None
            or self.pending_fd < 0
            or self.pending_identity is None
        ):
            raise RuntimeError("receipt reservation is closed")
        reopened = _open_absolute_directory_no_symlinks(
            self.path.parent, create=False
        )
        try:
            if self._identity(os.fstat(reopened)) != self.parent_identity:
                raise RuntimeError("receipt parent identity changed after reservation")
        finally:
            os.close(reopened)
        parent_info = os.fstat(self.parent_fd)
        lock_info = os.fstat(self.lock_fd)
        pending_info = os.fstat(self.pending_fd)
        try:
            lock_leaf = os.stat(
                self.lock_name,
                dir_fd=self.parent_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("receipt reservation lock disappeared") from exc
        try:
            pending_leaf = os.stat(
                self.pending_name,
                dir_fd=self.parent_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("receipt pending inode disappeared") from exc
        if (
            self._identity(parent_info) != self.parent_identity
            or parent_info.st_uid != os.geteuid()
            or stat.S_IMODE(parent_info.st_mode) & 0o077
            or self._identity(lock_info) != self.lock_identity
            or self._identity(lock_leaf) != self.lock_identity
            or self._identity(pending_info) != self.pending_identity
            or self._identity(pending_leaf) != self.pending_identity
            or not stat.S_ISREG(lock_info.st_mode)
            or not stat.S_ISREG(pending_info.st_mode)
            or lock_info.st_uid != os.geteuid()
            or pending_info.st_uid != os.geteuid()
            or stat.S_IMODE(lock_info.st_mode) & 0o077
            or (
                expect_empty
                and stat.S_IMODE(pending_info.st_mode) & 0o077
            )
            or (
                not expect_empty
                and pending_info.st_mode & 0o222
            )
            or lock_info.st_nlink != 1
            or pending_info.st_nlink != 1
        ):
            raise RuntimeError("receipt reservation identity changed")
        self._require_final_absent()
        if expect_empty and pending_info.st_size != 0:
            raise RuntimeError("receipt reservation was modified before publication")

    def publish(self, document: dict[str, Any]) -> None:
        self.verify(expect_empty=True)
        body = dict(document)
        sealed = {**body, "receipt_sha256": _sha_bytes(_canonical(body))}
        payload = json.dumps(
            sealed, ensure_ascii=False, sort_keys=True, indent=2
        ).encode("utf-8") + b"\n"
        view = memoryview(payload)
        offset = 0
        while offset < len(view):
            written = os.write(self.pending_fd, view[offset:])
            if written <= 0:
                raise RuntimeError("receipt reservation write made no progress")
            offset += written
        os.fsync(self.pending_fd)
        os.fchmod(self.pending_fd, 0o400)
        os.fsync(self.pending_fd)
        self.verify(expect_empty=False)
        if os.pread(self.pending_fd, len(payload) + 1, 0) != payload:
            raise RuntimeError("published receipt failed exact descriptor readback")
        os.link(
            self.pending_name,
            self.path.name,
            src_dir_fd=self.parent_fd,
            dst_dir_fd=self.parent_fd,
            follow_symlinks=False,
        )
        self.final_linked = True
        final_info = os.stat(
            self.path.name,
            dir_fd=self.parent_fd,
            follow_symlinks=False,
        )
        if (
            self._identity(final_info) != self.pending_identity
            or not stat.S_ISREG(final_info.st_mode)
            or final_info.st_size != len(payload)
            or final_info.st_mode & 0o222
        ):
            raise RuntimeError("published receipt failed exact final-link readback")
        os.unlink(self.pending_name, dir_fd=self.parent_fd)
        self._clear_lock_manifest()
        os.fsync(self.parent_fd)
        self.published = True

    def read_published(self) -> bytes:
        if not self.published or self.pending_fd < 0:
            raise RuntimeError("receipt has not been published")
        reopened = _open_absolute_directory_no_symlinks(
            self.path.parent, create=False
        )
        try:
            if self._identity(os.fstat(reopened)) != self.parent_identity:
                raise RuntimeError("receipt parent identity changed after publication")
        finally:
            os.close(reopened)
        descriptor_info = os.fstat(self.pending_fd)
        final_info = os.stat(
            self.path.name,
            dir_fd=self.parent_fd,
            follow_symlinks=False,
        )
        if (
            self._identity(descriptor_info) != self.pending_identity
            or self._identity(final_info) != self.pending_identity
            or descriptor_info.st_nlink != 1
            or final_info.st_nlink != 1
            or final_info.st_mode & 0o222
        ):
            raise RuntimeError("published receipt identity changed")
        return os.pread(self.pending_fd, descriptor_info.st_size + 1, 0)

    def abort(self, *, suppress_errors: bool = False) -> None:
        if self.parent_fd < 0:
            self.close()
            return
        cleanup_error: OSError | None = None
        try:
            if self.pending_fd >= 0 and self.pending_identity is not None:
                try:
                    leaf = os.stat(
                        self.pending_name,
                        dir_fd=self.parent_fd,
                        follow_symlinks=False,
                    )
                except FileNotFoundError:
                    pass
                else:
                    if self._identity(leaf) == self.pending_identity:
                        os.unlink(self.pending_name, dir_fd=self.parent_fd)
                        os.fsync(self.parent_fd)
                        self._clear_lock_manifest()
        except OSError as exc:
            cleanup_error = exc
        finally:
            self.close()
        if cleanup_error is not None and not suppress_errors:
            raise RuntimeError("failed to clean receipt pending inode") from cleanup_error

    def close(self) -> None:
        if self.pending_fd >= 0:
            os.close(self.pending_fd)
            self.pending_fd = -1
        if self.lock_fd >= 0:
            try:
                fcntl.flock(self.lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(self.lock_fd)
                self.lock_fd = -1
        if self.parent_fd >= 0:
            os.close(self.parent_fd)
            self.parent_fd = -1

    def __enter__(self) -> "_ReceiptReservation":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if exc_type is None and self.published:
            self.close()
        else:
            self.abort(suppress_errors=exc_type is not None)
        return False


def _reserve_receipt_path(path: Path) -> _ReceiptReservation:
    return _ReceiptReservation(path)


def _publish_once(path: Path, document: dict[str, Any]) -> None:
    with _reserve_receipt_path(path) as reservation:
        reservation.publish(document)


def _exact_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        char in "0123456789abcdef" for char in value
    )


def _valid_payload_normalization_receipt(value: Any) -> bool:
    """Validate the exact, privacy-minimal normalization attestation shape."""

    if not isinstance(value, dict) or set(value) != {
        "schema_version", "before", "after", "updated_count",
    }:
        return False
    if value.get("schema_version") != NORMALIZATION_RECEIPT_SCHEMA:
        return False
    updated_count = value.get("updated_count")
    if type(updated_count) is not int or updated_count < 0:
        return False
    snapshots = []
    for name in ("before", "after"):
        snapshot = value.get(name)
        if not isinstance(snapshot, dict) or set(snapshot) != {
            "row_count", "projection_sha256",
        }:
            return False
        row_count = snapshot.get("row_count")
        if type(row_count) is not int or row_count < 0:
            return False
        if not _exact_sha256(snapshot.get("projection_sha256")):
            return False
        snapshots.append(snapshot)
    before, after = snapshots
    if before["row_count"] != after["row_count"]:
        return False
    if updated_count > before["row_count"]:
        return False
    hashes_equal = hmac.compare_digest(
        before["projection_sha256"], after["projection_sha256"]
    )
    return hashes_equal if updated_count == 0 else not hashes_equal


def verify_predeploy_receipt(
    path: Path,
    expected_file_sha256: str,
    settings: ServerSettings,
    connection: Any,
    driver: Any,
) -> dict[str, Any]:
    """Bind a deployed receipt to this artifact and these live stores.

    The self-digest detects accidental edits. The independently configured raw
    file SHA is the deployment authority; without it, a replacement JSON file
    could simply carry a recomputed self-digest.
    """

    if not path.is_absolute():
        raise ValueError("predeploy receipt path must be absolute")
    resolved = path.resolve(strict=True)
    if resolved != path or not resolved.is_file() or resolved.is_symlink():
        raise ValueError("predeploy receipt must be a non-symlink regular file")
    if resolved.stat().st_mode & 0o222:
        raise ValueError("predeploy receipt must be read-only")
    if not _exact_sha256(expected_file_sha256):
        raise ValueError("predeploy receipt file SHA-256 is missing or malformed")
    raw = resolved.read_bytes()
    file_sha = _sha_bytes(raw)
    if not hmac.compare_digest(file_sha, expected_file_sha256):
        raise ValueError("predeploy receipt file SHA-256 mismatch")
    try:
        document = _strict_json_loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("predeploy receipt is not valid JSON") from exc
    if not isinstance(document, dict):
        raise ValueError("predeploy receipt must be an object")
    body = dict(document)
    self_digest = body.pop("receipt_sha256", None)
    if not (
        _exact_sha256(self_digest)
        and hmac.compare_digest(self_digest, _sha_bytes(_canonical(body)))
    ):
        raise ValueError("predeploy receipt self-digest mismatch")

    artifact = _artifact_identity()
    operation = operation_identity(artifact)
    target = target_identity(settings, connection, driver)
    if not (
        body.get("schema_version") == RECEIPT_SCHEMA
        and body.get("contract_id") == CONTRACT_ID
        and isinstance(body.get("environment"), str)
        and bool(body.get("environment"))
        and body.get("environment") == settings.storage_environment
        and body.get("artifact") == artifact
        and body.get("operation") == operation
        and body.get("target_sha256") == target["sha256"]
        and body.get("target") == target["details"]
    ):
        raise ValueError("predeploy receipt is artifact-, operation-, or target-mismatched")

    created_at = _parse_time(body.get("created_at"), "created_at")
    drain = body.get("writer_drain")
    if not isinstance(drain, dict):
        raise ValueError("predeploy receipt lacks writer-drain evidence")
    drain_verified = _parse_time(drain.get("verified_at"), "writer_drain.verified_at")
    drain_expires = _parse_time(drain.get("expires_at"), "writer_drain.expires_at")
    live = drain.get("live_fence")
    if not isinstance(live, dict):
        raise ValueError("predeploy receipt lacks live writer-fence evidence")
    live_verified = _parse_time(live.get("verified_at"), "live_fence.verified_at")
    live_expires = _parse_time(live.get("expires_at"), "live_fence.expires_at")
    drain_evidence = drain.get("evidence_refs")
    live_evidence = live.get("evidence_refs")
    signed_response = live.get("signed_response")
    try:
        signed_body = _verify_fence_response_signature(
            signed_response, settings.storage_fence_public_key_hex
        )
        authority_key_sha256 = _fence_authority_sha256(
            settings.storage_fence_public_key_hex
        )
    except (RuntimeError, ValueError) as exc:
        raise ValueError(
            "predeploy receipt lacks a valid writer-fence authority signature"
        ) from exc
    signed_fence_valid = (
        isinstance(signed_response, dict)
        and set(signed_response) == FENCE_RESPONSE_FIELDS
        and signed_body.get("schema_version") == FENCE_VERIFICATION_SCHEMA
        and signed_body.get("active") is True
        and isinstance(signed_body.get("nonce"), str)
        and len(signed_body.get("nonce")) == 64
        and all(char in "0123456789abcdef" for char in signed_body["nonce"])
        and signed_body.get("environment") == body["environment"]
        and signed_body.get("target_sha256") == target["sha256"]
        and signed_body.get("operation_sha256") == operation["sha256"]
        and signed_body.get("lease_id") == drain.get("lease_id")
        and signed_body.get("drain_receipt_sha256") == drain.get("sha256")
        and signed_body.get("verified_at") == live.get("verified_at")
        and signed_body.get("expires_at") == live.get("expires_at")
        and signed_body.get("evidence_refs") == live_evidence
    )
    historical_fence_valid = (
        drain.get("schema_version") == DRAIN_SCHEMA
        and drain.get("environment") == body["environment"]
        and drain.get("target_sha256") == target["sha256"]
        and drain.get("operation_sha256") == operation["sha256"]
        and isinstance(drain.get("lease_id"), str) and bool(drain.get("lease_id"))
        and _exact_sha256(drain.get("sha256"))
        and isinstance(drain_evidence, list) and bool(drain_evidence)
        and all(isinstance(item, str) and item for item in drain_evidence)
        and live.get("schema_version") == FENCE_VERIFICATION_SCHEMA
        and _exact_sha256(live.get("verifier_sha256"))
        and live.get("verifier_sha256") == settings.storage_fence_verifier_sha256
        and live.get("authority_key_sha256") == authority_key_sha256
        and signed_fence_valid
        and isinstance(live_evidence, list) and bool(live_evidence)
        and all(isinstance(item, str) and item for item in live_evidence)
        and drain_verified <= live_verified <= created_at < live_expires <= drain_expires
        and (drain_expires - drain_verified).total_seconds() <= 900
        and (live_expires - live_verified).total_seconds() <= 60
        and created_at <= datetime.now(timezone.utc) + timedelta(seconds=5)
    )
    if not historical_fence_valid:
        raise ValueError("predeploy receipt has incoherent historical fence evidence")

    pg = body.get("postgresql")
    neo = body.get("neo4j")
    if not (
        isinstance(pg, dict) and pg.get("ok") is True
        and isinstance(pg.get("report"), dict)
        and pg["report"].get("contract_id") == CONTRACT_ID
        and pg["report"].get("ok") is True
        and pg["report"].get("failures") == []
        and isinstance(neo, dict) and neo.get("migration_ok") is True
        and _valid_payload_normalization_receipt(
            neo.get("payload_normalization")
        )
        and isinstance(neo.get("report"), dict)
        and neo["report"].get("contract_id") == CONTRACT_ID
        and (
            (
                neo["report"].get("ok") is True
                and neo["report"].get("failures") == []
                and neo.get("ok") is True
            )
            or (
                neo["report"].get("ok") is False
                and neo["report"].get("failures")
                    == ["neo4j.outbox.pending"]
                and neo.get("ok") is False
            )
        )
    ):
        raise ValueError("predeploy receipt lacks exact postflight success readback")
    return {
        "ok": True,
        "contract_id": CONTRACT_ID,
        "file_sha256": file_sha,
        "receipt_sha256": self_digest,
        "environment": body["environment"],
        "created_at": created_at.isoformat(),
        "target_sha256": target["sha256"],
        "operation_sha256": operation["sha256"],
    }


def _bounded_pg_migration(
    connection: Any,
    expires_at: str,
    source: bytes,
) -> None:
    deadline = _parse_time(expires_at, "expires_at")
    remaining = (deadline - datetime.now(timezone.utc)).total_seconds() - 5
    if remaining < 5:
        raise ValueError("writer-drain lease has insufficient time for PostgreSQL migration")
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('lock_timeout', %s, false)",
                       (f"{max(1000, min(int(remaining * 1000), 30000))}ms",))
        cursor.execute("SELECT set_config('statement_timeout', %s, false)",
                       (f"{max(1000, int(remaining * 1000))}ms",))
    timer = threading.Timer(remaining, connection.cancel)
    timer.daemon = True
    timer.start()
    try:
        with connection.cursor() as cursor:
            cursor.execute(source.decode("utf-8"))
    finally:
        timer.cancel()


def _bounded_neo_migration(driver: Any, expires_at: str, source: bytes) -> None:
    deadline = _parse_time(expires_at, "expires_at")
    headroom = (deadline - datetime.now(timezone.utc)).total_seconds()
    query_budget = headroom - (
        NEO_CONNECTION_ACQUISITION_SECONDS + NEO_LEASE_MARGIN_SECONDS
    )
    if query_budget < 5:
        raise ValueError("writer-fence lease has insufficient time for Neo4j migration")
    for statement in _migration_cypher(source):
        _neo_query(
            driver,
            statement,
            timeout_seconds=query_budget,
            deadline=deadline,
        )


_OUTBOX_NORMALIZATION_SCAN = (
    "MATCH (o:OutboxEntry) RETURN o.id AS id, o.tree AS tree, o.op AS op, "
    "o.node_tag AS node_tag, o.payload AS payload ORDER BY o.id"
)


def _neo_payload_normalization_snapshot(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Commit to the exact projected rows without copying payloads into a receipt."""

    projection = []
    seen_ids = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Neo4j outbox normalization row must be an object")
        row_id = row.get("id")
        tree = row.get("tree")
        op = row.get("op")
        node_tag = row.get("node_tag")
        payload = row.get("payload")
        if not isinstance(row_id, str) or not row_id or row_id in seen_ids:
            raise ValueError("Neo4j outbox normalization IDs must be unique strings")
        if not isinstance(tree, str) or not tree:
            raise ValueError("Neo4j outbox normalization tree must be a string")
        if not isinstance(op, str) or not op:
            raise ValueError("Neo4j outbox normalization op must be a string")
        if node_tag is not None and not isinstance(node_tag, str):
            raise ValueError("Neo4j outbox normalization node_tag must be string or null")
        if not isinstance(payload, str):
            raise ValueError("Neo4j outbox normalization payload must be a string")
        seen_ids.add(row_id)
        projection.append([row_id, tree, op, node_tag, payload])
    projection.sort(key=lambda item: item[0])
    return {
        "row_count": len(projection),
        "projection_sha256": _sha_bytes(
            NORMALIZATION_PROJECTION_DOMAIN + _canonical(projection)
        ),
    }


def _neo_payload_normalization_plan(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dry-run the exact strict decode and canonicalization used by the mutation."""

    updates = []
    for row in rows:
        raw_payload = row.get("payload")
        payload = _strict_json_loads(raw_payload)
        canonical_payload = validate_history_record(
            row.get("tree"),
            row.get("op"),
            row.get("node_tag"),
            payload,
            row.get("id"),
        )
        if raw_payload != canonical_payload:
            updates.append({
                "id": row.get("id"),
                "raw_payload": raw_payload,
                "canonical_payload": canonical_payload,
            })
    return updates


def _bounded_neo_payload_normalization(
    driver: Any, expires_at: str
) -> dict[str, Any]:
    """Canonicalize legacy JSON and attest an exact post-mutation rescan."""

    deadline = _parse_time(expires_at, "expires_at")
    query_budget = (deadline - datetime.now(timezone.utc)).total_seconds() - (
        NEO_CONNECTION_ACQUISITION_SECONDS + NEO_LEASE_MARGIN_SECONDS
    )
    if query_budget < 5:
        raise ValueError(
            "writer-fence lease has insufficient time for Neo4j normalization"
        )
    rows = _neo_query(
        driver, _OUTBOX_NORMALIZATION_SCAN,
        timeout_seconds=query_budget, deadline=deadline,
    )
    updates = _neo_payload_normalization_plan(rows)
    before = _neo_payload_normalization_snapshot(rows)
    if updates:
        result = _neo_query(
            driver,
            "UNWIND $rows AS row "
            "MATCH (o:OutboxEntry {id:row.id}) "
            "WHERE o.payload=row.raw_payload "
            "SET o.payload=row.canonical_payload "
            "RETURN count(o) AS updated",
            rows=updates,
            timeout_seconds=query_budget,
            deadline=deadline,
        )
        updated = result[0].get("updated") if len(result) == 1 else None
        if type(updated) is not int or updated != len(updates):
            raise RuntimeError("Neo4j outbox normalization lost exact CAS authority")

    canonical_by_id = {
        update["id"]: update["canonical_payload"] for update in updates
    }
    expected_rows = [
        {
            **row,
            "payload": canonical_by_id.get(row["id"], row["payload"]),
        }
        for row in rows
    ]
    after_rows = _neo_query(
        driver, _OUTBOX_NORMALIZATION_SCAN,
        timeout_seconds=query_budget, deadline=deadline,
    )
    after = _neo_payload_normalization_snapshot(after_rows)
    expected_after = _neo_payload_normalization_snapshot(expected_rows)
    if after != expected_after:
        raise RuntimeError("Neo4j outbox normalization post-scan diverged")
    if _neo_payload_normalization_plan(after_rows):
        raise RuntimeError("Neo4j outbox normalization post-scan is not canonical")
    return {
        "schema_version": NORMALIZATION_RECEIPT_SCHEMA,
        "before": before,
        "after": after,
        "updated_count": len(updates),
    }


def inspect_target() -> dict[str, Any]:
    psycopg2, LazyNeo4jDriver = _database_clients()
    settings = ServerSettings.from_env()
    resources = {
        name: _resource_bytes(name) for name in (PG_RESOURCE, NEO_RESOURCE)
    }
    artifact = _artifact_identity()
    operation = operation_identity(artifact, resources)
    connection = psycopg2.connect(**settings.pg_kw)
    driver = LazyNeo4jDriver(
        connection_acquisition_timeout=NEO_CONNECTION_ACQUISITION_SECONDS,
        connection_timeout=NEO_CONNECTION_ACQUISITION_SECONDS,
    )
    try:
        connection.autocommit = True
        target = target_identity(settings, connection, driver)
    finally:
        connection.close()
        driver.close()
    return {
        "contract_id": CONTRACT_ID,
        "artifact": artifact,
        "operation_sha256": operation["sha256"],
        "target_sha256": target["sha256"],
        "target": target["details"],
    }


def apply(
    *,
    drain_receipt: Path,
    environment: str,
    receipt_out: Path,
    fence_verifier: Path,
    fence_verifier_sha256: str,
) -> dict[str, Any]:
    if not receipt_out.is_absolute():
        raise ValueError("--receipt-out must be an absolute path")
    settings = ServerSettings.from_env()
    if settings.storage_environment != environment:
        raise RuntimeError("--environment does not match LAKATOS_STORAGE_ENVIRONMENT")
    if not (
        _exact_sha256(settings.storage_fence_verifier_sha256)
        and _exact_sha256(fence_verifier_sha256)
        and hmac.compare_digest(
            settings.storage_fence_verifier_sha256 or "",
            fence_verifier_sha256,
        )
    ):
        raise RuntimeError(
            "fence verifier SHA is not pinned by deployment configuration"
        )
    try:
        fence_public_key_hex = settings.storage_fence_public_key_hex
        _ed25519_public_key_bytes(fence_public_key_hex)
    except ValueError as exc:
        raise RuntimeError(
            "writer-fence authority public key is not pinned by deployment configuration"
        ) from exc
    with _reserve_receipt_path(receipt_out) as receipt_reservation:
        return _apply_after_receipt_reservation(
            drain_receipt=drain_receipt,
            environment=environment,
            receipt_out=receipt_out,
            fence_verifier=fence_verifier,
            fence_verifier_sha256=fence_verifier_sha256,
            settings=settings,
            fence_public_key_hex=fence_public_key_hex,
            receipt_reservation=receipt_reservation,
        )


def _apply_after_receipt_reservation(
    *,
    drain_receipt: Path,
    environment: str,
    receipt_out: Path,
    fence_verifier: Path,
    fence_verifier_sha256: str,
    settings: ServerSettings,
    fence_public_key_hex: str,
    receipt_reservation: _ReceiptReservation,
) -> dict[str, Any]:
    # The final leaf, its parent directory, and every ancestor were already
    # acquired without symlink traversal.  Recheck before even importing DB
    # clients so an unusable output target can never follow a mutation.
    receipt_reservation.verify(expect_empty=True)
    psycopg2, LazyNeo4jDriver = _database_clients()
    resources = {
        name: _resource_bytes(name) for name in (PG_RESOURCE, NEO_RESOURCE)
    }
    artifact = _artifact_identity()
    operation = operation_identity(artifact, resources)
    connection = psycopg2.connect(**settings.pg_kw)
    driver = LazyNeo4jDriver(
        connection_acquisition_timeout=NEO_CONNECTION_ACQUISITION_SECONDS,
        connection_timeout=NEO_CONNECTION_ACQUISITION_SECONDS,
    )
    try:
        connection.autocommit = True
        target = target_identity(settings, connection, driver)
        drain = validate_drain_receipt(
            drain_receipt, environment, target["sha256"], operation["sha256"],
            datetime.now(timezone.utc),
        )
        drain = _revalidate_drain(
            drain_receipt, environment, target["sha256"], operation["sha256"],
            drain["sha256"], fence_verifier, fence_verifier_sha256,
            fence_public_key_hex,
        )
        # Cross-store preflight precedes the first mutation.  Missing uniqueness
        # is the sole allowed failure because this operation creates it.
        before = inspect_neo_outbox_contract(
            driver_kg(driver), require_canonical_payload=False
        )
        writer_lease_rows = before.get("details", {}).get(
            "writer_lease_identities_checked"
        )
        allowed_before_migration = {
                "neo4j.constraint.lkt_outbox_id_unique.missing",
                "neo4j.constraint.lkt_argument_id_unique.missing",
                "neo4j.constraint.lkt_runtime_writer_lease_name_unique.missing",
                "neo4j.outbox.pending",
        }
        # A completely fresh target legitimately has no singleton yet; the
        # migration creates it.  Any existing malformed/duplicate singleton is
        # rejected before the earlier PostgreSQL migration can commit.
        if writer_lease_rows == 0:
            allowed_before_migration.add("neo4j.writer_lease.identity")
        non_constraint_failures = [
            item for item in before.get("failures", [])
            if item not in allowed_before_migration
        ]
        if non_constraint_failures:
            raise RuntimeError("Neo4j outbox preflight failed: " + ", ".join(non_constraint_failures))
        try:
            _neo_payload_normalization_plan(
                driver_kg(driver)(_OUTBOX_NORMALIZATION_SCAN)
            )
        except (TypeError, ValueError, UnicodeError) as exc:
            raise RuntimeError(
                "Neo4j outbox strict normalization preflight failed"
            ) from exc
        drain = _revalidate_drain(
            drain_receipt, environment, target["sha256"], operation["sha256"],
            drain["sha256"], fence_verifier, fence_verifier_sha256,
            fence_public_key_hex,
        )
        receipt_reservation.verify(expect_empty=True)
        _bounded_pg_migration(
            connection,
            drain["live_fence"]["expires_at"],
            resources[PG_RESOURCE],
        )
        drain = _revalidate_drain(
            drain_receipt, environment, target["sha256"], operation["sha256"],
            drain["sha256"], fence_verifier, fence_verifier_sha256,
            fence_public_key_hex,
        )
        pg_report = inspect_pg_history_contract(connection)
        if pg_report.get("ok") is not True:
            raise RuntimeError("PostgreSQL exact readback failed after migration")
        projections = pg_projection_rows(connection)

        drain = _revalidate_drain(
            drain_receipt, environment, target["sha256"], operation["sha256"],
            drain["sha256"], fence_verifier, fence_verifier_sha256,
            fence_public_key_hex,
        )
        receipt_reservation.verify(expect_empty=True)
        _bounded_neo_migration(
            driver,
            drain["live_fence"]["expires_at"],
            resources[NEO_RESOURCE],
        )
        drain = _revalidate_drain(
            drain_receipt, environment, target["sha256"], operation["sha256"],
            drain["sha256"], fence_verifier, fence_verifier_sha256,
            fence_public_key_hex,
        )
        receipt_reservation.verify(expect_empty=True)
        payload_normalization = _bounded_neo_payload_normalization(
            driver, drain["live_fence"]["expires_at"]
        )
        drain = _revalidate_drain(
            drain_receipt, environment, target["sha256"], operation["sha256"],
            drain["sha256"], fence_verifier, fence_verifier_sha256,
            fence_public_key_hex,
        )
        neo_report = inspect_neo_outbox_contract(
            driver_kg(driver), projection_rows=projections
        )
        neo_failures = set(neo_report.get("failures") or [])
        if not neo_failures <= {"neo4j.outbox.pending"}:
            raise RuntimeError("Neo4j/cross-store exact readback failed after migration")

        # Persist the final live challenge rather than an earlier boundary
        # check that may already have aged by the time the receipt is written.
        drain = _revalidate_drain(
            drain_receipt, environment, target["sha256"], operation["sha256"],
            drain["sha256"], fence_verifier, fence_verifier_sha256,
            fence_public_key_hex,
        )
        receipt = {
            "schema_version": RECEIPT_SCHEMA,
            "contract_id": CONTRACT_ID,
            "environment": environment,
            "artifact": artifact,
            "operation": operation,
            "target_sha256": target["sha256"],
            "target": target["details"],
            "writer_drain": drain,
            "postgresql": {"ok": True, "report": pg_report},
            "neo4j": {
                "ok": neo_report.get("ok") is True,
                "migration_ok": True,
                "payload_normalization": payload_normalization,
                "report": neo_report,
            },
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        receipt_reservation.verify(expect_empty=True)
        receipt_reservation.publish(receipt)
        published_bytes = receipt_reservation.read_published()
        published = _strict_json_loads(published_bytes)
        expected_self_digest = _sha_bytes(_canonical(receipt))
        if published.get("receipt_sha256") != expected_self_digest:
            raise RuntimeError("published receipt digest readback mismatch")
        return {
            **published,
            "receipt_file_sha256": _sha_bytes(published_bytes),
        }
    finally:
        connection.close()
        driver.close()


def driver_kg(driver: Any):
    def kg(query: str, **params: Any) -> list[dict[str, Any]]:
        return _neo_query(driver, query, **params)
    return kg


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--inspect-target", action="store_true")
    mode.add_argument("--inspect-verifier", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--drain-receipt", type=Path)
    parser.add_argument("--environment")
    parser.add_argument("--receipt-out", type=Path)
    parser.add_argument("--fence-verifier", type=Path)
    parser.add_argument("--fence-verifier-sha256")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.inspect_verifier:
        if not args.fence_verifier:
            raise SystemExit("--inspect-verifier requires --fence-verifier")
        print(json.dumps(
            fence_verifier_identity(args.fence_verifier),
            ensure_ascii=False,
            sort_keys=True,
        ))
        return 0
    if args.inspect_target:
        print(json.dumps(inspect_target(), ensure_ascii=False, sort_keys=True))
        return 0
    if not (
        args.drain_receipt and args.environment and args.receipt_out
        and args.fence_verifier and args.fence_verifier_sha256
    ):
        raise SystemExit(
            "--apply requires --drain-receipt, --environment, --receipt-out, "
            "--fence-verifier, and --fence-verifier-sha256"
        )
    receipt = apply(
        drain_receipt=args.drain_receipt,
        environment=args.environment,
        receipt_out=args.receipt_out,
        fence_verifier=args.fence_verifier,
        fence_verifier_sha256=args.fence_verifier_sha256,
    )
    print(json.dumps({
        "ok": True, "contract_id": receipt["contract_id"],
        "receipt": str(args.receipt_out),
        "receipt_file_sha256": receipt["receipt_file_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
