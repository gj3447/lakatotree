"""KG repository and typed projections for Lakatos trees.

# KG: seed-lkt-engine-kg-read-normalizer-20260616
"""

from __future__ import annotations

from collections.abc import Callable
import json

from fastapi import HTTPException


KgQuery = Callable[..., list[dict]]


def normalize_text(value) -> str:
    """Collapse heterogeneous KG scalar/list values into searchable display text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple, set)):
        return "\n".join(part for item in value if (part := normalize_text(item)))
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def normalize_text_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, (list, tuple, set)):
        return [text for item in value if (text := normalize_text(item))]
    return [normalize_text(value)]


def normalize_tree_row(row: dict) -> dict:
    out = dict(row)
    for key in ("title", "hard_core", "frontier_rule", "doc", "coverage_statement"):
        out[key] = normalize_text(out.get(key))
    out["coverage_backlog"] = normalize_text_list(out.get("coverage_backlog"))
    return out


def normalize_node_row(row: dict) -> dict:
    out = dict(row)
    out["tag"] = normalize_text(out.get("tag"))
    out["verdict"] = normalize_text(out.get("verdict")) or "proof"
    out["parent"] = normalize_text(out.get("parent")) or None
    out["parents"] = normalize_text_list(out.get("parents"))
    out["questions"] = normalize_text_list(out.get("questions"))
    out["parent_edges"] = [
        {
            "tag": normalize_text(edge.get("tag")) if isinstance(edge, dict) else normalize_text(edge),
            "inferred": bool(edge.get("inferred")) if isinstance(edge, dict) else False,
            "relation_kind": normalize_text(edge.get("relation_kind")) if isinstance(edge, dict) else "",
            "evidence_ref": normalize_text(edge.get("evidence_ref")) if isinstance(edge, dict) else "",
        }
        for edge in (out.get("parent_edges") or [])
        if (isinstance(edge, dict) and edge.get("tag")) or (not isinstance(edge, dict) and edge)
    ]
    return out


def normalize_frontier_row(row: dict) -> dict:
    out = dict(row)
    out["name"] = normalize_text(out.get("name"))
    out["status"] = normalize_text(out.get("status")) or "OPEN"
    out["body"] = normalize_text(out.get("body"))
    out["closed_by"] = normalize_text_list(out.get("closed_by"))
    return out


class TreeKgRepository:
    """Tree-specific KG read boundary.

    The rest of the tree context consumes normalized Python dictionaries instead
    of raw Neo4j property values. That keeps list/scalar drift in KG from leaking
    into string-search and metric code.
    """

    # KG: rf-lkt-engine-typed-kg-read-normalization-20260616

    def __init__(self, kg: KgQuery):
        self.kg = kg

    def list_trees(self) -> list[dict]:
        return self.kg("MATCH (t:LakatosTree) RETURN t.name AS name, t.title AS title")

    def load_tree_data(self, name: str) -> dict:
        t = self.kg(
            "MATCH (t:LakatosTree {name:$n}) RETURN t.title AS title, t.hard_core AS hard_core, "
            "t.frontier_rule AS frontier_rule, t.doc AS doc, "
            "t.coverage_backlog AS coverage_backlog, t.coverage_statement AS coverage_statement",
            n=name,
        )
        if not t:
            raise HTTPException(404, f"나무 없음: {name}")
        nodes = self.kg(
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
               e.pred_direction AS pred_direction, e.pred_closes AS pred_closes,
               CASE WHEN size(parent_edges)>0 THEN parent_edges[0].tag ELSE null END AS parent,
               [pe IN parent_edges | pe.tag] AS parents, parent_edges AS parent_edges,
               questions AS questions
        ORDER BY tag""",
            n=name,
        )
        frontier = self.kg(
            "MATCH (t:LakatosTree {name:$n})-[:HAS_FRONTIER]->(q) "
            "RETURN q.name AS name, q.status AS status, q.body AS body, "
            "q.closed_by AS closed_by, q.expected_gain AS expected_gain, "
            "q.cost AS cost, q.n_visits AS n_visits",
            n=name,
        )
        return {
            "name": name,
            **normalize_tree_row(t[0]),
            "nodes": [normalize_node_row(row) for row in nodes],
            "frontier": [normalize_frontier_row(row) for row in frontier],
        }
