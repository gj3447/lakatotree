"""Read-model projections for Lakatos trees."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import HTTPException

from lakatos.programme.flip import layer_flips
from lakatos.quant.metrics import tree_metrics


KgQuery = Callable[..., list[dict]]


def load_tree_data(name: str, *, kg: KgQuery) -> dict:
    """Project a LakatosTree and its node/frontier rows from KG into API shape."""
    t = kg(
        "MATCH (t:LakatosTree {name:$n}) RETURN t.title AS title, t.hard_core AS hard_core, "
        "t.frontier_rule AS frontier_rule, t.doc AS doc, "
        "t.coverage_backlog AS coverage_backlog, t.coverage_statement AS coverage_statement",
        n=name,
    )
    if not t:
        raise HTTPException(404, f"나무 없음: {name}")
    nodes = kg(
        """MATCH (t:LakatosTree {name:$n})-[:HAS_NODE]->(e)
        OPTIONAL MATCH (e)-[bf:BRANCHED_FROM]->(p)
        WITH e, collect(DISTINCT {tag:p.tag, inferred:coalesce(bf.inferred,false),
             relation_kind:coalesce(bf.relation_kind,'knowledge_inheritance'),
             evidence_ref:coalesce(bf.evidence_ref,'')}) AS raw_parent_edges
        OPTIONAL MATCH (e)-[:RAISES_QUESTION]->(q)
        WITH e, [pe IN raw_parent_edges WHERE pe.tag IS NOT NULL] AS parent_edges,
             collect(DISTINCT q.name) AS questions
        RETURN e.tag AS tag, e.verdict AS verdict, e.note AS note, e.script AS script,
               e.result_path AS result_path, e.algorithm AS algorithm, e.comment AS comment,
               e.limitation AS limitation, e.open_question AS open_question,
               e.metric_name AS metric_name, e.metric_value AS metric_value,
               e.metric_scope AS metric_scope, e.novel_registered AS novel_registered,
               e.novel_confirmed AS novel_confirmed,
               e.pred_baseline AS pred_baseline, e.pred_noise_band AS pred_noise_band,
               e.pred_direction AS pred_direction,
               CASE WHEN size(parent_edges)>0 THEN parent_edges[0].tag ELSE null END AS parent,
               [pe IN parent_edges | pe.tag] AS parents, parent_edges AS parent_edges,
               questions AS questions
        ORDER BY tag""",
        n=name,
    )
    qs = kg(
        "MATCH (t:LakatosTree {name:$n})-[:HAS_FRONTIER]->(q) "
        "RETURN q.name AS name, q.status AS status, q.body AS body, "
        "q.closed_by AS closed_by, q.expected_gain AS expected_gain, "
        "q.cost AS cost, q.n_visits AS n_visits",
        n=name,
    )
    return dict(name=name, **t[0], nodes=nodes, frontier=qs)


def compute_tree_metrics(td: dict) -> dict:
    """Compute report metrics from a projected tree read model.

    `layer_flips` is merged here (not inside `tree_metrics`) on purpose: it lives in
    `lakatos.programme` and `tree_metrics` lives in `lakatos.quant` — folding it in there
    would be an upward `quant → programme` import that `.importlinter` forbids. The server
    read-model is outside the layered contract, so it is the clean seam to compose them.
    """
    m = tree_metrics(
        td["nodes"],
        td["frontier"],
        cfg={
            "coverage_backlog": td.get("coverage_backlog") or [],
            "coverage_statement": td.get("coverage_statement") or "",
        },
    )
    m["layer_flips"] = layer_flips(td["nodes"], td["frontier"])
    return m

