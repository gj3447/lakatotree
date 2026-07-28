"""Executable receipt for adjudication-backed Laudan budget accounting.

The adapter drives the production ``tree_metrics`` and ``branch_inputs``
surfaces.  ``LKT_HSWM_LAUDAN_INJECT=count-structure`` temporarily restores the
defect by treating every graph node as an attempt; the locked requirements must
then turn RED, and the production helper is restored in ``finally``.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys


_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lakatos.quant import metrics  # noqa: E402


def _event(cid: str, name: str, **attrs) -> dict:
    return {
        "cid": cid,
        "correlation_id": cid,
        "cycle_id": cid,
        "service": "lakatos.hswm_laudan_spend",
        "event": name,
        **attrs,
    }


def _state(*, adjudicated: bool, source: str | None = None) -> dict:
    return {
        "verdict_source": source,
        "current_receipt_sha": ("a" * 64 if adjudicated else None),
        "judged_at": ("2026-07-28T00:00:00+00:00" if adjudicated else None),
        "measurement_grade": ("server_regenerated" if adjudicated else None),
        "replay_status": ("verified" if adjudicated else None),
    }


def _branch(*, adjudicated: bool, label_only: bool = False) -> list[dict]:
    nodes = [dict(
        tag="root", verdict="CANONICAL", parent=None, parents=[],
        **_state(adjudicated=False),
    )]
    parent = "root"
    for index in range(5):
        tag = f"layer-{index}"
        row = dict(
            tag=tag,
            verdict=("partial" if adjudicated else "proof"),
            parent=parent,
            parents=[parent],
            **_state(
                adjudicated=adjudicated,
                source=("scripted" if adjudicated or label_only else None),
            ),
        )
        if label_only:
            row["current_receipt_sha"] = "b" * 64
        nodes.append(row)
        parent = tag
    leaf = dict(
        tag="open-experiment",
        verdict="progressive_conditional",
        parent=parent,
        parents=[parent],
        **_state(
            adjudicated=adjudicated,
            source=("engine" if adjudicated or label_only else None),
        ),
    )
    if label_only:
        leaf["current_receipt_sha"] = "c" * 64
    nodes.append(leaf)
    return nodes


def _candidates(nodes: list[dict]) -> list[dict]:
    return metrics.tree_metrics(nodes, [])["laudan"]["abandon_candidates"]


def verify(backend, cid):
    original = metrics._attempted_chain
    try:
        injected = os.getenv("LKT_HSWM_LAUDAN_INJECT") == "count-structure"
        if injected:
            metrics._attempted_chain = lambda chain: list(chain)

        structural = _branch(adjudicated=False)
        label_only = _branch(adjudicated=False, label_only=True)
        structural_inputs = metrics.branch_inputs(
            structural, [], leaf="open-experiment"
        )
        if injected:
            assert _candidates(structural), "fault injection did not revive false abandon"
            assert _candidates(label_only), "fault injection did not count label-only rows"
            assert structural_inputs["nodes_spent"] > 0, structural_inputs
        else:
            assert _candidates(structural) == [], "dense structure consumed scientific budget"
            assert _candidates(label_only) == [], "label/prediction-only rows consumed budget"
            assert structural_inputs["nodes_spent"] == 0, structural_inputs
            backend.ship([_event(
                cid,
                "structural_depth_retained_without_spend",
                graph_depth=6,
                nodes_spent=structural_inputs["nodes_spent"],
                label_only_retained=True,
            )])

        # Keep the second gate as a positive control during fault injection so
        # the OOPTDD evaluator reports a missing-event RED (1/2), not an adapter
        # crash.  The defect is isolated to the structural-spend guard above.
        if injected:
            metrics._attempted_chain = original
        adjudicated = _branch(adjudicated=True)
        candidates = _candidates(adjudicated)
        candidate = next(
            row for row in candidates if row["leaf"] == "open-experiment"
        )
        adjudicated_inputs = metrics.branch_inputs(
            adjudicated, [], leaf="open-experiment"
        )
        assert adjudicated_inputs["nodes_spent"] == 6, adjudicated_inputs
        assert adjudicated_inputs["prediction_hits"] == 0, adjudicated_inputs
        assert "예산" in candidate["reason"], candidate
        backend.ship([_event(
            cid,
            "adjudicated_attempts_trigger_zero_hit_budget",
            nodes_spent=adjudicated_inputs["nodes_spent"],
            prediction_hits=adjudicated_inputs["prediction_hits"],
            reason=candidate["reason"],
        )])
    finally:
        metrics._attempted_chain = original
