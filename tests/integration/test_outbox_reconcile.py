"""B1 실DB 영수증 (override 2026-06-21): transactional-outbox + 멱등 reconcile, real Neo4j + real PG.

mock 으로는 못 떨군 영수증: PG 다운 시 hist 가 이력을 KG OutboxEntry(정본)에 기록(유실 방지)하고,
PG 회복 후 reconcile_outbox 가 PG history 에 *정확히 1행* 재적용(ON CONFLICT event_id) + outbox applied
표기 → 재실행해도 이중적재 없음(멱등). KG=truth/PG=best-effort 불변 유지하되 발산이 auditable+복구가능.
"""
import psycopg2
import pytest

from server.container import AppContainer

pytestmark = pytest.mark.integration


class _DummyMongo:
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
    name = "b1_outbox"
    # 이 테스트 트리의 잔여 outbox 정리(공유 세션 DB 격리)
    AppContainer(neo=neo4j_driver, mongo=_DummyMongo(), pg_kw=pg_kw).kg(
        "MATCH (o:OutboxEntry {tree:$t}) DETACH DELETE o", t=name)

    # 1) PG 다운(잘못된 포트) → hist 가 KG OutboxEntry(pending)로 기록(유실 아님)
    bad = dict(pg_kw, host="127.0.0.1", port=1)
    c_down = AppContainer(neo=neo4j_driver, mongo=_DummyMongo(), pg_kw=bad)
    c_down.hist(name, "test_result", "v", {"verdict": "progressive"})
    pend = c_down.kg("MATCH (o:OutboxEntry {tree:$t, status:'pending'}) RETURN count(o) AS c", t=name)
    assert pend[0]["c"] == 1                                   # 유실 대신 outbox 기록
    assert _pg_count(pg_kw, name) == 0                         # PG 엔 아직 없음

    # 2) PG 회복 → reconcile 가 정확히 1행 재적용 + outbox applied
    c_up = AppContainer(neo=neo4j_driver, mongo=_DummyMongo(), pg_kw=pg_kw)
    out = c_up.reconcile_outbox()
    assert out["replayed_count"] >= 1 and out["still_pending"] == out["pending"] - out["replayed_count"]
    assert _pg_count(pg_kw, name) == 1                         # PG 에 1행 복구
    pend2 = c_up.kg("MATCH (o:OutboxEntry {tree:$t, status:'pending'}) RETURN count(o) AS c", t=name)
    assert pend2[0]["c"] == 0                                  # 더 이상 pending 아님(applied)

    # 3) 멱등: 재실행해도 이중적재 없음
    c_up.reconcile_outbox()
    assert _pg_count(pg_kw, name) == 1                         # 여전히 1행(ON CONFLICT/applied 멱등)
