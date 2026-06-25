"""HTTP adapter for the Lakatos tree context.

# KG: seed-lkt-engine-tree-api-router-20260616
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter

from server.contexts.tree.schemas import CreateTreeIn, NodeIn, QuestionIn
from server.contexts.tree.service import TreeService


def create_tree_router(service_factory: Callable[[], TreeService]) -> APIRouter:
    """Build tree routes without letting server.app own tree use cases."""
    router = APIRouter()

    @router.get("/api/trees")
    def trees():
        return service_factory().list_trees()

    @router.get("/api/tree/{name}")
    def tree(name: str):
        return service_factory().tree_data(name)

    @router.post("/api/tree/{name}")
    def create_tree(name: str, spec: CreateTreeIn):
        """나무 생성/메타 upsert. GET 와 같은 경로지만 메서드(POST)로 분기 — 멱등·last-write-wins."""
        return service_factory().create_tree(name, spec)

    @router.get("/api/tree/{name}/metrics")
    def metrics(name: str, snapshot: bool = False):
        return service_factory().metrics(name, snapshot=snapshot)

    @router.post("/api/tree/{name}/node")
    def add_node(name: str, n: NodeIn):
        return service_factory().add_node(name, n)

    @router.post("/api/tree/{name}/question")
    def open_question(name: str, q: QuestionIn):
        return service_factory().open_question(name, q)

    @router.post("/api/tree/{name}/question/{qname}/close")
    def close_question(name: str, qname: str, closed_by: str = ""):
        return service_factory().close_question(name, qname, closed_by=closed_by)

    return router
