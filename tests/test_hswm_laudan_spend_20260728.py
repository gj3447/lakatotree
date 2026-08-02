"""Dense knowledge structure must not masquerade as spent scientific budget.

Locked before the implementation change on 2026-07-28.  Laudan rule 2 is
about exhausted attempts with zero prediction hits, not graph depth.  Canon,
formalisation, evidence, and interface nodes therefore cannot consume that
budget until the server has actually adjudicated them.
"""

from lakatos.quant.metrics import tree_metrics
from lakatos.quant.metrics import branch_inputs
from server.contexts.tree.mutations import TreeMutationService
from server.contexts.tree.schemas import NodeIn


def _managed_state(*, adjudicated: bool, source: str | None = None) -> dict:
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
        **_managed_state(adjudicated=False),
    )]
    parent = "root"
    for index in range(5):
        tag = f"layer-{index}"
        row = dict(
            tag=tag,
            verdict=("partial" if adjudicated else "proof"),
            parent=parent,
            parents=[parent],
        )
        row.update(_managed_state(
            adjudicated=adjudicated,
            source=("scripted" if adjudicated or label_only else None),
        ))
        if label_only:
            row["current_receipt_sha"] = "b" * 64
        nodes.append(row)
        parent = tag
    leaf = dict(
        tag="open-experiment",
        verdict="progressive_conditional",
        parent=parent,
        parents=[parent],
    )
    leaf.update(_managed_state(
        adjudicated=adjudicated,
        source=("engine" if adjudicated or label_only else None),
    ))
    if label_only:
        leaf["current_receipt_sha"] = "c" * 64
    nodes.append(leaf)
    return nodes


def _abandonment(nodes: list[dict]) -> list[dict]:
    return tree_metrics(nodes, [])["laudan"]["abandon_candidates"]


def test_dense_unadjudicated_structure_does_not_spend_laudan_budget():
    assert _abandonment(_branch(adjudicated=False)) == []


def test_forceful_label_and_prediction_receipt_without_outcome_do_not_spend():
    assert _abandonment(_branch(adjudicated=False, label_only=True)) == []


def test_receipted_attempts_still_trigger_zero_hit_budget_rule():
    nodes = _branch(adjudicated=True)
    candidates = _abandonment(nodes)
    candidate = next(row for row in candidates if row["leaf"] == "open-experiment")
    assert branch_inputs(nodes, [], leaf="open-experiment")["nodes_spent"] == 6
    assert "예산" in candidate["reason"]


def test_add_node_abandon_signal_uses_adjudicated_spend_not_graph_depth():
    child = NodeIn(tag="next-experiment", parent="open-experiment")
    structural = _branch(adjudicated=False)
    attempted = _branch(adjudicated=True)

    assert TreeMutationService._branch_abandon_signal(
        child, {"nodes": structural, "frontier": []}
    ) is None
    signal = TreeMutationService._branch_abandon_signal(
        child, {"nodes": attempted, "frontier": []}
    )
    assert signal is not None
    assert signal["nodes_spent"] == 6
    assert "예산" in signal["reason"]


def test_structural_nodes_do_not_break_consecutive_attempt_chronology():
    nodes = [dict(
        tag="root", verdict="CANONICAL", parent=None, parents=[],
        **_managed_state(adjudicated=False),
    )]
    parent = "root"
    for index in range(3):
        attempt = f"attempt-{index}"
        nodes.append(dict(
            tag=attempt,
            verdict="rejected",
            parent=parent,
            parents=[parent],
            **_managed_state(adjudicated=True, source="scripted"),
        ))
        parent = attempt
        if index < 2:
            structure = f"structure-{index}"
            nodes.append(dict(
                tag=structure,
                verdict="proof",
                parent=parent,
                parents=[parent],
                **_managed_state(adjudicated=False),
            ))
            parent = structure

    candidates = _abandonment(nodes)
    candidate = next(row for row in candidates if row["leaf"] == "attempt-2")
    assert branch_inputs(nodes, [], leaf="attempt-2")["nodes_spent"] == 3
    assert "연속 비진보 3" in candidate["reason"]
