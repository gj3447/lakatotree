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


def internet_observations(rows: list[dict]) -> tuple[list[dict], dict]:
    """A2: ResearchEvent(internet) payload 행 → (eigentrust 입력 관측 리스트, {node_tag: source}).

    source = url|source_type (trust_view 와 동형). 노드당 *첫* 관측의 source 를 노드 source 로 바인딩
    (결정성: obs 쿼리가 created_at 오름차순). 노드가 source 를 들면 branch_credence 가 그 source 의
    글로벌 eigentrust 신뢰로 가중(per-node float override) — 없으면 per-node source_trust(prom A)로 폴백.

    프로덕션 read-model 의 *유일 정본*(D1 감사 2026-06-26): 전엔 read_models.load_tree_data(테스트만 호출)
    에 살아있고 프로덕션 경로(TreeKgRepository)에는 없어 A2 eigentrust 가 모든 HTTP 경로에서 inert 였다.
    """
    observations: list[dict] = []
    node_source: dict = {}
    for r in rows or []:
        try:
            p = json.loads(r.get("payload") or "{}")
        except (ValueError, TypeError):
            p = {}
        src = (p.get("url") or p.get("source_type") or "").strip()
        if not src:
            continue
        node = r.get("node") or ""
        observations.append(dict(
            source=src, source_type=p.get("source_type") or "", node=node,
            corroboration_score=float(p.get("corroboration_score") or 0.0)))
        node_source.setdefault(node, src)   # 노드당 첫 관측 source (결정적)
    return observations, node_source


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
            "t.coverage_backlog AS coverage_backlog, t.coverage_statement AS coverage_statement, "
            "t.ontology AS ontology",
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
               e.novel_confirmed AS novel_confirmed, e.source_trust AS source_trust,
               e.verdict_source AS verdict_source,
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
        # A2 (D1 감사 2026-06-26): 노드의 internet 관측 → eigentrust 입력 관측 + 노드별 source 바인딩.
        # compute_tree_metrics 가 이 observations 로 글로벌 출처신뢰(eigentrust)를 주입한다 — 프로덕션
        # 경로(이 repository)가 유일 정본이므로 여기서 방출해야 A2/D1 이 prod 에서 실제로 발동한다.
        obs_rows = self.kg(
            "MATCH (t:LakatosTree {name:$n})-[:HAS_NODE]->(e)-[:HAS_RESEARCH_EVENT]->"
            "(ev:ResearchEvent {realm:'internet'}) "
            "RETURN e.tag AS node, ev.payload AS payload ORDER BY e.tag, ev.created_at",
            n=name,
        )
        observations, node_source = internet_observations(obs_rows)
        normalized_nodes = [normalize_node_row(row) for row in nodes]
        for r in normalized_nodes:
            if r["tag"] in node_source:
                r["source"] = node_source[r["tag"]]
        return {
            "name": name,
            **normalize_tree_row(t[0]),
            "nodes": normalized_nodes,
            "frontier": [normalize_frontier_row(row) for row in frontier],
            "observations": observations,
        }
