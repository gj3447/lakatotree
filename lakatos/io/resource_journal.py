"""SQLite repository and compatibility facade for durable resource state.

The deterministic command/event kernel, immutable journal contracts, pure
canonical codec, and trusted-anchor adapter live in separate modules.  This
module owns SQLite transaction ordering, replay orchestration, and the stable
public import surface retained for existing consumers.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sqlite3
from typing import Callable

from lakatos.io._resource_anchor import SignedAppendOnlyFileAnchor
from lakatos.io._resource_journal_codec import (
    _budget_blob,
    _budget_from_blob,
    _checkpoint_for,
    _transition_blob,
    _transition_from_blob,
)
from lakatos.io._resource_journal_contracts import (
    ANCHOR_SCHEMA_VERSION,
    AnchorConflict,
    AnchorReconcileResult,
    AnchorStatus,
    BudgetIdentityConflict,
    CODEC_VERSION,
    DatabaseRollbackDetected,
    DurableDecision,
    HistoryReplacementDetected,
    JOURNAL_SCHEMA_VERSION,
    JournalCorruption,
    JournalNotInitialized,
    JournalSchemaMismatch,
    JournalSnapshot,
    ResourceCheckpoint,
    ResourceJournalError,
    RevisionConflict,
    TrustedAnchorCorruption,
    TrustedAnchorStore,
    TrustedAnchorUnavailable,
    UnanchoredHistoryGap,
    _canonical_bytes,
    _checkpoint_from_dict,
    _decode_canonical_blob,
    _require_identifier,
    _sha256_bytes,
)
from lakatos.resource_coordination import ResourceCommand, ResourceState
from lakatos.resource_kernel import (
    DEFAULT_RESOURCE_KERNEL,
    ResourceKernel,
    require_compatible_resource_kernel,
)


_APPLICATION_ID = 0x4C4B5253  # ASCII "LKRS"; a signed 32-bit SQLite application id.
_USER_VERSION = 1


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
    states: tuple[ResourceState, ...]
    checkpoints: tuple[ResourceCheckpoint, ...]
    anchor_statuses: tuple[AnchorStatus, ...]

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
        kernel: ResourceKernel = DEFAULT_RESOURCE_KERNEL,
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
        self._kernel = require_compatible_resource_kernel(kernel)
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
        states = [state]
        checkpoints = [genesis]
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
                state = self._kernel.evolve(state, transition)
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
            checkpoints.append(checkpoint)
            states.append(state)
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
        statuses: list[AnchorStatus] = []
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
            statuses.append(status)
        return _LoadedJournal(
            state=state,
            states=tuple(states),
            checkpoints=tuple(checkpoints),
            anchor_statuses=tuple(statuses),
        )

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
            if any(status is AnchorStatus.CONFIRMED for status in loaded.anchor_statuses):
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
            for revision, status in enumerate(loaded.anchor_statuses)
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
            decision = self._kernel.decide(loaded.state, command)  # dedup precedes revision CAS
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
                next_state = self._kernel.evolve(loaded.state, transition)
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
