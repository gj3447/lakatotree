"""트리별 Belief 격리와 frontier-question FSM 회귀 가드.

행동 계약을 구현보다 먼저 고정한다. Belief 식별자는 ``(tree, belief_id)``이고,
질문은 OPEN/CLOSED 상태기계로만 전이한다. CLOSED 질문의 재개는 거부하며 CLOSE는 멱등이다.
# KG: state-isolation-frontier-fsm-20260728
"""
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from lakatos.programme.agm import Belief
from server.contexts.tree.schemas import QuestionIn
from server.contexts.tree.service import TreeService


def load_app():
    os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
    os.environ.setdefault("NEO4J_USER", "neo4j")
    os.environ.setdefault("NEO4J_PASSWORD", "test")
    return importlib.import_module("server.app")


def test_belief_writes_and_abandon_are_tree_scoped(monkeypatch):
    app = load_app()
    ops_seen = []
    monkeypatch.setattr(app, "kg_tx", lambda ops: ops_seen.extend(ops) or [[] for _ in ops])
    monkeypatch.setattr(app, "kg", lambda *a, **k: [])
    result = SimpleNamespace(
        base=(Belief("b-live", "live", "protective_belt", 0.5, 0, 0, ()),),
        removed=("b-old",),
        added=("b-live",),
        programme_shift_candidate=False,
    )
    monkeypatch.setattr(app, "hist", lambda *a, **k: None)

    app._persist_revision("TreeA", "contraction", result, None)

    cyphers = "\n".join(cypher for cypher, _ in ops_seen)
    assert "MERGE (bel:Belief {tree:$tree, belief_id: b.belief_id})" in cyphers
    assert "bel.tree=$tree AND bel.belief_id IN $removed" in cyphers


def test_belief_load_prefers_scoped_row_over_legacy_duplicate(monkeypatch):
    app = load_app()
    monkeypatch.setattr(
        app,
        "kg",
        lambda *a, **k: [
            dict(belief_id="b", statement="legacy", kind="protective_belt", scope_tree=None),
            dict(belief_id="b", statement="scoped", kind="hard_core", scope_tree="TreeA"),
        ],
    )

    beliefs = app._load_belief_base("TreeA")

    assert len(beliefs) == 1
    assert beliefs[0].statement == "scoped"


def test_frontier_reducer_conforms_to_machine_spec():
    from lakatos.frontier_state import QuestionEvent, QuestionState, step

    source = Path(__file__).parents[1] / "docs/data/frontier_question_fsm.v1.json"
    machine = json.loads(source.read_text(encoding="utf-8"))["machines"][0]
    declared = {
        (transition["from"], transition["event"]): transition
        for transition in machine["transitions"]
    }
    for state in QuestionState:
        for event in QuestionEvent:
            expected = declared.get((state.value, event.value))
            if expected is None:
                with pytest.raises(ValueError):
                    step(state, event)
                continue
            actual = step(state, event)
            assert actual.state.value == expected["to"]
            assert actual.transition_id == expected["id"]
            assert [effect.value for effect in actual.effects] == expected["effects"]


def test_belief_composite_constraint_and_migration_are_declared():
    from server.contexts.tree.diagnostics import diagnose_required_constraints

    report = diagnose_required_constraints([])
    assert "Belief.(tree+belief_id)" in report["missing"]
    assert any("lkt_belief_tree_id_key" in query for query in report["migration_cypher"])
    migration = (Path(__file__).parents[1] / "scripts/migrate_belief_tree_scope_20260728.cypher").read_text()
    assert "SUPERSEDED_BY" in migration
    assert "DELETE" not in migration.upper()


class _QuestionKg:
    def __init__(self, before_state: str):
        self.before_state = before_state
        self.calls = []

    def __call__(self, cypher, **params):
        self.calls.append((cypher, params))
        return [{
            "name": params.get("qn"),
            "before_state": self.before_state,
            "after_state": "CLOSED",
            "transitioned": self.before_state == "OPEN",
        }]


def _service(port, history):
    return TreeService(kg=port, kg_tx=None, hist=lambda *args: history.append(args), pg=None)


def test_closed_question_cannot_be_reopened():
    port = _QuestionKg("CLOSED")
    history = []

    with pytest.raises(HTTPException) as exc:
        _service(port, history).open_question("TreeA", QuestionIn(qname="q", body="rewrite"))

    assert exc.value.status_code == 409
    assert history == []


def test_duplicate_close_is_idempotent_and_does_not_append_history():
    port = _QuestionKg("CLOSED")
    history = []

    out = _service(port, history).close_question("TreeA", "q", closed_by="node-a")

    assert out["state"] == "CLOSED"
    assert out["changed"] is False
    assert history == []


def test_open_question_created_at_is_a_latch_not_last_write_wins():
    port = _QuestionKg("OPEN")
    _service(port, []).open_question("TreeA", QuestionIn(qname="q", body="refresh"))

    cypher, _ = port.calls[0]
    assert "ON CREATE SET qn.status=$open_state, qn.created_at=$ts" in cypher
    assert "SET qn.body=$body, qn.status='OPEN', qn.created_at=$ts" not in cypher
