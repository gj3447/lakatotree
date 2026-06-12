"""CLI local commands.
# KG: span_lakatotree_cli
"""
import json

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
