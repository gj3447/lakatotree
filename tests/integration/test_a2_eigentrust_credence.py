"""A2 실DB 영수증: eigentrust 글로벌 신뢰가 canonical_credence 를 *실제로 움직인다* (Gate 1 해금).

mock 으로는 못 떨군 영수증: 실 Neo4j 에 트리+노드+다출처 internet 관측을 만들고, 프로덕션 read-model 의 실
경로(TreeKgRepository.load_tree_data → compute_tree_metrics)를 태운다. 정본경로 progressive 노드가 internet
출처(블로그+peer co-support)에 묶이면, 맵 주입 credence 가 맵-없음 baseline 과 *달라진다* — 글로벌 그래프
신뢰가 판결 신뢰도를 실제로 가중함(A2 가 prod 경로서 inert 아님)을 입증한다. 방향(↑/↓)은 prior-상대적이라
*크기 있는 이동*을 불변식으로 본다(저신뢰 출처가 항상 credence 를 낮추는 건 아니다 — 증거가 prior 아래로
끌었으면 가중 감소가 credence 를 prior 쪽으로 *복귀*시킨다).

★전제(서빙 형상): 정본경로 progress/CANONICAL 노드는 verdict_source 영수증을 들어야 한다. 실 KG 서빙 로더는
verdict_source 키를 항상 싣고(미설정=None), tree_metrics 의 prom-honesty 가 영수증 없는 진보를 inconclusive 로
강등해 canonical_path 를 비운다(키 생략한 옛 픽스처는 trusted 라 통과=fake-green). seed 가 verdict_source 를
달아 이 drift 를 닫는다. 항-drift 가드: ooptdd_receipts/A2 (hermetic, R02+R10).
"""
import pytest

from server.container import AppContainer
from server.contexts.tree.repository import TreeKgRepository
from server.read_models import compute_tree_metrics

pytestmark = pytest.mark.integration


def load_tree_data(name, *, kg):
    """프로덕션 경로 그대로(D1 감사 2026-06-26: 죽은 read_models 사본 제거 후 단일 정본)."""
    return TreeKgRepository(kg).load_tree_data(name)


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
                  p1.metric_scope='s', p1.pred_baseline=1.0, p1.pred_noise_band=0.02, p1.pred_closes='q1',
                  p1.verdict_source='engine'
            MERGE (t)-[:HAS_NODE]->(p1)
            MERGE (top:LakatosNode {tag:'top'}) SET top.verdict='CANONICAL', top.metric_value=0.4,
                  top.metric_scope='s', top.verdict_source='engine'
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
    # 글로벌 eigentrust 신뢰가 판결 신뢰도를 *움직인다*(A2 prod-wired): 맵 주입 ≠ baseline, 크기 있는 이동.
    # 방향은 prior-상대적(여기선 blog 0.5 가 증거가중↓ → credence 가 prior 쪽 복귀 ↑). 핵심 = inert 아님.
    cred_with = m_with["bayes"]["canonical_credence"]
    cred_without = m_without["bayes"]["canonical_credence"]
    assert cred_with is not None and cred_without is not None
    assert cred_with != cred_without and abs(cred_with - cred_without) > 0.05
