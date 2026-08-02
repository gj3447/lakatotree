"""Application composition root — owns external resource lifecycle.

Neo4j 드라이버 / Mongo DB / PostgreSQL 풀을 *하나의 응집된 주입 가능한 단위*로
생성·운용·종료한다. 기존엔 server.app 모듈 전역(`NEO`/`MONGO`/`_PG_POOL` +
`global _PG_POOL` 변이)으로 흩어져 있어 자원층을 단독으로 테스트할 수 없었다.
어댑터는 주입(기본값=실제 lazy 어댑터) — fake 를 넣어 자원층만 단위검증 가능.

server.app 은 이 컨테이너에 얇게 위임만 한다(모듈 API 는 하위호환 유지).
# KG: span_lakatotree_server_architecture
"""

from __future__ import annotations

import json
import hashlib
import logging
import re
from collections.abc import Callable, Iterable
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from datetime import datetime, timezone
from threading import Lock, RLock
from typing import Any
from uuid import uuid4

import psycopg2
import psycopg2.pool
from neo4j import Query, unit_of_work
from psycopg2 import DataError as PgDataError
from psycopg2 import InterfaceError as PgInterfaceError
from psycopg2 import IntegrityError as PgIntegrityError
from psycopg2 import OperationalError as PgOperationalError
from psycopg2.pool import PoolError as PgPoolError

from lakatos.io.reconcile import (
    canonical_history_payload,
    history_advisory_lock_keys,
    history_event_id,
    plan_reconcile,
    validate_history_record,
)
from lakatos.verdicts import RECEIPT_FIELDS
from server.contexts.tree.admin_intents import (
    AdminIntentError,
    validate_admin_verdict_intent,
)
from server.contexts.tree.verdict_intents import (
    VerdictIntentError,
    validate_verdict_intent_group,
)
from server.contexts.tree.prediction_intents import (
    PredictionIntentError,
    validate_prediction_register_intent,
)
from server.contexts.tree.receipt_chain import (
    RECEIPT_CHAIN_ROWS_CYPHER,
    RECEIPT_IDENTITIES_CYPHER,
    ReceiptGraphError,
    validate_receipt_graph,
)
from server.contexts.tree.temporal_intents import (
    PREDICTION_TEMPORAL_IDENTITY_CYPHER,
    TEMPORAL_SIDECAR_IDENTITY_CYPHER,
    TemporalIntentError,
    classify_temporal_intent,
    validate_prediction_temporal_identity_row,
    validate_temporal_sidecar_identity_row,
)
from server.ports import (
    GuardedKgOps,
    HistoryEventConflict,
    KgTxGuardFailed,
    WriterFenceLost,
)


class AppContainer:
    """외부 자원(Neo4j/Mongo/PG)의 생성·접근·종료를 소유하는 합성 루트.

    - kg / kg_tx : Neo4j 읽기 / 단일 managed-write 트랜잭션(all-or-nothing, ROB-1)
    - pg         : PG 풀에서 빌려쓰고 commit/rollback 후 반납하는 컨텍스트매니저
    - hist       : append-only 이력 적재(PG 실패는 fenced KG outbox로 보전)
    - close      : 종료 시 best-effort 정리(하나 실패해도 나머지 닫고 실패목록 반환)
    """

    _WRITER_LEASE_KEY = (1279349588, 20260802)
    _WRITER_FENCE_NAME = "critique-history-writer-v1"
    _WRITER_FENCE_QUERY_TIMEOUT_SECONDS = 5.0
    _HISTORY_STATEMENT_TIMEOUT_MS = 5_000
    _HISTORY_LOCK_TIMEOUT_MS = 3_000

    def __init__(
        self,
        *,
        neo: Any,
        mongo: Any,
        pg_kw: dict,
        logger: logging.Logger | None = None,
        pool_min: int = 1,
        pool_max: int = 16,
        on_history_divergence: Callable[[str], None] | None = None,
        pg_connection_guard: Callable[[Any], None] | None = None,
        pg_kw_factory: Callable[[], dict] | None = None,
        writer_commit_guard: Callable[[], None] | None = None,
        writer_authority_scope: Callable[[], Any] | None = None,
    ):
        self._neo = neo
        self._mongo = mongo
        self._pg_kw = pg_kw
        self._logger = logger or logging.getLogger("lakatotree.server")
        self._pool_min = pool_min
        self._pool_max = pool_max
        self._pg_pool_lock = Lock()
        self._pg_pool = None   # lazy — import/생성 시 미연결(테스트/오프라인 안전)
        # Held for the complete fenced Neo4j transaction.  Local invalidation
        # therefore drains an already-authorized write before it revokes the
        # token and releases the PostgreSQL election lease.
        self._writer_lease_lock = RLock()
        self._writer_commit_linearization_lock = RLock()
        self._writer_scope_depth: ContextVar[int] = ContextVar(
            f"writer_scope_depth_{id(self)}", default=0
        )
        self._writer_lease_conn = None
        self._writer_pg_backend_pid: int | None = None
        self._writer_fence_token: str | None = None
        self._writer_fence_generation: int | None = None
        self._on_history_divergence = on_history_divergence
        self._pg_connection_guard = pg_connection_guard
        self._pg_kw_factory = pg_kw_factory
        self._writer_commit_guard = writer_commit_guard
        self._writer_authority_scope = writer_authority_scope

    def _pg_connection_parameters(self) -> dict:
        if self._pg_kw_factory is None:
            return dict(self._pg_kw)
        parameters = self._pg_kw_factory()
        if not isinstance(parameters, dict):
            raise RuntimeError("PostgreSQL connection profile factory is invalid")
        return dict(parameters)

    def _signal_history_divergence(self, reason: str) -> None:
        """Fail the process-local critique gate without changing mutation semantics."""

        callback = self._on_history_divergence
        if callback is None:
            return
        try:
            callback(reason)
        except Exception as exc:  # noqa: BLE001 - the durable intent remains authoritative
            self._logger.error(
                "history divergence callback failed: %s", type(exc).__name__
            )

    @property
    def neo_driver(self) -> Any:
        """The exact Neo4j adapter used by both audits and mutations."""

        return self._neo

    # ── Neo4j ──────────────────────────────────────────────────────────
    def kg(self, q: str, **kw: Any) -> list[dict]:
        timeout = kw.pop("_query_timeout_seconds", None)
        statement = Query(q, timeout=float(timeout)) if timeout is not None else q
        with self._neo.session() as s:
            return s.run(statement, **kw).data()

    def _execute_kg_tx(
        self,
        ops: Iterable[tuple[str, dict]],
        *,
        writer_fence: tuple[str, int] | None = None,
    ) -> list:
        guarded = bool(getattr(ops, "require_first_result", False))
        guard_field = getattr(ops, "guard_field", None)
        guard_expected = getattr(ops, "guard_expected", True)
        op_list = list(ops)

        def _unit(tx):
            if writer_fence is not None:
                token, generation = writer_fence
                fence_rows = tx.run(
                    """MATCH (lease:RuntimeWriterLease {
                           name:$lease_name, owner_token:$owner_token,
                           generation:$generation})
                       SET lease._writer_fence_cas=
                           coalesce(lease._writer_fence_cas,0)+0
                       RETURN lease.owner_token AS owner_token,
                              lease.generation AS generation""",
                    lease_name=self._WRITER_FENCE_NAME,
                    owner_token=token,
                    generation=generation,
                ).data()
                if fence_rows != [{
                    "owner_token": token,
                    "generation": generation,
                }]:
                    # Raised inside the managed callback, before the caller's
                    # first statement: Neo4j rolls the lock touch back and no
                    # domain mutation can commit under stale authority.
                    raise WriterFenceLost("runtime writer fence is absent or stale")
            results = []
            for index, (cypher, params) in enumerate(op_list):
                data = tx.run(cypher, **params).data()
                if guarded and index == 0 and not data:
                    # Raise *inside* execute_write callback: Neo4j rolls back the dummy lock write
                    # and no later provenance op runs. Returning [] and checking after commit is too late.
                    raise KgTxGuardFailed("guarded first statement matched no row")
                if guarded and index == 0 and guard_field is not None:
                    actual = data[0].get(guard_field)
                    accepted = (
                        actual in guard_expected
                        if isinstance(guard_expected, (set, frozenset))
                        else actual == guard_expected
                    )
                    if len(data) != 1 or not accepted:
                        raise KgTxGuardFailed(
                            f"guarded first statement rejected: {actual!r}",
                            actual=actual,
                            row=(dict(data[0]) if len(data) == 1 else None),
                        )
                results.append(data)
            # This is still inside Neo4j's managed transaction callback.  A
            # deadline/generation failure therefore rolls back every domain op
            # instead of discovering stale authority after commit.
            if writer_fence is not None:
                if not self._pg_writer_lease_ready_unlocked():
                    raise WriterFenceLost(
                        "runtime PostgreSQL election lease was lost before Neo4j commit"
                    )
                if self._writer_commit_guard is not None:
                    self._writer_commit_guard()
            return results
        callback = (
            unit_of_work(timeout=self._WRITER_FENCE_QUERY_TIMEOUT_SECONDS)(_unit)
            if writer_fence is not None
            else _unit
        )
        with self._neo.session() as s:
            return s.execute_write(callback)

    def kg_tx(self, ops: Iterable[tuple[str, dict]]) -> list:
        """여러 Cypher 를 단일 managed write 트랜잭션으로 (KG-내부 부분쓰기 분기 차단, ROB-1)."""

        return self._execute_kg_tx(ops)

    @contextmanager
    def writer_ledger_scope(self):
        """Serialize one complete Neo4j-to-PostgreSQL ledger command.

        ``writer_fenced_kg_tx`` protects one Neo4j transaction.  A ledger
        command also projects PostgreSQL history and marks its outbox applied.
        Holding the same re-entrant lease lock across the complete sequence
        prevents a second request from advancing the head while the first
        projection is blocked or about to invalidate writer authority.
        """

        with self._writer_lease_lock:
            authority_scope = (
                self._writer_authority_scope()
                if self._writer_authority_scope is not None
                else nullcontext()
            )
            with authority_scope:
                token = self._writer_scope_depth.set(
                    self._writer_scope_depth.get() + 1
                )
                try:
                    yield
                finally:
                    self._writer_scope_depth.reset(token)

    @contextmanager
    def writer_commit_barrier(self):
        """Linearize fenced datastore commits against state invalidation."""

        with self._writer_commit_linearization_lock:
            yield

    def writer_fenced_kg_tx(self, ops: Iterable[tuple[str, dict]]) -> list:
        """Run a mutation only while PG election and the in-Neo token agree.

        The local lock spans the complete managed Neo4j transaction.  Lease
        invalidation/release cannot race between authorization and commit, and
        a new replica cannot replace the Neo token until this transaction
        releases the singleton node lock.
        """

        lost: WriterFenceLost | None = None
        with self._writer_lease_lock:
            token = self._writer_fence_token
            generation = self._writer_fence_generation
            if (
                not self._pg_writer_lease_ready_unlocked()
                or not isinstance(token, str)
                or not token
                or type(generation) is not int
                or generation < 1
            ):
                self._close_writer_lease_unlocked()
                lost = WriterFenceLost("runtime writer election lease is absent")
            else:
                try:
                    with self.writer_commit_barrier():
                        return self._execute_kg_tx(
                            ops, writer_fence=(token, generation)
                        )
                except WriterFenceLost as exc:
                    self._close_writer_lease_unlocked()
                    lost = exc
        assert lost is not None
        self._signal_history_divergence("runtime.global_writer_fence.lost")
        raise lost

    def _history_kg_tx(self, ops: Iterable[tuple[str, dict]]) -> list:
        """Use the signed ledger fence only inside its explicitly closed scope.

        Generic tree administration predates the critique-history writer
        contract and is deliberately not claimed by that authority.  Its
        outbox bookkeeping must therefore follow the same generic transaction
        path as its domain mutation instead of accidentally requiring a
        ContextVar that the generic command never captured.
        """

        if self._writer_scope_depth.get() > 0:
            return self.writer_fenced_kg_tx(ops)
        return self._execute_kg_tx(ops)

    # ── PostgreSQL ─────────────────────────────────────────────────────
    def pg_pool(self):
        pool = self._pg_pool
        if pool is None:
            with self._pg_pool_lock:
                pool = self._pg_pool
                if pool is None:
                    pool = psycopg2.pool.ThreadedConnectionPool(
                        self._pool_min, self._pool_max,
                        **self._pg_connection_parameters(),
                    )
                    self._pg_pool = pool
        return pool

    @contextmanager
    def pg(self):
        """풀에서 빌려 쓰고 반납 — 성공 시 commit, 예외 시 rollback, 항상 putconn."""
        pool = self.pg_pool()
        conn = None
        primary_error = False
        discard = False
        try:
            # Revalidate the authority-bearing CA/profile before a lazy pool is
            # allowed to create another physical connection.
            self._pg_connection_parameters()
            conn = pool.getconn()
            if self._pg_connection_guard is not None:
                try:
                    self._pg_connection_guard(conn)
                except Exception:
                    discard = True
                    raise
            yield conn
            conn.commit()
        except Exception:
            primary_error = True
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:  # closed/failed connections cannot roll back
                    discard = True
            raise
        finally:
            if conn is not None:
                discard = discard or bool(getattr(conn, "closed", False))
                try:
                    pool.putconn(conn, close=discard)
                except TypeError:
                    # Minimal injected pools in tests may implement the legacy
                    # one-argument port; production psycopg2 accepts ``close``.
                    try:
                        pool.putconn(conn)
                    except Exception:
                        if not primary_error:
                            raise
                except Exception:
                    if not primary_error:
                        raise

    @contextmanager
    def _writer_fenced_pg(self):
        """Commit on the same PG session that owns the advisory writer lease.

        A pooled mutation connection could survive after the dedicated lease
        session died and commit after a successor acquired authority.  Using
        the lease-owning backend for the transaction makes that schedule
        impossible: loss of the session destroys both the advisory lock and
        its in-flight transaction.
        """

        try:
            with self._writer_lease_lock:
                connection = self._writer_lease_conn
                if (
                    connection is None
                    or not self._pg_writer_lease_ready_unlocked()
                ):
                    raise WriterFenceLost(
                        "runtime PostgreSQL election lease is absent"
                    )
                with self.writer_commit_barrier():
                    primary_error: BaseException | None = None
                    try:
                        connection.autocommit = False
                        yield connection
                        if not self._pg_writer_lease_ready_unlocked():
                            raise WriterFenceLost(
                                "runtime PostgreSQL election lease was lost before commit"
                            )
                        if self._writer_commit_guard is not None:
                            self._writer_commit_guard()
                        connection.commit()
                    except BaseException as exc:
                        primary_error = exc
                        try:
                            connection.rollback()
                        except Exception:
                            pass
                        raise
                    finally:
                        if (
                            self._writer_lease_conn is connection
                            and not bool(getattr(connection, "closed", False))
                        ):
                            try:
                                connection.autocommit = True
                            except Exception:
                                if primary_error is None:
                                    raise
        except WriterFenceLost:
            # The transaction has already rolled back. Lease revocation is safe.
            self._signal_history_divergence(
                "runtime.storage_commit_authority.lost"
            )
            raise

    def _close_pg_pool(self) -> None:
        with self._pg_pool_lock:
            pool = self._pg_pool
            self._pg_pool = None
        if pool is not None:
            pool.closeall()

    def acquire_writer_lease(self) -> bool:
        """Acquire the one global critique-writer lease on a dedicated PG session."""

        with self._writer_lease_lock:
            if self._writer_lease_ready_unlocked():
                return True
            self._close_writer_lease_unlocked()
            conn = None
            try:
                conn = psycopg2.connect(**self._pg_connection_parameters())
                conn.autocommit = True
                if self._pg_connection_guard is not None:
                    self._pg_connection_guard(conn)
                with conn.cursor() as cur:
                    cur.execute("SET statement_timeout = '5s'")
                    cur.execute("SET lock_timeout = '3s'")
                    cur.execute(
                        "SELECT pg_try_advisory_lock(%s,%s)",
                        self._WRITER_LEASE_KEY,
                    )
                    row = cur.fetchone()
                if not row or row[0] is not True:
                    conn.close()
                    return False
                token = uuid4().hex
                claimed = self._claim_neo_writer_fence_unlocked(token)
                if claimed is None:
                    conn.close()
                    return False
                generation = claimed
                self._writer_lease_conn = conn
                backend_pid = conn.get_backend_pid()
                if type(backend_pid) is not int or backend_pid < 1:
                    self._close_writer_lease_unlocked()
                    return False
                self._writer_pg_backend_pid = backend_pid
                self._writer_fence_token = token
                self._writer_fence_generation = generation
                # The dedicated PG session may have died while the Neo claim
                # blocked.  Publish authority only after both sides still name
                # this exact owner; otherwise a failover replica may already
                # have advanced the fence generation.
                if not self._writer_lease_ready_unlocked():
                    self._close_writer_lease_unlocked()
                    return False
                return True
            except Exception:  # noqa: BLE001 - unavailable PG means no writer authority
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
                self._close_writer_lease_unlocked()
                return False

    def _pg_writer_lease_ready_unlocked(self) -> bool:
        conn = self._writer_lease_conn
        if conn is None or bool(getattr(conn, "closed", False)):
            return False
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT EXISTS (
                         SELECT 1 FROM pg_locks
                         WHERE locktype='advisory' AND pid=pg_backend_pid()
                           AND classid=%s::oid AND objid=%s::oid AND granted
                       )""",
                    self._WRITER_LEASE_KEY,
                )
                row = cur.fetchone()
            return bool(row and row[0] is True)
        except Exception:  # noqa: BLE001 - broken lease session fails closed
            return False

    def _claim_neo_writer_fence_unlocked(self, token: str) -> int | None:
        ts = datetime.now(timezone.utc).isoformat()

        @unit_of_work(timeout=self._WRITER_FENCE_QUERY_TIMEOUT_SECONDS)
        def _claim(tx):
            return tx.run(
                """MERGE (lease:RuntimeWriterLease {name:$lease_name})
                   SET lease._writer_fence_cas=
                       coalesce(lease._writer_fence_cas,0)+0,
                       lease.generation=coalesce(lease.generation,0)+1,
                       lease.owner_token=$owner_token,
                       lease.acquired_at=$ts,
                   lease.released_at=null
                   RETURN lease.owner_token AS owner_token,
                          lease.generation AS generation""",
                lease_name=self._WRITER_FENCE_NAME,
                owner_token=token,
                ts=ts,
            ).data()

        with self._neo.session() as session:
            rows = session.execute_write(_claim)
        if (
            len(rows) != 1
            or rows[0].get("owner_token") != token
            or type(rows[0].get("generation")) is not int
            or rows[0]["generation"] < 1
        ):
            return None
        return rows[0]["generation"]

    def _neo_writer_fence_ready_unlocked(self) -> bool:
        token = self._writer_fence_token
        generation = self._writer_fence_generation
        if (
            not isinstance(token, str)
            or not token
            or type(generation) is not int
            or generation < 1
        ):
            return False
        try:
            with self._neo.session() as session:
                rows = session.run(
                    Query("""MATCH (lease:RuntimeWriterLease {
                           name:$lease_name, owner_token:$owner_token,
                           generation:$generation})
                       RETURN lease.owner_token AS owner_token,
                              lease.generation AS generation""",
                          timeout=self._WRITER_FENCE_QUERY_TIMEOUT_SECONDS),
                    lease_name=self._WRITER_FENCE_NAME,
                    owner_token=token,
                    generation=generation,
                ).data()
            return rows == [{"owner_token": token, "generation": generation}]
        except Exception:  # noqa: BLE001 - unreadable fence is no authority
            return False

    def _writer_lease_ready_unlocked(self) -> bool:
        return (
            self._pg_writer_lease_ready_unlocked()
            and self._neo_writer_fence_ready_unlocked()
        )

    def writer_lease_ready(self) -> bool:
        """O(1) live proof that this process still owns global write authority."""

        with self._writer_lease_lock:
            return self._writer_lease_ready_unlocked()

    def writer_lease_public_projection(self) -> dict[str, Any] | None:
        """Return the current public lease binding without exposing its token."""

        with self._writer_lease_lock:
            if not self._writer_lease_ready_unlocked():
                return None
            token = self._writer_fence_token
            generation = self._writer_fence_generation
            backend_pid = self._writer_pg_backend_pid
            if not (
                isinstance(token, str)
                and token
                and type(generation) is int
                and generation >= 1
                and type(backend_pid) is int
                and backend_pid >= 1
            ):
                return None
            return {
                "lease_id": self._WRITER_FENCE_NAME,
                "owner_token_sha256": hashlib.sha256(
                    token.encode("ascii")
                ).hexdigest(),
                "generation": generation,
                "postgresql_backend_pid": backend_pid,
                "postgresql_advisory_key": list(self._WRITER_LEASE_KEY),
            }

    @contextmanager
    def writer_authority(self, *, acquire: bool) -> Iterable[bool]:
        """Hold local writer authority across an audit or reconciliation seam.

        The returned boolean is a snapshot taken while the same re-entrant lock
        that fences critique mutations remains held.  ``acquire=True`` elects
        this replica first; ``False`` only accepts already-held authority.
        The lease is intentionally retained after a successful context.
        """

        with self._writer_lease_lock:
            ready = (
                self.acquire_writer_lease()
                if acquire
                else self.writer_lease_ready()
            )
            try:
                yield ready
            except BaseException:
                # An audit/reconciliation exception means this process did not
                # establish a publishable authority state.  Do not strand the
                # global election lease and starve a healthy replica.
                self._close_writer_lease_unlocked()
                raise

    def release_writer_lease(self) -> None:
        """Relinquish mutation authority after a local contract invalidation."""

        self._close_writer_lease()

    def _close_writer_lease_unlocked(self) -> None:
        conn = self._writer_lease_conn
        token = self._writer_fence_token
        generation = self._writer_fence_generation
        self._writer_lease_conn = None
        self._writer_pg_backend_pid = None
        self._writer_fence_token = None
        self._writer_fence_generation = None
        if (
            isinstance(token, str)
            and token
            and type(generation) is int
            and generation >= 1
        ):
            try:
                ts = datetime.now(timezone.utc).isoformat()

                @unit_of_work(timeout=self._WRITER_FENCE_QUERY_TIMEOUT_SECONDS)
                def _revoke(tx):
                    return tx.run(
                        """MATCH (lease:RuntimeWriterLease {
                               name:$lease_name, owner_token:$owner_token,
                               generation:$generation})
                           SET lease._writer_fence_cas=
                               coalesce(lease._writer_fence_cas,0)+0,
                               lease.released_at=$ts
                           REMOVE lease.owner_token
                           RETURN count(lease) AS revoked""",
                        lease_name=self._WRITER_FENCE_NAME,
                        owner_token=token,
                        generation=generation,
                        ts=ts,
                    ).data()

                with self._neo.session() as session:
                    session.execute_write(_revoke)
            except Exception as exc:  # noqa: BLE001 - local authority is still cleared
                self._logger.warning(
                    "runtime writer fence revocation failed closed: %s",
                    type(exc).__name__,
                )
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    def _close_writer_lease(self) -> None:
        with self._writer_lease_lock:
            self._close_writer_lease_unlocked()

    @staticmethod
    def _insert_history(
        cur: Any,
        tree: str,
        op: str,
        node_tag: str | None,
        payload_json: str,
        event_id: str | None,
    ) -> tuple[int | None, str | None, str | None]:
        if not isinstance(payload_json, str):
            raise HistoryEventConflict("history payload must be canonical JSON text")
        try:
            payload = json.loads(payload_json)
            payload_json = validate_history_record(
                tree, op, node_tag, payload, event_id
            )
        except (TypeError, ValueError, UnicodeError) as exc:
            raise HistoryEventConflict(
                "history record is not PostgreSQL-safe canonical JSON"
            ) from exc

        if event_id is None:
            cur.execute(
                "INSERT INTO public.history(tree, op, node_tag, payload) "
                "VALUES (%s,%s,%s,%s)",
                (tree, op, node_tag, payload_json),
            )
            return None, None, None

        expected_stable_id: str | None = None
        if op == "critique":
            arg_id = payload.get("arg_id") if isinstance(payload, dict) else None
            if (
                not isinstance(arg_id, str)
                or not arg_id
                or "/" in arg_id
            ):
                raise HistoryEventConflict(
                    "critique history payload lacks an unambiguous arg_id"
                )
            expected_stable_id = history_event_id(
                tree, "critique", f"{tree}/{arg_id}"
            )
            if event_id.startswith("he-") and event_id != expected_stable_id:
                raise HistoryEventConflict(
                    "critique history stable id does not bind its logical argument identity"
                )

        lock_keys = set(history_advisory_lock_keys(
            event_id, tree, op, node_tag, payload_json
        ))
        if expected_stable_id is not None:
            lock_keys.update(history_advisory_lock_keys(
                expected_stable_id, tree, op, node_tag, payload_json
            ))
        for lock_key in sorted(lock_keys):
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (lock_key,))

        if op == "critique":
            candidate_sql = (
                "SELECT id, event_id, "
                "tree=%s AND op=%s "
                "AND node_tag IS NOT DISTINCT FROM %s "
                "AND payload=%s::jsonb AS exact_content "
                "FROM public.history "
                "WHERE event_id=%s OR "
                "(tree=%s AND op='critique' AND payload->>'arg_id'=%s) "
                "ORDER BY id"
            )
            candidate_params = (
                tree,
                op,
                node_tag,
                payload_json,
                event_id,
                tree,
                arg_id,
            )
            claim_sql = (
                "SELECT h.id, h.event_id, "
                "h.tree=%s AND h.op=%s "
                "AND h.node_tag IS NOT DISTINCT FROM %s "
                "AND h.payload=%s::jsonb AS exact_content "
                "FROM public.history_event_claims b "
                "JOIN public.history h ON h.id=b.history_id "
                "WHERE b.stable_event_id=%s"
            )
            claim_params = (
                tree,
                op,
                node_tag,
                payload_json,
                expected_stable_id,
            )
            cur.execute(claim_sql, claim_params)
            existing_claims = list(cur.fetchall())
            if len(existing_claims) > 1 or any(
                len(row) != 3 or row[2] is not True
                for row in existing_claims
            ):
                raise HistoryEventConflict(
                    f"critique event claim {expected_stable_id!r} is conflicting"
                )

            cur.execute(candidate_sql, candidate_params)
            candidates = list(cur.fetchall())
            if len(candidates) > 1 or any(
                len(row) != 3 or row[2] is not True for row in candidates
            ):
                raise HistoryEventConflict(
                    f"critique history identity {tree}/{arg_id} is duplicated or conflicting"
                )

            if not candidates:
                try:
                    cur.execute(
                        "INSERT INTO public.history(tree, op, node_tag, payload, event_id) "
                        "VALUES (%s,%s,%s,%s,%s) "
                        "ON CONFLICT (event_id) WHERE event_id IS NOT NULL DO NOTHING",
                        # A legacy ob-* is an outbox alias, not the durable
                        # critique identity.  New projections must satisfy the
                        # migrated he-* constraint; an existing legacy row is
                        # still adopted in place by the candidate path above.
                        (tree, op, node_tag, payload_json, expected_stable_id),
                    )
                except PgIntegrityError as exc:
                    raise HistoryEventConflict(
                        "critique history logical identity violated uniqueness"
                    ) from exc
                cur.execute(candidate_sql, candidate_params)
                candidates = list(cur.fetchall())

            if (
                len(candidates) != 1
                or len(candidates[0]) != 3
                or candidates[0][2] is not True
            ):
                raise HistoryEventConflict(
                    f"critique history identity {tree}/{arg_id} failed exact materialization"
                )
            row_id, bound_event_id, _ = candidates[0]
            if bound_event_id not in (None, expected_stable_id) and not (
                isinstance(bound_event_id, str)
                and bound_event_id.startswith("ob-")
            ):
                raise HistoryEventConflict(
                    f"critique history identity is bound to unexpected event {bound_event_id!r}"
                )
            if existing_claims and existing_claims[0][0] != row_id:
                raise HistoryEventConflict(
                    "critique stable event is already claimed by another history row"
                )
            try:
                cur.execute(
                    "INSERT INTO public.history_event_claims(stable_event_id, history_id) "
                    "VALUES (%s,%s) ON CONFLICT (stable_event_id) DO NOTHING",
                    (expected_stable_id, row_id),
                )
            except PgIntegrityError as exc:
                raise HistoryEventConflict(
                    "critique history row is already claimed by another stable event"
                ) from exc

            cur.execute(candidate_sql, candidate_params)
            final_rows = list(cur.fetchall())
            if (
                len(final_rows) != 1
                or len(final_rows[0]) != 3
                or final_rows[0][2] is not True
                or final_rows[0][0] != row_id
            ):
                raise HistoryEventConflict(
                    f"critique history identity {tree}/{arg_id} failed exact readback"
                )
            cur.execute(claim_sql, claim_params)
            final_claims = list(cur.fetchall())
            if (
                len(final_claims) != 1
                or len(final_claims[0]) != 3
                or final_claims[0][0] != row_id
                or final_claims[0][2] is not True
            ):
                raise HistoryEventConflict(
                    f"critique event claim {expected_stable_id!r} failed exact readback"
                )
            return row_id, bound_event_id, expected_stable_id

        try:
            cur.execute(
                "INSERT INTO public.history(tree, op, node_tag, payload, event_id) "
                "VALUES (%s,%s,%s,%s,%s) "
                "ON CONFLICT (event_id) WHERE event_id IS NOT NULL DO NOTHING",
                (tree, op, node_tag, payload_json, event_id),
            )
        except PgIntegrityError as exc:
            raise HistoryEventConflict(
                f"history event id {event_id!r} violated uniqueness"
            ) from exc
        cur.execute(
            "SELECT tree=%s AND op=%s "
            "AND node_tag IS NOT DISTINCT FROM %s "
            "AND payload=%s::jsonb "
            "FROM public.history WHERE event_id=%s",
            (tree, op, node_tag, payload_json, event_id),
        )
        row = cur.fetchone()
        if row is None or len(row) != 1 or row[0] is not True:
            raise HistoryEventConflict(
                f"history event id {event_id!r} is absent or bound to different content"
            )
        return None, event_id, event_id

    def _mark_outbox_applied(
        self,
        event_id: str,
        tree: str,
        op: str,
        node_tag: str | None,
        payload_json: str,
        projection: tuple[int | None, str | None, str | None] | None = None,
    ) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        row_event_id = projection[1] if projection is not None else None
        stable_event_id = projection[2] if projection is not None else None
        current_adopted = (
            op == "critique"
            and isinstance(stable_event_id, str)
            and stable_event_id.startswith("he-")
            and event_id.startswith("ob-")
        )
        legacy_ids = sorted({
            candidate
            for candidate in (row_event_id,)
            if isinstance(candidate, str)
            and candidate.startswith("ob-")
            and candidate != event_id
        })
        ids = [event_id, *legacy_ids]
        snapshots = self.kg(
            "MATCH (o:OutboxEntry) WHERE o.id IN $ids "
            "RETURN o.id AS id, o.tree AS tree, o.op AS op, "
            "o.node_tag AS node_tag, o.payload AS payload, "
            "o.status AS status, o.created_at AS created_at, "
            "o.reason AS reason, o.applied_at AS applied_at, "
            "o.adopted_by AS adopted_by, o.adopted_at AS adopted_at, "
            "o.receipt_sha AS receipt_sha, o.causal_group AS causal_group, "
            "o.causal_index AS causal_index, o.request_sha256 AS request_sha256, "
            "o.demoted_tag AS demoted_tag, "
            "o.demoted_receipt_sha AS demoted_receipt_sha",
            ids=ids,
        )
        by_id: dict[str, list[dict]] = {outbox_id: [] for outbox_id in ids}
        for row in snapshots or []:
            row_id = row.get("id")
            if row_id in by_id:
                by_id[row_id].append(dict(row))
        try:
            payload_doc = json.loads(payload_json)
            expected_payload = canonical_history_payload(payload_doc)
        except (TypeError, ValueError) as exc:
            raise HistoryEventConflict(
                f"outbox {event_id!r} payload is not canonicalizable JSON"
            ) from exc

        expected: list[dict[str, Any]] = []
        for outbox_id in ids:
            rows = by_id[outbox_id]
            if len(rows) != 1:
                raise HistoryEventConflict(
                    f"outbox {outbox_id!r} is absent or duplicated"
                )
            row = rows[0]
            try:
                _, _, _, _, actual_payload_text = self._validated_outbox_entry(
                    row,
                    require_pending=False,
                )
                actual_payload = canonical_history_payload(json.loads(actual_payload_text))
            except (TypeError, ValueError) as exc:
                raise HistoryEventConflict(
                    f"outbox {outbox_id!r} payload is not canonicalizable JSON"
                ) from exc
            same_tag = row.get("node_tag") == node_tag
            if (
                row.get("tree") != tree
                or row.get("op") != op
                or not same_tag
                or actual_payload != expected_payload
            ):
                raise HistoryEventConflict(
                    f"outbox {outbox_id!r} immutable binding mismatch"
                )
            desired_status = (
                "adopted"
                if outbox_id in legacy_ids or (
                    outbox_id == event_id and current_adopted
                )
                else "applied"
            )
            expected.append({
                "id": outbox_id,
                "tree": tree,
                "op": op,
                "node_tag": node_tag,
                "payload": row["payload"],
                "canonical_payload": actual_payload,
                "reason": row["reason"],
                "created_at": row["created_at"],
                "receipt_sha": row.get("receipt_sha"),
                "causal_group": row.get("causal_group"),
                "causal_index": row.get("causal_index"),
                "request_sha256": row.get("request_sha256"),
                "demoted_tag": row.get("demoted_tag"),
                "demoted_receipt_sha": row.get("demoted_receipt_sha"),
                "desired_status": desired_status,
            })

        argument_required = (
            op == "critique"
            and isinstance(stable_event_id, str)
            and stable_event_id.startswith("he-")
        )
        if argument_required:
            self._require_stable_argument_binding(
                event_id, tree, op, node_tag, payload_json
            )
        argument = {
            key: payload_doc.get(key) if isinstance(payload_doc, dict) else None
            for key in ("arg_id", "by", "kind", "body", "attacks")
        }

        transition_query = (
            "OPTIONAL MATCH (lock_tree:LakatosTree {name:$arg_tree}) "
            "WITH [t IN collect(lock_tree) WHERE t IS NOT NULL] AS lock_trees "
            "FOREACH (t IN CASE WHEN $argument_required AND size(lock_trees)=1 "
            "                   THEN lock_trees ELSE [] END | "
            "  SET t._argument_cas=coalesce(t._argument_cas,0)+0) "
            "WITH lock_trees "
            "UNWIND $expected AS exp "
            "OPTIONAL MATCH (o:OutboxEntry {id:exp.id}) "
            "WITH lock_trees, exp, [n IN collect(o) WHERE n IS NOT NULL] AS nodes "
            "WITH lock_trees, collect({exp:exp, nodes:nodes}) AS groups "
            "WITH groups, CASE WHEN $argument_required THEN "
            "  size(lock_trees)=1 "
            "  AND COUNT { MATCH (a:Argument {id:$arg_full}) }=1 "
            "  AND COUNT { MATCH (owner)-[:HAS_ARGUMENT]->"
            "      (a:Argument {id:$arg_full}) }=1 "
            "  AND COUNT { MATCH (t:LakatosTree {name:$arg_tree})-[:HAS_NODE]->"
            "      (e {tag:$arg_tag})-[:HAS_ARGUMENT]->"
            "      (a:Argument:LakatosArgument {id:$arg_full}) "
            "    WHERE a.tree_name=$arg_tree AND a.local_id=$arg_id "
            "      AND a.by=$arg_by AND a.kind=$arg_kind AND a.body=$arg_body "
            "      AND a.attacks=$arg_attacks AND a.at IS NOT NULL }=1 "
            "ELSE true END AS argument_valid "
            "WITH groups, argument_valid, all(g IN groups WHERE size(g.nodes)=1 "
            "  AND all(o IN g.nodes WHERE o.tree=g.exp.tree AND o.op=g.exp.op "
            "    AND ((o.node_tag=g.exp.node_tag) "
            "         OR (o.node_tag IS NULL AND g.exp.node_tag IS NULL)) "
            "    AND (o.payload=g.exp.payload "
            "         OR o.payload=g.exp.canonical_payload) "
            "    AND o.reason=g.exp.reason AND o.created_at=g.exp.created_at "
            "    AND (coalesce(o.receipt_sha=g.exp.receipt_sha,false) "
            "         OR (o.receipt_sha IS NULL AND g.exp.receipt_sha IS NULL)) "
            "    AND (coalesce(o.causal_group=g.exp.causal_group,false) "
            "         OR (o.causal_group IS NULL AND g.exp.causal_group IS NULL)) "
            "    AND (coalesce(o.causal_index=g.exp.causal_index,false) "
            "         OR (o.causal_index IS NULL AND g.exp.causal_index IS NULL)) "
            "    AND (coalesce(o.request_sha256=g.exp.request_sha256,false) "
            "         OR (o.request_sha256 IS NULL AND g.exp.request_sha256 IS NULL)) "
            "    AND (coalesce(o.demoted_tag=g.exp.demoted_tag,false) "
            "         OR (o.demoted_tag IS NULL AND g.exp.demoted_tag IS NULL)) "
            "    AND (coalesce(o.demoted_receipt_sha=g.exp.demoted_receipt_sha,false) "
            "         OR (o.demoted_receipt_sha IS NULL "
            "             AND g.exp.demoted_receipt_sha IS NULL)) "
            "    AND ((g.exp.desired_status='applied' "
            "          AND ((o.status='pending' AND o.applied_at IS NULL) "
            "               OR (o.status='applied' AND o.applied_at IS NOT NULL))) "
            "      OR (g.exp.desired_status='adopted' "
            "          AND ((o.status='pending' AND o.applied_at IS NULL) "
            "               OR (o.status='applied' AND o.applied_at IS NOT NULL) "
            "               OR (o.status='adopted' AND o.adopted_by=$stable_id "
            "                   AND o.adopted_at IS NOT NULL)))))) AS outbox_prevalid "
            "WITH groups, argument_valid, "
            "     argument_valid AND outbox_prevalid AS prevalid "
            "FOREACH (g IN CASE WHEN prevalid THEN groups ELSE [] END | "
            "  FOREACH (o IN g.nodes | "
            "    SET o.status=g.exp.desired_status, "
            "        o.payload=g.exp.canonical_payload, "
            "        o.applied_at=CASE WHEN g.exp.desired_status='applied' "
            "                          THEN coalesce(o.applied_at,$ts) "
            "                          ELSE o.applied_at END, "
            "        o.adopted_by=CASE WHEN g.exp.desired_status='adopted' "
            "                          THEN $stable_id ELSE o.adopted_by END, "
            "        o.adopted_at=CASE WHEN g.exp.desired_status='adopted' "
            "                          THEN coalesce(o.adopted_at,$ts) "
            "                          ELSE o.adopted_at END)) "
            "WITH groups, prevalid, argument_valid "
            "RETURN prevalid, argument_valid, [g IN groups | g.exp.id] AS ids, "
            "all(g IN groups WHERE size(g.nodes)=1 "
            "  AND all(o IN g.nodes WHERE o.tree=g.exp.tree AND o.op=g.exp.op "
            "    AND ((o.node_tag=g.exp.node_tag) "
            "         OR (o.node_tag IS NULL AND g.exp.node_tag IS NULL)) "
            "    AND o.payload=g.exp.canonical_payload AND o.reason=g.exp.reason "
            "    AND o.created_at=g.exp.created_at "
            "    AND (coalesce(o.receipt_sha=g.exp.receipt_sha,false) "
            "         OR (o.receipt_sha IS NULL AND g.exp.receipt_sha IS NULL)) "
            "    AND (coalesce(o.causal_group=g.exp.causal_group,false) "
            "         OR (o.causal_group IS NULL AND g.exp.causal_group IS NULL)) "
            "    AND (coalesce(o.causal_index=g.exp.causal_index,false) "
            "         OR (o.causal_index IS NULL AND g.exp.causal_index IS NULL)) "
            "    AND (coalesce(o.request_sha256=g.exp.request_sha256,false) "
            "         OR (o.request_sha256 IS NULL AND g.exp.request_sha256 IS NULL)) "
            "    AND (coalesce(o.demoted_tag=g.exp.demoted_tag,false) "
            "         OR (o.demoted_tag IS NULL AND g.exp.demoted_tag IS NULL)) "
            "    AND (coalesce(o.demoted_receipt_sha=g.exp.demoted_receipt_sha,false) "
            "         OR (o.demoted_receipt_sha IS NULL "
            "             AND g.exp.demoted_receipt_sha IS NULL)) "
            "    AND o.status=g.exp.desired_status "
            "    AND ((g.exp.desired_status='applied' AND o.applied_at IS NOT NULL) "
            "      OR (g.exp.desired_status='adopted' "
            "          AND o.adopted_by=$stable_id AND o.adopted_at IS NOT NULL)))) "
            "AS postvalid"
        )
        transition_params = dict(
            expected=expected,
            stable_id=stable_event_id,
            argument_required=argument_required,
            arg_tree=tree,
            arg_tag=node_tag,
            arg_full=f"{tree}/{argument.get('arg_id')}",
            arg_id=argument.get("arg_id"),
            arg_by=argument.get("by"),
            arg_kind=argument.get("kind"),
            arg_body=argument.get("body"),
            arg_attacks=argument.get("attacks"),
            ts=ts,
        )
        tx_rows = self._history_kg_tx([
            (transition_query, transition_params)
        ])
        result = tx_rows[0] if tx_rows else []
        if (
            len(result) != 1
            or result[0].get("prevalid") is not True
            or result[0].get("argument_valid") is not True
            or result[0].get("postvalid") is not True
            or sorted(result[0].get("ids") or []) != sorted(ids)
        ):
            raise HistoryEventConflict(
                f"outbox {event_id!r} state transition failed exact readback"
            )

    @staticmethod
    def _timestamp_present(value: Any) -> bool:
        if hasattr(value, "iso_format"):
            value = value.iso_format()
        if not isinstance(value, str) or not value:
            return False
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        return parsed.tzinfo is not None

    @classmethod
    def _validated_outbox_entry(
        cls,
        entry: dict,
        *,
        require_pending: bool,
    ) -> tuple[str, str, str, str | None, str]:
        event_id = entry.get("id")
        tree = entry.get("tree")
        op = entry.get("op")
        node_tag = entry.get("node_tag")
        payload_text = entry.get("payload")
        status = entry.get("status")
        reason = entry.get("reason")
        label = event_id if isinstance(event_id, str) else repr(event_id)
        if not isinstance(event_id, str) or not re.fullmatch(
            r"(?:ob-[A-Za-z0-9._:-]+|ph-[A-Za-z0-9._:-]+|he-[0-9a-f]{64})",
            event_id,
        ):
            raise HistoryEventConflict(f"outbox {label} has an invalid id")
        if not isinstance(payload_text, str):
            raise HistoryEventConflict(f"outbox {event_id!r} has a non-text payload")
        try:
            decoded = json.loads(payload_text)
            canonical = validate_history_record(
                tree, op, node_tag, decoded, event_id
            )
        except (TypeError, ValueError, UnicodeError) as exc:
            raise HistoryEventConflict(
                f"outbox {event_id!r} is not PostgreSQL-safe canonical JSON"
            ) from exc

        if not cls._timestamp_present(entry.get("created_at")):
            raise HistoryEventConflict(f"outbox {event_id!r} lacks creation provenance")
        if not isinstance(reason, str) or not reason:
            raise HistoryEventConflict(f"outbox {event_id!r} lacks a reason")

        if event_id.startswith("he-"):
            arg_id = decoded.get("arg_id") if isinstance(decoded, dict) else None
            valid_stable = (
                op == "critique"
                and isinstance(arg_id, str)
                and bool(arg_id)
                and "/" not in arg_id
                and isinstance(node_tag, str)
                and bool(node_tag)
                and reason == "critique_commit_intent"
                and event_id == history_event_id(
                    tree, "critique", f"{tree}/{arg_id}"
                )
            )
            if not valid_stable:
                raise HistoryEventConflict(
                    f"outbox {event_id!r} lacks exact critique intent provenance"
                )

        state_valid = (
            status == "pending"
            and entry.get("applied_at") is None
            and entry.get("adopted_at") is None
            and entry.get("adopted_by") is None
        ) or (
            status == "applied"
            and cls._timestamp_present(entry.get("applied_at"))
            and entry.get("adopted_at") is None
            and entry.get("adopted_by") is None
        ) or (
            status == "adopted"
            and event_id.startswith("ob-")
            and cls._timestamp_present(entry.get("adopted_at"))
            and isinstance(entry.get("adopted_by"), str)
            and re.fullmatch(r"he-[0-9a-f]{64}", entry["adopted_by"])
            is not None
        )
        if not state_valid or (require_pending and status != "pending"):
            raise HistoryEventConflict(f"outbox {event_id!r} has an invalid state")
        return event_id, tree, op, node_tag, canonical

    def _require_stable_argument_binding(
        self,
        event_id: str,
        tree: str,
        op: str,
        node_tag: str | None,
        payload_json: str,
    ) -> None:
        try:
            payload = json.loads(payload_json)
        except (TypeError, ValueError) as exc:
            raise HistoryEventConflict("stable outbox payload is not JSON") from exc
        arg_id = payload.get("arg_id") if isinstance(payload, dict) else None
        if op != "critique":
            if event_id.startswith("he-"):
                raise HistoryEventConflict("stable outbox is not a critique argument")
            return
        required = {
            key: payload.get(key) if isinstance(payload, dict) else None
            for key in ("arg_id", "by", "kind", "body", "attacks")
        }
        if not all(isinstance(value, str) for value in required.values()):
            raise HistoryEventConflict("critique outbox lacks immutable Argument content")
        if set(payload) != {"arg_id", "attacks", "by", "kind", "body"}:
            raise HistoryEventConflict("critique outbox payload shape is not exact")
        arg_id = required["arg_id"]
        if not arg_id or "/" in arg_id:
            raise HistoryEventConflict("critique outbox has an invalid argument identity")
        expected_stable = history_event_id(tree, "critique", f"{tree}/{arg_id}")
        if event_id.startswith("he-") and event_id != expected_stable:
            raise HistoryEventConflict("stable outbox id does not bind its Argument")
        rows = self.kg(
            "RETURN "
            "COUNT { MATCH (a:Argument {id:$arg_full}) } AS arguments, "
            "COUNT { MATCH (owner)-[:HAS_ARGUMENT]->"
            "(a:Argument {id:$arg_full}) } AS owners, "
            "COUNT { MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->"
            "(e {tag:$tag})-[:HAS_ARGUMENT]->"
            "(a:Argument:LakatosArgument {id:$arg_full}) "
            "WHERE a.tree_name=$tree AND a.local_id=$arg_id "
            "AND a.by=$by AND a.kind=$kind AND a.body=$body "
            "AND a.attacks=$attacks AND a.at IS NOT NULL } AS exact_bindings",
            tree=tree,
            tag=node_tag,
            arg_full=f"{tree}/{arg_id}",
            arg_id=arg_id,
            by=required["by"],
            kind=required["kind"],
            body=required["body"],
            attacks=required["attacks"],
        )
        if rows != [{"arguments": 1, "owners": 1, "exact_bindings": 1}]:
            raise HistoryEventConflict(
                f"stable outbox {event_id!r} lacks its exact Argument binding"
            )

    def _record_pending_outbox(
        self,
        *,
        event_id: str,
        tree: str,
        op: str,
        node_tag: str | None,
        payload_json: str,
        ts: str,
        reason: str,
    ) -> None:
        if event_id.startswith("he-"):
            reason = "critique_commit_intent"
            self._require_stable_argument_binding(
                event_id, tree, op, node_tag, payload_json
            )
        params = dict(
            id=event_id,
            tree=tree,
            op=op,
            tag=node_tag,
            payload=payload_json,
            ts=ts,
            reason=reason,
        )
        try:
            results = self._history_kg_tx(GuardedKgOps([
                (
                    "OPTIONAL MATCH (t:LakatosTree {name:$tree}) "
                    "OPTIONAL MATCH (prior:OutboxEntry {id:$id}) "
                    "WITH t, [o IN collect(prior) WHERE o IS NOT NULL] AS priors "
                    "WITH t, priors, CASE "
                    "WHEN size(priors)>1 THEN 'conflict' "
                    "WHEN size(priors)=1 AND coalesce("
                    "priors[0].tree=$tree AND priors[0].op=$op "
                    "AND ((priors[0].node_tag=$tag) OR "
                    "     (priors[0].node_tag IS NULL AND $tag IS NULL)) "
                    "AND priors[0].payload=$payload "
                    "AND priors[0].created_at IS NOT NULL "
                    "AND ((priors[0].status='pending' AND priors[0].applied_at IS NULL) "
                    "OR (priors[0].status='applied' AND priors[0].applied_at IS NOT NULL)), "
                    "false) THEN 'existing' "
                    "WHEN size(priors)=1 THEN 'conflict' "
                    "WHEN t IS NULL THEN 'missing_tree' ELSE 'create' END AS guard_status "
                    "FOREACH (_ IN CASE WHEN guard_status='create' THEN [1] ELSE [] END | "
                    "SET t._tree_write_cas=coalesce(t._tree_write_cas,0)+0) "
                    "RETURN guard_status",
                    params,
                ),
                (
                    "MERGE (o:OutboxEntry {id:$id}) "
                    "ON CREATE SET o.tree=$tree, o.op=$op, o.node_tag=$tag, "
                    "o.payload=$payload, o.status='pending', o.created_at=$ts, "
                    "o.reason=$reason "
                    "RETURN o.id AS id, o.tree AS tree, o.op AS op, "
                    "o.node_tag AS node_tag, o.payload AS payload, "
                    "o.status AS status, o.created_at AS created_at, "
                    "o.reason AS reason, o.applied_at AS applied_at, "
                    "o.adopted_by AS adopted_by, o.adopted_at AS adopted_at",
                    params,
                ),
            ], guard_field="guard_status", guard_expected={"create", "existing"}))
        except WriterFenceLost:
            # Election loss is not an immutable-identity conflict.  The caller
            # invalidates readiness and reports a pending projection; it must
            # never disguise lease loss as corrupt durable content.
            raise
        except KgTxGuardFailed as exc:
            raise HistoryEventConflict(
                f"outbox {event_id!r} tree lock or immutable binding rejected"
            ) from exc
        rows = results[1] if len(results) > 1 else []
        if len(rows) != 1:
            raise HistoryEventConflict(
                f"outbox {event_id!r} merge did not return one exact node"
            )
        row = dict(rows[0])
        _, actual_tree, actual_op, actual_tag, actual_payload = (
            self._validated_outbox_entry(row, require_pending=False)
        )
        expected_payload = canonical_history_payload(json.loads(payload_json))
        if (
            actual_tree != tree
            or actual_op != op
            or actual_tag != node_tag
            or actual_payload != expected_payload
        ):
            raise HistoryEventConflict(
                f"outbox {event_id!r} immutable binding mismatch"
            )

    @classmethod
    def _set_history_transaction_timeouts(cls, cur: Any) -> None:
        """Bound advisory-lock and statement waits inside one history tx."""

        cur.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (f"{cls._HISTORY_STATEMENT_TIMEOUT_MS}ms",),
        )
        cur.execute(
            "SELECT set_config('lock_timeout', %s, true)",
            (f"{cls._HISTORY_LOCK_TIMEOUT_MS}ms",),
        )

    def hist(
        self,
        tree: str,
        op: str,
        node_tag: str | None = None,
        payload: dict | None = None,
        *,
        event_id: str | None = None,
    ) -> bool:
        if op == "critique" and event_id is None:
            raise HistoryEventConflict(
                "critique history requires a caller-stable event_id"
            )
        # ROB-1: 이력(PG)=best-effort audit, KG=truth. KG 커밋 후 PG 다운이 mutation 을 503 으로
        # 되돌리면 그래프-이력 분기가 더 나빠지므로 PG 연결오류는 mutation 을 막지 않는다.
        # B1(override 2026-06-21): 단 *조용히 잃지 않는다* — PG 실패 시 KG OutboxEntry(정본)에 기록하고
        #   reconcile_outbox 가 멱등 재적용한다. KG=truth/PG=best-effort 불변 유지하되 발산을 auditable 화.
        payload = {} if payload is None else payload
        supplied_event_id = event_id
        # Even best-effort events receive a per-invocation projection identity.
        # If commit acknowledgement is lost, the same identity is written to the
        # KG outbox and PostgreSQL replay converges instead of appending a second
        # row beside the ambiguously committed NULL-event row.
        # ``ph-*`` is a projection-local idempotency identity. A healthy
        # append needs no Neo outbox, while an ambiguous/transient failure may
        # materialize the same id as a recoverable OutboxEntry.
        effective_event_id = event_id or f"ph-history-{uuid4().hex}"
        try:
            pj = validate_history_record(
                tree, op, node_tag, payload, effective_event_id
            )
        except (TypeError, ValueError, UnicodeError) as exc:
            raise HistoryEventConflict("history record is not PostgreSQL-safe") from exc
        try:
            pg_scope = (
                self._writer_fenced_pg
                if self._writer_scope_depth.get() > 0
                else self.pg
            )
            with pg_scope() as c, c.cursor() as cur:
                self._set_history_transaction_timeouts(cur)
                projection = self._insert_history(
                    cur, tree, op, node_tag, pj, effective_event_id
                )
        except HistoryEventConflict:
            self._signal_history_divergence("runtime.history_projection.conflict")
            raise
        except (PgOperationalError, PgInterfaceError, PgPoolError) as e:
            ts = datetime.now(timezone.utc).isoformat()
            oid = effective_event_id
            try:
                self._record_pending_outbox(
                    event_id=oid,
                    tree=tree,
                    op=op,
                    node_tag=node_tag,
                    payload_json=pj,
                    ts=ts,
                    reason=type(e).__name__,
                )
                self._logger.warning(
                    "hist PG 실패 → OutboxEntry %s 기록(reconcile 대기, 이력 보존): %s", oid, type(e).__name__)
            except HistoryEventConflict:
                self._signal_history_divergence(
                    "runtime.history_outbox.conflict"
                )
                raise
            except Exception as ke:   # noqa: BLE001 — KG 도 다운 = 진짜 best-effort 한계(둘 다 유실)
                self._signal_history_divergence(
                    "runtime.history_projection.unrecoverable"
                )
                self._logger.error(
                    "hist PG+KG 동시 실패(이력 유실): %s / %s", type(e).__name__, type(ke).__name__)
                return False
            # Persist the recovery intent while the cross-store election is
            # still held, then revoke readiness.  Invalidating first releases
            # the very lease required to record the outbox.
            self._signal_history_divergence(
                "runtime.history_projection.pending"
            )
            return False
        else:
            if supplied_event_id is not None:
                try:
                    self._mark_outbox_applied(
                        supplied_event_id, tree, op, node_tag, pj, projection
                    )
                except HistoryEventConflict:
                    self._signal_history_divergence(
                        "runtime.history_outbox_conflict"
                    )
                    raise
                except Exception as exc:  # noqa: BLE001 — pending intent makes retry safe
                    self._signal_history_divergence(
                        "runtime.history_outbox_mark.pending"
                    )
                    self._logger.warning(
                        "history %s PG 적용 후 outbox applied 표기 실패(reconcile 재시도): %s",
                        supplied_event_id,
                        type(exc).__name__,
                    )
                    return False
            return True

    @classmethod
    def _validated_pending_outbox_entry(
        cls,
        entry: dict,
    ) -> tuple[str, str, str, str | None, str]:
        return cls._validated_outbox_entry(entry, require_pending=True)

    @classmethod
    def _causal_intent_binding(
        cls,
        entry: dict,
    ) -> tuple[str, int, tuple[str, ...]] | None:
        """Validate the receipt-bound test/closure/cycle outbox topology.

        Older best-effort history entries have no causal metadata.  New
        verdict-transaction intents are recognizable by both their durable
        reason and stable id namespace, so deleting the two causal properties
        cannot silently downgrade one into that legacy class.
        """

        event_id, _tree, op, _tag, payload_json = cls._validated_outbox_entry(
            entry,
            require_pending=False,
        )
        reason = entry.get("reason")
        group = entry.get("causal_group")
        index = entry.get("causal_index")
        specs = {
            ("test_result", "test_result_commit_intent"): 0,
            ("question_close", "question_close_commit_intent"): 1,
            ("cycle_result", "cycle_result_commit_intent"): 2,
        }
        stable_namespace = re.fullmatch(
            r"ob-(?:test-result|question-close|cycle-result)-[0-9a-f]{64}",
            event_id,
        ) is not None
        is_new_intent = (
            op in {"test_result", "question_close", "cycle_result"}
            or reason in {item[1] for item in specs}
            or stable_namespace
        )
        if not is_new_intent:
            if group is not None or index is not None:
                raise HistoryEventConflict(
                    f"outbox {event_id!r} has unsupported causal metadata"
                )
            return None
        expected_index = specs.get((op, reason))
        if expected_index is None:
            raise HistoryEventConflict(
                f"outbox {event_id!r} has a mismatched causal intent kind"
            )
        if not (
            isinstance(group, str)
            and re.fullmatch(r"[0-9a-f]{64}", group) is not None
            and type(index) is int
            and index == expected_index
            and entry.get("receipt_sha") == group
            and entry.get("status") in {"pending", "applied"}
        ):
            raise HistoryEventConflict(
                f"outbox {event_id!r} has a malformed causal receipt binding"
            )
        try:
            payload = json.loads(payload_json)
        except (TypeError, ValueError) as exc:
            raise HistoryEventConflict(
                f"outbox {event_id!r} has an invalid causal payload"
            ) from exc
        if not isinstance(payload, dict):
            raise HistoryEventConflict(
                f"outbox {event_id!r} causal payload is not an object"
            )
        test_id = f"ob-test-result-{group}"
        close_id = f"ob-question-close-{group}"
        if index == 0:
            if event_id != test_id or payload.get("receipt_sha") != group:
                raise HistoryEventConflict(
                    f"outbox {event_id!r} does not bind its test receipt"
                )
            dependencies: tuple[str, ...] = ()
        elif index == 1:
            if event_id != close_id or payload.get("receipt_sha") != group:
                raise HistoryEventConflict(
                    f"outbox {event_id!r} does not bind its closure receipt"
                )
            dependencies = (test_id,)
        else:
            suffix = event_id.removeprefix("ob-cycle-result-")
            dependent_ids = payload.get("dependent_history_event_ids")
            if not (
                event_id == f"ob-cycle-result-{suffix}"
                and re.fullmatch(r"[0-9a-f]{64}", suffix) is not None
                and payload.get("cycle_claim") == f"cycle-{suffix}"
                and payload.get("verdict_receipt_sha") == group
                and isinstance(dependent_ids, list)
                and len(dependent_ids) in {1, 2}
                and all(isinstance(item, str) for item in dependent_ids)
                and dependent_ids[0] == test_id
                and (len(dependent_ids) == 1 or dependent_ids[1] == close_id)
            ):
                raise HistoryEventConflict(
                    f"outbox {event_id!r} has an invalid cycle dependency manifest"
                )
            dependencies = tuple(dependent_ids)
        return group, index, dependencies

    def reconcile_outbox(self) -> dict:
        """B1: pending OutboxEntry(KG 정본)를 PG history 에 *멱등* 재적용(ON CONFLICT event_id DO NOTHING).
        KG↔PG 발산 복구 — PG 가 따라잡되 그 따라잡음이 감사가능. 반환 {pending, replayed, replayed_count, ...}."""
        rows = self.kg(
            "MATCH (o:OutboxEntry {status:'pending'}) "
            "RETURN o.id AS id, o.tree AS tree, o.op AS op, "
            "o.node_tag AS node_tag, o.payload AS payload, "
            "o.status AS status, o.created_at AS created_at, "
            "o.reason AS reason, o.applied_at AS applied_at, "
            "o.adopted_by AS adopted_by, o.adopted_at AS adopted_at, "
            "o.causal_group AS causal_group, o.causal_index AS causal_index, "
            "o.receipt_sha AS receipt_sha, o.request_sha256 AS request_sha256 "
            "ORDER BY o.created_at, coalesce(o.causal_group,o.id), "
            "coalesce(o.causal_index,0), o.id")
        plan = plan_reconcile([dict(r) for r in (rows or [])])
        replayed: list[str] = []
        conflicts: list[dict[str, str]] = []
        pg_down = False
        blocked_causal_groups: set[str] = set()
        causal_deferred: list[str] = []
        causal_bindings: dict[str, tuple[str, int, tuple[str, ...]]] = {}
        causal_entry_errors: dict[str, str] = {}
        candidate_causal_groups: set[str] = set()
        candidate_admin_ids: set[str] = set()
        candidate_prediction_ids: set[str] = set()
        candidate_prediction_temporal_ids: set[str] = set()
        candidate_temporal_sidecar_ids: set[str] = set()
        temporal_entry_errors: dict[str, str] = {}
        for entry in plan['to_replay']:
            entry_id = entry.get('id')
            try:
                temporal_kind = classify_temporal_intent(entry)
            except TemporalIntentError as exc:
                if isinstance(entry_id, str):
                    temporal_entry_errors[entry_id] = str(exc)
                temporal_kind = None
            if isinstance(entry_id, str) and temporal_kind == 'commitment':
                candidate_prediction_temporal_ids.add(entry_id)
            if isinstance(entry_id, str) and temporal_kind == 'sidecar':
                candidate_temporal_sidecar_ids.add(entry_id)
            if (
                isinstance(entry_id, str)
                and (
                    entry.get('op') == 'verdict'
                    or
                    re.fullmatch(r'ob-verdict-[0-9a-f]{64}', entry_id)
                    is not None
                    or entry.get('reason') == 'verdict_commit_intent'
                )
            ):
                candidate_admin_ids.add(entry_id)
            if (
                isinstance(entry_id, str)
                and (
                    entry.get('op') == 'prediction_register'
                    or
                    re.fullmatch(
                        r'ob-prediction-register-[0-9a-f]{64}', entry_id
                    ) is not None
                    or entry.get('reason') == 'prediction_register_commit_intent'
                )
            ):
                candidate_prediction_ids.add(entry_id)
            try:
                binding = self._causal_intent_binding(entry)
            except HistoryEventConflict as exc:
                if isinstance(entry_id, str):
                    causal_entry_errors[entry_id] = str(exc)
                group = entry.get('causal_group')
                if isinstance(group, str) and re.fullmatch(r'[0-9a-f]{64}', group):
                    candidate_causal_groups.add(group)
                continue
            if binding is not None:
                causal_bindings[entry_id] = binding
                candidate_causal_groups.add(binding[0])

        chain_index = None
        chain_error: str | None = None
        if (
            candidate_causal_groups
            or candidate_admin_ids
            or candidate_prediction_ids
            or candidate_prediction_temporal_ids
            or candidate_temporal_sidecar_ids
        ):
            try:
                chain_index = validate_receipt_graph(
                    self.kg(RECEIPT_CHAIN_ROWS_CYPHER),
                    self.kg(RECEIPT_IDENTITIES_CYPHER),
                )
            except ReceiptGraphError as exc:
                chain_error = str(exc)

        causal_rows_by_id: dict[str, dict] = {}
        causal_group_rows: dict[str, list[tuple[dict, int, tuple[str, ...]]]] = {}
        causal_group_errors: dict[str, str] = {}
        causal_authority_rows: dict[str, list[dict]] = {}
        if candidate_causal_groups:
            topology_rows = self.kg(
                "MATCH (o:OutboxEntry) WHERE o.causal_group IN $groups "
                "RETURN o.id AS id, o.tree AS tree, o.op AS op, "
                "o.node_tag AS node_tag, o.payload AS payload, "
                "o.status AS status, o.created_at AS created_at, "
                "o.reason AS reason, o.applied_at AS applied_at, "
                "o.adopted_by AS adopted_by, o.adopted_at AS adopted_at, "
                "o.causal_group AS causal_group, o.causal_index AS causal_index, "
                "o.receipt_sha AS receipt_sha, o.request_sha256 AS request_sha256",
                groups=sorted(candidate_causal_groups),
            )
            for raw in topology_rows or []:
                row = dict(raw)
                group = row.get('causal_group')
                try:
                    binding = self._causal_intent_binding(row)
                except HistoryEventConflict as exc:
                    if isinstance(group, str) and group in candidate_causal_groups:
                        causal_group_errors.setdefault(group, str(exc))
                    continue
                if binding is None or binding[0] not in candidate_causal_groups:
                    continue
                event_id = row['id']
                if event_id in causal_rows_by_id:
                    causal_group_errors.setdefault(
                        binding[0], f"duplicate causal outbox id {event_id!r}"
                    )
                    continue
                causal_rows_by_id[event_id] = row
                causal_group_rows.setdefault(binding[0], []).append(
                    (row, binding[1], binding[2])
                )
            authority_rows = self.kg(
                "UNWIND $groups AS group "
                "OPTIONAL MATCH (t:LakatosTree)-[:HAS_NODE]->"
                "(e {current_receipt_sha:group}) "
                "OPTIONAL MATCH (e)-[:HAS_RECEIPT]->"
                "(rec:VerdictReceipt {receipt_sha:group}) "
                "OPTIONAL MATCH (t)-[:HAS_FRONTIER]->"
                "(q:OpenQuestion {name:rec.target_id}) "
                "OPTIONAL MATCH (q)-[:HAS_CLOSURE]->"
                "(closure:QuestionClosure {id:group}) "
                "RETURN group, t.name AS current_tree, e.tag AS current_tag, "
                "e.current_receipt_sha AS current_receipt_sha, "
                "e.verdict AS current_verdict, "
                "e.verdict_source AS current_verdict_source, "
                "e.lakatos_status AS current_lakatos_status, "
                "e.metric_value AS current_metric_value, "
                "rec.receipt_sha AS bound_receipt_sha, "
                "rec.tree AS receipt_tree, rec.tag AS receipt_tag, "
                "rec.target_id AS receipt_target_id, "
                "rec.verdict AS receipt_verdict, "
                "rec.verdict_source AS receipt_verdict_source, "
                "rec.metric_name AS receipt_metric_name, "
                "rec.metric_value AS receipt_metric_value, "
                "rec.novel_confirmed AS receipt_novel_confirmed, "
                "rec.lakatos_status AS receipt_lakatos_status, "
                "rec.judged_at AS receipt_judged_at, "
                "rec.judge_script_sha AS receipt_judge_script_sha, "
                "rec.prev_receipt_sha AS receipt_prev_receipt_sha, "
                "rec.measurement_grade AS receipt_measurement_grade, "
                "rec.engine_rule_sha AS receipt_engine_rule_sha, "
                "rec.comment_sha AS receipt_comment_sha, "
                "rec.replay_status AS receipt_replay_status, "
                "rec.replay_reason AS receipt_replay_reason, "
                "rec.regenerated_metric AS receipt_regenerated_metric, "
                "rec.judge_script_path AS receipt_judge_script_path, "
                "rec.result_path AS receipt_result_path, "
                "rec.result_sha256 AS receipt_result_sha256, "
                "rec.measurement_lock_sha AS receipt_measurement_lock_sha, "
                "rec.source_script_path AS receipt_source_script_path, "
                "rec.source_result_path AS receipt_source_result_path, "
                "rec.history_payload_sha256 AS receipt_history_payload_sha256, "
                "rec.prediction_temporal_commitment_sha256 AS "
                "receipt_prediction_temporal_commitment_sha256, "
                "q.status AS question_state, "
                "q.closed_by AS question_closed_by, "
                "q.closed_events AS question_closed_events, "
                "closure.id AS closure_id, "
                "closure.closed_by AS closure_closed_by, "
                "closure.at AS closure_at, "
                "closure.tree AS closure_tree, "
                "closure.question AS closure_question, "
                "closure.trigger AS closure_trigger, "
                "closure.verdict AS closure_verdict, "
                "closure.receipt_sha AS closure_receipt_sha, "
                "COUNT { MATCH (q)-[:HAS_CLOSURE]->"
                "(:QuestionClosure {id:group})-[:CAUSED_BY]->(rec) } "
                "AS closure_bound_count, "
                "COUNT { MATCH (:QuestionClosure {id:group}) } "
                "AS closure_global_count, "
                "COUNT { MATCH (e)-[:CLOSES_QUESTION]->(q) } "
                "AS closes_rel_count, "
                "head([(e)-[rel:CLOSES_QUESTION]->(q) | rel.receipt_sha]) "
                "AS closes_rel_receipt_sha, "
                "head([(e)-[rel:CLOSES_QUESTION]->(q) | rel.verdict]) "
                "AS closes_rel_verdict, "
                "head([(e)-[rel:CLOSES_QUESTION]->(q) | rel.at]) "
                "AS closes_rel_at",
                groups=sorted(candidate_causal_groups),
            )
            for authority in authority_rows or []:
                group = authority.get('group')
                if isinstance(group, str) and group in candidate_causal_groups:
                    causal_authority_rows.setdefault(group, []).append(
                        dict(authority)
                    )
            for group in candidate_causal_groups:
                members = causal_group_rows.get(group, [])
                indices = [index for _row, index, _deps in members]
                if len(indices) != len(set(indices)):
                    causal_group_errors.setdefault(
                        group, "duplicate causal index in receipt group"
                    )
                    continue
                if not members:
                    causal_group_errors.setdefault(
                        group, "causal receipt group is missing"
                    )
                    continue
                trees = {row.get('tree') for row, _index, _deps in members}
                tags = {row.get('node_tag') for row, _index, _deps in members}
                created = {row.get('created_at') for row, _index, _deps in members}
                if len(trees) != 1 or len(tags) != 1 or len(created) != 1:
                    causal_group_errors.setdefault(
                        group, "causal receipt group provenance diverges"
                    )
                    continue
                authorities = causal_authority_rows.get(group, [])
                if len(authorities) != 1:
                    causal_group_errors.setdefault(
                        group,
                        "causal receipt group lacks exactly one current node authority",
                    )
                    continue
                authority = authorities[0]
                receipt_snapshot = {
                    key: authority.get(f'receipt_{key}')
                    for key in RECEIPT_FIELDS
                }
                receipt_snapshot['receipt_sha'] = authority.get(
                    'bound_receipt_sha'
                )
                current_snapshot = {
                    'current_receipt_sha': authority.get('current_receipt_sha'),
                    'verdict': authority.get('current_verdict'),
                    'verdict_source': authority.get('current_verdict_source'),
                    'lakatos_status': authority.get('current_lakatos_status'),
                    'metric_value': authority.get('current_metric_value'),
                }
                closure_snapshot = {
                    'question_state': authority.get('question_state'),
                    'question_closed_by': authority.get('question_closed_by'),
                    'question_closed_events': authority.get(
                        'question_closed_events'
                    ),
                    'closure_id': authority.get('closure_id'),
                    'closure_closed_by': authority.get('closure_closed_by'),
                    'closure_at': authority.get('closure_at'),
                    'closure_tree': authority.get('closure_tree'),
                    'closure_question': authority.get('closure_question'),
                    'closure_trigger': authority.get('closure_trigger'),
                    'closure_verdict': authority.get('closure_verdict'),
                    'closure_receipt_sha': authority.get('closure_receipt_sha'),
                    'closure_bound': authority.get('closure_bound_count') == 1,
                    'closure_global_count': authority.get(
                        'closure_global_count'
                    ),
                    'closes_rel_count': authority.get('closes_rel_count'),
                    'closes_rel_receipt_sha': authority.get(
                        'closes_rel_receipt_sha'
                    ),
                    'closes_rel_verdict': authority.get('closes_rel_verdict'),
                    'closes_rel_at': authority.get('closes_rel_at'),
                }
                try:
                    validate_verdict_intent_group(
                        tree=authority.get('current_tree'),
                        tag=authority.get('current_tag'),
                        receipt_sha=group,
                        receipt=receipt_snapshot,
                        current=current_snapshot,
                        outboxes=[row for row, _index, _deps in members],
                        closure=closure_snapshot,
                    )
                except VerdictIntentError as exc:
                    causal_group_errors.setdefault(group, str(exc))
                    continue
                scope = (
                    str(authority.get('current_tree')),
                    str(authority.get('current_tag')),
                )
                if chain_error is not None or (
                    chain_index is None
                    or group not in chain_index.ancestors_by_scope.get(
                        scope, frozenset()
                    )
                ):
                    causal_group_errors.setdefault(
                        group,
                        chain_error or 'causal receipt is not in current chain ancestry',
                    )
                    continue
                ids = {row.get('id') for row, _index, _deps in members}
                for row, _index, dependencies in members:
                    if any(dependency not in ids for dependency in dependencies):
                        causal_group_errors.setdefault(
                            group,
                            f"causal predecessor missing for {row.get('id')!r}",
                        )
                        break
                cycle_members = [
                    (row, dependencies)
                    for row, index, dependencies in members if index == 2
                ]
                if cycle_members:
                    _cycle_row, dependencies = cycle_members[0]
                    close_id = f"ob-question-close-{group}"
                    if (close_id in ids) != (close_id in dependencies):
                        causal_group_errors.setdefault(
                            group,
                            "cycle dependency manifest disagrees with closure intent",
                        )
            for event_id, (group, _index, _dependencies) in causal_bindings.items():
                if event_id not in causal_rows_by_id:
                    causal_group_errors.setdefault(
                        group, f"pending causal outbox {event_id!r} is absent from topology"
                    )

        admin_rows_by_id: dict[str, dict] = {}
        admin_entry_errors: dict[str, str] = {}
        if candidate_admin_ids:
            admin_authority_rows = self.kg(
                "UNWIND $ids AS event_id "
                "OPTIONAL MATCH (o:OutboxEntry {id:event_id}) "
                "OPTIONAL MATCH (t:LakatosTree {name:o.tree})-[:HAS_NODE]->"
                "(e {tag:o.node_tag}) "
                "OPTIONAL MATCH (e)-[:HAS_RECEIPT]->"
                "(rec:VerdictReceipt {receipt_sha:o.receipt_sha}) "
                "OPTIONAL MATCH (t)-[:HAS_NODE]->(demoted {tag:o.demoted_tag})"
                "-[:HAS_RECEIPT]->(demoted_rec:VerdictReceipt {"
                "receipt_sha:o.demoted_receipt_sha}) "
                "RETURN event_id, properties(o) AS outbox, "
                "e.current_receipt_sha AS current_receipt_sha, "
                "e.verdict AS current_verdict, "
                "e.verdict_source AS current_verdict_source, "
                "properties(rec) AS receipt, "
                "CASE WHEN demoted IS NULL THEN null ELSE {"
                "tag:demoted.tag, "
                "current_receipt_sha:demoted.current_receipt_sha, "
                "verdict:demoted.verdict, "
                "verdict_source:demoted.verdict_source} END "
                "AS demoted_current, "
                "properties(demoted_rec) AS demoted_receipt",
                ids=sorted(candidate_admin_ids),
            )
            admin_rows_grouped: dict[str, list[dict]] = {}
            for raw in admin_authority_rows or []:
                event_id = raw.get('event_id')
                if isinstance(event_id, str) and event_id in candidate_admin_ids:
                    admin_rows_grouped.setdefault(event_id, []).append(dict(raw))
            for event_id in candidate_admin_ids:
                snapshots = admin_rows_grouped.get(event_id, [])
                if len(snapshots) != 1:
                    admin_entry_errors[event_id] = (
                        "administrative intent lacks exactly one authority snapshot"
                    )
                    continue
                snapshot = snapshots[0]
                outbox = snapshot.get('outbox')
                receipt = snapshot.get('receipt')
                if not isinstance(outbox, dict) or not isinstance(receipt, dict):
                    admin_entry_errors[event_id] = (
                        "administrative intent receipt/outbox binding is missing"
                    )
                    continue
                try:
                    validate_admin_verdict_intent(
                        tree=outbox.get('tree'),
                        tag=outbox.get('node_tag'),
                        receipt_sha=outbox.get('receipt_sha'),
                        receipt=receipt,
                        current={
                            'current_receipt_sha': snapshot.get(
                                'current_receipt_sha'
                            ),
                            'verdict': snapshot.get('current_verdict'),
                            'verdict_source': snapshot.get(
                                'current_verdict_source'
                            ),
                        },
                        outbox=outbox,
                        demoted_receipt=snapshot.get('demoted_receipt'),
                        demoted_current=snapshot.get('demoted_current'),
                    )
                except AdminIntentError as exc:
                    admin_entry_errors[event_id] = str(exc)
                    continue
                promoted_scope = (
                    str(outbox.get('tree')),
                    str(outbox.get('node_tag')),
                )
                demoted_tag = outbox.get('demoted_tag')
                ancestry_ok = (
                    chain_error is None
                    and chain_index is not None
                    and outbox.get('receipt_sha')
                    in chain_index.ancestors_by_scope.get(
                        promoted_scope, frozenset()
                    )
                    and (
                        demoted_tag is None
                        or outbox.get('demoted_receipt_sha')
                        in chain_index.ancestors_by_scope.get(
                            (str(outbox.get('tree')), str(demoted_tag)),
                            frozenset(),
                        )
                    )
                )
                if not ancestry_ok:
                    admin_entry_errors[event_id] = (
                        chain_error
                        or 'administrative receipt is not in current chain ancestry'
                    )
                    continue
                admin_rows_by_id[event_id] = outbox

        prediction_rows_by_id: dict[str, dict] = {}
        prediction_entry_errors: dict[str, str] = {}
        if candidate_prediction_ids:
            prediction_authority_rows = self.kg(
                "UNWIND $ids AS event_id "
                "OPTIONAL MATCH (o:OutboxEntry {id:event_id}) "
                "OPTIONAL MATCH (t:LakatosTree {name:o.tree})-[:HAS_NODE]->"
                "(e {tag:o.node_tag}) "
                "OPTIONAL MATCH (e)-[binding:HAS_RECEIPT]->"
                "(rec:VerdictReceipt {receipt_sha:o.receipt_sha}) "
                "RETURN event_id, properties(o) AS outbox, "
                "count(DISTINCT t) AS trees, count(DISTINCT e) AS nodes, "
                "count(DISTINCT binding) AS bindings, "
                "count(DISTINCT rec) AS receipts, "
                "head(collect(DISTINCT properties(e))) AS current, "
                "head(collect(DISTINCT properties(rec))) AS receipt",
                ids=sorted(candidate_prediction_ids),
            )
            grouped_predictions: dict[str, list[dict]] = {}
            for raw in prediction_authority_rows or []:
                event_id = raw.get('event_id')
                if isinstance(event_id, str) and event_id in candidate_prediction_ids:
                    grouped_predictions.setdefault(event_id, []).append(dict(raw))
            for event_id in candidate_prediction_ids:
                snapshots = grouped_predictions.get(event_id, [])
                if len(snapshots) != 1:
                    prediction_entry_errors[event_id] = (
                        'prediction intent lacks exactly one authority snapshot'
                    )
                    continue
                snapshot = snapshots[0]
                outbox = snapshot.get('outbox')
                receipt = snapshot.get('receipt')
                current = snapshot.get('current')
                if not (
                    snapshot.get('trees') == 1
                    and snapshot.get('nodes') == 1
                    and snapshot.get('bindings') == 1
                    and snapshot.get('receipts') == 1
                    and isinstance(outbox, dict)
                    and isinstance(receipt, dict)
                    and isinstance(current, dict)
                ):
                    prediction_entry_errors[event_id] = (
                        'prediction intent receipt/node binding is missing'
                    )
                    continue
                try:
                    validate_prediction_register_intent(
                        tree=outbox.get('tree'),
                        tag=outbox.get('node_tag'),
                        receipt_sha=outbox.get('receipt_sha'),
                        receipt=receipt,
                        current=current,
                        outbox=outbox,
                        require_current_effect=True,
                    )
                except PredictionIntentError as exc:
                    prediction_entry_errors[event_id] = str(exc)
                    continue
                scope = (str(outbox.get('tree')), str(outbox.get('node_tag')))
                if chain_error is not None or (
                    chain_index is None
                    or outbox.get('receipt_sha')
                    not in chain_index.ancestors_by_scope.get(
                        scope, frozenset()
                    )
                ):
                    prediction_entry_errors[event_id] = (
                        chain_error
                        or 'prediction receipt is not in current chain ancestry'
                    )
                    continue
                prediction_rows_by_id[event_id] = outbox

        temporal_rows_by_id: dict[str, dict] = {}
        if candidate_prediction_temporal_ids:
            raw_rows = self.kg(PREDICTION_TEMPORAL_IDENTITY_CYPHER)
            grouped: dict[str, list[dict]] = {}
            for raw in raw_rows or []:
                row = dict(raw)
                outbox = row.get('outbox')
                event_id = outbox.get('id') if isinstance(outbox, dict) else None
                if (
                    isinstance(event_id, str)
                    and event_id in candidate_prediction_temporal_ids
                ):
                    grouped.setdefault(event_id, []).append(row)
            for event_id in candidate_prediction_temporal_ids:
                candidates = grouped.get(event_id, [])
                if len(candidates) != 1 or chain_index is None:
                    temporal_entry_errors[event_id] = (
                        chain_error
                        or 'prediction temporal intent lacks one exact authority snapshot'
                    )
                    continue
                try:
                    validated = validate_prediction_temporal_identity_row(
                        candidates[0],
                        chain_index=chain_index,
                        require_current_effect=True,
                    )
                except TemporalIntentError as exc:
                    temporal_entry_errors[event_id] = str(exc)
                    continue
                temporal_rows_by_id[event_id] = validated.outbox

        if candidate_temporal_sidecar_ids:
            raw_rows = self.kg(TEMPORAL_SIDECAR_IDENTITY_CYPHER)
            grouped = {}
            for raw in raw_rows or []:
                row = dict(raw)
                outbox = row.get('outbox')
                event_id = outbox.get('id') if isinstance(outbox, dict) else None
                if (
                    isinstance(event_id, str)
                    and event_id in candidate_temporal_sidecar_ids
                ):
                    grouped.setdefault(event_id, []).append(row)
            for event_id in candidate_temporal_sidecar_ids:
                candidates = grouped.get(event_id, [])
                if len(candidates) != 1 or chain_index is None:
                    temporal_entry_errors[event_id] = (
                        chain_error
                        or 'temporal sidecar intent lacks one exact authority snapshot'
                    )
                    continue
                try:
                    validated = validate_temporal_sidecar_identity_row(
                        candidates[0],
                        chain_index=chain_index,
                        require_current_effect=True,
                    )
                except TemporalIntentError as exc:
                    temporal_entry_errors[event_id] = str(exc)
                    continue
                temporal_rows_by_id[event_id] = validated.outbox
        legacy_groups: dict[str, set[str]] = {}
        legacy_trees: set[str] = set()
        for entry in plan['to_replay']:
            try:
                candidate_id, candidate_tree, candidate_op, _tag, candidate_payload = (
                    self._validated_pending_outbox_entry(entry)
                )
                payload_doc = json.loads(candidate_payload)
                arg_id = payload_doc.get("arg_id") if isinstance(payload_doc, dict) else None
                if (
                    candidate_id.startswith("ob-")
                    and candidate_op == "critique"
                    and isinstance(arg_id, str) and arg_id and "/" not in arg_id
                ):
                    stable = history_event_id(
                        candidate_tree, "critique", f"{candidate_tree}/{arg_id}"
                    )
                    legacy_groups.setdefault(stable, set()).add(candidate_id)
                    legacy_trees.add(candidate_tree)
            except (HistoryEventConflict, TypeError, ValueError, UnicodeError):
                continue
        # A previously adopted/applied legacy alias is not present in the pending
        # snapshot above.  Include every legacy critique alias in the affected
        # trees before authorizing another adoption; otherwise two ob-* ids can
        # silently claim the same stable critique identity and only fail the
        # later storage audit.
        if legacy_groups:
            alias_rows = self.kg(
                "MATCH (o:OutboxEntry) "
                "WHERE o.tree IN $trees AND o.op='critique' "
                "AND o.id STARTS WITH 'ob-' "
                "RETURN o.id AS id, o.tree AS tree, o.op AS op, "
                "o.node_tag AS node_tag, o.payload AS payload, "
                "o.status AS status, o.created_at AS created_at, "
                "o.reason AS reason, o.applied_at AS applied_at, "
                "o.adopted_by AS adopted_by, o.adopted_at AS adopted_at",
                trees=sorted(legacy_trees),
            )
            for alias in alias_rows or []:
                try:
                    alias_id, alias_tree, alias_op, _tag, alias_payload = (
                        self._validated_outbox_entry(
                            dict(alias), require_pending=False
                        )
                    )
                    payload_doc = json.loads(alias_payload)
                    arg_id = (
                        payload_doc.get("arg_id")
                        if isinstance(payload_doc, dict) else None
                    )
                    if (
                        alias_id.startswith("ob-")
                        and alias_op == "critique"
                        and isinstance(arg_id, str) and arg_id and "/" not in arg_id
                    ):
                        stable = history_event_id(
                            alias_tree, "critique", f"{alias_tree}/{arg_id}"
                        )
                        if stable in legacy_groups:
                            legacy_groups[stable].add(alias_id)
                except (HistoryEventConflict, TypeError, ValueError, UnicodeError):
                    continue
        duplicate_legacy_ids = {
            item
            for group in legacy_groups.values() if len(group) > 1
            for item in group
        }
        reported_causal_group_errors: set[str] = set()
        for e in plan['to_replay']:
            causal_group = e.get('causal_group')
            event_key = e.get('id')
            if isinstance(event_key, str) and event_key in admin_entry_errors:
                conflicts.append({
                    'id': event_key,
                    'error': admin_entry_errors[event_key],
                })
                continue
            if isinstance(event_key, str) and event_key in prediction_entry_errors:
                conflicts.append({
                    'id': event_key,
                    'error': prediction_entry_errors[event_key],
                })
                continue
            if isinstance(event_key, str) and event_key in temporal_entry_errors:
                conflicts.append({
                    'id': event_key,
                    'error': temporal_entry_errors[event_key],
                })
                continue
            if isinstance(event_key, str) and event_key in causal_entry_errors:
                conflicts.append({
                    'id': event_key,
                    'error': causal_entry_errors[event_key],
                })
                if isinstance(causal_group, str):
                    blocked_causal_groups.add(causal_group)
                continue
            causal_binding = (
                causal_bindings.get(event_key)
                if isinstance(event_key, str)
                else None
            )
            if causal_binding is not None:
                causal_group, _causal_index, dependencies = causal_binding
                group_error = causal_group_errors.get(causal_group)
                if group_error is not None:
                    if causal_group not in reported_causal_group_errors:
                        conflicts.append({
                            'id': event_key,
                            'error': group_error,
                        })
                        reported_causal_group_errors.add(causal_group)
                    blocked_causal_groups.add(causal_group)
                    if isinstance(event_key, str):
                        causal_deferred.append(event_key)
                    continue
                if causal_group in blocked_causal_groups:
                    if isinstance(event_key, str):
                        causal_deferred.append(event_key)
                    continue
                predecessor_ready = all(
                    causal_rows_by_id[dependency].get('status') == 'applied'
                    or dependency in replayed
                    for dependency in dependencies
                )
                if not predecessor_ready:
                    if isinstance(event_key, str):
                        causal_deferred.append(event_key)
                    continue
            if e.get("id") in duplicate_legacy_ids:
                conflicts.append({
                    "id": e["id"],
                    "error": "multiple legacy critique intents share one stable identity",
                })
                if isinstance(causal_group, str):
                    blocked_causal_groups.add(causal_group)
                continue
            try:
                authoritative_entry = (
                    causal_rows_by_id[event_key]
                    if causal_binding is not None
                    else admin_rows_by_id.get(
                        event_key,
                        prediction_rows_by_id.get(
                            event_key,
                            temporal_rows_by_id.get(event_key, e),
                        ),
                    )
                )
                event_id, tree, op, node_tag, payload = (
                    self._validated_pending_outbox_entry(authoritative_entry)
                )
                self._require_stable_argument_binding(
                    event_id, tree, op, node_tag, payload
                )
                pg_scope = (
                    self._writer_fenced_pg
                    if (
                        self._writer_lease_conn is not None
                        or self._writer_commit_guard is not None
                    )
                    else self.pg
                )
                with pg_scope() as c, c.cursor() as cur:
                    projection = self._insert_history(
                        cur,
                        tree,
                        op,
                        node_tag,
                        payload,
                        event_id,
                    )
                self._mark_outbox_applied(
                    event_id, tree, op, node_tag, payload,
                    projection,
                )
                replayed.append(event_id)
            except HistoryEventConflict as exc:
                conflict_id = e.get('id')
                conflicts.append({
                    'id': conflict_id if isinstance(conflict_id, str) else repr(conflict_id),
                    'error': str(exc),
                })
                self._logger.error(
                    "outbox %s history conflict(pending 유지): %s",
                    conflict_id,
                    exc,
                )
                if isinstance(causal_group, str):
                    blocked_causal_groups.add(causal_group)
            except (PgDataError, UnicodeError, ValueError) as exc:
                conflict_id = e.get("id")
                conflicts.append({
                    "id": conflict_id if isinstance(conflict_id, str) else repr(conflict_id),
                    "error": f"PostgreSQL data rejection: {type(exc).__name__}",
                })
                self._logger.error(
                    "outbox %s PostgreSQL data rejection(pending 유지): %s",
                    conflict_id,
                    type(exc).__name__,
                )
                if isinstance(causal_group, str):
                    blocked_causal_groups.add(causal_group)
            except (PgOperationalError, PgInterfaceError, PgPoolError):
                pg_down = True
                break   # PG 여전히 다운 — 나머지 pending 유지(다음 sweep 재시도)
        final_rows = self.kg(
            "MATCH (o:OutboxEntry {status:'pending'}) RETURN count(o) AS n"
        )
        if not (
            len(final_rows) == 1
            and type(final_rows[0].get("n")) is int
            and final_rows[0]["n"] >= 0
        ):
            raise HistoryEventConflict("final pending outbox readback was not exact")
        final_pending = final_rows[0]["n"]
        return {'pending': plan['pending_total'], 'replayed': replayed,
                'replayed_count': len(replayed),
                'still_pending': final_pending,
                'pg_down': pg_down, 'conflicts': conflicts,
                'causal_deferred': causal_deferred,
                'conflict_count': len(conflicts),
                'ok': not conflicts and not pg_down and final_pending == 0}

    def outbox_pending_count(self) -> int:
        """관측(#③ outbox 경화): 미적용 OutboxEntry 수 = KG↔PG 발산 깊이. best-effort — KG 다운 시 -1(미상).
        진짜 2PC 대신 outbox 정답패턴을 *관측가능*하게: pending 이 쌓이면 reconcile(자동 startup/수동 ops) 필요."""
        try:
            rows = self.kg("MATCH (o:OutboxEntry {status:'pending'}) RETURN count(o) AS n")
            return int(rows[0]['n']) if rows else 0
        except Exception:   # noqa: BLE001 — 관측은 어떤 예외도 운영을 막지 않음
            return -1

    # ── lifecycle ──────────────────────────────────────────────────────
    def close(self) -> list:
        """OPS-LIFECYCLE-1: 종료 시 각 자원을 best-effort 로 닫고 실패목록을 반환(감사)."""
        errs: list[str] = []
        for name, closer in (
            ("writer_lease", self._close_writer_lease),
            ("neo4j", lambda: self._neo.close()),
            ("mongo", lambda: self._mongo.close() if hasattr(self._mongo, "close") else self._mongo.client.close()),
            ("pg_pool", self._close_pg_pool),
        ):
            try:
                closer()
            except Exception as e:   # noqa: BLE001 — 종료 정리는 어떤 예외도 다음 자원을 막지 않는다
                errs.append(f"{name}:{type(e).__name__}:{e}")
        return errs
