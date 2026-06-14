"""CLI local commands.
# KG: span_lakatotree_cli
"""
import json

import lakatos.cli as cli
from lakatos.cli import main
from lakatos.lineage import (
    Derivation,
    EnvironmentFingerprint,
    dataset_manifest_from_derivations,
    manifest_to_dict,
)


def test_manifest_verify_cli_reads_manifest_and_reports_rebuild_plan(tmp_path, capsys):
    raw = Derivation("raw://lot-0060", "raw0", "", "", [], kind="source")
    final = Derivation(
        "artifact://report",
        "report0",
        "build.py",
        "script0",
        [("raw://lot-0060", "raw0")],
        kind="final",
    )
    manifest = dataset_manifest_from_derivations(
        "artifact://report",
        [raw, final],
        environment=EnvironmentFingerprint(python="3.12.0"),
    )
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest_to_dict(manifest)), encoding="utf-8")

    main(["manifest-verify", str(path), "--current-sha", "raw://lot-0060:raw0"])

    out = json.loads(capsys.readouterr().out)
    assert out["passed"] is True
    assert out["roots"] == ["raw://lot-0060"]
    assert out["rebuild_plan"][0]["output"] == "artifact://report"


def test_manifest_verify_cli_reports_stale_inputs(tmp_path, capsys):
    raw = Derivation("raw://lot-0060", "raw0", "", "", [], kind="source")
    final = Derivation(
        "artifact://report",
        "report0",
        "build.py",
        "script0",
        [("raw://lot-0060", "raw0")],
        kind="final",
    )
    manifest = dataset_manifest_from_derivations(
        "artifact://report",
        [raw, final],
        environment=EnvironmentFingerprint(python="3.12.0"),
    )
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest_to_dict(manifest)), encoding="utf-8")

    main(["manifest-verify", str(path), "--current-sha", "raw://lot-0060:rawNEW"])

    out = json.loads(capsys.readouterr().out)
    assert out["passed"] is False
    assert "stale_inputs" in out["reasons"]


# ── 신규 층 CLI 라우팅 (서버 API thin wrapper) — call() 패치로 네트워크 없이 검증 ──

def _capture_calls(monkeypatch):
    calls = []
    def fake_call(method, path, body=None):
        calls.append((method, path, body))
        return {'ok': True}
    monkeypatch.setattr(cli, 'call', fake_call)
    return calls


def test_stack_cli_routes_with_optional_leaf(monkeypatch, capsys):
    calls = _capture_calls(monkeypatch)
    cli.main(['stack', 'T'])
    cli.main(['stack', 'T', '--leaf', 'v22'])
    paths = [c[1] for c in calls]
    assert paths[0] == '/api/tree/T/stack'                 # leaf 생략 = 정본 leaf
    assert paths[1] == '/api/tree/T/stack?leaf=v22'
    assert all(c[0] == 'GET' for c in calls)


def test_lifecycle_cli_routes(monkeypatch, capsys):
    calls = _capture_calls(monkeypatch)
    cli.main(['lifecycle', 'T', '--leaf', 'best'])
    assert calls[0] == ('GET', '/api/tree/T/lifecycle?leaf=best', None)


def test_leaderboard_cli_passes_trees_and_snapshot(monkeypatch, capsys):
    calls = _capture_calls(monkeypatch)
    cli.main(['leaderboard', 'A,B'])
    cli.main(['leaderboard', 'A,B', '--snapshot'])
    assert calls[0][1].startswith('/api/leaderboard?')
    assert 'trees=A%2CB' in calls[0][1] and 'snapshot=false' in calls[0][1]
    assert 'snapshot=true' in calls[1][1]


def test_paradigm_cli_passes_incumbent_and_rivals(monkeypatch, capsys):
    calls = _capture_calls(monkeypatch)
    cli.main(['paradigm', 'D', 'A,B'])
    p = calls[0][1]
    assert p.startswith('/api/paradigm?')
    assert 'incumbent=D' in p and 'rivals=A%2CB' in p


def test_certificate_cli_routes(monkeypatch, capsys):
    calls = _capture_calls(monkeypatch)
    cli.main(['certificate', 'T', 'v22'])
    assert calls[0] == ('GET', '/api/tree/T/node/v22/certificate', None)


# ── Cluster ① CLI: predict --credence / question / question-close / calibration ──

def test_predict_cli_passes_credence(monkeypatch, capsys):
    calls = _capture_calls(monkeypatch)
    cli.main(['predict', 'T', 'v', '--metric', 'p95', '--baseline', '0.5', '--credence', '0.8'])
    method, path, body = calls[0]
    assert path == '/api/tree/T/node/v/prediction'
    assert body['credence'] == 0.8


def test_question_cli_passes_voi_meta(monkeypatch, capsys):
    calls = _capture_calls(monkeypatch)
    cli.main(['question', 'T', 'q1', '--body', 'why', '--gain', '0.4', '--cost', '2.0'])
    method, path, body = calls[0]
    assert (method, path) == ('POST', '/api/tree/T/question')
    assert (body['expected_gain'], body['cost'], body['qname']) == (0.4, 2.0, 'q1')


def test_question_close_cli_routes(monkeypatch, capsys):
    calls = _capture_calls(monkeypatch)
    cli.main(['question-close', 'T', 'q1', '--by', 'mid'])
    assert calls[0][0] == 'POST'
    assert calls[0][1] == '/api/tree/T/question/q1/close?closed_by=mid'


def test_calibration_cli_routes(monkeypatch, capsys):
    calls = _capture_calls(monkeypatch)
    cli.main(['calibration', 'T'])
    assert calls[0] == ('GET', '/api/tree/T/calibration', None)


# ── Cluster ② CLI: agm (spec file) / cycle (harness runner) ──

def test_agm_cli_posts_spec_file(monkeypatch, tmp_path, capsys):
    calls = _capture_calls(monkeypatch)
    spec = tmp_path / 'agm.json'
    spec.write_text('{"op":"expansion","base":[],"new":{"belief_id":"b1"}}')
    cli.main(['agm', str(spec)])
    assert calls[0][0] == 'POST' and calls[0][1] == '/api/agm/revise'
    assert calls[0][2]['op'] == 'expansion'


def test_cycle_cli_invokes_harness_run(monkeypatch):
    import lakatos.harness_run as hr
    seen = []
    monkeypatch.setattr(hr, 'main', lambda p: seen.append(p))
    cli.main(['cycle', '/tmp/spec.json'])
    assert seen == ['/tmp/spec.json']        # 하네스 러너로 위임(서버 RCE 회피, client-side)


def test_cli_call_injects_bearer_when_env(monkeypatch):
    monkeypatch.setenv('LAKATOS_API_TOKEN', 'tok')
    captured = {}

    class _R:
        def read(self): return b'{}'

    def fake_urlopen(req, timeout=None):
        captured['auth'] = req.headers.get('Authorization')
        return _R()

    monkeypatch.setattr(cli.urllib.request, 'urlopen', fake_urlopen)
    cli.call('GET', '/api/trees')
    assert captured['auth'] == 'Bearer tok'        # REG-1: auth 켜지면 client 가 토큰 전달


# ── P6-2: CLI verdict / critique / standing (CLI↔MCP 비대칭 해소) ──

def test_verdict_cli_routes(monkeypatch, capsys):
    calls = _capture_calls(monkeypatch)
    cli.main(['verdict', 'T', 'v', 'CANONICAL', '--note', 'best', '--human'])
    method, path, body = calls[0]
    assert (method, path) == ('POST', '/api/tree/T/node/v/verdict')
    assert body['verdict'] == 'CANONICAL' and body['human_verdict'] is True


def test_critique_cli_routes(monkeypatch, capsys):
    calls = _capture_calls(monkeypatch)
    cli.main(['critique', 'T', 'v', 'doubt:r1', 'v', '--kind', 'rebuttal'])
    method, path, body = calls[0]
    assert (method, path) == ('POST', '/api/tree/T/node/v/critique')
    assert body['arg_id'] == 'doubt:r1' and body['kind'] == 'rebuttal'


def test_standing_cli_routes(monkeypatch, capsys):
    calls = _capture_calls(monkeypatch)
    cli.main(['standing', 'T', 'v'])
    assert calls[0] == ('GET', '/api/tree/T/node/v/standing', None)
