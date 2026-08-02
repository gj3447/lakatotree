"""Tree isolation and frontier FSM executable receipt.

The adapter calls real LakatoTree functions. ``LKT_STATE_ISOLATION_INJECT=allow-reopen``
mutates the real transition table for one process; the same locked requirement must turn RED,
then the table is restored in ``finally``.
"""
from __future__ import annotations

import os
from contextlib import nullcontext
from pathlib import Path
import sys
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")

from fastapi import HTTPException  # noqa: E402

from lakatos.programme.agm import Belief  # noqa: E402
from server.contexts.tree.schemas import QuestionIn  # noqa: E402
from server.contexts.tree.service import TreeService  # noqa: E402
import server.app as app_mod  # noqa: E402


def _event(cid, name, **attrs):
    return {
        "cid": cid,
        "correlation_id": cid,
        "cycle_id": cid,
        "service": "lakatos.state_isolation_fsm",
        "event": name,
        **attrs,
    }


class _QuestionPort:
    def __init__(self, before_state):
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


def verify(backend, cid):
    from lakatos import frontier_state as frontier

    saved = dict(frontier._TRANSITIONS)
    try:
        if os.getenv("LKT_STATE_ISOLATION_INJECT") == "allow-reopen":
            frontier._TRANSITIONS[(frontier.QuestionState.CLOSED, frontier.QuestionEvent.OPEN)] = (
                frontier.QuestionTransition(
                    state=frontier.QuestionState.OPEN,
                    effects=(frontier.QuestionEffect.UPDATE_METADATA,),
                    transition_id="injected-reopen",
                )
            )

        captured = []
        old_kg, old_tx = app_mod.kg, app_mod.kg_tx
        old_ready = app_mod._require_critique_history_ready
        old_fenced = app_mod._container.writer_fenced_kg_tx
        old_authority_scope = app_mod._container._writer_authority_scope
        try:
            app_mod.kg = lambda *args, **kwargs: []
            app_mod.kg_tx = lambda ops: captured.extend(ops) or [[] for _ in ops]
            app_mod._require_critique_history_ready = lambda: None
            app_mod._container.writer_fenced_kg_tx = lambda ops: app_mod.kg_tx(ops)
            # This receipt verifies the FSM mutation, not production storage
            # admission.  Explicitly replace only the bounded authority seam;
            # the live composition root remains fail-closed.
            app_mod._container._writer_authority_scope = lambda: nullcontext()
            result = SimpleNamespace(
                base=(Belief("live", "live", "protective_belt", 0.5, 0, 0, ()),),
                removed=("old",),
                added=("live",),
                programme_shift_candidate=False,
            )
            old_hist = app_mod.hist
            app_mod.hist = lambda *args, **kwargs: None
            try:
                app_mod._persist_revision("TreeA", "contraction", result, None)
            finally:
                app_mod.hist = old_hist
        finally:
            app_mod.kg, app_mod.kg_tx = old_kg, old_tx
            app_mod._require_critique_history_ready = old_ready
            app_mod._container.writer_fenced_kg_tx = old_fenced
            app_mod._container._writer_authority_scope = old_authority_scope
        cyphers = "\n".join(query for query, _ in captured)
        assert "MERGE (bel:Belief {tree:$tree, belief_id: b.belief_id})" in cyphers
        assert "bel.tree=$tree AND bel.belief_id IN $removed" in cyphers
        backend.ship([_event(cid, "tree_scoped_belief_identity", tree="TreeA")])

        reopen_port = _QuestionPort("CLOSED")
        reopen_history = []
        service = TreeService(
            kg=reopen_port,
            kg_tx=None,
            hist=lambda *args: reopen_history.append(args),
            pg=None,
        )
        rejected = None
        try:
            service.open_question("TreeA", QuestionIn(qname="q", body="rewrite"))
        except HTTPException as exc:
            rejected = exc.status_code
        assert rejected == 409, f"CLOSED question reopened: status={rejected}"
        assert reopen_history == []
        backend.ship([_event(cid, "frontier_reopen_rejected", status=rejected)])

        close_port = _QuestionPort("CLOSED")
        close_history = []
        close_result = TreeService(
            kg=close_port,
            kg_tx=None,
            hist=lambda *args: close_history.append(args),
            pg=None,
        ).close_question("TreeA", "q", closed_by="node-a")
        assert close_result["state"] == "CLOSED" and close_result["changed"] is False
        assert close_history == []
        backend.ship([_event(cid, "frontier_close_idempotent", changed=False)])
    finally:
        frontier._TRANSITIONS.clear()
        frontier._TRANSITIONS.update(saved)
