"""Deterministic dual-resource coordination kernel.

The kernel governs resource-consuming effects and remains independent from the
Lakatosian scientific judge and ``cycle_budget``.  It reads no clock, network,
database, provider, environment variable, or subprocess.  Adapters record UTC
observations in commands, persist transitions with compare-and-swap, and execute
work only after an accepted grant is durable.

v1 deliberately keeps three separately-accounted dimensions: wall-clock compute,
provider-reported input tokens, and provider-reported output tokens.  Unlike units
are never summed or borrowed across axes.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
import hashlib
import json
import re
import string
from typing import Union


SCHEMA_VERSION = "lakatotree.resource/v1"
_DIMENSIONS = (
    "compute.wall_ms",
    "llm.input_tokens",
    "llm.output_tokens",
)
# Public description only.  Enforcement functions bind the private tuple in their
# defaults, so reassigning this exported name cannot disable a production guard.
DIMENSIONS = _DIMENSIONS

_RULE_TEXT = (
    b"lakatotree.resource/v1\x00"
    b"componentwise-hard-caps;atomic-vector-admission;utc-expiry-guards;"
    b"accepted-and-rejected-command-replay;grant-fence-workload-binding;"
    b"causal-observation-order;receipt-bound-transitions;state-hash-chain;"
    b"deterministic-journal-replay;derived-decision-metadata;"
    b"unknown-usage-holds;overrun-freezes;"
    b"scientific-verdict-independent"
)
ENGINE_RULE_SHA256 = hashlib.sha256(_RULE_TEXT).hexdigest()
_RFC3339_UTC = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$"
)


def _canonical_sha(payload: dict) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _identifier(value: str, label: str) -> None:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ValueError(f"{label} must be a non-empty string of at most 256 characters")
    if not value.isprintable():
        raise ValueError(f"{label} must contain printable characters only")


def _sha256(value: str, label: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or value != value.lower()
        or any(ch not in string.hexdigits for ch in value)
    ):
        raise ValueError(f"{label} must be a canonical lowercase hexadecimal SHA-256")


def _recorded_text(value: str, label: str) -> None:
    if not isinstance(value, str) or not value or not value.isprintable():
        raise ValueError(f"{label} must be a non-empty recorded string")


def _integer(value: int, label: str, *, minimum: int = 0) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")


def _schema(value: str, label: str) -> None:
    if value != SCHEMA_VERSION:
        raise ValueError(f"unsupported {label} schema: {value}")


def _utc_instant(value: str, label: str) -> datetime:
    """Parse the closed v1 UTC timestamp form used for deterministic guards."""

    if not isinstance(value, str) or _RFC3339_UTC.fullmatch(value) is None:
        raise ValueError(f"{label} must be an RFC3339 UTC timestamp ending in Z")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{label} must be a valid RFC3339 UTC timestamp") from exc


@dataclass(frozen=True, slots=True)
class ResourceVector:
    """Closed v1 resource vector; values never share or borrow units."""

    compute_wall_ms: int = 0
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0

    def __post_init__(self) -> None:
        for dimension, value in self.items():
            _integer(value, dimension)

    @classmethod
    def zero(cls) -> "ResourceVector":
        return cls()

    @classmethod
    def from_dict(cls, values: dict[str, int]) -> "ResourceVector":
        unknown = set(values) - set(_DIMENSIONS)
        if unknown:
            raise ValueError(f"unknown resource dimensions: {sorted(unknown)}")
        return cls(
            compute_wall_ms=values.get("compute.wall_ms", 0),
            llm_input_tokens=values.get("llm.input_tokens", 0),
            llm_output_tokens=values.get("llm.output_tokens", 0),
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "compute.wall_ms": self.compute_wall_ms,
            "llm.input_tokens": self.llm_input_tokens,
            "llm.output_tokens": self.llm_output_tokens,
        }

    def items(self) -> tuple[tuple[str, int], ...]:
        values = (
            self.compute_wall_ms,
            self.llm_input_tokens,
            self.llm_output_tokens,
        )
        return tuple(zip(_DIMENSIONS, values))

    def value(self, dimension: str) -> int:
        try:
            return self.to_dict()[dimension]
        except KeyError as exc:
            raise ValueError(f"unknown resource dimension: {dimension}") from exc

    def __add__(self, other: "ResourceVector") -> "ResourceVector":
        return ResourceVector(
            self.compute_wall_ms + other.compute_wall_ms,
            self.llm_input_tokens + other.llm_input_tokens,
            self.llm_output_tokens + other.llm_output_tokens,
        )

    def subtract(self, other: "ResourceVector") -> "ResourceVector":
        values = tuple(self.value(d) - other.value(d) for d in _DIMENSIONS)
        if any(value < 0 for value in values):
            raise ValueError("resource subtraction would produce a negative quantity")
        return ResourceVector(*values)

    def saturating_subtract(self, other: "ResourceVector") -> "ResourceVector":
        return ResourceVector(*(
            max(self.value(d) - other.value(d), 0) for d in _DIMENSIONS
        ))

    def exceeds(
        self,
        other: "ResourceVector",
        *,
        dimensions: tuple[str, ...] = _DIMENSIONS,
    ) -> tuple[str, ...]:
        return tuple(
            dimension
            for dimension in dimensions
            if self.value(dimension) > other.value(dimension)
        )

    @property
    def is_zero(self) -> bool:
        return all(value == 0 for _dimension, value in self.items())


class BudgetStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"


class GrantStatus(str, Enum):
    RESERVED = "RESERVED"
    IN_USE = "IN_USE"
    SETTLED = "SETTLED"
    CANCELLED_UNUSED = "CANCELLED_UNUSED"
    EXPIRED_UNUSED = "EXPIRED_UNUSED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED_SETTLED = "CANCELLED_SETTLED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    QUARANTINED_OVERRUN = "QUARANTINED_OVERRUN"


_HOLDS_RESERVATION = frozenset({
    GrantStatus.RESERVED,
    GrantStatus.IN_USE,
    GrantStatus.CANCEL_PENDING,
    GrantStatus.RECONCILIATION_REQUIRED,
})
_CHARGED = frozenset({
    GrantStatus.SETTLED,
    GrantStatus.CANCELLED_SETTLED,
    GrantStatus.QUARANTINED_OVERRUN,
})


@dataclass(frozen=True, slots=True)
class ResourceBudget:
    budget_id: str
    scope: str
    epoch: int
    hard_caps: ResourceVector
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _schema(self.schema_version, "budget")
        _identifier(self.budget_id, "budget_id")
        _identifier(self.scope, "scope")
        _integer(self.epoch, "epoch", minimum=1)
        if not isinstance(self.hard_caps, ResourceVector):
            raise ValueError("hard_caps must be a ResourceVector")

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "budget_id": self.budget_id,
            "scope": self.scope,
            "epoch": self.epoch,
            "hard_caps": self.hard_caps.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ResourceEstimate:
    work_id: str
    attempt_id: str
    workload_sha256: str
    adapter: str
    adapter_version: str
    upper_bound: ResourceVector
    valid_until: str
    expected: ResourceVector | None = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _schema(self.schema_version, "estimate")
        _identifier(self.work_id, "work_id")
        _identifier(self.attempt_id, "attempt_id")
        _sha256(self.workload_sha256, "workload_sha256")
        _identifier(self.adapter, "adapter")
        _identifier(self.adapter_version, "adapter_version")
        _utc_instant(self.valid_until, "valid_until")
        if not isinstance(self.upper_bound, ResourceVector):
            raise ValueError("upper_bound must be a ResourceVector")
        if self.upper_bound.is_zero:
            raise ValueError("upper_bound must reserve at least one resource unit")
        if self.expected is not None:
            if not isinstance(self.expected, ResourceVector):
                raise ValueError("expected must be a ResourceVector")
            if self.expected.exceeds(self.upper_bound):
                raise ValueError("expected usage cannot exceed the declared upper bound")

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "work_id": self.work_id,
            "attempt_id": self.attempt_id,
            "workload_sha256": self.workload_sha256,
            "adapter": self.adapter,
            "adapter_version": self.adapter_version,
            "upper_bound": self.upper_bound.to_dict(),
            "valid_until": self.valid_until,
            "expected": None if self.expected is None else self.expected.to_dict(),
        }

    @property
    def estimate_sha256(self) -> str:
        return _canonical_sha(self.to_dict())


@dataclass(frozen=True, slots=True)
class ResourceUsage:
    actual: ResourceVector
    measured_at: str
    measurement_sha256: str
    evidence_sha256: str
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _schema(self.schema_version, "usage")
        if not isinstance(self.actual, ResourceVector):
            raise ValueError("actual must be a ResourceVector")
        _utc_instant(self.measured_at, "measured_at")
        _sha256(self.measurement_sha256, "measurement_sha256")
        _sha256(self.evidence_sha256, "evidence_sha256")

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "actual": self.actual.to_dict(),
            "measured_at": self.measured_at,
            "measurement_sha256": self.measurement_sha256,
            "evidence_sha256": self.evidence_sha256,
        }


@dataclass(frozen=True, slots=True)
class RequestGrant:
    command_id: str
    grant_id: str
    fence_token: int
    observed_at: str
    expires_at: str
    estimate: ResourceEstimate

    def __post_init__(self) -> None:
        _identifier(self.command_id, "command_id")
        _identifier(self.grant_id, "grant_id")
        _integer(self.fence_token, "fence_token", minimum=1)
        _utc_instant(self.observed_at, "observed_at")
        _utc_instant(self.expires_at, "expires_at")
        if not isinstance(self.estimate, ResourceEstimate):
            raise ValueError("estimate must be a ResourceEstimate")

    def to_dict(self) -> dict:
        return {
            "type": "request_grant",
            "command_id": self.command_id,
            "grant_id": self.grant_id,
            "fence_token": self.fence_token,
            "observed_at": self.observed_at,
            "expires_at": self.expires_at,
            "estimate": self.estimate.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class _GrantCommand:
    command_id: str
    grant_id: str
    fence_token: int
    workload_sha256: str
    observed_at: str

    def __post_init__(self) -> None:
        _identifier(self.command_id, "command_id")
        _identifier(self.grant_id, "grant_id")
        _integer(self.fence_token, "fence_token", minimum=1)
        _sha256(self.workload_sha256, "workload_sha256")
        _utc_instant(self.observed_at, "observed_at")

    def _base_dict(self, operation: str) -> dict:
        return {
            "type": operation,
            "command_id": self.command_id,
            "grant_id": self.grant_id,
            "fence_token": self.fence_token,
            "workload_sha256": self.workload_sha256,
            "observed_at": self.observed_at,
        }


@dataclass(frozen=True, slots=True)
class StartGrant(_GrantCommand):
    def to_dict(self) -> dict:
        return self._base_dict("start_grant")


@dataclass(frozen=True, slots=True)
class CancelGrant(_GrantCommand):
    reason: str

    def __post_init__(self) -> None:
        super(CancelGrant, self).__post_init__()
        _recorded_text(self.reason, "reason")

    def to_dict(self) -> dict:
        return {**self._base_dict("cancel_grant"), "reason": self.reason}


@dataclass(frozen=True, slots=True)
class DeadlineObserved(_GrantCommand):
    def to_dict(self) -> dict:
        return self._base_dict("deadline_observed")


@dataclass(frozen=True, slots=True)
class UsageUnknown(_GrantCommand):
    reason: str

    def __post_init__(self) -> None:
        super(UsageUnknown, self).__post_init__()
        _recorded_text(self.reason, "reason")

    def to_dict(self) -> dict:
        return {**self._base_dict("usage_unknown"), "reason": self.reason}


@dataclass(frozen=True, slots=True)
class SettleGrant:
    command_id: str
    grant_id: str
    fence_token: int
    workload_sha256: str
    observed_at: str
    usage: ResourceUsage

    def __post_init__(self) -> None:
        _identifier(self.command_id, "command_id")
        _identifier(self.grant_id, "grant_id")
        _integer(self.fence_token, "fence_token", minimum=1)
        _sha256(self.workload_sha256, "workload_sha256")
        _utc_instant(self.observed_at, "observed_at")
        if not isinstance(self.usage, ResourceUsage):
            raise ValueError("usage must be a ResourceUsage")

    def to_dict(self) -> dict:
        return {
            "type": "settle_grant",
            "command_id": self.command_id,
            "grant_id": self.grant_id,
            "fence_token": self.fence_token,
            "workload_sha256": self.workload_sha256,
            "observed_at": self.observed_at,
            "usage": self.usage.to_dict(),
        }


ResourceCommand = Union[
    RequestGrant,
    StartGrant,
    SettleGrant,
    CancelGrant,
    DeadlineObserved,
    UsageUnknown,
]


@dataclass(frozen=True, slots=True)
class ResourceGrant:
    grant_id: str
    estimate_sha256: str
    workload_sha256: str
    reserved: ResourceVector
    reserved_at: str
    expires_at: str
    fence_token: int
    status: GrantStatus
    last_observed_at: str
    started_at: str | None = None
    actual: ResourceVector = ResourceVector()
    measured_at: str | None = None
    measurement_sha256: str | None = None
    evidence_sha256: str | None = None
    cancel_requested: bool = False
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _schema(self.schema_version, "grant")
        _identifier(self.grant_id, "grant_id")
        _sha256(self.estimate_sha256, "estimate_sha256")
        _sha256(self.workload_sha256, "workload_sha256")
        if not isinstance(self.reserved, ResourceVector):
            raise ValueError("reserved must be a ResourceVector")
        if self.reserved.is_zero:
            raise ValueError("a grant must reserve at least one resource unit")
        reserved_at = _utc_instant(self.reserved_at, "reserved_at")
        _utc_instant(self.expires_at, "expires_at")
        _integer(self.fence_token, "fence_token", minimum=1)
        if not isinstance(self.status, GrantStatus):
            raise ValueError("grant status must be a GrantStatus")
        if not isinstance(self.actual, ResourceVector):
            raise ValueError("actual must be a ResourceVector")
        last_observed_at = _utc_instant(self.last_observed_at, "last_observed_at")
        if last_observed_at < reserved_at:
            raise ValueError("grant observation time cannot precede reservation")
        started_at = None
        if self.started_at is not None:
            started_at = _utc_instant(self.started_at, "started_at")
            if started_at < reserved_at or started_at > last_observed_at:
                raise ValueError("started_at must lie within the grant observation interval")
        measured_at = None
        if self.measured_at is not None:
            measured_at = _utc_instant(self.measured_at, "measured_at")
        if self.measurement_sha256 is not None:
            _sha256(self.measurement_sha256, "measurement_sha256")
        if self.evidence_sha256 is not None:
            _sha256(self.evidence_sha256, "evidence_sha256")
        if not isinstance(self.cancel_requested, bool):
            raise ValueError("cancel_requested must be boolean")

        if self.status in _CHARGED:
            if (
                self.measurement_sha256 is None
                or self.evidence_sha256 is None
                or measured_at is None
                or started_at is None
            ):
                raise ValueError("charged grants require start, time, and evidence")
            if measured_at < started_at or measured_at > last_observed_at:
                raise ValueError("measurement time must lie between start and settlement")
        elif (
            not self.actual.is_zero
            or self.measured_at is not None
            or self.measurement_sha256 is not None
            or self.evidence_sha256 is not None
        ):
            raise ValueError("unsettled grants cannot carry measured usage")
        post_start = {
            GrantStatus.IN_USE,
            GrantStatus.CANCEL_PENDING,
            GrantStatus.RECONCILIATION_REQUIRED,
            *_CHARGED,
        }
        if self.status in post_start and started_at is None:
            raise ValueError("post-start grant status requires started_at")
        if self.status not in post_start and started_at is not None:
            raise ValueError("pre-start grant status cannot carry started_at")
        if (
            self.status is GrantStatus.QUARANTINED_OVERRUN
            and not self.actual.exceeds(self.reserved)
        ):
            raise ValueError("quarantined overrun must exceed its reservation")
        if self.status is GrantStatus.CANCELLED_SETTLED and not self.cancel_requested:
            raise ValueError("cancelled settlement must preserve cancellation intent")
        if self.status is GrantStatus.SETTLED and self.cancel_requested:
            raise ValueError("ordinary settlement cannot carry cancellation intent")
        if self.status in {GrantStatus.CANCEL_PENDING, GrantStatus.CANCELLED_SETTLED}:
            if not self.cancel_requested:
                raise ValueError("cancel state must preserve cancellation intent")

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "grant_id": self.grant_id,
            "estimate_sha256": self.estimate_sha256,
            "workload_sha256": self.workload_sha256,
            "reserved": self.reserved.to_dict(),
            "reserved_at": self.reserved_at,
            "expires_at": self.expires_at,
            "fence_token": self.fence_token,
            "status": self.status.value,
            "last_observed_at": self.last_observed_at,
            "started_at": self.started_at,
            "actual": self.actual.to_dict(),
            "measured_at": self.measured_at,
            "measurement_sha256": self.measurement_sha256,
            "evidence_sha256": self.evidence_sha256,
            "cancel_requested": self.cancel_requested,
        }


@dataclass(frozen=True, slots=True)
class ResourceReceipt:
    schema_version: str
    budget_id: str
    scope: str
    epoch: int
    operation: str
    outcome: str
    command_id: str
    command_sha256: str
    before_state_sha256: str
    after_state_sha256: str
    transition_payload_sha256: str
    before_revision: int
    after_revision: int
    grant_id: str
    reserved: ResourceVector
    actual: ResourceVector
    released: ResourceVector
    failure_code: str | None
    failure_detail: str | None
    failure_dimensions: tuple[str, ...]
    evidence_sha256: str | None
    engine_rule_sha256: str

    def __post_init__(self) -> None:
        _schema(self.schema_version, "receipt")
        _identifier(self.budget_id, "budget_id")
        _identifier(self.scope, "scope")
        _integer(self.epoch, "epoch", minimum=1)
        _identifier(self.operation, "operation")
        _identifier(self.outcome, "outcome")
        _identifier(self.command_id, "command_id")
        _sha256(self.command_sha256, "command_sha256")
        _sha256(self.before_state_sha256, "before_state_sha256")
        _sha256(self.after_state_sha256, "after_state_sha256")
        _sha256(self.transition_payload_sha256, "transition_payload_sha256")
        _integer(self.before_revision, "before_revision")
        if self.after_revision != self.before_revision + 1:
            raise ValueError("receipt revision must advance exactly once")
        _identifier(self.grant_id, "grant_id")
        for label, vector in (
            ("reserved", self.reserved),
            ("actual", self.actual),
            ("released", self.released),
        ):
            if not isinstance(vector, ResourceVector):
                raise ValueError(f"{label} must be a ResourceVector")
        if self.failure_code is None:
            if self.failure_detail is not None or self.failure_dimensions:
                raise ValueError("failure metadata requires failure_code")
        else:
            _identifier(self.failure_code, "failure_code")
            if self.failure_detail is not None:
                _recorded_text(self.failure_detail, "failure_detail")
        if not isinstance(self.failure_dimensions, tuple):
            raise ValueError("failure_dimensions must be a tuple")
        if set(self.failure_dimensions) - set(_DIMENSIONS):
            raise ValueError("failure_dimensions contains an unknown resource axis")
        if len(self.failure_dimensions) != len(set(self.failure_dimensions)):
            raise ValueError("failure_dimensions cannot contain duplicates")
        if self.evidence_sha256 is not None:
            _sha256(self.evidence_sha256, "evidence_sha256")
        _sha256(self.engine_rule_sha256, "engine_rule_sha256")

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "budget_id": self.budget_id,
            "scope": self.scope,
            "epoch": self.epoch,
            "operation": self.operation,
            "outcome": self.outcome,
            "command_id": self.command_id,
            "command_sha256": self.command_sha256,
            "before_state_sha256": self.before_state_sha256,
            "after_state_sha256": self.after_state_sha256,
            "transition_payload_sha256": self.transition_payload_sha256,
            "before_revision": self.before_revision,
            "after_revision": self.after_revision,
            "grant_id": self.grant_id,
            "reserved": self.reserved.to_dict(),
            "actual": self.actual.to_dict(),
            "released": self.released.to_dict(),
            "failure_code": self.failure_code,
            "failure_detail": self.failure_detail,
            "failure_dimensions": list(self.failure_dimensions),
            "evidence_sha256": self.evidence_sha256,
            "engine_rule_sha256": self.engine_rule_sha256,
        }

    @property
    def receipt_sha256(self) -> str:
        return _canonical_sha(self.to_dict())


@dataclass(frozen=True, slots=True)
class _CommandRecord:
    command_id: str
    command_sha256: str
    receipt_sha256: str
    transition_sha256: str
    receipt: ResourceReceipt
    transition: "ResourceTransition"


@dataclass(frozen=True, slots=True)
class ResourceTransition:
    command: ResourceCommand
    command_sha256: str
    transition_payload_sha256: str
    receipt_sha256: str
    transition_sha256: str
    grant: ResourceGrant | None
    spent_delta: ResourceVector
    freeze_budget: bool
    receipt: ResourceReceipt

    def __post_init__(self) -> None:
        _sha256(self.command_sha256, "command_sha256")
        _sha256(self.transition_payload_sha256, "transition_payload_sha256")
        _sha256(self.receipt_sha256, "receipt_sha256")
        _sha256(self.transition_sha256, "transition_sha256")
        if self.grant is not None and not isinstance(self.grant, ResourceGrant):
            raise ValueError("grant must be a ResourceGrant or None")
        if not isinstance(self.spent_delta, ResourceVector):
            raise ValueError("spent_delta must be a ResourceVector")
        if not isinstance(self.freeze_budget, bool):
            raise ValueError("freeze_budget must be boolean")
        if not isinstance(self.receipt, ResourceReceipt):
            raise ValueError("receipt must be a ResourceReceipt")


@dataclass(frozen=True, slots=True)
class Decision:
    transitions: tuple[ResourceTransition, ...]
    replayed: bool = False
    _replay_receipt: ResourceReceipt | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.transitions, tuple):
            raise ValueError("transitions must be a tuple")
        if self.replayed:
            if self.transitions or self._replay_receipt is None:
                raise ValueError("replay decision requires one stored receipt and no transition")
        elif len(self.transitions) != 1 or self._replay_receipt is not None:
            raise ValueError("fresh decision requires exactly one authoritative transition")

    @property
    def receipt(self) -> ResourceReceipt:
        if self.replayed:
            assert self._replay_receipt is not None
            return self._replay_receipt
        return self.transitions[0].receipt

    @property
    def rejection(self) -> "ResourceRejection | None":
        return _rejection_from_receipt(self.receipt)

    @property
    def accepted(self) -> bool:
        return self.receipt.outcome != "rejected"


def _snapshot_sha256(
    *,
    schema_version: str,
    budget_id: str,
    scope: str,
    epoch: int,
    revision: int,
    hard_caps: ResourceVector,
    spent: ResourceVector,
    status: BudgetStatus,
    grants: tuple[ResourceGrant, ...],
) -> str:
    """Hash the dynamic ledger snapshot independently from its journal records."""

    return _canonical_sha({
        "schema_version": schema_version,
        "budget_id": budget_id,
        "scope": scope,
        "epoch": epoch,
        "revision": revision,
        "hard_caps": hard_caps.to_dict(),
        "spent": spent.to_dict(),
        "status": status.value,
        "grants": [grant.to_dict() for grant in sorted(
            grants,
            key=lambda item: item.grant_id,
        )],
    })


@dataclass(frozen=True, slots=True)
class _ResourceProjection:
    """Internal journal-replay state without recursive constructor validation."""

    schema_version: str
    budget_id: str
    scope: str
    epoch: int
    revision: int
    hard_caps: ResourceVector
    spent: ResourceVector
    status: BudgetStatus
    grants: tuple[ResourceGrant, ...]

    @property
    def snapshot_sha256(self) -> str:
        return _snapshot_sha256(
            schema_version=self.schema_version,
            budget_id=self.budget_id,
            scope=self.scope,
            epoch=self.epoch,
            revision=self.revision,
            hard_caps=self.hard_caps,
            spent=self.spent,
            status=self.status,
            grants=self.grants,
        )

    @property
    def reserved(self) -> ResourceVector:
        total = ResourceVector.zero()
        for grant in self.grants:
            if grant.status in _HOLDS_RESERVATION:
                total = total + grant.reserved
        return total

    @property
    def remaining(self) -> ResourceVector:
        return self.hard_caps.saturating_subtract(self.spent + self.reserved)

    def grant(self, grant_id: str) -> ResourceGrant:
        for grant in self.grants:
            if grant.grant_id == grant_id:
                return grant
        raise UnknownGrant(grant_id)


@dataclass(frozen=True, slots=True)
class ResourceState:
    schema_version: str
    budget_id: str
    scope: str
    epoch: int
    revision: int
    hard_caps: ResourceVector
    spent: ResourceVector
    status: BudgetStatus
    grants: tuple[ResourceGrant, ...] = ()
    command_records: tuple[_CommandRecord, ...] = ()

    def __post_init__(self) -> None:
        _schema(self.schema_version, "resource state")
        ResourceBudget(
            budget_id=self.budget_id,
            scope=self.scope,
            epoch=self.epoch,
            hard_caps=self.hard_caps,
            schema_version=self.schema_version,
        )
        _integer(self.revision, "revision")
        if not isinstance(self.spent, ResourceVector):
            raise ValueError("spent must be a ResourceVector")
        if not isinstance(self.status, BudgetStatus):
            raise ValueError("budget status must be a BudgetStatus")
        if not isinstance(self.grants, tuple):
            raise ValueError("grants must be a tuple")
        if not isinstance(self.command_records, tuple):
            raise ValueError("command_records must be a tuple")
        if any(not isinstance(grant, ResourceGrant) for grant in self.grants):
            raise ValueError("grants must contain ResourceGrant values")

        grant_ids = [grant.grant_id for grant in self.grants]
        if len(grant_ids) != len(set(grant_ids)):
            raise ValueError("duplicate grant_id in resource state")

        charged = ResourceVector.zero()
        for grant in self.grants:
            if grant.status in _CHARGED:
                charged = charged + grant.actual
            if grant.status in {GrantStatus.SETTLED, GrantStatus.CANCELLED_SETTLED}:
                if grant.actual.exceeds(grant.reserved):
                    raise ValueError("non-quarantined settlement exceeds its reservation")
        if charged != self.spent:
            raise ValueError("spent must equal the measured usage of charged grants")

        quarantined = any(
            grant.status is GrantStatus.QUARANTINED_OVERRUN for grant in self.grants
        )
        if quarantined and self.status is not BudgetStatus.FROZEN:
            raise ValueError("a quarantined overrun must freeze the budget")
        if self.status is BudgetStatus.FROZEN and not quarantined:
            raise ValueError("a frozen v1 budget requires a quarantined overrun")
        if self.status is BudgetStatus.ACTIVE:
            deficits = _hard_cap_deficits(self.spent + self.reserved, self.hard_caps)
            if deficits:
                raise ValueError(f"active budget exceeds hard caps: {deficits}")

        command_ids = [record.command_id for record in self.command_records]
        if len(command_ids) != len(set(command_ids)):
            raise ValueError("duplicate command_id in resource state")
        if len(self.command_records) != self.revision:
            raise ValueError("revision must equal the number of retained command records")
        _validate_retained_history(self)

    @classmethod
    def create(
        cls,
        *,
        budget_id: str,
        scope: str,
        epoch: int,
        hard_caps: ResourceVector,
    ) -> "ResourceState":
        budget = ResourceBudget(
            budget_id=budget_id,
            scope=scope,
            epoch=epoch,
            hard_caps=hard_caps,
        )
        return cls(
            schema_version=budget.schema_version,
            budget_id=budget.budget_id,
            scope=budget.scope,
            epoch=budget.epoch,
            revision=0,
            hard_caps=budget.hard_caps,
            spent=ResourceVector.zero(),
            status=BudgetStatus.ACTIVE,
        )

    @property
    def budget(self) -> ResourceBudget:
        return ResourceBudget(
            budget_id=self.budget_id,
            scope=self.scope,
            epoch=self.epoch,
            hard_caps=self.hard_caps,
            schema_version=self.schema_version,
        )

    @property
    def snapshot_sha256(self) -> str:
        return _snapshot_sha256(
            schema_version=self.schema_version,
            budget_id=self.budget_id,
            scope=self.scope,
            epoch=self.epoch,
            revision=self.revision,
            hard_caps=self.hard_caps,
            spent=self.spent,
            status=self.status,
            grants=self.grants,
        )

    @property
    def reserved(self) -> ResourceVector:
        total = ResourceVector.zero()
        for grant in self.grants:
            if grant.status in _HOLDS_RESERVATION:
                total = total + grant.reserved
        return total

    @property
    def remaining(self) -> ResourceVector:
        return self.hard_caps.saturating_subtract(self.spent + self.reserved)

    def grant(self, grant_id: str) -> ResourceGrant:
        for grant in self.grants:
            if grant.grant_id == grant_id:
                return grant
        raise UnknownGrant(grant_id)


class ResourceRejection(RuntimeError):
    """Typed command rejection that is turned into a durable transition receipt."""

    def __init__(self, code: str, message: str, *, dimensions: tuple[str, ...] = ()):
        super().__init__(message)
        self.code = code
        self.dimensions = dimensions


class CapacityExceeded(ResourceRejection):
    def __init__(self, dimensions: tuple[str, ...]):
        super().__init__(
            "CAP_EXCEEDED",
            f"resource capacity exceeded: {', '.join(dimensions)}",
            dimensions=dimensions,
        )


class IdempotencyConflict(ResourceRejection):
    def __init__(self, command_id: str):
        super().__init__(
            "IDEMPOTENCY_CONFLICT",
            f"command_id was reused with a different payload: {command_id}",
        )


class InvalidTransition(ResourceRejection):
    def __init__(self, message: str):
        super().__init__("INVALID_TRANSITION", message)


class UnknownGrant(ResourceRejection):
    def __init__(self, grant_id: str):
        super().__init__("GRANT_NOT_FOUND", f"resource grant not found: {grant_id}")


class BudgetFrozen(ResourceRejection):
    def __init__(self):
        super().__init__("BUDGET_FROZEN", "resource budget is frozen")


def _command_hash(command: ResourceCommand) -> str:
    return _canonical_sha(command.to_dict())


def _operation(command: ResourceCommand) -> str:
    return command.to_dict()["type"]


def _hard_cap_deficits(
    requested: ResourceVector,
    remaining: ResourceVector,
    _dimensions: tuple[str, ...] = _DIMENSIONS,
) -> tuple[str, ...]:
    """Invariant guard; separate from admission so one mutation cannot erase both."""

    return requested.exceeds(remaining, dimensions=_dimensions)


def _admission_deficits(
    requested: ResourceVector,
    remaining: ResourceVector,
    _dimensions: tuple[str, ...] = _DIMENSIONS,
) -> tuple[str, ...]:
    """Admission guard.  OOPTDD mutates only this function in an isolated copy."""

    return requested.exceeds(remaining, dimensions=_dimensions)


def _bound_grant(state: ResourceState, command) -> ResourceGrant:
    grant = state.grant(command.grant_id)
    if grant.fence_token != command.fence_token:
        raise InvalidTransition("fence token does not match the grant")
    if grant.workload_sha256 != command.workload_sha256:
        raise InvalidTransition("workload identity does not match the grant")
    return grant


def _projected_grants(
    state: ResourceState,
    command: ResourceCommand,
    grant: ResourceGrant | None,
) -> tuple[ResourceGrant, ...]:
    if grant is None:
        return state.grants
    grants = list(state.grants)
    if isinstance(command, RequestGrant):
        grants.append(grant)
        return tuple(grants)
    for index, previous in enumerate(grants):
        if previous.grant_id == grant.grant_id:
            grants[index] = grant
            return tuple(grants)
    raise UnknownGrant(grant.grant_id)


def _projected_state_sha256(
    state: ResourceState,
    command: ResourceCommand,
    grant: ResourceGrant | None,
    spent_delta: ResourceVector,
    freeze_budget: bool,
) -> str:
    return _snapshot_sha256(
        schema_version=state.schema_version,
        budget_id=state.budget_id,
        scope=state.scope,
        epoch=state.epoch,
        revision=state.revision + 1,
        hard_caps=state.hard_caps,
        spent=state.spent + spent_delta,
        status=BudgetStatus.FROZEN if freeze_budget else state.status,
        grants=_projected_grants(state, command, grant),
    )


def _transition_body(
    *,
    state: ResourceState,
    command: ResourceCommand,
    command_sha256: str,
    grant: ResourceGrant | None,
    spent_delta: ResourceVector,
    freeze_budget: bool,
) -> dict:
    """Canonical semantic transition bytes; no external event vocabulary lives here."""

    return {
        "schema_version": SCHEMA_VERSION,
        "budget_id": state.budget_id,
        "scope": state.scope,
        "epoch": state.epoch,
        "before_revision": state.revision,
        "after_revision": state.revision + 1,
        "before_state_sha256": state.snapshot_sha256,
        "after_state_sha256": _projected_state_sha256(
            state,
            command,
            grant,
            spent_delta,
            freeze_budget,
        ),
        "command": command.to_dict(),
        "command_sha256": command_sha256,
        "grant": None if grant is None else grant.to_dict(),
        "spent_delta": spent_delta.to_dict(),
        "freeze_budget": freeze_budget,
    }


def _transition_envelope(payload_sha256: str, receipt_sha256: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "transition_payload_sha256": payload_sha256,
        "receipt_sha256": receipt_sha256,
    }


def _decision(
    state: ResourceState,
    command: ResourceCommand,
    *,
    outcome: str,
    grant: ResourceGrant | None,
    reserved: ResourceVector = ResourceVector(),
    actual: ResourceVector = ResourceVector(),
    released: ResourceVector = ResourceVector(),
    spent_delta: ResourceVector = ResourceVector(),
    freeze_budget: bool = False,
    failure_code: str | None = None,
    failure_detail: str | None = None,
    failure_dimensions: tuple[str, ...] = (),
    evidence_sha256: str | None = None,
) -> Decision:
    command_sha256 = _command_hash(command)
    body = _transition_body(
        state=state,
        command=command,
        command_sha256=command_sha256,
        grant=grant,
        spent_delta=spent_delta,
        freeze_budget=freeze_budget,
    )
    payload_sha256 = _canonical_sha(body)
    receipt = ResourceReceipt(
        schema_version=SCHEMA_VERSION,
        budget_id=state.budget_id,
        scope=state.scope,
        epoch=state.epoch,
        operation=_operation(command),
        outcome=outcome,
        command_id=command.command_id,
        command_sha256=command_sha256,
        before_state_sha256=body["before_state_sha256"],
        after_state_sha256=body["after_state_sha256"],
        transition_payload_sha256=payload_sha256,
        before_revision=state.revision,
        after_revision=state.revision + 1,
        grant_id=command.grant_id,
        reserved=reserved,
        actual=actual,
        released=released,
        failure_code=failure_code,
        failure_detail=failure_detail,
        failure_dimensions=failure_dimensions,
        evidence_sha256=evidence_sha256,
        engine_rule_sha256=ENGINE_RULE_SHA256,
    )
    receipt_sha256 = receipt.receipt_sha256
    transition_sha256 = _canonical_sha(
        _transition_envelope(payload_sha256, receipt_sha256)
    )
    transition = ResourceTransition(
        command=command,
        command_sha256=command_sha256,
        transition_payload_sha256=payload_sha256,
        receipt_sha256=receipt_sha256,
        transition_sha256=transition_sha256,
        grant=grant,
        spent_delta=spent_delta,
        freeze_budget=freeze_budget,
        receipt=receipt,
    )
    return Decision(transitions=(transition,))


def _rejected_decision(
    state: ResourceState,
    command: ResourceCommand,
    rejection: ResourceRejection,
) -> Decision:
    return _decision(
        state,
        command,
        outcome="rejected",
        grant=None,
        failure_code=rejection.code,
        failure_detail=str(rejection),
        failure_dimensions=rejection.dimensions,
    )


def _rejection_from_receipt(receipt: ResourceReceipt) -> ResourceRejection | None:
    if receipt.outcome != "rejected":
        return None
    if receipt.failure_code == "CAP_EXCEEDED":
        return CapacityExceeded(receipt.failure_dimensions)
    if receipt.failure_code == "BUDGET_FROZEN":
        return BudgetFrozen()
    if receipt.failure_code == "GRANT_NOT_FOUND":
        return UnknownGrant(receipt.grant_id)
    if receipt.failure_code == "INVALID_TRANSITION":
        return InvalidTransition(receipt.failure_detail or "invalid transition")
    return ResourceRejection(
        receipt.failure_code or "REJECTED",
        receipt.failure_detail or "resource command rejected",
        dimensions=receipt.failure_dimensions,
    )


def _decide_fresh_accepted(state: ResourceState, command: ResourceCommand) -> Decision:
    if isinstance(command, RequestGrant):
        if state.status is BudgetStatus.FROZEN:
            raise BudgetFrozen()
        if any(grant.grant_id == command.grant_id for grant in state.grants):
            raise InvalidTransition(f"grant_id already exists: {command.grant_id}")

        observed = _utc_instant(command.observed_at, "observed_at")
        expires = _utc_instant(command.expires_at, "expires_at")
        valid_until = _utc_instant(command.estimate.valid_until, "valid_until")
        if observed > valid_until:
            raise InvalidTransition("estimate was stale when admission was observed")
        if expires > valid_until:
            raise InvalidTransition("grant expiry cannot outlive estimate validity")
        if observed >= expires:
            raise InvalidTransition("grant must be requested before its expiry")

        deficits = _admission_deficits(command.estimate.upper_bound, state.remaining)
        if deficits:
            raise CapacityExceeded(deficits)
        grant = ResourceGrant(
            grant_id=command.grant_id,
            estimate_sha256=command.estimate.estimate_sha256,
            workload_sha256=command.estimate.workload_sha256,
            reserved=command.estimate.upper_bound,
            reserved_at=command.observed_at,
            expires_at=command.expires_at,
            fence_token=command.fence_token,
            status=GrantStatus.RESERVED,
            last_observed_at=command.observed_at,
        )
        return _decision(
            state,
            command,
            outcome="reserved",
            grant=grant,
            reserved=grant.reserved,
        )

    grant = _bound_grant(state, command)

    if isinstance(command, StartGrant):
        if grant.status is not GrantStatus.RESERVED:
            raise InvalidTransition(f"cannot start grant in {grant.status.value}")
        start_observed = _utc_instant(command.observed_at, "observed_at")
        if start_observed < _utc_instant(grant.last_observed_at, "last_observed_at"):
            raise InvalidTransition("start observation precedes the grant lifecycle")
        if start_observed >= _utc_instant(
            grant.expires_at,
            "expires_at",
        ):
            raise InvalidTransition("cannot start a grant at or after its expiry")
        return _decision(
            state,
            command,
            outcome="in_use",
            grant=replace(
                grant,
                status=GrantStatus.IN_USE,
                started_at=command.observed_at,
                last_observed_at=command.observed_at,
            ),
            reserved=grant.reserved,
        )

    if isinstance(command, SettleGrant):
        allowed = {
            GrantStatus.IN_USE,
            GrantStatus.CANCEL_PENDING,
            GrantStatus.RECONCILIATION_REQUIRED,
        }
        if grant.status not in allowed:
            raise InvalidTransition(f"cannot settle grant in {grant.status.value}")
        usage = command.usage
        settle_observed = _utc_instant(command.observed_at, "observed_at")
        if settle_observed < _utc_instant(
            grant.last_observed_at,
            "last_observed_at",
        ):
            raise InvalidTransition("settlement observation precedes the grant lifecycle")
        if grant.started_at is None:  # defensive; ResourceGrant also enforces this
            raise InvalidTransition("settlement requires a recorded start")
        measured = _utc_instant(usage.measured_at, "measured_at")
        if measured < _utc_instant(grant.started_at, "started_at"):
            raise InvalidTransition("usage measurement precedes grant start")
        if measured > settle_observed:
            raise InvalidTransition("usage measurement is later than settlement observation")
        overrun = usage.actual.exceeds(grant.reserved)
        if overrun:
            updated = replace(
                grant,
                status=GrantStatus.QUARANTINED_OVERRUN,
                actual=usage.actual,
                measured_at=usage.measured_at,
                measurement_sha256=usage.measurement_sha256,
                evidence_sha256=usage.evidence_sha256,
                last_observed_at=command.observed_at,
            )
            return _decision(
                state,
                command,
                outcome="quarantined_overrun",
                grant=updated,
                reserved=grant.reserved,
                actual=usage.actual,
                released=grant.reserved.saturating_subtract(usage.actual),
                spent_delta=usage.actual,
                freeze_budget=True,
                failure_code="RESOURCE_OVERRUN",
                failure_detail="measured usage exceeded the reserved vector",
                failure_dimensions=overrun,
                evidence_sha256=usage.evidence_sha256,
            )
        status = (
            GrantStatus.CANCELLED_SETTLED
            if grant.cancel_requested
            else GrantStatus.SETTLED
        )
        updated = replace(
            grant,
            status=status,
            actual=usage.actual,
            measured_at=usage.measured_at,
            measurement_sha256=usage.measurement_sha256,
            evidence_sha256=usage.evidence_sha256,
            last_observed_at=command.observed_at,
        )
        return _decision(
            state,
            command,
            outcome=status.value.lower(),
            grant=updated,
            reserved=grant.reserved,
            actual=usage.actual,
            released=grant.reserved.subtract(usage.actual),
            spent_delta=usage.actual,
            evidence_sha256=usage.evidence_sha256,
        )

    if isinstance(command, CancelGrant):
        if _utc_instant(command.observed_at, "observed_at") < _utc_instant(
            grant.last_observed_at,
            "last_observed_at",
        ):
            raise InvalidTransition("cancel observation precedes the grant lifecycle")
        if grant.status is GrantStatus.RESERVED:
            return _decision(
                state,
                command,
                outcome="cancelled_unused",
                grant=replace(
                    grant,
                    status=GrantStatus.CANCELLED_UNUSED,
                    last_observed_at=command.observed_at,
                ),
                reserved=grant.reserved,
                released=grant.reserved,
            )
        if grant.status is GrantStatus.IN_USE:
            return _decision(
                state,
                command,
                outcome="cancel_pending",
                grant=replace(
                    grant,
                    status=GrantStatus.CANCEL_PENDING,
                    cancel_requested=True,
                    last_observed_at=command.observed_at,
                ),
                reserved=grant.reserved,
            )
        raise InvalidTransition(f"cannot cancel grant in {grant.status.value}")

    if isinstance(command, DeadlineObserved):
        deadline_observed = _utc_instant(command.observed_at, "observed_at")
        if deadline_observed < _utc_instant(
            grant.last_observed_at,
            "last_observed_at",
        ):
            raise InvalidTransition("deadline observation precedes the grant lifecycle")
        if deadline_observed < _utc_instant(
            grant.expires_at,
            "expires_at",
        ):
            raise InvalidTransition("deadline observation precedes grant expiry")
        if grant.status is GrantStatus.RESERVED:
            return _decision(
                state,
                command,
                outcome="expired_unused",
                grant=replace(
                    grant,
                    status=GrantStatus.EXPIRED_UNUSED,
                    last_observed_at=command.observed_at,
                ),
                reserved=grant.reserved,
                released=grant.reserved,
            )
        if grant.status is GrantStatus.IN_USE:
            return _decision(
                state,
                command,
                outcome="cancel_pending",
                grant=replace(
                    grant,
                    status=GrantStatus.CANCEL_PENDING,
                    cancel_requested=True,
                    last_observed_at=command.observed_at,
                ),
                reserved=grant.reserved,
            )
        raise InvalidTransition(f"cannot apply deadline in {grant.status.value}")

    if isinstance(command, UsageUnknown):
        if grant.status not in {GrantStatus.IN_USE, GrantStatus.CANCEL_PENDING}:
            raise InvalidTransition(f"usage cannot be unknown in {grant.status.value}")
        if _utc_instant(command.observed_at, "observed_at") < _utc_instant(
            grant.last_observed_at,
            "last_observed_at",
        ):
            raise InvalidTransition("usage observation precedes the grant lifecycle")
        return _decision(
            state,
            command,
            outcome="reconciliation_required",
            grant=replace(
                grant,
                status=GrantStatus.RECONCILIATION_REQUIRED,
                last_observed_at=command.observed_at,
            ),
            reserved=grant.reserved,
            failure_code="USAGE_UNKNOWN",
            failure_detail=command.reason,
        )

    raise TypeError(f"unsupported resource command: {type(command)!r}")


def _decide_fresh(
    state: ResourceState | _ResourceProjection,
    command: ResourceCommand,
) -> Decision:
    try:
        return _decide_fresh_accepted(state, command)
    except ResourceRejection as rejection:
        return _rejected_decision(state, command, rejection)


def _validate_transition_against(
    state: ResourceState | _ResourceProjection,
    transition: ResourceTransition,
) -> None:
    """Rehash and semantically replay one transition against its exact prefix."""

    if _command_hash(transition.command) != transition.command_sha256:
        raise InvalidTransition("command payload does not match its content hash")

    body = _transition_body(
        state=state,
        command=transition.command,
        command_sha256=transition.command_sha256,
        grant=transition.grant,
        spent_delta=transition.spent_delta,
        freeze_budget=transition.freeze_budget,
    )
    payload_sha256 = _canonical_sha(body)
    if payload_sha256 != transition.transition_payload_sha256:
        raise InvalidTransition("transition payload does not match its content hash")
    receipt = transition.receipt
    if receipt.transition_payload_sha256 != payload_sha256:
        raise InvalidTransition("receipt does not bind the transition payload")
    if receipt.receipt_sha256 != transition.receipt_sha256:
        raise InvalidTransition("receipt payload does not match its content hash")
    transition_sha256 = _canonical_sha(
        _transition_envelope(payload_sha256, transition.receipt_sha256)
    )
    if transition_sha256 != transition.transition_sha256:
        raise InvalidTransition("transition envelope does not match its content hash")
    if (
        receipt.budget_id != state.budget_id
        or receipt.scope != state.scope
        or receipt.epoch != state.epoch
        or receipt.before_revision != state.revision
        or receipt.after_revision != state.revision + 1
        or receipt.before_state_sha256 != state.snapshot_sha256
        or receipt.after_state_sha256 != _projected_state_sha256(
            state,
            transition.command,
            transition.grant,
            transition.spent_delta,
            transition.freeze_budget,
        )
        or receipt.command_id != transition.command.command_id
        or receipt.command_sha256 != transition.command_sha256
        or receipt.operation != _operation(transition.command)
        or receipt.engine_rule_sha256 != ENGINE_RULE_SHA256
    ):
        raise InvalidTransition("receipt identity or revision does not match current state")

    # Re-running the pure decision function is the closed semantic validator.  It
    # catches a self-consistently rehashed but illegal transition as well as ordinary
    # corruption, without duplicating the state machine in the reducer.
    expected = _decide_fresh(state, transition.command)
    if expected.transitions != (transition,):
        raise InvalidTransition("transition does not match the deterministic decision")


def _projection_after(
    state: ResourceState | _ResourceProjection,
    transition: ResourceTransition,
) -> _ResourceProjection:
    return _ResourceProjection(
        schema_version=state.schema_version,
        budget_id=state.budget_id,
        scope=state.scope,
        epoch=state.epoch,
        revision=state.revision + 1,
        hard_caps=state.hard_caps,
        spent=state.spent + transition.spent_delta,
        status=(
            BudgetStatus.FROZEN
            if transition.freeze_budget
            else state.status
        ),
        grants=_projected_grants(
            state,
            transition.command,
            transition.grant,
        ),
    )


def _validate_retained_history(state: ResourceState) -> None:
    """Replay the complete retained journal from genesis and match the snapshot."""

    projection = _ResourceProjection(
        schema_version=state.schema_version,
        budget_id=state.budget_id,
        scope=state.scope,
        epoch=state.epoch,
        revision=0,
        hard_caps=state.hard_caps,
        spent=ResourceVector.zero(),
        status=BudgetStatus.ACTIVE,
        grants=(),
    )
    if not state.command_records:
        if state.snapshot_sha256 != projection.snapshot_sha256:
            raise ValueError("empty journal state must equal the budget genesis")
        return

    for record in state.command_records:
        if not isinstance(record, _CommandRecord):
            raise ValueError("command_records must contain internal command records")
        _identifier(record.command_id, "record.command_id")
        _sha256(record.command_sha256, "record.command_sha256")
        _sha256(record.receipt_sha256, "record.receipt_sha256")
        _sha256(record.transition_sha256, "record.transition_sha256")
        if not isinstance(record.receipt, ResourceReceipt):
            raise ValueError("command record receipt must be a ResourceReceipt")
        if not isinstance(record.transition, ResourceTransition):
            raise ValueError("command record transition must be a ResourceTransition")

        transition = record.transition
        receipt = record.receipt
        if (
            record.command_id != transition.command.command_id
            or record.command_id != receipt.command_id
        ):
            raise ValueError("command record, transition, and receipt IDs diverged")
        if (
            record.command_sha256 != transition.command_sha256
            or record.command_sha256 != receipt.command_sha256
        ):
            raise ValueError("command record, transition, and receipt hashes diverged")
        if (
            record.receipt != transition.receipt
            or record.receipt_sha256 != transition.receipt_sha256
            or record.receipt_sha256 != receipt.receipt_sha256
        ):
            raise ValueError("command record receipt binding is invalid")
        if record.transition_sha256 != transition.transition_sha256:
            raise ValueError("command record transition hash is invalid")
        if (
            projection.revision == 0
            and receipt.before_state_sha256 != projection.snapshot_sha256
        ):
            raise ValueError("journal does not begin at this budget genesis")
        try:
            _validate_transition_against(projection, transition)
        except ResourceRejection as exc:
            raise ValueError(
                "command record failed deterministic semantic replay"
            ) from exc
        projection = _projection_after(projection, transition)

    if (
        projection.revision != state.revision
        or projection.spent != state.spent
        or projection.status is not state.status
        or projection.grants != state.grants
        or projection.snapshot_sha256 != state.snapshot_sha256
    ):
        raise ValueError("current state diverges from the retained journal replay")


def decide(state: ResourceState, command: ResourceCommand) -> Decision:
    """Return one durable transition, or the exact prior decision on replay."""

    if not isinstance(command, (
        RequestGrant,
        StartGrant,
        SettleGrant,
        CancelGrant,
        DeadlineObserved,
        UsageUnknown,
    )):
        raise TypeError(f"unsupported resource command: {type(command)!r}")

    command_sha256 = _command_hash(command)
    for record in state.command_records:
        if record.command_id != command.command_id:
            continue
        if record.command_sha256 != command_sha256:
            raise IdempotencyConflict(command.command_id)
        return Decision(
            transitions=(),
            replayed=True,
            _replay_receipt=record.receipt,
        )
    return _decide_fresh(state, command)


def evolve(state: ResourceState, transition: ResourceTransition) -> ResourceState:
    """Apply one semantic transition after content and decision revalidation."""

    if any(
        record.command_id == transition.command.command_id
        for record in state.command_records
    ):
        raise InvalidTransition("command transition was already applied")
    _validate_transition_against(state, transition)
    projection = _projection_after(state, transition)

    return ResourceState(
        schema_version=state.schema_version,
        budget_id=state.budget_id,
        scope=state.scope,
        epoch=state.epoch,
        revision=state.revision + 1,
        hard_caps=state.hard_caps,
        spent=projection.spent,
        status=projection.status,
        grants=projection.grants,
        command_records=state.command_records + (
            _CommandRecord(
                command_id=transition.command.command_id,
                command_sha256=transition.command_sha256,
                receipt_sha256=transition.receipt_sha256,
                transition_sha256=transition.transition_sha256,
                receipt=transition.receipt,
                transition=transition,
            ),
        ),
    )


def evolve_all(state: ResourceState, decision: Decision) -> ResourceState:
    """Apply all transitions; an exact replay has none and is a no-op."""

    for transition in decision.transitions:
        state = evolve(state, transition)
    return state


def raise_for_rejection(decision: Decision) -> None:
    """Optional exception-style boundary for adapters that prefer raising."""

    if decision.rejection is not None:
        raise decision.rejection


__all__ = [
    "BudgetFrozen",
    "BudgetStatus",
    "CancelGrant",
    "CapacityExceeded",
    "DeadlineObserved",
    "Decision",
    "DIMENSIONS",
    "ENGINE_RULE_SHA256",
    "GrantStatus",
    "IdempotencyConflict",
    "InvalidTransition",
    "RequestGrant",
    "ResourceBudget",
    "ResourceEstimate",
    "ResourceGrant",
    "ResourceReceipt",
    "ResourceRejection",
    "ResourceState",
    "ResourceTransition",
    "ResourceUsage",
    "ResourceVector",
    "SCHEMA_VERSION",
    "SettleGrant",
    "StartGrant",
    "UnknownGrant",
    "UsageUnknown",
    "decide",
    "evolve",
    "evolve_all",
    "raise_for_rejection",
]
