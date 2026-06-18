"""P7-B: MCP/CLI 3면 대칭 — lineage/rebuild/manifest 계열 MCP 도구 (TDD RED→GREEN).

CLI 에는 있으나 MCP 에 없던 명령(채널 비대칭): tree(전체구조)/lineage/script-history/
rebuild-verify/lineage-record/manifest-verify. AI agent 가 MCP 로 계보·재현을 다룰 수 있어야.
(rebuild-run 은 client-side bash 실행 → RCE 회피로 CLI-only 유지: 서버 no-bash 규칙과 일관.)
"""
import json
import urllib.parse as up

import lakatos.mcp_server as m


def _cap_get(monkeypatch):
    seen = []

    def fake_get(path):
        seen.append(path)
        return {'ok': True, 'path': path}

    monkeypatch.setattr(m, '_get', fake_get)
    return seen


def _cap_post(monkeypatch):
    seen = []

    def fake_post(path, body):
        seen.append((path, body))
        return {'ok': True, 'path': path}

    monkeypatch.setattr(m, '_post', fake_post)
    return seen


# ── 비대칭 해소: 6개 도구가 등록되어 있다 ───────────────────────────────────
def test_all_six_tools_exist():
    for name in ('get_tree', 'get_lineage', 'script_history',
                 'rebuild_verify', 'record_derivation', 'manifest_verify'):
        assert hasattr(m, name), f'MCP 도구 누락: {name}'
        assert callable(getattr(m, name))


def test_get_tree_routes(monkeypatch):
    seen = _cap_get(monkeypatch)
    out = json.loads(m.get_tree('T'))
    assert seen[0] == '/api/tree/T'
    assert out['ok'] is True


def test_get_lineage_routes_with_stale(monkeypatch):
    seen = _cap_get(monkeypatch)
    json.loads(m.get_lineage('data/x.npz'))
    json.loads(m.get_lineage('data/x.npz', stale=True))
    assert seen[0] == f'/api/lineage/{up.quote("data/x.npz")}'
    assert seen[1] == f'/api/lineage/{up.quote("data/x.npz")}?stale=true'


def test_script_history_routes(monkeypatch):
    seen = _cap_get(monkeypatch)
    json.loads(m.script_history('judge.py'))
    assert seen[0] == f'/api/lineage-script/{up.quote("judge.py")}'


def test_rebuild_verify_routes(monkeypatch):
    seen = _cap_get(monkeypatch)
    json.loads(m.rebuild_verify('out/result.json'))
    assert seen[0] == f'/api/rebuild-verify/{up.quote("out/result.json")}'


def test_record_derivation_routes_and_parses_inputs(monkeypatch):
    seen = _cap_post(monkeypatch)
    json.loads(m.record_derivation('out.npz', 'sha_out', producer='gen.py',
                                   producer_sha='sha_p', inputs_csv='a.raw:sha_a, b.raw:sha_b',
                                   kind='final'))
    path, body = seen[0]
    assert path == '/api/lineage/derivation'
    assert body['output'] == 'out.npz' and body['output_sha'] == 'sha_out'
    assert body['producer'] == 'gen.py' and body['kind'] == 'final'
    assert body['inputs'] == [['a.raw', 'sha_a'], ['b.raw', 'sha_b']]


def test_manifest_verify_local_no_server(monkeypatch):
    # manifest-verify 는 로컬(파일 read + 검증) — 서버 호출 없음. lineage 헬퍼를 패치.
    import lakatos.io.lineage as L

    captured = {}

    class _Res:
        def as_dict(self):
            return {'verified': True, 'reasons': []}

    def fake_load(path):
        captured['path'] = path
        return {'manifest': 'obj'}

    def fake_verify(manifest, current_shas=None, require_environment=True):
        captured['current_shas'] = current_shas
        captured['require_environment'] = require_environment
        return _Res()

    monkeypatch.setattr(L, 'load_dataset_manifest', fake_load)
    monkeypatch.setattr(L, 'verify_dataset_manifest', fake_verify)

    # 서버 호출이 일어나면 실패하도록 _get/_post 를 막는다.
    monkeypatch.setattr(m, '_get', lambda *a, **k: (_ for _ in ()).throw(AssertionError('서버호출 금지')))
    monkeypatch.setattr(m, '_post', lambda *a, **k: (_ for _ in ()).throw(AssertionError('서버호출 금지')))

    out = json.loads(m.manifest_verify('/tmp/manifest.json',
                                       current_sha_csv='a.raw:sha_a',
                                       require_environment=False))
    assert out['verified'] is True
    assert captured['path'] == '/tmp/manifest.json'
    assert captured['current_shas'] == {'a.raw': 'sha_a'}
    assert captured['require_environment'] is False
