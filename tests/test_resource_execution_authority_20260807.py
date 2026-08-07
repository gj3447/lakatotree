"""RED-first guards for durable, operation-specific resource execution authority."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from lakatos.io.resource_execution import (
    AuthenticatedWorkloadDispatchPermit,
    DispatchOutcomeUnknown,
    HMACPermitAuthenticator,
    ResourceExecutionGate,
    UnauthenticatedWorkloadDispatchPermit,
)
from lakatos.io.resource_journal import (
    AnchorStatus,
    SQLiteResourceJournal,
    SignedAppendOnlyFileAnchor,
)
from lakatos.resource_coordination import (
    CancelGrant,
    GrantStatus,
    IdempotencyConflict,
    RequestGrant,
    ResourceEstimate,
    ResourceState,
    ResourceVector,
    StartGrant,
)
from lakatos.resource_execution import (
    ExpiredWorkloadDispatchPermit,
    InvalidWorkloadDispatchIntent,
    ResourceAuthority,
    StaleWorkloadDispatchPermit,
    UnconfirmedResourceAuthority,
    WorkloadDispatchIntentReference,
    WorkloadDispatchPermit,
    WorkloadDispatchReceipt,
    mint_workload_dispatch_permit,
    revalidate_workload_dispatch_permit,
)


SCOPE = "tree:resource-execution"
NOW = "2026-08-07T11:02:00Z"
PERMIT_SIGNING_KEY = bytes(range(32))
PERMIT_ISSUER = "test:resource-execution-gate"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _state() -> ResourceState:
    return ResourceState.create(
        budget_id="budget:resource-execution",
        scope=SCOPE,
        epoch=1,
        hard_caps=ResourceVector(100, 200, 40),
    )


def _request(
    *,
    command_id: str = "request:effect-1",
    grant_id: str = "grant:effect-1",
    wall: int = 10,
    workload_sha256: str | None = None,
) -> RequestGrant:
    workload = workload_sha256 or _sha("workload:effect-1")
    return RequestGrant(
        command_id=command_id,
        grant_id=grant_id,
        fence_token=7,
        observed_at="2026-08-07T11:00:00Z",
        expires_at="2026-08-07T12:00:00Z",
        estimate=ResourceEstimate(
            work_id=f"work:{grant_id}",
            attempt_id=f"attempt:{grant_id}",
            workload_sha256=workload,
            adapter="resource-execution-test",
            adapter_version="1",
            upper_bound=ResourceVector(wall, 20, 5),
            valid_until="2026-08-07T12:00:00Z",
        ),
    )


def _start(
    *,
    command_id: str = "effect:effect-1",
    grant_id: str = "grant:effect-1",
    workload_sha256: str | None = None,
) -> StartGrant:
    return StartGrant(
        command_id=command_id,
        grant_id=grant_id,
        fence_token=7,
        workload_sha256=workload_sha256 or _sha("workload:effect-1"),
        observed_at="2026-08-07T11:01:00Z",
    )


class _Clock:
    def __init__(self, now: str = NOW) -> None:
        self.now = now

    def now_utc(self) -> str:
        return self.now


class _SequenceClock:
    def __init__(self, *values: str) -> None:
        self._values = iter(values)
        self.calls = 0

    def now_utc(self) -> str:
        self.calls += 1
        return next(self._values)


class _IdempotentEffect:
    """Reference fake: physical calls are deduplicated by effect/workload identity."""

    adapter = "resource-execution-test"
    adapter_version = "1"

    def __init__(self) -> None:
        self.physical_calls = 0
        self._receipts: dict[str, tuple[str, WorkloadDispatchReceipt]] = {}

    def dispatch(self, permit: WorkloadDispatchPermit) -> WorkloadDispatchReceipt:
        prior = self._receipts.get(permit.effect_id)
        if prior is not None:
            workload_sha256, receipt = prior
            if workload_sha256 != permit.workload_sha256:
                raise IdempotencyConflict(permit.effect_id)
            return receipt
        self.physical_calls += 1
        receipt = WorkloadDispatchReceipt(
            operation=permit.operation,
            effect_id=permit.effect_id,
            workload_sha256=permit.workload_sha256,
            fence_token=permit.fence_token,
            intent_sha256=permit.intent_sha256,
            completed_at="2026-08-07T11:03:00Z",
            evidence_sha256=_sha(f"effect:{permit.effect_id}:{permit.workload_sha256}"),
        )
        self._receipts[permit.effect_id] = (permit.workload_sha256, receipt)
        return receipt

    def lookup(
        self,
        permit: WorkloadDispatchIntentReference,
    ) -> WorkloadDispatchReceipt | None:
        prior = self._receipts.get(permit.effect_id)
        if prior is None:
            return None
        workload_sha256, receipt = prior
        if workload_sha256 != permit.workload_sha256:
            raise IdempotencyConflict(permit.effect_id)
        return receipt


class _MismatchedEffect:
    adapter = "resource-execution-test"
    adapter_version = "1"

    def dispatch(self, permit: WorkloadDispatchPermit) -> WorkloadDispatchReceipt:
        return WorkloadDispatchReceipt(
            operation=permit.operation,
            effect_id=permit.effect_id,
            workload_sha256=_sha("wrong-workload"),
            fence_token=permit.fence_token,
            intent_sha256=permit.intent_sha256,
            completed_at="2026-08-07T11:03:00Z",
            evidence_sha256=_sha("mismatched-effect"),
        )

    def lookup(
        self,
        permit: WorkloadDispatchIntentReference,
    ) -> WorkloadDispatchReceipt | None:
        return None


class _WrongAdapterEffect(_IdempotentEffect):
    adapter = "wrong-adapter"


class _UncertainLookupEffect(_IdempotentEffect):
    def lookup(
        self,
        permit: WorkloadDispatchIntentReference,
    ) -> WorkloadDispatchReceipt | None:
        raise ConnectionError(f"lookup outcome unknown for {permit.effect_id}")


class _CancelAfterAuthorizationEffect(_IdempotentEffect):
    def __init__(self, journal: SQLiteResourceJournal) -> None:
        super().__init__()
        self._journal = journal

    def dispatch(self, permit: WorkloadDispatchPermit) -> WorkloadDispatchReceipt:
        cancelled = self._journal.apply(
            SCOPE,
            CancelGrant(
                command_id="cancel:after-authorization",
                grant_id=permit.grant_id,
                fence_token=permit.fence_token,
                workload_sha256=permit.workload_sha256,
                observed_at="2026-08-07T11:02:01Z",
                reason="committed after dispatch authorization point",
            ),
        )
        assert cancelled.decision.accepted
        return super().dispatch(permit)


class _TransactionalCrashAfterEffect:
    """The target row is both the physical effect and its durable receipt."""

    adapter = "resource-execution-test"
    adapter_version = "1"

    def __init__(self, target_path: Path, *, crash_after_commit: bool) -> None:
        self._target_path = target_path
        self._crash_after_commit = crash_after_commit
        self.physical_calls = 0
        connection = sqlite3.connect(self._target_path)
        try:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS workload_effects ("
                "effect_id TEXT PRIMARY KEY, workload_sha256 TEXT NOT NULL, "
                "intent_sha256 TEXT NOT NULL UNIQUE, receipt_json TEXT NOT NULL)"
            )
            connection.commit()
        finally:
            connection.close()

    def lookup(
        self,
        permit: WorkloadDispatchIntentReference,
    ) -> WorkloadDispatchReceipt | None:
        connection = sqlite3.connect(self._target_path)
        try:
            row = connection.execute(
                "SELECT workload_sha256, intent_sha256, receipt_json "
                "FROM workload_effects WHERE effect_id = ?",
                (permit.effect_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        workload_sha256, intent_sha256, receipt_json = row
        if (
            workload_sha256 != permit.workload_sha256
            or intent_sha256 != permit.intent_sha256
        ):
            raise IdempotencyConflict(permit.effect_id)
        return WorkloadDispatchReceipt(**json.loads(receipt_json))

    def dispatch(self, permit: WorkloadDispatchPermit) -> WorkloadDispatchReceipt:
        receipt = WorkloadDispatchReceipt(
            operation=permit.operation,
            effect_id=permit.effect_id,
            workload_sha256=permit.workload_sha256,
            fence_token=permit.fence_token,
            intent_sha256=permit.intent_sha256,
            completed_at="2026-08-07T11:03:00Z",
            evidence_sha256=_sha(f"durable-effect:{permit.intent_sha256}"),
        )
        connection = sqlite3.connect(self._target_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT workload_sha256, intent_sha256, receipt_json "
                "FROM workload_effects WHERE effect_id = ?",
                (permit.effect_id,),
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO workload_effects "
                    "(effect_id, workload_sha256, intent_sha256, receipt_json) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        permit.effect_id,
                        permit.workload_sha256,
                        permit.intent_sha256,
                        json.dumps(receipt.to_dict(), sort_keys=True),
                    ),
                )
                connection.commit()
                self.physical_calls += 1
                result = receipt
            else:
                connection.commit()
                workload_sha256, intent_sha256, receipt_json = row
                if (
                    workload_sha256 != permit.workload_sha256
                    or intent_sha256 != permit.intent_sha256
                ):
                    raise IdempotencyConflict(permit.effect_id)
                result = WorkloadDispatchReceipt(**json.loads(receipt_json))
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
        if self._crash_after_commit:
            self._crash_after_commit = False
            raise ConnectionError("response lost after durable effect")
        return result


def _journal(tmp_path: Path, *, anchored: bool = True) -> SQLiteResourceJournal:
    anchor = (
        SignedAppendOnlyFileAnchor(
            tmp_path / "trusted-anchor",
            signing_key=bytes(range(32)),
        )
        if anchored
        else None
    )
    journal = SQLiteResourceJournal(
        tmp_path / "resource.sqlite3",
        trusted_anchor=anchor,
    )
    initialized = journal.initialize(_state())
    assert initialized.anchor_status is (
        AnchorStatus.CONFIRMED if anchored else AnchorStatus.PENDING
    )
    return journal


def _reserved(journal: SQLiteResourceJournal) -> None:
    result = journal.apply(SCOPE, _request())
    assert result.decision.accepted and result.anchor_status is AnchorStatus.CONFIRMED


def _gate(
    journal: SQLiteResourceJournal,
    effect,
    clock=None,
) -> ResourceExecutionGate:
    return ResourceExecutionGate(
        scope=SCOPE,
        journal=journal,
        effect=effect,
        clock=clock or _Clock(),
        permit_authenticator=HMACPermitAuthenticator(
            signing_key=PERMIT_SIGNING_KEY,
            issuer=PERMIT_ISSUER,
        ),
    )


def _authority(snapshot) -> ResourceAuthority:
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


def test_guard_mechanism_confirmed_start_is_intent_and_exact_permit_dispatches(tmp_path):
    journal = _journal(tmp_path)
    _reserved(journal)
    effect = _IdempotentEffect()
    gate = _gate(journal, effect)

    authorization = gate.prepare(_start())
    permit = authorization.permit
    snapshot = journal.load(SCOPE)

    assert snapshot.anchor_status is AnchorStatus.CONFIRMED
    assert snapshot.checkpoint.command_id == permit.effect_id == _start().command_id
    assert snapshot.state.command_records[-1].transition.command == _start()
    assert permit.authority_revision == snapshot.state.revision == 2
    assert permit.authority_state_sha256 == snapshot.state.snapshot_sha256
    assert permit.authority_checkpoint_sha256 == snapshot.checkpoint.checkpoint_sha256
    assert permit.authority_journal_head_sha256 == snapshot.checkpoint.journal_head_sha256
    assert permit.grant_id == _start().grant_id
    assert permit.fence_token == _start().fence_token
    assert permit.workload_sha256 == _start().workload_sha256
    assert permit.adapter == effect.adapter
    assert permit.adapter_version == effect.adapter_version
    assert permit.expires_at == "2026-08-07T11:02:30Z"

    receipt = gate.dispatch(authorization)
    assert receipt.effect_id == permit.effect_id
    assert receipt.workload_sha256 == permit.workload_sha256
    assert effect.physical_calls == 1


def test_forged_permit_envelope_is_rejected_before_effect(tmp_path):
    journal = _journal(tmp_path)
    _reserved(journal)
    effect = _IdempotentEffect()
    gate = _gate(journal, effect)
    valid = gate.prepare(_start())
    forged = AuthenticatedWorkloadDispatchPermit(
        permit=valid.permit,
        issuer=valid.issuer,
        authentication_sha256="0" * 64,
    )

    with pytest.raises(UnauthenticatedWorkloadDispatchPermit):
        gate.dispatch(forged)

    assert effect.physical_calls == 0


def test_prepare_uses_one_logical_clock_observation_across_durable_commit(tmp_path):
    journal = _journal(tmp_path)
    _reserved(journal)
    clock = _SequenceClock(NOW, "2026-08-07T12:00:00Z")

    authorization = _gate(journal, _IdempotentEffect(), clock).prepare(_start())

    assert clock.calls == 1
    assert authorization.permit.issued_at == NOW


def test_guard_defect_unconfirmed_authority_cannot_persist_start_or_dispatch(tmp_path):
    journal = _journal(tmp_path, anchored=False)
    effect = _IdempotentEffect()

    with pytest.raises(UnconfirmedResourceAuthority):
        _gate(journal, effect).prepare(_start())

    snapshot = journal.load(SCOPE)
    assert snapshot.state.revision == 0
    assert snapshot.state.grants == ()
    assert effect.physical_calls == 0


def test_guard_defect_head_movement_stales_permit_before_effect(tmp_path):
    journal = _journal(tmp_path)
    _reserved(journal)
    effect = _IdempotentEffect()
    gate = _gate(journal, effect)
    authorization = gate.prepare(_start())
    permit = authorization.permit

    rejected = journal.apply(
        SCOPE,
        _request(command_id="request:rejected", grant_id="grant:rejected", wall=101),
    )
    assert not rejected.decision.accepted
    assert rejected.anchor_status is AnchorStatus.CONFIRMED

    with pytest.raises(StaleWorkloadDispatchPermit):
        gate.dispatch(authorization)
    assert effect.physical_calls == 0


def test_guard_defect_cancel_after_mint_stales_permit_before_effect(tmp_path):
    journal = _journal(tmp_path)
    _reserved(journal)
    effect = _IdempotentEffect()
    gate = _gate(journal, effect)
    authorization = gate.prepare(_start())
    permit = authorization.permit
    journal.apply(
        SCOPE,
        CancelGrant(
            command_id="cancel:effect-1",
            grant_id=permit.grant_id,
            fence_token=permit.fence_token,
            workload_sha256=permit.workload_sha256,
            observed_at="2026-08-07T11:03:00Z",
            reason="operator cancellation",
        ),
    )

    with pytest.raises(StaleWorkloadDispatchPermit):
        gate.dispatch(authorization)
    assert effect.physical_calls == 0


def test_cancel_committed_after_authorization_is_a_later_pending_stop_event(tmp_path):
    journal = _journal(tmp_path)
    _reserved(journal)
    effect = _CancelAfterAuthorizationEffect(journal)
    gate = _gate(journal, effect)
    authorization = gate.prepare(_start())

    receipt = gate.dispatch(authorization)

    assert receipt.effect_id == authorization.permit.effect_id
    assert effect.physical_calls == 1
    assert (
        journal.load(SCOPE).state.grant(authorization.permit.grant_id).status
        is GrantStatus.CANCEL_PENDING
    )


def test_guard_defect_expired_permit_is_rejected_at_dispatch_boundary(tmp_path):
    journal = _journal(tmp_path)
    _reserved(journal)
    effect = _IdempotentEffect()
    clock = _Clock()
    gate = _gate(journal, effect, clock)
    authorization = gate.prepare(_start())
    permit = authorization.permit
    clock.now = "2026-08-07T12:00:00Z"

    with pytest.raises(ExpiredWorkloadDispatchPermit):
        gate.dispatch(authorization)
    assert effect.physical_calls == 0


def test_expired_grant_is_rejected_before_start_intent_is_persisted(tmp_path):
    journal = _journal(tmp_path)
    _reserved(journal)
    clock = _Clock("2026-08-07T12:00:00Z")

    with pytest.raises(ExpiredWorkloadDispatchPermit):
        _gate(journal, _IdempotentEffect(), clock).prepare(_start())

    snapshot = journal.load(SCOPE)
    assert snapshot.state.revision == 1
    assert snapshot.state.grant(_start().grant_id).status is GrantStatus.RESERVED


def test_adapter_mismatch_is_rejected_before_start_intent_is_persisted(tmp_path):
    journal = _journal(tmp_path)
    _reserved(journal)

    with pytest.raises(InvalidWorkloadDispatchIntent, match="adapter identity"):
        _gate(journal, _WrongAdapterEffect()).prepare(_start())

    snapshot = journal.load(SCOPE)
    assert snapshot.state.revision == 1
    assert snapshot.state.grant(_start().grant_id).status is GrantStatus.RESERVED


def test_exact_start_retry_remints_current_permit_and_effect_port_deduplicates(tmp_path):
    journal = _journal(tmp_path)
    _reserved(journal)
    effect = _IdempotentEffect()
    gate = _gate(journal, effect)

    first = gate.prepare(_start())
    first_receipt = gate.dispatch(first)
    replay = gate.prepare(_start())
    replay_receipt = gate.dispatch(replay)

    assert replay == first
    assert replay_receipt == first_receipt
    assert effect.physical_calls == 1
    assert journal.load(SCOPE).state.revision == 2


def test_head_advance_remints_new_permit_but_stable_receipt_still_replays(tmp_path):
    journal = _journal(tmp_path)
    _reserved(journal)
    effect = _IdempotentEffect()
    clock = _Clock()
    gate = _gate(journal, effect, clock)

    first_authorization = gate.prepare(_start())
    first = first_authorization.permit
    first_receipt = gate.dispatch(first_authorization)
    journal.apply(
        SCOPE,
        _request(command_id="request:rejected", grant_id="grant:rejected", wall=101),
    )
    clock.now = "2026-08-07T11:04:00Z"
    reminted_authorization = gate.prepare(_start())
    reminted = reminted_authorization.permit
    replay_receipt = gate.dispatch(reminted_authorization)

    assert reminted != first
    assert reminted.authority_revision > first.authority_revision
    assert reminted.intent_sha256 == first.intent_sha256
    assert reminted.permit_sha256 != first.permit_sha256
    assert replay_receipt == first_receipt
    assert effect.physical_calls == 1


def test_same_start_effect_id_with_changed_workload_conflicts_before_effect(tmp_path):
    journal = _journal(tmp_path)
    _reserved(journal)
    effect = _IdempotentEffect()
    gate = _gate(journal, effect)
    gate.prepare(_start())

    with pytest.raises(IdempotencyConflict):
        gate.prepare(_start(workload_sha256=_sha("changed-workload")))
    assert effect.physical_calls == 0
    assert journal.load(SCOPE).state.revision == 2


def test_effect_receipt_binding_mismatch_is_outcome_unknown(tmp_path):
    journal = _journal(tmp_path)
    _reserved(journal)
    gate = _gate(journal, _MismatchedEffect())
    authorization = gate.prepare(_start())
    permit = authorization.permit

    with pytest.raises(DispatchOutcomeUnknown, match="receipt") as caught:
        gate.dispatch(authorization)

    assert caught.value.usage_unknown_recorded
    assert caught.value.returned_receipt is not None
    snapshot = journal.load(SCOPE)
    assert (
        snapshot.state.grant(permit.grant_id).status
        is GrantStatus.RECONCILIATION_REQUIRED
    )


def test_response_loss_records_unknown_and_restart_reconciles_durable_receipt(tmp_path):
    journal = _journal(tmp_path)
    _reserved(journal)
    target_path = tmp_path / "effect-target.sqlite3"
    first_effect = _TransactionalCrashAfterEffect(
        target_path,
        crash_after_commit=True,
    )
    authorization = _gate(journal, first_effect).prepare(_start())
    permit = authorization.permit

    with pytest.raises(DispatchOutcomeUnknown) as caught:
        _gate(journal, first_effect).dispatch(authorization)

    assert caught.value.usage_unknown_recorded
    assert first_effect.physical_calls == 1
    assert (
        journal.load(SCOPE).state.grant(permit.grant_id).status
        is GrantStatus.RECONCILIATION_REQUIRED
    )

    restarted_effect = _TransactionalCrashAfterEffect(
        target_path,
        crash_after_commit=False,
    )
    restarted_gate = _gate(journal, restarted_effect)
    assert restarted_gate.recoverable_effect_ids() == (permit.effect_id,)
    recovered = restarted_gate.reconcile(permit.effect_id)

    assert recovered is not None
    assert recovered.intent_sha256 == permit.intent_sha256
    assert restarted_effect.physical_calls == 0


def test_uncertain_restart_lookup_records_unknown_without_reviving_permit(tmp_path):
    journal = _journal(tmp_path)
    _reserved(journal)
    authorization = _gate(journal, _IdempotentEffect()).prepare(_start())
    reference_only_gate = _gate(journal, _UncertainLookupEffect())

    with pytest.raises(DispatchOutcomeUnknown) as caught:
        reference_only_gate.reconcile(authorization.permit.effect_id)

    assert caught.value.permit_sha256 is None
    assert caught.value.usage_unknown_recorded
    assert (
        journal.load(SCOPE).state.grant(authorization.permit.grant_id).status
        is GrantStatus.RECONCILIATION_REQUIRED
    )


def test_fresh_process_discovers_and_reconciles_without_ephemeral_permit(tmp_path):
    journal = _journal(tmp_path)
    _reserved(journal)
    target_path = tmp_path / "process-effect-target.sqlite3"
    effect = _TransactionalCrashAfterEffect(
        target_path,
        crash_after_commit=True,
    )
    authorization = _gate(journal, effect).prepare(_start())
    expected_intent = authorization.permit.intent_sha256
    with pytest.raises(DispatchOutcomeUnknown):
        _gate(journal, effect).dispatch(authorization)

    probe = r'''import json
from pathlib import Path
import sqlite3
import sys

from lakatos.io.resource_execution import HMACPermitAuthenticator, ResourceExecutionGate
from lakatos.io.resource_journal import SQLiteResourceJournal, SignedAppendOnlyFileAnchor
from lakatos.resource_execution import WorkloadDispatchReceipt

class Clock:
    def now_utc(self):
        return "2026-08-07T13:00:00Z"

class Effect:
    adapter = "resource-execution-test"
    adapter_version = "1"
    def __init__(self, path):
        self.path = path
    def dispatch(self, permit):
        raise AssertionError("reconcile must never redispatch")
    def lookup(self, reference):
        connection = sqlite3.connect(self.path)
        try:
            row = connection.execute(
                "SELECT workload_sha256, intent_sha256, receipt_json "
                "FROM workload_effects WHERE effect_id = ?",
                (reference.effect_id,),
            ).fetchone()
        finally:
            connection.close()
        assert row is not None
        assert row[0] == reference.workload_sha256
        assert row[1] == reference.intent_sha256
        return WorkloadDispatchReceipt(**json.loads(row[2]))

root = Path(sys.argv[1])
journal = SQLiteResourceJournal(
    root / "resource.sqlite3",
    trusted_anchor=SignedAppendOnlyFileAnchor(
        root / "trusted-anchor",
        signing_key=bytes(range(32)),
    ),
)
gate = ResourceExecutionGate(
    scope="tree:resource-execution",
    journal=journal,
    effect=Effect(root / "process-effect-target.sqlite3"),
    clock=Clock(),
    permit_authenticator=HMACPermitAuthenticator(
        signing_key=bytes(range(32)),
        issuer="fresh-process",
    ),
)
effect_ids = gate.recoverable_effect_ids()
assert effect_ids == ("effect:effect-1",)
receipt = gate.reconcile(effect_ids[0])
assert receipt is not None
print(receipt.intent_sha256)
'''
    completed = subprocess.run(
        [sys.executable, "-c", probe, str(tmp_path)],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == expected_intent


def test_pure_permit_functions_are_deterministic_frozen_and_alias_free(tmp_path):
    journal = _journal(tmp_path)
    _reserved(journal)
    journal.apply(SCOPE, _start())
    snapshot = journal.load(SCOPE)
    authority = _authority(snapshot)

    left = mint_workload_dispatch_permit(
        snapshot.state,
        authority,
        effect_id=_start().command_id,
        observed_at=NOW,
    )
    right = mint_workload_dispatch_permit(
        snapshot.state,
        authority,
        effect_id=_start().command_id,
        observed_at=NOW,
    )
    assert left == right
    assert revalidate_workload_dispatch_permit(
        snapshot.state,
        authority,
        left,
        observed_at=NOW,
    ) == left
    with pytest.raises(FrozenInstanceError):
        left.effect_id = "mutated"
    assert not any(isinstance(value, (dict, list, set)) for value in left.to_dict().values())
