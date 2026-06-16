"""AppContainer (server.container) 단위검증 — 자원층을 fake 어댑터로 단독 테스트.

합성 루트 추출의 핵심 가치: 모듈 전역 + `global` 변이 없이 자원 생명주기를
주입된 fake 로 검증할 수 있다(전엔 server.app 전역 monkeypatch 로만 가능했음).
# KG: span_lakatotree_server_architecture
"""
import pytest
from psycopg2 import OperationalError as PgOperationalError

from server.container import AppContainer


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


def test_hist_swallows_pg_operational_error(caplog):
    # PG 다운은 best-effort — 예외를 삼키고 경고만(KG=truth, 이력만 유실)
    class _PgDownContainer(AppContainer):
        def pg(self):
            raise PgOperationalError("pg down")
    c = _PgDownContainer(neo=_FakeNeo(), mongo=_FakeMongo(), pg_kw={})
    c.hist("tree", "op")   # raise 하면 테스트 실패 — 삼켜야 정상
