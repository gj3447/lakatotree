"""Cluster ④ — 운영 안전망 + 이론 정직성 (나생문 ROB-2/4/6, DEPLOY-1, T3-3/4).

healthz/503 graceful/opt-in auth/input 검증/kuhn 매직넘버 제거/grounded tier 값 검증.
"""
import asyncio
import importlib
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi.testclient import TestClient
from psycopg2 import OperationalError as PgOperationalError


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
    monkeypatch.setattr(app.MONGO, 'list_collection_names', lambda *a, **k: [])
    monkeypatch.setattr(app._container, 'writer_lease_ready', lambda: True)
    app._storage_contract_state.update(
        checked=True, ok=True, failures=[], checked_at="2026-08-02T00:00:00+00:00"
    )


def _writer_up(monkeypatch, app):
    monkeypatch.setattr(app._container, 'acquire_writer_lease', lambda: True)
    monkeypatch.setattr(app._container, 'writer_lease_ready', lambda: True)
    monkeypatch.setattr(app._container, 'release_writer_lease', lambda: None)


# ── DEPLOY-1: /healthz ──

def test_healthz_200_when_all_up(monkeypatch):
    app = load_app()
    _all_up(monkeypatch, app)
    r = TestClient(app.app).get('/healthz')
    assert r.status_code == 200 and r.json()['status'] == 'ok'


def test_readyz_requires_full_cached_storage_authority(monkeypatch):
    app = load_app()
    _all_up(monkeypatch, app)
    client = TestClient(app.app)
    assert client.get('/readyz').status_code == 200

    app._storage_contract_state.update(
        checked=True,
        ok=False,
        failures=['predeploy.receipt.invalid'],
        checked_at='2026-08-02T00:00:00+00:00',
    )
    degraded = client.get('/readyz')
    assert degraded.status_code == 503
    assert degraded.json()['services']['critique_history'] == 'disabled'
    assert client.get('/healthz').status_code == 200


def test_runtime_history_divergence_immediately_closes_readyz_and_critique_gate(
    monkeypatch,
):
    app = load_app()
    _all_up(monkeypatch, app)
    monkeypatch.setattr(
        app._container,
        'pg',
        lambda: (_ for _ in ()).throw(PgOperationalError('pg down')),
    )
    monkeypatch.setattr(
        app._container, '_record_pending_outbox', lambda **_kwargs: None
    )

    app.hist('T', 'runtime_probe', payload={'probe': True})

    response = TestClient(app.app).get('/readyz')
    assert response.status_code == 503
    assert response.json()['services']['critique_history'] == 'disabled'
    with pytest.raises(app.HTTPException) as captured:
        app._require_critique_history_ready()
    assert captured.value.status_code == 503


def test_stale_green_audit_cannot_overwrite_newer_runtime_invalidation(monkeypatch):
    app = load_app()
    _writer_up(monkeypatch, app)
    started = Event()
    release = Event()
    healthy = {
        'ok': True,
        'postgresql': {'failures': []},
        'neo4j': {'failures': []},
        'predeploy_receipt': {'failures': []},
    }

    def delayed_readback():
        started.set()
        assert release.wait(timeout=5)
        return healthy

    monkeypatch.setattr(app, '_storage_contract_readback', delayed_readback)
    monkeypatch.setattr(
        app,
        '_semantic_contract_readback',
        lambda: {'ok': True, 'failures': [], 'violations': []},
    )
    with app._storage_contract_state_lock:
        app._storage_contract_state.update(
            checked=True,
            ok=False,
            failures=['before_refresh'],
            checked_at=None,
            generation=100,
        )

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(app._refresh_storage_contract_state)
        assert started.wait(timeout=5)
        app._invalidate_storage_contract_state('runtime.history_projection.pending')
        release.set()
        result = future.result(timeout=5)

    assert result['ok'] is False
    assert result['failures'] == ['runtime.history_projection.pending']
    assert result['generation'] == 101


def test_stale_green_audit_cannot_overwrite_semantic_invalidation(monkeypatch):
    app = load_app()
    _writer_up(monkeypatch, app)
    started = Event()
    release = Event()

    def delayed_readback():
        started.set()
        assert release.wait(timeout=5)
        return {
            'ok': True,
            'postgresql': {'failures': []},
            'neo4j': {'failures': []},
            'predeploy_receipt': {'failures': []},
        }

    monkeypatch.setattr(app, '_storage_contract_readback', delayed_readback)
    monkeypatch.setattr(
        app,
        '_semantic_contract_readback',
        lambda: {'ok': True, 'failures': [], 'violations': []},
    )
    with app._storage_contract_state_lock:
        app._storage_contract_state.update(
            checked=True,
            ok=False,
            failures=['before_refresh'],
            checked_at=None,
            generation=200,
        )

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(app._refresh_storage_contract_state)
        assert started.wait(timeout=5)
        service = app._evidence_claim_service()
        service._signal_semantic_divergence(
            'runtime.critique_standing.reconciliation_failed'
        )
        release.set()
        result = future.result(timeout=5)

    assert result['ok'] is False
    assert result['failures'] == [
        'runtime.critique_standing.reconciliation_failed'
    ]
    assert result['generation'] == 201


def test_healthz_503_when_neo4j_down(monkeypatch):
    app = load_app()
    _all_up(monkeypatch, app)

    def boom(*a, **k):
        raise RuntimeError('unreachable')

    monkeypatch.setattr(app, 'kg', boom)
    r = TestClient(app.app).get('/healthz')
    assert r.status_code == 503
    assert 'down' in r.json()['services']['neo4j'] and r.json()['status'] == 'degraded'


def test_healthz_503_when_mongo_ping_works_but_database_read_is_unauthorized(monkeypatch):
    """Readiness must catch the common false-green where unauthenticated ping still succeeds."""
    app = load_app()
    _all_up(monkeypatch, app)

    def unauthorized(*_a, **_k):
        raise RuntimeError('not authorized on lakatos')

    monkeypatch.setattr(app.MONGO, 'list_collection_names', unauthorized)
    r = TestClient(app.app).get('/healthz')
    assert r.status_code == 503
    assert r.json()['services']['mongo'] == 'down'


# ── ROB-4: opt-in bearer auth (mutating only) ──

def test_auth_blocks_post_without_token(monkeypatch):
    app = load_app()
    monkeypatch.setenv('LAKATOS_API_TOKEN', 'secret')
    r = TestClient(app.app).post('/api/tree/T/question', json={'qname': 'q1'})
    assert r.status_code == 401


# ── #4: B1 outbox 복구 운영 트리거(고아 메서드 → 운영 surface) ──

def test_reconcile_outbox_ops_endpoint(monkeypatch):
    app = load_app()
    _writer_up(monkeypatch, app)
    monkeypatch.setenv('LAKATOS_API_TOKEN', 'operator-secret')
    fake = {'ok': True, 'pending': 2, 'replayed': ['o1', 'o2'],
            'replayed_count': 2, 'still_pending': 0, 'pg_down': False}
    monkeypatch.setattr(
        app,
        '_require_reconciliation_authority',
        lambda: {'predeploy_receipt': {'ok': True}},
    )
    monkeypatch.setattr(
        app,
        '_refresh_storage_contract_state',
        lambda: {'ok': True, 'failures': []},
    )
    monkeypatch.setattr(app, '_reconcile_durable_critique_state', lambda: fake)
    r = TestClient(app.app).post(
        '/api/ops/reconcile-outbox',
        headers={'authorization': 'Bearer operator-secret'},
    )
    assert r.status_code == 200
    assert r.json() == {**fake, 'storage_contract_ok': True}


def test_reconcile_outbox_endpoint_never_returns_green_after_failed_readback(
    monkeypatch,
):
    app = load_app()
    _writer_up(monkeypatch, app)
    monkeypatch.setenv('LAKATOS_API_TOKEN', 'operator-secret')
    monkeypatch.setattr(app, '_require_reconciliation_authority', lambda: {})
    monkeypatch.setattr(
        app,
        '_reconcile_durable_critique_state',
        lambda: {'ok': True, 'replayed': ['o1'], 'still_pending': 0},
    )
    monkeypatch.setattr(
        app,
        '_refresh_storage_contract_state',
        lambda: {'ok': False, 'failures': ['cross_store.outbox_projection']},
    )
    r = TestClient(app.app).post(
        '/api/ops/reconcile-outbox',
        headers={'authorization': 'Bearer operator-secret'},
    )
    assert r.status_code == 503
    assert r.json()['ok'] is False
    assert r.json()['storage_contract_ok'] is False


def test_reconcile_outbox_ops_endpoint_is_auth_gated(monkeypatch):
    app = load_app()
    monkeypatch.setenv('LAKATOS_API_TOKEN', 'secret')   # mutating POST → Bearer 강제
    r = TestClient(app.app).post('/api/ops/reconcile-outbox')
    assert r.status_code == 401


def test_reconcile_outbox_ops_endpoint_rejects_open_posture(monkeypatch):
    app = load_app()
    monkeypatch.delenv('LAKATOS_API_TOKEN', raising=False)
    monkeypatch.setattr(
        app,
        '_reconcile_durable_critique_state',
        lambda: (_ for _ in ()).throw(AssertionError('mutation reached')),
    )
    r = TestClient(app.app).post('/api/ops/reconcile-outbox')
    assert r.status_code == 403


def test_storage_contract_refresh_endpoint_rejects_open_posture(monkeypatch):
    app = load_app()
    monkeypatch.delenv('LAKATOS_API_TOKEN', raising=False)
    monkeypatch.setattr(
        app,
        '_refresh_storage_contract_state',
        lambda: (_ for _ in ()).throw(AssertionError('audit reached')),
    )
    response = TestClient(app.app).post('/api/ops/critique-history-contract')
    assert response.status_code == 403


# ── #③ outbox 운영 경화: startup 자동복구 + pending depth 관측 (2PC 대신 outbox 강화) ──

def test_startup_reconcile_runs_outbox_recovery(monkeypatch):
    app = load_app()
    _writer_up(monkeypatch, app)
    calls = []
    def fake():
        calls.append(1)
        return {
            'ok': True, 'pending': 0, 'replayed': [], 'replayed_count': 0,
            'still_pending': 0, 'pg_down': False, 'conflicts': [],
            'conflict_count': 0,
        }
    monkeypatch.setattr(
        app, '_reconcile_critique_semantics',
        lambda: {'ok': True, 'failures': [], 'violations': []},
    )
    monkeypatch.setattr(app._container, 'reconcile_outbox', fake)
    r = app._startup_reconcile()
    assert calls == [1, 1] and r['replayed_count'] == 0


def test_durable_reconcile_projects_cause_before_semantic_effect(monkeypatch):
    app = load_app()
    _writer_up(monkeypatch, app)
    order = []
    passes = iter((
        {
            'ok': True, 'pending': 1, 'replayed': ['critique'],
            'replayed_count': 1, 'still_pending': 0, 'pg_down': False,
            'conflicts': [], 'conflict_count': 0,
        },
        {
            'ok': True, 'pending': 1, 'replayed': ['standing'],
            'replayed_count': 1, 'still_pending': 0, 'pg_down': False,
            'conflicts': [], 'conflict_count': 0,
        },
    ))

    def outbox():
        report = next(passes)
        order.append(report['replayed'][0])
        return report

    def semantic():
        order.append('semantic')
        return {'ok': True, 'failures': [], 'violations': []}

    monkeypatch.setattr(app._container, 'reconcile_outbox', outbox)
    monkeypatch.setattr(app, '_reconcile_critique_semantics', semantic)

    result = app._reconcile_durable_critique_state()

    assert order == ['critique', 'semantic', 'standing']
    assert result['ok'] is True
    assert result['replayed'] == ['critique', 'standing']


def test_startup_reconcile_swallows_errors(monkeypatch):
    app = load_app()
    def boom():
        raise RuntimeError('kg down at boot')
    monkeypatch.setattr(
        app, '_reconcile_critique_semantics',
        lambda: {'ok': True, 'failures': [], 'violations': []},
    )
    monkeypatch.setattr(app._container, 'reconcile_outbox', boom)
    assert app._startup_reconcile() is None   # 부팅 복구 실패가 서버 기동을 막지 않음


def test_startup_reconcile_fails_closed_for_serving(monkeypatch):
    app = load_app()
    monkeypatch.setattr(
        app, '_reconcile_critique_semantics',
        lambda: {'ok': True, 'failures': [], 'violations': []},
    )
    monkeypatch.setattr(
        app._container,
        'reconcile_outbox',
        lambda: {'ok': False, 'still_pending': 1, 'conflict_count': 1},
    )
    with pytest.raises(app.StorageContractError):
        app._startup_reconcile(fail_closed=True)


def test_lifespan_invalid_receipt_never_mutates_reconciliation(monkeypatch):
    app = load_app()
    calls = []
    monkeypatch.setattr(
        app,
        '_storage_contract_readback',
        lambda: {
            'contract_id': app.CONTRACT_ID,
            'postgresql': {'contract_id': app.CONTRACT_ID,
                           'ok': True, 'failures': []},
            'neo4j': {'contract_id': app.CONTRACT_ID,
                       'ok': False, 'failures': ['neo4j.outbox.pending']},
            'predeploy_receipt': {'contract_id': app.CONTRACT_ID,
                                  'ok': False, 'failures': ['invalid']},
        },
    )
    monkeypatch.setattr(
        app, '_startup_reconcile',
        lambda **_kwargs: calls.append('reconcile'),
    )
    monkeypatch.setattr(
        app, '_refresh_storage_contract_state',
        lambda: {'ok': False, 'failures': ['predeploy.receipt.invalid']},
    )
    monkeypatch.setattr(app, '_close_resources', lambda: [])

    async def exercise():
        async with app._lifespan(app.app):
            assert calls == []

    asyncio.run(exercise())


def test_lifespan_authorized_pending_reconciles_then_uses_second_audit(monkeypatch):
    app = load_app()
    calls = []
    initial = {
        'contract_id': app.CONTRACT_ID,
        'postgresql': {'contract_id': app.CONTRACT_ID,
                       'ok': True, 'failures': []},
        'neo4j': {'contract_id': app.CONTRACT_ID,
                   'ok': False, 'failures': ['neo4j.outbox.pending']},
        'predeploy_receipt': {'contract_id': app.CONTRACT_ID,
                              'ok': True, 'failures': []},
    }
    monkeypatch.setattr(app, '_storage_contract_readback', lambda: initial)
    monkeypatch.setattr(
        app, '_startup_reconcile',
        lambda **_kwargs: calls.append('reconcile') or {'ok': True},
    )
    monkeypatch.setattr(
        app,
        '_refresh_storage_contract_state',
        lambda: calls.append('audit') or {
            'ok': False, 'failures': ['cross_store.outbox_projection'],
        },
    )
    monkeypatch.setattr(app, '_close_resources', lambda: [])
    monkeypatch.setattr(app._container, 'acquire_writer_lease', lambda: True)

    async def exercise():
        async with app._lifespan(app.app):
            assert calls == ['reconcile', 'audit']

    asyncio.run(exercise())


def test_explicit_contract_refresh_rejects_reachable_but_wrong_storage(monkeypatch):
    app = load_app()
    _all_up(monkeypatch, app)
    monkeypatch.setenv('LAKATOS_API_TOKEN', 'operator-secret')
    monkeypatch.setattr(app, '_storage_contract_readback', lambda: {'ok': False})
    monkeypatch.setattr(
        app, '_semantic_contract_readback',
        lambda: {'ok': True, 'failures': [], 'violations': []},
    )
    r = TestClient(app.app).post(
        '/api/ops/critique-history-contract',
        headers={'authorization': 'Bearer operator-secret'},
    )
    assert r.status_code == 503
    assert r.json()['ok'] is False


def test_storage_contract_readback_requires_pinned_predeploy_receipt(monkeypatch):
    app = load_app()
    monkeypatch.delenv('LAKATOS_STORAGE_PREDEPLOY_RECEIPT', raising=False)
    monkeypatch.delenv('LAKATOS_STORAGE_PREDEPLOY_RECEIPT_SHA256', raising=False)
    monkeypatch.setattr(app, 'pg', lambda: _Conn())
    monkeypatch.setattr(
        app, 'inspect_pg_history_contract',
        lambda _conn: {'ok': True, 'failures': []},
    )
    monkeypatch.setattr(app, 'pg_projection_rows', lambda _conn: [])
    monkeypatch.setattr(
        app, 'inspect_neo_outbox_contract',
        lambda *_a, **_k: {'ok': True, 'failures': []},
    )

    report = app._storage_contract_readback()

    assert report['ok'] is False
    assert report['predeploy_receipt']['failures'] == [
        'predeploy.receipt.path_missing',
        'predeploy.receipt.sha256_missing',
    ]


def test_storage_contract_readback_consumes_exact_pinned_receipt(monkeypatch):
    app = load_app()
    monkeypatch.setenv('LAKATOS_STORAGE_PREDEPLOY_RECEIPT', '/receipt.json')
    monkeypatch.setenv('LAKATOS_STORAGE_PREDEPLOY_RECEIPT_SHA256', 'a' * 64)
    monkeypatch.setattr(app, 'pg', lambda: _Conn())
    monkeypatch.setattr(
        app, 'inspect_pg_history_contract',
        lambda _conn: {'ok': True, 'failures': []},
    )
    monkeypatch.setattr(app, 'pg_projection_rows', lambda _conn: [])
    monkeypatch.setattr(
        app, 'inspect_neo_outbox_contract',
        lambda *_a, **_k: {'ok': True, 'failures': []},
    )
    monkeypatch.setattr(
        app, 'verify_predeploy_receipt',
        lambda *_a, **_k: {'ok': True, 'failures': [], 'contract_id': 'ok'},
    )

    report = app._storage_contract_readback()

    assert report['ok'] is True
    assert report['predeploy_receipt']['ok'] is True


def test_critique_ready_uses_cached_startup_audit_without_ledger_rescan(monkeypatch):
    app = load_app()
    app._storage_contract_state.update(
        checked=True, ok=True, failures=[], checked_at="2026-08-02T00:00:00+00:00"
    )
    monkeypatch.setattr(
        app,
        '_storage_contract_readback',
        lambda: (_ for _ in ()).throw(AssertionError('request-path ledger rescan')),
    )
    monkeypatch.setattr(app._container, 'writer_lease_ready', lambda: True)

    app._require_critique_history_ready()

    app._storage_contract_state.update(
        checked=True,
        ok=False,
        failures=['neo4j.outbox.pending'],
        checked_at="2026-08-02T00:00:01+00:00",
    )
    with pytest.raises(app.HTTPException) as exc:
        app._require_critique_history_ready()
    assert exc.value.status_code == 503
    assert app._storage_contract_state['failures'] == ['neo4j.outbox.pending']


@pytest.mark.parametrize(
    ('report', 'expected'),
    [
        ({
            'contract_id': 'lakatotree-critique-history-storage/v1',
            'postgresql': {'contract_id': 'lakatotree-critique-history-storage/v1',
                           'ok': True, 'failures': []},
            'neo4j': {'contract_id': 'lakatotree-critique-history-storage/v1',
                       'ok': False, 'failures': ['neo4j.outbox.pending']},
            'predeploy_receipt': {'contract_id': 'lakatotree-critique-history-storage/v1',
                                  'ok': True, 'failures': []},
        }, True),
        ({
            'contract_id': 'lakatotree-critique-history-storage/v1',
            'postgresql': {'contract_id': 'lakatotree-critique-history-storage/v1',
                           'ok': True, 'failures': []},
            'neo4j': {'contract_id': 'lakatotree-critique-history-storage/v1',
                       'ok': True, 'failures': []},
            'predeploy_receipt': {'contract_id': 'lakatotree-critique-history-storage/v1',
                                  'ok': False, 'failures': []},
        }, False),
        ({
            'contract_id': 'lakatotree-critique-history-storage/v1',
            'postgresql': {'contract_id': 'lakatotree-critique-history-storage/v1',
                           'ok': True, 'failures': []},
            'neo4j': {'contract_id': 'lakatotree-critique-history-storage/v1',
                       'ok': False, 'failures': ['neo4j.argument.binding']},
            'predeploy_receipt': {'contract_id': 'lakatotree-critique-history-storage/v1',
                                  'ok': True, 'failures': []},
        }, False),
        ({
            'contract_id': 'lakatotree-critique-history-storage/v1',
            'postgresql': {'contract_id': 'lakatotree-critique-history-storage/v1',
                           'ok': True, 'failures': []},
            'neo4j': {'contract_id': 'lakatotree-critique-history-storage/v1',
                       'ok': False, 'failures': []},
            'predeploy_receipt': {'contract_id': 'lakatotree-critique-history-storage/v1',
                                  'ok': True, 'failures': []},
        }, False),
        ({
            'contract_id': 'lakatotree-critique-history-storage/v1',
            'postgresql': {'contract_id': 'lakatotree-critique-history-storage/v1',
                           'ok': True, 'failures': []},
            'predeploy_receipt': {'contract_id': 'lakatotree-critique-history-storage/v1',
                                  'ok': True, 'failures': []},
        }, False),
    ],
)
def test_reconciliation_authority_is_exact_and_pending_only(report, expected):
    app = load_app()
    assert app._reconciliation_authorized(report) is expected


def test_healthz_does_not_scan_or_block_on_outbox_backlog(monkeypatch):
    app = load_app()
    _all_up(monkeypatch, app)
    monkeypatch.setattr(
        app._container,
        'outbox_pending_count',
        lambda: (_ for _ in ()).throw(AssertionError("health must not scan outbox")),
    )
    r = TestClient(app.app).get('/healthz')
    assert r.status_code == 200
    assert 'outbox' not in r.json()['services']


def test_outbox_status_endpoint_reports_pending_depth(monkeypatch):
    app = load_app()
    monkeypatch.setattr(app._container, 'outbox_pending_count', lambda: 3)
    r = TestClient(app.app).get('/api/ops/outbox-status')
    assert r.status_code == 200 and r.json() == {'pending': 3}


def test_auth_allows_get_and_correct_token(monkeypatch):
    app = load_app()
    monkeypatch.setenv('LAKATOS_API_TOKEN', 'secret')
    monkeypatch.setattr(app, 'kg', lambda q, **k: [{'name': 'q1'}] if 'OpenQuestion' in q else [])
    # 2026-07-23: open_question fail-loud(나무 미존재 404) — 이 테스트의 관심은 auth 라
    # 질문 MERGE 만 성공 행을 돌려 트리 존재를 흉내(종전 범용 [] fake 는 404 를 유발)
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
