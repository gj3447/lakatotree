"""db_boundary (prom-honesty): 서버 write-path Cypher 를 *실 Neo4j* 로 실행 — 부분문자열 단언 넘어.

감사 발견: 모든 KG 가 monkeypatch 이고 서버 테스트는 Cypher *부분문자열*만 단언 → MERGE 키/WHERE 가
틀려도 green(semantically 무효를 못 잡음). 이 통합 테스트는 실제 TreeKgWriter Cypher 를 testcontainer
Neo4j 에 돌려 *그래프 실재*(노드/verdict/metric)를 검증하고, prom-honesty/1 게이트가 실 DB 경계에서도
작동함을 확인한다.

gated(LAKATOS_IT): CI(hermetic)에선 skip — dogfood harness 는 db_boundary 를 pending(gated)로 정직 표기.
LAKATOS_IT=1 + testcontainers 에서만 실행돼 progressive 채점 가능(영수증 없는 green 금지).
"""
import pytest

from server.container import AppContainer
from server.contexts.tree.schemas import NodeIn
from server.contexts.tree.writer import TreeKgWriter

pytestmark = pytest.mark.integration


class _DummyMongo:
    def close(self):
        pass


def _container(driver):
    return AppContainer(neo=driver, mongo=_DummyMongo(), pg_kw={})


def test_kg_write_path_real_driver(neo4j_driver):
    """TreeKgWriter.add_node 의 실제 Cypher 가 실 Neo4j 에서 semantically 유효 — 노드/verdict/metric 실재.
    (mock+부분문자열로는 MERGE 키/SET 절 오류를 못 잡던 것을 실 DB 그래프로 확증.)"""
    c = _container(neo4j_driver)
    c.kg_tx([("MERGE (t:LakatosTree {name:$n})", {"n": "IT_DBBoundary"})])
    writer = TreeKgWriter(c.kg_tx)

    writer.add_node("IT_DBBoundary",
                    NodeIn(tag="it_child", verdict="proof", metric_name="p95",
                           metric_value=0.42, metric_scope="lot"), [])

    rows = c.kg("""MATCH (t:LakatosTree {name:'IT_DBBoundary'})-[:HAS_NODE]->(e {tag:'it_child'})
                   RETURN e.verdict AS v, e.metric_value AS mv, e.metric_name AS mn""")
    assert rows, "실 Neo4j 에 노드 미생성 — write-path Cypher 가 semantically 무효(부분문자열론 못 잡던 것)"
    assert rows[0]["v"] == "proof" and rows[0]["mv"] == 0.42 and rows[0]["mn"] == "p95"


def test_scripted_verdict_rejected_before_real_write(neo4j_driver):
    """prom-honesty/1 이 실 DB 경계에서도 유효: writer 가 scripted verdict 를 by-construction 거부하고
    실 Neo4j 에 단 한 줄도 쓰지 않는다(게이트가 실경로에서 작동 — self-report 차단)."""
    c = _container(neo4j_driver)
    c.kg_tx([("MERGE (t:LakatosTree {name:$n})", {"n": "IT_Gate"})])
    writer = TreeKgWriter(c.kg_tx)

    with pytest.raises(ValueError, match="prom-honesty/1"):
        writer.add_node("IT_Gate", NodeIn(tag="forge", verdict="progressive"), [])

    rows = c.kg("MATCH (:LakatosTree {name:'IT_Gate'})-[:HAS_NODE]->(e {tag:'forge'}) RETURN count(e) AS c")
    assert rows[0]["c"] == 0, "scripted verdict 가 실 DB 에 들어감 — by-construction 게이트 우회"
