"""Imperative workload-dispatch gate over the durable resource journal.

The gate persists ``StartGrant`` before minting short-lived authority, then
reloads and revalidates the confirmed journal cut immediately before invoking an
idempotent effect port.  Adapter failures and invalid receipts are durably marked
``UsageUnknown`` whenever the journal remains reachable; recovery uses the same
stable intent through the adapter's authoritative lookup operation.

This module deliberately does not claim generic exactly-once delivery.  A real
effect adapter must durably deduplicate the stable intent and atomically enforce
the fence at its own target boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import hmac
from typing import NoReturn, Protocol

from lakatos.io._resource_journal_contracts import (
    DurableDecision,
    JournalSnapshot,
)
from lakatos.resource_coordination import (
    GrantStatus,
    ResourceCommand,
    ResourceUsage,
    SettleGrant,
    StartGrant,
    UsageUnknown,
)
from lakatos.resource_execution import (
    DEFAULT_WORKLOAD_DISPATCH_PERMIT_TTL_SECONDS,
    MAX_WORKLOAD_DISPATCH_PERMIT_TTL_SECONDS,
    InvalidWorkloadDispatchIntent,
    ResourceAuthority,
    WorkloadDispatchIntentReference,
    WorkloadDispatchPermit,
    WorkloadDispatchReceipt,
    derive_workload_dispatch_intent_reference,
    mint_workload_dispatch_permit,
    recoverable_workload_dispatch_effect_ids,
    require_current_confirmed_authority,
    revalidate_workload_dispatch_permit,
    validate_start_grant_preflight,
    validate_workload_dispatch_intent_reference,
    validate_workload_dispatch_receipt,
)


_PERMIT_AUTH_DOMAIN = b"lakatotree-workload-dispatch-permit\x00v1\n"


class UnauthenticatedWorkloadDispatchPermit(RuntimeError):
    """The permit envelope was not issued by this gate's pinned authority."""


@dataclass(frozen=True, slots=True)
class AuthenticatedWorkloadDispatchPermit:
    """Authenticated I/O-shell envelope around a pure permit claim."""

    permit: WorkloadDispatchPermit
    issuer: str
    authentication_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.permit, WorkloadDispatchPermit):
            raise TypeError("authenticated permit must wrap a WorkloadDispatchPermit")
        if (
            not isinstance(self.issuer, str)
            or not self.issuer
            or len(self.issuer) > 256
            or not self.issuer.isprintable()
        ):
            raise ValueError("permit issuer must be printable and <= 256 chars")
        if (
            not isinstance(self.authentication_sha256, str)
            or len(self.authentication_sha256) != 64
            or self.authentication_sha256 != self.authentication_sha256.lower()
            or any(
                character not in "0123456789abcdef"
                for character in self.authentication_sha256
            )
        ):
            raise ValueError("permit authentication must be a lowercase SHA-256 tag")


class PermitAuthenticatorPort(Protocol):
    def seal(
        self,
        permit: WorkloadDispatchPermit,
    ) -> AuthenticatedWorkloadDispatchPermit:
        ...

    def open(
        self,
        authorization: AuthenticatedWorkloadDispatchPermit,
    ) -> WorkloadDispatchPermit:
        ...


class HMACPermitAuthenticator:
    """Pinned composition-root authenticator for in-process permit handoff."""

    def __init__(self, *, signing_key: bytes, issuer: str) -> None:
        if not isinstance(signing_key, bytes) or len(signing_key) < 32:
            raise ValueError("permit signing_key must contain at least 32 bytes")
        if (
            not isinstance(issuer, str)
            or not issuer
            or len(issuer) > 256
            or not issuer.isprintable()
        ):
            raise ValueError("permit issuer must be printable and <= 256 chars")
        self._signing_key = signing_key
        self._issuer = issuer

    def _tag(self, permit: WorkloadDispatchPermit) -> str:
        payload = (
            _PERMIT_AUTH_DOMAIN
            + self._issuer.encode("utf-8")
            + b"\0"
            + permit.permit_sha256.encode("ascii")
        )
        return hmac.new(self._signing_key, payload, hashlib.sha256).hexdigest()

    def seal(
        self,
        permit: WorkloadDispatchPermit,
    ) -> AuthenticatedWorkloadDispatchPermit:
        if not isinstance(permit, WorkloadDispatchPermit):
            raise TypeError("seal requires a WorkloadDispatchPermit")
        return AuthenticatedWorkloadDispatchPermit(
            permit=permit,
            issuer=self._issuer,
            authentication_sha256=self._tag(permit),
        )

    def open(
        self,
        authorization: AuthenticatedWorkloadDispatchPermit,
    ) -> WorkloadDispatchPermit:
        if not isinstance(authorization, AuthenticatedWorkloadDispatchPermit):
            raise TypeError(
                "dispatch requires an AuthenticatedWorkloadDispatchPermit"
            )
        expected = self._tag(authorization.permit)
        if authorization.issuer != self._issuer or not hmac.compare_digest(
            authorization.authentication_sha256,
            expected,
        ):
            raise UnauthenticatedWorkloadDispatchPermit(
                "workload-dispatch permit authentication failed"
            )
        return authorization.permit


class DispatchOutcomeUnknown(RuntimeError):
    """The effect may have happened; usage remains held for reconciliation."""

    def __init__(
        self,
        reference: WorkloadDispatchPermit | WorkloadDispatchIntentReference,
        detail: str,
        *,
        usage_unknown_recorded: bool,
        returned_receipt: WorkloadDispatchReceipt | None = None,
    ) -> None:
        recorded = "confirmed" if usage_unknown_recorded else "not confirmed"
        super().__init__(
            f"workload dispatch outcome is unknown for {reference.effect_id}: "
            f"{detail}; UsageUnknown {recorded}; reconcile through the "
            "idempotent effect port"
        )
        self.effect_id = reference.effect_id
        self.workload_sha256 = reference.workload_sha256
        self.intent_sha256 = reference.intent_sha256
        self.permit_sha256 = (
            reference.permit_sha256
            if isinstance(reference, WorkloadDispatchPermit)
            else None
        )
        self.usage_unknown_recorded = usage_unknown_recorded
        self.returned_receipt = returned_receipt


class ResourceJournalPort(Protocol):
    def load(self, scope: str) -> JournalSnapshot:
        ...

    def apply(
        self,
        scope: str,
        command: ResourceCommand,
        *,
        expected_revision: int | None = None,
    ) -> DurableDecision:
        ...


class ClockPort(Protocol):
    def now_utc(self) -> str:
        ...


class WorkloadEffectPort(Protocol):
    """Durable adapter for one effect kind.

    ``dispatch`` must atomically enforce the permit fence at the target and
    deduplicate ``(effect_id, workload_sha256, intent_sha256)`` across process
    restarts. ``lookup`` returns ``None`` only for authoritative absence; an
    uncertain lookup must raise instead.
    """

    adapter: str
    adapter_version: str

    def dispatch(self, permit: WorkloadDispatchPermit) -> WorkloadDispatchReceipt:
        ...

    def lookup(
        self,
        reference: WorkloadDispatchIntentReference,
    ) -> WorkloadDispatchReceipt | None:
        ...


class MeasuredWorkloadEffectPort(WorkloadEffectPort, Protocol):
    """Effect port that can exact-readback terminal resource measurement."""

    def lookup_usage(
        self,
        reference: WorkloadDispatchIntentReference,
    ) -> ResourceUsage | None:
        ...


def authority_from_snapshot(snapshot: JournalSnapshot) -> ResourceAuthority:
    if not isinstance(snapshot, JournalSnapshot):
        raise TypeError("snapshot must be a JournalSnapshot")
    if (
        snapshot.checkpoint.revision != snapshot.state.revision
        or snapshot.checkpoint.state_sha256 != snapshot.state.snapshot_sha256
        or snapshot.checkpoint.budget_id != snapshot.state.budget_id
        or snapshot.checkpoint.scope != snapshot.state.scope
        or snapshot.checkpoint.epoch != snapshot.state.epoch
    ):
        raise ValueError("journal snapshot checkpoint/state binding diverged")
    return ResourceAuthority(
        budget_id=snapshot.state.budget_id,
        scope=snapshot.state.scope,
        epoch=snapshot.state.epoch,
        revision=snapshot.state.revision,
        state_sha256=snapshot.state.snapshot_sha256,
        checkpoint_sha256=snapshot.checkpoint.checkpoint_sha256,
        journal_head_sha256=snapshot.checkpoint.journal_head_sha256,
        anchor_status=snapshot.anchor_status.value,
    )


def _effect_identity(effect: WorkloadEffectPort) -> tuple[str, str]:
    adapter = getattr(effect, "adapter", None)
    adapter_version = getattr(effect, "adapter_version", None)
    for label, value in (
        ("effect.adapter", adapter),
        ("effect.adapter_version", adapter_version),
    ):
        if (
            not isinstance(value, str)
            or not value
            or len(value) > 256
            or not value.isprintable()
        ):
            raise InvalidWorkloadDispatchIntent(
                f"{label} must be a printable non-empty string <= 256 chars"
            )
    return adapter, adapter_version


def _usage_unknown_command_id(
    reference: WorkloadDispatchPermit | WorkloadDispatchIntentReference,
    observed_at: str,
    detail: str,
) -> str:
    material = (
        f"{reference.scope}\0{reference.effect_id}\0{reference.intent_sha256}\0"
        f"{observed_at}\0{detail}"
    ).encode("utf-8")
    return f"usage-unknown:{hashlib.sha256(material).hexdigest()}"


def _settle_command_id(
    reference: WorkloadDispatchIntentReference,
    usage: ResourceUsage,
) -> str:
    material = (
        f"{reference.scope}\0{reference.effect_id}\0{reference.intent_sha256}\0"
        f"{usage.measurement_sha256}\0{usage.evidence_sha256}"
    ).encode("utf-8")
    return f"settle:{hashlib.sha256(material).hexdigest()}"


def _latest_utc(*values: str) -> str:
    """Select a lifecycle-safe UTC observation even if the system clock steps back."""

    return max(
        values,
        key=lambda value: datetime.fromisoformat(
            value.removesuffix("Z") + "+00:00"
        ),
    )


class ResourceExecutionGate:
    """Prepare, dispatch, and reconcile through injected journal/effect ports."""

    def __init__(
        self,
        *,
        scope: str,
        journal: ResourceJournalPort,
        effect: WorkloadEffectPort,
        clock: ClockPort,
        permit_authenticator: PermitAuthenticatorPort,
        settlement_effect: MeasuredWorkloadEffectPort | None = None,
        permit_ttl_seconds: int = DEFAULT_WORKLOAD_DISPATCH_PERMIT_TTL_SECONDS,
    ) -> None:
        if not isinstance(scope, str) or not scope or not scope.isprintable():
            raise ValueError("scope must be a printable non-empty string")
        if (
            isinstance(permit_ttl_seconds, bool)
            or not isinstance(permit_ttl_seconds, int)
            or not (
                1
                <= permit_ttl_seconds
                <= MAX_WORKLOAD_DISPATCH_PERMIT_TTL_SECONDS
            )
        ):
            raise ValueError(
                "permit_ttl_seconds must be an integer between 1 and "
                f"{MAX_WORKLOAD_DISPATCH_PERMIT_TTL_SECONDS}"
            )
        self._scope = scope
        self._journal = journal
        self._effect = effect
        if (
            settlement_effect is not None
            and _effect_identity(settlement_effect) != _effect_identity(effect)
        ):
            raise ValueError(
                "settlement effect identity must match the dispatch effect identity"
            )
        self._settlement_effect = settlement_effect
        self._clock = clock
        self._permit_authenticator = permit_authenticator
        self._permit_ttl_seconds = permit_ttl_seconds

    def prepare(
        self,
        start: StartGrant,
        *,
        expected_revision: int | None = None,
    ) -> AuthenticatedWorkloadDispatchPermit:
        """Persist and confirm the StartGrant intent, then mint from a fresh cut."""

        if not isinstance(start, StartGrant):
            raise TypeError("prepare requires a StartGrant")
        before = self._journal.load(self._scope)
        before_authority = authority_from_snapshot(before)
        require_current_confirmed_authority(before.state, before_authority)
        observed_at = self._clock.now_utc()
        expected_effect = validate_start_grant_preflight(
            before.state,
            start,
            observed_at=observed_at,
        )
        if _effect_identity(self._effect) != expected_effect:
            raise InvalidWorkloadDispatchIntent(
                "effect adapter identity diverges from the reserved estimate"
            )
        revision = (
            before.state.revision
            if expected_revision is None
            else expected_revision
        )
        durable = self._journal.apply(
            self._scope,
            start,
            expected_revision=revision,
        )
        if durable.decision.rejection is not None:
            raise durable.decision.rejection

        # Exact journal replay can return its historical snapshot. Always reload
        # the current confirmed head before minting new short-lived authority.
        current = self._journal.load(self._scope)
        authority = authority_from_snapshot(current)
        return self._permit_authenticator.seal(
            mint_workload_dispatch_permit(
                current.state,
                authority,
                effect_id=start.command_id,
                observed_at=observed_at,
                max_ttl_seconds=self._permit_ttl_seconds,
            )
        )

    def _persist_usage_unknown(
        self,
        reference: WorkloadDispatchPermit | WorkloadDispatchIntentReference,
        detail: str,
    ) -> bool:
        if self._confirmed_reconciliation_hold(reference):
            return True
        try:
            observed_at = self._clock.now_utc()
            command = UsageUnknown(
                command_id=_usage_unknown_command_id(reference, observed_at, detail),
                grant_id=reference.grant_id,
                fence_token=reference.fence_token,
                workload_sha256=reference.workload_sha256,
                observed_at=observed_at,
                reason=(
                    f"workload.dispatch outcome unknown: {detail}; "
                    f"intent={reference.intent_sha256}"
                ),
            )
            durable = self._journal.apply(self._scope, command)
        except Exception:
            return self._confirmed_reconciliation_hold(reference)
        if (
            durable.decision.accepted
            and durable.anchor_status.value == "CONFIRMED"
        ):
            return True
        return self._confirmed_reconciliation_hold(reference)

    def _confirmed_reconciliation_hold(
        self,
        reference: WorkloadDispatchPermit | WorkloadDispatchIntentReference,
    ) -> bool:
        try:
            snapshot = self._journal.load(self._scope)
            authority = authority_from_snapshot(snapshot)
            require_current_confirmed_authority(snapshot.state, authority)
            grant = snapshot.state.grant(reference.grant_id)
        except Exception:
            return False
        return (
            grant.status is GrantStatus.RECONCILIATION_REQUIRED
            and grant.fence_token == reference.fence_token
            and grant.workload_sha256 == reference.workload_sha256
        )

    def _raise_unknown(
        self,
        reference: WorkloadDispatchPermit | WorkloadDispatchIntentReference,
        detail: str,
        *,
        cause: Exception | None = None,
        returned_receipt: WorkloadDispatchReceipt | None = None,
    ) -> NoReturn:
        unknown = DispatchOutcomeUnknown(
            reference,
            detail,
            usage_unknown_recorded=self._persist_usage_unknown(reference, detail),
            returned_receipt=returned_receipt,
        )
        if cause is not None:
            raise unknown from cause
        raise unknown

    def dispatch(
        self,
        authorization: AuthenticatedWorkloadDispatchPermit,
    ) -> WorkloadDispatchReceipt:
        """Reload, revalidate, and immediately cross the idempotent effect port."""

        # OOPTDD_AUTHENTICATED_PERMIT_GUARD: only this gate's pinned issuer may
        # turn a pure permit claim into effect authority.
        permit = self._permit_authenticator.open(authorization)
        current = self._journal.load(self._scope)
        authority = authority_from_snapshot(current)
        observed_at = self._clock.now_utc()
        # OOPTDD_REVALIDATE_IMMEDIATELY_BEFORE_EFFECT_GUARD: this is the final
        # authority decision before crossing the injected physical-effect port.
        validated = revalidate_workload_dispatch_permit(
            current.state,
            authority,
            permit,
            observed_at=observed_at,
        )
        if _effect_identity(self._effect) != (
            validated.adapter,
            validated.adapter_version,
        ):
            raise InvalidWorkloadDispatchIntent(
                "effect adapter identity diverges from the dispatch intent"
            )
        try:
            receipt = self._effect.dispatch(validated)
        except Exception as exc:
            self._raise_unknown(
                validated,
                f"effect port raised {type(exc).__name__}",
                cause=exc,
            )
        if not isinstance(receipt, WorkloadDispatchReceipt):
            self._raise_unknown(
                validated,
                "effect port returned no typed receipt",
            )
        try:
            return validate_workload_dispatch_receipt(
                validated.intent_reference,
                receipt,
            )
        except (TypeError, InvalidWorkloadDispatchIntent) as exc:
            self._raise_unknown(
                validated,
                "effect receipt binding diverged",
                cause=exc,
                returned_receipt=receipt,
            )

    def recoverable_effect_ids(self) -> tuple[str, ...]:
        """Discover unresolved stable intents from a fresh confirmed journal cut."""

        current = self._journal.load(self._scope)
        authority = authority_from_snapshot(current)
        require_current_confirmed_authority(current.state, authority)
        return recoverable_workload_dispatch_effect_ids(current.state)

    def reconcile(
        self,
        effect_id: str,
    ) -> WorkloadDispatchReceipt | None:
        """Rebuild intent from the journal and look it up without redispatch."""
        current = self._journal.load(self._scope)
        authority = authority_from_snapshot(current)
        require_current_confirmed_authority(current.state, authority)
        reference = derive_workload_dispatch_intent_reference(
            current.state,
            effect_id=effect_id,
        )
        validate_workload_dispatch_intent_reference(current.state, reference)
        if _effect_identity(self._effect) != (
            reference.adapter,
            reference.adapter_version,
        ):
            raise InvalidWorkloadDispatchIntent(
                "effect adapter identity diverges from the dispatch intent"
            )
        try:
            receipt = self._effect.lookup(reference)
        except Exception as exc:
            self._raise_unknown(
                reference,
                f"effect lookup raised {type(exc).__name__}",
                cause=exc,
            )
        if receipt is None:
            return None
        if not isinstance(receipt, WorkloadDispatchReceipt):
            self._raise_unknown(
                reference,
                "effect lookup returned no typed receipt",
            )
        try:
            return validate_workload_dispatch_receipt(reference, receipt)
        except (TypeError, InvalidWorkloadDispatchIntent) as exc:
            self._raise_unknown(
                reference,
                "effect lookup receipt binding diverged",
                cause=exc,
                returned_receipt=receipt,
            )

    def settle(self, effect_id: str) -> DurableDecision:
        """Exact-read terminal receipt/usage and durably settle the open grant.

        Settlement never revives a permit and never redispatches.  It is valid only
        while the persisted StartGrant remains unresolved; callers recovering an
        already terminal grant must exact-read its retained settlement receipt.
        """

        current = self._journal.load(self._scope)
        authority = authority_from_snapshot(current)
        require_current_confirmed_authority(current.state, authority)
        reference = derive_workload_dispatch_intent_reference(
            current.state,
            effect_id=effect_id,
        )
        validate_workload_dispatch_intent_reference(current.state, reference)
        if _effect_identity(self._effect) != (
            reference.adapter,
            reference.adapter_version,
        ):
            raise InvalidWorkloadDispatchIntent(
                "effect adapter identity diverges from the settlement intent"
            )
        settlement_effect = self._settlement_effect
        if settlement_effect is None:
            raise InvalidWorkloadDispatchIntent(
                "no measured settlement effect was injected into this gate"
            )
        if _effect_identity(settlement_effect) != (
            reference.adapter,
            reference.adapter_version,
        ):
            raise InvalidWorkloadDispatchIntent(
                "settlement effect identity diverges from the settlement intent"
            )
        try:
            receipt = settlement_effect.lookup(reference)
            usage = settlement_effect.lookup_usage(reference)
        except Exception as exc:
            self._raise_unknown(
                reference,
                f"effect settlement lookup raised {type(exc).__name__}",
                cause=exc,
            )
        if receipt is None or usage is None:
            self._raise_unknown(
                reference,
                "effect has no complete terminal receipt and usage",
            )
        if not isinstance(receipt, WorkloadDispatchReceipt):
            self._raise_unknown(
                reference,
                "effect settlement returned no typed receipt",
            )
        if not isinstance(usage, ResourceUsage):
            self._raise_unknown(
                reference,
                "effect settlement returned no typed usage",
            )
        try:
            validate_workload_dispatch_receipt(reference, receipt)
        except (TypeError, InvalidWorkloadDispatchIntent) as exc:
            self._raise_unknown(
                reference,
                "effect settlement receipt binding diverged",
                cause=exc,
                returned_receipt=receipt,
            )
        if usage.evidence_sha256 != receipt.evidence_sha256:
            self._raise_unknown(
                reference,
                "effect usage evidence diverges from the dispatch receipt",
                returned_receipt=receipt,
            )
        command = SettleGrant(
            command_id=_settle_command_id(reference, usage),
            grant_id=reference.grant_id,
            fence_token=reference.fence_token,
            workload_sha256=reference.workload_sha256,
            observed_at=_latest_utc(
                self._clock.now_utc(),
                current.state.grant(reference.grant_id).last_observed_at,
                usage.measured_at,
            ),
            usage=usage,
        )
        durable = self._journal.apply(
            self._scope,
            command,
            expected_revision=current.state.revision,
        )
        if durable.decision.rejection is not None:
            raise durable.decision.rejection
        return durable


__all__ = [
    "AuthenticatedWorkloadDispatchPermit",
    "ClockPort",
    "DispatchOutcomeUnknown",
    "HMACPermitAuthenticator",
    "MeasuredWorkloadEffectPort",
    "PermitAuthenticatorPort",
    "ResourceExecutionGate",
    "ResourceJournalPort",
    "WorkloadEffectPort",
    "UnauthenticatedWorkloadDispatchPermit",
    "authority_from_snapshot",
]
