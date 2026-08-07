"""Pure workload-dispatch authority derived from the resource journal.

``StartGrant`` is the operation-specific durable intent for
``workload.dispatch/v1``.  A permit is only a short-lived immutable snapshot of
that intent and a confirmed journal authority; callers must revalidate it against
a fresh authority immediately before crossing the effect boundary.

This module performs no I/O and reads no ambient clock.  It deliberately does not
claim generic exactly-once execution: replay safety also requires an effect adapter
that durably deduplicates the stable intent and exposes reconciliation when an
outcome is unknown.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import string

from lakatos.resource_coordination import (
    GrantStatus,
    IdempotencyConflict,
    RequestGrant,
    ResourceState,
    StartGrant,
)


EXECUTION_SCHEMA_VERSION = "lakatotree.resource-execution/v1"
WORKLOAD_DISPATCH_OPERATION = "workload.dispatch/v1"
DEFAULT_WORKLOAD_DISPATCH_PERMIT_TTL_SECONDS = 30
MAX_WORKLOAD_DISPATCH_PERMIT_TTL_SECONDS = 300
_RFC3339_UTC = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$"
)


def _canonical_sha(value: dict) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _identifier(value: str, label: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 256
        or not value.isprintable()
    ):
        raise ValueError(f"{label} must be a printable non-empty string <= 256 chars")


def _sha256(value: str, label: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or value != value.lower()
        or any(character not in string.hexdigits for character in value)
    ):
        raise ValueError(f"{label} must be a lowercase hexadecimal SHA-256")


def _integer(value: int, label: str, *, minimum: int = 0) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")


def _utc_instant(value: str, label: str) -> datetime:
    if not isinstance(value, str) or _RFC3339_UTC.fullmatch(value) is None:
        raise ValueError(f"{label} must be an RFC3339 UTC timestamp ending in Z")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{label} must be a valid RFC3339 UTC timestamp") from exc


def _utc_text(value: datetime) -> str:
    normalized = value.astimezone(timezone.utc)
    timespec = "microseconds" if normalized.microsecond else "seconds"
    return normalized.isoformat(timespec=timespec).replace("+00:00", "Z")


class ResourceExecutionAuthorityError(RuntimeError):
    """Base class for fail-closed workload-dispatch authorization failures."""


class UnconfirmedResourceAuthority(ResourceExecutionAuthorityError):
    pass


class StaleResourceAuthority(ResourceExecutionAuthorityError):
    pass


class InvalidWorkloadDispatchIntent(ResourceExecutionAuthorityError):
    pass


class StaleWorkloadDispatchPermit(ResourceExecutionAuthorityError):
    pass


class ExpiredWorkloadDispatchPermit(ResourceExecutionAuthorityError):
    pass


@dataclass(frozen=True, slots=True)
class ResourceAuthority:
    """Exact externally confirmed journal cut supplied by an I/O adapter."""

    budget_id: str
    scope: str
    epoch: int
    revision: int
    state_sha256: str
    checkpoint_sha256: str
    journal_head_sha256: str
    anchor_status: str
    schema_version: str = EXECUTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EXECUTION_SCHEMA_VERSION:
            raise ValueError("unsupported resource authority schema")
        _identifier(self.budget_id, "authority.budget_id")
        _identifier(self.scope, "authority.scope")
        _integer(self.epoch, "authority.epoch", minimum=1)
        _integer(self.revision, "authority.revision")
        _sha256(self.state_sha256, "authority.state_sha256")
        _sha256(self.checkpoint_sha256, "authority.checkpoint_sha256")
        _sha256(self.journal_head_sha256, "authority.journal_head_sha256")
        if self.anchor_status not in {"PENDING", "CONFIRMED"}:
            raise ValueError("authority.anchor_status must be PENDING or CONFIRMED")

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "budget_id": self.budget_id,
            "scope": self.scope,
            "epoch": self.epoch,
            "revision": self.revision,
            "state_sha256": self.state_sha256,
            "checkpoint_sha256": self.checkpoint_sha256,
            "journal_head_sha256": self.journal_head_sha256,
            "anchor_status": self.anchor_status,
        }


@dataclass(frozen=True, slots=True)
class WorkloadDispatchIntentReference:
    """Stable journal-derived identity used for restart-safe reconciliation."""

    effect_id: str
    budget_id: str
    scope: str
    epoch: int
    grant_id: str
    fence_token: int
    workload_sha256: str
    estimate_sha256: str
    adapter: str
    adapter_version: str
    start_command_sha256: str
    start_receipt_sha256: str
    intent_sha256: str
    start_observed_at: str
    start_revision: int
    grant_expires_at: str
    operation: str = WORKLOAD_DISPATCH_OPERATION
    schema_version: str = EXECUTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EXECUTION_SCHEMA_VERSION:
            raise ValueError("unsupported workload-dispatch intent schema")
        if self.operation != WORKLOAD_DISPATCH_OPERATION:
            raise ValueError("unsupported workload-dispatch operation")
        for label, value in (
            ("effect_id", self.effect_id),
            ("budget_id", self.budget_id),
            ("scope", self.scope),
            ("grant_id", self.grant_id),
            ("adapter", self.adapter),
            ("adapter_version", self.adapter_version),
        ):
            _identifier(value, f"intent reference.{label}")
        _integer(self.epoch, "intent reference.epoch", minimum=1)
        _integer(self.fence_token, "intent reference.fence_token", minimum=1)
        _integer(self.start_revision, "intent reference.start_revision", minimum=1)
        for label, value in (
            ("workload_sha256", self.workload_sha256),
            ("estimate_sha256", self.estimate_sha256),
            ("start_command_sha256", self.start_command_sha256),
            ("start_receipt_sha256", self.start_receipt_sha256),
            ("intent_sha256", self.intent_sha256),
        ):
            _sha256(value, f"intent reference.{label}")
        started = _utc_instant(
            self.start_observed_at,
            "intent reference.start_observed_at",
        )
        expires = _utc_instant(
            self.grant_expires_at,
            "intent reference.grant_expires_at",
        )
        if started >= expires:
            raise ValueError("dispatch intent must start before grant expiry")

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "operation": self.operation,
            "effect_id": self.effect_id,
            "budget_id": self.budget_id,
            "scope": self.scope,
            "epoch": self.epoch,
            "grant_id": self.grant_id,
            "fence_token": self.fence_token,
            "workload_sha256": self.workload_sha256,
            "estimate_sha256": self.estimate_sha256,
            "adapter": self.adapter,
            "adapter_version": self.adapter_version,
            "start_command_sha256": self.start_command_sha256,
            "start_receipt_sha256": self.start_receipt_sha256,
            "intent_sha256": self.intent_sha256,
            "start_observed_at": self.start_observed_at,
            "start_revision": self.start_revision,
            "grant_expires_at": self.grant_expires_at,
        }


@dataclass(frozen=True, slots=True)
class WorkloadDispatchPermit:
    """One operation's authority, never a generic ``executable`` flag."""

    effect_id: str
    budget_id: str
    scope: str
    epoch: int
    grant_id: str
    fence_token: int
    workload_sha256: str
    estimate_sha256: str
    adapter: str
    adapter_version: str
    start_command_sha256: str
    start_receipt_sha256: str
    intent_sha256: str
    start_observed_at: str
    start_revision: int
    authority_revision: int
    authority_state_sha256: str
    authority_checkpoint_sha256: str
    authority_journal_head_sha256: str
    issued_at: str
    expires_at: str
    grant_expires_at: str
    operation: str = WORKLOAD_DISPATCH_OPERATION
    schema_version: str = EXECUTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EXECUTION_SCHEMA_VERSION:
            raise ValueError("unsupported workload-dispatch permit schema")
        if self.operation != WORKLOAD_DISPATCH_OPERATION:
            raise ValueError("unsupported workload-dispatch operation")
        self.intent_reference
        _integer(self.authority_revision, "permit.authority_revision", minimum=1)
        if self.start_revision > self.authority_revision:
            raise ValueError("permit start revision cannot exceed authority revision")
        for label, value in (
            ("authority_state_sha256", self.authority_state_sha256),
            ("authority_checkpoint_sha256", self.authority_checkpoint_sha256),
            ("authority_journal_head_sha256", self.authority_journal_head_sha256),
        ):
            _sha256(value, f"permit.{label}")
        issued = _utc_instant(self.issued_at, "permit.issued_at")
        start_observed = _utc_instant(
            self.start_observed_at,
            "permit.start_observed_at",
        )
        expires = _utc_instant(self.expires_at, "permit.expires_at")
        grant_expires = _utc_instant(
            self.grant_expires_at,
            "permit.grant_expires_at",
        )
        if issued >= expires:
            raise ValueError("permit must be issued before its expiry")
        if issued < start_observed:
            raise ValueError("permit cannot be issued before StartGrant")
        if expires > grant_expires:
            raise ValueError("permit cannot outlive its resource grant")
        if expires - issued > timedelta(
            seconds=MAX_WORKLOAD_DISPATCH_PERMIT_TTL_SECONDS
        ):
            raise ValueError("permit lifetime exceeds the closed maximum TTL")

    def to_dict(self) -> dict:
        return {
            **self.intent_reference.to_dict(),
            "authority_revision": self.authority_revision,
            "authority_state_sha256": self.authority_state_sha256,
            "authority_checkpoint_sha256": self.authority_checkpoint_sha256,
            "authority_journal_head_sha256": self.authority_journal_head_sha256,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }

    @property
    def intent_reference(self) -> WorkloadDispatchIntentReference:
        return WorkloadDispatchIntentReference(
            effect_id=self.effect_id,
            budget_id=self.budget_id,
            scope=self.scope,
            epoch=self.epoch,
            grant_id=self.grant_id,
            fence_token=self.fence_token,
            workload_sha256=self.workload_sha256,
            estimate_sha256=self.estimate_sha256,
            adapter=self.adapter,
            adapter_version=self.adapter_version,
            start_command_sha256=self.start_command_sha256,
            start_receipt_sha256=self.start_receipt_sha256,
            intent_sha256=self.intent_sha256,
            start_observed_at=self.start_observed_at,
            start_revision=self.start_revision,
            grant_expires_at=self.grant_expires_at,
            operation=self.operation,
            schema_version=self.schema_version,
        )

    @property
    def permit_sha256(self) -> str:
        return _canonical_sha(self.to_dict())


@dataclass(frozen=True, slots=True)
class WorkloadDispatchReceipt:
    """Effect-port evidence bound to the stable persisted dispatch intent."""

    effect_id: str
    workload_sha256: str
    fence_token: int
    intent_sha256: str
    completed_at: str
    evidence_sha256: str
    operation: str = WORKLOAD_DISPATCH_OPERATION
    schema_version: str = EXECUTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EXECUTION_SCHEMA_VERSION:
            raise ValueError("unsupported workload-dispatch receipt schema")
        if self.operation != WORKLOAD_DISPATCH_OPERATION:
            raise ValueError("unsupported workload-dispatch receipt operation")
        _identifier(self.effect_id, "dispatch receipt.effect_id")
        _integer(self.fence_token, "dispatch receipt.fence_token", minimum=1)
        for label, value in (
            ("workload_sha256", self.workload_sha256),
            ("intent_sha256", self.intent_sha256),
            ("evidence_sha256", self.evidence_sha256),
        ):
            _sha256(value, f"dispatch receipt.{label}")
        _utc_instant(self.completed_at, "dispatch receipt.completed_at")

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "operation": self.operation,
            "effect_id": self.effect_id,
            "workload_sha256": self.workload_sha256,
            "fence_token": self.fence_token,
            "intent_sha256": self.intent_sha256,
            "completed_at": self.completed_at,
            "evidence_sha256": self.evidence_sha256,
        }

    @property
    def receipt_sha256(self) -> str:
        return _canonical_sha(self.to_dict())


@dataclass(frozen=True, slots=True)
class _StartIntentMaterial:
    command: StartGrant
    command_sha256: str
    receipt_sha256: str
    estimate_sha256: str
    adapter: str
    adapter_version: str
    start_revision: int
    expires_at: str


def require_current_confirmed_authority(
    state: ResourceState,
    authority: ResourceAuthority,
) -> None:
    """Fail unless ``authority`` is confirmed and describes ``state`` exactly."""

    if not isinstance(state, ResourceState):
        raise TypeError("state must be a ResourceState")
    if not isinstance(authority, ResourceAuthority):
        raise TypeError("authority must be a ResourceAuthority")
    if authority.anchor_status != "CONFIRMED":
        raise UnconfirmedResourceAuthority(
            f"resource authority is {authority.anchor_status}, not CONFIRMED"
        )
    identity = (state.budget_id, state.scope, state.epoch)
    if identity != (authority.budget_id, authority.scope, authority.epoch):
        raise StaleResourceAuthority("resource authority budget identity diverged")
    if state.revision != authority.revision:
        raise StaleResourceAuthority("resource authority revision diverged")
    if state.snapshot_sha256 != authority.state_sha256:
        raise StaleResourceAuthority("resource authority state hash diverged")


def _start_intent_material(
    state: ResourceState,
    *,
    effect_id: str,
    allowed_statuses: frozenset[GrantStatus] = frozenset({GrantStatus.IN_USE}),
) -> _StartIntentMaterial:
    _identifier(effect_id, "effect_id")
    record = next(
        (item for item in state.command_records if item.command_id == effect_id),
        None,
    )
    if record is None or not isinstance(record.transition.command, StartGrant):
        raise InvalidWorkloadDispatchIntent(
            "effect_id does not name a persisted StartGrant intent"
        )
    command = record.transition.command
    receipt = record.receipt
    if receipt.operation != "start_grant" or receipt.outcome != "in_use":
        raise InvalidWorkloadDispatchIntent(
            "persisted StartGrant was not accepted into IN_USE"
        )
    if (
        receipt.command_id != command.command_id
        or receipt.command_sha256 != record.command_sha256
        or receipt.receipt_sha256 != record.receipt_sha256
        or receipt.after_revision < 1
    ):
        raise InvalidWorkloadDispatchIntent("StartGrant journal binding diverged")
    try:
        grant = state.grant(command.grant_id)
    except RuntimeError as exc:
        raise InvalidWorkloadDispatchIntent("StartGrant grant is absent") from exc
    if grant.status not in allowed_statuses:
        raise InvalidWorkloadDispatchIntent(
            f"StartGrant grant status is not dispatch-valid: {grant.status.value}"
        )
    if grant.started_at is None or grant.started_at != command.observed_at:
        raise InvalidWorkloadDispatchIntent("grant start observation diverged")
    if (
        grant.fence_token != command.fence_token
        or grant.workload_sha256 != command.workload_sha256
    ):
        raise InvalidWorkloadDispatchIntent("grant fence/workload binding diverged")
    request_record = next(
        (
            item
            for item in state.command_records
            if isinstance(item.transition.command, RequestGrant)
            and item.transition.command.grant_id == command.grant_id
            and item.receipt.outcome == "reserved"
        ),
        None,
    )
    if request_record is None:
        raise InvalidWorkloadDispatchIntent("accepted grant request is absent")
    request = request_record.transition.command
    if request.estimate.estimate_sha256 != grant.estimate_sha256:
        raise InvalidWorkloadDispatchIntent("grant estimate binding diverged")
    return _StartIntentMaterial(
        command=command,
        command_sha256=record.command_sha256,
        receipt_sha256=record.receipt_sha256,
        estimate_sha256=request.estimate.estimate_sha256,
        adapter=request.estimate.adapter,
        adapter_version=request.estimate.adapter_version,
        start_revision=receipt.after_revision,
        expires_at=grant.expires_at,
    )


def _require_observation_window(
    material: _StartIntentMaterial,
    observed_at: str,
    *,
    expires_at: str | None = None,
) -> None:
    observed = _utc_instant(observed_at, "observed_at")
    started = _utc_instant(material.command.observed_at, "start observed_at")
    expires = _utc_instant(
        expires_at or material.expires_at,
        "dispatch expires_at",
    )
    if observed < started:
        raise InvalidWorkloadDispatchIntent("dispatch observation precedes StartGrant")
    if observed >= expires:
        raise ExpiredWorkloadDispatchPermit(
            "workload-dispatch authority expired before effect execution"
        )


def validate_start_grant_preflight(
    state: ResourceState,
    start: StartGrant,
    *,
    observed_at: str,
) -> tuple[str, str]:
    """Reject an already-expired or misbound start before it is persisted."""

    if not isinstance(state, ResourceState):
        raise TypeError("state must be a ResourceState")
    if not isinstance(start, StartGrant):
        raise TypeError("start must be a StartGrant")
    existing = next(
        (record for record in state.command_records if record.command_id == start.command_id),
        None,
    )
    if existing is not None:
        if existing.transition.command != start:
            raise IdempotencyConflict(start.command_id)
        material = _start_intent_material(state, effect_id=start.command_id)
        _require_observation_window(material, observed_at)
        return material.adapter, material.adapter_version
    try:
        grant = state.grant(start.grant_id)
    except RuntimeError as exc:
        raise InvalidWorkloadDispatchIntent("StartGrant grant is absent") from exc
    if grant.status is not GrantStatus.RESERVED:
        raise InvalidWorkloadDispatchIntent(
            f"cannot prepare dispatch from {grant.status.value}"
        )
    if (
        grant.fence_token != start.fence_token
        or grant.workload_sha256 != start.workload_sha256
    ):
        raise InvalidWorkloadDispatchIntent("StartGrant fence/workload binding diverged")
    observed = _utc_instant(observed_at, "observed_at")
    if observed < _utc_instant(start.observed_at, "start.observed_at"):
        raise InvalidWorkloadDispatchIntent("preflight observation precedes StartGrant")
    if observed >= _utc_instant(grant.expires_at, "grant.expires_at"):
        raise ExpiredWorkloadDispatchPermit(
            "resource grant expired before StartGrant could become an effect intent"
        )
    request_record = next(
        (
            item
            for item in state.command_records
            if isinstance(item.transition.command, RequestGrant)
            and item.transition.command.grant_id == start.grant_id
            and item.receipt.outcome == "reserved"
        ),
        None,
    )
    if request_record is None:
        raise InvalidWorkloadDispatchIntent("accepted grant request is absent")
    estimate = request_record.transition.command.estimate
    if estimate.estimate_sha256 != grant.estimate_sha256:
        raise InvalidWorkloadDispatchIntent("grant estimate binding diverged")
    return estimate.adapter, estimate.adapter_version


def _intent_sha256(
    state: ResourceState,
    material: _StartIntentMaterial,
) -> str:
    command = material.command
    return _canonical_sha(
        {
            "schema_version": EXECUTION_SCHEMA_VERSION,
            "operation": WORKLOAD_DISPATCH_OPERATION,
            "effect_id": command.command_id,
            "budget_id": state.budget_id,
            "scope": state.scope,
            "epoch": state.epoch,
            "grant_id": command.grant_id,
            "fence_token": command.fence_token,
            "workload_sha256": command.workload_sha256,
            "estimate_sha256": material.estimate_sha256,
            "adapter": material.adapter,
            "adapter_version": material.adapter_version,
            "start_command_sha256": material.command_sha256,
            "start_receipt_sha256": material.receipt_sha256,
            "start_observed_at": command.observed_at,
            "start_revision": material.start_revision,
            "grant_expires_at": material.expires_at,
        }
    )


def mint_workload_dispatch_permit(
    state: ResourceState,
    authority: ResourceAuthority,
    *,
    effect_id: str,
    observed_at: str,
    max_ttl_seconds: int = DEFAULT_WORKLOAD_DISPATCH_PERMIT_TTL_SECONDS,
) -> WorkloadDispatchPermit:
    """Derive a permit from one confirmed cut and its accepted StartGrant."""

    require_current_confirmed_authority(state, authority)
    _integer(max_ttl_seconds, "max_ttl_seconds", minimum=1)
    if max_ttl_seconds > MAX_WORKLOAD_DISPATCH_PERMIT_TTL_SECONDS:
        raise ValueError("max_ttl_seconds exceeds the closed maximum")
    material = _start_intent_material(state, effect_id=effect_id)
    _require_observation_window(material, observed_at)
    command = material.command
    issued = _utc_instant(observed_at, "observed_at")
    grant_expires = _utc_instant(material.expires_at, "grant expires_at")
    permit_expires = min(
        grant_expires,
        issued + timedelta(seconds=max_ttl_seconds),
    )
    return WorkloadDispatchPermit(
        effect_id=command.command_id,
        budget_id=state.budget_id,
        scope=state.scope,
        epoch=state.epoch,
        grant_id=command.grant_id,
        fence_token=command.fence_token,
        workload_sha256=command.workload_sha256,
        estimate_sha256=material.estimate_sha256,
        adapter=material.adapter,
        adapter_version=material.adapter_version,
        start_command_sha256=material.command_sha256,
        start_receipt_sha256=material.receipt_sha256,
        intent_sha256=_intent_sha256(state, material),
        start_observed_at=command.observed_at,
        start_revision=material.start_revision,
        authority_revision=authority.revision,
        authority_state_sha256=authority.state_sha256,
        authority_checkpoint_sha256=authority.checkpoint_sha256,
        authority_journal_head_sha256=authority.journal_head_sha256,
        issued_at=observed_at,
        expires_at=_utc_text(permit_expires),
        grant_expires_at=material.expires_at,
    )


def revalidate_workload_dispatch_permit(
    state: ResourceState,
    authority: ResourceAuthority,
    permit: WorkloadDispatchPermit,
    *,
    observed_at: str,
) -> WorkloadDispatchPermit:
    """Revalidate an exact permit against a newly loaded confirmed authority."""

    if not isinstance(permit, WorkloadDispatchPermit):
        raise TypeError("permit must be a WorkloadDispatchPermit")
    require_current_confirmed_authority(state, authority)
    if (
        permit.budget_id,
        permit.scope,
        permit.epoch,
    ) != (
        authority.budget_id,
        authority.scope,
        authority.epoch,
    ):
        raise StaleWorkloadDispatchPermit("permit budget identity is stale")
    if (
        permit.authority_revision != authority.revision
        or permit.authority_state_sha256 != authority.state_sha256
        or permit.authority_checkpoint_sha256 != authority.checkpoint_sha256
        or permit.authority_journal_head_sha256 != authority.journal_head_sha256
    ):
        raise StaleWorkloadDispatchPermit("permit journal authority is stale")
    observed = _utc_instant(observed_at, "observed_at")
    if observed < _utc_instant(permit.issued_at, "permit.issued_at"):
        raise InvalidWorkloadDispatchIntent("dispatch observation precedes permit issue")
    material = _start_intent_material(state, effect_id=permit.effect_id)
    _require_observation_window(material, observed_at, expires_at=permit.expires_at)
    command = material.command
    expected = (
        command.grant_id,
        command.fence_token,
        command.workload_sha256,
        material.estimate_sha256,
        material.adapter,
        material.adapter_version,
        material.command_sha256,
        material.receipt_sha256,
        _intent_sha256(state, material),
        command.observed_at,
        material.start_revision,
        material.expires_at,
    )
    actual = (
        permit.grant_id,
        permit.fence_token,
        permit.workload_sha256,
        permit.estimate_sha256,
        permit.adapter,
        permit.adapter_version,
        permit.start_command_sha256,
        permit.start_receipt_sha256,
        permit.intent_sha256,
        permit.start_observed_at,
        permit.start_revision,
        permit.grant_expires_at,
    )
    if actual != expected:
        raise StaleWorkloadDispatchPermit("permit StartGrant binding is stale")
    return permit


_RECOVERABLE_GRANT_STATUSES = frozenset(
    {
        GrantStatus.IN_USE,
        GrantStatus.CANCEL_PENDING,
        GrantStatus.RECONCILIATION_REQUIRED,
    }
)


def derive_workload_dispatch_intent_reference(
    state: ResourceState,
    *,
    effect_id: str,
) -> WorkloadDispatchIntentReference:
    """Reconstruct stable recovery identity solely from persisted journal state."""

    if not isinstance(state, ResourceState):
        raise TypeError("state must be a ResourceState")
    material = _start_intent_material(
        state,
        effect_id=effect_id,
        allowed_statuses=_RECOVERABLE_GRANT_STATUSES,
    )
    command = material.command
    return WorkloadDispatchIntentReference(
        effect_id=command.command_id,
        budget_id=state.budget_id,
        scope=state.scope,
        epoch=state.epoch,
        grant_id=command.grant_id,
        fence_token=command.fence_token,
        workload_sha256=command.workload_sha256,
        estimate_sha256=material.estimate_sha256,
        adapter=material.adapter,
        adapter_version=material.adapter_version,
        start_command_sha256=material.command_sha256,
        start_receipt_sha256=material.receipt_sha256,
        intent_sha256=_intent_sha256(state, material),
        start_observed_at=command.observed_at,
        start_revision=material.start_revision,
        grant_expires_at=material.expires_at,
    )


def recoverable_workload_dispatch_effect_ids(state: ResourceState) -> tuple[str, ...]:
    """Discover accepted unresolved dispatch intents in journal order."""

    if not isinstance(state, ResourceState):
        raise TypeError("state must be a ResourceState")
    effect_ids: list[str] = []
    for record in state.command_records:
        command = record.transition.command
        if not isinstance(command, StartGrant) or record.receipt.outcome != "in_use":
            continue
        try:
            derive_workload_dispatch_intent_reference(
                state,
                effect_id=command.command_id,
            )
        except InvalidWorkloadDispatchIntent:
            continue
        effect_ids.append(command.command_id)
    return tuple(effect_ids)


def validate_workload_dispatch_intent_reference(
    state: ResourceState,
    reference: WorkloadDispatchIntentReference,
) -> WorkloadDispatchIntentReference:
    """Validate a stable recovery reference without reviving an old permit."""

    if not isinstance(reference, WorkloadDispatchIntentReference):
        raise TypeError("reference must be a WorkloadDispatchIntentReference")
    expected = derive_workload_dispatch_intent_reference(
        state,
        effect_id=reference.effect_id,
    )
    if reference != expected:
        raise InvalidWorkloadDispatchIntent("stable dispatch intent binding diverged")
    return reference


def validate_workload_dispatch_receipt(
    reference: WorkloadDispatchIntentReference,
    receipt: WorkloadDispatchReceipt,
) -> WorkloadDispatchReceipt:
    """Require one effect receipt to match the stable intent and causal time."""

    if not isinstance(reference, WorkloadDispatchIntentReference):
        raise TypeError("reference must be a WorkloadDispatchIntentReference")
    if not isinstance(receipt, WorkloadDispatchReceipt):
        raise TypeError("receipt must be a WorkloadDispatchReceipt")
    expected = (
        reference.operation,
        reference.effect_id,
        reference.workload_sha256,
        reference.fence_token,
        reference.intent_sha256,
    )
    actual = (
        receipt.operation,
        receipt.effect_id,
        receipt.workload_sha256,
        receipt.fence_token,
        receipt.intent_sha256,
    )
    if actual != expected:
        raise InvalidWorkloadDispatchIntent("effect receipt binding diverged")
    if _utc_instant(receipt.completed_at, "receipt.completed_at") < _utc_instant(
        reference.start_observed_at,
        "intent reference.start_observed_at",
    ):
        raise InvalidWorkloadDispatchIntent("effect receipt predates StartGrant intent")
    return receipt


__all__ = [
    "EXECUTION_SCHEMA_VERSION",
    "DEFAULT_WORKLOAD_DISPATCH_PERMIT_TTL_SECONDS",
    "MAX_WORKLOAD_DISPATCH_PERMIT_TTL_SECONDS",
    "ExpiredWorkloadDispatchPermit",
    "InvalidWorkloadDispatchIntent",
    "ResourceAuthority",
    "ResourceExecutionAuthorityError",
    "StaleResourceAuthority",
    "StaleWorkloadDispatchPermit",
    "UnconfirmedResourceAuthority",
    "WORKLOAD_DISPATCH_OPERATION",
    "WorkloadDispatchPermit",
    "WorkloadDispatchIntentReference",
    "WorkloadDispatchReceipt",
    "derive_workload_dispatch_intent_reference",
    "mint_workload_dispatch_permit",
    "require_current_confirmed_authority",
    "revalidate_workload_dispatch_permit",
    "recoverable_workload_dispatch_effect_ids",
    "validate_start_grant_preflight",
    "validate_workload_dispatch_intent_reference",
    "validate_workload_dispatch_receipt",
]
