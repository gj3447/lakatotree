"""Explicit node lifecycle FSM for LakatoTree.

The persisted KG has historically carried lifecycle facts as separate fields
(`pred_registered_at`, `verdict`, `verdict_source`, `judged_at`, ...).  This
module is the single place that folds those fields into a closed state and
defines legal state transitions.
# KG: span_lakatotree_node_state_fsm
"""

from __future__ import annotations

from enum import Enum

from lakatos.verdicts import REJECTING_VERDICTS as _REJECTING_VERDICTS
from lakatos.verdicts import force_of_row, is_progress_verdict


class NodeState(str, Enum):
    DRAFT = "DRAFT"
    PREDICTED = "PREDICTED"
    MEASURED = "MEASURED"
    JUDGED_SCRIPTED = "JUDGED_SCRIPTED"
    INCONCLUSIVE = "INCONCLUSIVE"
    CANONICAL_CANDIDATE = "CANONICAL_CANDIDATE"
    CANONICAL = "CANONICAL"
    FORMER_CANONICAL = "FORMER_CANONICAL"
    REJECTED = "REJECTED"
    DIFFERENT_PROGRAMME = "DIFFERENT_PROGRAMME"
    ADMINISTRATIVE = "ADMINISTRATIVE"


_DRAFT_VERDICTS = frozenset({"", "proof", None})


def derive_node_state(row: dict) -> NodeState:
    """Derive the explicit lifecycle state from a KG/read-model node row.

    This is intentionally conservative: force-less green verdicts become
    INCONCLUSIVE instead of candidates, and administrative labels remain outside
    the scripted judgement lifecycle.
    """
    verdict = row.get("verdict")
    source = row.get("verdict_source")
    force = force_of_row(row)

    if verdict == "CANONICAL":
        return NodeState.CANONICAL
    if verdict == "former_canonical":
        return NodeState.FORMER_CANONICAL
    if verdict == "different_programme":
        return NodeState.DIFFERENT_PROGRAMME
    if force == "INCONCLUSIVE":
        return NodeState.INCONCLUSIVE
    if verdict in _REJECTING_VERDICTS:
        return NodeState.REJECTED
    if force == "COUNTS":
        if is_progress_verdict(verdict) and row.get("novel_confirmed"):
            return NodeState.CANONICAL_CANDIDATE
        return NodeState.JUDGED_SCRIPTED
    if row.get("judged_at") or row.get("metric_value") is not None:
        return NodeState.MEASURED
    if row.get("pred_registered_at") or row.get("pred_metric") or row.get("pred_baseline") is not None:
        return NodeState.PREDICTED
    if verdict not in _DRAFT_VERDICTS or source:
        return NodeState.ADMINISTRATIVE
    return NodeState.DRAFT


ALLOWED_TRANSITIONS: dict[NodeState, frozenset[NodeState]] = {
    NodeState.DRAFT: frozenset({
        NodeState.DRAFT,
        NodeState.PREDICTED,
        NodeState.CANONICAL,
        NodeState.ADMINISTRATIVE,
    }),
    NodeState.PREDICTED: frozenset({
        NodeState.PREDICTED,
        NodeState.MEASURED,
        NodeState.JUDGED_SCRIPTED,
        NodeState.INCONCLUSIVE,
        NodeState.CANONICAL_CANDIDATE,
        NodeState.REJECTED,
        NodeState.DIFFERENT_PROGRAMME,
    }),
    NodeState.MEASURED: frozenset({
        NodeState.MEASURED,
        NodeState.JUDGED_SCRIPTED,
        NodeState.INCONCLUSIVE,
        NodeState.CANONICAL_CANDIDATE,
        NodeState.REJECTED,
        NodeState.DIFFERENT_PROGRAMME,
    }),
    NodeState.JUDGED_SCRIPTED: frozenset({
        NodeState.JUDGED_SCRIPTED,
        NodeState.CANONICAL_CANDIDATE,
        NodeState.CANONICAL,
        NodeState.FORMER_CANONICAL,
        NodeState.ADMINISTRATIVE,
    }),
    NodeState.INCONCLUSIVE: frozenset({
        NodeState.INCONCLUSIVE,
        NodeState.PREDICTED,
        NodeState.JUDGED_SCRIPTED,
        NodeState.CANONICAL_CANDIDATE,
        NodeState.CANONICAL,
        NodeState.REJECTED,
        NodeState.DIFFERENT_PROGRAMME,
    }),
    NodeState.CANONICAL_CANDIDATE: frozenset({
        NodeState.CANONICAL_CANDIDATE,
        NodeState.CANONICAL,
        NodeState.FORMER_CANONICAL,
        NodeState.REJECTED,
        NodeState.DIFFERENT_PROGRAMME,
        NodeState.ADMINISTRATIVE,
    }),
    NodeState.CANONICAL: frozenset({NodeState.CANONICAL, NodeState.FORMER_CANONICAL}),
    NodeState.FORMER_CANONICAL: frozenset({NodeState.FORMER_CANONICAL, NodeState.ADMINISTRATIVE}),
    NodeState.REJECTED: frozenset({NodeState.REJECTED, NodeState.ADMINISTRATIVE}),
    NodeState.DIFFERENT_PROGRAMME: frozenset({NodeState.DIFFERENT_PROGRAMME, NodeState.ADMINISTRATIVE}),
    NodeState.ADMINISTRATIVE: frozenset({NodeState.ADMINISTRATIVE, NodeState.PREDICTED}),
}


def transition_allowed(before: NodeState, after: NodeState) -> bool:
    return after in ALLOWED_TRANSITIONS[before]


def assert_transition_allowed(before: NodeState, after: NodeState) -> None:
    if not transition_allowed(before, after):
        raise ValueError(f"illegal node state transition: {before.value} -> {after.value}")


def derive_state_value(row: dict) -> str:
    """String helper for KG SET clauses and JSON read models."""
    return derive_node_state(row).value
