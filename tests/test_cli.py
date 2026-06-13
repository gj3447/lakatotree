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
