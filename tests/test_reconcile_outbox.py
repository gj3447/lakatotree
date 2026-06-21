"""B1 (override 2026-06-21): transactional-outbox + 멱등 reconcile 헤르메틱 검증.

hist(PG best-effort) 실패를 *조용히 잃지 않고* KG OutboxEntry(정본)에 기록 → reconcile_outbox 가 멱등
재적용(ON CONFLICT event_id). KG=truth/PG=best-effort 불변 유지하되 발산을 auditable 화. (실DB 영수증은
tests/integration/test_outbox_reconcile.py.)
"""
import contextlib

from psycopg2 import OperationalError as PgOperationalError

from lakatos.io.reconcile import outbox_id, plan_reconcile
from server.container import AppContainer


# ── 순수 로직 ────────────────────────────────────────────────────────────────
def test_outbox_id_deterministic_and_ts_sensitive():
    a = outbox_id('t', 'op', 'n', {'x': 1}, '2026-06-21T01:00:00')
    assert a == outbox_id('t', 'op', 'n', {'x': 1}, '2026-06-21T01:00:00')   # 결정적(중복 pending 방지)
    assert a != outbox_id('t', 'op', 'n', {'x': 1}, '2026-06-21T02:00:00')   # 다른 시점 구분
    assert a.startswith('ob-')


def test_plan_reconcile_skips_already_applied():
    pending = [{'id': 'a'}, {'id': 'b'}, {'id': 'c'}]
    p = plan_reconcile(pending, applied_ids={'b'})
    assert [e['id'] for e in p['to_replay']] == ['a', 'c']     # 멱등: 적용분 건너뜀
    assert p['already_applied'] == ['b'] and p['pending_total'] == 3 and p['replay_count'] == 2


# ── container 통합(가짜 neo/pg) ──────────────────────────────────────────────
class _Res:
    def __init__(self, rows): self._rows = rows
    def data(self): return self._rows


class _Sess:
    def __init__(self, handler, log): self._h, self._log = handler, log
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def run(self, cypher, **kw):
        self._log.append((cypher, kw))
        return _Res(self._h(cypher, kw))


class _Neo:
    def __init__(self, handler, log): self._h, self._log = handler, log
    def session(self): return _Sess(self._h, self._log)
    def close(self): pass


class _Cur:
    def __init__(self, log): self._log = log
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, sql, params=None): self._log.append((sql, params))


class _Conn:
    def __init__(self, log): self._log = log
    def cursor(self): return _Cur(self._log)


def test_hist_records_outbox_entry_on_pg_failure():
    """PG 다운 시 hist 가 이력을 잃지 않고 KG OutboxEntry(pending)로 기록."""
    neolog = []
    c = AppContainer(neo=_Neo(lambda cy, kw: [], neolog), mongo=object(), pg_kw={})

    @contextlib.contextmanager
    def _down():
        raise PgOperationalError('pg down')
        yield  # noqa: unreachable
    c.pg = _down
    c.hist('T', 'test_result', 'v', {'verdict': 'progressive'})
    merges = [cy for cy, _ in neolog if 'OutboxEntry' in cy]
    assert merges and 'MERGE (o:OutboxEntry' in merges[0]      # 유실 대신 outbox 기록
    assert any("status='pending'" in cy for cy in merges)


def test_reconcile_outbox_replays_pending_with_idempotent_upsert():
    """pending OutboxEntry 를 PG 에 ON CONFLICT 재적용 + applied 표기(재실행 시 skip=멱등)."""
    neolog, pglog = [], []

    def handler(cypher, kw):
        if 'OutboxEntry' in cypher and 'pending' in cypher and 'RETURN' in cypher:
            return [{'id': 'ob-1', 'tree': 'T', 'op': 'test_result',
                     'node_tag': 'v', 'payload': '{"verdict":"progressive"}'}]
        return []
    c = AppContainer(neo=_Neo(handler, neolog), mongo=object(), pg_kw={})

    @contextlib.contextmanager
    def _ok():
        yield _Conn(pglog)
    c.pg = _ok
    out = c.reconcile_outbox()
    assert out['replayed_count'] == 1 and out['replayed'] == ['ob-1'] and out['still_pending'] == 0
    inserts = [sql for sql, _ in pglog if 'INSERT INTO history' in sql]
    assert inserts and 'ON CONFLICT (event_id)' in inserts[0] and 'DO NOTHING' in inserts[0]   # 멱등 upsert
    assert any("status='applied'" in cy for cy, _ in neolog)               # outbox applied 표기
