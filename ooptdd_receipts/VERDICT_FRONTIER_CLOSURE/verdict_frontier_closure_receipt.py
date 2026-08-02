"""Executable receipt for the real verdict-to-frontier transaction.

The adapter drives ``JudgementService.register_prediction`` and
``JudgementService.submit_test_result`` through the stateful KG harness used by
the service contract tests.  That harness only acknowledges closure when the
production Cypher still contains the question lock, closure ledger, receipt
causality, and node-to-question binding.  Consequently this receipt turns RED
when either the verdict policy *or the production transaction* is removed.

``LKT_VFC_INJECT=suppress-conclusive`` temporarily empties the production
question-answer verdict set.  The same locked requirements must turn RED, then
the policy is restored in ``finally``.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import tempfile

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lakatos import frontier_state as frontier  # noqa: E402


def _load_service_harness():
    """Load the faithful stateful KG seam without duplicating service policy."""

    path = _ROOT / "tests" / "test_prediction_receipt_20260710.py"
    spec = importlib.util.spec_from_file_location("_vfc_service_harness", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load service harness: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _event(cid, name, **attrs):
    return {
        "cid": cid,
        "correlation_id": cid,
        "cycle_id": cid,
        "service": "lakatos.verdict_frontier_closure",
        "event": name,
        **attrs,
    }


def verify(backend, cid):
    harness = _load_service_harness()
    saved = frontier.QUESTION_ANSWER_VERDICTS
    try:
        if os.getenv("LKT_VFC_INJECT") == "suppress-conclusive":
            frontier.QUESTION_ANSWER_VERDICTS = frozenset()

        with tempfile.TemporaryDirectory() as tmp:
            result, producer = harness._verified_progressive_result(Path(tmp))
            service, kg = harness._svc(producer=producer)
            service.register_prediction("T", "seam", harness._pred())
            close = service.submit_test_result("T", "seam", result)
        assert close["verdict"] == "progressive", close
        assert close["question"] == {
            "target": "q-x",
            "closed": True,
            "state": "CLOSED",
            "transition": "adjudication-close",
        }, (
            "real service transaction did not close its receipt-bound question: "
            f"{close['question']!r}"
        )
        assert kg.questions["q-x"]["status"] == "CLOSED"
        assert kg.questions["q-x"]["closed_by"] == ["seam"]
        verdict_receipts = [
            receipt for receipt in kg.receipts
            if receipt.get("verdict_source") == "scripted"
        ]
        assert len(verdict_receipts) == 1, verdict_receipts
        assert kg.questions["q-x"]["closed_events"] == [
            verdict_receipts[0]["receipt_sha"]
        ], "FSM event identity drifted from the persisted verdict receipt"
        backend.ship([_event(
            cid,
            "adjudication_closed_question",
            transition=close["question"]["transition"],
            receipt_sha=verdict_receipts[0]["receipt_sha"],
            closure_event_id=kg.questions["q-x"]["closed_events"][0],
        )])

        service, kg = harness._svc()
        service.register_prediction("T", "seam", harness._pred())
        retained = service.submit_test_result(
            "T",
            "seam",
            harness.Result(metric_value=1.0, script="inline", novel_measured=1.0),
        )
        assert retained["verdict"] == "progressive_unverified", retained
        assert retained["question"] == {
            "target": "q-x",
            "closed": False,
            "state": "OPEN",
            "transition": "adjudication-retain-open",
        }, (
            f"nonconclusive service adjudication changed frontier: {retained!r}"
        )
        assert kg.questions["q-x"]["status"] == "OPEN"
        backend.ship([_event(
            cid,
            "nonconclusive_question_retained",
            transition=retained["question"]["transition"],
        )])

        service, kg = harness._svc()
        service.register_prediction("T", "seam", harness._pred())
        kg.questions["q-x"]["status"] = "CLOSED"
        duplicate = service.submit_test_result(
            "T",
            "seam",
            harness.Result(
                metric_value=1.0,
                script="inline",
                novel_measured=1.0,
                lakatos_anomaly=True,
                lakatos_consequence=True,
                lakatos_excess=True,
                lakatos_hardcore=True,
            ),
        )
        assert duplicate["question"] == {
            "target": "q-x",
            "closed": False,
            "state": "CLOSED",
            "transition": "duplicate-adjudication",
        }, (
            f"preclosed service adjudication was not idempotent: {duplicate!r}"
        )
        assert kg.questions["q-x"]["closed_by"] == []
        backend.ship([_event(
            cid,
            "duplicate_adjudication_idempotent",
            transition=duplicate["question"]["transition"],
        )])
    finally:
        frontier.QUESTION_ANSWER_VERDICTS = saved
