"""P7-C: 에러 분기 커버리지 — 미테스트 예외 경로 (TDD).

production 진입점(harness_run)·MCP _post·claim _payload_float 의 에러핸들링 분기가
happy-path 테스트에 가려 미커버였다. 실제 위험분기를 핀으로 고정 + NaN/inf 잠복버그 수정.
"""
import io
import json
import urllib.error

import pytest

import lakatos.mcp_server as m
import lakatos.harness_run as hr
import lakatos.claim as claim
import lakatos.grounding as G
from lakatos.engine import Realm, ResearchEvent


# ── COVERAGE-MCP-001: _post 4xx/5xx 분기 (mcp_server.py:27-28) ───────────────
class _FakeResp:
    def __init__(self, status, text='', payload=None):
        self.status_code = status
        self.text = text
        self._payload = payload or {}

    def json(self):
        return self._payload


def test_mcp_post_returns_error_dict_on_4xx(monkeypatch):
    monkeypatch.setattr(m.httpx, 'post', lambda *a, **k: _FakeResp(409, text='conflict: gate failed'))
    out = m._post('/api/x', {'a': 1})
    assert out['error'] == 409
    assert 'conflict' in out['detail']


def test_mcp_post_returns_json_on_2xx(monkeypatch):
    monkeypatch.setattr(m.httpx, 'post', lambda *a, **k: _FakeResp(200, payload={'ok': True}))
    assert m._post('/api/x', {})['ok'] is True


# ── COVERAGE-HARNESS-001: _http 에러 + _bash/_git_sha 실포트 + internet_sources ──
def test_harness_http_error_returns_error_dict(monkeypatch):
    def boom(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 503, 'down', {}, io.BytesIO(b'service down'))
    monkeypatch.setattr(hr.urllib.request, 'urlopen', boom)
    out = hr._http('GET', '/api/trees')
    assert out['error'] == 503 and 'down' in out['detail']


def test_harness_bash_real_echo():
    text, code = hr._bash('echo metric=0.5')
    assert 'metric=0.5' in text and code == 0


def test_harness_bash_nonzero_exit():
    text, code = hr._bash('exit 3')
    assert code == 3


def test_harness_git_sha_returns_str_or_none():
    sha = hr._git_sha()
    assert sha is None or isinstance(sha, str)


def test_harness_main_internet_sources_branch(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(hr, '_http', lambda mth, p, body=None: (calls.append((mth, p)) or
        {'verdict': 'progressive', 'novel': None, 'delta': -0.2, 'grounded_extension': []}))
    monkeypatch.setattr(hr, '_bash', lambda cmd: ('metric=0.3', 0))
    monkeypatch.setattr(hr, '_git_sha', lambda: 'abc1234')
    spec = dict(tree='T', tag='e1', parent='root', metric='p95', baseline=0.5,
                judge_cmd='echo metric=0.3', internet_sources=[['http://x', 0.8]])
    p = tmp_path / 'spec.json'
    p.write_text(json.dumps(spec))
    hr.main(str(p))
    out = json.loads(capsys.readouterr().out)
    assert out['verdict'] == 'progressive'


# ── COVERAGE-CLAIM-001: _payload_float malformed + NaN/inf 잠복버그 ──────────
def _ev(payload):
    return ResearchEvent(name='e', realm=Realm.BASH, actor='a', action='observe',
                         target='t', payload=tuple(payload.items()))


def test_claim_malformed_confidence_falls_to_realm_default():
    realm_default = G.GROUNDED['evidence_realm_confidence']['value']['BASH']
    assert claim._event_confidence(_ev({'confidence': 'abc'})) == pytest.approx(realm_default)


def test_claim_nan_inf_confidence_rejected_not_silent_one():
    # ★잠복버그: 전엔 'NaN'→float→_clamp01(nan)=1.0(조용한 최대신뢰). 이제 non-finite=malformed.
    realm_default = G.GROUNDED['evidence_realm_confidence']['value']['BASH']
    assert claim._event_confidence(_ev({'confidence': 'NaN'})) == pytest.approx(realm_default)
    assert claim._event_confidence(_ev({'confidence': 'infinity'})) == pytest.approx(realm_default)


def test_claim_valid_explicit_confidence_used():
    assert claim._event_confidence(_ev({'confidence': '0.9'})) == pytest.approx(0.9)
