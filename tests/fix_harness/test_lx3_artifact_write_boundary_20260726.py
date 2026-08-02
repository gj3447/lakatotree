"""Write-boundary guards for LX3 scorer/result/MeasurementLock receipt binding."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from lakatos.io.replay import ProducerReplayVerdict
from lakatos import measurement_lock as measurement_lock_mod
from lakatos.replay_artifacts import snapshot_path
from lakatos.verdicts import receipt_content_sha
from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import TestResultIn as Result
from server.file_hashing import file_sha


@pytest.fixture(autouse=True)
def _private_replay_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("LAKATOS_REPLAY_CACHE_ROOT", str(tmp_path / "server-replay-cache"))


class SubmitKg:
    def __init__(self, *, existing_result_path: str = ""):
        self.existing_result_path = existing_result_path
        self.tx_ops: list[list[tuple[str, dict]]] = []
        self.queries: list[str] = []

    def __call__(self, query: str, **_params):
        self.queries.append(query)
        if "pred_metric AS m" in query:
            return [{
                "m": "seam", "d": "lower", "b": 10.0, "nb": 0.0,
                "scale": "ratio", "novel": "", "vsrc": None,
                "nmet": None, "ndir": None, "nthr": None, "psha": None,
                "closes": None, "n_opened": 0,
                "pred_registered_at": "2026-07-26", "node_state": "PREDICTED",
                "judged_at": None, "existing_metric_value": None,
                "existing_result_path": self.existing_result_path,
                "hard_core": "", "require_novel_anchor": False,
                "assurance_tier": None, "attestor_dids": None,
                "prev_receipt_sha": None,
            }]
        return []

    def tx(self, ops):
        self.tx_ops.append(ops)
        return [[{"claimed": "seam"}] for _ in ops]


class CrossVerbRaceKg(SubmitKg):
    """Simulate another verdict verb advancing the receipt pointer after submit's preread."""

    def tx(self, ops):
        self.tx_ops.append(ops)
        query, params = ops[0]
        if "coalesce(e.current_receipt_sha,'') = coalesce($prev_rsha,'')" not in query:
            return [[{"claimed": "seam"}] for _ in ops]
        assert params["prev_rsha"] == "p" * 64
        return [[], *[[{"ok": True}] for _ in ops[1:]]]


def _files(tmp_path: Path) -> tuple[Path, Path]:
    script = tmp_path / "score.py"
    result = tmp_path / "result.json"
    script.write_text("print(1.0)\n", encoding="utf-8")
    result.write_text('{"metric":1.0}\n', encoding="utf-8")
    return script, result


def _service(kg: SubmitKg, producer) -> JudgementService:
    return JudgementService(
        kg=kg, kg_tx=kg.tx, hist=lambda *_a, **_k: None,
        foundation=lambda _name: None,
        reproducible_for_node=lambda *_a: None,
        producer_replay_submit=producer,
    )


def test_existing_result_path_is_the_single_canonical_input_and_lock_is_atomic(tmp_path):
    script, result = _files(tmp_path)
    replay_args: list[tuple] = []

    def producer(*args):
        replay_args.append(args)
        return ProducerReplayVerdict(True, 1.0, 1.0, "externally_verified")

    kg = SubmitKg(existing_result_path=str(result))
    out = _service(kg, producer).submit_test_result(
        "T", "seam", Result(metric_value=1.0, script=str(script), result_path=""))

    source_script_path, source_result_path = str(script.resolve()), str(result.resolve())
    script_path = str(snapshot_path(
        kind="script", sha256=file_sha(source_script_path), source_path=source_script_path))
    result_path = str(snapshot_path(
        kind="result", sha256=file_sha(source_result_path), source_path=source_result_path))
    assert replay_args == [(script_path, result_path, 1.0)]
    cypher, params = kg.tx_ops[0][0]
    assert params["script"] == script_path and params["rp"] == result_path
    assert params["source_script"] == source_script_path
    assert params["source_rp"] == source_result_path
    assert params["result_sha256"] == file_sha(result_path)
    assert params["lsha"] == out["measurement_lock_sha"]
    expected_deps = [
        {"path": script_path, "sha256": file_sha(source_script_path)},
        {"path": result_path, "sha256": file_sha(source_result_path)},
    ]
    assert json.loads(params["lock_payload_json"])["deps"] == sorted(
        expected_deps, key=lambda dep: dep["path"])
    assert "FOREACH (_ IN CASE WHEN $lsha IS NULL" in cypher
    assert "ml.payload_json=$lock_payload_json" in cypher
    assert not any("MERGE (ml:MeasurementLock" in query for query in kg.queries), \
        "MeasurementLock must not be minted in a post-transaction side write"

    sealed = {
        "tree": "T", "tag": "seam", "target_id": params["target_id"],
        "verdict": params["v"], "verdict_source": "scripted",
        "metric_name": params["mn"], "metric_value": params["mv"],
        "novel_confirmed": params["novel"], "lakatos_status": params["lstat"],
        "judged_at": params["ts"], "judge_script_sha": params["sha"],
        "prev_receipt_sha": params["prev_rsha"], "measurement_grade": params["mg"],
        "engine_rule_sha": params["engine_rule_sha"], "comment_sha": params["csha"],
        "replay_status": params["replay_status"], "replay_reason": params["replay_reason"],
        "regenerated_metric": params["regenerated_metric"],
        "judge_script_path": params["script"], "result_path": params["rp"],
        "result_sha256": params["result_sha256"], "measurement_lock_sha": params["lsha"],
        "source_script_path": params["source_script"],
        "source_result_path": params["source_rp"],
        "history_payload_sha256": params["history_payload_sha256"],
    }
    assert receipt_content_sha(sealed) == params["rsha"]
    assert out["replay_authoritative"] is True


def test_unsealed_result_never_reaches_scorer_or_earns_replay_authority(tmp_path):
    script, _result = _files(tmp_path)
    called = False

    def producer(*_args):
        nonlocal called
        called = True
        return ProducerReplayVerdict(True, 1.0, 1.0, "externally_verified")

    kg = SubmitKg()
    out = _service(kg, producer).submit_test_result(
        "T", "seam", Result(
            metric_value=1.0, script=str(script), result_path="/etc/passwd"))
    params = kg.tx_ops[0][0][1]
    assert called is False
    assert params["mg"] == "client_asserted"
    assert params["replay_status"] == "not_replayable"
    assert params["result_sha256"] is None and params["lsha"] is None
    assert out["replay_authoritative"] is False and out["replay"] is None


def test_cross_verb_receipt_pointer_advance_causes_atomic_cas_409(tmp_path):
    script, result = _files(tmp_path)
    kg = CrossVerbRaceKg()

    original_call = kg.__call__

    def preread_with_pointer(query, **params):
        rows = original_call(query, **params)
        if "pred_metric AS m" in query:
            rows[0]["prev_receipt_sha"] = "p" * 64
        return rows

    svc = JudgementService(
        kg=preread_with_pointer, kg_tx=kg.tx, hist=lambda *_a, **_k: None,
        foundation=lambda _name: None, reproducible_for_node=lambda *_a: None,
        producer_replay_submit=lambda *_a: None,
    )
    with pytest.raises(HTTPException) as exc:
        svc.submit_test_result("T", "seam", Result(
            metric_value=1.0, script=str(script), result_path=str(result)))
    assert exc.value.status_code == 409
    assert "동시/재채점 차단" in str(exc.value.detail)


@pytest.mark.parametrize("mutated", ["script", "result"])
def test_submitter_source_swap_cannot_change_executed_snapshot(tmp_path, mutated):
    script, result = _files(tmp_path)
    executed = []

    def producer(script_snapshot, result_snapshot, _metric):
        before = (Path(script_snapshot).read_bytes(), Path(result_snapshot).read_bytes())
        target = script if mutated == "script" else result
        target.write_text("malicious bytes during replay\n", encoding="utf-8")
        executed.append((script_snapshot, result_snapshot, before,
                         Path(script_snapshot).read_bytes(), Path(result_snapshot).read_bytes()))
        return ProducerReplayVerdict(True, 1.0, 1.0, "externally_verified")

    kg = SubmitKg()
    out = _service(kg, producer).submit_test_result(
        "T", "seam", Result(
            metric_value=1.0, script=str(script), result_path=str(result)))
    assert out["replay_authoritative"] is True
    assert executed and executed[0][2] == executed[0][3:]
    assert all("server-replay-cache" in p for p in executed[0][:2])


def test_symbol_body_hash_with_real_result_is_never_executable_replay(tmp_path):
    script = tmp_path / "symbol_score.py"
    result = tmp_path / "result.json"
    script.write_text("def score():\n    return 1.0\n", encoding="utf-8")
    result.write_text('{"metric":1.0}\n', encoding="utf-8")
    called = False

    def producer(*_args):
        nonlocal called
        called = True
        return ProducerReplayVerdict(True, 1.0, 1.0, "externally_verified")

    kg = SubmitKg()
    out = _service(kg, producer).submit_test_result(
        "T", "seam", Result(
            metric_value=1.0, script=f"{script}::score", result_path=str(result)))
    assert called is False
    assert out["replay_status"] == "not_replayable"
    assert out["measurement_lock_sha"] is None
    assert out["replay_authoritative"] is False


def test_measurement_lock_mint_failure_aborts_before_graph_write(tmp_path, monkeypatch):
    script, result = _files(tmp_path)
    kg = SubmitKg()
    monkeypatch.setattr(
        measurement_lock_mod, "build_measurement_lock",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("lock backend failed")))
    with pytest.raises(HTTPException) as exc:
        _service(kg, lambda *_args: ProducerReplayVerdict(
            True, 1.0, 1.0, "externally_verified")).submit_test_result(
                "T", "seam", Result(
                    metric_value=1.0, script=str(script), result_path=str(result)))
    assert exc.value.status_code == 503
    assert kg.tx_ops == []
