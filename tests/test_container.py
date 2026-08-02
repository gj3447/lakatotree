"""AppContainer (server.container) 단위검증 — 자원층을 fake 어댑터로 단독 테스트.

합성 루트 추출의 핵심 가치: 모듈 전역 + `global` 변이 없이 자원 생명주기를
주입된 fake 로 검증할 수 있다(전엔 server.app 전역 monkeypatch 로만 가능했음).
# KG: span_lakatotree_server_architecture
"""
from concurrent.futures import ThreadPoolExecutor
import inspect
from threading import Event

import pytest
from psycopg2 import InterfaceError as PgInterfaceError
from psycopg2 import OperationalError as PgOperationalError

from lakatos.io.reconcile import history_event_id
from server.container import AppContainer
from server.ports import (
    GuardedKgOps,
    HistoryEventConflict,
    KgTxGuardFailed,
    WriterFenceLost,
)


def test_outbox_state_transitions_use_only_the_writer_fenced_port():
    pending_source = inspect.getsource(AppContainer._record_pending_outbox)
    applied_source = inspect.getsource(AppContainer._mark_outbox_applied)

    assert "self.writer_fenced_kg_tx" in pending_source
    assert "self.writer_fenced_kg_tx" in applied_source
    assert "self.kg_tx(" not in pending_source
    assert "self.kg_tx(" not in applied_source


class _FakeSession:
    def __init__(self, sink): self._sink = sink
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def run(self, q, **kw):
        self._sink.append((q, kw))
        return type("R", (), {"data": lambda s: [{"ok": 1}]})()
    def execute_write(self, unit): return unit(self)


class _FakeNeo:
    def __init__(self): self.queries = []; self.closed = False
    def session(self): return _FakeSession(self.queries)
    def close(self): self.closed = True


class _FakeMongo:
    def __init__(self): self.closed = False
    def close(self): self.closed = True


def _container(**kw):
    return AppContainer(neo=kw.get("neo", _FakeNeo()), mongo=kw.get("mongo", _FakeMongo()),
                        pg_kw={"host": "x"}, **{k: v for k, v in kw.items() if k not in ("neo", "mongo")})


def test_kg_runs_against_injected_driver():
    neo = _FakeNeo()
    c = AppContainer(neo=neo, mongo=_FakeMongo(), pg_kw={})
    assert c.kg("RETURN 1", a=2) == [{"ok": 1}]
    assert neo.queries == [("RETURN 1", {"a": 2})]


def test_kg_tx_runs_all_ops_in_one_unit():
    neo = _FakeNeo()
    c = AppContainer(neo=neo, mongo=_FakeMongo(), pg_kw={})
    c.kg_tx([("CREATE (a)", {"x": 1}), ("CREATE (b)", {"y": 2})])
    assert [q for q, _ in neo.queries] == ["CREATE (a)", "CREATE (b)"]   # 단일 트랜잭션 내 순차 실행


def test_guarded_kg_tx_raises_inside_unit_before_later_ops():
    class EmptyFirstSession(_FakeSession):
        def run(self, q, **kw):
            self._sink.append((q, kw))
            rows = [] if q == "CLAIM" else [{"unexpected": True}]
            return type("R", (), {"data": lambda _self: rows})()

    class GuardNeo(_FakeNeo):
        def session(self):
            return EmptyFirstSession(self.queries)

    neo = GuardNeo()
    c = AppContainer(neo=neo, mongo=_FakeMongo(), pg_kw={})
    with pytest.raises(KgTxGuardFailed):
        c.kg_tx(GuardedKgOps([("CLAIM", {}), ("PROVENANCE", {})]))
    assert [q for q, _ in neo.queries] == ["CLAIM"]


def test_guarded_kg_tx_value_barrier_rolls_back_before_later_ops():
    class StatusSession(_FakeSession):
        def run(self, q, **kw):
            self._sink.append((q, kw))
            rows = [{"guard_status": "claim_conflict"}]
            return type("R", (), {"data": lambda _self: rows})()

    class GuardNeo(_FakeNeo):
        def session(self):
            return StatusSession(self.queries)

    neo = GuardNeo()
    c = AppContainer(neo=neo, mongo=_FakeMongo(), pg_kw={})
    with pytest.raises(KgTxGuardFailed, match="claim_conflict"):
        c.kg_tx(GuardedKgOps(
            [("CLAIM", {}), ("SIDE_EFFECT", {})],
            guard_field="guard_status",
            guard_expected="ok",
        ))
    assert [q for q, _ in neo.queries] == ["CLAIM"]


def test_guarded_kg_tx_set_accepts_explicit_terminal_states_and_preserves_row():
    class StatusSession(_FakeSession):
        def run(self, q, **kw):
            self._sink.append((q, kw))
            rows = (
                [{"guard_status": "already_committed", "generation": 7}]
                if q == "CLAIM"
                else [{"ran": True}]
            )
            return type("R", (), {"data": lambda _self: rows})()

    class GuardNeo(_FakeNeo):
        def session(self):
            return StatusSession(self.queries)

    neo = GuardNeo()
    c = AppContainer(neo=neo, mongo=_FakeMongo(), pg_kw={})
    result = c.kg_tx(GuardedKgOps(
        [("CLAIM", {}), ("SIDE_EFFECT", {})],
        guard_field="guard_status",
        guard_expected={"proceed", "already_committed"},
    ))
    assert result[0] == [{"guard_status": "already_committed", "generation": 7}]
    assert [q for q, _ in neo.queries] == ["CLAIM", "SIDE_EFFECT"]


def test_guard_failure_exposes_exact_first_row_but_never_runs_later_ops():
    class StatusSession(_FakeSession):
        def run(self, q, **kw):
            self._sink.append((q, kw))
            rows = [{"guard_status": "already_committed", "generation": 7}]
            return type("R", (), {"data": lambda _self: rows})()

    class GuardNeo(_FakeNeo):
        def session(self):
            return StatusSession(self.queries)

    neo = GuardNeo()
    c = AppContainer(neo=neo, mongo=_FakeMongo(), pg_kw={})
    with pytest.raises(KgTxGuardFailed) as captured:
        c.kg_tx(GuardedKgOps(
            [("CLAIM", {}), ("SIDE_EFFECT", {})],
            guard_field="guard_status",
            guard_expected="ok",
        ))
    assert captured.value.actual == "already_committed"
    assert captured.value.row == {
        "guard_status": "already_committed",
        "generation": 7,
    }
    assert [q for q, _ in neo.queries] == ["CLAIM"]


def test_close_collects_per_resource_errors():
    class Boom:
        def close(self): raise RuntimeError("boom")
    c = AppContainer(neo=Boom(), mongo=_FakeMongo(), pg_kw={})
    errs = c.close()
    assert any("neo4j" in e and "RuntimeError" in e for e in errs)   # 실패는 수집, 다른 자원은 진행


def test_close_all_ok_returns_empty():
    neo, mongo = _FakeNeo(), _FakeMongo()
    c = AppContainer(neo=neo, mongo=mongo, pg_kw={})
    assert c.close() == []        # pg 풀 미초기화(lazy) → skip, 나머지 정상
    assert neo.closed and mongo.closed


def test_close_skips_uninitialized_pg_pool():
    # 풀을 한 번도 안 빌렸으면 closeall 시도 없이 통과(lazy 미초기화 안전)
    c = AppContainer(neo=_FakeNeo(), mongo=_FakeMongo(), pg_kw={})
    assert c._pg_pool is None
    assert c.close() == []


def test_global_writer_lease_allows_one_replica_and_live_loss_fails_closed(
    monkeypatch,
):
    state = {"owner": None}
    neo_state = {"token": None, "generation": 0}

    class _LeaseSession:
        def __init__(self, queries):
            self.queries = queries

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def run(self, query, **params):
            text = str(query)
            self.queries.append((text, params))
            rows = []
            if "MERGE (lease:RuntimeWriterLease" in text:
                neo_state["generation"] += 1
                neo_state["token"] = params["owner_token"]
                rows = [{
                    "owner_token": neo_state["token"],
                    "generation": neo_state["generation"],
                }]
            elif "REMOVE lease.owner_token" in text:
                exact = (
                    neo_state["token"] == params["owner_token"]
                    and neo_state["generation"] == params["generation"]
                )
                if exact:
                    neo_state["token"] = None
                rows = [{"revoked": 1 if exact else 0}]
            elif "MATCH (lease:RuntimeWriterLease" in text:
                if (
                    neo_state["token"] == params["owner_token"]
                    and neo_state["generation"] == params["generation"]
                ):
                    rows = [{
                        "owner_token": neo_state["token"],
                        "generation": neo_state["generation"],
                    }]
            else:
                rows = [{"mutated": True}]
            return type("R", (), {"data": lambda _self: rows})()

        def execute_write(self, unit):
            return unit(self)

    class _LeaseNeo:
        def __init__(self):
            self.queries = []

        def session(self):
            return _LeaseSession(self.queries)

        def close(self):
            return None

    class _Cursor:
        def __init__(self, conn):
            self.conn = conn
            self.row = None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, query, _params=None):
            if "pg_try_advisory_lock" in query:
                acquired = state["owner"] in (None, self.conn)
                if acquired:
                    state["owner"] = self.conn
                    self.conn.holds = True
                self.row = (acquired,)
            elif "FROM pg_locks" in query:
                self.row = (
                    state["owner"] is self.conn and self.conn.holds,
                )
            elif query.startswith("SET "):
                self.row = None
            else:  # pragma: no cover - lease protocol has a closed SQL surface
                raise AssertionError(query)

        def fetchone(self):
            return self.row

    class _Connection:
        closed = False
        holds = False

        def cursor(self):
            return _Cursor(self)

        def close(self):
            self.closed = True
            self.holds = False
            if state["owner"] is self:
                state["owner"] = None

    monkeypatch.setattr(
        "server.container.psycopg2.connect", lambda **_kwargs: _Connection()
    )
    neo = _LeaseNeo()
    first = _container(neo=neo)
    second = _container(neo=neo)

    assert first.acquire_writer_lease() is True
    assert first.writer_lease_ready() is True
    assert second.acquire_writer_lease() is False
    assert first.writer_fenced_kg_tx([("MUTATE", {})]) == [
        [{"mutated": True}]
    ]
    first.release_writer_lease()
    assert first.writer_lease_ready() is False
    assert second.acquire_writer_lease() is True

    state["owner"] = None  # simulate backend/session lease loss
    assert second.writer_lease_ready() is False


def test_writer_fence_rejects_a_token_taken_over_before_domain_mutation(
    monkeypatch,
):
    """A stale process cannot pass merely because its PG precheck was once green."""

    c = _container()
    c._writer_lease_conn = object()
    c._writer_fence_token = "old"
    c._writer_fence_generation = 1
    monkeypatch.setattr(c, "_pg_writer_lease_ready_unlocked", lambda: True)
    queries = []

    class _Session(_FakeSession):
        def run(self, query, **params):
            queries.append(str(query))
            rows = [] if "RuntimeWriterLease" in str(query) else [{"mutated": True}]
            return type("R", (), {"data": lambda _self: rows})()

    class _Neo(_FakeNeo):
        def session(self):
            return _Session(self.queries)

    c._neo = _Neo()
    monkeypatch.setattr(c, "_close_writer_lease_unlocked", lambda: None)

    with pytest.raises(WriterFenceLost):
        c.writer_fenced_kg_tx([("MUTATE", {})])

    assert all(query != "MUTATE" for query in queries)


def test_writer_acquire_revalidates_pg_after_neo_claim(monkeypatch):
    """A PG lease lost while Neo claim blocks is never published as authority."""

    class _Cursor:
        row = None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, query, _params=None):
            if "pg_try_advisory_lock" in query:
                self.row = (True,)
            elif "FROM pg_locks" in query:
                self.row = (False,)
            elif query.startswith("SET "):
                self.row = None

        def fetchone(self):
            return self.row

    class _Connection:
        closed = False

        def cursor(self):
            return _Cursor()

        def close(self):
            self.closed = True

    class _NeoSession(_FakeSession):
        def run(self, query, **params):
            text = str(query)
            self._sink.append((text, params))
            if "MERGE (lease:RuntimeWriterLease" in text:
                rows = [{
                    "owner_token": params["owner_token"],
                    "generation": 1,
                }]
            else:
                rows = [{"revoked": 1}]
            return type("R", (), {"data": lambda _self: rows})()

    class _Neo(_FakeNeo):
        def session(self):
            return _NeoSession(self.queries)

    monkeypatch.setattr(
        "server.container.psycopg2.connect", lambda **_kwargs: _Connection()
    )
    c = _container(neo=_Neo())

    assert c.acquire_writer_lease() is False
    assert c._writer_lease_conn is None
    assert c._writer_fence_token is None


def test_writer_authority_releases_global_lease_on_exception(monkeypatch):
    c = _container()
    released = []
    monkeypatch.setattr(c, "acquire_writer_lease", lambda: True)
    monkeypatch.setattr(
        c, "_close_writer_lease_unlocked", lambda: released.append(True)
    )

    with pytest.raises(RuntimeError, match="audit failed"):
        with c.writer_authority(acquire=True) as ready:
            assert ready is True
            raise RuntimeError("audit failed")

    assert released == [True]


def test_pg_pool_first_use_constructs_exactly_one_pool(monkeypatch):
    entered = Event()
    release = Event()
    second_started = Event()
    constructed = []

    class _Pool:
        def __init__(self, *_args, **_kwargs):
            constructed.append(self)
            entered.set()
            assert release.wait(timeout=5)

    monkeypatch.setattr("server.container.psycopg2.pool.ThreadedConnectionPool", _Pool)
    c = _container()

    def second_call():
        second_started.set()
        return c.pg_pool()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(c.pg_pool)
        assert entered.wait(timeout=5)
        second = executor.submit(second_call)
        assert second_started.wait(timeout=5)
        assert len(constructed) == 1
        release.set()
        assert first.result(timeout=5) is second.result(timeout=5)
    assert len(constructed) == 1


def test_pg_returns_connection_to_the_pool_that_checked_it_out():
    class _Connection:
        def commit(self):
            return None

        def rollback(self):
            return None

    connection = _Connection()

    class _Pool:
        def __init__(self, name):
            self.name = name
            self.returned = []

        def getconn(self):
            return connection

        def putconn(self, value):
            self.returned.append(value)

    origin = _Pool("origin")
    foreign = _Pool("foreign")
    calls = []

    def changing_pool_lookup():
        calls.append(True)
        return origin if len(calls) == 1 else foreign

    c = _container()
    c.pg_pool = changing_pool_lookup
    with c.pg() as borrowed:
        assert borrowed is connection
    assert len(calls) == 1
    assert origin.returned == [connection]
    assert foreign.returned == []


def test_hist_swallows_pg_operational_error(caplog):
    # PG 다운은 best-effort — 예외를 삼키고 경고만(KG=truth, 이력만 유실)
    class _PgDownContainer(AppContainer):
        recorded = []
        def pg(self):
            raise PgOperationalError("pg down")
        def _record_pending_outbox(self, **kwargs):
            self.recorded.append(kwargs)
    c = _PgDownContainer(neo=_FakeNeo(), mongo=_FakeMongo(), pg_kw={})
    c.hist("tree", "op")   # raise 하면 테스트 실패 — 삼켜야 정상
    assert len(c.recorded) == 1


def test_hist_rejects_idless_critique_before_any_storage_side_effect():
    touched = []

    class _NoStorageContainer(AppContainer):
        def pg(self):
            touched.append("pg")
            raise AssertionError("PostgreSQL must not be opened")

        def _record_pending_outbox(self, **_kwargs):
            touched.append("outbox")
            raise AssertionError("outbox must not be written")

    c = _NoStorageContainer(neo=_FakeNeo(), mongo=_FakeMongo(), pg_kw={})
    with pytest.raises(HistoryEventConflict, match="caller-stable event_id"):
        c.hist(
            "tree",
            "critique",
            "n",
            {
                "arg_id": "a",
                "attacks": "n",
                "by": "b",
                "kind": "doubt",
                "body": "",
            },
        )
    assert touched == []


def test_hist_pg_failure_invalidates_runtime_storage_authority():
    events = []

    class _PgDownContainer(AppContainer):
        def pg(self):
            raise PgOperationalError("pg down")

        def _record_pending_outbox(self, **_kwargs):
            events.append("outbox")

    c = _PgDownContainer(
        neo=_FakeNeo(),
        mongo=_FakeMongo(),
        pg_kw={},
        on_history_divergence=events.append,
    )

    c.hist("tree", "op")

    assert events == ["outbox", "runtime.history_projection.pending"]


def test_history_transactions_install_bounded_local_timeouts():
    calls = []

    class _Cursor:
        def execute(self, query, params):
            calls.append((query, params))

    AppContainer._set_history_transaction_timeouts(_Cursor())

    assert calls == [
        (
            "SELECT set_config('statement_timeout', %s, true)",
            ("5000ms",),
        ),
        (
            "SELECT set_config('lock_timeout', %s, true)",
            ("3000ms",),
        ),
    ]


def test_history_lock_timeout_becomes_recoverable_pending_projection():
    events = []

    class _Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, query, _params):
            if "lock_timeout" in query:
                raise PgOperationalError("canceling statement due to lock timeout")

    class _Connection:
        def cursor(self):
            return _Cursor()

    class _Container(AppContainer):
        def pg(self):
            class _Pg:
                def __enter__(self):
                    return _Connection()

                def __exit__(self, *_args):
                    return False

            return _Pg()

        def _record_pending_outbox(self, **kwargs):
            events.append(("outbox", kwargs["event_id"]))

    container = _Container(
        neo=_FakeNeo(),
        mongo=_FakeMongo(),
        pg_kw={},
        on_history_divergence=lambda reason: events.append(("signal", reason)),
    )

    assert container.hist(
        "tree", "op", payload={"value": 1}, event_id="ob-timeout"
    ) is False
    assert events == [
        ("outbox", "ob-timeout"),
        ("signal", "runtime.history_projection.pending"),
    ]


def test_hist_pg_identity_conflict_invalidates_runtime_storage_authority():
    reasons = []

    class _Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, *_args):
            return None

    class _Connection:
        def cursor(self):
            return _Cursor()

    class _ConflictContainer(AppContainer):
        @staticmethod
        def _insert_history(*_args, **_kwargs):
            raise HistoryEventConflict("proven row mismatch")

        def pg(self):
            class _Pg:
                def __enter__(self):
                    return _Connection()

                def __exit__(self, *_args):
                    return False

            return _Pg()

    c = _ConflictContainer(
        neo=_FakeNeo(),
        mongo=_FakeMongo(),
        pg_kw={},
        on_history_divergence=reasons.append,
    )

    with pytest.raises(HistoryEventConflict, match="proven row mismatch"):
        c.hist("tree", "critique", "n", {"arg_id": "a", "attacks": "n",
                                              "by": "b", "kind": "doubt", "body": ""},
               event_id="he-" + "a" * 64)

    assert reasons == ["runtime.history_projection.conflict"]


def test_stable_outbox_cannot_claim_legacy_adopted_state():
    stable_id = history_event_id("T", "critique", "T/a")
    entry = {
        "id": stable_id,
        "tree": "T",
        "op": "critique",
        "node_tag": "n",
        "payload": '{"arg_id":"a","attacks":"n","body":"","by":"b","kind":"doubt"}',
        "status": "adopted",
        "created_at": "2026-08-02T00:00:00+00:00",
        "reason": "critique_commit_intent",
        "applied_at": None,
        "adopted_by": stable_id,
        "adopted_at": "2026-08-02T00:00:01+00:00",
    }

    with pytest.raises(HistoryEventConflict, match="invalid state"):
        AppContainer._validated_outbox_entry(entry, require_pending=False)


def test_ambiguous_commit_preserves_primary_error_and_discards_broken_connection():
    returned = []

    class _Connection:
        closed = 1

        def cursor(self):
            class _Cursor:
                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

                def execute(self, *_args):
                    return None

                def fetchone(self):
                    return (True,)

            return _Cursor()

        def commit(self):
            raise PgOperationalError("commit acknowledgement lost")

        def rollback(self):
            raise PgInterfaceError("connection already closed")

    class _Pool:
        def getconn(self):
            return _Connection()

        def putconn(self, connection, close=False):
            returned.append((connection, close))

    reasons = []

    class _Container(AppContainer):
        def pg_pool(self):
            return _Pool()

        def _record_pending_outbox(self, **kwargs):
            self.recorded = kwargs

    c = _Container(
        neo=_FakeNeo(),
        mongo=_FakeMongo(),
        pg_kw={},
        on_history_divergence=reasons.append,
    )
    c.hist("tree", "op", payload={"value": 1})

    assert reasons == ["runtime.history_projection.pending"]
    assert c.recorded["event_id"].startswith("ph-history-")
    assert returned and returned[0][1] is True
