"""Hermetic dual-guard receipt for the receipted replay-portability boundary."""
from __future__ import annotations

import tempfile
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import HTTPException  # noqa: E402

from lakatos import assurance  # noqa: E402
from lakatos.io.replay import ProducerReplayVerdict  # noqa: E402
import server.contexts.tree.judgement_service as judgement_module  # noqa: E402
from server.contexts.tree.judgement_service import JudgementService  # noqa: E402
from server.contexts.tree.schemas import TestResultIn  # noqa: E402
from server.file_hashing import file_sha  # noqa: E402


def _event(cid: str, name: str) -> dict:
    return {
        "cid": cid,
        "correlation_id": cid,
        "cycle_id": cid,
        "service": "lakatotree.replay_portability",
        "event": name,
    }


class _Kg:
    def __init__(self, script_sha: str):
        self.script_sha = script_sha
        self.tx_ops = []

    def __call__(self, query, **_params):
        if "pred_metric AS m" in query:
            return [{
                "m": "seam", "d": "lower", "b": 10.0, "nb": 0.0,
                "scale": "ratio", "novel": "", "vsrc": None,
                "nmet": None, "ndir": None, "nthr": None,
                "psha": self.script_sha,
                "pred_registered_at": "2026-08-06", "node_state": "PREDICTED",
                "judged_at": None, "existing_metric_value": None,
                "existing_result_path": "", "existing_verdict": None,
                "existing_lstat": None, "prev_receipt_sha": None,
                "closes": None, "n_opened": 0, "hard_core": "",
                "require_novel_anchor": False, "assurance_tier": "receipted",
                "attestor_dids": None, "research_layout": None,
                "layout_owner_did": None, "layout_sig": None,
                "witness_dids": None,
            }]
        return []

    def tx(self, ops):
        self.tx_ops.append(ops)
        return [[{"claimed": "seam"}] for _ in ops]


def _service(kg: _Kg, producer_calls: list) -> JudgementService:
    def producer(*args):
        producer_calls.append(args)
        return ProducerReplayVerdict(True, 1.0, 1.0, "externally_verified")

    return JudgementService(
        kg=kg,
        kg_tx=kg.tx,
        hist=lambda *_args, **_kwargs: None,
        foundation=lambda _name: None,
        reproducible_for_node=lambda *_args: None,
        producer_replay_submit=producer,
    )


def verify(backend, cid):
    saved_root = judgement_module.longinus.ROOT
    saved_receipted = assurance.TIER_GATES["receipted"]
    try:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            repo = tmp / "repo"
            artifacts = repo / "artifacts"
            artifacts.mkdir(parents=True)
            script = artifacts / "score.py"
            result = artifacts / "result.json"
            script.write_text("print(1.0)\n", encoding="utf-8")
            result.write_text('{"metric":1.0}\n', encoding="utf-8")
            script_sha = file_sha(str(script))
            judgement_module.longinus.ROOT = repo

            positive_kg = _Kg(script_sha)
            positive_calls = []
            positive = _service(positive_kg, positive_calls).submit_test_result(
                "T",
                "seam",
                TestResultIn(
                    metric_value=1.0,
                    script="artifacts/score.py",
                    result_path="artifacts/result.json",
                    script_sha=script_sha,
                ),
            )
            if not (
                positive["replay_authoritative"] is True
                and len(positive_calls) == 1
                and len(positive_kg.tx_ops) == 1
            ):
                raise RuntimeError("portable positive path did not reach one guarded write")

            rejected_kg = _Kg(script_sha)
            rejected_calls = []
            try:
                _service(rejected_kg, rejected_calls).submit_test_result(
                    "T",
                    "seam",
                    TestResultIn(
                        metric_value=1.0,
                        script=str(script),
                        result_path=str(result),
                        script_sha=script_sha,
                    ),
                )
            except HTTPException as exc:
                rejected = exc.status_code == 422
            else:
                rejected = False
            if not rejected or rejected_calls or rejected_kg.tx_ops:
                raise RuntimeError("absolute-path artifact crossed the portable write boundary")
            backend.ship([_event(cid, "portable_artifact_boundary_verified")])

            # Genuine negative oracle: remove only the new tier bit.  The same request must now
            # traverse the unchanged permissive compatibility path and reach the capture tx.
            assurance.TIER_GATES["receipted"] = frozenset(
                bit for bit in saved_receipted
                if bit != assurance.GATE_REPLAY_PORTABILITY
            )
            ablated_kg = _Kg(script_sha)
            ablated_calls = []
            _service(ablated_kg, ablated_calls).submit_test_result(
                "T",
                "seam",
                TestResultIn(
                    metric_value=1.0,
                    script=str(script),
                    result_path=str(result),
                    script_sha=script_sha,
                ),
            )
            if len(ablated_calls) != 1 or len(ablated_kg.tx_ops) != 1:
                raise RuntimeError("gate ablation did not expose the absolute-path defect")
            backend.ship([_event(cid, "portability_gate_load_bearing")])
    finally:
        judgement_module.longinus.ROOT = saved_root
        assurance.TIER_GATES["receipted"] = saved_receipted
