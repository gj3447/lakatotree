"""preflight 가 서버 설정을 실제로 배워 오는가 (2026-08-05 회귀).

`_server_env()` 의 docstring 은 "로컬 서버면 /proc 에서 실제 값을 읽고, 못 찾으면
자기 env → 빈 값 순으로 강등한다"고 약속한다. 구현은 `if not any(env.values())` 라
자기 env 에 키가 **하나라도** 차 있으면 /proc 조회를 통째로 건너뛰었다. 실배포에서
.claude.json 이 MCP 클라이언트에 LAKATOS_SCRIPT_ROOTS 만 좁게 주고 있어 그 단락이
항상 발동했고, LAKATOS_RAW_ROOT 를 영영 못 배워 /data/kjra/PROJECT 안 경로에
거짓 "동기화 루트 밖" 경고를 냈다. 서버는 같은 파일을 멀쩡히 읽어 봉인했다.

/proc 조회는 바로 그 드리프트를 막으려고 쓰인 코드다. 부분 env 가 그것을 무력화하는
한, 경고는 서버가 아니라 클라이언트 자신의 좁은 설정을 되읽는 자기참조가 된다.

지표 스코어러: scripts/d3b_preflight_role_roots_scorer_20260805.py (3 -> 0).
"""
import lakatos.mcp_server as m
import pytest


@pytest.fixture(autouse=True)
def _clear_cache():
    m._SERVER_ENV_CACHE = None
    yield
    m._SERVER_ENV_CACHE = None


def _fake_scan(found):
    return lambda: dict(found)


def test_partial_client_env_does_not_suppress_server_lookup(monkeypatch):
    """회귀 본체 — 클라이언트가 SCRIPT_ROOTS 만 줘도 RAW_ROOT 를 서버에서 배워야 한다."""
    monkeypatch.setenv('LAKATOS_SCRIPT_ROOTS', '/client/narrow')
    monkeypatch.delenv('LAKATOS_RAW_ROOT', raising=False)
    monkeypatch.setattr(m, '_scan_server_process', _fake_scan({
        'LAKATOS_SCRIPT_ROOTS': '/server/a:/server/b',
        'LAKATOS_RAW_ROOT': '/server/raw',
    }))
    env = m._server_env()
    assert env['LAKATOS_RAW_ROOT'] == '/server/raw'
    # 서버가 권위 — 클라이언트의 좁은 값이 이기면 안 된다
    assert env['LAKATOS_SCRIPT_ROOTS'] == '/server/a:/server/b'


def test_own_env_is_a_per_key_fallback(monkeypatch):
    """서버에서 못 배운 키만 자기 env 로 강등된다 (all-or-nothing 아님)."""
    monkeypatch.setenv('LAKATOS_SCRIPT_ROOTS', '/client/narrow')
    monkeypatch.setenv('LAKATOS_RAW_ROOT', '/client/raw')
    monkeypatch.setattr(m, '_scan_server_process', _fake_scan({
        'LAKATOS_SCRIPT_ROOTS': '/server/a',
    }))
    env = m._server_env()
    assert env['LAKATOS_SCRIPT_ROOTS'] == '/server/a'      # 서버가 이긴다
    assert env['LAKATOS_RAW_ROOT'] == '/client/raw'        # 서버가 안 준 키만 폴백


def test_no_server_process_degrades_to_own_env(monkeypatch):
    monkeypatch.setenv('LAKATOS_SCRIPT_ROOTS', '/client/narrow')
    monkeypatch.setenv('LAKATOS_RAW_ROOT', '/client/raw')
    monkeypatch.setattr(m, '_scan_server_process', _fake_scan({}))
    assert m._server_env() == {'LAKATOS_SCRIPT_ROOTS': '/client/narrow',
                               'LAKATOS_RAW_ROOT': '/client/raw'}


def test_raw_root_widens_the_result_role_only(monkeypatch):
    """RAW_ROOT 는 result 에만 적용된다 — script 까지 넓히면 게이트가 헐거워진다."""
    monkeypatch.delenv('LAKATOS_SCRIPT_ROOTS', raising=False)
    monkeypatch.delenv('LAKATOS_RAW_ROOT', raising=False)
    monkeypatch.setattr(m, '_scan_server_process', _fake_scan({
        'LAKATOS_SCRIPT_ROOTS': '/server/scripts',
        'LAKATOS_RAW_ROOT': '/server/raw',
    }))
    assert not m._preflight_paths('/server/raw/e/x.json', role='result')
    assert m._preflight_paths('/server/raw/e/x.py', role='script')
    assert not m._preflight_paths('/server/scripts/x.py', role='script')


def test_client_process_is_not_mistaken_for_the_server(monkeypatch):
    """MCP 클라이언트도 LAKATOS_SCRIPT_ROOTS 를 갖는다 — 자기를 서버로 읽으면 안 된다.

    /proc 스캔이 'SCRIPT_ROOTS 가 있는 첫 프로세스'를 집으면 클라이언트 자신을 집어
    자기 설정을 서버 설정이라며 되읽는다. 서버만 RAW_ROOT 를 갖고 cmdline 에
    uvicorn 이 있다는 점으로 갈라야 한다.
    """
    procs = {
        '100': ('python -m lakatos.mcp_server', 'LAKATOS_SCRIPT_ROOTS=/client/narrow\x00'),
        '200': ('python -m uvicorn --app-dir server app:app --port 55170',
                'LAKATOS_SCRIPT_ROOTS=/server/a\x00LAKATOS_RAW_ROOT=/server/raw\x00'),
    }
    monkeypatch.setattr(m.os, 'listdir', lambda p: list(procs) if p == '/proc' else [])

    real_open = open

    def fake_open(path, mode='r', *a, **kw):
        for pid, (cmd, env) in procs.items():
            if path == f'/proc/{pid}/environ':
                return _BytesFile(env.encode())
            if path == f'/proc/{pid}/cmdline':
                return _BytesFile(cmd.encode())
        return real_open(path, mode, *a, **kw)

    monkeypatch.setattr('builtins.open', fake_open)
    found = m._scan_server_process()
    assert found.get('LAKATOS_RAW_ROOT') == '/server/raw', \
        '클라이언트 프로세스를 서버로 오인했다 (자기설정 되읽기)'
    assert found['LAKATOS_SCRIPT_ROOTS'] == '/server/a'


class _BytesFile:
    """open(path,'rb') 최소 대역 — 컨텍스트 매니저 + read()."""

    def __init__(self, data: bytes):
        self._data = data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._data
