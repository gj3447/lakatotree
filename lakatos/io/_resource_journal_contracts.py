"""Stable contracts shared by resource-journal adapters.

This module is intentionally free of SQLite, filesystem, and signing effects.
It owns the version identities, immutable DTOs, error taxonomy, and canonical
primitive validation used by both persistence and trusted-anchor adapters.
Consumers should keep importing the public names from ``resource_journal``;
the facade re-exports these exact objects for compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import string
from typing import Protocol

from lakatos.resource_coordination import (
    Decision,
    ENGINE_RULE_SHA256,
    ResourceState,
    SCHEMA_VERSION,
)


JOURNAL_SCHEMA_VERSION = "lakatotree.resource-journal/v1"
CODEC_VERSION = "lakatotree.resource-journal-codec/v1"
ANCHOR_SCHEMA_VERSION = "lakatotree.resource-anchor/v1"

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
    "TrustedAnchorCorruption",
    "TrustedAnchorStore",
    "TrustedAnchorUnavailable",
    "UnanchoredHistoryGap",
]
