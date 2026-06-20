"""Read-model projections for Lakatos trees."""

from __future__ import annotations

import json
from collections.abc import Callable

from fastapi import HTTPException

from lakatos.programme.flip import layer_flips
from lakatos.quant.metrics import tree_metrics


KgQuery = Callable[..., list[dict]]


def _internet_observations(rows: list[dict]) -> tuple[list[dict], dict]:
    """A2: ResearchEvent(internet) payload 행 → (eigentrust 입력 관측 리스트, {node_tag: source}).

    source = url|source_type (trust_view 와 동형). 노드당 *첫* 관측의 source 를 노드 source 로 바인딩
    (결정성: obs 쿼리가 created_at 오름차순). 노드가 source 를 들면 branch_credence 가 그 source 의
    글로벌 eigentrust 신뢰로 가중(per-node float override) — 없으면 per-node source_trust(prom A)로 폴백.
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
               e.novel_confirmed AS novel_confirmed, e.source_trust AS source_trust,
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
    # A2: 노드의 internet 관측 → eigentrust 입력 관측 + 노드별 source 바인딩(credence 글로벌 신뢰 가중).
    obs_rows = kg(
        "MATCH (t:LakatosTree {name:$n})-[:HAS_NODE]->(e)-[:HAS_RESEARCH_EVENT]->"
        "(ev:ResearchEvent {realm:'internet'}) "
        "RETURN e.tag AS node, ev.payload AS payload ORDER BY e.tag, ev.created_at",
        n=name,
    )
    observations, node_source = _internet_observations(obs_rows)
    for r in nodes:
        if r["tag"] in node_source:
            r["source"] = node_source[r["tag"]]
    return dict(name=name, **t[0], nodes=nodes, frontier=qs, observations=observations)


def compute_tree_metrics(td: dict) -> dict:
    """Compute report metrics from a projected tree read model.

    `layer_flips` is merged here (not inside `tree_metrics`) on purpose: it lives in
    `lakatos.programme` and `tree_metrics` lives in `lakatos.quant` — folding it in there
    would be an upward `quant → programme` import that `.importlinter` forbids. The server
    read-model is outside the layered contract, so it is the clean seam to compose them.
    """
    cfg = {
        "coverage_backlog": td.get("coverage_backlog") or [],
        "coverage_statement": td.get("coverage_statement") or "",
    }
    # A2: 관측이 있으면 eigentrust 글로벌 출처신뢰 맵을 구성해 credence 가중에 주입(없으면 레거시).
    observations = td.get("observations")
    if observations:
        from lakatos.trust import global_source_trust
        gst = global_source_trust(observations)
        if gst["trust"]:
            cfg["source_trust_map"] = gst["trust"]
            cfg["trust_coverage_mode"] = gst["coverage"]["mode"]
    m = tree_metrics(td["nodes"], td["frontier"], cfg=cfg)
    m["layer_flips"] = layer_flips(td["nodes"], td["frontier"])
    return m

