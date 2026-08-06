"""RED-first integration guards for the durable dual-resource journal.

These tests use real files and independent SQLite connections.  They exercise
the response-loss and concurrency windows that the pure resource kernel cannot
close by itself.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time

import pytest

from lakatos.io.resource_journal import (
    AnchorStatus,
    DatabaseRollbackDetected,
    HistoryReplacementDetected,
    JournalSchemaMismatch,
    RevisionConflict,
    SQLiteResourceJournal,
    SignedAppendOnlyFileAnchor,
)
from lakatos.resource_coordination import (
    CapacityExceeded,
    IdempotencyConflict,
    RequestGrant,
    ResourceEstimate,
    ResourceState,
    ResourceVector,
    decide,
)


SCOPE = "tree:durable-resource"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _state(
    *,
    scope: str = SCOPE,
    wall: int = 100,
    input_tokens: int = 100,
    output_tokens: int = 20,
) -> ResourceState:
    return ResourceState.create(
        budget_id=f"budget:{scope}",
        scope=scope,
        epoch=1,
        hard_caps=ResourceVector(wall, input_tokens, output_tokens),
    )


def _request(
    command_id: str,
    grant_id: str,
    *,
    wall: int = 100,
    input_tokens: int = 100,
    output_tokens: int = 20,
) -> RequestGrant:
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
            adapter="durable-journal-test",
            adapter_version="1",
            upper_bound=ResourceVector(wall, input_tokens, output_tokens),
            valid_until="2026-08-07T12:00:00Z",
        ),
    )


def _anchor(path: Path) -> SignedAppendOnlyFileAnchor:
    return SignedAppendOnlyFileAnchor(path, signing_key=bytes(range(32)))


def _counts(database: Path, scope: str = SCOPE) -> tuple[int, int, int]:
    with sqlite3.connect(database) as connection:
        head = connection.execute(
            "SELECT revision FROM resource_budget_head WHERE scope = ?", (scope,)
        ).fetchone()
        transitions = connection.execute(
            "SELECT count(*) FROM resource_journal WHERE scope = ?", (scope,)
        ).fetchone()[0]
        intents = connection.execute(
            "SELECT count(*) FROM resource_anchor_outbox WHERE scope = ?", (scope,)
        ).fetchone()[0]
    assert head is not None
    return int(head[0]), int(transitions), int(intents)


def test_guard_mechanism_commit_survives_response_loss_and_exact_retry(tmp_path):
    database = tmp_path / "resource.sqlite3"
    anchor = _anchor(tmp_path / "trusted-anchor")
    genesis = _state()
    expected = decide(genesis, _request("command-1", "grant-1")).receipt

    lost = False

    def lose_response(_result) -> None:
        nonlocal lost
        if not lost:
            lost = True
            raise ConnectionError("simulated response loss after SQLite commit")

    writer = SQLiteResourceJournal(
        database,
        trusted_anchor=anchor,
        failure_inject_after_commit=lose_response,
    )
    created = writer.initialize(genesis)
    assert created.anchor_status is AnchorStatus.CONFIRMED

    with pytest.raises(ConnectionError, match="after SQLite commit"):
        writer.apply(SCOPE, _request("command-1", "grant-1"))

    # Independent readback before retry proves the exception happened after commit.
    assert _counts(database) == (1, 1, 2)  # genesis + revision-1 anchor intents
    pending = SQLiteResourceJournal(database, trusted_anchor=anchor).load(SCOPE)
    assert pending.state.revision == 1
    assert pending.anchor_status is AnchorStatus.PENDING

    replay = SQLiteResourceJournal(database, trusted_anchor=anchor).apply(
        SCOPE,
        _request("command-1", "grant-1"),
        expected_revision=0,
    )
    assert replay.decision.replayed is True
    assert replay.decision.receipt == expected
    assert replay.anchor_status is AnchorStatus.CONFIRMED
    assert not hasattr(replay, "executable")
    assert _counts(database) == (1, 1, 2)


def test_guard_defect_changed_command_id_payload_conflicts_without_mutation(tmp_path):
    database = tmp_path / "resource.sqlite3"
    journal = SQLiteResourceJournal(database, trusted_anchor=_anchor(tmp_path / "anchor"))
    journal.initialize(_state())
    first = journal.apply(SCOPE, _request("same-command", "grant-1", wall=20))
    assert first.decision.accepted is True
    assert first.anchor_status is AnchorStatus.CONFIRMED
    assert not hasattr(first, "executable")

    with pytest.raises(IdempotencyConflict):
        journal.apply(SCOPE, _request("same-command", "grant-1", wall=21))

    assert _counts(database) == (1, 1, 2)
    snapshot = journal.load(SCOPE)
    assert snapshot.state.reserved == ResourceVector(20, 100, 20)


def test_exact_retry_precedes_stale_revision_but_new_stale_command_conflicts(tmp_path):
    database = tmp_path / "resource.sqlite3"
    journal = SQLiteResourceJournal(database, trusted_anchor=_anchor(tmp_path / "anchor"))
    journal.initialize(_state())
    journal.apply(SCOPE, _request("command-1", "grant-1", wall=10), expected_revision=0)

    journal.apply(
        SCOPE,
        _request("command-2", "grant-2", wall=10),
        expected_revision=1,
    )

    replay = journal.apply(
        SCOPE,
        _request("command-1", "grant-1", wall=10),
        expected_revision=0,
    )
    assert replay.decision.replayed is True
    assert replay.state.revision == replay.checkpoint.revision == 1
    assert replay.state.snapshot_sha256 == replay.checkpoint.state_sha256
    assert journal.load(SCOPE).state.revision == 2

    with pytest.raises(RevisionConflict) as conflict:
        journal.apply(
            SCOPE,
            _request("command-3", "grant-3", wall=10),
            expected_revision=0,
        )
    assert (conflict.value.expected_revision, conflict.value.actual_revision) == (0, 2)
    assert _counts(database) == (2, 2, 3)


def test_two_processes_claiming_last_slot_serialize_without_oversubscription(tmp_path):
    database = tmp_path / "resource.sqlite3"
    anchor_dir = tmp_path / "trusted-anchor"
    SQLiteResourceJournal(database, trusted_anchor=_anchor(anchor_dir)).initialize(_state())
    start = tmp_path / "start"
    script = r'''from pathlib import Path
import hashlib, json, sys, time
from lakatos.io.resource_journal import SQLiteResourceJournal, SignedAppendOnlyFileAnchor
from lakatos.resource_coordination import RequestGrant, ResourceEstimate, ResourceVector

database, anchor_dir, scope, raw_index, ready, start = sys.argv[1:]
index = int(raw_index)
sha = lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest()
grant_id = f"grant-{index}"
command = RequestGrant(
    command_id=f"command-{index}", grant_id=grant_id, fence_token=1,
    observed_at="2026-08-07T11:00:00Z", expires_at="2026-08-07T12:00:00Z",
    estimate=ResourceEstimate(
        work_id=f"work:{grant_id}", attempt_id=f"attempt:{grant_id}",
        workload_sha256=sha(f"workload:{grant_id}"), adapter="process-test",
        adapter_version="1", upper_bound=ResourceVector(100, 100, 20),
        valid_until="2026-08-07T12:00:00Z",
    ),
)
journal = SQLiteResourceJournal(
    database,
    trusted_anchor=SignedAppendOnlyFileAnchor(anchor_dir, signing_key=bytes(range(32))),
)
Path(ready).write_text("ready", encoding="utf-8")
deadline = time.monotonic() + 10
while not Path(start).exists():
    if time.monotonic() >= deadline:
        raise TimeoutError("parent did not release process race")
    time.sleep(0.005)
result = journal.apply(scope, command)
print(json.dumps({
    "accepted": result.decision.accepted,
    "rejection": None if result.decision.rejection is None else type(result.decision.rejection).__name__,
    "dimensions": [] if result.decision.rejection is None else list(result.decision.rejection.dimensions),
    "anchor_status": result.anchor_status.value,
}))
'''
    processes = []
    ready_paths = []
    try:
        for index in (1, 2):
            ready = tmp_path / f"ready-{index}"
            ready_paths.append(ready)
            processes.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        "-c",
                        script,
                        str(database),
                        str(anchor_dir),
                        SCOPE,
                        str(index),
                        str(ready),
                        str(start),
                    ],
                    cwd=Path(__file__).resolve().parents[1],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            )
        deadline = time.monotonic() + 10
        while not all(path.exists() for path in ready_paths):
            assert time.monotonic() < deadline, "child processes did not reach race barrier"
            assert all(process.poll() is None for process in processes)
            time.sleep(0.005)
        start.write_text("go", encoding="utf-8")
        completed = [process.communicate(timeout=20) for process in processes]
        for process, (_stdout, stderr) in zip(processes, completed):
            assert process.returncode == 0, stderr
        results = [json.loads(stdout) for stdout, _stderr in completed]
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)

    assert sum(result["accepted"] for result in results) == 1
    rejected = next(result for result in results if not result["accepted"])
    assert rejected["rejection"] == CapacityExceeded.__name__
    assert tuple(rejected["dimensions"]) == (
        "compute.wall_ms",
        "llm.input_tokens",
        "llm.output_tokens",
    )
    assert all(result["anchor_status"] == AnchorStatus.CONFIRMED.value for result in results)

    final = SQLiteResourceJournal(database, trusted_anchor=_anchor(anchor_dir)).load(SCOPE)
    assert final.state.revision == 2
    assert len(final.state.grants) == 1
    assert final.state.reserved == final.state.hard_caps
    assert _counts(database) == (2, 2, 3)


def test_process_death_after_commit_is_recovered_by_exact_retry(tmp_path):
    database = tmp_path / "resource.sqlite3"
    anchor_dir = tmp_path / "trusted-anchor"
    SQLiteResourceJournal(database, trusted_anchor=_anchor(anchor_dir)).initialize(_state())
    script = r'''import hashlib, os, sys
from lakatos.io.resource_journal import SQLiteResourceJournal, SignedAppendOnlyFileAnchor
from lakatos.resource_coordination import RequestGrant, ResourceEstimate, ResourceVector

database, anchor_dir, scope = sys.argv[1:]
sha = lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest()
command = RequestGrant(
    command_id="process-loss-command", grant_id="process-loss-grant", fence_token=1,
    observed_at="2026-08-07T11:00:00Z", expires_at="2026-08-07T12:00:00Z",
    estimate=ResourceEstimate(
        work_id="work:process-loss-grant", attempt_id="attempt:process-loss-grant",
        workload_sha256=sha("workload:process-loss-grant"), adapter="durable-journal-test",
        adapter_version="1", upper_bound=ResourceVector(10, 10, 2),
        valid_until="2026-08-07T12:00:00Z",
    ),
)
def die_after_commit(_result):
    os._exit(86)
journal = SQLiteResourceJournal(
    database,
    trusted_anchor=SignedAppendOnlyFileAnchor(anchor_dir, signing_key=bytes(range(32))),
    failure_inject_after_commit=die_after_commit,
)
journal.apply(scope, command)
raise AssertionError("failure injection did not terminate the process")
'''
    completed = subprocess.run(
        [sys.executable, "-c", script, str(database), str(anchor_dir), SCOPE],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 86, completed.stderr
    assert _counts(database) == (1, 1, 2)
    pending = SQLiteResourceJournal(database, trusted_anchor=_anchor(anchor_dir)).load(SCOPE)
    assert pending.state.revision == 1
    assert pending.anchor_status is AnchorStatus.PENDING

    replay = SQLiteResourceJournal(database, trusted_anchor=_anchor(anchor_dir)).apply(
        SCOPE,
        _request(
            "process-loss-command",
            "process-loss-grant",
            wall=10,
            input_tokens=10,
            output_tokens=2,
        ),
        expected_revision=0,
    )
    assert replay.decision.replayed is True
    assert replay.anchor_status is AnchorStatus.CONFIRMED
    assert _counts(database) == (1, 1, 2)


def test_anchor_reconciliation_is_idempotent_across_both_crash_windows(tmp_path):
    database = tmp_path / "resource.sqlite3"
    anchor = _anchor(tmp_path / "trusted-anchor")
    genesis = _state()
    lost = False

    def stop_before_anchor(_result) -> None:
        nonlocal lost
        if not lost:
            lost = True
            raise RuntimeError("crash before external anchor")

    journal = SQLiteResourceJournal(
        database,
        trusted_anchor=anchor,
        failure_inject_after_commit=stop_before_anchor,
    )
    journal.initialize(genesis)
    with pytest.raises(RuntimeError, match="before external anchor"):
        journal.apply(SCOPE, _request("command-1", "grant-1"))
    assert anchor.read(SCOPE).revision == 0

    published = False

    def stop_after_publish(_checkpoint) -> None:
        nonlocal published
        if not published:
            published = True
            raise RuntimeError("crash after external anchor before local mark")

    fresh = SQLiteResourceJournal(database, trusted_anchor=anchor)
    with pytest.raises(RuntimeError, match="before local mark"):
        fresh.reconcile_anchor(SCOPE, after_publish=stop_after_publish)
    assert anchor.read(SCOPE).revision == 1
    assert fresh.load(SCOPE).anchor_status is AnchorStatus.PENDING

    reconciled = fresh.reconcile_anchor(SCOPE)
    assert reconciled.confirmed_revisions == (1,)
    assert reconciled.snapshot.anchor_status is AnchorStatus.CONFIRMED
    assert anchor.read(SCOPE).revision == 1
    assert _counts(database) == (1, 1, 2)


def test_external_anchor_detects_database_rollback(tmp_path):
    database = tmp_path / "resource.sqlite3"
    genesis_copy = tmp_path / "genesis.sqlite3"
    anchor = _anchor(tmp_path / "trusted-anchor")
    journal = SQLiteResourceJournal(database, trusted_anchor=anchor)
    journal.initialize(_state())
    shutil.copyfile(database, genesis_copy)
    journal.apply(SCOPE, _request("command-1", "grant-1"))
    assert anchor.read(SCOPE).revision == 1

    shutil.copyfile(genesis_copy, database)
    restored = SQLiteResourceJournal(database, trusted_anchor=anchor)
    with pytest.raises(DatabaseRollbackDetected):
        restored.load(SCOPE)
    with pytest.raises(DatabaseRollbackDetected):
        restored.apply(SCOPE, _request("command-2", "grant-2"))


def test_external_anchor_detects_convergent_same_revision_history_replacement(tmp_path):
    trusted_database = tmp_path / "trusted.sqlite3"
    replacement_database = tmp_path / "replacement.sqlite3"
    anchor = _anchor(tmp_path / "trusted-anchor")
    genesis = _state(wall=1, input_tokens=1, output_tokens=1)

    trusted = SQLiteResourceJournal(trusted_database, trusted_anchor=anchor)
    trusted.initialize(genesis)
    anchored = trusted.apply(
        SCOPE,
        _request("rejected-a", "grant-a", wall=2, input_tokens=1, output_tokens=1),
    )
    assert not anchored.decision.accepted

    replacement = SQLiteResourceJournal(replacement_database)
    replacement.initialize(genesis)
    alternative = replacement.apply(
        SCOPE,
        _request("rejected-b", "grant-b", wall=1, input_tokens=2, output_tokens=1),
    )
    assert not alternative.decision.accepted
    assert alternative.state.snapshot_sha256 == anchored.state.snapshot_sha256
    assert alternative.checkpoint.journal_head_sha256 != anchored.checkpoint.journal_head_sha256

    shutil.copyfile(replacement_database, trusted_database)
    replaced = SQLiteResourceJournal(trusted_database, trusted_anchor=anchor)
    with pytest.raises(HistoryReplacementDetected):
        replaced.load(SCOPE)


def test_live_sqlite_schema_objects_are_verified_not_only_metadata_receipt(tmp_path):
    database = tmp_path / "resource.sqlite3"
    SQLiteResourceJournal(database).initialize(_state())
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TRIGGER unauthorized_resource_trigger "
            "AFTER INSERT ON resource_journal BEGIN SELECT 1; END"
        )

    with pytest.raises(JournalSchemaMismatch, match="live schema"):
        SQLiteResourceJournal(database)


def test_signed_anchor_rejects_file_tampering(tmp_path):
    anchor_dir = tmp_path / "trusted-anchor"
    anchor = _anchor(anchor_dir)
    journal = SQLiteResourceJournal(tmp_path / "resource.sqlite3", trusted_anchor=anchor)
    journal.initialize(_state())
    anchor_file = next(anchor_dir.glob("*.json"))
    raw = anchor_file.read_bytes()
    anchor_file.write_bytes(raw.replace(b'"revision":0', b'"revision":9'))

    with pytest.raises(ValueError, match="anchor"):
        anchor.read(SCOPE)
