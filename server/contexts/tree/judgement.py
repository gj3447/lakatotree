"""Judgement HTTP routes for tree node verdicts and scripted results.

# KG: seed-lkt-engine-route-judgement-extract-20260616
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter

from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import PredictionIn, TestResultIn, VerdictIn


def create_judgement_router(service_factory: Callable[[], JudgementService]) -> APIRouter:
    """Create context-owned judgement routes. Routes call the service directly —
    no intermediate Surface of positional callables (one HTTP surface, SSOT)."""

    # KG: seed-lkt-engine-route-judgement-extract-20260616

    router = APIRouter()

    @router.post("/api/tree/{name}/node/{tag}/verdict")
    def set_verdict(name: str, tag: str, v: VerdictIn):
        return service_factory().set_verdict(name, tag, v)

    @router.post("/api/tree/{name}/node/{tag}/prediction")
    def register_prediction(name: str, tag: str, p: PredictionIn):
        return service_factory().register_prediction(name, tag, p)

    @router.post("/api/tree/{name}/node/{tag}/test_result")
    def submit_test_result(name: str, tag: str, r: TestResultIn):
        return service_factory().submit_test_result(name, tag, r)

    @router.get("/api/tree/{name}/node/{tag}/eureka")
    def node_eureka(name: str, tag: str):
        return service_factory().node_eureka(name, tag)

    return router
