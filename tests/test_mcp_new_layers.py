"""신규 층 MCP 도구 라우팅 — stack/lifecycle/leaderboard/paradigm/certificate.

MCP 도구는 서버 API(:55170) 의 thin wrapper(단일 정본). _get 패치로 네트워크 없이 경로 검증.
# KG: span_lakatotree_mcp
"""
import json

import lakatos.mcp_server as m


def _cap(monkeypatch):
    seen = []

    def fake_get(path):
        seen.append(path)
        return {'ok': True, 'path': path}

    monkeypatch.setattr(m, '_get', fake_get)
    return seen


def test_stack_tool_routes_with_optional_leaf(monkeypatch):
    seen = _cap(monkeypatch)
    out = json.loads(m.stack('T'))
    json.loads(m.stack('T', leaf='v22'))
    assert seen[0] == '/api/tree/T/stack'
    assert seen[1] == '/api/tree/T/stack?leaf=v22'
    assert out['ok'] is True


def test_lifecycle_tool_routes(monkeypatch):
    seen = _cap(monkeypatch)
    json.loads(m.lifecycle('T', leaf='best'))
    assert seen[0] == '/api/tree/T/lifecycle?leaf=best'


def test_leaderboard_tool_routes(monkeypatch):
    seen = _cap(monkeypatch)
    json.loads(m.leaderboard('A,B'))
    json.loads(m.leaderboard('A,B', snapshot=True))
    assert seen[0].startswith('/api/leaderboard?')
    assert 'trees=A%2CB' in seen[0] and 'snapshot=false' in seen[0]
    assert 'snapshot=true' in seen[1]


def test_paradigm_tool_routes(monkeypatch):
    seen = _cap(monkeypatch)
    json.loads(m.paradigm('D', 'A,B'))
    assert seen[0].startswith('/api/paradigm?')
    assert 'incumbent=D' in seen[0] and 'rivals=A%2CB' in seen[0]


def test_certificate_tool_routes(monkeypatch):
    seen = _cap(monkeypatch)
    json.loads(m.certificate('T', 'v22'))
    assert seen[0] == '/api/tree/T/node/v22/certificate'


# ── Cluster ① MCP: calibration / open_question / close_question / register_prediction credence ──

def _cap_post(monkeypatch):
    seen = []

    def fake_post(path, body):
        seen.append((path, body))
        return {'ok': True}

    monkeypatch.setattr(m, '_post', fake_post)
    return seen


def test_calibration_tool_routes(monkeypatch):
    seen = _cap(monkeypatch)
    json.loads(m.calibration('T'))
    assert seen[0] == '/api/tree/T/calibration'


def test_open_question_tool_passes_voi_meta(monkeypatch):
    seen = _cap_post(monkeypatch)
    json.loads(m.open_question('T', 'q1', body='why', expected_gain=0.4, cost=2.0))
    path, body = seen[0]
    assert path == '/api/tree/T/question'
    assert (body['expected_gain'], body['cost']) == (0.4, 2.0)


def test_close_question_tool_routes(monkeypatch):
    seen = _cap_post(monkeypatch)
    json.loads(m.close_question('T', 'q1', closed_by='mid'))
    assert seen[0][0] == '/api/tree/T/question/q1/close?closed_by=mid'


def test_register_prediction_tool_includes_credence(monkeypatch):
    seen = _cap_post(monkeypatch)
    json.loads(m.register_prediction('T', 'v', metric='p95', baseline=0.5, credence=0.8))
    path, body = seen[0]
    assert path == '/api/tree/T/node/v/prediction'
    assert body['credence'] == 0.8
