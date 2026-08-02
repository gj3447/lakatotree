"""Real-datastore proof that critique audit intent survives a post-KG crash."""
from __future__ import annotations

import contextlib
import importlib.resources
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from uuid import uuid4

import psycopg2
import pytest
from fastapi import HTTPException
from psycopg2 import sql

from lakatos.io.reconcile import history_event_id
from server.container import AppContainer
from server.contexts.tree.evidence_claim_service import EvidenceClaimService
from server.contexts.tree.schemas import CritiqueIn
from server.ports import HistoryEventConflict, WriterFenceLost
from server.storage_contract import inspect_neo_outbox_contract, pg_projection_rows
from server import storage_predeploy


pytestmark = pytest.mark.integration


@pytest.fixture(scope="module", autouse=True)
def _exact_outbox_identity_constraint(neo4j_driver):
    """No test may rely on another test having happened to create this constraint."""

    with neo4j_driver.session() as session:
        resources = importlib.resources.files("server.storage_migrations")
        for name in storage_predeploy.NEO_RESOURCES:
            for statement in storage_predeploy._migration_cypher(
                resources.joinpath(name).read_bytes()
            ):
                session.run(statement).consume()
        rows = session.run(
            "SHOW CONSTRAINTS YIELD name, type, entityType, labelsOrTypes, properties "
            "WHERE name='lkt_outbox_id_unique' "
            "RETURN name, type, entityType, labelsOrTypes, properties"
        ).data()
    assert len(rows) == 1
    assert rows[0]["entityType"] == "NODE"
    assert rows[0]["labelsOrTypes"] == ["OutboxEntry"]
    assert rows[0]["properties"] == ["id"]


def _require_writer(container: AppContainer) -> None:
    assert container.acquire_writer_lease() is True
    assert container.writer_lease_ready() is True


class _BorrowedDriver:
    def __init__(self, driver):
        self._driver = driver

    def session(self, *args, **kwargs):
        return self._driver.session(*args, **kwargs)

    def close(self):
        pass


class _DummyMongo:
    def close(self):
        pass


def test_two_containers_elect_one_writer_then_fail_over(neo4j_driver, pg_kw):
    containers = [
        AppContainer(
            neo=_BorrowedDriver(neo4j_driver), mongo=_DummyMongo(), pg_kw=pg_kw
        )
        for _ in range(2)
    ]
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            acquired = list(pool.map(lambda item: item.acquire_writer_lease(), containers))

        assert acquired.count(True) == 1
        assert acquired.count(False) == 1
        winner = containers[acquired.index(True)]
        loser = containers[acquired.index(False)]
        assert winner.writer_lease_ready() is True
        assert loser.writer_lease_ready() is False

        winner.close()
        assert loser.acquire_writer_lease() is True
        assert loser.writer_lease_ready() is True
    finally:
        for container in containers:
            container.close()


def test_lease_backend_death_rolls_back_and_successor_takes_over(
    neo4j_driver, pg_kw
):
    """The lease-owning PG backend is also the mutation transaction boundary."""

    event_id = f"ph-runtime-lease-{uuid4().hex}"
    successor_event_id = f"ph-runtime-successor-{uuid4().hex}"
    winner = AppContainer(
        neo=_BorrowedDriver(neo4j_driver), mongo=_DummyMongo(), pg_kw=pg_kw
    )
    successor = AppContainer(
        neo=_BorrowedDriver(neo4j_driver), mongo=_DummyMongo(), pg_kw=pg_kw
    )
    killer = None
    try:
        _require_writer(winner)
        assert successor.acquire_writer_lease() is False
        lease = winner.writer_lease_public_projection()
        assert lease is not None
        backend_pid = lease["postgresql_backend_pid"]

        killer = psycopg2.connect(**pg_kw)
        killer.autocommit = True
        with pytest.raises(WriterFenceLost):
            with winner._writer_fenced_pg() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO public.history(tree,op,payload,event_id) "
                        "VALUES ('runtime-lease-test','lease-killed','{}'::jsonb,%s)",
                        (event_id,),
                    )
                with killer.cursor() as cursor:
                    cursor.execute("SELECT pg_terminate_backend(%s)", (backend_pid,))
                    assert cursor.fetchone() == (True,)

        check = psycopg2.connect(**pg_kw)
        try:
            with check.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) FROM public.history WHERE event_id=%s",
                    (event_id,),
                )
                assert cursor.fetchone() == (0,)
        finally:
            check.close()

        assert successor.acquire_writer_lease() is True
        with successor._writer_fenced_pg() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO public.history(tree,op,payload,event_id) "
                    "VALUES ('runtime-lease-test','successor','{}'::jsonb,%s)",
                    (successor_event_id,),
                )
        assert _history_rows(pg_kw, "runtime-lease-test")[-1][4] == successor_event_id
    finally:
        if killer is not None:
            killer.close()
        cleanup = psycopg2.connect(**pg_kw)
        try:
            with cleanup, cleanup.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM public.history WHERE event_id IN (%s,%s)",
                    (event_id, successor_event_id),
                )
        finally:
            cleanup.close()
        winner.close()
        successor.close()


def _service(container: AppContainer, hist) -> EvidenceClaimService:
    return EvidenceClaimService(
        kg=container.kg,
        kg_tx=container.kg_tx,
        critique_kg_tx=container.writer_fenced_kg_tx,
        hist=hist,
        foundation=lambda _tree: None,
        load_lineage=lambda: (),
        reproducible_for_node=lambda _tree, _tag: None,
        on_semantic_divergence=None,
    )


def _history_rows(pg_kw, tree: str) -> list[tuple]:
    connection = psycopg2.connect(**pg_kw)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, op, node_tag, payload, event_id FROM public.history "
                "WHERE tree=%s ORDER BY id",
                (tree,),
            )
            return cursor.fetchall()
    finally:
        connection.close()


def _insert_history_row(pg_kw, tree, tag, payload, event_id=None) -> int:
    connection = psycopg2.connect(**pg_kw)
    try:
        with connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO public.history(tree, op, node_tag, payload, event_id) "
                "VALUES (%s,'critique',%s,%s,%s) RETURNING id",
                (tree, tag, json.dumps(payload, ensure_ascii=False), event_id),
            )
            return cursor.fetchone()[0]
    finally:
        connection.close()


def _create_database(pg_kw: dict, name: str) -> dict:
    connection = psycopg2.connect(**pg_kw)
    try:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    finally:
        connection.close()
    return {**pg_kw, "dbname": name}


def _drop_database(pg_kw: dict, name: str) -> None:
    connection = psycopg2.connect(**pg_kw)
    try:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname=%s AND pid<>pg_backend_pid()",
                (name,),
            )
            cursor.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
    finally:
        connection.close()


@contextlib.contextmanager
def _legacy_history_database(
    pg_kw, tree, tag, payload, event_id=None, *, seed_history=True
):
    """Seed a pre-contract row, then upgrade the disposable database in place."""

    database = f"lkt_legacy_{uuid4().hex}"
    isolated_kw = _create_database(pg_kw, database)
    connection = None
    try:
        connection = psycopg2.connect(**isolated_kw)
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE public.history(
                  id BIGSERIAL PRIMARY KEY,
                  ts TIMESTAMPTZ NOT NULL DEFAULT now(),
                  tree TEXT NOT NULL,
                  op TEXT NOT NULL,
                  node_tag TEXT,
                  payload JSONB,
                  event_id TEXT
                );
                CREATE UNIQUE INDEX uq_history_event_id
                  ON public.history(event_id) WHERE event_id IS NOT NULL;
                """
            )
            row_id = None
            if seed_history:
                cursor.execute(
                    "INSERT INTO public.history(tree,op,node_tag,payload,event_id) "
                    "VALUES (%s,'critique',%s,%s,%s) RETURNING id",
                    (tree, tag, json.dumps(payload, ensure_ascii=False), event_id),
                )
                row_id = cursor.fetchone()[0]
            migration = importlib.resources.files(
                "server.storage_migrations"
            ).joinpath("critique_history_v1.sql").read_text(encoding="utf-8")
            cursor.execute(migration)
        connection.close()
        connection = None
        yield isolated_kw, row_id
    finally:
        if connection is not None:
            connection.close()
        _drop_database(pg_kw, database)


def _history_claims(pg_kw, tree: str) -> list[tuple]:
    connection = psycopg2.connect(**pg_kw)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT c.stable_event_id, c.history_id "
                "FROM public.history_event_claims c "
                "JOIN public.history h ON h.id=c.history_id "
                "WHERE h.tree=%s ORDER BY c.stable_event_id",
                (tree,),
            )
            return cursor.fetchall()
    finally:
        connection.close()


def _seed_tree_and_argument(container, tree, tag, payload) -> None:
    container.kg(
        "CREATE CONSTRAINT lkt_argument_id_unique IF NOT EXISTS "
        "FOR (n:LakatosArgument) REQUIRE n.id IS UNIQUE"
    )
    container.kg(
        "CREATE CONSTRAINT lkt_outbox_id_unique IF NOT EXISTS "
        "FOR (n:OutboxEntry) REQUIRE n.id IS UNIQUE"
    )
    container.kg(
        "CREATE (t:LakatosTree {name:$tree})-[:HAS_NODE]->"
        "(e:LakatosNode {name:$node_name, tag:$tag, verdict:'proof', "
        "valid_until_rebutted:true}) "
        "CREATE (a:Argument:LakatosArgument {id:$argument_id, tree_name:$tree, "
        "local_id:$arg_id, attacks:$attacks, by:$by, kind:$kind, body:$body, "
        "at:$ts}) "
        "CREATE (e)-[:HAS_ARGUMENT]->(a)",
        tree=tree,
        node_name=f"{tree}/{tag}",
        tag=tag,
        argument_id=f"{tree}/{payload.arg_id}",
        arg_id=payload.arg_id,
        attacks=payload.attacks,
        by=payload.by,
        kind=payload.kind,
        body=payload.body,
        ts=datetime.now(timezone.utc).isoformat(),
    )


def _cleanup(container, pg_kw, tree):
    connection = psycopg2.connect(**pg_kw)
    try:
        with connection, connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM public.history_event_claims WHERE history_id IN "
                "(SELECT id FROM public.history WHERE tree=%s)",
                (tree,),
            )
            cursor.execute("DELETE FROM public.history WHERE tree=%s", (tree,))
    finally:
        connection.close()
    container.kg(
        "MATCH (o:OutboxEntry {tree:$tree}) DETACH DELETE o",
        tree=tree,
    )
    container.kg(
        "MATCH (a:Argument) WHERE a.id STARTS WITH $prefix DETACH DELETE a",
        prefix=f"{tree}/",
    )
    container.kg(
        "MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e) "
        "DETACH DELETE e",
        tree=tree,
    )
    container.kg(
        "MATCH (t:LakatosTree {name:$tree}) DETACH DELETE t",
        tree=tree,
    )


def test_atomic_intent_recovers_without_client_retry(neo4j_driver, pg_kw):
    tree = f"CRITIQUE_CRASH_{uuid4().hex}"
    tag = "n"
    payload = CritiqueIn(
        arg_id="d1",
        attacks=tag,
        by="alice",
        kind="doubt",
        body="question",
    )
    history_payload = payload.model_dump()
    event_id = history_event_id(tree, "critique", f"{tree}/{payload.arg_id}")
    container = AppContainer(
        neo=_BorrowedDriver(neo4j_driver),
        mongo=_DummyMongo(),
        pg_kw=pg_kw,
    )
    _require_writer(container)
    container.kg(
        "CREATE CONSTRAINT lkt_argument_id_unique IF NOT EXISTS "
        "FOR (n:LakatosArgument) REQUIRE n.id IS UNIQUE"
    )
    container.kg(
        "CREATE (t:LakatosTree {name:$tree})-[:HAS_NODE]->"
        "(e:LakatosNode {name:$node_name, tag:$tag, verdict:'proof', "
        "valid_until_rebutted:true})",
        tree=tree,
        node_name=f"{tree}/{tag}",
        tag=tag,
    )

    def crash_before_projection(*_args, **_kwargs):
        raise RuntimeError("simulated process death after Neo4j commit")

    try:
        with pytest.raises(RuntimeError, match="simulated process death"):
            _service(container, crash_before_projection).add_critique(
                tree, tag, payload
            )

        committed = container.kg(
            "MATCH (a:Argument {id:$id}) "
            "OPTIONAL MATCH (o:OutboxEntry {id:$event_id}) "
            "RETURN count(a) AS arguments, count(o) AS intents, "
            "collect(o.status) AS statuses",
            id=f"{tree}/d1",
            event_id=event_id,
        )[0]
        assert committed == {
            "arguments": 1,
            "intents": 1,
            "statuses": ["pending"],
        }
        assert _history_rows(pg_kw, tree) == []

        recovered = container.reconcile_outbox()

        assert event_id in recovered["replayed"]
        rows = _history_rows(pg_kw, tree)
        assert len(rows) == 1
        assert rows[0][1:] == ("critique", tag, history_payload, event_id)
        assert _history_claims(pg_kw, tree) == [(event_id, rows[0][0])]
        assert container.kg(
            "MATCH (o:OutboxEntry {id:$id}) RETURN o.status AS status",
            id=event_id,
        ) == [{"status": "applied"}]

        retry = _service(container, container.hist).add_critique(tree, tag, payload)

        assert retry["idempotent"] is True
        assert _history_rows(pg_kw, tree) == rows
        assert container.reconcile_outbox()["replayed"].count(event_id) == 0
    finally:
        _cleanup(container, pg_kw, tree)
        container.close()


def test_postgresql_commit_before_outbox_mark_recovers_exactly_once(
    neo4j_driver, pg_kw, monkeypatch
):
    tree = f"CRITIQUE_POST_PG_CRASH_{uuid4().hex}"
    tag = "n"
    payload = CritiqueIn(
        arg_id="d1", attacks=tag, by="alice", kind="doubt", body="question"
    )
    event_id = history_event_id(tree, "critique", f"{tree}/{payload.arg_id}")
    first = AppContainer(
        neo=_BorrowedDriver(neo4j_driver), mongo=_DummyMongo(), pg_kw=pg_kw
    )
    _require_writer(first)
    first.kg(
        "CREATE (t:LakatosTree {name:$tree})-[:HAS_NODE]->"
        "(e:LakatosNode {name:$node_name, tag:$tag, verdict:'proof', "
        "valid_until_rebutted:true})",
        tree=tree,
        node_name=f"{tree}/{tag}",
        tag=tag,
    )

    def lose_applied_mark(*_args, **_kwargs):
        raise RuntimeError("simulated process death before outbox applied mark")

    monkeypatch.setattr(first, "_mark_outbox_applied", lose_applied_mark)
    recovered = None
    try:
        assert _service(first, first.hist).add_critique(tree, tag, payload)["ok"]
        rows = _history_rows(pg_kw, tree)
        assert len(rows) == 1
        assert _history_claims(pg_kw, tree) == [(event_id, rows[0][0])]
        assert first.kg(
            "MATCH (o:OutboxEntry {id:$id}) RETURN o.status AS status",
            id=event_id,
        ) == [{"status": "pending"}]

        first.close()
        first = None
        recovered = AppContainer(
            neo=_BorrowedDriver(neo4j_driver), mongo=_DummyMongo(), pg_kw=pg_kw
        )
        _require_writer(recovered)
        result = recovered.reconcile_outbox()
        assert result["ok"] is True
        assert event_id in result["replayed"]
        assert _history_rows(pg_kw, tree) == rows
        assert recovered.reconcile_outbox()["replayed"] == []
        assert recovered.kg(
            "MATCH (o:OutboxEntry {id:$id}) RETURN o.status AS status",
            id=event_id,
        ) == [{"status": "applied"}]
    finally:
        cleanup = recovered or first
        if cleanup is not None:
            _cleanup(cleanup, pg_kw, tree)
            cleanup.close()


def test_real_postgresql_operational_error_leaves_stable_intent_for_recovery(
    neo4j_driver, pg_kw
):
    tree = f"CRITIQUE_PG_DOWN_{uuid4().hex}"
    tag = "n"
    payload = CritiqueIn(
        arg_id="d1", attacks=tag, by="alice", kind="doubt", body="question"
    )
    event_id = history_event_id(tree, "critique", f"{tree}/{payload.arg_id}")
    bad_pg_kw = {**pg_kw, "host": "127.0.0.1", "port": 1, "connect_timeout": 1}
    unavailable = AppContainer(
        neo=_BorrowedDriver(neo4j_driver), mongo=_DummyMongo(), pg_kw=pg_kw
    )
    _require_writer(unavailable)
    # Model projection failure after election: the dedicated lease connection
    # remains live while new pooled history connections use the dead endpoint.
    unavailable._pg_kw = bad_pg_kw
    unavailable.kg(
        "CREATE (t:LakatosTree {name:$tree})-[:HAS_NODE]->"
        "(e:LakatosNode {name:$node_name, tag:$tag, verdict:'proof', "
        "valid_until_rebutted:true})",
        tree=tree,
        node_name=f"{tree}/{tag}",
        tag=tag,
    )
    recovered = None
    try:
        assert _service(unavailable, unavailable.hist).add_critique(
            tree, tag, payload
        )["ok"]
        assert _history_rows(pg_kw, tree) == []
        assert unavailable.kg(
            "MATCH (o:OutboxEntry {id:$id}) "
            "RETURN o.status AS status, o.reason AS reason",
            id=event_id,
        ) == [{"status": "pending", "reason": "critique_commit_intent"}]

        unavailable.close()
        unavailable = None
        recovered = AppContainer(
            neo=_BorrowedDriver(neo4j_driver), mongo=_DummyMongo(), pg_kw=pg_kw
        )
        _require_writer(recovered)
        result = recovered.reconcile_outbox()
        assert result["ok"] is True
        assert event_id in result["replayed"]
        rows = _history_rows(pg_kw, tree)
        assert len(rows) == 1
        assert _history_claims(pg_kw, tree) == [(event_id, rows[0][0])]
        retry = _service(recovered, recovered.hist).add_critique(tree, tag, payload)
        assert retry["idempotent"] is True
        assert _history_rows(pg_kw, tree) == rows
    finally:
        cleanup = recovered or unavailable
        if cleanup is not None:
            _cleanup(cleanup, pg_kw, tree)
            cleanup.close()


@pytest.mark.parametrize("legacy_kind", ["null", "outbox"])
def test_exact_retry_adopts_one_legacy_row_without_client_projection_retry(
    neo4j_driver, pg_kw, legacy_kind
):
    tree = f"CRITIQUE_LEGACY_{legacy_kind}_{uuid4().hex}"
    tag = "n"
    payload = CritiqueIn(
        arg_id="d1", attacks=tag, by="alice", kind="doubt", body="question"
    )
    history_payload = payload.model_dump()
    stable_id = history_event_id(tree, "critique", f"{tree}/{payload.arg_id}")
    legacy_id = None if legacy_kind == "null" else f"ob-{uuid4().hex[:24]}"
    with _legacy_history_database(
        pg_kw, tree, tag, history_payload, legacy_id
    ) as (isolated_kw, original_row_id):
        container = AppContainer(
            neo=_BorrowedDriver(neo4j_driver),
            mongo=_DummyMongo(),
            pg_kw=isolated_kw,
        )
        _require_writer(container)
        _seed_tree_and_argument(container, tree, tag, payload)
        if legacy_id is not None:
            container.kg(
                "CREATE (o:OutboxEntry {id:$id, tree:$tree, op:'critique', "
                "node_tag:$tag, payload:$payload, status:'applied', "
                "created_at:$ts, applied_at:$ts, reason:'PgOperationalError'})",
                id=legacy_id,
                tree=tree,
                tag=tag,
                payload=json.dumps(history_payload, ensure_ascii=False),
                ts="2026-07-01T00:00:00+00:00",
            )

        def crash_before_projection(*_args, **_kwargs):
            raise RuntimeError("simulated post-commit crash")

        try:
            with pytest.raises(RuntimeError, match="post-commit crash"):
                _service(container, crash_before_projection).add_critique(
                    tree, tag, payload
                )
            assert container.kg(
                "MATCH (o:OutboxEntry {id:$id}) RETURN o.status AS status",
                id=stable_id,
            ) == [{"status": "pending"}]

            result = container.reconcile_outbox()

            assert result["ok"] is True
            assert stable_id in result["replayed"]
            rows = _history_rows(isolated_kw, tree)
            assert len(rows) == 1
            assert rows[0] == (
                original_row_id,
                "critique",
                tag,
                history_payload,
                legacy_id,
            )
            assert _history_claims(isolated_kw, tree) == [
                (stable_id, original_row_id)
            ]
            if legacy_id is not None:
                assert container.kg(
                    "MATCH (o:OutboxEntry {id:$id}) "
                    "RETURN o.status AS status, o.adopted_by AS adopted_by",
                    id=legacy_id,
                ) == [{"status": "adopted", "adopted_by": stable_id}]
        finally:
            _cleanup(container, isolated_kw, tree)
            container.close()


def test_migrated_reconcile_materializes_missing_legacy_projection_as_stable_id(
    neo4j_driver, pg_kw
):
    tree = f"CRITIQUE_LEGACY_PENDING_{uuid4().hex}"
    tag = "n"
    payload = CritiqueIn(
        arg_id="d1", attacks=tag, by="alice", kind="doubt", body="question"
    )
    history_payload = payload.model_dump()
    stable_id = history_event_id(tree, "critique", f"{tree}/{payload.arg_id}")
    legacy_id = f"ob-{uuid4().hex[:24]}"
    with _legacy_history_database(
        pg_kw,
        tree,
        tag,
        history_payload,
        seed_history=False,
    ) as (isolated_kw, original_row_id):
        assert original_row_id is None
        container = AppContainer(
            neo=_BorrowedDriver(neo4j_driver),
            mongo=_DummyMongo(),
            pg_kw=isolated_kw,
        )
        _require_writer(container)
        _seed_tree_and_argument(container, tree, tag, payload)
        container.kg(
            "CREATE (o:OutboxEntry {id:$id, tree:$tree, op:'critique', "
            "node_tag:$tag, payload:$payload, status:'pending', "
            "created_at:$ts, reason:'PgOperationalError'})",
            id=legacy_id,
            tree=tree,
            tag=tag,
            payload=json.dumps(history_payload, ensure_ascii=False),
            ts="2026-07-01T00:00:00+00:00",
        )

        try:
            result = container.reconcile_outbox()

            assert result["ok"] is True
            assert legacy_id in result["replayed"]
            rows = _history_rows(isolated_kw, tree)
            assert len(rows) == 1
            assert rows[0][1:] == (
                "critique",
                tag,
                history_payload,
                stable_id,
            )
            assert _history_claims(isolated_kw, tree) == [
                (stable_id, rows[0][0])
            ]
            assert container.kg(
                "MATCH (o:OutboxEntry {id:$id}) "
                "RETURN o.status AS status, o.adopted_by AS adopted_by, "
                "o.payload AS payload",
                id=legacy_id,
            ) == [{
                "status": "adopted",
                "adopted_by": stable_id,
                "payload": json.dumps(
                    history_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ),
            }]
            with container.pg() as connection:
                contract = inspect_neo_outbox_contract(
                    container.kg,
                    projection_rows=pg_projection_rows(connection),
                )
            assert contract["ok"] is True
            assert contract["failures"] == []
        finally:
            _cleanup(container, isolated_kw, tree)
            container.close()


def test_concurrent_exact_retries_adopt_one_legacy_row(neo4j_driver, pg_kw):
    tree = f"CRITIQUE_CONCURRENT_{uuid4().hex}"
    tag = "n"
    payload = CritiqueIn(
        arg_id="d1", attacks=tag, by="alice", kind="doubt", body="question"
    )
    history_payload = payload.model_dump()
    stable_id = history_event_id(tree, "critique", f"{tree}/{payload.arg_id}")
    with _legacy_history_database(
        pg_kw, tree, tag, history_payload
    ) as (isolated_kw, original_row_id):
        container = AppContainer(
            neo=_BorrowedDriver(neo4j_driver),
            mongo=_DummyMongo(),
            pg_kw=isolated_kw,
        )
        _require_writer(container)
        _seed_tree_and_argument(container, tree, tag, payload)
        with container.pg():
            pass  # initialize the shared ThreadedConnectionPool before worker threads

        try:
            def retry():
                return _service(container, container.hist).add_critique(
                    tree, tag, payload
                )

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _index: retry(), range(2)))

            assert all(result["idempotent"] is True for result in results)
            rows = _history_rows(isolated_kw, tree)
            assert len(rows) == 1
            assert rows[0][0] == original_row_id
            assert rows[0][4] is None
            assert _history_claims(isolated_kw, tree) == [
                (stable_id, original_row_id)
            ]
            assert container.kg(
                "MATCH (o:OutboxEntry {id:$id}) "
                "RETURN count(o) AS count, collect(o.status) AS statuses",
                id=stable_id,
            ) == [{"count": 1, "statuses": ["applied"]}]
        finally:
            _cleanup(container, isolated_kw, tree)
            container.close()


def test_same_critique_identity_with_different_content_fails_loud(
    neo4j_driver, pg_kw
):
    tree = f"CRITIQUE_CONFLICT_{uuid4().hex}"
    tag = "n"
    old_payload = {
        "arg_id": "d1",
        "attacks": tag,
        "by": "alice",
        "kind": "doubt",
        "body": "old",
    }
    new_payload = {**old_payload, "body": "new"}
    stable_id = history_event_id(tree, "critique", f"{tree}/d1")
    with _legacy_history_database(
        pg_kw, tree, tag, old_payload
    ) as (isolated_kw, _original_row_id):
        container = AppContainer(
            neo=_BorrowedDriver(neo4j_driver),
            mongo=_DummyMongo(),
            pg_kw=isolated_kw,
        )
        _require_writer(container)
        try:
            with pytest.raises(HistoryEventConflict):
                container.hist(
                    tree, "critique", tag, new_payload, event_id=stable_id
                )
            rows = _history_rows(isolated_kw, tree)
            assert len(rows) == 1
            assert rows[0][3] == old_payload
            assert rows[0][4] is None
            assert _history_claims(isolated_kw, tree) == []
        finally:
            _cleanup(container, isolated_kw, tree)
            container.close()


@pytest.mark.parametrize("poison", ["before\x00after", "surrogate-\ud800"])
def test_pg_hostile_critique_never_commits_and_next_valid_write_recovers(
    neo4j_driver, pg_kw, poison
):
    tree = f"CRITIQUE_POISON_{uuid4().hex}"
    tag = "n"
    container = AppContainer(
        neo=_BorrowedDriver(neo4j_driver), mongo=_DummyMongo(), pg_kw=pg_kw
    )
    _require_writer(container)
    container.kg(
        "CREATE (t:LakatosTree {name:$tree})-[:HAS_NODE]->"
        "(e:LakatosNode {name:$node_name, tag:$tag, verdict:'proof', "
        "valid_until_rebutted:true})",
        tree=tree, node_name=f"{tree}/{tag}", tag=tag,
    )
    poisoned = CritiqueIn(
        arg_id="d1", attacks=tag, by="alice", kind="doubt", body=poison,
    )
    valid = CritiqueIn(
        arg_id="d1", attacks=tag, by="alice", kind="doubt", body="valid",
    )
    try:
        with pytest.raises(HTTPException) as exc:
            _service(container, container.hist).add_critique(tree, tag, poisoned)
        assert exc.value.status_code == 422
        assert container.kg(
            "MATCH (a:Argument {id:$id}) "
            "OPTIONAL MATCH (o:OutboxEntry {tree:$tree}) "
            "RETURN count(DISTINCT a) AS arguments, count(DISTINCT o) AS outboxes",
            id=f"{tree}/d1", tree=tree,
        ) == [{"arguments": 0, "outboxes": 0}]
        assert _history_rows(pg_kw, tree) == []

        result = _service(container, container.hist).add_critique(tree, tag, valid)
        assert result["ok"] is True
        assert len(_history_rows(pg_kw, tree)) == 1
    finally:
        _cleanup(container, pg_kw, tree)
        container.close()
