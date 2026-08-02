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
from tests._live_ledger_test_seam import install_live_ledger_test_seam


def load_app():
    os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
    os.environ.setdefault("NEO4J_USER", "neo4j")
    os.environ.setdefault("NEO4J_PASSWORD", "test")
    return importlib.import_module("server.app")


@pytest.fixture(autouse=True)
def _live_ledger(monkeypatch):
    install_live_ledger_test_seam(monkeypatch, load_app())


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


def test_belief_reader_ignores_v2_inactive_legacy_pointer(monkeypatch):
    app = load_app()
    seen = []

    def fake(query, **_params):
        seen.append(query)
        return []

    monkeypatch.setattr(app, "kg", fake)
    assert app._load_belief_base("TreeA") == []
    assert "coalesce(hb.active, true)=true" in seen[0]


def test_belief_writer_reactivates_only_the_scoped_pointer(monkeypatch):
    app = load_app()
    ops_seen = []
    monkeypatch.setattr(app, "kg_tx", lambda ops: ops_seen.extend(ops) or [[] for _ in ops])
    monkeypatch.setattr(app, "kg", lambda *_a, **_k: [])
    monkeypatch.setattr(app, "hist", lambda *_a, **_k: None)
    result = SimpleNamespace(
        base=(Belief("b", "live", "protective_belt", 0.5, 0, 0, ()),),
        removed=(),
        added=("b",),
        programme_shift_candidate=False,
    )
    app._persist_revision("TreeA", "revision", result, None)
    query = ops_seen[0][0]
    assert "MERGE (t)-[hb:HAS_BELIEF]->(bel)" in query
    assert "SET hb.active=true" in query


def test_frontier_reducer_conforms_to_machine_spec():
    from lakatos.frontier_state import QuestionEvent, QuestionState, step

    source = Path(__file__).parents[1] / "docs/data/frontier_question_fsm.v1.json"
    machine = json.loads(source.read_text(encoding="utf-8"))["machines"][0]
    declared = {}
    for transition in machine["transitions"]:
        declared.setdefault((transition["from"], transition["event"]), []).append(transition)
    for state in QuestionState:
        for event in (QuestionEvent.OPEN, QuestionEvent.CLOSE):
            expected = declared.get((state.value, event.value), [])
            if not expected:
                with pytest.raises(ValueError):
                    step(state, event)
                continue
            assert len(expected) == 1
            expected = expected[0]
            actual = step(state, event)
            assert actual.state.value == expected["to"]
            assert actual.transition_id == expected["id"]
            assert [effect.value for effect in actual.effects] == expected["effects"]

    closing = step(QuestionState.OPEN, QuestionEvent.ADJUDICATED,
                   verdict="progressive", receipt_sha="a" * 64,
                   assurance_level=2)
    retained = step(QuestionState.OPEN, QuestionEvent.ADJUDICATED,
                    verdict="partial", receipt_sha="b" * 64,
                    assurance_level=2)
    duplicate = step(QuestionState.CLOSED, QuestionEvent.ADJUDICATED,
                     verdict="rejected", receipt_sha="c" * 64)
    assert closing.transition_id == "adjudication-close"
    assert retained.transition_id == "adjudication-retain-open"
    assert duplicate.transition_id == "duplicate-adjudication"
    adjudication_close = next(
        route for route in declared[("OPEN", "ADJUDICATED")]
        if route.get("guard") == "receipt_backed_conclusive"
    )
    assert adjudication_close["effect_bindings"]["RecordQuestionClosure"]["event_id"] \
        == "event.receipt_sha"
    with pytest.raises(ValueError, match="sha256"):
        step(QuestionState.OPEN, QuestionEvent.ADJUDICATED,
             verdict="progressive", receipt_sha="not-a-receipt")

    # Sprint A P0-2: REATTRIBUTE never reopens; receipt-backed append only on CLOSED.
    from lakatos.frontier_state import QuestionEffect
    appended = step(QuestionState.CLOSED, QuestionEvent.REATTRIBUTE,
                    verdict="progressive", receipt_sha="d" * 64,
                    assurance_level=2)
    retained = step(QuestionState.CLOSED, QuestionEvent.REATTRIBUTE,
                    verdict="partial", receipt_sha="e" * 64,
                    assurance_level=2)
    assert appended.transition_id == "reattribute-append"
    assert QuestionEffect.APPEND_CLOSER in appended.effects
    assert appended.state is QuestionState.CLOSED
    assert retained.transition_id == "reattribute-retain"
    assert retained.effects == ()
    with pytest.raises(ValueError, match="CLOSED"):
        step(QuestionState.OPEN, QuestionEvent.REATTRIBUTE,
             verdict="progressive", receipt_sha="f" * 64)
    with pytest.raises(ValueError, match="sha256"):
        step(QuestionState.CLOSED, QuestionEvent.REATTRIBUTE,
             verdict="progressive", receipt_sha="short")


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


class _ReattrKg:
    """Two-phase kg: (1) load closer+status (2) append write."""

    def __init__(self, *, q_status, closer_row, write_ok=True):
        self.q_status = q_status
        self.closer_row = closer_row
        self.write_ok = write_ok
        self.calls = []

    def __call__(self, cypher, **params):
        self.calls.append((cypher, params))
        if "OPTIONAL MATCH" in cypher and "HAS_NODE" in cypher:
            return [{
                "q_status": self.q_status,
                **self.closer_row,
            }]
        if "kind='reattribute'" in cypher or "reattribute" in cypher or "$closure_id" in cypher and "SET q.closed_by" in cypher:
            if not self.write_ok:
                return []
            prev = self.closer_row.get("prev_closed_by") or []
            by = params.get("by")
            closed_by = prev if by in prev else list(prev) + [by]
            return [{"name": params.get("qn"), "closed_by": closed_by}]
        return []


def test_reattribute_appends_receipted_closer_without_reopen():
    closer = dict(
        tag="node-ok",
        verdict="progressive",
        verdict_source="scripted",
        current_receipt_sha="a" * 64,
        measurement_grade="server_regenerated",
        replay_status="verified",
        measurement_lock_sha="1" * 64,
        receipt_bindings=1,
        lock_bindings=1,
        qualitative_self_report=False,
        node_state="CANONICAL_CANDIDATE",
        prev_closed_by=["admin-old"],
    )
    port = _ReattrKg(q_status="CLOSED", closer_row=closer)
    history = []
    out = _service(port, history).reattribute_question("TreeA", "q", closed_by="node-ok")
    assert out["ok"] is True
    assert out["state"] == "CLOSED"
    assert out["changed"] is True
    assert out["appended"] is True
    assert "node-ok" in (out.get("closed_by") or [])
    assert history and history[0][1] == "question_reattribute"
    # never sets status OPEN
    write_cypher = port.calls[-1][0]
    assert "OPEN" not in write_cypher or "open_state" in write_cypher
    assert "SET q.status=$open" not in write_cypher
    assert "valueType(q.closed_by) STARTS WITH 'LIST'" in write_cypher
    assert "ELSE current_closed_by + [$by]" in write_cypher
    assert "n.current_receipt_sha" in write_cypher
    assert port.calls[-1][1]["exp_receipt_sha"] == "a" * 64


def test_reattribute_rejects_force_of_row_non_counts_closer():
    closer = dict(
        tag="node-bad",
        verdict="progressive",
        verdict_source="scripted",
        current_receipt_sha="",  # present-empty → INCONCLUSIVE
        measurement_grade=None,
        replay_status=None,
        node_state="INCONCLUSIVE",
    )
    port = _ReattrKg(q_status="CLOSED", closer_row=closer)
    history = []
    with pytest.raises(HTTPException) as exc:
        _service(port, history).reattribute_question("TreeA", "q", closed_by="node-bad")
    assert exc.value.status_code == 409
    assert "COUNTS" in str(exc.value.detail)
    assert history == []


def test_reattribute_rejects_open_question():
    closer = dict(
        tag="node-ok",
        verdict="progressive",
        verdict_source="scripted",
        current_receipt_sha="b" * 64,
        measurement_grade="server_regenerated",
        replay_status="verified",
        measurement_lock_sha="2" * 64,
        receipt_bindings=1,
        lock_bindings=1,
        qualitative_self_report=False,
        node_state="CANONICAL_CANDIDATE",
    )
    port = _ReattrKg(q_status="OPEN", closer_row=closer)
    with pytest.raises(HTTPException) as exc:
        _service(port, []).reattribute_question("TreeA", "q", closed_by="node-ok")
    assert exc.value.status_code == 409


def test_open_question_created_at_is_a_latch_not_last_write_wins():
    port = _QuestionKg("OPEN")
    _service(port, []).open_question("TreeA", QuestionIn(qname="q", body="refresh"))

    cypher, _ = port.calls[0]
    assert "ON CREATE SET qn.status=$open_state, qn.created_at=$ts" in cypher
    assert "SET qn.body=$body, qn.status='OPEN', qn.created_at=$ts" not in cypher
