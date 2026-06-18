"""P7-D: 운영 견고성 — 배포/관측/수명주기 (TDD).

P6-1 pg pool 너머 운영 결함:
  OPS-INIT-1     oo_sink 하드코딩 내부 IP(localhost) 기본값 → 외부배포서 깨짐
  OPS-LIFECYCLE-1 Neo4j/Mongo 가 shutdown 시 close 안 됨 → 커넥션 누수
  OPS-BOOTSTRAP-1 run.sh schema 실패가 silent → 진짜 오류와 benign skip 미구분
  OPS-OBSERVABILITY-1 print-only 관측 → 명명 logger
"""
import importlib
import os

import pytest


def load_app():
    os.environ.setdefault('NEO4J_URI', 'bolt://localhost:7687')
    os.environ.setdefault('NEO4J_USER', 'neo4j')
    os.environ.setdefault('NEO4J_PASSWORD', 'test')
    return importlib.import_module('server.app')


# ── OPS-INIT-1: oo_sink — 내부 IP 하드코딩 제거, OO_URL 명시 강제 ───────────
def test_oo_sink_requires_explicit_url(monkeypatch):
    from lakatos.io import oo_sink
    monkeypatch.setenv('CONSUMER_LOGS_E2E', '1')
    monkeypatch.setenv('OO_PASS', 'secret')
    monkeypatch.delenv('OO_URL', raising=False)
    with pytest.raises(ValueError):
        oo_sink.ship([{'event': 'x'}], opener=lambda *a, **k: None)


def test_oo_sink_no_hardcoded_internal_ip():
    import lakatos.io.oo_sink as oo
    text = open(oo.__file__, encoding='utf-8').read()
    assert '10.147' not in text, 'oo_sink 에 내부 IP 하드코딩 잔존(외부배포 깨짐)'


def test_oo_sink_uses_explicit_url(monkeypatch):
    from lakatos.io import oo_sink
    monkeypatch.setenv('CONSUMER_LOGS_E2E', '1')
    monkeypatch.setenv('OO_PASS', 'secret')
    monkeypatch.setenv('OO_URL', 'http://oo.example:5080')
    seen = {}

    class _R:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"ok":1}'

    def opener(request, timeout):
        seen['url'] = request.full_url
        return _R()

    oo_sink.ship([{'event': 'x'}], opener=opener)
    assert seen['url'].startswith('http://oo.example:5080')


# ── OPS-LIFECYCLE-1: shutdown 시 드라이버 close ─────────────────────────────
def test_close_resources_closes_all(monkeypatch):
    # _close_resources 는 합성 루트(_container)에 위임 — fake 자원 컨테이너로 위임 검증.
    app = load_app()
    from server.container import AppContainer
    closed = []
    neo = type('N', (), {'close': lambda s: closed.append('neo')})()
    mongo = type('M', (), {'client': type('C', (), {'close': lambda s: closed.append('mongo')})()})()
    monkeypatch.setattr(app, '_container', AppContainer(neo=neo, mongo=mongo, pg_kw={}))
    errs = app._close_resources()
    assert set(closed) == {'neo', 'mongo'}   # pg 풀 lazy 미초기화 → skip
    assert errs == []


def test_close_resources_collects_errors(monkeypatch):
    app = load_app()
    from server.container import AppContainer
    neo = type('N', (), {'close': lambda s: (_ for _ in ()).throw(RuntimeError('boom'))})()
    mongo = type('M', (), {'client': type('C', (), {'close': lambda s: None})()})()
    monkeypatch.setattr(app, '_container', AppContainer(neo=neo, mongo=mongo, pg_kw={}))
    errs = app._close_resources()
    assert any('neo4j' in e for e in errs)


def test_lifespan_closes_on_shutdown(monkeypatch):
    from fastapi.testclient import TestClient
    from server.container import AppContainer
    app = load_app()
    closed = []
    neo = type('N', (), {'close': lambda s: closed.append('neo')})()
    mongo = type('M', (), {'client': type('C', (), {'close': lambda s: closed.append('mongo')})()})()
    monkeypatch.setattr(app, '_container', AppContainer(neo=neo, mongo=mongo, pg_kw={}))
    with TestClient(app.app):
        pass                                              # __exit__ → shutdown → _close_resources
    assert 'neo' in closed and 'mongo' in closed


# ── OPS-OBSERVABILITY-1: 명명 logger ────────────────────────────────────────
def test_server_has_named_logger():
    app = load_app()
    assert app.logger.name == 'lakatotree.server'


# ── OPS-BOOTSTRAP-1: run.sh schema 실패 구분 (source 가드) ──────────────────
def test_run_sh_schema_not_blanket_suppressed():
    text = open(os.path.join(os.path.dirname(__file__), '..', 'server', 'run.sh'), encoding='utf-8').read()
    schema_block = text.split('schema.sql', 1)[1][:400]
    assert 'ON_ERROR_STOP' in text, 'schema.sql 오류가 비-0 종료하도록 ON_ERROR_STOP 필요'
    # PG 가동중 schema 실패 시 loud exit (진짜 오류와 benign skip 구분)
    assert 'exit 1' in text, 'schema.sql 진짜 실패 시 exit 1 (silent skip 금지)'
