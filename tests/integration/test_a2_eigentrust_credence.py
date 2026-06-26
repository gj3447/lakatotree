"""A2 실DB 영수증: eigentrust 글로벌 신뢰가 canonical_credence 를 *실제로 움직인다* (Gate 1 해금).

mock 으로는 못 떨군 영수증: 실 Neo4j 에 트리+노드+다출처 internet 관측을 만들고, read_models 의 실
경로(load_tree_data → compute_tree_metrics)를 태운다. 정본경로 progressive 노드가 *저신뢰* 출처
(블로그, peer_reviewed 와 co-support 되어 eigentrust 정규화로 낮아짐)에 묶이면, 맵 주입 credence 가
맵-없음(per-node 기본 1.0) baseline 보다 *낮다* — 글로벌 그래프 신뢰가 판결 신뢰도를 가중함을 입증.
"""
import pytest

from server.container import AppContainer
from server.read_models import compute_tree_metrics, load_tree_data

pytestmark = pytest.mark.integration


class _DummyMongo:
    def close(self):
        pass


def _seed_tree(c, name):
    c.kg_tx([
        ("MERGE (t:LakatosTree {name:$n})", {"n": name}),
        ("""MATCH (t:LakatosTree {name:$n})
            MERGE (root:LakatosNode {tag:'root'}) SET root.verdict='canonical_stage',
                  root.metric_value=1.0, root.metric_scope='s'
            MERGE (t)-[:HAS_NODE]->(root)
            MERGE (p1:LakatosNode {tag:'p1'}) SET p1.verdict='progressive', p1.metric_value=0.5,
                  p1.metric_scope='s', p1.pred_baseline=1.0, p1.pred_noise_band=0.02, p1.pred_closes='q1'
            MERGE (t)-[:HAS_NODE]->(p1)
            MERGE (top:LakatosNode {tag:'top'}) SET top.verdict='CANONICAL', top.metric_value=0.4,
                  top.metric_scope='s'
            MERGE (t)-[:HAS_NODE]->(top)
            MERGE (p1)-[:BRANCHED_FROM]->(root)
            MERGE (top)-[:BRANCHED_FROM]->(p1)""", {"n": name}),
        # 정본경로 노드 p1 을 받치는 두 internet 관측: 블로그(먼저=노드 source) + peer_reviewed(seed).
        # co-support(같은 노드 2관측) → eigentrust 가 블로그 신뢰를 1.0 미만으로 정규화.
        ("""MATCH (t:LakatosTree {name:$n})-[:HAS_NODE]->(p1 {tag:'p1'})
            MERGE (e1:ResearchEvent {id:$n+'/p1/obs/blog'})
              SET e1.realm='internet', e1.created_at='2026-06-20T01:00:00',
                  e1.payload='{"url":"blog://x","source_type":"blog","corroboration_score":0.5}'
            MERGE (p1)-[:HAS_RESEARCH_EVENT]->(e1)
            MERGE (e2:ResearchEvent {id:$n+'/p1/obs/peer'})
              SET e2.realm='internet', e2.created_at='2026-06-20T02:00:00',
                  e2.payload='{"url":"peer://a","source_type":"peer_reviewed","corroboration_score":0.9}'
            MERGE (p1)-[:HAS_RESEARCH_EVENT]->(e2)""", {"n": name}),
    ])


def test_eigentrust_map_moves_canonical_credence_on_real_db(neo4j_driver):
    c = AppContainer(neo=neo4j_driver, mongo=_DummyMongo(), pg_kw={})
    name = "a2tree_credence"
    _seed_tree(c, name)

    td = load_tree_data(name, kg=c.kg)
    by = {r["tag"]: r for r in td["nodes"]}
    assert by["p1"]["source"] == "blog://x"          # 실DB 관측에서 노드 source 바인딩(첫=블로그)
    assert any(o["source"] == "peer://a" for o in td["observations"])   # 관측 그래프 방출

    m_with = compute_tree_metrics(td)
    m_without = compute_tree_metrics({**td, "observations": []})         # 맵 없음 baseline
    tc = m_with["bayes"]["trust_coverage"]
    assert tc["map_supplied"] is True and tc["path_sources_matched"] >= 1
    # 글로벌 신뢰가 판결 신뢰도를 *움직인다*: 저신뢰(블로그<1.0) 출처 → 맵 credence < baseline(1.0)
    assert m_with["bayes"]["canonical_credence"] < m_without["bayes"]["canonical_credence"]
