"""Durable target-fenced local build adapter and resource-gated runner.

The adapter offers at-most-one *launch attempt* for a stable effect identity,
not generic exactly-once subprocess execution.  It commits a target claim before
launch, serializes one scope with a POSIX lock, refuses stale/equal foreign fences,
and never relaunches a nonterminal claim.  A crash between the durable claim and
authoritative terminal evidence therefore remains explicitly unknown.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path, PurePosixPath
import platform
import selectors
import signal
import sqlite3
import stat
import subprocess
import sys
import time
from typing import Callable, Iterator, Mapping, Protocol

try:
    import fcntl
except ImportError:  # pragma: no cover - production/test deployment is POSIX.
    fcntl = None

from lakatos.build_execution import (
    BuildExecutionResult,
    BuildExecutionSpec,
    BuildRun,
    BuildTerminalStatus,
    LOCAL_BUILD_ADAPTER,
    LOCAL_BUILD_ADAPTER_VERSION,
    ResourceBuildConfigError,
    ResourceBuildOutcomeUnknown,
    ResourceBuildOverrun,
    environment_sha256,
)
from lakatos.io._resource_journal_contracts import (
    AnchorStatus,
    ResourceJournalError,
    RevisionConflict,
    TrustedAnchorCorruption,
    TrustedAnchorUnavailable,
)
from lakatos.io.resource_execution import (
    DispatchOutcomeUnknown,
    HMACPermitAuthenticator,
    ResourceExecutionGate,
    ResourceJournalPort,
    authority_from_snapshot,
)
from lakatos.io.resource_journal import (
    JournalNotInitialized,
    SQLiteResourceJournal,
    SignedAppendOnlyFileAnchor,
)
from lakatos.resource_coordination import (
    GrantStatus,
    RequestGrant,
    ResourceEstimate,
    ResourceState,
    ResourceUsage,
    ResourceVector,
    SettleGrant,
    StartGrant,
)
from lakatos.resource_execution import (
    WorkloadDispatchIntentReference,
    WorkloadDispatchPermit,
    WorkloadDispatchReceipt,
    require_current_confirmed_authority,
)


_APPLICATION_ID = 0x4C4B4254  # "LKBT"
_USER_VERSION = 1
_TARGET_SCHEMA_VERSION = "lakatotree.local-build-target/v1"
_TARGET_AUTH_DOMAIN = b"lakatotree-local-build-target-auth\x00v1\n"
_TARGET_KEY_ID_DOMAIN = b"lakatotree-local-build-target-key-id\x00v1\n"
_INPUT_MANIFEST_SCHEMA_VERSION = "lakatotree.build-input-manifest/v1"
_INPUT_MANIFEST_DOMAIN = b"lakatotree-build-input-manifest\x00v1\n"
# Stable SQLite primary result codes: BUSY, LOCKED, READONLY, INTERRUPT, IOERR,
# FULL, CANTOPEN, and PROTOCOL.  Python 3.10 does not expose their symbolic names.
_TRANSIENT_SQLITE_PRIMARY_CODES = frozenset({5, 6, 8, 9, 10, 13, 14, 15})
_DARWIN_SANDBOX_ADAPTER = "lakatotree.darwin-sandbox-exec"
_DARWIN_SANDBOX_VERSION = "1"
_PROCESS_CLEANUP_GRACE_SECONDS = 1.0
_MAX_RESULT_BLOB_BYTES = 8 * 1024 * 1024
_MAX_RECEIPT_BLOB_BYTES = 64 * 1024
_BOUNDED_EFFECT_ROW_SQL = """
    SELECT
        effect_id,
        scope,
        workload_sha256,
        intent_sha256,
        fence_token,
        status,
        length(result_blob) AS result_blob_length,
        CASE
            WHEN result_blob IS NULL OR length(result_blob) <= ? THEN result_blob
            ELSE NULL
        END AS result_blob,
        result_sha256,
        length(receipt_blob) AS receipt_blob_length,
        CASE
            WHEN receipt_blob IS NULL OR length(receipt_blob) <= ? THEN receipt_blob
            ELSE NULL
        END AS receipt_blob,
        receipt_sha256,
        target_mac_sha256
    FROM build_effects
    WHERE effect_id = ?
"""
_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE build_target_meta (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        schema_version TEXT NOT NULL,
        adapter TEXT NOT NULL,
        adapter_version TEXT NOT NULL,
        schema_sha256 TEXT NOT NULL,
        target_key_id TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE build_fence_allocator (
        scope TEXT PRIMARY KEY,
        highest_token INTEGER NOT NULL CHECK (highest_token >= 0)
    )
    """,
    """
    CREATE TABLE build_fence_allocations (
        scope TEXT NOT NULL,
        effect_id TEXT NOT NULL,
        fence_token INTEGER NOT NULL CHECK (fence_token >= 1),
        PRIMARY KEY (scope, effect_id),
        UNIQUE (scope, fence_token)
    )
    """,
    """
    CREATE TABLE build_dispatch_head (
        scope TEXT PRIMARY KEY,
        fence_token INTEGER NOT NULL CHECK (fence_token >= 1),
        effect_id TEXT NOT NULL,
        UNIQUE (scope, fence_token)
    )
    """,
    """
    CREATE TABLE build_effects (
        effect_id TEXT PRIMARY KEY,
        scope TEXT NOT NULL,
        workload_sha256 TEXT NOT NULL,
        intent_sha256 TEXT NOT NULL,
        fence_token INTEGER NOT NULL CHECK (fence_token >= 1),
        status TEXT NOT NULL CHECK (status IN ('CLAIMED', 'TERMINAL')),
        result_blob BLOB,
        result_sha256 TEXT,
        receipt_blob BLOB,
        receipt_sha256 TEXT,
        target_mac_sha256 TEXT,
        UNIQUE (scope, fence_token),
        UNIQUE (intent_sha256),
        CHECK (
            (status = 'CLAIMED' AND result_blob IS NULL AND result_sha256 IS NULL
             AND receipt_blob IS NULL AND receipt_sha256 IS NULL
             AND target_mac_sha256 IS NULL)
            OR
            (status = 'TERMINAL' AND result_blob IS NOT NULL AND result_sha256 IS NOT NULL
             AND receipt_blob IS NOT NULL AND receipt_sha256 IS NOT NULL
             AND target_mac_sha256 IS NOT NULL)
        )
    )
    """,
)
_SCHEMA_SHA256 = hashlib.sha256(
    "\n".join(statement.strip() for statement in _SCHEMA_STATEMENTS).encode("utf-8")
).hexdigest()
_EXPECTED_TABLES = {
    "build_target_meta",
    "build_fence_allocator",
    "build_fence_allocations",
    "build_dispatch_head",
    "build_effects",
}


def _normalize_schema_sql(value: str) -> str:
    return " ".join(value.split())


_EXPECTED_LIVE_SCHEMA = {
    ("table", table_name): _normalize_schema_sql(statement)
    for table_name, statement in zip(
        (
            "build_target_meta",
            "build_fence_allocator",
            "build_fence_allocations",
            "build_dispatch_head",
            "build_effects",
        ),
        _SCHEMA_STATEMENTS,
        strict=True,
    )
}


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


class BuildExecutionIsolationPort(Protocol):
    """Trusted process boundary used by the local build effect."""

    adapter: str
    adapter_version: str
    policy_sha256: str
    denies_provider_network: bool
    protects_resource_root: bool

    def argv(self, spec: BuildExecutionSpec) -> tuple[str, ...]:
        ...


class BuildInputVerifierPort(Protocol):
    """Exact-read verifier for the files declared as workload inputs."""

    manifest_sha256: str

    def verify(self) -> None:
        ...


class BuildEffectPort(Protocol):
    """Application-facing durable build effect boundary."""

    adapter: str
    adapter_version: str

    @property
    def spec(self) -> BuildExecutionSpec:
        ...

    def load_terminal_result(
        self,
        *,
        effect_id: str,
        workload_sha256: str,
    ) -> tuple[BuildExecutionResult, WorkloadDispatchReceipt]:
        ...

    def verify_inputs(self) -> None:
        ...


class BuildInputManifestError(RuntimeError):
    """A declared build input is missing, changed, or outside the bound root."""


@dataclass(frozen=True, slots=True)
class VerifiedBuildInputManifest:
    """Canonical file-by-file input manifest, rechecked before every replay/launch."""

    root: Path
    entries: tuple[tuple[str, str], ...]
    manifest_sha256: str

    @classmethod
    def load(
        cls,
        manifest_path: str | os.PathLike[str],
        *,
        root: str | os.PathLike[str],
    ) -> "VerifiedBuildInputManifest":
        bound_root = Path(root).resolve()
        path = Path(manifest_path).expanduser().resolve()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BuildInputManifestError("build input manifest is unreadable") from exc
        if not isinstance(payload, dict) or set(payload) != {"schema_version", "files"}:
            raise BuildInputManifestError("build input manifest fields diverged")
        if payload["schema_version"] != _INPUT_MANIFEST_SCHEMA_VERSION:
            raise BuildInputManifestError("unsupported build input manifest schema")
        files = payload["files"]
        if not isinstance(files, list) or not files:
            raise BuildInputManifestError("build input manifest requires at least one file")
        entries: list[tuple[str, str]] = []
        for entry in files:
            if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
                raise BuildInputManifestError("build input manifest entry fields diverged")
            relative = entry["path"]
            digest = entry["sha256"]
            pure_relative = (
                PurePosixPath(relative) if isinstance(relative, str) else None
            )
            if (
                not isinstance(relative, str)
                or not relative
                or "\\" in relative
                or "\0" in relative
                or pure_relative is None
                or pure_relative.is_absolute()
                or not pure_relative.parts
                or pure_relative.as_posix() != relative
                or any(part in {"", ".", ".."} for part in pure_relative.parts)
            ):
                raise BuildInputManifestError(
                    "build input paths must be normalized relative POSIX paths"
                )
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or digest != digest.lower()
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise BuildInputManifestError("build input digest is not canonical SHA-256")
            entries.append((relative, digest))
        if entries != sorted(entries) or len(entries) != len(set(entries)):
            raise BuildInputManifestError(
                "build input manifest paths must be unique and lexically sorted"
            )
        canonical = {
            "schema_version": _INPUT_MANIFEST_SCHEMA_VERSION,
            "files": [
                {"path": relative, "sha256": digest}
                for relative, digest in entries
            ],
        }
        instance = cls(
            root=bound_root,
            entries=tuple(entries),
            manifest_sha256=hashlib.sha256(
                _INPUT_MANIFEST_DOMAIN + _canonical_bytes(canonical)
            ).hexdigest(),
        )
        instance.verify()
        return instance

    def verify(self) -> None:
        for relative, expected_sha256 in self.entries:
            candidate = self.root.joinpath(*relative.split("/"))
            try:
                resolved = candidate.resolve(strict=True)
                resolved.relative_to(self.root)
                metadata = candidate.lstat()
            except (OSError, ValueError) as exc:
                raise BuildInputManifestError(
                    f"declared build input is missing or outside root: {relative}"
                ) from exc
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(resolved.stat().st_mode):
                raise BuildInputManifestError(
                    f"declared build input must be a regular non-symlink file: {relative}"
                )
            if _sha256_file(resolved) != expected_sha256:
                raise BuildInputManifestError(f"declared build input changed: {relative}")


def darwin_sandbox_profile(protected_root: str | os.PathLike[str]) -> str:
    """Return the exact deterministic Seatbelt policy without touching the host."""

    root_literal = json.dumps(str(Path(protected_root).resolve()), ensure_ascii=False)
    return "\n".join((
        "(version 1)",
        "(allow default)",
        "(deny network*)",
        f"(deny file-read* (subpath {root_literal}))",
        f"(deny file-write* (subpath {root_literal}))",
    ))


def darwin_sandbox_argv(
    profile: str,
    spec: BuildExecutionSpec,
) -> tuple[str, ...]:
    """Build the closed argv for the production Seatbelt adapter."""

    if not isinstance(profile, str) or not profile:
        raise ValueError("sandbox profile must be non-empty text")
    if not isinstance(spec, BuildExecutionSpec):
        raise TypeError("sandbox argv requires a BuildExecutionSpec")
    return (
        "/usr/bin/sandbox-exec",
        "-p",
        profile,
        spec.shell,
        "-c",
        spec.command,
    )


class DarwinSandboxExecIsolation:
    """macOS sandbox profile denying network and access to the resource authority root."""

    adapter = _DARWIN_SANDBOX_ADAPTER
    adapter_version = _DARWIN_SANDBOX_VERSION
    denies_provider_network = True
    protects_resource_root = True

    def __init__(self, protected_root: str | os.PathLike[str]) -> None:
        if platform.system() != "Darwin":
            raise ResourceBuildConfigError(
                "the built-in provider-denied build isolation currently requires macOS"
            )
        executable = Path("/usr/bin/sandbox-exec")
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise ResourceBuildConfigError("/usr/bin/sandbox-exec is unavailable")
        self._profile = darwin_sandbox_profile(protected_root)
        self.policy_sha256 = hashlib.sha256(
            b"lakatotree-darwin-build-sandbox\x00v1\n"
            + self._profile.encode("utf-8")
        ).hexdigest()

    def argv(self, spec: BuildExecutionSpec) -> tuple[str, ...]:
        return darwin_sandbox_argv(self._profile, spec)


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.removesuffix("Z") + "+00:00")


def _logical_completed_at(
    *,
    started_at: str,
    elapsed_monotonic_ns: int,
    observed_at: str,
) -> str:
    monotonic_floor = _parse_utc(started_at) + timedelta(
        microseconds=(elapsed_monotonic_ns + 999) // 1000
    )
    completed = max(monotonic_floor, _parse_utc(observed_at))
    return completed.isoformat(timespec="microseconds").replace("+00:00", "Z")


class _BoundedStreamEvidence:
    """Incremental, memory-bounded evidence for one subprocess pipe."""

    def __init__(self, *, tail_bytes: int) -> None:
        self._digest = hashlib.sha256()
        self._tail_bytes = tail_bytes
        self._tail = b""
        self.byte_count = 0

    def append(self, chunk: bytes, *, remaining_bytes: int) -> bool:
        """Record the admitted prefix and report whether bytes were refused."""

        admitted = chunk[:remaining_bytes]
        self._digest.update(admitted)
        self.byte_count += len(admitted)
        self._tail = (self._tail + admitted)[-self._tail_bytes :]
        return len(admitted) != len(chunk)

    @property
    def sha256(self) -> str:
        return self._digest.hexdigest()

    @property
    def tail(self) -> bytes:
        return self._tail


def _decode_bounded_output_tail(raw: bytes, *, max_bytes: int) -> str:
    """Decode replacement text while preserving the persisted UTF-8 byte cap."""

    encoded = raw.decode("utf-8", errors="replace").encode("utf-8")
    if len(encoded) <= max_bytes:
        return encoded.decode("utf-8")
    suffix = encoded[-max_bytes:]
    while suffix and suffix[0] & 0b1100_0000 == 0b1000_0000:
        suffix = suffix[1:]
    return suffix.decode("utf-8")


def _kill_process_group(process_group_id: int) -> None:
    try:
        os.killpg(process_group_id, signal.SIGKILL)
    except ProcessLookupError:
        pass


class _SystemClock:
    def now_utc(self) -> str:
        return _utc_now()


def _require_text_identity(value: str, label: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 256
        or not value.isprintable()
    ):
        raise ValueError(f"{label} must be printable, non-empty, and <= 256 chars")


class BuildTargetError(RuntimeError):
    """The local target registry rejected or could not verify an effect."""


class BuildTargetIdentityConflict(BuildTargetError):
    """A stable target identifier was reused with a changed binding."""


class BuildTargetOutcomeUnknown(BuildTargetError):
    """The target contains a durable nonterminal claim and will not relaunch it."""


class StaleBuildFence(BuildTargetError):
    """A lower/equal foreign fence reached the target launch boundary."""


def _translated_target_sqlite_error(error: sqlite3.Error) -> BuildTargetError:
    """Classify SQLite availability separately from deterministic target defects."""

    code = getattr(error, "sqlite_errorcode", None)
    primary_code = code & 0xFF if isinstance(code, int) else None
    # Python only exposed Error.sqlite_errorcode from 3.11; LakatoTree also
    # supports 3.10, where the message fallback below is the available signal.
    detail = str(error).strip() or type(error).__name__
    fallback_transient = any(fragment in detail.lower() for fragment in (
        "busy",
        "locked",
        "read-only",
        "readonly",
        "disk i/o",
        "disk is full",
        "unable to open",
        "interrupted",
        "protocol",
    ))
    if primary_code in _TRANSIENT_SQLITE_PRIMARY_CODES or (
        primary_code is None and fallback_transient
    ):
        return BuildTargetOutcomeUnknown(f"build target SQLite unavailable: {detail}")
    return BuildTargetError(f"build target SQLite rejected durable state: {detail}")


def _rollback_preserving_failure(connection: sqlite3.Connection) -> None:
    try:
        if connection.in_transaction:
            connection.rollback()
    except sqlite3.Error:
        pass


class SQLiteFencedBuildEffect:
    """SQLite target registry plus serialized provider-free subprocess effect."""

    adapter = LOCAL_BUILD_ADAPTER
    adapter_version = LOCAL_BUILD_ADAPTER_VERSION

    def __init__(
        self,
        database_path: str | os.PathLike[str],
        *,
        spec: BuildExecutionSpec,
        environment: Mapping[str, str],
        isolation: BuildExecutionIsolationPort,
        input_verifier: BuildInputVerifierPort,
        authentication_key: bytes,
        utc_now: Callable[[], str] = _utc_now,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        failure_inject_after_claim: Callable[[str], None] | None = None,
        failure_inject_after_terminal_commit: (
            Callable[[BuildExecutionResult], None] | None
        ) = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        if fcntl is None:
            raise OSError("SQLiteFencedBuildEffect requires POSIX file locking")
        if not isinstance(spec, BuildExecutionSpec):
            raise TypeError("spec must be a BuildExecutionSpec")
        self._path = Path(database_path)
        if str(database_path) == ":memory:" or not self._path.parent.exists():
            raise ValueError("build target requires a durable file in an existing directory")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._timeout_seconds = float(timeout_seconds)
        self._spec = spec
        self._environment = dict(environment)
        if environment_sha256(self._environment) != spec.environment_sha256:
            raise ValueError("closed child environment diverges from BuildExecutionSpec")
        isolation_binding = (
            getattr(isolation, "adapter", None),
            getattr(isolation, "adapter_version", None),
            getattr(isolation, "policy_sha256", None),
        )
        if isolation_binding != (
            spec.isolation_adapter,
            spec.isolation_version,
            spec.isolation_policy_sha256,
        ):
            raise ValueError("build isolation identity diverges from BuildExecutionSpec")
        if not (
            getattr(isolation, "denies_provider_network", False)
            and getattr(isolation, "protects_resource_root", False)
        ):
            raise ValueError(
                "build isolation must deny provider network and protect resource authority"
            )
        if getattr(input_verifier, "manifest_sha256", None) != spec.input_manifest_sha256:
            raise ValueError("input verifier diverges from BuildExecutionSpec")
        if not isinstance(authentication_key, bytes) or len(authentication_key) < 32:
            raise ValueError("target authentication_key must contain at least 32 bytes")
        self._isolation = isolation
        self._input_verifier = input_verifier
        self._authentication_key = bytes(authentication_key)
        self._target_key_id = hashlib.sha256(
            _TARGET_KEY_ID_DOMAIN + self._authentication_key
        ).hexdigest()
        self._utc_now = utc_now
        self._monotonic_ns = monotonic_ns
        self._failure_inject_after_claim = failure_inject_after_claim
        self._failure_inject_after_terminal_commit = failure_inject_after_terminal_commit
        self._bootstrap_or_verify_schema()

    @property
    def spec(self) -> BuildExecutionSpec:
        return self._spec

    def _connect(self) -> sqlite3.Connection:
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(
                self._path,
                timeout=self._timeout_seconds,
                isolation_level=None,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute(
                f"PRAGMA busy_timeout = {max(1, int(self._timeout_seconds * 1000))}"
            )
            if connection.execute("PRAGMA synchronous").fetchone()[0] != 2:
                raise BuildTargetError("SQLite synchronous=FULL readback failed")
            return connection
        except sqlite3.Error as exc:
            if connection is not None:
                try:
                    connection.close()
                except sqlite3.Error:
                    pass
            raise _translated_target_sqlite_error(exc) from exc
        except BaseException:
            if connection is not None:
                try:
                    connection.close()
                except sqlite3.Error:
                    pass
            raise

    @contextmanager
    def _target_connection(self) -> Iterator[sqlite3.Connection]:
        """Close, roll back, and type every target SQLite failure uniformly."""

        connection = self._connect()
        body_failed = False
        try:
            yield connection
        except sqlite3.Error as exc:
            body_failed = True
            _rollback_preserving_failure(connection)
            raise _translated_target_sqlite_error(exc) from exc
        except BaseException:
            body_failed = True
            _rollback_preserving_failure(connection)
            raise
        finally:
            try:
                connection.close()
            except sqlite3.Error as exc:
                if not body_failed:
                    raise _translated_target_sqlite_error(exc) from exc

    def _bootstrap_or_verify_schema(self) -> None:
        with self._target_connection() as connection:
            application_id = connection.execute("PRAGMA application_id").fetchone()[0]
            user_version = connection.execute("PRAGMA user_version").fetchone()[0]
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            if not tables:
                if application_id != 0 or user_version != 0:
                    raise BuildTargetError("empty target database has foreign metadata")
                mode = connection.execute("PRAGMA journal_mode = DELETE").fetchone()[0]
                if str(mode).lower() != "delete":
                    raise BuildTargetError("SQLite rollback journal mode is required")
                connection.execute("BEGIN EXCLUSIVE")
                try:
                    for statement in _SCHEMA_STATEMENTS:
                        connection.execute(statement)
                    connection.execute(
                        "INSERT INTO build_target_meta VALUES (1, ?, ?, ?, ?, ?)",
                        (
                            _TARGET_SCHEMA_VERSION,
                            self.adapter,
                            self.adapter_version,
                            _SCHEMA_SHA256,
                            self._target_key_id,
                        ),
                    )
                    connection.execute(f"PRAGMA application_id = {_APPLICATION_ID}")
                    connection.execute(f"PRAGMA user_version = {_USER_VERSION}")
                    connection.commit()
                except BaseException:
                    _rollback_preserving_failure(connection)
                    raise
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            if tables != _EXPECTED_TABLES:
                raise BuildTargetError(f"build target tables diverged: {sorted(tables)}")
            live_schema = {
                (row["type"], row["name"]): _normalize_schema_sql(row["sql"])
                for row in connection.execute(
                    "SELECT type, name, sql FROM sqlite_master "
                    "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
                )
                if row["sql"] is not None
            }
            if live_schema != _EXPECTED_LIVE_SCHEMA:
                raise BuildTargetError(
                    "build target live schema diverged from the exact schema receipt"
                )
            if (
                connection.execute("PRAGMA application_id").fetchone()[0]
                != _APPLICATION_ID
                or connection.execute("PRAGMA user_version").fetchone()[0]
                != _USER_VERSION
                or str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
                != "delete"
            ):
                raise BuildTargetError("build target SQLite metadata diverged")
            meta = connection.execute(
                "SELECT schema_version, adapter, adapter_version, schema_sha256, "
                "target_key_id "
                "FROM build_target_meta WHERE singleton = 1"
            ).fetchone()
            if meta is None or tuple(meta) != (
                _TARGET_SCHEMA_VERSION,
                self.adapter,
                self.adapter_version,
                _SCHEMA_SHA256,
                self._target_key_id,
            ):
                raise BuildTargetError("build target metadata diverged")

    @contextmanager
    def _scope_lock(self, scope: str) -> Iterator[None]:
        _require_text_identity(scope, "scope")
        scope_key = hashlib.sha256(scope.encode("utf-8")).hexdigest()
        lock_path = self._path.parent / f".{self._path.name}.{scope_key}.lock"
        descriptor: int | None = None
        try:
            descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        except OSError as exc:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            raise BuildTargetOutcomeUnknown(
                f"build target lock unavailable: {exc}"
            ) from exc
        body_failed = False
        try:
            yield
        except BaseException:
            body_failed = True
            raise
        finally:
            cleanup_error: OSError | None = None
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            except OSError as exc:
                cleanup_error = exc
            try:
                os.close(descriptor)
            except OSError as exc:
                cleanup_error = cleanup_error or exc
            if cleanup_error is not None and not body_failed:
                raise BuildTargetOutcomeUnknown(
                    f"build target lock cleanup is uncertain: {cleanup_error}"
                ) from cleanup_error

    def allocate_fence(self, *, scope: str, effect_id: str) -> int:
        """Allocate or replay one target-local monotonic fence for an effect."""

        _require_text_identity(scope, "scope")
        _require_text_identity(effect_id, "effect_id")
        with self._scope_lock(scope):
            with self._target_connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT fence_token FROM build_fence_allocations "
                    "WHERE scope = ? AND effect_id = ?",
                    (scope, effect_id),
                ).fetchone()
                if existing is not None:
                    connection.commit()
                    return int(existing["fence_token"])
                head = connection.execute(
                    "SELECT highest_token FROM build_fence_allocator WHERE scope = ?",
                    (scope,),
                ).fetchone()
                token = 1 if head is None else int(head["highest_token"]) + 1
                connection.execute(
                    "INSERT INTO build_fence_allocations "
                    "(scope, effect_id, fence_token) VALUES (?, ?, ?)",
                    (scope, effect_id, token),
                )
                connection.execute(
                    "INSERT INTO build_fence_allocator (scope, highest_token) "
                    "VALUES (?, ?) ON CONFLICT(scope) DO UPDATE SET highest_token=excluded.highest_token",
                    (scope, token),
                )
                connection.commit()
                return token

    @staticmethod
    def _validate_binding(row: sqlite3.Row, reference) -> None:
        expected = (
            reference.effect_id,
            reference.scope,
            reference.workload_sha256,
            reference.intent_sha256,
            reference.fence_token,
        )
        actual = (
            row["effect_id"],
            row["scope"],
            row["workload_sha256"],
            row["intent_sha256"],
            row["fence_token"],
        )
        if actual != expected:
            raise BuildTargetIdentityConflict(
                "effect id was replayed with a changed scope/workload/intent/fence"
            )

    @staticmethod
    def _decode_result(row: sqlite3.Row, raw: bytes) -> BuildExecutionResult:
        try:
            payload = json.loads(raw.decode("utf-8"))
            if _canonical_bytes(payload) != raw:
                raise ValueError("terminal build result is not canonical")
            result = BuildExecutionResult.from_dict(payload)
        except Exception as exc:
            raise BuildTargetError("terminal build result is unreadable") from exc
        if result.evidence_sha256 != row["result_sha256"]:
            raise BuildTargetError("terminal build result hash diverged")
        return result

    @staticmethod
    def _decode_receipt(row: sqlite3.Row, raw: bytes) -> WorkloadDispatchReceipt:
        try:
            payload = json.loads(raw.decode("utf-8"))
            if _canonical_bytes(payload) != raw:
                raise ValueError("terminal dispatch receipt is not canonical")
            receipt = WorkloadDispatchReceipt(**payload)
        except Exception as exc:
            raise BuildTargetError("terminal dispatch receipt is unreadable") from exc
        if receipt.receipt_sha256 != row["receipt_sha256"]:
            raise BuildTargetError("terminal dispatch receipt hash diverged")
        return receipt

    def _target_mac(
        self,
        *,
        effect_id: str,
        scope: str,
        workload_sha256: str,
        intent_sha256: str,
        fence_token: int,
        result_sha256: str,
        receipt_sha256: str,
        result_blob_sha256: str,
        receipt_blob_sha256: str,
    ) -> str:
        material = _canonical_bytes({
            "effect_id": effect_id,
            "scope": scope,
            "workload_sha256": workload_sha256,
            "intent_sha256": intent_sha256,
            "fence_token": fence_token,
            "result_sha256": result_sha256,
            "receipt_sha256": receipt_sha256,
            "result_blob_sha256": result_blob_sha256,
            "receipt_blob_sha256": receipt_blob_sha256,
        })
        return hmac.new(
            self._authentication_key,
            _TARGET_AUTH_DOMAIN + material,
            hashlib.sha256,
        ).hexdigest()

    def _terminal_values(
        self,
        row: sqlite3.Row,
    ) -> tuple[BuildExecutionResult, WorkloadDispatchReceipt]:
        if row["status"] != "TERMINAL":
            raise BuildTargetOutcomeUnknown(
                "durable build claim has no authoritative terminal evidence"
            )
        result_blob_length = row["result_blob_length"]
        receipt_blob_length = row["receipt_blob_length"]
        if (
            isinstance(result_blob_length, bool)
            or not isinstance(result_blob_length, int)
            or result_blob_length < 0
        ):
            raise BuildTargetError("terminal target authentication failed")
        if result_blob_length > _MAX_RESULT_BLOB_BYTES:
            raise BuildTargetError("terminal build result exceeds the readback limit")
        if (
            isinstance(receipt_blob_length, bool)
            or not isinstance(receipt_blob_length, int)
            or receipt_blob_length < 0
        ):
            raise BuildTargetError("terminal target authentication failed")
        if receipt_blob_length > _MAX_RECEIPT_BLOB_BYTES:
            raise BuildTargetError("terminal dispatch receipt exceeds the readback limit")
        result_blob_value = row["result_blob"]
        receipt_blob_value = row["receipt_blob"]
        if not isinstance(result_blob_value, (bytes, bytearray, memoryview)):
            raise BuildTargetError("terminal target authentication failed")
        if not isinstance(receipt_blob_value, (bytes, bytearray, memoryview)):
            raise BuildTargetError("terminal target authentication failed")
        result_blob = bytes(result_blob_value)
        receipt_blob = bytes(receipt_blob_value)
        if len(result_blob) != result_blob_length:
            raise BuildTargetError("terminal target authentication failed")
        if len(receipt_blob) != receipt_blob_length:
            raise BuildTargetError("terminal target authentication failed")
        try:
            expected_mac = self._target_mac(
                effect_id=row["effect_id"],
                scope=row["scope"],
                workload_sha256=row["workload_sha256"],
                intent_sha256=row["intent_sha256"],
                fence_token=row["fence_token"],
                result_sha256=row["result_sha256"],
                receipt_sha256=row["receipt_sha256"],
                result_blob_sha256=hashlib.sha256(result_blob).hexdigest(),
                receipt_blob_sha256=hashlib.sha256(receipt_blob).hexdigest(),
            )
        except (TypeError, ValueError) as exc:
            raise BuildTargetError("terminal target authentication failed") from exc
        target_mac = row["target_mac_sha256"]
        if (
            not isinstance(target_mac, str)
            or not hmac.compare_digest(expected_mac, target_mac)
        ):
            raise BuildTargetError("terminal target authentication failed")
        # Only authenticated bounded bytes cross the JSON/schema boundary.
        result = self._decode_result(row, result_blob)
        receipt = self._decode_receipt(row, receipt_blob)
        expected = (
            row["effect_id"],
            row["workload_sha256"],
            row["intent_sha256"],
            row["fence_token"],
            result.evidence_sha256,
        )
        actual = (
            result.effect_id,
            result.workload_sha256,
            result.intent_sha256,
            result.fence_token,
            receipt.evidence_sha256,
        )
        if actual != expected:
            raise BuildTargetError("terminal result binding diverged")
        if (
            receipt.effect_id,
            receipt.workload_sha256,
            receipt.intent_sha256,
            receipt.fence_token,
            receipt.completed_at,
        ) != (
            result.effect_id,
            result.workload_sha256,
            result.intent_sha256,
            result.fence_token,
            result.completed_at,
        ):
            raise BuildTargetError("dispatch receipt and build result diverged")
        return result, receipt

    @staticmethod
    def _bounded_effect_row(
        connection: sqlite3.Connection,
        effect_id: str,
    ) -> sqlite3.Row | None:
        """Read blob lengths first and materialize only bounded terminal bytes."""

        return connection.execute(
            _BOUNDED_EFFECT_ROW_SQL,
            (_MAX_RESULT_BLOB_BYTES, _MAX_RECEIPT_BLOB_BYTES, effect_id),
        ).fetchone()

    def _load_row(self, effect_id: str) -> sqlite3.Row | None:
        with self._target_connection() as connection:
            return self._bounded_effect_row(connection, effect_id)

    def _claim(self, permit: WorkloadDispatchPermit) -> sqlite3.Row | None:
        with self._target_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._bounded_effect_row(connection, permit.effect_id)
            if existing is not None:
                self._validate_binding(existing, permit)
                connection.commit()
                return existing
            allocation = connection.execute(
                "SELECT fence_token FROM build_fence_allocations "
                "WHERE scope = ? AND effect_id = ?",
                (permit.scope, permit.effect_id),
            ).fetchone()
            if allocation is None or int(allocation["fence_token"]) != permit.fence_token:
                raise StaleBuildFence("permit has no exact target fence allocation")
            unresolved = connection.execute(
                "SELECT effect_id FROM build_effects "
                "WHERE scope = ? AND status = 'CLAIMED' LIMIT 1",
                (permit.scope,),
            ).fetchone()
            if unresolved is not None:
                raise BuildTargetOutcomeUnknown(
                    f"scope has unresolved build claim {unresolved['effect_id']}"
                )
            head = connection.execute(
                "SELECT fence_token, effect_id FROM build_dispatch_head WHERE scope = ?",
                (permit.scope,),
            ).fetchone()
            if head is not None and permit.fence_token <= int(head["fence_token"]):
                raise StaleBuildFence(
                    "target rejected a lower/equal fence bound to another effect"
                )
            connection.execute(
                "INSERT INTO build_effects "
                "(effect_id, scope, workload_sha256, intent_sha256, fence_token, status) "
                "VALUES (?, ?, ?, ?, ?, 'CLAIMED')",
                (
                    permit.effect_id,
                    permit.scope,
                    permit.workload_sha256,
                    permit.intent_sha256,
                    permit.fence_token,
                ),
            )
            connection.execute(
                "INSERT INTO build_dispatch_head (scope, fence_token, effect_id) "
                "VALUES (?, ?, ?) ON CONFLICT(scope) DO UPDATE SET "
                "fence_token=excluded.fence_token, effect_id=excluded.effect_id",
                (permit.scope, permit.fence_token, permit.effect_id),
            )
            connection.commit()
            return None

    def _run_subprocess(self, permit: WorkloadDispatchPermit) -> BuildExecutionResult:
        started_at = self._utc_now()
        started_ns = self._monotonic_ns()
        control_deadline = time.monotonic() + self._spec.timeout_seconds
        status = BuildTerminalStatus.EXITED
        returncode: int | None = None
        stdout_evidence = _BoundedStreamEvidence(
            tail_bytes=self._spec.output_tail_bytes
        )
        stderr_evidence = _BoundedStreamEvidence(
            tail_bytes=self._spec.output_tail_bytes
        )
        process: subprocess.Popen[bytes] | None = None
        selector = selectors.DefaultSelector()
        cleanup_deadline: float | None = None
        try:
            try:
                process = subprocess.Popen(
                    self._isolation.argv(self._spec),
                    shell=False,
                    cwd=self._spec.cwd,
                    env=self._environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    start_new_session=True,
                )
            except OSError as exc:
                status = BuildTerminalStatus.SPAWN_FAILED
                returncode = 126
                message = f"{type(exc).__name__}: {exc}".encode(
                    "utf-8", errors="replace"
                )
                stderr_evidence.append(
                    message,
                    remaining_bytes=self._spec.max_output_bytes,
                )
            else:
                assert process.stdout is not None and process.stderr is not None
                for name, stream in (
                    ("stdout", process.stdout),
                    ("stderr", process.stderr),
                ):
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ, data=name)

                while selector.get_map() or process.poll() is None:
                    now = time.monotonic()
                    leader_returncode = process.poll()
                    if (
                        status is BuildTerminalStatus.EXITED
                        and leader_returncode is not None
                        and returncode is None
                    ):
                        returncode = leader_returncode
                        # The admitted unit is the complete process group. Close
                        # ordinary background descendants before settlement.
                        _kill_process_group(process.pid)
                        cleanup_deadline = now + _PROCESS_CLEANUP_GRACE_SECONDS
                    elif (
                        status is BuildTerminalStatus.EXITED
                        and leader_returncode is None
                        and now >= control_deadline
                    ):
                        status = BuildTerminalStatus.TIMED_OUT
                        returncode = None
                        _kill_process_group(process.pid)
                        cleanup_deadline = now + _PROCESS_CLEANUP_GRACE_SECONDS

                    if cleanup_deadline is not None and now >= cleanup_deadline:
                        break
                    next_deadline = (
                        cleanup_deadline
                        if cleanup_deadline is not None
                        else control_deadline
                    )
                    ready = selector.select(
                        timeout=max(0.0, min(0.05, next_deadline - now))
                    )
                    for key, _mask in ready:
                        stream = key.fileobj
                        try:
                            chunk = os.read(stream.fileno(), 65_536)
                        except BlockingIOError:
                            continue
                        except OSError as exc:
                            raise BuildTargetOutcomeUnknown(
                                "subprocess output evidence could not be read"
                            ) from exc
                        if not chunk:
                            selector.unregister(stream)
                            stream.close()
                            continue
                        admitted = (
                            stdout_evidence.byte_count + stderr_evidence.byte_count
                        )
                        remaining = max(self._spec.max_output_bytes - admitted, 0)
                        evidence = (
                            stdout_evidence
                            if key.data == "stdout"
                            else stderr_evidence
                        )
                        refused = evidence.append(
                            chunk,
                            remaining_bytes=remaining,
                        )
                        if refused and status is BuildTerminalStatus.EXITED:
                            status = BuildTerminalStatus.OUTPUT_LIMIT_EXCEEDED
                            returncode = None
                            _kill_process_group(process.pid)
                            cleanup_deadline = (
                                time.monotonic() + _PROCESS_CLEANUP_GRACE_SECONDS
                            )

                if status in {
                    BuildTerminalStatus.TIMED_OUT,
                    BuildTerminalStatus.OUTPUT_LIMIT_EXCEEDED,
                }:
                    remaining_cleanup = max(
                        0.0,
                        (cleanup_deadline or time.monotonic()) - time.monotonic(),
                    )
                    try:
                        process.wait(timeout=remaining_cleanup)
                    except subprocess.TimeoutExpired as exc:
                        raise BuildTargetOutcomeUnknown(
                            "forced-stop build leader could not be reaped"
                        ) from exc
                elif returncode is None:
                    returncode = process.wait(timeout=_PROCESS_CLEANUP_GRACE_SECONDS)
        finally:
            active_exception = sys.exc_info()[0] is not None
            cleanup_error: Exception | None = None
            for key in list(selector.get_map().values()):
                stream = key.fileobj
                try:
                    selector.unregister(stream)
                except Exception as exc:
                    cleanup_error = cleanup_error or exc
                try:
                    stream.close()
                except OSError as exc:
                    cleanup_error = cleanup_error or exc
            try:
                selector.close()
            except OSError as exc:
                cleanup_error = cleanup_error or exc
            if process is not None:
                try:
                    if process.poll() is None:
                        _kill_process_group(process.pid)
                    # Always wait after the last possible kill. This both reaps the
                    # leader and makes exceptional stream cleanup non-leaking.
                    process.wait(timeout=_PROCESS_CLEANUP_GRACE_SECONDS)
                except (OSError, subprocess.TimeoutExpired) as exc:
                    cleanup_error = cleanup_error or exc
            if cleanup_error is not None and not active_exception:
                raise BuildTargetOutcomeUnknown(
                    "subprocess cleanup could not authoritatively reap the leader"
                ) from cleanup_error

        raw_output_tail = (stdout_evidence.tail + stderr_evidence.tail)[
            -self._spec.output_tail_bytes :
        ]
        output_tail = _decode_bounded_output_tail(
            raw_output_tail,
            max_bytes=self._spec.output_tail_bytes,
        )
        completed_ns = self._monotonic_ns()
        elapsed_ns = max(completed_ns - started_ns, 0)
        completed_at = _logical_completed_at(
            started_at=started_at,
            elapsed_monotonic_ns=elapsed_ns,
            observed_at=self._utc_now(),
        )
        return BuildExecutionResult(
            effect_id=permit.effect_id,
            workload_sha256=permit.workload_sha256,
            intent_sha256=permit.intent_sha256,
            fence_token=permit.fence_token,
            status=status,
            returncode=returncode,
            started_at=started_at,
            completed_at=completed_at,
            elapsed_monotonic_ns=elapsed_ns,
            compute_wall_ms=(elapsed_ns + 999_999) // 1_000_000,
            stdout_sha256=stdout_evidence.sha256,
            stderr_sha256=stderr_evidence.sha256,
            stdout_bytes=stdout_evidence.byte_count,
            stderr_bytes=stderr_evidence.byte_count,
            output_tail=output_tail,
        )

    def _commit_terminal(
        self,
        permit: WorkloadDispatchPermit,
        result: BuildExecutionResult,
        receipt: WorkloadDispatchReceipt,
    ) -> None:
        result_blob = _canonical_bytes(result.to_dict())
        receipt_blob = _canonical_bytes(receipt.to_dict())
        target_mac = self._target_mac(
            effect_id=permit.effect_id,
            scope=permit.scope,
            workload_sha256=permit.workload_sha256,
            intent_sha256=permit.intent_sha256,
            fence_token=permit.fence_token,
            result_sha256=result.evidence_sha256,
            receipt_sha256=receipt.receipt_sha256,
            result_blob_sha256=hashlib.sha256(result_blob).hexdigest(),
            receipt_blob_sha256=hashlib.sha256(receipt_blob).hexdigest(),
        )
        with self._target_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT effect_id, scope, workload_sha256, intent_sha256, "
                "fence_token, status FROM build_effects WHERE effect_id = ?",
                (permit.effect_id,),
            ).fetchone()
            if row is None:
                raise BuildTargetError("durable build claim disappeared")
            self._validate_binding(row, permit)
            if row["status"] != "CLAIMED":
                raise BuildTargetIdentityConflict("build claim was already terminalized")
            updated = connection.execute(
                "UPDATE build_effects SET status = 'TERMINAL', result_blob = ?, "
                "result_sha256 = ?, receipt_blob = ?, receipt_sha256 = ?, "
                "target_mac_sha256 = ? "
                "WHERE effect_id = ? AND status = 'CLAIMED'",
                (
                    sqlite3.Binary(result_blob),
                    result.evidence_sha256,
                    sqlite3.Binary(receipt_blob),
                    receipt.receipt_sha256,
                    target_mac,
                    permit.effect_id,
                ),
            )
            if updated.rowcount != 1:
                raise BuildTargetError("terminal build CAS failed")
            connection.commit()

    def dispatch(self, permit: WorkloadDispatchPermit) -> WorkloadDispatchReceipt:
        if not isinstance(permit, WorkloadDispatchPermit):
            raise TypeError("dispatch requires a WorkloadDispatchPermit")
        if permit.workload_sha256 != self._spec.workload_sha256:
            raise BuildTargetIdentityConflict(
                "permit workload does not bind the registered build execution spec"
            )
        self._input_verifier.verify()
        with self._scope_lock(permit.scope):
            existing = self._claim(permit)
            if existing is not None:
                _result, receipt = self._terminal_values(existing)
                return receipt
            # Close the composition-to-launch race as far as a trusted local workspace
            # permits. A concurrent mutation after this read is outside the v1 contract.
            self._input_verifier.verify()
            if self._failure_inject_after_claim is not None:
                self._failure_inject_after_claim(permit.effect_id)
            result = self._run_subprocess(permit)
            receipt = WorkloadDispatchReceipt(
                operation=permit.operation,
                effect_id=permit.effect_id,
                workload_sha256=permit.workload_sha256,
                fence_token=permit.fence_token,
                intent_sha256=permit.intent_sha256,
                completed_at=result.completed_at,
                evidence_sha256=result.evidence_sha256,
            )
            self._commit_terminal(permit, result, receipt)
        if self._failure_inject_after_terminal_commit is not None:
            self._failure_inject_after_terminal_commit(result)
        return receipt

    def lookup(
        self,
        reference: WorkloadDispatchIntentReference,
    ) -> WorkloadDispatchReceipt | None:
        row = self._load_row(reference.effect_id)
        if row is None:
            return None
        self._validate_binding(row, reference)
        _result, receipt = self._terminal_values(row)
        return receipt

    def lookup_usage(
        self,
        reference: WorkloadDispatchIntentReference,
    ) -> ResourceUsage | None:
        row = self._load_row(reference.effect_id)
        if row is None:
            return None
        self._validate_binding(row, reference)
        result, _receipt = self._terminal_values(row)
        return result.usage

    def load_terminal_result(
        self,
        *,
        effect_id: str,
        workload_sha256: str,
    ) -> tuple[BuildExecutionResult, WorkloadDispatchReceipt]:
        row = self._load_row(effect_id)
        if row is None:
            raise BuildTargetOutcomeUnknown("target has no authoritative effect record")
        if row["workload_sha256"] != workload_sha256:
            raise BuildTargetIdentityConflict("terminal workload identity diverged")
        return self._terminal_values(row)

    def verify_inputs(self) -> None:
        self._input_verifier.verify()


def _settlement_receipt_sha256(state, grant_id: str) -> str:
    for record in reversed(state.command_records):
        command = record.transition.command
        if isinstance(command, SettleGrant) and command.grant_id == grant_id:
            return record.receipt_sha256
    raise ResourceBuildConfigError("terminal resource grant has no settlement receipt")


def _recorded_command(state, command_id: str):
    """Return the exact retained command payload for restart-safe composition."""

    for record in state.command_records:
        command = record.transition.command
        if command.command_id == command_id:
            return command
    return None


def _translated_resource_journal_error(
    error: ResourceJournalError | TrustedAnchorCorruption,
) -> ResourceBuildConfigError | ResourceBuildOutcomeUnknown:
    """Map durable-store failures to the public build-service taxonomy."""

    if isinstance(error, (RevisionConflict, TrustedAnchorUnavailable)):
        return ResourceBuildOutcomeUnknown(str(error))
    return ResourceBuildConfigError(str(error))


class ResourceGatedBuildRunner:
    """Application service: admit -> authorize -> effect -> measure -> settle."""

    def __init__(
        self,
        *,
        scope: str,
        journal: ResourceJournalPort,
        gate: ResourceExecutionGate,
        effect: BuildEffectPort,
        request: RequestGrant,
        start: StartGrant,
    ) -> None:
        _require_text_identity(scope, "scope")
        if not isinstance(request, RequestGrant):
            raise TypeError("request must be a RequestGrant")
        if not isinstance(start, StartGrant):
            raise TypeError("start must be a StartGrant")
        expected = (
            request.grant_id,
            request.fence_token,
            request.estimate.workload_sha256,
            request.estimate.adapter,
            request.estimate.adapter_version,
        )
        actual = (
            start.grant_id,
            start.fence_token,
            start.workload_sha256,
            effect.adapter,
            effect.adapter_version,
        )
        if actual != expected or start.command_id == request.command_id:
            raise ResourceBuildConfigError(
                "RequestGrant, StartGrant, and build adapter bindings diverge"
            )
        if request.estimate.workload_sha256 != effect.spec.workload_sha256:
            raise ResourceBuildConfigError("estimate does not bind the build spec")
        self._scope = scope
        self._journal = journal
        self._gate = gate
        self._effect = effect
        self._request = request
        self._start = start

    @staticmethod
    def _find_grant(state, grant_id: str):
        return next((grant for grant in state.grants if grant.grant_id == grant_id), None)

    def _terminal_run(self, state) -> BuildRun:
        grant = state.grant(self._request.grant_id)
        result, receipt = self._effect.load_terminal_result(
            effect_id=self._start.command_id,
            workload_sha256=self._start.workload_sha256,
        )
        usage = result.usage
        if (
            grant.actual != usage.actual
            or grant.measured_at != usage.measured_at
            or grant.measurement_sha256 != usage.measurement_sha256
            or grant.evidence_sha256 != usage.evidence_sha256
        ):
            raise ResourceBuildConfigError(
                "terminal target evidence diverges from resource settlement"
            )
        if grant.status is GrantStatus.QUARANTINED_OVERRUN:
            raise ResourceBuildOverrun(
                "measured build use exceeded its reservation; budget is frozen"
            )
        if grant.status is not GrantStatus.SETTLED:
            raise ResourceBuildOutcomeUnknown(
                f"grant is not normally settled: {grant.status.value}"
            )
        terminal_returncode = {
            BuildTerminalStatus.TIMED_OUT: 124,
            BuildTerminalStatus.OUTPUT_LIMIT_EXCEEDED: 125,
        }.get(result.status, result.returncode)
        if terminal_returncode is None:
            raise ResourceBuildConfigError(
                "terminal build status has no legacy-compatible return code"
            )
        return BuildRun(
            output=result.output_tail,
            returncode=terminal_returncode,
            timed_out=result.status is BuildTerminalStatus.TIMED_OUT,
            effect_id=result.effect_id,
            workload_sha256=result.workload_sha256,
            intent_sha256=result.intent_sha256,
            dispatch_receipt_sha256=receipt.receipt_sha256,
            evidence_sha256=result.evidence_sha256,
            measurement_sha256=usage.measurement_sha256,
            settlement_receipt_sha256=_settlement_receipt_sha256(
                state, self._request.grant_id
            ),
        )

    def __call__(self, command: str) -> BuildRun:
        try:
            return self._run(command)
        except (ResourceJournalError, TrustedAnchorCorruption) as exc:
            raise _translated_resource_journal_error(exc) from exc

    def _run(self, command: str) -> BuildRun:
        if command != self._effect.spec.command:
            raise ResourceBuildConfigError(
                "harness build command diverges from the admitted workload"
            )
        try:
            self._effect.verify_inputs()
        except BuildInputManifestError as exc:
            raise ResourceBuildConfigError(str(exc)) from exc
        snapshot = self._journal.load(self._scope)
        authority = authority_from_snapshot(snapshot)
        require_current_confirmed_authority(snapshot.state, authority)
        grant = self._find_grant(snapshot.state, self._request.grant_id)
        if grant is None:
            reserved = self._journal.apply(
                self._scope,
                self._request,
                expected_revision=snapshot.state.revision,
            )
            if reserved.decision.rejection is not None:
                raise reserved.decision.rejection
            if reserved.anchor_status is not AnchorStatus.CONFIRMED:
                raise ResourceBuildOutcomeUnknown(
                    "resource reservation is not externally confirmed"
                )
            snapshot = self._journal.load(self._scope)
            grant = snapshot.state.grant(self._request.grant_id)

        if grant.status in {GrantStatus.SETTLED, GrantStatus.QUARANTINED_OVERRUN}:
            return self._terminal_run(snapshot.state)

        receipt: WorkloadDispatchReceipt | None = None
        if grant.status is GrantStatus.RESERVED:
            authorization = self._gate.prepare(
                self._start,
                expected_revision=snapshot.state.revision,
            )
            try:
                receipt = self._gate.dispatch(authorization)
            except DispatchOutcomeUnknown:
                try:
                    receipt = self._gate.reconcile(self._start.command_id)
                except DispatchOutcomeUnknown as exc:
                    raise ResourceBuildOutcomeUnknown(str(exc)) from exc
        elif grant.status in {
            GrantStatus.IN_USE,
            GrantStatus.RECONCILIATION_REQUIRED,
        }:
            try:
                receipt = self._gate.reconcile(self._start.command_id)
            except DispatchOutcomeUnknown as exc:
                raise ResourceBuildOutcomeUnknown(str(exc)) from exc
        else:
            raise ResourceBuildOutcomeUnknown(
                f"resource grant cannot execute from {grant.status.value}"
            )
        if receipt is None:
            raise ResourceBuildOutcomeUnknown(
                "target authoritatively has no terminal receipt; redispatch is forbidden"
            )

        settled = self._gate.settle(self._start.command_id)
        if settled.anchor_status is not AnchorStatus.CONFIRMED:
            raise ResourceBuildOutcomeUnknown("resource settlement is not confirmed")
        return self._terminal_run(settled.state)


_RESOURCE_CONFIGURATION_KEYS = frozenset({
    "LAKATOTREE_RESOURCE_BUILD_DIR",
    "LAKATOTREE_RESOURCE_ANCHOR_KEY_HEX",
    "LAKATOTREE_RESOURCE_PERMIT_KEY_HEX",
    "LAKATOTREE_RESOURCE_COMPUTE_CAP_MS",
    "LAKATOTREE_BUILD_INPUT_MANIFEST",
})


def _is_sensitive_child_environment_key(name: str) -> bool:
    upper = name.upper()
    if upper in {"AUTH", "AUTHORIZATION"} or upper.endswith(("_AUTH", "_KEY")):
        return True
    return any(fragment in upper for fragment in (
        "API_KEY",
        "ACCESS_KEY",
        "AUTH_TOKEN",
        "AUTHORIZATION",
        "COOKIE",
        "CREDENTIAL",
        "PASSWORD",
        "SECRET",
        "TOKEN",
    ))


def closed_build_environment(environment: Mapping[str, str]) -> dict[str, str]:
    """Return the only environment mapping allowed across the build effect port."""

    return {
        key: value
        for key, value in environment.items()
        if key not in _RESOURCE_CONFIGURATION_KEYS
        and not _is_sensitive_child_environment_key(key)
    }


def _configuration_key(
    environment: Mapping[str, str],
    name: str,
    *,
    exact_bytes: int | None = None,
    minimum_bytes: int | None = None,
) -> bytes:
    raw = environment.get(name)
    if not isinstance(raw, str) or not raw:
        raise ResourceBuildConfigError(f"{name} is required when resource build is enabled")
    try:
        value = bytes.fromhex(raw)
    except ValueError as exc:
        raise ResourceBuildConfigError(f"{name} must be hexadecimal") from exc
    if exact_bytes is not None and len(value) != exact_bytes:
        raise ResourceBuildConfigError(f"{name} must contain exactly {exact_bytes} bytes")
    if minimum_bytes is not None and len(value) < minimum_bytes:
        raise ResourceBuildConfigError(f"{name} must contain at least {minimum_bytes} bytes")
    return value


def _positive_configuration_integer(
    environment: Mapping[str, str],
    name: str,
) -> int:
    raw = environment.get(name)
    try:
        value = int(raw) if raw is not None else 0
    except (TypeError, ValueError) as exc:
        raise ResourceBuildConfigError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise ResourceBuildConfigError(f"{name} must be a positive integer")
    return value


def resource_root_path_violation(
    *,
    prospective: Path,
    cwd: Path,
    home: Path,
) -> str | None:
    """Pure path-policy decision for the durable resource authority root."""

    if prospective == Path(prospective.anchor) or prospective == home:
        return "resource build directory cannot be a broad root/home"
    if cwd == prospective or cwd.is_relative_to(prospective):
        return "resource build directory cannot contain the build working tree"
    return None


def resource_root_metadata_violation(
    *,
    mode: int,
    owner_uid: int,
    current_uid: int,
) -> str | None:
    """Pure ownership/type/mode decision over one lstat snapshot."""

    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        return "resource build directory must be a real directory"
    if owner_uid != current_uid:
        return "resource build directory must be owned by the current user"
    if stat.S_IMODE(mode) & 0o077:
        return "resource build directory must not grant group/other permissions"
    return None


def _prepare_resource_root(
    raw_root: str,
    *,
    cwd: Path,
) -> Path:
    """Create or validate the owner-private resource authority directory."""

    candidate = Path(raw_root).expanduser()
    prospective = candidate.resolve(strict=False)
    path_violation = resource_root_path_violation(
        prospective=prospective,
        cwd=cwd,
        home=Path.home().resolve(),
    )
    if path_violation is not None:
        raise ResourceBuildConfigError(path_violation)
    try:
        if candidate.is_symlink():
            raise ResourceBuildConfigError(
                "resource build directory cannot be a symbolic link"
            )
        candidate.mkdir(parents=True, exist_ok=True, mode=0o700)
        metadata = candidate.lstat()
        root = candidate.resolve(strict=True)
    except ResourceBuildConfigError:
        raise
    except OSError as exc:
        raise ResourceBuildConfigError(
            "resource build directory cannot be created or inspected"
        ) from exc
    metadata_violation = resource_root_metadata_violation(
        mode=metadata.st_mode,
        owner_uid=metadata.st_uid,
        current_uid=os.getuid(),
    )
    if metadata_violation is not None:
        raise ResourceBuildConfigError(metadata_violation)
    return root


def resource_gated_build_runner_from_environment(
    *,
    tree: str,
    tag: str,
    command: str,
    timeout_seconds: int,
    environment: Mapping[str, str] | None = None,
) -> ResourceGatedBuildRunner | None:
    """Build the opt-in production composition, or return ``None`` for legacy mode.

    Enabling is explicit through ``LAKATOTREE_RESOURCE_BUILD_DIR``.  Once enabled,
    all authority, cap, and input-manifest values are mandatory and fail closed;
    signing material is removed from the child subprocess environment.
    """

    source_environment = dict(os.environ if environment is None else environment)
    raw_root = source_environment.get("LAKATOTREE_RESOURCE_BUILD_DIR")
    if raw_root is None or raw_root == "":
        return None
    if not isinstance(tree, str) or not tree or not isinstance(tag, str) or not tag:
        raise ResourceBuildConfigError("tree and tag are required for build identity")
    anchor_key = _configuration_key(
        source_environment,
        "LAKATOTREE_RESOURCE_ANCHOR_KEY_HEX",
        exact_bytes=32,
    )
    permit_key = _configuration_key(
        source_environment,
        "LAKATOTREE_RESOURCE_PERMIT_KEY_HEX",
        minimum_bytes=32,
    )
    cap_ms = _positive_configuration_integer(
        source_environment,
        "LAKATOTREE_RESOURCE_COMPUTE_CAP_MS",
    )
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int)
        or timeout_seconds <= 0
    ):
        raise ResourceBuildConfigError("build timeout must be a positive integer")
    reservation_ms = timeout_seconds * 1000 + 1000
    if reservation_ms > cap_ms:
        raise ResourceBuildConfigError(
            "build timeout reservation plus 1000ms reap margin exceeds compute cap"
        )
    cwd = Path.cwd().resolve()
    root = _prepare_resource_root(raw_root, cwd=cwd)
    manifest_path = source_environment.get("LAKATOTREE_BUILD_INPUT_MANIFEST")
    if not isinstance(manifest_path, str) or not manifest_path:
        raise ResourceBuildConfigError(
            "LAKATOTREE_BUILD_INPUT_MANIFEST is required when resource build is enabled"
        )
    try:
        input_manifest = VerifiedBuildInputManifest.load(manifest_path, root=cwd)
    except BuildInputManifestError as exc:
        raise ResourceBuildConfigError(str(exc)) from exc
    isolation = DarwinSandboxExecIsolation(root)
    child_environment = closed_build_environment(source_environment)
    spec = BuildExecutionSpec(
        command=command,
        cwd=str(cwd),
        shell="/bin/sh",
        timeout_seconds=timeout_seconds,
        environment_sha256=environment_sha256(child_environment),
        input_manifest_sha256=input_manifest.manifest_sha256,
        isolation_adapter=isolation.adapter,
        isolation_version=isolation.adapter_version,
        isolation_policy_sha256=isolation.policy_sha256,
    )
    identity = hashlib.sha256(
        f"{tree}\0{tag}\0{spec.workload_sha256}".encode("utf-8")
    ).hexdigest()
    scope = f"harness-build:{hashlib.sha256(tree.encode('utf-8')).hexdigest()}"
    effect_id = f"build:{identity}"
    grant_id = f"grant:{identity}"
    effect = SQLiteFencedBuildEffect(
        root / "build-target.sqlite3",
        spec=spec,
        environment=child_environment,
        isolation=isolation,
        input_verifier=input_manifest,
        authentication_key=hmac.new(
            permit_key,
            b"lakatotree-local-build-target-key\x00v1\n",
            hashlib.sha256,
        ).digest(),
    )
    fence_token = effect.allocate_fence(scope=scope, effect_id=effect_id)
    try:
        journal = SQLiteResourceJournal(
            root / "resource.sqlite3",
            trusted_anchor=SignedAppendOnlyFileAnchor(
                root / "resource-anchor",
                signing_key=anchor_key,
            ),
        )
        state = ResourceState.create(
            budget_id=f"budget:{hashlib.sha256(scope.encode('utf-8')).hexdigest()}",
            scope=scope,
            epoch=1,
            hard_caps=ResourceVector(compute_wall_ms=cap_ms),
        )
        try:
            snapshot = journal.load(scope)
        except JournalNotInitialized:
            snapshot = journal.initialize(state)
    except (ResourceJournalError, TrustedAnchorCorruption) as exc:
        raise _translated_resource_journal_error(exc) from exc
    if snapshot.state.budget != state.budget:
        raise ResourceBuildConfigError(
            "existing resource scope has a different cap/epoch; use a new resource "
            "directory/tree or restore the original cap"
        )

    observed = datetime.now(timezone.utc)
    expires = observed + timedelta(seconds=max(300, timeout_seconds + 60))
    observed_at = observed.isoformat(timespec="microseconds").replace("+00:00", "Z")
    expires_at = expires.isoformat(timespec="microseconds").replace("+00:00", "Z")
    fresh_request = RequestGrant(
        command_id=f"request:{identity}",
        grant_id=grant_id,
        fence_token=fence_token,
        observed_at=observed_at,
        expires_at=expires_at,
        estimate=ResourceEstimate(
            work_id=f"work:{identity}",
            attempt_id=f"attempt:{identity}",
            workload_sha256=spec.workload_sha256,
            adapter=effect.adapter,
            adapter_version=effect.adapter_version,
            upper_bound=ResourceVector(compute_wall_ms=reservation_ms),
            valid_until=expires_at,
        ),
    )
    retained_request = _recorded_command(snapshot.state, fresh_request.command_id)
    if retained_request is None:
        request = fresh_request
    elif not isinstance(retained_request, RequestGrant):
        raise ResourceBuildConfigError("retained request command has a different type")
    else:
        request = retained_request
        expected_request_binding = (
            fresh_request.command_id,
            fresh_request.grant_id,
            fresh_request.fence_token,
            fresh_request.estimate.work_id,
            fresh_request.estimate.attempt_id,
            fresh_request.estimate.workload_sha256,
            fresh_request.estimate.adapter,
            fresh_request.estimate.adapter_version,
            fresh_request.estimate.upper_bound,
        )
        retained_request_binding = (
            request.command_id,
            request.grant_id,
            request.fence_token,
            request.estimate.work_id,
            request.estimate.attempt_id,
            request.estimate.workload_sha256,
            request.estimate.adapter,
            request.estimate.adapter_version,
            request.estimate.upper_bound,
        )
        if retained_request_binding != expected_request_binding:
            raise ResourceBuildConfigError(
                "retained resource request diverges from the current build binding"
            )
        if request.expires_at != request.estimate.valid_until:
            raise ResourceBuildConfigError(
                "retained resource request has divergent expiry evidence"
            )

    fresh_start = StartGrant(
        command_id=effect_id,
        grant_id=grant_id,
        fence_token=fence_token,
        workload_sha256=spec.workload_sha256,
        observed_at=observed_at,
    )
    retained_start = _recorded_command(snapshot.state, fresh_start.command_id)
    if retained_start is None:
        start = fresh_start
    elif not isinstance(retained_start, StartGrant):
        raise ResourceBuildConfigError("retained start command has a different type")
    else:
        start = retained_start
        if (
            start.command_id,
            start.grant_id,
            start.fence_token,
            start.workload_sha256,
        ) != (
            fresh_start.command_id,
            fresh_start.grant_id,
            fresh_start.fence_token,
            fresh_start.workload_sha256,
        ):
            raise ResourceBuildConfigError(
                "retained resource start diverges from the current build binding"
            )
    gate = ResourceExecutionGate(
        scope=scope,
        journal=journal,
        effect=effect,
        clock=_SystemClock(),
        permit_authenticator=HMACPermitAuthenticator(
            signing_key=permit_key,
            issuer=f"lakatotree:harness-build:{identity[:24]}",
        ),
        settlement_effect=effect,
    )
    return ResourceGatedBuildRunner(
        scope=scope,
        journal=journal,
        gate=gate,
        effect=effect,
        request=request,
        start=start,
    )


__all__ = [
    "BuildEffectPort",
    "BuildExecutionIsolationPort",
    "BuildInputManifestError",
    "BuildInputVerifierPort",
    "BuildTargetError",
    "BuildTargetIdentityConflict",
    "BuildTargetOutcomeUnknown",
    "ResourceGatedBuildRunner",
    "SQLiteFencedBuildEffect",
    "StaleBuildFence",
    "VerifiedBuildInputManifest",
    "closed_build_environment",
    "DarwinSandboxExecIsolation",
    "darwin_sandbox_argv",
    "darwin_sandbox_profile",
    "resource_root_metadata_violation",
    "resource_root_path_violation",
    "resource_gated_build_runner_from_environment",
]
