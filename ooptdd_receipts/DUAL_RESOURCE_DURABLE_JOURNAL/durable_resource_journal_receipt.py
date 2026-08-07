"""Hermetic OOPTDD receipt for the durable dual-resource journal."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lakatos.io.resource_journal import (  # noqa: E402
    AnchorStatus,
    DatabaseRollbackDetected,
    SQLiteResourceJournal,
    SignedAppendOnlyFileAnchor,
)
from lakatos.resource_coordination import (  # noqa: E402
    CapacityExceeded,
    RequestGrant,
    ResourceEstimate,
    ResourceState,
    ResourceVector,
)


SIGNING_KEY = bytes(range(32))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(f"durable resource journal receipt red: {message}")


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _event(cid: str, name: str) -> dict:
    # Observation literals belong to this receipt adapter, not the domain kernel.
    return {
        "cid": cid,
        "correlation_id": cid,
        "cycle_id": cid,
        "service": "lakatotree.resource_journal",
        "event": name,
    }


def _state(scope: str) -> ResourceState:
    return ResourceState.create(
        budget_id=f"budget:{scope}",
        scope=scope,
        epoch=1,
        hard_caps=ResourceVector(100, 100, 20),
    )


def _request(command_id: str, grant_id: str) -> RequestGrant:
    workload = _sha(f"workload:{grant_id}")
    return RequestGrant(
        command_id=command_id,
        grant_id=grant_id,
        fence_token=1,
        observed_at="2026-08-07T11:00:00Z",
        expires_at="2026-08-07T12:00:00Z",
        estimate=ResourceEstimate(
            work_id=f"work:{grant_id}",
            attempt_id=f"attempt:{grant_id}",
            workload_sha256=workload,
            adapter="durable-journal-ooptdd",
            adapter_version="1",
            upper_bound=ResourceVector(100, 100, 20),
            valid_until="2026-08-07T12:00:00Z",
        ),
    )


def _anchor(path: Path) -> SignedAppendOnlyFileAnchor:
    return SignedAppendOnlyFileAnchor(path, signing_key=SIGNING_KEY)


def _response_loss_exact_replay(root: Path) -> None:
    scope = "tree:receipt-response-loss"
    database = root / "response-loss.sqlite3"
    anchor = _anchor(root / "response-loss-anchor")
    lost = False

    def lose_once(_result) -> None:
        nonlocal lost
        if not lost:
            lost = True
            raise ConnectionError("simulated response loss")

    writer = SQLiteResourceJournal(
        database,
        trusted_anchor=anchor,
        failure_inject_after_commit=lose_once,
    )
    writer.initialize(_state(scope))
    command = _request("response-command", "response-grant")
    try:
        writer.apply(scope, command)
    except ConnectionError:
        pass
    else:
        raise RuntimeError("response-loss injection did not interrupt the caller")

    with sqlite3.connect(database) as connection:
        transition_count = connection.execute(
            "SELECT count(*) FROM resource_journal WHERE scope = ?", (scope,)
        ).fetchone()[0]
    _require(transition_count == 1, "committed transition was lost or duplicated")

    replay = SQLiteResourceJournal(database, trusted_anchor=anchor).apply(
        scope,
        command,
        expected_revision=0,
    )
    _require(replay.decision.replayed, "exact retry was not classified as replay")
    _require(replay.state.revision == 1, "exact retry advanced the durable revision")
    _require(
        replay.anchor_status is AnchorStatus.CONFIRMED,
        "exact retry did not reconcile its pending checkpoint",
    )
    _require(
        not hasattr(replay, "executable"),
        "durability result exposed a stale operation-agnostic execution boolean",
    )


def _concurrent_last_slot(root: Path) -> None:
    scope = "tree:receipt-last-slot"
    database = root / "last-slot.sqlite3"
    anchor_path = root / "last-slot-anchor"
    SQLiteResourceJournal(database, trusted_anchor=_anchor(anchor_path)).initialize(
        _state(scope)
    )
    barrier = threading.Barrier(3)

    def claim(index: int):
        journal = SQLiteResourceJournal(database, trusted_anchor=_anchor(anchor_path))
        barrier.wait(timeout=5)
        return journal.apply(
            scope,
            _request(f"last-slot-command-{index}", f"last-slot-grant-{index}"),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(claim, index) for index in (1, 2)]
        barrier.wait(timeout=5)
        results = [future.result(timeout=15) for future in futures]

    _require(
        sum(result.decision.accepted for result in results) == 1,
        "concurrent writers did not serialize to exactly one admission",
    )
    rejection = next(result for result in results if not result.decision.accepted)
    _require(
        isinstance(rejection.decision.rejection, CapacityExceeded),
        "losing last-slot claim was not a durable capacity rejection",
    )
    final = SQLiteResourceJournal(database, trusted_anchor=_anchor(anchor_path)).load(scope)
    _require(final.state.revision == 2, "one concurrent command vanished")
    _require(len(final.state.grants) == 1, "last slot was oversubscribed")
    _require(final.state.reserved == final.state.hard_caps, "reservation vector drifted")


def _external_rollback_guard(root: Path) -> None:
    scope = "tree:receipt-rollback"
    database = root / "rollback.sqlite3"
    old_database = root / "rollback-genesis.sqlite3"
    anchor = _anchor(root / "rollback-anchor")
    journal = SQLiteResourceJournal(database, trusted_anchor=anchor)
    journal.initialize(_state(scope))
    shutil.copyfile(database, old_database)
    journal.apply(scope, _request("rollback-command", "rollback-grant"))
    shutil.copyfile(old_database, database)

    try:
        SQLiteResourceJournal(database, trusted_anchor=anchor).load(scope)
    except DatabaseRollbackDetected:
        return
    raise RuntimeError("externally anchored database rollback was accepted")


_COMMIT_MARKER = '''                # OOPTDD_COMMIT_BEFORE_RESPONSE_GUARD: local history must be durable
                # before a callback, anchor publication, or caller response can occur.
                connection.commit()
'''


def _commit_order_mutant_must_red() -> None:
    source_path = ROOT / "lakatos" / "io" / "resource_journal.py"
    source = source_path.read_text(encoding="utf-8")
    if source.count(_COMMIT_MARKER) != 1:
        raise RuntimeError("durable commit mutation marker is not unique")
    replacement = _COMMIT_MARKER.replace(
        "connection.commit()",
        "connection.rollback()",
    )
    mutant = source.replace(_COMMIT_MARKER, replacement, 1)
    source_sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()
    if hashlib.sha256(mutant.encode("utf-8")).hexdigest() == source_sha256:
        raise RuntimeError("durable journal mutant did not change source")

    probe = r'''from pathlib import Path
import hashlib
import tempfile

from lakatos.io.resource_journal import SQLiteResourceJournal
from lakatos.resource_coordination import (
    RequestGrant, ResourceEstimate, ResourceState, ResourceVector,
)

sha = lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest()
with tempfile.TemporaryDirectory() as raw:
    root = Path(raw)
    scope = "tree:commit-mutant"
    state = ResourceState.create(
        budget_id="budget:commit-mutant", scope=scope, epoch=1,
        hard_caps=ResourceVector(1, 1, 1),
    )
    def lose(_result):
        raise ConnectionError("response lost")
    journal = SQLiteResourceJournal(
        root / "resource.sqlite3", failure_inject_after_commit=lose,
    )
    journal.initialize(state)
    command = RequestGrant(
        command_id="commit-command", grant_id="commit-grant", fence_token=1,
        observed_at="2026-08-07T11:00:00Z", expires_at="2026-08-07T12:00:00Z",
        estimate=ResourceEstimate(
            work_id="commit-work", attempt_id="commit-attempt",
            workload_sha256=sha("commit-workload"), adapter="mutant",
            adapter_version="1", upper_bound=ResourceVector(1, 1, 1),
            valid_until="2026-08-07T12:00:00Z",
        ),
    )
    try:
        journal.apply(scope, command)
    except ConnectionError:
        pass
    loaded = SQLiteResourceJournal(root / "resource.sqlite3").load(scope)
    assert loaded.state.revision == 1, "MUTANT_LOST_COMMIT"
'''

    with tempfile.TemporaryDirectory(prefix="lakatotree-journal-mutant-") as raw_temp:
        package = Path(raw_temp) / "lakatos"
        io_package = package / "io"
        io_package.mkdir(parents=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
        (io_package / "__init__.py").write_text("", encoding="utf-8")
        for relative in (
            "resource_coordination.py",
            "resource_kernel.py",
            "write_cert.py",
        ):
            (package / relative).write_bytes(
                (ROOT / "lakatos" / relative).read_bytes()
            )
        for name in (
            "_resource_journal_contracts.py",
            "_resource_journal_codec.py",
            "_resource_anchor.py",
        ):
            (io_package / name).write_bytes(
                (ROOT / "lakatos" / "io" / name).read_bytes()
            )
        (io_package / "resource_journal.py").write_text(mutant, encoding="utf-8")
        environment = os.environ.copy()
        environment["PYTHONPATH"] = raw_temp
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        completed = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=raw_temp,
            env=environment,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
    if completed.returncode == 0 or "MUTANT_LOST_COMMIT" not in completed.stderr:
        raise RuntimeError(
            "isolated commit-order mutant did not produce the preregistered RED: "
            f"rc={completed.returncode} stderr={completed.stderr[-500:]}"
        )
    if hashlib.sha256(source_path.read_bytes()).hexdigest() != source_sha256:
        raise RuntimeError("canonical durable journal changed during mutation receipt")


def verify(backend, cid):
    with tempfile.TemporaryDirectory(prefix="lakatotree-durable-journal-receipt-") as raw:
        root = Path(raw)
        _response_loss_exact_replay(root)
        backend.ship([_event(cid, "response_loss_exact_replay_durable")])

        _concurrent_last_slot(root)
        backend.ship([_event(cid, "concurrent_last_slot_serialized")])

        _external_rollback_guard(root)
        backend.ship([_event(cid, "external_checkpoint_detects_rollback")])

    _commit_order_mutant_must_red()
    backend.ship([_event(cid, "commit_before_response_load_bearing")])
