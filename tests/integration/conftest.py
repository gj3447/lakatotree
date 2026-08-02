"""D 통합티어 — 실 Neo4j(testcontainers) 대상. LAKATOS_IT 게이트로 hermetic 단위 suite 와 분리.

2026-06-16 결정(test_run_cycle_atomicity.py: KG=truth / PG=best-effort / 복구=멱등 재실행)을 *실 DB* 로
characterize 한다 — 원자성 *강요*가 아니라, kg_tx(execute_write, all-or-nothing)가 실제로 롤백하고
MERGE 재실행이 수렴함을 영수증으로 고정한다. prom C 의 atomic bind(B1-step1) / A4 / submit_test_result
가 의존하는 ROB-1 이 실 Neo4j 에서 성립함을 검증.

게이트: LAKATOS_IT 미설정 시 tier 전체 skip(로컬 단위 = 빠름·docker 불필요). 게이트가
켜진 차단 CI에서는 의존성 누락이나 단 하나의 skip도 성공으로 강등하지 않고 실패시킨다.
"""
import os
from pathlib import Path

import pytest

LAKATOS_IT = os.getenv('LAKATOS_IT')
LAKATOS_PG_IMAGE = os.getenv('LAKATOS_PG_IMAGE', 'postgres:16-alpine')
_ROOT = Path(__file__).resolve().parents[2]


def pytest_configure(config):
    config.addinivalue_line(
        'markers', 'integration: 실 Neo4j+PG 통합 테스트(testcontainers, LAKATOS_IT 게이트)')


@pytest.fixture(scope='session')
def neo4j_connection_info():
    """세션 1회 실 Neo4j 컨테이너의 ephemeral pinned endpoint/credential."""
    if not LAKATOS_IT:
        pytest.skip('LAKATOS_IT 미설정 — 통합티어 skip (hermetic 단위 suite 보존)')
    from testcontainers import neo4j as neo4j_mod

    with neo4j_mod.Neo4jContainer('neo4j:5.26') as neo:
        yield {
            'uri': neo.get_connection_url(),
            'user': 'neo4j',
            'password': getattr(neo, 'password', None) or 'password',
        }


@pytest.fixture(scope='session')
def neo4j_driver(neo4j_connection_info):
    """세션 1회 실 Neo4j 드라이버."""
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(
        neo4j_connection_info['uri'],
        auth=(neo4j_connection_info['user'], neo4j_connection_info['password']),
    )
    try:
        driver.verify_connectivity()
        yield driver
    finally:
        driver.close()


@pytest.fixture(scope='session')
def pg_kw():
    """세션 1회 실 PostgreSQL 컨테이너 + schema.sql 적용 → psycopg2 연결 kwargs(B1 reconcile 영수증용)."""
    if not LAKATOS_IT:
        pytest.skip('LAKATOS_IT 미설정 — 통합티어 skip (hermetic 단위 suite 보존)')
    from testcontainers import postgres as pg_mod
    import psycopg2
    with pg_mod.PostgresContainer(LAKATOS_PG_IMAGE) as pg:
        kw = dict(host=pg.get_container_host_ip(), port=int(pg.get_exposed_port(5432)),
                  user=pg.username, password=pg.password, dbname=pg.dbname)
        conn = psycopg2.connect(**kw)
        try:
            with conn, conn.cursor() as cur:
                cur.execute((_ROOT / 'server' / 'schema.sql').read_text(encoding='utf-8'))
        finally:
            conn.close()
        yield kw


def pytest_sessionfinish(session, exitstatus):
    """A blocking integration run may never turn missing evidence into GREEN."""

    if not LAKATOS_IT:
        return
    reporter = session.config.pluginmanager.getplugin("terminalreporter")
    skipped = reporter.stats.get("skipped", []) if reporter is not None else []
    if skipped:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
