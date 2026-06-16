"""Application composition root — owns external resource lifecycle.

Neo4j 드라이버 / Mongo DB / PostgreSQL 풀을 *하나의 응집된 주입 가능한 단위*로
생성·운용·종료한다. 기존엔 server.app 모듈 전역(`NEO`/`MONGO`/`_PG_POOL` +
`global _PG_POOL` 변이)으로 흩어져 있어 자원층을 단독으로 테스트할 수 없었다.
어댑터는 주입(기본값=실제 lazy 어댑터) — fake 를 넣어 자원층만 단위검증 가능.

server.app 은 이 컨테이너에 얇게 위임만 한다(모듈 API 는 하위호환 유지).
# KG: span_lakatotree_server_architecture
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from contextlib import contextmanager
from typing import Any

import psycopg2.pool
from psycopg2 import OperationalError as PgOperationalError


class AppContainer:
    """외부 자원(Neo4j/Mongo/PG)의 생성·접근·종료를 소유하는 합성 루트.

    - kg / kg_tx : Neo4j 읽기 / 단일 managed-write 트랜잭션(all-or-nothing, ROB-1)
    - pg         : PG 풀에서 빌려쓰고 commit/rollback 후 반납하는 컨텍스트매니저
    - hist       : append-only 이력 적재(best-effort — PG 다운은 삼키고 경고, KG=truth)
    - close      : 종료 시 best-effort 정리(하나 실패해도 나머지 닫고 실패목록 반환)
    """

    def __init__(
        self,
        *,
        neo: Any,
        mongo: Any,
        pg_kw: dict,
        logger: logging.Logger | None = None,
        pool_min: int = 1,
        pool_max: int = 16,
    ):
        self._neo = neo
        self._mongo = mongo
        self._pg_kw = pg_kw
        self._logger = logger or logging.getLogger("lakatotree.server")
        self._pool_min = pool_min
        self._pool_max = pool_max
        self._pg_pool = None   # lazy — import/생성 시 미연결(테스트/오프라인 안전)

    # ── Neo4j ──────────────────────────────────────────────────────────
    def kg(self, q: str, **kw: Any) -> list[dict]:
        with self._neo.session() as s:
            return s.run(q, **kw).data()

    def kg_tx(self, ops: Iterable[tuple[str, dict]]) -> list:
        """여러 Cypher 를 단일 managed write 트랜잭션으로 (KG-내부 부분쓰기 분기 차단, ROB-1)."""
        def _unit(tx):
            return [tx.run(cypher, **params).data() for cypher, params in ops]
        with self._neo.session() as s:
            return s.execute_write(_unit)

    # ── PostgreSQL ─────────────────────────────────────────────────────
    def pg_pool(self):
        if self._pg_pool is None:
            self._pg_pool = psycopg2.pool.ThreadedConnectionPool(
                self._pool_min, self._pool_max, **self._pg_kw)
        return self._pg_pool

    @contextmanager
    def pg(self):
        """풀에서 빌려 쓰고 반납 — 성공 시 commit, 예외 시 rollback, 항상 putconn."""
        conn = self.pg_pool().getconn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self.pg_pool().putconn(conn)

    def hist(self, tree: str, op: str, node_tag: str | None = None, payload: dict | None = None) -> None:
        # ROB-1: 이력(PG)=best-effort audit, KG=truth. KG 커밋 후 PG 다운이 mutation 을 503 으로
        # 되돌리면 그래프-이력 분기가 더 나빠지므로, PG 연결오류는 삼키고 경고만(이력만 유실).
        try:
            with self.pg() as c, c.cursor() as cur:
                cur.execute(
                    "INSERT INTO history(tree, op, node_tag, payload) VALUES (%s,%s,%s,%s)",
                    (tree, op, node_tag, json.dumps(payload or {}, ensure_ascii=False)))
        except PgOperationalError as e:
            self._logger.error("hist PG 적재 실패(best-effort, KG 는 정상): %s", type(e).__name__)

    # ── lifecycle ──────────────────────────────────────────────────────
    def close(self) -> list:
        """OPS-LIFECYCLE-1: 종료 시 각 자원을 best-effort 로 닫고 실패목록을 반환(감사)."""
        errs: list[str] = []
        for name, closer in (
            ("neo4j", lambda: self._neo.close()),
            ("mongo", lambda: self._mongo.close() if hasattr(self._mongo, "close") else self._mongo.client.close()),
            ("pg_pool", lambda: self._pg_pool.closeall() if self._pg_pool is not None else None),
        ):
            try:
                closer()
            except Exception as e:   # noqa: BLE001 — 종료 정리는 어떤 예외도 다음 자원을 막지 않는다
                errs.append(f"{name}:{type(e).__name__}:{e}")
        return errs
