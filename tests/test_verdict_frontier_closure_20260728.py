"""Verdict-driven frontier closure and typed-density surface contracts.

Locked before implementation on 2026-07-28.  A receipt-backed conclusive
adjudication must deliver the frontier FSM event in the same transaction as the
verdict; inconclusive/non-closing verdicts must leave the question open.
"""
from __future__ import annotations

import json
import inspect
from pathlib import Path

import pytest

from lakatos.frontier_state import QuestionEffect, QuestionEvent, QuestionState, step
from lakatos.quant.metrics import tree_metrics
from server.contexts.tree.judgement_service import JudgementService


_ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize("verdict", ["progressive", "rejected"])
def test_receipted_conclusive_adjudication_closes_open_question(verdict):
    transition = step(
        QuestionState.OPEN,
        QuestionEvent.ADJUDICATED,
        verdict=verdict,
        receipt_sha="a" * 64,
        assurance_level=2,
    )

    assert transition.state is QuestionState.CLOSED
    assert transition.transition_id == "adjudication-close"
    assert transition.effects == (QuestionEffect.RECORD_CLOSURE,)


@pytest.mark.parametrize(
    "verdict",
    [
        "partial", "equivalent", "progressive_unverified", "progressive_conditional",
        "degenerating", "withdrawn", "different_programme", "ambiguous",
    ],
)
def test_nonconclusive_adjudication_retains_open_question(verdict):
    transition = step(
        QuestionState.OPEN,
        QuestionEvent.ADJUDICATED,
        verdict=verdict,
        receipt_sha="b" * 64,
        assurance_level=2,
    )

    assert transition.state is QuestionState.OPEN
    assert transition.transition_id == "adjudication-retain-open"
    assert transition.effects == ()


def test_adjudication_without_receipt_is_rejected_not_treated_as_close():
    with pytest.raises(ValueError, match="receipt"):
        step(
            QuestionState.OPEN,
            QuestionEvent.ADJUDICATED,
            verdict="progressive",
            receipt_sha="",
            assurance_level=2,
        )


@pytest.mark.parametrize("receipt_sha", ["a", "A" * 64, "g" * 64, "a" * 63, "a" * 65])
def test_adjudication_requires_canonical_sha256_receipt_identity(receipt_sha):
    with pytest.raises(ValueError, match="sha256"):
        step(
            QuestionState.OPEN,
            QuestionEvent.ADJUDICATED,
            verdict="progressive",
            receipt_sha=receipt_sha,
            assurance_level=2,
        )


def test_duplicate_adjudication_is_idempotent():
    transition = step(
        QuestionState.CLOSED,
        QuestionEvent.ADJUDICATED,
        verdict="progressive",
        receipt_sha="c" * 64,
        assurance_level=2,
    )

    assert transition.state is QuestionState.CLOSED
    assert transition.transition_id == "duplicate-adjudication"
    assert transition.effects == ()


@pytest.mark.parametrize("assurance_level", [None, 0, 1])
@pytest.mark.parametrize("verdict", ["progressive", "rejected"])
def test_unverified_receipt_cannot_close_frontier(verdict, assurance_level):
    transition = step(
        QuestionState.OPEN,
        QuestionEvent.ADJUDICATED,
        verdict=verdict,
        receipt_sha="d" * 64,
        assurance_level=assurance_level,
    )

    assert transition.state is QuestionState.OPEN
    assert transition.transition_id == "adjudication-retain-open"


def test_qualitative_self_report_cannot_close_even_at_l2():
    transition = step(
        QuestionState.OPEN,
        QuestionEvent.ADJUDICATED,
        verdict="progressive",
        receipt_sha="e" * 64,
        assurance_level=2,
        qualitative_self_report=True,
    )

    assert transition.state is QuestionState.OPEN


def test_frontier_machine_source_declares_adjudication_routes():
    source = json.loads((_ROOT / "docs/data/frontier_question_fsm.v1.json").read_text())
    machine = source["machines"][0]
    routes = {
        transition["id"]: transition
        for transition in machine["transitions"]
        if transition["event"] == "ADJUDICATED"
    }

    assert set(routes) == {
        "adjudication-close",
        "adjudication-retain-open",
        "duplicate-adjudication",
    }
    assert routes["adjudication-close"]["guard"] == "receipt_backed_conclusive"
    assert routes["adjudication-close"]["effects"] == ["RecordQuestionClosure"]
    assert routes["adjudication-close"]["effect_bindings"]["RecordQuestionClosure"] \
        == {
            "tree": "event.tree",
            "question": "event.question",
            "event_id": "event.receipt_sha",
        }


def test_production_adjudication_ledger_uses_receipt_as_fsm_event_identity():
    """The executable write path must materialize the semantic-source effect payload exactly."""

    source = inspect.getsource(JudgementService.submit_test_result)

    assert "closure_id = rsha if target_id else None" in source
    assert "q.closed_events" in source
    assert "MERGE (c:QuestionClosure {id:$closure_id})" in source
    assert "c.receipt_sha=$rsha" in source


def test_question_is_write_locked_before_registration_reads_open_state():
    """Concurrent manual close must win before a bound prediction can inspect q.status."""

    source = inspect.getsource(JudgementService.register_prediction)
    lock = "SET q._cas=coalesce(q._cas, 0) + 0"
    read = "ELSE coalesce(q.status, '__MISSING__') END AS question_state"

    assert lock in source and read in source
    assert source.index(lock) < source.index(read)
    assert "question_state = $open_state" in source


def test_submit_fails_closed_before_writes_on_unknown_question_state():
    """Corrupt/novel persisted states are not silently adjudicated around the reducer."""

    source = inspect.getsource(JudgementService.submit_test_result)
    state_guard = "question_before_state IN [$open_state, $closed_state]"
    verdict_write = "SET e.metric_name=$mn"

    assert state_guard in source and verdict_write in source
    assert source.index(state_guard) < source.index(verdict_write)


def test_tree_metrics_exposes_structural_density_without_inventing_quality():
    nodes = [
        {"tag": "root", "parent_edges": [], "verdict": "proof"},
        {"tag": "a", "parent_edges": [{"tag": "root", "relation_kind": "FORMALIZES"}],
         "verdict": "proof"},
        {"tag": "b", "parent_edges": [{"tag": "root", "relation_kind": "knowledge_inheritance"}],
         "verdict": "proof"},
        {"tag": "join", "parent_edges": [
            {"tag": "a", "relation_kind": "TESTS"},
            {"tag": "b", "relation_kind": "DEPENDS_ON"},
        ], "verdict": "proof"},
        {"tag": "island", "parent_edges": [], "verdict": "proof"},
    ]

    structure = tree_metrics(nodes, [])["structure"]

    assert structure == {
        "roots": 2,
        "components": 2,
        "raw_edges": 4,
        "edges": 4,
        "duplicate_edges": 0,
        "multi_parent_nodes": 1,
        "typed_edges": 3,
        "typed_edge_ratio": 0.75,
        "largest_component_ratio": 0.8,
        "dangling_edges": 0,
        "unnamed_nodes": 0,
        "duplicate_tag_nodes": 0,
    }


def test_structure_density_does_not_credit_duplicate_or_dangling_edges():
    nodes = [
        {"tag": "root", "parent_edges": [], "verdict": "proof"},
        {"tag": "child", "parent_edges": [
            {"tag": "root", "relation_kind": "TESTS"},
            {"tag": "root", "relation_kind": "TESTS"},
            {"tag": "missing", "relation_kind": "DEPENDS_ON"},
        ], "verdict": "proof"},
    ]

    structure = tree_metrics(nodes, [])["structure"]

    assert structure["raw_edges"] == 3
    assert structure["edges"] == 1
    assert structure["duplicate_edges"] == 1
    assert structure["dangling_edges"] == 1
    assert structure["multi_parent_nodes"] == 0
    assert structure["typed_edge_ratio"] == 1.0


def test_mcp_add_node_forwards_typed_parent_edges(monkeypatch):
    import lakatos.mcp_server as mcp

    seen = []
    monkeypatch.setattr(mcp, "_post", lambda path, body: seen.append((path, body)) or {"ok": True})
    monkeypatch.setattr(mcp, "_with_preflight", lambda result, preflight: result)

    mcp.add_node(
        "T",
        "child",
        parent_edges_json=json.dumps([
            {
                "tag": "root",
                "relation_kind": "FORMALIZES",
                "evidence_ref": "kg:canon-root",
                "inferred": False,
            }
        ]),
    )

    assert seen[0][1]["parent_edges"] == [{
        "tag": "root",
        "relation_kind": "FORMALIZES",
        "evidence_ref": "kg:canon-root",
        "inferred": False,
    }]


def test_mcp_add_node_rejects_non_array_parent_edges():
    import lakatos.mcp_server as mcp

    with pytest.raises(ValueError, match="JSON array"):
        mcp.add_node("T", "child", parent_edges_json='{"tag":"root"}')


@pytest.mark.parametrize("payload", [
    [{"tag": "root", "relation_kind": "TESTS"}],
    [{"tag": "root", "inferred": "yes", "evidence_ref": "kg:x"}],
    [{"tag": "root", "relation_kind": "TESTS", "evidence_ref": "kg:x", "extra": 1}],
])
def test_mcp_add_node_rejects_malformed_or_unproven_typed_edges(payload):
    import lakatos.mcp_server as mcp

    with pytest.raises(ValueError):
        mcp.add_node("T", "child", parent_edges_json=json.dumps(payload))


def test_mcp_add_node_bounds_parent_edge_count():
    import lakatos.mcp_server as mcp

    payload = [{"tag": f"p{i}"} for i in range(mcp.PARENT_EDGES_MAX_COUNT + 1)]
    with pytest.raises(ValueError, match="exceeds"):
        mcp.add_node("T", "child", parent_edges_json=json.dumps(payload))
