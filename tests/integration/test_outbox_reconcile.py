"""B1 실DB 영수증 (override 2026-06-21): transactional-outbox + 멱등 reconcile, real Neo4j + real PG.

mock 으로는 못 떨군 영수증: PG 다운 시 hist 가 이력을 KG OutboxEntry(정본)에 기록(유실 방지)하고,
PG 회복 후 reconcile_outbox 가 PG history 에 *정확히 1행* 재적용(ON CONFLICT event_id) + outbox applied
표기 → 재실행해도 이중적재 없음(멱등). KG=truth/PG=best-effort 불변 유지하되 발산이 auditable+복구가능.
"""
import psycopg2
import pytest
from uuid import uuid4

from server.container import AppContainer

pytestmark = pytest.mark.integration


class _DummyMongo:
    def close(self):
        pass


class _BorrowedDriver:
    def __init__(self, driver):
        self._driver = driver

    def session(self, *args, **kwargs):
        return self._driver.session(*args, **kwargs)

    def close(self):
        pass


def _pg_count(pg_kw, tree):
    conn = psycopg2.connect(**pg_kw)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM history WHERE tree=%s", (tree,))
            return cur.fetchone()[0]
    finally:
        conn.close()


def test_pg_down_records_outbox_then_reconcile_replays_once(neo4j_driver, pg_kw):
    name = f"b1_outbox_{uuid4().hex}"
    bad = {**pg_kw, "host": "127.0.0.1", "port": 1, "connect_timeout": 1}
    c_down = AppContainer(
        neo=_BorrowedDriver(neo4j_driver), mongo=_DummyMongo(), pg_kw=pg_kw
    )
    c_up = None
    try:
        # Pending history intents are now ownership-bound to an existing tree;
        # this receipt exercises recovery, not the missing-tree rejection gate.
        c_down.kg("CREATE (t:LakatosTree {name:$tree})", tree=name)
        assert c_down.acquire_writer_lease() is True
        # The dedicated election session remains valid while a fresh history
        # connection observes the simulated outage.  This models a failure
        # after authority was acquired, rather than an impossible acquisition
        # through an already-dead endpoint.
        c_down._pg_kw = bad
        # 1) PG 다운 → hist 가 이 테스트 전용 pending intent를 KG에 남긴다.
        c_down.hist(name, "node_add", "v", {"verdict": "progressive"})
        pending = c_down.kg(
            "MATCH (o:OutboxEntry {tree:$tree, status:'pending'}) "
            "RETURN o.id AS id",
            tree=name,
        )
        assert len(pending) == 1
        event_id = pending[0]["id"]
        assert _pg_count(pg_kw, name) == 0

        # 2) A fresh healthy process replays only the captured identity.
        c_down.close()
        c_down = None
        c_up = AppContainer(
            neo=_BorrowedDriver(neo4j_driver), mongo=_DummyMongo(), pg_kw=pg_kw
        )
        assert c_up.acquire_writer_lease() is True
        result = c_up.reconcile_outbox()
        assert event_id in result["replayed"]
        assert _pg_count(pg_kw, name) == 1
        assert c_up.kg(
            "MATCH (o:OutboxEntry {id:$id}) RETURN o.status AS status",
            id=event_id,
        ) == [{"status": "applied"}]

        # 3) A second replay is a no-op for this identity.
        assert event_id not in c_up.reconcile_outbox()["replayed"]
        assert _pg_count(pg_kw, name) == 1
    finally:
        try:
            connection = psycopg2.connect(**pg_kw)
            try:
                with connection, connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM history_event_claims WHERE history_id IN "
                        "(SELECT id FROM history WHERE tree=%s)",
                        (name,),
                    )
                    cursor.execute("DELETE FROM history WHERE tree=%s", (name,))
            finally:
                connection.close()
        finally:
            try:
                with neo4j_driver.session() as session:
                    session.run(
                        "MATCH (o:OutboxEntry {tree:$tree}) DETACH DELETE o",
                        tree=name,
                    ).consume()
                    session.run(
                        "MATCH (t:LakatosTree {name:$tree}) DETACH DELETE t",
                        tree=name,
                    ).consume()
            finally:
                for container in (c_up, c_down):
                    if container is not None:
                        container.close()
