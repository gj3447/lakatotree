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
