"""Cluster ④ — 운영 안전망 + 이론 정직성 (나생문 ROB-2/4/6, DEPLOY-1, T3-3/4).

healthz/503 graceful/opt-in auth/input 검증/kuhn 매직넘버 제거/grounded tier 값 검증.
"""
import importlib
import os

import pytest
from fastapi.testclient import TestClient


def load_app():
    os.environ.setdefault('NEO4J_URI', 'bolt://localhost:7687')
    os.environ.setdefault('NEO4J_USER', 'neo4j')
    os.environ.setdefault('NEO4J_PASSWORD', 'test')
    return importlib.import_module('server.app')


class _Cur:
    def execute(self, *a): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _Conn:
    def cursor(self, *a, **k): return _Cur()
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _all_up(monkeypatch, app):
    monkeypatch.setattr(app, 'kg', lambda *a, **k: [{'ok': 1}])
    monkeypatch.setattr(app, 'pg', lambda: _Conn())
    monkeypatch.setattr(app.MONGO, 'command', lambda *a, **k: {})


# ── DEPLOY-1: /healthz ──

def test_healthz_200_when_all_up(monkeypatch):
    app = load_app()
    _all_up(monkeypatch, app)
    r = TestClient(app.app).get('/healthz')
    assert r.status_code == 200 and r.json()['status'] == 'ok'


def test_healthz_503_when_neo4j_down(monkeypatch):
    app = load_app()
    _all_up(monkeypatch, app)

    def boom(*a, **k):
        raise RuntimeError('unreachable')

    monkeypatch.setattr(app, 'kg', boom)
    r = TestClient(app.app).get('/healthz')
    assert r.status_code == 503
    assert 'down' in r.json()['services']['neo4j'] and r.json()['status'] == 'degraded'


# ── ROB-4: opt-in bearer auth (mutating only) ──

def test_auth_blocks_post_without_token(monkeypatch):
    app = load_app()
    monkeypatch.setenv('LAKATOS_API_TOKEN', 'secret')
    r = TestClient(app.app).post('/api/tree/T/question', json={'qname': 'q1'})
    assert r.status_code == 401


# ── #4: B1 outbox 복구 운영 트리거(고아 메서드 → 운영 surface) ──

def test_reconcile_outbox_ops_endpoint(monkeypatch):
    app = load_app()
    fake = {'pending': 2, 'replayed': ['o1', 'o2'], 'replayed_count': 2,
            'still_pending': 0, 'pg_down': False}
    monkeypatch.setattr(app._container, 'reconcile_outbox', lambda: fake)
    r = TestClient(app.app).post('/api/ops/reconcile-outbox')
    assert r.status_code == 200 and r.json() == fake


def test_reconcile_outbox_ops_endpoint_is_auth_gated(monkeypatch):
    app = load_app()
    monkeypatch.setenv('LAKATOS_API_TOKEN', 'secret')   # mutating POST → Bearer 강제
    r = TestClient(app.app).post('/api/ops/reconcile-outbox')
    assert r.status_code == 401


def test_auth_allows_get_and_correct_token(monkeypatch):
    app = load_app()
    monkeypatch.setenv('LAKATOS_API_TOKEN', 'secret')
    monkeypatch.setattr(app, 'kg', lambda *a, **k: [])
    monkeypatch.setattr(app, 'hist', lambda *a, **k: None)
    c = TestClient(app.app)
    assert c.get('/api/trees').status_code == 200          # GET 은 무인증 통과
    r = c.post('/api/tree/T/question', json={'qname': 'q1'},
               headers={'authorization': 'Bearer secret'})
    assert r.status_code == 200                            # 올바른 토큰 통과


# ── ROB-6: 입력 검증 ──

def test_empty_tag_rejected_422(monkeypatch):
    app = load_app()
    r = TestClient(app.app).post('/api/tree/T/node', json={'tag': ''})
    assert r.status_code == 422                            # 빈 tag → Pydantic 422 (kg 도달 전)


def test_history_limit_clamped(monkeypatch):
    app = load_app()
    captured = {}

    class _RCur(_Cur):
        def execute(self, sql, params): captured['limit'] = params[-1]
        def fetchall(self): return []

    class _RConn(_Conn):
        def cursor(self, *a, **k): return _RCur()

    monkeypatch.setattr(app, 'pg', lambda: _RConn())
    app.history('T', limit=999999)
    assert captured['limit'] == 1000                       # 무제한 → 1000 cap


# ── T3-3: kuhn 매직넘버 → grounding ──

def test_kuhn_degeneration_threshold_from_grounding():
    from lakatos.programme.kuhn import DEGENERATION_K, incumbent_degenerating
    from lakatos.grounding import GROUNDED
    assert DEGENERATION_K == GROUNDED['abandon_k']['value']   # bare 3 제거, 레지스트리 출처
    assert incumbent_degenerating([], DEGENERATION_K) is True
    assert incumbent_degenerating([], DEGENERATION_K - 1) is False


# ── T3-4: grounded tier 값 유효성 ──

def test_grounded_registry_tiers_all_valid():
    from lakatos.grounding import GROUNDED
    valid = {'literature', 'policy_in_scale', 'policy'}
    assert GROUNDED and all(g.get('tier') in valid for g in GROUNDED.values())


def test_auth_blocks_get_snapshot_sideeffect(monkeypatch):
    # AUTH-BYPASS 수정: GET ?snapshot=true 는 DB insert side-effect → 토큰 없으면 401
    app = load_app()
    monkeypatch.setenv('LAKATOS_API_TOKEN', 'secret')
    r = TestClient(app.app).get('/api/tree/T/metrics?snapshot=true')
    assert r.status_code == 401


def test_healthz_does_not_leak_exception_class(monkeypatch):
    app = load_app()
    _all_up(monkeypatch, app)

    def boom(*a, **k):
        raise RuntimeError('SecretDriverName')

    monkeypatch.setattr(app, 'kg', boom)
    r = TestClient(app.app).get('/healthz')
    assert r.json()['services']['neo4j'] == 'down'   # 클래스명 'RuntimeError' 노출 안 함


# ── B4 OPS-ROB-1: bearer-auth ?snapshot 가 1/yes/on/True 변형도 게이트 (전엔 'true' 만) ──

def test_auth_blocks_get_snapshot_truthy_variants(monkeypatch):
    app = load_app()
    monkeypatch.setenv('LAKATOS_API_TOKEN', 'secret')
    c = TestClient(app.app)
    for v in ('1', 'yes', 'on', 'True', 'TRUE', 'true'):
        r = c.get(f'/api/tree/T/metrics?snapshot={v}')
        assert r.status_code == 401, f'snapshot={v} 가 인증 우회됨 (side-effect GET)'


# ── B4 OPS-COR-1: _parse_metric 가 과학적 표기 지수 보존 (전엔 절단) ──

def test_parse_metric_sci_notation_harness():
    from lakatos.harness import _parse_metric
    assert _parse_metric('metric=1.5e-3') == 0.0015
    assert _parse_metric('done metric: -2.0E+2') == -200.0
    assert _parse_metric('metric=0.279') == 0.279          # 회귀 0


def test_parse_metric_sci_notation_rebuild():
    from lakatos.io.rebuild import _parse_metric
    assert _parse_metric('metric=1.5e-3') == 0.0015
    assert _parse_metric('metric=0.279') == 0.279


# ── P6-1a OPS-DEAD-1: pg() ThreadedConnectionPool — 빌려/commit/반납, 예외 시 rollback ──

def test_pg_pool_borrows_commits_and_returns(monkeypatch):
    app = load_app()
    events = []

    class _C:
        def commit(self): events.append('commit')
        def rollback(self): events.append('rollback')

    class _Pool:
        def getconn(self): events.append('get'); return _C()
        def putconn(self, c): events.append('put')

    monkeypatch.setattr(app._container, 'pg_pool', lambda: _Pool())
    with app.pg() as c:
        events.append('use')
    assert events == ['get', 'use', 'commit', 'put']     # 누수 없음(반드시 putconn)


def test_pg_pool_rolls_back_on_error_and_returns(monkeypatch):
    app = load_app()
    events = []

    class _C:
        def commit(self): events.append('commit')
        def rollback(self): events.append('rollback')

    class _Pool:
        def getconn(self): return _C()
        def putconn(self, c): events.append('put')

    monkeypatch.setattr(app._container, 'pg_pool', lambda: _Pool())
    with pytest.raises(ValueError):
        with app.pg() as c:
            raise ValueError('boom')
    assert events == ['rollback', 'put']                 # 예외→rollback+반납(commit 안 함)
