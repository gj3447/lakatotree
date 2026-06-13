"""Cluster ① — '초록인데 안 돌던' 기능을 실제로 작동시키는 write-path 검증.

T3-1: pred_credence write → certify G4(calibration) 가 더 이상 영구 n=0 아님.
WIRE-1: question 의 expected_gain/cost write → directions VoI 가 default 가 아닌 실값으로 차등.
GAP-T2-04: route-contract + TestClient 스모크 — CLI/MCP↔서버 route/serialization drift 차단.
# KG: span_lakatotree_make_it_real
"""
import importlib
import os

from fastapi.testclient import TestClient


def load_app():
    os.environ.setdefault('NEO4J_URI', 'bolt://localhost:7687')
    os.environ.setdefault('NEO4J_USER', 'neo4j')
    os.environ.setdefault('NEO4J_PASSWORD', 'test')
    return importlib.import_module('server.app')


def _capture_kg(monkeypatch, app, ret=None):
    calls = []

    def fake_kg(q, **kw):
        calls.append((q, kw))
        return ret if ret is not None else [{'tag': 'v'}]

    monkeypatch.setattr(app, 'kg', fake_kg)
    monkeypatch.setattr(app, 'hist', lambda *a, **k: None)
    return calls


# ── T3-1: pred_credence write-path (certify G4 부활) ──

def test_register_prediction_writes_pred_credence(monkeypatch):
    app = load_app()
    calls = _capture_kg(monkeypatch, app)
    app.register_prediction('T', 'v', app.PredictionIn(
        metric_name='p95', baseline_value=0.5, credence=0.8))
    q, kw = calls[0]
    assert 'e.pred_credence=$credence' in q
    assert kw['credence'] == 0.8


def test_register_prediction_credence_optional(monkeypatch):
    app = load_app()
    calls = _capture_kg(monkeypatch, app)
    app.register_prediction('T', 'v', app.PredictionIn(metric_name='p95', baseline_value=0.5))
    assert calls[0][1]['credence'] is None        # 안 줘도 OK


def test_calibration_has_data_once_pred_credence_present(monkeypatch):
    # write-path 생겨 calibration 이 더 이상 구조적 n=0 영구가 아님 (certify G4 통과 가능)
    app = load_app()
    monkeypatch.setattr(app, 'kg', lambda q, **kw: [dict(p=0.8, o=True), dict(p=0.3, o=False)])
    out = app.calibration('T')
    assert out['n'] == 2


# ── WIRE-1: VoI write-path (directions 차등 부활) ──

def test_open_question_writes_voi_meta(monkeypatch):
    app = load_app()
    calls = _capture_kg(monkeypatch, app)
    app.open_question('T', app.QuestionIn(qname='q1', body='b', expected_gain=0.4, cost=2.0))
    q, kw = calls[0]
    assert 'qn.expected_gain=$expected_gain' in q and 'qn.cost=$cost' in q
    assert (kw['expected_gain'], kw['cost']) == (0.4, 2.0)


def test_directions_ranks_by_real_voi_and_survives_none(monkeypatch):
    app = load_app()
    td = dict(name='T', title='T', hard_core=[], frontier_rule='', doc='',
              coverage_backlog=[], coverage_statement='',
              nodes=[dict(tag='c', verdict='CANONICAL', metric_value=None)],
              frontier=[
                  dict(name='q-old', status='OPEN', body='', expected_gain=None, cost=None, n_visits=None),
                  dict(name='q-hi', status='OPEN', body='', expected_gain=0.9, cost=1.0, n_visits=1),
                  dict(name='q-lo', status='OPEN', body='', expected_gain=0.05, cost=5.0, n_visits=1)])
    monkeypatch.setattr(app, 'tree_data', lambda n: td)
    monkeypatch.setattr(app, 'compute_metrics', lambda t: {'bayes': {'canonical_credence': 0.5}})
    out = app.directions('T')
    names = [d['name'] for d in out['ranked_directions']]
    assert names[0] == 'q-hi'                     # 실 VoI 반영 → 차등 생김 (전엔 전부 동률)
    assert 'q-old' in names                       # None(옛 질문)이어도 crash 없이 포함


# ── GAP-T2-04: route-contract (CLI/MCP 가 부르는 경로가 전부 실재하는가) ──

def test_cli_mcp_endpoints_are_registered_routes():
    app = load_app()
    registered = set()
    for r in app.app.routes:
        for m in (getattr(r, 'methods', None) or []):
            registered.add((m, r.path))
    required = {
        ('GET', '/api/trees'), ('GET', '/api/tree/{name}'),
        ('GET', '/api/tree/{name}/metrics'), ('GET', '/api/tree/{name}/directions'),
        ('GET', '/api/tree/{name}/stack'), ('GET', '/api/tree/{name}/lifecycle'),
        ('GET', '/api/leaderboard'), ('GET', '/api/paradigm'),
        ('GET', '/api/tree/{name}/node/{tag}/certificate'),
        ('GET', '/api/tree/{name}/calibration'),
        ('POST', '/api/tree/{name}/question'),
        ('POST', '/api/tree/{name}/question/{qname}/close'),
        ('POST', '/api/tree/{name}/node/{tag}/prediction'),
        ('POST', '/api/tree/{name}/node/{tag}/test_result'),
        ('GET', '/api/tree/{name}/node/{tag}/standing'),
        ('GET', '/api/tree/{name}/node/{tag}/claim-standing'),
        ('POST', '/api/tree/{name}/node/{tag}/critique'),
    }
    missing = required - registered
    assert not missing, f'CLI/MCP 가 부르는데 미등록 라우트: {missing}'


# ── GAP-T2-04: TestClient 스모크 — 실 ASGI/직렬화 스택 관통 (read 경로) ──

def test_testclient_trees_and_dashboard_serialize(monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, 'kg', lambda q, **kw: [])     # 빈 KG
    client = TestClient(app.app)
    r = client.get('/api/trees')
    assert r.status_code == 200 and r.json() == []
    d = client.get('/')
    assert d.status_code == 200 and '라카토스 서버' in d.text
