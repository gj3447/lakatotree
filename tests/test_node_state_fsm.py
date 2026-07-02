"""Node lifecycle FSM harness.

The state tree is stored in KG as ``node_state`` but remains derivable from the
older verdict/source/timestamp fields for legacy rows. These tests keep both
surfaces aligned.
# KG: span_lakatotree_node_state_fsm
"""

from __future__ import annotations

import pytest

from lakatos.node_state import NodeState, assert_transition_allowed, derive_node_state
from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.repository import normalize_node_row
from server.contexts.tree.schemas import NodeIn, TestResultIn as _TestResultIn
from server.contexts.tree.writer import TreeKgWriter


def test_node_state_derives_closed_lifecycle_from_kg_fields():
    assert derive_node_state({"verdict": "proof"}) == NodeState.DRAFT
    assert derive_node_state({"pred_registered_at": "2026-06-26", "pred_metric": "m"}) == NodeState.PREDICTED
    assert derive_node_state({"metric_value": 1.0}) == NodeState.MEASURED
    assert derive_node_state({"verdict": "partial", "verdict_source": "scripted"}) == NodeState.JUDGED_SCRIPTED
    assert derive_node_state({
        "verdict": "progressive",
        "verdict_source": "scripted",
        "novel_confirmed": True,
    }) == NodeState.CANONICAL_CANDIDATE
    assert derive_node_state({"verdict": "progressive", "verdict_source": None}) == NodeState.INCONCLUSIVE
    assert derive_node_state({"verdict": "CANONICAL", "verdict_source": "admin"}) == NodeState.CANONICAL
    assert derive_node_state({"verdict": "former_canonical", "verdict_source": "engine"}) == NodeState.FORMER_CANONICAL
    assert derive_node_state({"verdict": "rejected", "verdict_source": "scripted"}) == NodeState.REJECTED
    assert derive_node_state({"verdict": "different_programme", "verdict_source": "scripted"}) == NodeState.DIFFERENT_PROGRAMME


def test_node_state_transition_table_blocks_shortcuts():
    assert_transition_allowed(NodeState.DRAFT, NodeState.PREDICTED)
    assert_transition_allowed(NodeState.PREDICTED, NodeState.CANONICAL_CANDIDATE)
    assert_transition_allowed(NodeState.CANONICAL_CANDIDATE, NodeState.CANONICAL)
    assert_transition_allowed(NodeState.CANONICAL, NodeState.FORMER_CANONICAL)
    assert_transition_allowed(NodeState.DRAFT, NodeState.CANONICAL)  # human/reproducible floor path
    with pytest.raises(ValueError):
        assert_transition_allowed(NodeState.CANONICAL, NodeState.PREDICTED)


def test_writer_persists_draft_node_state_to_kg():
    captured = []

    def kg_tx(ops):
        captured.append(list(ops))
        return [[{"t": "T"}] for _ in ops]

    TreeKgWriter(kg_tx).add_node("T", NodeIn(tag="root"), [])

    cypher, params = captured[0][0]
    # G1(2026-07-02): node_state 는 verdict-preservation CASE 를 통해 SET 된다(scored 보존/draft 갱신).
    # 계약 불변 — 신규 노드는 $node_state=DRAFT 로 지속(ELSE 분기). 리터럴 shape 만 CASE 로 바뀜.
    assert "e.node_state = CASE" in cypher and "$node_state" in cypher
    assert params["node_state"] == NodeState.DRAFT.value


def test_repository_derives_node_state_for_legacy_rows_without_kg_state():
    row = normalize_node_row({
        "tag": "n",
        "verdict": "progressive",
        "verdict_source": "scripted",
        "novel_confirmed": True,
    })
    assert row["node_state"] == NodeState.CANONICAL_CANDIDATE.value


def test_submit_test_result_persists_derived_scripted_state():
    captured = []

    def kg(query, **params):
        if "RETURN e.pred_metric AS m" in query:
            return [dict(
                m="p95", d="lower", b=0.5, nb=0.05, scale="ratio", novel="",
                vsrc=None, nmet=None, ndir=None, nthr=None, psha=None,
                pred_registered_at="2026-06-26T00:00:00+00:00",
                node_state=NodeState.PREDICTED.value,
                judged_at=None, existing_metric_value=None,
                closes=None, n_opened=0, hard_core="",
            )]
        return []

    def kg_tx(ops):
        captured.append(list(ops))
        return [[{"claimed": "n"}] for _ in ops]

    svc = JudgementService(
        kg=kg,
        kg_tx=kg_tx,
        hist=lambda *a, **k: None,
        foundation=lambda *a, **k: None,
        reproducible_for_node=lambda *a, **k: None,
    )
    out = svc.submit_test_result("T", "n", _TestResultIn(metric_value=0.4, script="inline"))

    assert out["ok"] is True
    claim_cypher, claim_params = captured[0][0]
    assert "e.node_state=$node_state" in claim_cypher
    assert claim_params["node_state"] == NodeState.JUDGED_SCRIPTED.value
