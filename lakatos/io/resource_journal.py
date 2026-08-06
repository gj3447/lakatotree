"""Durable state-plane adapter for :mod:`lakatos.resource_coordination`.

The deterministic resource kernel owns admission and lifecycle semantics.  This
module owns the I/O boundary: canonical bytes, a local SQLite revision-CAS
journal, an atomic anchor outbox, and reconciliation against an independently
stored signed chain head.

SQLite and the external anchor are intentionally *not* a distributed
transaction.  A command, transition, receipt, head update, and pending anchor
intent commit atomically first.  External anchoring happens afterwards and is
idempotently reconcilable.  Confirmation is evidence about durable history, not
an execution permit: the future effect adapter must mint and revalidate a fenced,
operation-specific permit at dispatch time.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import string
from typing import Callable, Iterator, Protocol

try:  # POSIX is the supported substrate for the append-only file authority.
    import fcntl
except ImportError:  # pragma: no cover - hosted CI and deployment are POSIX.
    fcntl = None

from lakatos.resource_coordination import (
    BudgetStatus,
    CancelGrant,
    DeadlineObserved,
    Decision,
    ENGINE_RULE_SHA256,
    GrantStatus,
    RequestGrant,
    ResourceBudget,
    ResourceCommand,
    ResourceEstimate,
    ResourceGrant,
    ResourceReceipt,
    ResourceState,
    ResourceTransition,
    ResourceUsage,
    ResourceVector,
    SCHEMA_VERSION,
    SettleGrant,
    StartGrant,
    UsageUnknown,
    decide,
    evolve,
)
from lakatos.write_cert import (
    ed25519_public_key,
    ed25519_sign,
    ed25519_verify,
)


JOURNAL_SCHEMA_VERSION = "lakatotree.resource-journal/v1"
CODEC_VERSION = "lakatotree.resource-journal-codec/v1"
ANCHOR_SCHEMA_VERSION = "lakatotree.resource-anchor/v1"

_APPLICATION_ID = 0x4C4B5253  # ASCII "LKRS"; a signed 32-bit SQLite application id.
_USER_VERSION = 1
_JOURNAL_DOMAIN = b"lakatotree-resource-journal\x00v1\n"
_ANCHOR_DOMAIN = b"lakatotree-resource-anchor\x00v1\n"
_HEX = frozenset(string.hexdigits)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_sha256(value: str | None, label: str, *, optional: bool = False) -> None:
    if value is None and optional:
        return
    if (
        not isinstance(value, str)
        or len(value) != 64
        or value != value.lower()
        or any(character not in _HEX for character in value)
    ):
        raise ValueError(f"{label} must be a lowercase hexadecimal SHA-256")


def _require_identifier(value: str, label: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 256
        or not value.isprintable()
    ):
        raise ValueError(f"{label} must be a printable non-empty string <= 256 chars")


def _expect_mapping(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _expect_keys(value: dict, expected: set[str], label: str) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        unknown = sorted(set(value) - expected)
        raise ValueError(f"{label} fields diverged: missing={missing} unknown={unknown}")


def _decode_canonical_blob(value: object, label: str) -> dict:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise JournalCorruption(f"{label} is not stored as bytes")
    raw = bytes(value)
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JournalCorruption(f"{label} is not canonical UTF-8 JSON") from exc
    mapping = _expect_mapping(decoded, label)
    if _canonical_bytes(mapping) != raw:
        raise JournalCorruption(f"{label} bytes are not canonical")
    return mapping


class AnchorStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"


class ResourceJournalError(RuntimeError):
    """Base class for durable resource journal failures."""


class JournalSchemaMismatch(ResourceJournalError):
    pass


class JournalNotInitialized(ResourceJournalError):
    pass


class JournalCorruption(ResourceJournalError):
    pass


class BudgetIdentityConflict(ResourceJournalError):
    pass


class RevisionConflict(ResourceJournalError):
    def __init__(self, expected_revision: int, actual_revision: int):
        super().__init__(
            f"resource revision conflict: expected {expected_revision}, "
            f"actual {actual_revision}"
        )
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision


class TrustedAnchorUnavailable(ResourceJournalError):
    pass


class AnchorConflict(ResourceJournalError):
    pass


class DatabaseRollbackDetected(ResourceJournalError):
    pass


class HistoryReplacementDetected(ResourceJournalError):
    pass


class UnanchoredHistoryGap(ResourceJournalError):
    pass


class TrustedAnchorCorruption(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ResourceCheckpoint:
    """Content-addressed external commitment for one journal revision."""

    schema_version: str
    codec_version: str
    kernel_schema_version: str
    engine_rule_sha256: str
    budget_id: str
    scope: str
    epoch: int
    revision: int
    state_sha256: str
    journal_head_sha256: str
    previous_journal_head_sha256: str | None
    command_id: str | None
    command_sha256: str | None
    transition_sha256: str | None
    receipt_sha256: str | None

    def __post_init__(self) -> None:
        if self.schema_version != ANCHOR_SCHEMA_VERSION:
            raise ValueError("unsupported resource checkpoint schema")
        if self.codec_version != CODEC_VERSION:
            raise ValueError("unsupported resource checkpoint codec")
        if self.kernel_schema_version != SCHEMA_VERSION:
            raise ValueError("resource checkpoint kernel schema mismatch")
        if self.engine_rule_sha256 != ENGINE_RULE_SHA256:
            raise ValueError("resource checkpoint engine rule mismatch")
        _require_identifier(self.budget_id, "checkpoint.budget_id")
        _require_identifier(self.scope, "checkpoint.scope")
        if isinstance(self.epoch, bool) or not isinstance(self.epoch, int) or self.epoch < 1:
            raise ValueError("checkpoint.epoch must be an integer >= 1")
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 0
        ):
            raise ValueError("checkpoint.revision must be an integer >= 0")
        _require_sha256(self.state_sha256, "checkpoint.state_sha256")
        _require_sha256(self.journal_head_sha256, "checkpoint.journal_head_sha256")
        _require_sha256(
            self.previous_journal_head_sha256,
            "checkpoint.previous_journal_head_sha256",
            optional=True,
        )
        for label, value in (
            ("command_sha256", self.command_sha256),
            ("transition_sha256", self.transition_sha256),
            ("receipt_sha256", self.receipt_sha256),
        ):
            _require_sha256(value, f"checkpoint.{label}", optional=True)
        if self.revision == 0:
            if any(
                value is not None
                for value in (
                    self.previous_journal_head_sha256,
                    self.command_id,
                    self.command_sha256,
                    self.transition_sha256,
                    self.receipt_sha256,
                )
            ):
                raise ValueError("genesis checkpoint cannot bind a command or predecessor")
        else:
            if self.previous_journal_head_sha256 is None:
                raise ValueError("non-genesis checkpoint requires its predecessor head")
            if self.command_id is None:
                raise ValueError("non-genesis checkpoint requires command_id")
            _require_identifier(self.command_id, "checkpoint.command_id")
            if any(
                value is None
                for value in (
                    self.command_sha256,
                    self.transition_sha256,
                    self.receipt_sha256,
                )
            ):
                raise ValueError("non-genesis checkpoint requires command/transition hashes")

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "codec_version": self.codec_version,
            "kernel_schema_version": self.kernel_schema_version,
            "engine_rule_sha256": self.engine_rule_sha256,
            "budget_id": self.budget_id,
            "scope": self.scope,
            "epoch": self.epoch,
            "revision": self.revision,
            "state_sha256": self.state_sha256,
            "journal_head_sha256": self.journal_head_sha256,
            "previous_journal_head_sha256": self.previous_journal_head_sha256,
            "command_id": self.command_id,
            "command_sha256": self.command_sha256,
            "transition_sha256": self.transition_sha256,
            "receipt_sha256": self.receipt_sha256,
        }

    @property
    def checkpoint_sha256(self) -> str:
        return _sha256_bytes(_canonical_bytes(self.to_dict()))


@dataclass(frozen=True, slots=True)
class JournalSnapshot:
    state: ResourceState
    checkpoint: ResourceCheckpoint
    anchor_status: AnchorStatus


@dataclass(frozen=True, slots=True)
class DurableDecision:
    state: ResourceState
    decision: Decision
    checkpoint: ResourceCheckpoint
    anchor_status: AnchorStatus


@dataclass(frozen=True, slots=True)
class AnchorReconcileResult:
    confirmed_revisions: tuple[int, ...]
    snapshot: JournalSnapshot


class TrustedAnchorStore(Protocol):
    def read(self, scope: str) -> ResourceCheckpoint | None:
        ...

    def compare_and_set(
        self,
        *,
        expected_journal_head_sha256: str | None,
        checkpoint: ResourceCheckpoint,
    ) -> ResourceCheckpoint:
        ...


def _checkpoint_from_dict(value: dict) -> ResourceCheckpoint:
    expected = {
        "schema_version",
        "codec_version",
        "kernel_schema_version",
        "engine_rule_sha256",
        "budget_id",
        "scope",
        "epoch",
        "revision",
        "state_sha256",
        "journal_head_sha256",
        "previous_journal_head_sha256",
        "command_id",
        "command_sha256",
        "transition_sha256",
        "receipt_sha256",
    }
    _expect_keys(value, expected, "resource checkpoint")
    return ResourceCheckpoint(**value)


class SignedAppendOnlyFileAnchor:
    """Signed, append-only reference implementation of ``TrustedAnchorStore``.

    The directory must be a trust boundary independent from the SQLite file.
    Each checkpoint is an immutable signed file; reads scan the complete chain
    instead of trusting a rollbackable mutable head pointer.  Production callers
    should place the directory on separately administered or append-only storage,
    or replace this adapter with a remote CAS authority.
    """

    def __init__(
        self,
        directory: str | os.PathLike[str],
        *,
        signing_key: bytes | None = None,
        verify_key: bytes | None = None,
    ) -> None:
        if fcntl is None:
            raise OSError("SignedAppendOnlyFileAnchor requires POSIX file locking")
        if signing_key is None and verify_key is None:
            raise ValueError("an anchor signing_key or pinned verify_key is required")
        self._directory = Path(directory)
        self._directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._signing_key = signing_key
        derived = ed25519_public_key(signing_key) if signing_key is not None else None
        if verify_key is not None and derived is not None and verify_key != derived:
            raise ValueError("anchor signing key does not match the pinned verify key")
        self._verify_key = verify_key if verify_key is not None else derived
        assert self._verify_key is not None
        if len(self._verify_key) != 32:
            raise ValueError("anchor verify_key must contain 32 bytes")

    @staticmethod
    def _scope_key(scope: str) -> str:
        _require_identifier(scope, "anchor scope")
        return hashlib.sha256(scope.encode("utf-8")).hexdigest()

    def _record_path(self, checkpoint: ResourceCheckpoint) -> Path:
        return self._directory / (
            f"{self._scope_key(checkpoint.scope)}."
            f"{checkpoint.revision:020d}."
            f"{checkpoint.journal_head_sha256}.json"
        )

    @contextmanager
    def _locked(self, scope: str, *, exclusive: bool) -> Iterator[None]:
        key = self._scope_key(scope)
        lock_path = self._directory / f".{key}.lock"
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            fcntl.flock(descriptor, operation)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _decode_record(self, path: Path) -> ResourceCheckpoint:
        try:
            raw = path.read_bytes()
            envelope = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TrustedAnchorCorruption(f"anchor record is unreadable: {path.name}") from exc
        if not isinstance(envelope, dict) or _canonical_bytes(envelope) != raw:
            raise TrustedAnchorCorruption(f"anchor record is not canonical: {path.name}")
        try:
            _expect_keys(
                envelope,
                {"checkpoint", "signature_algorithm", "signer_public_key", "signature"},
                "signed anchor",
            )
            if envelope["signature_algorithm"] != "Ed25519":
                raise ValueError("unsupported anchor signature algorithm")
            signer = bytes.fromhex(envelope["signer_public_key"])
            signature = bytes.fromhex(envelope["signature"])
            if signer != self._verify_key:
                raise ValueError("anchor signer is not the pinned authority")
            checkpoint = _checkpoint_from_dict(
                _expect_mapping(envelope["checkpoint"], "anchor checkpoint")
            )
            signing_bytes = _ANCHOR_DOMAIN + _canonical_bytes(checkpoint.to_dict())
            if not ed25519_verify(self._verify_key, signing_bytes, signature):
                raise ValueError("anchor signature is invalid")
            if path != self._record_path(checkpoint):
                raise ValueError("anchor filename does not match its signed checkpoint")
            return checkpoint
        except (TypeError, ValueError) as exc:
            raise TrustedAnchorCorruption(f"anchor verification failed: {path.name}") from exc

    def _read_all_unlocked(self, scope: str) -> tuple[ResourceCheckpoint, ...]:
        prefix = self._scope_key(scope)
        paths = sorted(self._directory.glob(f"{prefix}.*.json"))
        checkpoints = [self._decode_record(path) for path in paths]
        if not checkpoints:
            return ()
        by_revision: dict[int, ResourceCheckpoint] = {}
        for checkpoint in checkpoints:
            if checkpoint.scope != scope:
                raise TrustedAnchorCorruption("anchor scope hash collision or substitution")
            previous = by_revision.get(checkpoint.revision)
            if previous is not None and previous != checkpoint:
                raise AnchorConflict(
                    f"external anchor fork at revision {checkpoint.revision}"
                )
            by_revision[checkpoint.revision] = checkpoint
        revisions = sorted(by_revision)
        if revisions != list(range(revisions[-1] + 1)):
            raise TrustedAnchorCorruption("external anchor chain has a revision gap")
        ordered = tuple(by_revision[revision] for revision in revisions)
        for index, checkpoint in enumerate(ordered):
            if index == 0:
                if checkpoint.previous_journal_head_sha256 is not None:
                    raise TrustedAnchorCorruption("external genesis has a predecessor")
                continue
            previous = ordered[index - 1]
            if (
                checkpoint.budget_id != previous.budget_id
                or checkpoint.scope != previous.scope
                or checkpoint.epoch != previous.epoch
                or checkpoint.previous_journal_head_sha256
                != previous.journal_head_sha256
            ):
                raise TrustedAnchorCorruption("external anchor chain is not contiguous")
        return ordered

    def read(self, scope: str) -> ResourceCheckpoint | None:
        with self._locked(scope, exclusive=False):
            checkpoints = self._read_all_unlocked(scope)
        return checkpoints[-1] if checkpoints else None

    def compare_and_set(
        self,
        *,
        expected_journal_head_sha256: str | None,
        checkpoint: ResourceCheckpoint,
    ) -> ResourceCheckpoint:
        if self._signing_key is None:
            raise TrustedAnchorUnavailable("anchor is configured for verification only")
        if expected_journal_head_sha256 is not None:
            _require_sha256(expected_journal_head_sha256, "expected anchor head")
        with self._locked(checkpoint.scope, exclusive=True):
            checkpoints = self._read_all_unlocked(checkpoint.scope)
            current = checkpoints[-1] if checkpoints else None
            if current == checkpoint:
                return current
            if current is None:
                if expected_journal_head_sha256 is not None or checkpoint.revision != 0:
                    raise AnchorConflict("external anchor genesis CAS predecessor mismatch")
            else:
                if (
                    current.journal_head_sha256 != expected_journal_head_sha256
                    or checkpoint.previous_journal_head_sha256
                    != expected_journal_head_sha256
                    or checkpoint.revision != current.revision + 1
                    or checkpoint.budget_id != current.budget_id
                    or checkpoint.epoch != current.epoch
                ):
                    raise AnchorConflict("external anchor predecessor CAS failed")
            signing_bytes = _ANCHOR_DOMAIN + _canonical_bytes(checkpoint.to_dict())
            envelope = {
                "checkpoint": checkpoint.to_dict(),
                "signature_algorithm": "Ed25519",
                "signer_public_key": self._verify_key.hex(),
                "signature": ed25519_sign(self._signing_key, signing_bytes).hex(),
            }
            raw = _canonical_bytes(envelope)
            destination = self._record_path(checkpoint)
            temporary = self._directory / (
                f".anchor-{os.getpid()}-{id(checkpoint):x}-{checkpoint.revision}.tmp"
            )
            descriptor = None
            try:
                descriptor = os.open(
                    temporary,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
                offset = 0
                while offset < len(raw):
                    offset += os.write(descriptor, raw[offset:])
                os.fsync(descriptor)
                os.close(descriptor)
                descriptor = None
                os.link(temporary, destination)
                os.unlink(temporary)
                directory_fd = os.open(self._directory, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except FileExistsError:
                if temporary.exists():
                    temporary.unlink()
                existing = self._decode_record(destination)
                if existing != checkpoint:
                    raise AnchorConflict("external anchor identity was reused")
            finally:
                if descriptor is not None:
                    os.close(descriptor)
                if temporary.exists():
                    temporary.unlink()
            stored = self._decode_record(destination)
            if stored != checkpoint:
                raise TrustedAnchorCorruption("external anchor exact readback diverged")
            return stored


def _budget_blob(budget: ResourceBudget) -> bytes:
    return _canonical_bytes({"codec_version": CODEC_VERSION, "budget": budget.to_dict()})


def _budget_from_blob(blob: object) -> ResourceBudget:
    envelope = _decode_canonical_blob(blob, "resource budget")
    _expect_keys(envelope, {"codec_version", "budget"}, "resource budget envelope")
    if envelope["codec_version"] != CODEC_VERSION:
        raise JournalCorruption("resource budget codec is unsupported")
    value = _expect_mapping(envelope["budget"], "resource budget payload")
    _expect_keys(
        value,
        {"schema_version", "budget_id", "scope", "epoch", "hard_caps"},
        "resource budget payload",
    )
    return ResourceBudget(
        schema_version=value["schema_version"],
        budget_id=value["budget_id"],
        scope=value["scope"],
        epoch=value["epoch"],
        hard_caps=ResourceVector.from_dict(
            _expect_mapping(value["hard_caps"], "budget hard caps")
        ),
    )


def _estimate_from_dict(value: dict) -> ResourceEstimate:
    _expect_keys(
        value,
        {
            "schema_version",
            "work_id",
            "attempt_id",
            "workload_sha256",
            "adapter",
            "adapter_version",
            "upper_bound",
            "valid_until",
            "expected",
        },
        "resource estimate",
    )
    expected = value["expected"]
    return ResourceEstimate(
        schema_version=value["schema_version"],
        work_id=value["work_id"],
        attempt_id=value["attempt_id"],
        workload_sha256=value["workload_sha256"],
        adapter=value["adapter"],
        adapter_version=value["adapter_version"],
        upper_bound=ResourceVector.from_dict(
            _expect_mapping(value["upper_bound"], "estimate upper bound")
        ),
        valid_until=value["valid_until"],
        expected=(
            None
            if expected is None
            else ResourceVector.from_dict(_expect_mapping(expected, "estimate expected"))
        ),
    )


def _usage_from_dict(value: dict) -> ResourceUsage:
    _expect_keys(
        value,
        {
            "schema_version",
            "actual",
            "measured_at",
            "measurement_sha256",
            "evidence_sha256",
        },
        "resource usage",
    )
    return ResourceUsage(
        schema_version=value["schema_version"],
        actual=ResourceVector.from_dict(_expect_mapping(value["actual"], "usage actual")),
        measured_at=value["measured_at"],
        measurement_sha256=value["measurement_sha256"],
        evidence_sha256=value["evidence_sha256"],
    )


def _command_from_dict(value: dict) -> ResourceCommand:
    operation = value.get("type")
    base = {"type", "command_id", "grant_id", "fence_token", "observed_at"}
    if operation == "request_grant":
        _expect_keys(value, base | {"expires_at", "estimate"}, "request_grant command")
        return RequestGrant(
            command_id=value["command_id"],
            grant_id=value["grant_id"],
            fence_token=value["fence_token"],
            observed_at=value["observed_at"],
            expires_at=value["expires_at"],
            estimate=_estimate_from_dict(
                _expect_mapping(value["estimate"], "request estimate")
            ),
        )
    grant_base = base | {"workload_sha256"}
    if operation == "start_grant":
        _expect_keys(value, grant_base, "start_grant command")
        return StartGrant(**{key: value[key] for key in grant_base if key != "type"})
    if operation == "deadline_observed":
        _expect_keys(value, grant_base, "deadline_observed command")
        return DeadlineObserved(**{key: value[key] for key in grant_base if key != "type"})
    if operation == "cancel_grant":
        _expect_keys(value, grant_base | {"reason"}, "cancel_grant command")
        return CancelGrant(
            **{key: value[key] for key in grant_base if key != "type"},
            reason=value["reason"],
        )
    if operation == "usage_unknown":
        _expect_keys(value, grant_base | {"reason"}, "usage_unknown command")
        return UsageUnknown(
            **{key: value[key] for key in grant_base if key != "type"},
            reason=value["reason"],
        )
    if operation == "settle_grant":
        _expect_keys(value, grant_base | {"usage"}, "settle_grant command")
        return SettleGrant(
            **{key: value[key] for key in grant_base if key != "type"},
            usage=_usage_from_dict(_expect_mapping(value["usage"], "settlement usage")),
        )
    raise ValueError(f"unsupported durable resource command type: {operation!r}")


def _grant_from_dict(value: dict) -> ResourceGrant:
    expected = {
        "schema_version",
        "grant_id",
        "estimate_sha256",
        "workload_sha256",
        "reserved",
        "reserved_at",
        "expires_at",
        "fence_token",
        "status",
        "last_observed_at",
        "started_at",
        "actual",
        "measured_at",
        "measurement_sha256",
        "evidence_sha256",
        "cancel_requested",
    }
    _expect_keys(value, expected, "resource grant")
    return ResourceGrant(
        schema_version=value["schema_version"],
        grant_id=value["grant_id"],
        estimate_sha256=value["estimate_sha256"],
        workload_sha256=value["workload_sha256"],
        reserved=ResourceVector.from_dict(_expect_mapping(value["reserved"], "grant reserved")),
        reserved_at=value["reserved_at"],
        expires_at=value["expires_at"],
        fence_token=value["fence_token"],
        status=GrantStatus(value["status"]),
        last_observed_at=value["last_observed_at"],
        started_at=value["started_at"],
        actual=ResourceVector.from_dict(_expect_mapping(value["actual"], "grant actual")),
        measured_at=value["measured_at"],
        measurement_sha256=value["measurement_sha256"],
        evidence_sha256=value["evidence_sha256"],
        cancel_requested=value["cancel_requested"],
    )


def _receipt_from_dict(value: dict) -> ResourceReceipt:
    expected = {
        "schema_version",
        "budget_id",
        "scope",
        "epoch",
        "operation",
        "outcome",
        "command_id",
        "command_sha256",
        "before_state_sha256",
        "after_state_sha256",
        "transition_payload_sha256",
        "before_revision",
        "after_revision",
        "grant_id",
        "reserved",
        "actual",
        "released",
        "failure_code",
        "failure_detail",
        "failure_dimensions",
        "evidence_sha256",
        "engine_rule_sha256",
    }
    _expect_keys(value, expected, "resource receipt")
    dimensions = value["failure_dimensions"]
    if not isinstance(dimensions, list):
        raise ValueError("receipt failure_dimensions must be a list on disk")
    return ResourceReceipt(
        schema_version=value["schema_version"],
        budget_id=value["budget_id"],
        scope=value["scope"],
        epoch=value["epoch"],
        operation=value["operation"],
        outcome=value["outcome"],
        command_id=value["command_id"],
        command_sha256=value["command_sha256"],
        before_state_sha256=value["before_state_sha256"],
        after_state_sha256=value["after_state_sha256"],
        transition_payload_sha256=value["transition_payload_sha256"],
        before_revision=value["before_revision"],
        after_revision=value["after_revision"],
        grant_id=value["grant_id"],
        reserved=ResourceVector.from_dict(_expect_mapping(value["reserved"], "receipt reserved")),
        actual=ResourceVector.from_dict(_expect_mapping(value["actual"], "receipt actual")),
        released=ResourceVector.from_dict(_expect_mapping(value["released"], "receipt released")),
        failure_code=value["failure_code"],
        failure_detail=value["failure_detail"],
        failure_dimensions=tuple(dimensions),
        evidence_sha256=value["evidence_sha256"],
        engine_rule_sha256=value["engine_rule_sha256"],
    )


def _transition_blob(transition: ResourceTransition) -> bytes:
    return _canonical_bytes(
        {
            "codec_version": CODEC_VERSION,
            "transition": {
                "command": transition.command.to_dict(),
                "command_sha256": transition.command_sha256,
                "transition_payload_sha256": transition.transition_payload_sha256,
                "receipt_sha256": transition.receipt_sha256,
                "transition_sha256": transition.transition_sha256,
                "grant": None if transition.grant is None else transition.grant.to_dict(),
                "spent_delta": transition.spent_delta.to_dict(),
                "freeze_budget": transition.freeze_budget,
                "receipt": transition.receipt.to_dict(),
            },
        }
    )


def _transition_from_blob(blob: object) -> ResourceTransition:
    envelope = _decode_canonical_blob(blob, "resource transition")
    _expect_keys(envelope, {"codec_version", "transition"}, "transition envelope")
    if envelope["codec_version"] != CODEC_VERSION:
        raise JournalCorruption("resource transition codec is unsupported")
    value = _expect_mapping(envelope["transition"], "transition payload")
    _expect_keys(
        value,
        {
            "command",
            "command_sha256",
            "transition_payload_sha256",
            "receipt_sha256",
            "transition_sha256",
            "grant",
            "spent_delta",
            "freeze_budget",
            "receipt",
        },
        "transition payload",
    )
    grant = value["grant"]
    return ResourceTransition(
        command=_command_from_dict(_expect_mapping(value["command"], "transition command")),
        command_sha256=value["command_sha256"],
        transition_payload_sha256=value["transition_payload_sha256"],
        receipt_sha256=value["receipt_sha256"],
        transition_sha256=value["transition_sha256"],
        grant=(None if grant is None else _grant_from_dict(_expect_mapping(grant, "transition grant"))),
        spent_delta=ResourceVector.from_dict(
            _expect_mapping(value["spent_delta"], "transition spent_delta")
        ),
        freeze_budget=value["freeze_budget"],
        receipt=_receipt_from_dict(_expect_mapping(value["receipt"], "transition receipt")),
    )


def _journal_head_sha256(
    *,
    budget: ResourceBudget,
    revision: int,
    state_sha256: str,
    previous_journal_head_sha256: str | None,
    command_id: str | None,
    command_sha256: str | None,
    transition_sha256: str | None,
    receipt_sha256: str | None,
) -> str:
    payload = {
        "journal_schema_version": JOURNAL_SCHEMA_VERSION,
        "codec_version": CODEC_VERSION,
        "kernel_schema_version": SCHEMA_VERSION,
        "engine_rule_sha256": ENGINE_RULE_SHA256,
        "budget": budget.to_dict(),
        "revision": revision,
        "state_sha256": state_sha256,
        "previous_journal_head_sha256": previous_journal_head_sha256,
        "command_id": command_id,
        "command_sha256": command_sha256,
        "transition_sha256": transition_sha256,
        "receipt_sha256": receipt_sha256,
    }
    return _sha256_bytes(_JOURNAL_DOMAIN + _canonical_bytes(payload))


def _checkpoint_for(
    state: ResourceState,
    *,
    previous_journal_head_sha256: str | None,
    transition: ResourceTransition | None,
) -> ResourceCheckpoint:
    command = None if transition is None else transition.command
    head = _journal_head_sha256(
        budget=state.budget,
        revision=state.revision,
        state_sha256=state.snapshot_sha256,
        previous_journal_head_sha256=previous_journal_head_sha256,
        command_id=None if command is None else command.command_id,
        command_sha256=None if transition is None else transition.command_sha256,
        transition_sha256=None if transition is None else transition.transition_sha256,
        receipt_sha256=None if transition is None else transition.receipt_sha256,
    )
    return ResourceCheckpoint(
        schema_version=ANCHOR_SCHEMA_VERSION,
        codec_version=CODEC_VERSION,
        kernel_schema_version=SCHEMA_VERSION,
        engine_rule_sha256=ENGINE_RULE_SHA256,
        budget_id=state.budget_id,
        scope=state.scope,
        epoch=state.epoch,
        revision=state.revision,
        state_sha256=state.snapshot_sha256,
        journal_head_sha256=head,
        previous_journal_head_sha256=previous_journal_head_sha256,
        command_id=None if command is None else command.command_id,
        command_sha256=None if transition is None else transition.command_sha256,
        transition_sha256=None if transition is None else transition.transition_sha256,
        receipt_sha256=None if transition is None else transition.receipt_sha256,
    )


_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE resource_store_meta (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        store_schema_version TEXT NOT NULL,
        codec_version TEXT NOT NULL,
        application_id INTEGER NOT NULL,
        schema_sha256 TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE resource_budget_head (
        scope TEXT PRIMARY KEY,
        budget_id TEXT NOT NULL,
        epoch INTEGER NOT NULL CHECK (epoch >= 1),
        budget_blob BLOB NOT NULL,
        budget_sha256 TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK (revision >= 0),
        state_sha256 TEXT NOT NULL,
        journal_head_sha256 TEXT NOT NULL,
        UNIQUE (scope, budget_id, epoch)
    )
    """,
    """
    CREATE TABLE resource_journal (
        scope TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK (revision >= 1),
        command_id TEXT NOT NULL,
        command_sha256 TEXT NOT NULL,
        transition_sha256 TEXT NOT NULL,
        receipt_sha256 TEXT NOT NULL,
        transition_blob BLOB NOT NULL,
        before_state_sha256 TEXT NOT NULL,
        after_state_sha256 TEXT NOT NULL,
        previous_journal_head_sha256 TEXT NOT NULL,
        journal_head_sha256 TEXT NOT NULL,
        PRIMARY KEY (scope, revision),
        UNIQUE (scope, command_id),
        UNIQUE (scope, journal_head_sha256),
        FOREIGN KEY (scope) REFERENCES resource_budget_head(scope)
    )
    """,
    """
    CREATE TABLE resource_anchor_outbox (
        scope TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK (revision >= 0),
        checkpoint_blob BLOB NOT NULL,
        checkpoint_sha256 TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('PENDING', 'CONFIRMED')),
        PRIMARY KEY (scope, revision),
        UNIQUE (scope, checkpoint_sha256),
        FOREIGN KEY (scope) REFERENCES resource_budget_head(scope)
    )
    """,
)
_SCHEMA_SHA256 = _sha256_bytes(
    "\n".join(statement.strip() for statement in _SCHEMA_STATEMENTS).encode("utf-8")
)


def _normalize_schema_sql(value: str) -> str:
    return " ".join(value.split())


_EXPECTED_LIVE_SCHEMA = {
    ("table", table_name): _normalize_schema_sql(statement)
    for table_name, statement in zip(
        (
            "resource_store_meta",
            "resource_budget_head",
            "resource_journal",
            "resource_anchor_outbox",
        ),
        _SCHEMA_STATEMENTS,
        strict=True,
    )
}


@dataclass(frozen=True, slots=True)
class _LoadedJournal:
    state: ResourceState
    states: dict[int, ResourceState]
    checkpoints: dict[int, ResourceCheckpoint]
    anchor_statuses: dict[int, AnchorStatus]

    @property
    def checkpoint(self) -> ResourceCheckpoint:
        return self.checkpoints[self.state.revision]


class SQLiteResourceJournal:
    """Single-host durable journal around the pure resource kernel.

    ``failure_inject_after_commit`` is a test-only crash seam.  It runs before
    anchor reconciliation and must never be used to dispatch an external effect.
    """

    def __init__(
        self,
        database_path: str | os.PathLike[str],
        *,
        trusted_anchor: TrustedAnchorStore | None = None,
        timeout_seconds: float = 10.0,
        failure_inject_after_commit: Callable[[DurableDecision], None] | None = None,
    ) -> None:
        self._path = Path(database_path)
        if str(database_path) == ":memory:" or not self._path.parent.exists():
            raise ValueError("resource journal requires a durable file in an existing directory")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._timeout_seconds = float(timeout_seconds)
        self._trusted_anchor = trusted_anchor
        self._failure_inject_after_commit = failure_inject_after_commit
        self._bootstrap_or_verify_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._path,
            timeout=self._timeout_seconds,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute(
            f"PRAGMA busy_timeout = {max(1, int(self._timeout_seconds * 1000))}"
        )
        if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            connection.close()
            raise JournalSchemaMismatch("SQLite foreign key enforcement is unavailable")
        if connection.execute("PRAGMA synchronous").fetchone()[0] != 2:
            connection.close()
            raise JournalSchemaMismatch("SQLite synchronous=FULL exact readback failed")
        return connection

    def _bootstrap_or_verify_schema(self) -> None:
        connection = self._connect()
        try:
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
                    raise JournalSchemaMismatch("empty SQLite file has foreign metadata")
                mode = connection.execute("PRAGMA journal_mode = DELETE").fetchone()[0]
                if str(mode).lower() != "delete":
                    raise JournalSchemaMismatch("SQLite rollback journal mode is required")
                connection.execute("BEGIN EXCLUSIVE")
                try:
                    for statement in _SCHEMA_STATEMENTS:
                        connection.execute(statement)
                    connection.execute(
                        "INSERT INTO resource_store_meta VALUES (1, ?, ?, ?, ?)",
                        (
                            JOURNAL_SCHEMA_VERSION,
                            CODEC_VERSION,
                            _APPLICATION_ID,
                            _SCHEMA_SHA256,
                        ),
                    )
                    connection.execute(f"PRAGMA application_id = {_APPLICATION_ID}")
                    connection.execute(f"PRAGMA user_version = {_USER_VERSION}")
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
            expected_tables = {
                "resource_store_meta",
                "resource_budget_head",
                "resource_journal",
                "resource_anchor_outbox",
            }
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            if tables != expected_tables:
                raise JournalSchemaMismatch(
                    f"resource journal tables diverged: {sorted(tables)}"
                )
            live_schema = {
                (row["type"], row["name"]): _normalize_schema_sql(row["sql"])
                for row in connection.execute(
                    "SELECT type, name, sql FROM sqlite_master "
                    "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
                )
                if row["sql"] is not None
            }
            if live_schema != _EXPECTED_LIVE_SCHEMA:
                raise JournalSchemaMismatch(
                    "resource journal live schema diverged from the exact schema receipt"
                )
            if (
                connection.execute("PRAGMA application_id").fetchone()[0]
                != _APPLICATION_ID
                or connection.execute("PRAGMA user_version").fetchone()[0]
                != _USER_VERSION
                or str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
                != "delete"
            ):
                raise JournalSchemaMismatch("resource journal SQLite metadata diverged")
            meta = connection.execute(
                "SELECT store_schema_version, codec_version, application_id, schema_sha256 "
                "FROM resource_store_meta WHERE singleton = 1"
            ).fetchone()
            expected_meta = (
                JOURNAL_SCHEMA_VERSION,
                CODEC_VERSION,
                _APPLICATION_ID,
                _SCHEMA_SHA256,
            )
            if meta is None or tuple(meta) != expected_meta:
                raise JournalSchemaMismatch("resource journal schema receipt diverged")
        finally:
            connection.close()

    @staticmethod
    def _checkpoint_blob(checkpoint: ResourceCheckpoint) -> bytes:
        return _canonical_bytes(checkpoint.to_dict())

    @staticmethod
    def _checkpoint_from_blob(blob: object) -> ResourceCheckpoint:
        return _checkpoint_from_dict(_decode_canonical_blob(blob, "anchor checkpoint"))

    def _load_connection(
        self,
        connection: sqlite3.Connection,
        scope: str,
        *,
        allow_missing: bool = False,
    ) -> _LoadedJournal | None:
        _require_identifier(scope, "resource scope")
        head = connection.execute(
            "SELECT budget_id, epoch, budget_blob, budget_sha256, revision, "
            "state_sha256, journal_head_sha256 "
            "FROM resource_budget_head WHERE scope = ?",
            (scope,),
        ).fetchone()
        if head is None:
            if allow_missing:
                return None
            raise JournalNotInitialized(f"resource journal scope is not initialized: {scope}")
        budget_blob = bytes(head["budget_blob"])
        if _sha256_bytes(budget_blob) != head["budget_sha256"]:
            raise JournalCorruption("resource budget blob hash diverged")
        try:
            budget = _budget_from_blob(budget_blob)
        except ValueError as exc:
            raise JournalCorruption("resource budget cannot be decoded") from exc
        if (
            budget.scope != scope
            or budget.budget_id != head["budget_id"]
            or budget.epoch != head["epoch"]
        ):
            raise JournalCorruption("resource budget head identity diverged")
        state = ResourceState.create(
            budget_id=budget.budget_id,
            scope=budget.scope,
            epoch=budget.epoch,
            hard_caps=budget.hard_caps,
        )
        genesis = _checkpoint_for(
            state,
            previous_journal_head_sha256=None,
            transition=None,
        )
        states = {0: state}
        checkpoints = {0: genesis}
        rows = connection.execute(
            "SELECT revision, command_id, command_sha256, transition_sha256, "
            "receipt_sha256, transition_blob, before_state_sha256, "
            "after_state_sha256, previous_journal_head_sha256, journal_head_sha256 "
            "FROM resource_journal WHERE scope = ? ORDER BY revision",
            (scope,),
        ).fetchall()
        if len(rows) != head["revision"]:
            raise JournalCorruption("resource journal row count does not match its head")
        previous_head = genesis.journal_head_sha256
        for expected_revision, row in enumerate(rows, start=1):
            if row["revision"] != expected_revision:
                raise JournalCorruption("resource journal revisions are not contiguous")
            try:
                transition = _transition_from_blob(row["transition_blob"])
                if (
                    transition.command.command_id != row["command_id"]
                    or transition.command_sha256 != row["command_sha256"]
                    or transition.transition_sha256 != row["transition_sha256"]
                    or transition.receipt_sha256 != row["receipt_sha256"]
                    or transition.receipt.before_state_sha256
                    != row["before_state_sha256"]
                    or transition.receipt.after_state_sha256 != row["after_state_sha256"]
                ):
                    raise ValueError("resource journal row bindings diverged")
                state = evolve(state, transition)
            except (TypeError, ValueError) as exc:
                raise JournalCorruption(
                    f"resource transition {expected_revision} failed semantic replay"
                ) from exc
            checkpoint = _checkpoint_for(
                state,
                previous_journal_head_sha256=previous_head,
                transition=transition,
            )
            if (
                row["previous_journal_head_sha256"] != previous_head
                or row["journal_head_sha256"] != checkpoint.journal_head_sha256
                or row["after_state_sha256"] != state.snapshot_sha256
            ):
                raise JournalCorruption("resource journal chain head diverged")
            checkpoints[expected_revision] = checkpoint
            states[expected_revision] = state
            previous_head = checkpoint.journal_head_sha256
        if (
            state.revision != head["revision"]
            or state.snapshot_sha256 != head["state_sha256"]
            or previous_head != head["journal_head_sha256"]
        ):
            raise JournalCorruption("resource journal cached head failed exact replay")

        outbox_rows = connection.execute(
            "SELECT revision, checkpoint_blob, checkpoint_sha256, status "
            "FROM resource_anchor_outbox WHERE scope = ? ORDER BY revision",
            (scope,),
        ).fetchall()
        if [row["revision"] for row in outbox_rows] != list(range(state.revision + 1)):
            raise UnanchoredHistoryGap("resource anchor outbox has a revision gap")
        statuses: dict[int, AnchorStatus] = {}
        for row in outbox_rows:
            revision = row["revision"]
            try:
                checkpoint = self._checkpoint_from_blob(row["checkpoint_blob"])
                status = AnchorStatus(row["status"])
            except (TypeError, ValueError) as exc:
                raise JournalCorruption("resource anchor outbox cannot be decoded") from exc
            if (
                checkpoint != checkpoints[revision]
                or checkpoint.checkpoint_sha256 != row["checkpoint_sha256"]
            ):
                raise JournalCorruption("resource anchor intent diverged from journal history")
            statuses[revision] = status
        return _LoadedJournal(state, states, checkpoints, statuses)

    @staticmethod
    def _verify_external(
        loaded: _LoadedJournal | None,
        external: ResourceCheckpoint | None,
        *,
        scope: str,
    ) -> None:
        if loaded is None:
            if external is not None:
                raise DatabaseRollbackDetected(
                    f"external anchor for {scope} exists but the local journal is absent"
                )
            return
        if external is None:
            if any(status is AnchorStatus.CONFIRMED for status in loaded.anchor_statuses.values()):
                raise HistoryReplacementDetected(
                    "local journal claims confirmation but the external anchor is absent"
                )
            return
        if (
            external.scope != loaded.state.scope
            or external.budget_id != loaded.state.budget_id
            or external.epoch != loaded.state.epoch
        ):
            raise HistoryReplacementDetected("external anchor budget identity diverged")
        if external.revision > loaded.state.revision:
            raise DatabaseRollbackDetected(
                f"external anchor revision {external.revision} is ahead of local "
                f"revision {loaded.state.revision}"
            )
        local = loaded.checkpoints[external.revision]
        if local != external:
            raise HistoryReplacementDetected(
                f"external anchor and local history diverge at revision {external.revision}"
            )
        if any(
            revision > external.revision and status is AnchorStatus.CONFIRMED
            for revision, status in loaded.anchor_statuses.items()
        ):
            raise UnanchoredHistoryGap(
                "local confirmation status is ahead of the external authority"
            )

    def _external_head(self, scope: str) -> ResourceCheckpoint | None:
        if self._trusted_anchor is None:
            return None
        return self._trusted_anchor.read(scope)

    def initialize(self, state: ResourceState) -> JournalSnapshot:
        if not isinstance(state, ResourceState) or state.revision != 0:
            raise ValueError("resource journal initialization requires a genesis state")
        expected_genesis = ResourceState.create(
            budget_id=state.budget_id,
            scope=state.scope,
            epoch=state.epoch,
            hard_caps=state.hard_caps,
        )
        if state != expected_genesis:
            raise ValueError("resource journal initialization state is not exact genesis")
        external = self._external_head(state.scope)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            loaded = self._load_connection(connection, state.scope, allow_missing=True)
            self._verify_external(loaded, external, scope=state.scope)
            if loaded is None:
                checkpoint = _checkpoint_for(
                    state,
                    previous_journal_head_sha256=None,
                    transition=None,
                )
                budget_blob = _budget_blob(state.budget)
                connection.execute(
                    "INSERT INTO resource_budget_head "
                    "(scope, budget_id, epoch, budget_blob, budget_sha256, revision, "
                    "state_sha256, journal_head_sha256) VALUES (?, ?, ?, ?, ?, 0, ?, ?)",
                    (
                        state.scope,
                        state.budget_id,
                        state.epoch,
                        sqlite3.Binary(budget_blob),
                        _sha256_bytes(budget_blob),
                        state.snapshot_sha256,
                        checkpoint.journal_head_sha256,
                    ),
                )
                checkpoint_blob = self._checkpoint_blob(checkpoint)
                connection.execute(
                    "INSERT INTO resource_anchor_outbox "
                    "(scope, revision, checkpoint_blob, checkpoint_sha256, status) "
                    "VALUES (?, 0, ?, ?, 'PENDING')",
                    (
                        state.scope,
                        sqlite3.Binary(checkpoint_blob),
                        checkpoint.checkpoint_sha256,
                    ),
                )
            elif loaded.state.budget != state.budget or loaded.state.revision != 0:
                raise BudgetIdentityConflict(
                    f"resource scope already belongs to a different or advanced budget: {state.scope}"
                )
            connection.commit()
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
        if self._trusted_anchor is not None:
            return self.reconcile_anchor(state.scope).snapshot
        return self.load(state.scope)

    def load(self, scope: str) -> JournalSnapshot:
        external = self._external_head(scope)
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            loaded = self._load_connection(connection, scope)
            assert loaded is not None
            connection.commit()
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
        self._verify_external(loaded, external, scope=scope)
        return JournalSnapshot(
            state=loaded.state,
            checkpoint=loaded.checkpoint,
            anchor_status=loaded.anchor_statuses[loaded.state.revision],
        )

    def apply(
        self,
        scope: str,
        command: ResourceCommand,
        *,
        expected_revision: int | None = None,
    ) -> DurableDecision:
        if expected_revision is not None and (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 0
        ):
            raise ValueError("expected_revision must be an integer >= 0")
        external = self._external_head(scope)
        connection = self._connect()
        committed_result: DurableDecision | None = None
        try:
            connection.execute("BEGIN IMMEDIATE")
            loaded = self._load_connection(connection, scope)
            assert loaded is not None
            self._verify_external(loaded, external, scope=scope)
            decision = decide(loaded.state, command)  # dedup precedes revision CAS
            if decision.replayed:
                checkpoint = loaded.checkpoints[decision.receipt.after_revision]
                connection.commit()
                committed_result = DurableDecision(
                    state=loaded.states[checkpoint.revision],
                    decision=decision,
                    checkpoint=checkpoint,
                    anchor_status=loaded.anchor_statuses[checkpoint.revision],
                )
            else:
                if (
                    expected_revision is not None
                    and expected_revision != loaded.state.revision
                ):
                    raise RevisionConflict(expected_revision, loaded.state.revision)
                transition = decision.transitions[0]
                next_state = evolve(loaded.state, transition)
                checkpoint = _checkpoint_for(
                    next_state,
                    previous_journal_head_sha256=loaded.checkpoint.journal_head_sha256,
                    transition=transition,
                )
                blob = _transition_blob(transition)
                connection.execute(
                    "INSERT INTO resource_journal "
                    "(scope, revision, command_id, command_sha256, transition_sha256, "
                    "receipt_sha256, transition_blob, before_state_sha256, "
                    "after_state_sha256, previous_journal_head_sha256, journal_head_sha256) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        scope,
                        next_state.revision,
                        transition.command.command_id,
                        transition.command_sha256,
                        transition.transition_sha256,
                        transition.receipt_sha256,
                        sqlite3.Binary(blob),
                        transition.receipt.before_state_sha256,
                        transition.receipt.after_state_sha256,
                        loaded.checkpoint.journal_head_sha256,
                        checkpoint.journal_head_sha256,
                    ),
                )
                updated = connection.execute(
                    "UPDATE resource_budget_head SET revision = ?, state_sha256 = ?, "
                    "journal_head_sha256 = ? WHERE scope = ? AND revision = ? "
                    "AND state_sha256 = ? AND journal_head_sha256 = ?",
                    (
                        next_state.revision,
                        next_state.snapshot_sha256,
                        checkpoint.journal_head_sha256,
                        scope,
                        loaded.state.revision,
                        loaded.state.snapshot_sha256,
                        loaded.checkpoint.journal_head_sha256,
                    ),
                )
                if updated.rowcount != 1:
                    raise RevisionConflict(loaded.state.revision, -1)
                checkpoint_blob = self._checkpoint_blob(checkpoint)
                connection.execute(
                    "INSERT INTO resource_anchor_outbox "
                    "(scope, revision, checkpoint_blob, checkpoint_sha256, status) "
                    "VALUES (?, ?, ?, ?, 'PENDING')",
                    (
                        scope,
                        next_state.revision,
                        sqlite3.Binary(checkpoint_blob),
                        checkpoint.checkpoint_sha256,
                    ),
                )
                # OOPTDD_COMMIT_BEFORE_RESPONSE_GUARD: local history must be durable
                # before a callback, anchor publication, or caller response can occur.
                connection.commit()
                committed_result = DurableDecision(
                    state=next_state,
                    decision=decision,
                    checkpoint=checkpoint,
                    anchor_status=AnchorStatus.PENDING,
                )
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
        assert committed_result is not None
        if (
            not committed_result.decision.replayed
            and self._failure_inject_after_commit is not None
        ):
            self._failure_inject_after_commit(committed_result)
        if self._trusted_anchor is None:
            return committed_result
        self.reconcile_anchor(scope)
        return DurableDecision(
            state=committed_result.state,
            decision=committed_result.decision,
            checkpoint=committed_result.checkpoint,
            anchor_status=AnchorStatus.CONFIRMED,
        )

    def _mark_confirmed(self, scope: str, revision: int) -> bool:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            updated = connection.execute(
                "UPDATE resource_anchor_outbox SET status = 'CONFIRMED' "
                "WHERE scope = ? AND revision = ? AND status = 'PENDING'",
                (scope, revision),
            )
            connection.commit()
            return updated.rowcount == 1
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def reconcile_anchor(
        self,
        scope: str,
        *,
        after_publish: Callable[[ResourceCheckpoint], None] | None = None,
    ) -> AnchorReconcileResult:
        if self._trusted_anchor is None:
            raise TrustedAnchorUnavailable("no trusted resource anchor is configured")
        external = self._trusted_anchor.read(scope)
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            loaded = self._load_connection(connection, scope)
            assert loaded is not None
            connection.commit()
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
        self._verify_external(loaded, external, scope=scope)

        confirmed: list[int] = []
        external_revision = -1 if external is None else external.revision
        for revision in range(external_revision + 1):
            if loaded.anchor_statuses[revision] is AnchorStatus.PENDING:
                if self._mark_confirmed(scope, revision):
                    confirmed.append(revision)
        expected_head = None if external is None else external.journal_head_sha256
        for revision in range(external_revision + 1, loaded.state.revision + 1):
            checkpoint = loaded.checkpoints[revision]
            stored = self._trusted_anchor.compare_and_set(
                expected_journal_head_sha256=expected_head,
                checkpoint=checkpoint,
            )
            if stored != checkpoint:
                raise HistoryReplacementDetected("external anchor exact readback diverged")
            if after_publish is not None:
                after_publish(checkpoint)
            if self._mark_confirmed(scope, revision):
                confirmed.append(revision)
            expected_head = checkpoint.journal_head_sha256
        snapshot = self.load(scope)
        return AnchorReconcileResult(tuple(confirmed), snapshot)


__all__ = [
    "ANCHOR_SCHEMA_VERSION",
    "AnchorConflict",
    "AnchorReconcileResult",
    "AnchorStatus",
    "BudgetIdentityConflict",
    "CODEC_VERSION",
    "DatabaseRollbackDetected",
    "DurableDecision",
    "HistoryReplacementDetected",
    "JOURNAL_SCHEMA_VERSION",
    "JournalCorruption",
    "JournalNotInitialized",
    "JournalSchemaMismatch",
    "JournalSnapshot",
    "ResourceCheckpoint",
    "ResourceJournalError",
    "RevisionConflict",
    "SQLiteResourceJournal",
    "SignedAppendOnlyFileAnchor",
    "TrustedAnchorCorruption",
    "TrustedAnchorStore",
    "TrustedAnchorUnavailable",
    "UnanchoredHistoryGap",
]
