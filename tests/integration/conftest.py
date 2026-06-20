"""D 통합티어 — 실 Neo4j(testcontainers) 대상. LAKATOS_IT 게이트로 hermetic 단위 suite 와 분리.

2026-06-16 결정(test_run_cycle_atomicity.py: KG=truth / PG=best-effort / 복구=멱등 재실행)을 *실 DB* 로
characterize 한다 — 원자성 *강요*가 아니라, kg_tx(execute_write, all-or-nothing)가 실제로 롤백하고
MERGE 재실행이 수렴함을 영수증으로 고정한다. prom C 의 atomic bind(B1-step1) / A4 / submit_test_result
가 의존하는 ROB-1 이 실 Neo4j 에서 성립함을 검증.

게이트: LAKATOS_IT 미설정 시 tier 전체 skip(로컬/CI 단위 = 빠름·docker 불필요) — 기존 CONSUMER_LOGS_E2E 패턴 미러.
clean clone 에 testcontainers 가 없어도 collection 이 깨지지 않게 fixture 안에서 lazy importorskip.
"""
import os

import pytest

LAKATOS_IT = os.getenv('LAKATOS_IT')


def pytest_configure(config):
    config.addinivalue_line(
        'markers', 'integration: 실 Neo4j+PG 통합 테스트(testcontainers, LAKATOS_IT 게이트)')


@pytest.fixture(scope='session')
def neo4j_driver():
    """세션 1회 실 Neo4j 컨테이너 + 드라이버. LAKATOS_IT 없으면 skip, testcontainers 없으면 importorskip."""
    if not LAKATOS_IT:
        pytest.skip('LAKATOS_IT 미설정 — 통합티어 skip (hermetic 단위 suite 보존)')
    neo4j_mod = pytest.importorskip('testcontainers.neo4j')
    from neo4j import GraphDatabase

    with neo4j_mod.Neo4jContainer('neo4j:5') as neo:
        uri = neo.get_connection_url()
        password = getattr(neo, 'password', None) or 'password'
        driver = GraphDatabase.driver(uri, auth=('neo4j', password))
        try:
            driver.verify_connectivity()
            yield driver
        finally:
            driver.close()
