"""외부 생태계 adapter TDD — OpenLineage/DVC/PROV export.
# KG: span_lakatotree_adapters
"""
from datetime import datetime, timezone

from lakatos.adapters import (
    bash_act_to_prov_document,
    derivation_to_openlineage_event,
    derivations_to_dvc_lock,
    derivations_to_dvc_pipeline,
    derivations_to_prov_document,
    lineage_result_to_openlineage_events,
    observation_to_prov_document,
    rebuild_recipe_manifest,
)
from lakatos.engine import (
    BashAct,
    InternetObservation,
    LineageReplayGate,
    SourceCredibilityScore,
)
from lakatos.lineage import Derivation


ZDF = Derivation(
    output="VFEZ0060.zdf",
    output_sha="z0",
    producer="",
    producer_sha="",
    inputs=[],
    kind="source",
    ts="t0",
)
RIM = Derivation(
    output="_rimobs_0060.npz",
    output_sha="r0",
    producer="319.py",
    producer_sha="s319",
    inputs=[("VFEZ0060.zdf", "z0")],
    params={"stride": 2},
    kind="intermediate",
    ts="t1",
)
FINAL = Derivation(
    output="perview_v22.json",
    output_sha="p0",
    producer="334.py",
    producer_sha="s334",
    inputs=[("_rimobs_0060.npz", "r0")],
    params={"lots": 6},
    kind="final",
    ts="t2",
)


def test_derivation_to_openlineage_event_maps_run_job_datasets():
    event = derivation_to_openlineage_event(
        FINAL,
        namespace="bpc",
        event_time="2026-06-12T00:00:00Z",
    )

    assert event["eventType"] == "COMPLETE"
    assert event["job"]["name"] == "334.py"
    assert event["inputs"][0]["name"] == "_rimobs_0060.npz"
    assert event["outputs"][0]["name"] == "perview_v22.json"
    assert event["outputs"][0]["facets"]["lakatotree_hash"]["sha256"] == "p0"
    assert event["run"]["facets"]["lakatotree_replay"]["producer_sha"] == "s334"


def test_lineage_replay_result_exports_openlineage_sequence():
    result = LineageReplayGate.evaluate(
        "perview_v22.json",
        [ZDF, RIM, FINAL],
        sources={"VFEZ0060.zdf"},
    )

    events = lineage_result_to_openlineage_events(result, namespace="bpc")

    assert [e["outputs"][0]["name"] for e in events] == [
        "_rimobs_0060.npz",
        "perview_v22.json",
    ]
    assert {e["schemaURL"].split("#")[-1] for e in events} == {"/definitions/RunEvent"}


def test_derivations_to_dvc_pipeline_and_lock_are_replayable_from_raw():
    dvc_yaml = derivations_to_dvc_pipeline([ZDF, RIM, FINAL])
    dvc_lock = derivations_to_dvc_lock([ZDF, RIM, FINAL])

    assert "VFEZ0060_zdf" not in dvc_yaml["stages"]
    assert dvc_yaml["stages"]["_rimobs_0060_npz"]["deps"] == ["VFEZ0060.zdf", "319.py"]
    assert dvc_yaml["stages"]["perview_v22_json"]["outs"] == ["perview_v22.json"]
    assert dvc_lock["stages"]["perview_v22_json"]["outs"][0]["md5"] == "p0"


def test_rebuild_recipe_manifest_carries_roots_plan_and_dvc_exports():
    manifest = rebuild_recipe_manifest("perview_v22.json", [ZDF, RIM, FINAL])

    assert manifest["raw_roots"] == ["VFEZ0060.zdf"]
    assert [x["output"] for x in manifest["rebuild_steps"]] == [
        "_rimobs_0060.npz",
        "perview_v22.json",
    ]
    assert "dvc_yaml" in manifest and "dvc_lock" in manifest


def test_derivations_to_prov_document_maps_entities_activities_agents():
    doc = derivations_to_prov_document([ZDF, RIM, FINAL])

    assert doc["entity"]["VFEZ0060.zdf"]["type"] == "RawDataArtifact"
    assert doc["entity"]["perview_v22.json"]["type"] == "DerivedDataArtifact"
    assert "derive:perview_v22.json@t2" in doc["activity"]
    rels = {(r["rel"], r["from"], r["to"]) for r in doc["relations"]}
    assert ("wasDerivedFrom", "perview_v22.json", "_rimobs_0060.npz") in rels
    assert ("wasAttributedTo", "derive:perview_v22.json@t2", "script:334.py") in rels


def test_observation_and_bash_export_to_prov_documents():
    obs = InternetObservation(
        name="obs-1",
        url="https://example.test/paper",
        query="lakatos tree",
        retrieved_at=datetime(2026, 6, 12, tzinfo=timezone.utc),
        content_hash="h1",
        fetch_tool="web.fetch",
        source_type="paper",
        credibility=SourceCredibilityScore(provenance_score=1.0),
    )
    bash = BashAct(
        name="pytest",
        command="python -m pytest tests/ -q",
        cwd="/repo",
        exit_code=0,
        stdout_summary="87 passed",
        git_sha="abc123",
    )

    obs_doc = observation_to_prov_document(obs)
    bash_doc = bash_act_to_prov_document(bash)

    assert obs_doc["entity"]["snapshot:obs-1"]["type"] == "InternetObservation"
    assert obs_doc["activity"]["fetch:obs-1"]["type"] == "WebFetch"
    assert bash_doc["entity"]["bash:pytest#result"]["exit_code"] == 0
    assert bash_doc["activity"]["bash:pytest"]["git_sha"] == "abc123"
