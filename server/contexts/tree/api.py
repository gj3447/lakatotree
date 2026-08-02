"""HTTP adapter for the Lakatos tree context.

# KG: seed-lkt-engine-tree-api-router-20260616
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Header

from server.contexts.tree.schemas import CreateTreeIn, NodeIn, QuestionIn
from server.contexts.tree.service import TreeService


def create_tree_router(service_factory: Callable[[], TreeService]) -> APIRouter:
    """Build tree routes without letting server.app own tree use cases."""
    router = APIRouter()

    @router.get("/api/trees")
    def trees():
        return service_factory().list_trees()

    @router.post("/api/trees/janitor")
    def list_index_janitor(delete_empty_probes: bool = False):
        """q-selfdev-list-index-janitor: dangling list/empty Probe 잔해 스캔(+선택 삭제)."""
        return service_factory().list_index_janitor(delete_empty_probes=delete_empty_probes)

    @router.get("/api/tree/{name}")
    def tree(name: str):
        return service_factory().tree_data(name)

    @router.post("/api/tree/{name}")
    def create_tree(
        name: str,
        spec: CreateTreeIn,
        create_only: bool = False,
        idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    ):
        """나무 생성/메타 upsert. create_only=true 면 동명 나무를 덮지 않고 409.

        ``Idempotency-Key``를 주면 동일 키+동일 본문 재시도는 처음 커밋을
        재사용하며, 동일 키+다른 본문은 충돌로 거부한다. 키가 없으면 기존
        last-write-wins 호출 의미를 유지한다.
        """
        return service_factory().create_tree(
            name,
            spec,
            create_only=create_only,
            idempotency_key=idempotency_key,
        )

    @router.delete("/api/tree/{name}")
    def delete_tree(
        name: str,
        cascade: bool = False,
        idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    ):
        """나무 삭제(파괴적). 멱등키를 의무화해 응답 유실 후 재시도가
        동명 재생성 트리를 지우는 ABA 오류를 막는다."""
        return service_factory().delete_tree(
            name,
            cascade=cascade,
            idempotency_key=idempotency_key,
        )

    @router.get("/api/tree/{name}/metrics")
    def metrics(name: str, snapshot: bool = False):
        return service_factory().metrics(name, snapshot=snapshot)

    @router.get("/api/tree/{name}/consilience")
    def consilience(name: str, leaf1: str, leaf2: str, credence: bool = False):
        """G7 재합류(R9-CONSIL) — 두 leaf 3-way 병합 리포트(criss-cross=가상조상, conflict=데이터).
        무변이(GET 이 계약). credence=true 는 union_credence 동봉 — 무타깃 확증=422 fail-closed."""
        return service_factory().consilience(name, leaf1, leaf2, credence=credence)

    @router.post("/api/tree/{name}/node")
    def add_node(name: str, n: NodeIn):
        return service_factory().add_node(name, n)

    @router.post("/api/tree/{name}/question")
    def open_question(name: str, q: QuestionIn):
        return service_factory().open_question(name, q)

    @router.post("/api/tree/{name}/question/{qname}/close")
    def close_question(name: str, qname: str, closed_by: str = ""):
        return service_factory().close_question(name, qname, closed_by=closed_by)

    @router.post("/api/tree/{name}/question/{qname}/reattribute")
    def reattribute_question(name: str, qname: str, closed_by: str = ""):
        """Append receipt-backed closer to CLOSED question (no reopen). Sprint A P0-2."""
        return service_factory().reattribute_question(name, qname, closed_by=closed_by)

    return router
