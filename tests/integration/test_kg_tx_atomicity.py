"""실 Neo4j 로 kg_tx(ROB-1) all-or-nothing + 복구=멱등 재실행 characterize (D 통합티어).

mock 으로는 검증 불가했던 것을 실 DB 로: AppContainer.kg_tx 가 execute_write(managed write tx)라
중간 실패 시 전체 롤백(부분 KG 쓰기 없음)이고, MERGE 기반 write 는 재실행이 수렴한다(2026-06-16
복구 모델). prom C 의 atomic observation bind / A4 belief 영속+auto-demote / submit_test_result 의
판결+PROV 단일 tx 가 모두 이 보장에 의존한다.
"""
import pytest

from server.container import AppContainer

pytestmark = pytest.mark.integration


class _DummyMongo:
    def close(self):
        pass


def _container(driver):
    # kg/kg_tx 만 실 Neo4j. PG(hist)=best-effort 라 이 테스트서 미사용 → pg_kw 비움(lazy, 미연결).
    return AppContainer(neo=driver, mongo=_DummyMongo(), pg_kw={})


def test_kg_tx_rolls_back_on_midtx_failure(neo4j_driver):
    """ROB-1: op1(노드 생성) 성공 + op2(잘못된 Cypher) 실패 → 전체 tx 롤백 → op1 미반영."""
    c = _container(neo4j_driver)
    with pytest.raises(Exception):
        c.kg_tx([
            ("CREATE (n:ITNode {tag:'rollback-probe'})", {}),
            ("THIS IS NOT VALID CYPHER", {}),
        ])
    rows = c.kg("MATCH (n:ITNode {tag:'rollback-probe'}) RETURN count(n) AS c")
    assert rows[0]['c'] == 0, 'mid-tx 실패 후 op1 이 남으면 롤백이 깨진 것 (ROB-1 위반)'


def test_kg_tx_commits_all_ops_on_success(neo4j_driver):
    """성공 경로: op-list 전부 한 tx 로 커밋(부분 아님)."""
    c = _container(neo4j_driver)
    c.kg_tx([
        ("CREATE (n:ITNode {tag:'commit-a'})", {}),
        ("CREATE (n:ITNode {tag:'commit-b'})", {}),
    ])
    rows = c.kg("MATCH (n:ITNode) WHERE n.tag IN ['commit-a','commit-b'] RETURN count(n) AS c")
    assert rows[0]['c'] == 2


def test_recovery_is_rerun_idempotent_merge(neo4j_driver):
    """복구=재실행: 같은 MERGE op 를 두 번(부분 실패 후 재실행 시뮬) 돌려도 노드 1개로 수렴(멱등)."""
    c = _container(neo4j_driver)
    op = ("MERGE (n:ITNode {tag:'rerun'}) SET n.v=$v", {'v': 1})
    c.kg_tx([op])
    c.kg_tx([op])
    rows = c.kg("MATCH (n:ITNode {tag:'rerun'}) RETURN count(n) AS c")
    assert rows[0]['c'] == 1, 'MERGE 재실행이 중복 생성하면 복구=재실행 모델이 깨진 것'
