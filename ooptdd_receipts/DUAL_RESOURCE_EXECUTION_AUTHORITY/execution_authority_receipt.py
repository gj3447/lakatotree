"""Hermetic OOPTDD receipt for operation-specific resource execution authority."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lakatos.io.resource_execution import (  # noqa: E402
    DispatchOutcomeUnknown,
    HMACPermitAuthenticator,
    ResourceExecutionGate,
)
from lakatos.io.resource_journal import (  # noqa: E402
    AnchorStatus,
    SQLiteResourceJournal,
    SignedAppendOnlyFileAnchor,
)
from lakatos.resource_coordination import (  # noqa: E402
    GrantStatus,
    RequestGrant,
    ResourceEstimate,
    ResourceState,
    ResourceVector,
    StartGrant,
)
from lakatos.resource_execution import (  # noqa: E402
    StaleWorkloadDispatchPermit,
    WorkloadDispatchReceipt,
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(f"resource execution authority receipt red: {message}")


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _event(cid: str, name: str) -> dict:
    return {
        "cid": cid,
        "correlation_id": cid,
        "cycle_id": cid,
        "service": "lakatotree.resource_execution",
        "event": name,
    }


class _Clock:
    def __init__(self, now: str = "2026-08-07T11:02:00Z") -> None:
        self.now = now

    def now_utc(self) -> str:
        return self.now


class _TransactionalTargetEffect:
    adapter = "ooptdd-resource-execution"
    adapter_version = "1"

    def __init__(self, target_stem: Path, *, crash_after_commit: bool = False) -> None:
        self._target_path = target_stem.with_suffix(".target.sqlite3")
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

    def lookup(self, permit):
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
            raise RuntimeError("effect id was replayed with changed stable intent")
        return WorkloadDispatchReceipt(**json.loads(receipt_json))

    def dispatch(self, permit):
        receipt = WorkloadDispatchReceipt(
            operation=permit.operation,
            effect_id=permit.effect_id,
            workload_sha256=permit.workload_sha256,
            fence_token=permit.fence_token,
            intent_sha256=permit.intent_sha256,
            completed_at="2026-08-07T11:03:00Z",
            evidence_sha256=_sha(f"receipt:{permit.effect_id}"),
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
                    raise RuntimeError("effect id was replayed with changed intent")
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


def _permit_authenticator() -> HMACPermitAuthenticator:
    return HMACPermitAuthenticator(
        signing_key=bytes(range(32)),
        issuer="ooptdd:resource-execution",
    )


def _state(scope: str) -> ResourceState:
    return ResourceState.create(
        budget_id=f"budget:{scope}",
        scope=scope,
        epoch=1,
        hard_caps=ResourceVector(100, 200, 40),
    )


def _request(
    scope: str,
    *,
    command_id: str = "request:effect",
    grant_id: str = "grant:effect",
    wall: int = 10,
) -> RequestGrant:
    return RequestGrant(
        command_id=command_id,
        grant_id=grant_id,
        fence_token=7,
        observed_at="2026-08-07T11:00:00Z",
        expires_at="2026-08-07T12:00:00Z",
        estimate=ResourceEstimate(
            work_id=f"work:{grant_id}",
            attempt_id=f"attempt:{grant_id}",
            workload_sha256=_sha(f"workload:{scope}"),
            adapter="ooptdd-resource-execution",
            adapter_version="1",
            upper_bound=ResourceVector(wall, 20, 5),
            valid_until="2026-08-07T12:00:00Z",
        ),
    )


def _start(scope: str) -> StartGrant:
    return StartGrant(
        command_id="effect:effect",
        grant_id="grant:effect",
        fence_token=7,
        workload_sha256=_sha(f"workload:{scope}"),
        observed_at="2026-08-07T11:01:00Z",
    )


def _run_isolated_execution_mutant(
    *,
    mutant_source: str,
    probe: str,
    prefix: str,
) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix=prefix) as raw:
        root = Path(raw)
        package = root / "lakatos"
        io_package = package / "io"
        io_package.mkdir(parents=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
        (io_package / "__init__.py").write_text("", encoding="utf-8")
        for name in (
            "resource_coordination.py",
            "resource_kernel.py",
            "resource_execution.py",
            "write_cert.py",
        ):
            (package / name).write_bytes((ROOT / "lakatos" / name).read_bytes())
        for name in (
            "_resource_journal_contracts.py",
            "_resource_journal_codec.py",
            "_resource_anchor.py",
            "resource_journal.py",
        ):
            source_path = ROOT / "lakatos" / "io" / name
            (io_package / name).write_bytes(source_path.read_bytes())
        (io_package / "resource_execution.py").write_text(
            mutant_source,
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment["PYTHONPATH"] = raw
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(
            [sys.executable, "-c", probe],
            cwd=raw,
            env=environment,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )


_REVALIDATION_MARKER = '''        # OOPTDD_REVALIDATE_IMMEDIATELY_BEFORE_EFFECT_GUARD: this is the final
        # authority decision before crossing the injected physical-effect port.
        validated = revalidate_workload_dispatch_permit(
            current.state,
            authority,
            permit,
            observed_at=observed_at,
        )
'''

_AUTHENTICATION_MARKER = '''        # OOPTDD_AUTHENTICATED_PERMIT_GUARD: only this gate's pinned issuer may
        # turn a pure permit claim into effect authority.
        permit = self._permit_authenticator.open(authorization)
'''


def _immediate_revalidation_mutant_must_red() -> None:
    source_path = ROOT / "lakatos" / "io" / "resource_execution.py"
    source = source_path.read_text(encoding="utf-8")
    if source.count(_REVALIDATION_MARKER) != 1:
        raise RuntimeError("execution revalidation mutation marker is not unique")
    mutant = source.replace(_REVALIDATION_MARKER, "        validated = permit\n", 1)
    canonical_sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()
    _require(
        hashlib.sha256(mutant.encode("utf-8")).hexdigest() != canonical_sha256,
        "execution revalidation mutant did not change source",
    )

    probe = r'''from pathlib import Path
import hashlib
import tempfile

from lakatos.io.resource_execution import HMACPermitAuthenticator, ResourceExecutionGate
from lakatos.io.resource_journal import SQLiteResourceJournal, SignedAppendOnlyFileAnchor
from lakatos.resource_coordination import (
    RequestGrant, ResourceEstimate, ResourceState, ResourceVector, StartGrant,
)
from lakatos.resource_execution import WorkloadDispatchReceipt

sha = lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest()
class Clock:
    def now_utc(self):
        return "2026-08-07T11:02:00Z"
class Effect:
    adapter = "mutant"
    adapter_version = "1"
    def __init__(self, marker):
        self.marker = marker
    def lookup(self, permit):
        return None
    def dispatch(self, permit):
        self.marker.write_text(permit.effect_id, encoding="utf-8")
        return WorkloadDispatchReceipt(
            operation=permit.operation, effect_id=permit.effect_id,
            workload_sha256=permit.workload_sha256, fence_token=permit.fence_token,
            intent_sha256=permit.intent_sha256,
            completed_at="2026-08-07T11:03:00Z", evidence_sha256=sha("evidence"),
        )

with tempfile.TemporaryDirectory() as raw:
    root = Path(raw)
    scope = "tree:mutant-resource-execution"
    workload = sha("mutant-workload")
    journal = SQLiteResourceJournal(
        root / "resource.sqlite3",
        trusted_anchor=SignedAppendOnlyFileAnchor(
            root / "anchor", signing_key=bytes(range(32)),
        ),
    )
    journal.initialize(ResourceState.create(
        budget_id="budget:mutant", scope=scope, epoch=1,
        hard_caps=ResourceVector(100, 200, 40),
    ))
    def request(command_id, grant_id, wall, request_workload):
        return RequestGrant(
            command_id=command_id, grant_id=grant_id, fence_token=7,
            observed_at="2026-08-07T11:00:00Z",
            expires_at="2026-08-07T12:00:00Z",
            estimate=ResourceEstimate(
                work_id="work:" + grant_id, attempt_id="attempt:" + grant_id,
                workload_sha256=request_workload, adapter="mutant", adapter_version="1",
                upper_bound=ResourceVector(wall, 20, 5),
                valid_until="2026-08-07T12:00:00Z",
            ),
        )
    journal.apply(scope, request("request:effect", "grant:effect", 10, workload))
    marker = root / "physical-effect"
    gate = ResourceExecutionGate(
        scope=scope, journal=journal, effect=Effect(marker), clock=Clock(),
        permit_authenticator=HMACPermitAuthenticator(
            signing_key=bytes(range(32)), issuer="mutant",
        ),
    )
    authorization = gate.prepare(StartGrant(
        command_id="effect:effect", grant_id="grant:effect", fence_token=7,
        workload_sha256=workload, observed_at="2026-08-07T11:01:00Z",
    ))
    rejected = journal.apply(
        scope,
        request("request:rejected", "grant:rejected", 101, sha("rejected-workload")),
    )
    assert not rejected.decision.accepted
    gate.dispatch(authorization)
    if marker.exists():
        raise AssertionError("MUTANT_EXECUTED_STALE_PERMIT")
    raise AssertionError("MUTANT_DID_NOT_REACH_EFFECT")
'''

    completed = _run_isolated_execution_mutant(
        mutant_source=mutant,
        probe=probe,
        prefix="lakatotree-resource-execution-mutant-",
    )
    if completed.returncode == 0 or "MUTANT_EXECUTED_STALE_PERMIT" not in completed.stderr:
        raise RuntimeError(
            "isolated immediate-revalidation mutant missed preregistered RED: "
            f"rc={completed.returncode} stderr={completed.stderr[-500:]}"
        )
    if hashlib.sha256(source_path.read_bytes()).hexdigest() != canonical_sha256:
        raise RuntimeError("canonical execution gate changed during mutation receipt")


def _permit_authentication_mutant_must_red() -> None:
    source_path = ROOT / "lakatos" / "io" / "resource_execution.py"
    source = source_path.read_text(encoding="utf-8")
    if source.count(_AUTHENTICATION_MARKER) != 1:
        raise RuntimeError("permit authentication mutation marker is not unique")
    mutant = source.replace(
        _AUTHENTICATION_MARKER,
        "        permit = authorization.permit\n",
        1,
    )
    canonical_sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()
    _require(
        hashlib.sha256(mutant.encode("utf-8")).hexdigest() != canonical_sha256,
        "permit authentication mutant did not change source",
    )

    probe = r'''from pathlib import Path
import hashlib
import tempfile

from lakatos.io.resource_execution import (
    AuthenticatedWorkloadDispatchPermit,
    HMACPermitAuthenticator,
    ResourceExecutionGate,
)
from lakatos.io.resource_journal import SQLiteResourceJournal, SignedAppendOnlyFileAnchor
from lakatos.resource_coordination import (
    RequestGrant, ResourceEstimate, ResourceState, ResourceVector, StartGrant,
)
from lakatos.resource_execution import WorkloadDispatchReceipt

sha = lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest()
class Clock:
    def now_utc(self):
        return "2026-08-07T11:02:00Z"
class Effect:
    adapter = "authentication-mutant"
    adapter_version = "1"
    def __init__(self, marker):
        self.marker = marker
    def lookup(self, reference):
        return None
    def dispatch(self, permit):
        self.marker.write_text(permit.effect_id, encoding="utf-8")
        return WorkloadDispatchReceipt(
            operation=permit.operation, effect_id=permit.effect_id,
            workload_sha256=permit.workload_sha256, fence_token=permit.fence_token,
            intent_sha256=permit.intent_sha256,
            completed_at="2026-08-07T11:03:00Z", evidence_sha256=sha("evidence"),
        )

with tempfile.TemporaryDirectory() as raw:
    root = Path(raw)
    scope = "tree:authentication-mutant"
    workload = sha("authentication-mutant-workload")
    journal = SQLiteResourceJournal(
        root / "resource.sqlite3",
        trusted_anchor=SignedAppendOnlyFileAnchor(
            root / "anchor", signing_key=bytes(range(32)),
        ),
    )
    journal.initialize(ResourceState.create(
        budget_id="budget:authentication-mutant", scope=scope, epoch=1,
        hard_caps=ResourceVector(100, 200, 40),
    ))
    journal.apply(scope, RequestGrant(
        command_id="request:effect", grant_id="grant:effect", fence_token=7,
        observed_at="2026-08-07T11:00:00Z",
        expires_at="2026-08-07T12:00:00Z",
        estimate=ResourceEstimate(
            work_id="work:effect", attempt_id="attempt:effect",
            workload_sha256=workload, adapter="authentication-mutant",
            adapter_version="1", upper_bound=ResourceVector(10, 20, 5),
            valid_until="2026-08-07T12:00:00Z",
        ),
    ))
    marker = root / "forged-physical-effect"
    gate = ResourceExecutionGate(
        scope=scope, journal=journal, effect=Effect(marker), clock=Clock(),
        permit_authenticator=HMACPermitAuthenticator(
            signing_key=bytes(range(32)), issuer="authentication-mutant",
        ),
    )
    valid = gate.prepare(StartGrant(
        command_id="effect:effect", grant_id="grant:effect", fence_token=7,
        workload_sha256=workload, observed_at="2026-08-07T11:01:00Z",
    ))
    forged = AuthenticatedWorkloadDispatchPermit(
        permit=valid.permit,
        issuer=valid.issuer,
        authentication_sha256="0" * 64,
    )
    gate.dispatch(forged)
    if marker.exists():
        raise AssertionError("MUTANT_EXECUTED_FORGED_PERMIT")
    raise AssertionError("MUTANT_DID_NOT_REACH_EFFECT")
'''

    completed = _run_isolated_execution_mutant(
        mutant_source=mutant,
        probe=probe,
        prefix="lakatotree-permit-authentication-mutant-",
    )
    if (
        completed.returncode == 0
        or "MUTANT_EXECUTED_FORGED_PERMIT" not in completed.stderr
    ):
        raise RuntimeError(
            "isolated permit-authentication mutant missed preregistered RED: "
            f"rc={completed.returncode} stderr={completed.stderr[-500:]}"
        )
    if hashlib.sha256(source_path.read_bytes()).hexdigest() != canonical_sha256:
        raise RuntimeError("canonical execution gate changed during mutation receipt")


def verify(backend, cid):
    with tempfile.TemporaryDirectory(prefix="lakatotree-resource-execution-receipt-") as raw:
        root = Path(raw)
        scope = "tree:ooptdd-resource-execution"
        journal = SQLiteResourceJournal(
            root / "resource.sqlite3",
            trusted_anchor=SignedAppendOnlyFileAnchor(
                root / "trusted-anchor",
                signing_key=bytes(range(32)),
            ),
        )
        journal.initialize(_state(scope))
        journal.apply(scope, _request(scope))
        clock = _Clock()
        target_stem = root / "physical-effect"
        effect = _TransactionalTargetEffect(target_stem)
        gate = ResourceExecutionGate(
            scope=scope,
            journal=journal,
            effect=effect,
            clock=clock,
            permit_authenticator=_permit_authenticator(),
        )

        authorization = gate.prepare(_start(scope))
        permit = authorization.permit
        snapshot = journal.load(scope)
        _require(snapshot.anchor_status is AnchorStatus.CONFIRMED, "intent is unconfirmed")
        _require(snapshot.checkpoint.command_id == permit.effect_id, "effect id is unbound")
        _require(snapshot.state.revision == permit.authority_revision, "revision is unbound")
        _require(
            snapshot.checkpoint.checkpoint_sha256 == permit.authority_checkpoint_sha256,
            "checkpoint is unbound",
        )
        _require(
            snapshot.checkpoint.journal_head_sha256
            == permit.authority_journal_head_sha256,
            "journal head is unbound",
        )
        backend.ship([_event(cid, "confirmed_start_intent_mints_exact_permit")])

        first = gate.dispatch(authorization)
        replay_authorization = gate.prepare(_start(scope))
        replay = gate.dispatch(replay_authorization)
        _require(
            replay_authorization == authorization,
            "exact StartGrant replay changed permit",
        )
        _require(replay == first, "exact effect retry changed receipt")
        _require(effect.physical_calls == 1, "exact retry repeated physical effect")
        backend.ship([_event(cid, "exact_retry_deduplicates_physical_effect")])

        rejected = journal.apply(
            scope,
            _request(
                scope,
                command_id="request:rejected",
                grant_id="grant:rejected",
                wall=101,
            ),
        )
        _require(not rejected.decision.accepted, "head-advance probe was not rejected")
        try:
            gate.dispatch(authorization)
        except StaleWorkloadDispatchPermit:
            pass
        else:
            raise RuntimeError("stale permit reached physical effect")
        _require(effect.physical_calls == 1, "stale permit repeated physical effect")
        backend.ship([_event(cid, "stale_head_fails_closed_before_effect")])

        clock.now = "2026-08-07T11:04:00Z"
        restarted_effect = _TransactionalTargetEffect(target_stem)
        restarted_gate = ResourceExecutionGate(
            scope=scope,
            journal=journal,
            effect=restarted_effect,
            clock=clock,
            permit_authenticator=_permit_authenticator(),
        )
        reminted_authorization = restarted_gate.prepare(_start(scope))
        reminted = reminted_authorization.permit
        recovered_replay = restarted_gate.dispatch(reminted_authorization)
        _require(reminted != permit, "new confirmed head did not remint authority")
        _require(
            reminted.intent_sha256 == permit.intent_sha256,
            "stable effect intent changed during remint",
        )
        _require(recovered_replay == first, "restart changed durable effect receipt")
        _require(
            restarted_effect.physical_calls == 0,
            "restart repeated the durable physical effect",
        )
        backend.ship([_event(cid, "restart_remint_reuses_stable_effect_intent")])

        unknown_scope = "tree:ooptdd-resource-execution-unknown"
        unknown_journal = SQLiteResourceJournal(
            root / "unknown-resource.sqlite3",
            trusted_anchor=SignedAppendOnlyFileAnchor(
                root / "unknown-trusted-anchor",
                signing_key=bytes(reversed(range(32))),
            ),
        )
        unknown_journal.initialize(_state(unknown_scope))
        unknown_journal.apply(unknown_scope, _request(unknown_scope))
        unknown_target_stem = root / "unknown-physical-effect"
        crashing_effect = _TransactionalTargetEffect(
            unknown_target_stem,
            crash_after_commit=True,
        )
        unknown_gate = ResourceExecutionGate(
            scope=unknown_scope,
            journal=unknown_journal,
            effect=crashing_effect,
            clock=_Clock(),
            permit_authenticator=_permit_authenticator(),
        )
        unknown_authorization = unknown_gate.prepare(_start(unknown_scope))
        unknown_permit = unknown_authorization.permit
        try:
            unknown_gate.dispatch(unknown_authorization)
        except DispatchOutcomeUnknown as exc:
            _require(exc.usage_unknown_recorded, "UsageUnknown was not confirmed")
        else:
            raise RuntimeError("response loss was not classified outcome-unknown")
        _require(
            unknown_journal.load(unknown_scope)
            .state.grant(unknown_permit.grant_id)
            .status
            is GrantStatus.RECONCILIATION_REQUIRED,
            "unknown outcome did not hold the reservation",
        )
        recovery_effect = _TransactionalTargetEffect(unknown_target_stem)
        recovery_gate = ResourceExecutionGate(
            scope=unknown_scope,
            journal=unknown_journal,
            effect=recovery_effect,
            clock=_Clock(),
            permit_authenticator=_permit_authenticator(),
        )
        _require(
            recovery_gate.recoverable_effect_ids() == (unknown_permit.effect_id,),
            "restart could not discover the durable intent",
        )
        recovered = recovery_gate.reconcile(unknown_permit.effect_id)
        _require(recovered is not None, "restart lookup lost the durable receipt")
        _require(recovered.intent_sha256 == unknown_permit.intent_sha256, "bad recovery")
        _require(recovery_effect.physical_calls == 0, "reconcile dispatched new work")
        backend.ship([_event(cid, "unknown_outcome_persists_and_reconciles")])

    _immediate_revalidation_mutant_must_red()
    backend.ship([_event(cid, "immediate_revalidation_load_bearing")])
    _permit_authentication_mutant_must_red()
    backend.ship([_event(cid, "permit_authentication_load_bearing")])
