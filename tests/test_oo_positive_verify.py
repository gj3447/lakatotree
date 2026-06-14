"""oo positive verifier — verify_trace 단위(opener 모킹) + gated 실네트워크 통합.

LTDD positive 단언 로직(session 실재=GREEN / 부재=RED / 합계불일치·부분유실=RED)을 핀.
실 oo 왕복(_search HTTP/auth/parse)은 CONSUMER_LOGS_E2E=1 일 때만 도는 gated 통합테스트로 커버.
"""
import json
import os

import pytest

from lakatos import oo_sink


class _FakeResp:
    def __init__(self, hits):
        self._b = json.dumps({'hits': hits}).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._b


def _opener(hits):
    return lambda request, timeout: _FakeResp(hits)


@pytest.fixture
def _oo_env(monkeypatch):
    """fake oo creds — opener 가 실제 HTTP 를 가로채므로 값은 무관(verify 가 OO_URL 존재만 요구)."""
    monkeypatch.setenv('OO_URL', 'http://oo.test:5080')
    monkeypatch.setenv('OO_USER', 'u')
    monkeypatch.setenv('OO_PASS', 'p')


# ── 단위: verify_trace 로직 (opener 주입, 네트워크 없음) ──────────────────────
def test_verify_green_when_session_present(_oo_env):
    hits = [{'event': 'test_session', 'passed': 25, 'failed': 0, 'total': 25, 'skipped': 0,
             'service': 'lakatotree.tests'}, *[{'event': 'test_outcome'} for _ in range(25)]]
    r = oo_sink.verify_trace('cid', expect_total=25, retries=1, delay=0, opener=_opener(hits))
    assert r['ok'] is True and r['outcomes'] == 25 and r['reasons'] == []


def test_verify_red_when_no_session(_oo_env):
    r = oo_sink.verify_trace('cid', retries=1, delay=0, opener=_opener([{'event': 'test_outcome'}]))
    assert r['ok'] is False and 'no_test_session_trace_in_oo_after_poll' in r['reasons']


def test_verify_red_on_total_mismatch(_oo_env):
    hits = [{'event': 'test_session', 'passed': 20, 'total': 20, 'service': 'lakatotree.tests'}]
    r = oo_sink.verify_trace('cid', expect_total=25, retries=1, delay=0, opener=_opener(hits))
    assert r['ok'] is False and any('total=20' in x for x in r['reasons'])


def test_verify_red_on_partial_outcome_loss(_oo_env):
    # session 은 있으나 outcome 일부 유실(20<25) — silent partial loss 감지.
    hits = [{'event': 'test_session', 'total': 25, 'service': 'lakatotree.tests'},
            *[{'event': 'test_outcome'} for _ in range(20)]]
    r = oo_sink.verify_trace('cid', expect_total=25, retries=1, delay=0, opener=_opener(hits))
    assert r['ok'] is False and any('partial_loss' in x for x in r['reasons'])


def test_verify_oo_url_unset_is_red(monkeypatch):
    monkeypatch.delenv('OO_URL', raising=False)
    r = oo_sink.verify_trace('cid', retries=1, delay=0, opener=_opener([]))
    assert r['ok'] is False and r['reasons'] == ['OO_URL_unset']


def test_cli_wrapper_exit_codes(monkeypatch):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        'oo_pv', Path(__file__).resolve().parents[1] / 'scripts' / 'oo_positive_verify.py')
    cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)
    monkeypatch.setattr(cli, 'verify_trace',
                        lambda cid, **k: {'ok': True, 'attempts': 1, 'outcomes': 3,
                                          'session': {'passed': 3, 'total': 3}, 'reasons': []})
    assert cli.main(['cid']) == 0
    monkeypatch.setattr(cli, 'verify_trace',
                        lambda cid, **k: {'ok': False, 'session': {}, 'reasons': ['x']})
    assert cli.main(['cid']) == 1


# ── gated 통합: 실 oo 왕복(_search HTTP/auth/parse) — oo e2e 모드에서만 ────────
@pytest.mark.skipif(os.getenv('CONSUMER_LOGS_E2E') != '1' or not os.getenv('OO_PASS'),
                    reason='oo e2e off (CONSUMER_LOGS_E2E!=1) — 실네트워크 통합 skip')
def test_verify_trace_real_network_bogus_cid():
    # _oo_env 안 받음 → 세션 실제 OO_URL/OO_PASS 사용. 존재하지 않는 cid 조회 →
    # 네트워크 도달(인증/검색API/파싱 동작) + trace 없음 = RED. 실네트워크 경로 회귀 차단.
    r = oo_sink.verify_trace('bogus-no-such-cid-' + 'z' * 10, retries=1, delay=0)
    assert r['ok'] is False
    assert r['reasons'] == ['no_test_session_trace_in_oo_after_poll']   # 도달O, trace X
