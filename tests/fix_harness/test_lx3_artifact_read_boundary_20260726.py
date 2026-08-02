"""LX3 replay-artifact binding guards.

The authoritative replay command must be derived from one content-valid v5 receipt, not from
mutable node metadata.  These tests cover the write-side first-write-wins guard, receipt/cache
parity, MeasurementLock content rehashing, provenance fail-closed behavior, and argv-safe command
serialization.
"""
from __future__ import annotations

import json
import shlex

import pytest
from fastapi import HTTPException

import lakatos.verdicts as V
from lakatos.io.prov import replay_command
from lakatos.measurement_lock import build_measurement_lock, lock_sha
from server.file_hashing import file_sha
from server.contexts.audit import fsck as F
from server.contexts.tree.evidence_claim_service import EvidenceClaimService
from server.contexts.tree.repository import TreeKgRepository
from server.contexts.tree.schemas import NodeIn
from server.contexts.tree.writer import TreeKgWriter


def _sealed_bundle(tmp_path) -> tuple[dict, dict, dict]:
    script_file = tmp_path / "LX3 scorer.py"
    result_file = tmp_path / "LX3 lot;final.json"
    script_file.write_text("print('metric=1.0')\n", encoding="utf-8")
    result_file.write_text('{"metric":1.0}\n', encoding="utf-8")
    script, result = str(script_file.resolve()), str(result_file.resolve())
    script_sha, result_sha = file_sha(script), file_sha(result)
    lock = build_measurement_lock(
        cmd=replay_command(script, result),
        deps=[{"path": script, "sha256": script_sha},
              {"path": result, "sha256": result_sha}],
        params={"metric_name": "m"}, env_sha="3" * 64,
        outs=[{"name": "m", "value": 1.0}],
        measurement_grade="server_regenerated", replay_status="verified",
    )
    lsha = lock_sha(lock)
    fields = {key: None for key in V.RECEIPT_FIELDS}
    fields.update({
        "tree": "T", "tag": "n", "verdict": "progressive",
        "verdict_source": "scripted", "metric_name": "m", "metric_value": 1.0,
        "novel_confirmed": False, "lakatos_status": "progressive",
        "judged_at": "2026-07-26T00:00:00+00:00", "judge_script_sha": script_sha,
        "measurement_grade": "server_regenerated", "engine_rule_sha": "4" * 64,
        "comment_sha": "5" * 64, "replay_status": "verified",
        "judge_script_path": script, "result_path": result,
        "result_sha256": result_sha, "measurement_lock_sha": lsha,
    })
    rsha = V.receipt_content_sha(fields)
    receipt = {**fields, "receipt_sha": rsha}
    lock_record = {
        "lock_sha": lsha,
        "payload_json": json.dumps(lock, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
    }
    node = {
        "tag": "n", "verdict": "proof", "current_receipt_sha": rsha,
        "judge_script": script, "judge_script_sha": script_sha,
        "result_path": result, "result_sha256": result_sha,
        "measurement_lock_sha": lsha, "replay_status": "verified",
        "replay_reason": None, "regenerated_metric": None,
        "receipts": [receipt], "measurement_locks": [lock_record],
    }
    return node, receipt, lock_record


def _service_row(node: dict, receipts: list[dict], locks: list[dict]) -> dict:
    receipt = receipts[0] if receipts else None
    return {
        "script": node.get("judge_script"), "rp": node.get("result_path"),
        "result_sha256": node.get("result_sha256"),
        "measurement_lock_sha": node.get("measurement_lock_sha"),
        "replay_status": node.get("replay_status"), "replay_reason": node.get("replay_reason"),
        "regenerated_metric": node.get("regenerated_metric"),
        "verdict": node.get("verdict"), "sha": node.get("judge_script_sha"),
        "current_receipt_sha": node.get("current_receipt_sha"),
        "head_receipts": receipts, "measurement_locks": locks, "prov": [],
    }


def _service(row: dict, *, env_sha: str = "3" * 64) -> EvidenceClaimService:
    return EvidenceClaimService(
        kg=lambda _query, **_params: [row],
        hist=lambda *_args, **_kwargs: None,
        foundation=lambda _name: None,
        load_lineage=lambda: [],
        reproducible_for_node=lambda *_args: None,
        environment_fingerprint=lambda: {"test": "lx3"},
        fingerprint_sha=lambda _fingerprint: env_sha,
    )


def test_writer_preserves_result_path_for_receipt_backed_and_promoted_nodes():
    captured: list[list[tuple[str, dict]]] = []

    def tx(ops):
        captured.append(ops)
        return [[{"t": "T"}] for _ in ops]

    writer = TreeKgWriter(tx)
    writer.add_node("T", NodeIn(tag="n", result_path="forged.json"), [])
    writer.upsert_nodes("T", [NodeIn(tag="n", result_path="forged.json")])

    single = captured[0][0][0]
    bulk = captured[1][0][0]
    assert "AS preserve_measured_authority" in single
    assert "AS preserve_measured_authority" in bulk
    assert "WHEN claim_conflict THEN [] ELSE [1] END" in single
    assert (
        "e.result_path = CASE WHEN preserve_measured_authority "
        "THEN e.result_path ELSE $result_path END"
    ) in single
    assert (
        "e.result_path = CASE WHEN preserve_measured_authority "
        "THEN e.result_path ELSE row.result_path END"
    ) in bulk
    assert "OPTIONAL MATCH (e)-[:HAS_RECEIPT]->(authority_receipt:VerdictReceipt)" in single
    assert "OPTIONAL MATCH (e)-[:HAS_RECEIPT]->(authority_receipt:VerdictReceipt)" in bulk
    assert "admin" in captured[0][0][1]["forceful"]
    assert "admin" in captured[1][0][1]["forceful"]


def test_writer_authority_guard_covers_legacy_state_and_relationship_receipts():
    captured: list[list[tuple[str, dict]]] = []

    def tx(ops):
        captured.append(ops)
        return [[{"t": "T"}] for _ in ops]

    writer = TreeKgWriter(tx)
    writer.add_node("T", NodeIn(tag="one"), [])
    writer.upsert_nodes("T", [NodeIn(tag="many")])
    for query in (captured[0][0][0], captured[1][0][0]):
        assert "NOT coalesce(e.verdict,'') IN ['', 'proof']" in query
        assert "coalesce(e.node_state,'DRAFT') <> 'DRAFT'" in query
        assert "count(authority_receipt) > 0 AS has_any_receipt" in query
        assert "OR has_any_receipt" in query


def test_repository_projects_every_artifact_cache_field():
    seen: list[str] = []

    def kg(query, **_params):
        seen.append(query)
        if "RETURN t.title AS title" in query:
            return [{"title": "T"}]
        return []

    TreeKgRepository(kg).load_tree_data("T")
    projection = next(q for q in seen if "ORDER BY tag" in q)
    assert "e.judge_script AS judge_script" in projection
    assert "e.judge_script_sha AS judge_script_sha" in projection
    assert "e.result_path AS result_path" in projection
    assert "e.result_sha256 AS result_sha256" in projection
    assert "e.measurement_lock_sha AS measurement_lock_sha" in projection


@pytest.mark.parametrize("cache_key,sealed_key,forged", [
    ("judge_script", "judge_script_path", "/srv/forged.py"),
    ("judge_script_sha", "judge_script_sha", "d" * 64),
    ("result_path", "result_path", "/srv/forged.json"),
    ("result_sha256", "result_sha256", "f" * 64),
    ("measurement_lock_sha", "measurement_lock_sha", "e" * 64),
])
def test_fsck_rejects_each_v5_artifact_cache_drift(tmp_path, cache_key, sealed_key, forged):
    node, receipt, _lock_record = _sealed_bundle(tmp_path)
    assert node[cache_key] == receipt[sealed_key]
    node[cache_key] = forged
    findings = F.fsck_node(node)
    assert any(f.check_id == "REPLAY_INPUT_CACHE_MISMATCH" and f.severity == F.ERROR
               for f in findings)


def test_fsck_rehashes_measurement_lock_payload_json(tmp_path):
    node, _receipt, lock_record = _sealed_bundle(tmp_path)
    assert not any(f.check_id == "MEASUREMENT_LOCK_CONTENT_MISMATCH"
                   for f in F.fsck_node(node))
    payload = json.loads(lock_record["payload_json"])
    payload["outs"][0]["value"] = 999.0
    lock_record["payload_json"] = json.dumps(payload)
    finding = next(f for f in F.fsck_node(node)
                   if f.check_id == "MEASUREMENT_LOCK_CONTENT_MISMATCH")
    assert finding.severity == F.ERROR and "payload" in finding.detail


def test_fsck_rejects_identical_duplicate_head_and_lock_records(tmp_path):
    node, receipt, lock_record = _sealed_bundle(tmp_path)
    node["receipts"] = [receipt, dict(receipt)]
    assert any(f.check_id == "RECEIPT_CHAIN_MISMATCH" for f in F.fsck_node(node))

    node["receipts"] = [receipt]
    node["measurement_locks"] = [lock_record, dict(lock_record)]
    assert any(f.check_id == "MEASUREMENT_LOCK_CONTENT_MISMATCH" for f in F.fsck_node(node))


def test_ops_fsck_enriches_records_with_measurement_lock(tmp_path, monkeypatch):
    from server import app

    node, receipt, lock_record = _sealed_bundle(tmp_path)
    payload = json.loads(lock_record["payload_json"])
    payload["env_sha"] = "tampered"
    lock_record["payload_json"] = json.dumps(payload)
    queries: list[str] = []

    def kg(query, **_params):
        queries.append(query)
        if "HAS_RECEIPT" in query:
            return [{"tag": "n", "receipts": [receipt]}]
        if "HAS_LOCK" in query:
            return [{"tag": "n", "measurement_locks": [lock_record]}]
        return [{"name": "T"}]

    base = {k: v for k, v in node.items() if k not in {"receipts", "measurement_locks"}}
    monkeypatch.setattr(app, "kg", kg)
    monkeypatch.setattr(app, "tree_data", lambda _name: {"nodes": [base]})
    out = app.ops_fsck()
    assert out["counts"].get("MEASUREMENT_LOCK_CONTENT_MISMATCH") == 1
    lock_query = next(query for query in queries if "HAS_LOCK" in query)
    assert "collect(DISTINCT ml" not in lock_query


def test_provenance_uses_only_valid_v5_sealed_replay_inputs(tmp_path):
    node, receipt, lock_record = _sealed_bundle(tmp_path)
    out = _service(_service_row(node, [receipt], [lock_record])).provenance("T", "n")
    assert out["authoritative"] is True
    assert out["receipt_sha"] == receipt["receipt_sha"]
    assert out["script"] == receipt["judge_script_path"]
    assert out["result_path"] == receipt["result_path"]
    assert shlex.split(out["replay"]) == ["python", receipt["judge_script_path"], receipt["result_path"]]


@pytest.mark.parametrize("mutation", ["invalid_receipt", "node_path_drift", "node_script_sha_drift"])
def test_provenance_fails_closed_for_invalid_v5_or_cache_drift(tmp_path, mutation):
    node, receipt, lock_record = _sealed_bundle(tmp_path)
    if mutation == "invalid_receipt":
        receipt["result_path"] = "/srv/forged.json"
    elif mutation == "node_path_drift":
        node["result_path"] = "/srv/forged.json"
    else:
        node["judge_script_sha"] = "f" * 64
    with pytest.raises(HTTPException) as exc:
        _service(_service_row(node, [receipt], [lock_record])).provenance("T", "n")
    assert exc.value.status_code == 409


@pytest.mark.parametrize("unbound", [
    "relative_script", "invalid_script_sha", "missing_result_sha", "missing_lock",
    "missing_lock_record", "invalid_lock",
])
def test_content_valid_v5_with_unbound_replay_inputs_is_non_authoritative(tmp_path, unbound):
    node, receipt, lock_record = _sealed_bundle(tmp_path)
    locks = [lock_record]
    if unbound == "relative_script":
        receipt["judge_script_path"] = "relative/scorer.py"
        node["judge_script"] = receipt["judge_script_path"]
    elif unbound == "invalid_script_sha":
        receipt["judge_script_sha"] = "not-a-sha"
        node["judge_script_sha"] = "not-a-sha"
    elif unbound == "missing_result_sha":
        receipt["result_sha256"] = None
        node["result_sha256"] = None
    elif unbound == "missing_lock":
        receipt["measurement_lock_sha"] = None
        node["measurement_lock_sha"] = None
        locks = []
    elif unbound == "missing_lock_record":
        locks = []
    else:
        payload = json.loads(lock_record["payload_json"])
        payload["outs"][0]["value"] = 999.0
        lock_record["payload_json"] = json.dumps(payload)
    receipt["receipt_sha"] = V.receipt_content_sha(receipt)
    node["current_receipt_sha"] = receipt["receipt_sha"]

    out = _service(_service_row(node, [receipt], locks)).provenance("T", "n")
    assert out["authoritative"] is False
    assert out["replay"] is None
    assert out["authority_reason"] == "v5_replay_inputs_unbound"


@pytest.mark.parametrize("semantic_field", ["outs", "measurement_grade", "replay_status"])
def test_resealed_lock_with_wrong_measurement_semantics_is_rejected(tmp_path, semantic_field):
    """Every individual hash remains valid; only the receipt↔lock semantic relation is false."""
    node, receipt, lock_record = _sealed_bundle(tmp_path)
    payload = json.loads(lock_record["payload_json"])
    if semantic_field == "outs":
        payload["outs"] = [{"name": "m", "value": 999.0}]
    elif semantic_field == "measurement_grade":
        payload["measurement_grade"] = "attested"
    else:
        payload["replay_status"] = "mismatch"

    new_lock_sha = lock_sha(payload)
    lock_record.update(
        lock_sha=new_lock_sha,
        payload_json=json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
    )
    receipt["measurement_lock_sha"] = new_lock_sha
    node["measurement_lock_sha"] = new_lock_sha
    receipt["receipt_sha"] = V.receipt_content_sha(receipt)
    node["current_receipt_sha"] = receipt["receipt_sha"]

    findings = F.fsck_node(node)
    assert any(f.check_id == "MEASUREMENT_LOCK_CONTENT_MISMATCH" for f in findings)
    out = _service(_service_row(node, [receipt], [lock_record])).provenance("T", "n")
    assert out["authoritative"] is False
    assert out["authority_reason"] == "v5_replay_inputs_unbound"


def test_provenance_environment_drift_is_explicitly_non_authoritative(tmp_path):
    node, receipt, lock_record = _sealed_bundle(tmp_path)
    out = _service(
        _service_row(node, [receipt], [lock_record]), env_sha="9" * 64,
    ).provenance("T", "n")
    assert out["authoritative"] is False
    assert out["replay"] is None
    assert out["authority_reason"] == "measurement_environment_drift"


@pytest.mark.parametrize("duplicate", ["head", "lock"])
def test_provenance_rejects_duplicate_current_head_or_lock_without_distinct_collapse(tmp_path, duplicate):
    node, receipt, lock_record = _sealed_bundle(tmp_path)
    receipts = [receipt, dict(receipt)] if duplicate == "head" else [receipt]
    locks = [lock_record, dict(lock_record)] if duplicate == "lock" else [lock_record]
    queries: list[str] = []

    def kg(query, **_params):
        queries.append(query)
        return [_service_row(node, receipts, locks)]

    svc = EvidenceClaimService(
        kg=kg, hist=lambda *_a, **_k: None, foundation=lambda _n: None,
        load_lineage=lambda: [], reproducible_for_node=lambda *_a: None,
    )
    with pytest.raises(HTTPException) as exc:
        svc.provenance("T", "n")
    assert exc.value.status_code == 409
    assert "collect(DISTINCT ml" not in queries[0]


@pytest.mark.parametrize("artifact", ["script", "result"])
def test_provenance_rehashes_current_artifacts_and_rejects_disk_drift(tmp_path, artifact):
    node, receipt, lock_record = _sealed_bundle(tmp_path)
    path = receipt["judge_script_path" if artifact == "script" else "result_path"]
    with open(path, "a", encoding="utf-8") as stream:
        stream.write("drift\n")
    with pytest.raises(HTTPException) as exc:
        _service(_service_row(node, [receipt], [lock_record])).provenance("T", "n")
    assert exc.value.status_code == 409
    assert "artifact drift" in str(exc.value.detail)


def test_legacy_provenance_is_explicitly_non_authoritative(tmp_path):
    node, receipt, _lock_record = _sealed_bundle(tmp_path)
    legacy_fields = {key: receipt.get(key) for key in V.RECEIPT_FIELDS_V3}
    legacy_sha = V.receipt_content_sha(legacy_fields, fieldset=V.RECEIPT_FIELDS_V3)
    legacy = {**legacy_fields, "receipt_sha": legacy_sha}
    node["current_receipt_sha"] = legacy_sha
    out = _service(_service_row(node, [legacy], [])).provenance("T", "n")
    assert out["authoritative"] is False
    assert out["replay"] is None
    assert out["authority_reason"] == "legacy_receipt_not_artifact_bound"


def test_replay_command_shell_quotes_each_argv_component():
    script = "/srv/judges/LX3 scorer.py"
    result = "/srv/results/lot; $(touch nope).json"
    cmd = replay_command(script, result)
    assert shlex.split(cmd) == ["python", script, result]
