"""A2 실DB 영수증: eigentrust 글로벌 신뢰가 canonical_credence 를 *실제로 움직인다* (Gate 1 해금).

mock 으로는 못 떨군 영수증: 실 Neo4j 에 트리+노드+다출처 internet 관측을 만들고, 프로덕션 read-model 의 실
경로(TreeKgRepository.load_tree_data → compute_tree_metrics)를 태운다. 정본경로 progressive 노드가 internet
출처(블로그+peer co-support)에 묶이면, 맵 주입 credence 가 맵-없음 baseline 과 *달라진다* — 글로벌 그래프
신뢰가 판결 신뢰도를 실제로 가중함(A2 가 prod 경로서 inert 아님)을 입증한다. 방향(↑/↓)은 prior-상대적이라
*크기 있는 이동*을 불변식으로 본다(저신뢰 출처가 항상 credence 를 낮추는 건 아니다 — 증거가 prior 아래로
끌었으면 가중 감소가 credence 를 prior 쪽으로 *복귀*시킨다).

★전제(서빙 형상): 정본경로 progress/CANONICAL 노드는 verdict_source와 실제 receipt-tip 포인터를 들어야 한다.
실 KG 서빙 로더는 두 키를 항상 싣고, tree_metrics의 prom-honesty가 원장 포인터 없는 진보를 inconclusive로
강등해 canonical_path를 비운다(키 생략한 옛 픽스처는 trusted라 통과=fake-green). seed가 두 판결의
VerdictReceipt 관계와 current_receipt_sha를 함께 만들어 이 drift를 닫는다. 항-drift 가드:
ooptdd_receipts/A2 (hermetic, R02+R10).
"""
import hashlib
from uuid import uuid4

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


class _BorrowedDriver:
    def __init__(self, driver):
        self._driver = driver

    def session(self, *args, **kwargs):
        return self._driver.session(*args, **kwargs)

    def close(self):
        pass


def _seed_tree(c, name):
    p1_rsha = hashlib.sha256(f"{name}:p1".encode()).hexdigest()
    top_rsha = hashlib.sha256(f"{name}:top".encode()).hexdigest()
    c.kg_tx([
        ("MERGE (t:LakatosTree {name:$n})", {"n": name}),
        ("""MATCH (t:LakatosTree {name:$n})
            MERGE (root:LakatosNode {name:$n+'/root'}) SET root.tag='root',
                  root.verdict='canonical_stage',
                  root.metric_value=1.0, root.metric_scope='s'
            MERGE (t)-[:HAS_NODE]->(root)
            MERGE (p1:LakatosNode {name:$n+'/p1'}) SET p1.tag='p1',
                  p1.verdict='progressive', p1.metric_value=0.5,
                  p1.metric_scope='s', p1.pred_baseline=1.0, p1.pred_noise_band=0.02, p1.pred_closes='q1',
                  p1.verdict_source='engine', p1.current_receipt_sha=$p1_rsha
            MERGE (t)-[:HAS_NODE]->(p1)
            MERGE (top:LakatosNode {name:$n+'/top'}) SET top.tag='top',
                  top.verdict='CANONICAL', top.metric_value=0.4,
                  top.metric_scope='s', top.verdict_source='engine',
                  top.current_receipt_sha=$top_rsha
            MERGE (t)-[:HAS_NODE]->(top)
            MERGE (p1r:VerdictReceipt {receipt_sha:$p1_rsha})
              SET p1r.tree=$n, p1r.tag='p1', p1r.verdict='progressive'
            MERGE (p1)-[:HAS_RECEIPT]->(p1r)
            MERGE (topr:VerdictReceipt {receipt_sha:$top_rsha})
              SET topr.tree=$n, topr.tag='top', topr.verdict='CANONICAL'
            MERGE (top)-[:HAS_RECEIPT]->(topr)
            MERGE (p1)-[:BRANCHED_FROM]->(root)
            MERGE (top)-[:BRANCHED_FROM]->(p1)""", {
                "n": name, "p1_rsha": p1_rsha, "top_rsha": top_rsha}),
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
    c = AppContainer(
        neo=_BorrowedDriver(neo4j_driver), mongo=_DummyMongo(), pg_kw={}
    )
    name = f"a2tree_credence_{uuid4().hex}"
    try:
        _seed_tree(c, name)

        td = load_tree_data(name, kg=c.kg)
        by = {r["tag"]: r for r in td["nodes"]}
        assert by["p1"]["source"] == "blog://x"
        assert any(o["source"] == "peer://a" for o in td["observations"])

        m_with = compute_tree_metrics(td)
        m_without = compute_tree_metrics({**td, "observations": []})
        tc = m_with["bayes"]["trust_coverage"]
        assert tc["map_supplied"] is True and tc["path_sources_matched"] >= 1
        cred_with = m_with["bayes"]["canonical_credence"]
        cred_without = m_without["bayes"]["canonical_credence"]
        assert cred_with is not None and cred_without is not None
        assert cred_with != cred_without and abs(cred_with - cred_without) > 0.05
    finally:
        try:
            c.kg(
                "MATCH (r:VerdictReceipt {tree:$name}) DETACH DELETE r",
                name=name,
            )
            c.kg(
                "MATCH (e:ResearchEvent) WHERE e.id STARTS WITH $prefix "
                "DETACH DELETE e",
                prefix=f"{name}/",
            )
            c.kg(
                "MATCH (t:LakatosTree {name:$name})-[:HAS_NODE]->(n) "
                "DETACH DELETE n",
                name=name,
            )
            c.kg(
                "MATCH (t:LakatosTree {name:$name}) DETACH DELETE t",
                name=name,
            )
        finally:
            c.close()
