"""FIX-HARNESS #23 (P2, merged with #11): oo strict-mode arrival gate is fail-open.

Finding id: #23 (merged #11)
Locations:
    lakatos/io/oo_verify.py:119  (ship except block — session_finish)
    lakatos/io/oo_verify.py:133  (verify except block — region :128-135)
    tests/conftest.py:65         (consumes res['fail_build'] → session.exitstatus = 1)

The bug:
    The strict-mode contract is "oo non-arrival ⇒ session failure (exit 1)". But that
    enforcement (verify_policy) only runs on the *clean* negative path (verify returns
    ok=False). The two `except Exception` blocks in session_finish hardcode
    `fail_build=False` regardless of `mode`. So if ship()/verify() *raises* — e.g.
    oo_sink hits a 401/HTTPError or a misconfigured endpoint — the exception is
    swallowed and the build is reported as PASS *even in strict mode*, bypassing the
    arrival gate. A should-FAIL build is downgraded to PASS (fail-open).

The exact fix:
    In *both* except blocks set  `fail_build = (mode == 'strict')`  (keep warn-mode,
    mode='1', swallowing as-is). i.e. return {... 'fail_build': mode == 'strict' ...}.

xfail(strict) until fixed: the negative-oracle assertions below encode the CORRECT
post-fix behavior (strict + raise ⇒ fail_build True). They FAIL today (bug present)
and will PASS once the fix lands, at which point strict=True trips the xfail.

Hermetic: no network. We force the inner ship/verify callables to raise via the
`shipper=`/`verifier=` injection points that oo_verify.session_finish already exposes
(same pattern as tests/test_oo_verify.py), and exercise the REAL session_finish gate.
"""
import pytest

from lakatos.io import oo_verify


def _reports(n):
    # tests/test_oo_verify.py 스타일 동일 — nodeid 만 있으면 session_finish 가 돈다.
    return [{'nodeid': f't{i}', 'outcome': 'passed', 'duration': 0.0, 'when': 'call', 'longrepr': ''}
            for i in range(n)]


@pytest.fixture
def _gate_on(monkeypatch):
    """enabled() = CONSUMER_LOGS_E2E==1 ∧ OO_PASS — 게이트 ON 으로 실 session_finish 경로 진입."""
    monkeypatch.setenv('CONSUMER_LOGS_E2E', '1')
    monkeypatch.setenv('OO_PASS', 'p')


def _http_401(*_a, **_k):
    # oo_sink 401/HTTPError 모사 — 실 장애에서 ship/verify 가 던지는 예외 모양.
    raise RuntimeError('HTTP Error 401: Unauthorized (oo_sink)')


# [FIXED 2026-06-27] #23 — green regression (oo_verify.py:133 verify except → fail_build=mode=='strict')
def test_strict_verify_raise_fails_build(_gate_on):
    # ship 은 성공, verify 가 예외(401 등) → strict 계약상 빌드 실패여야 한다.
    # 오늘: except(line 133) 가 fail_build=False 로 삼켜 PASS(버그). 수정 후: True.
    r = oo_verify.session_finish(
        _reports(2), 'cid-strict-verify', mode='strict',
        shipper=lambda recs: None, verifier=_http_401)
    assert r['fail_build'] is True   # post-fix: mode=='strict' 이면 예외도 세션 실패
    assert any('verify skipped' in m for m in r['messages'])


# [FIXED 2026-06-27] #23 — green regression (oo_verify.py:119 ship except → fail_build=mode=='strict')
def test_strict_ship_raise_fails_build(_gate_on):
    # ship 자체가 예외(401 등) → strict 계약상 빌드 실패여야 한다.
    # 오늘: except(line 119) 가 fail_build=False 로 삼켜 PASS(버그). 수정 후: True.
    r = oo_verify.session_finish(
        _reports(2), 'cid-strict-ship', mode='strict',
        shipper=_http_401, verifier=lambda: {'ok': True})
    assert r['fail_build'] is True   # post-fix: mode=='strict' 이면 ship 예외도 세션 실패


def test_warn_mode_still_swallows_raise(_gate_on):
    # 스코프 가드(xfail 아님 — 오늘도 수정 후도 통과): warn(mode='1')에서는 예외를
    # 그대로 삼켜 fail_build=False ('관측은 판결을 바꾸지 않는다' 보존). 수정이 strict 에만
    # 한정됨을 고정 — 이게 깨지면 fix 가 과도하게 적용된 것.
    r_v = oo_verify.session_finish(
        _reports(2), 'cid-warn-verify', mode='1',
        shipper=lambda recs: None, verifier=_http_401)
    r_s = oo_verify.session_finish(
        _reports(2), 'cid-warn-ship', mode='1',
        shipper=_http_401, verifier=lambda: {'ok': True})
    assert r_v['fail_build'] is False
    assert r_s['fail_build'] is False
