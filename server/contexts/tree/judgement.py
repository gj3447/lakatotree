"""Judgement HTTP routes for tree node verdicts and scripted results.

# KG: seed-lkt-engine-route-judgement-extract-20260616
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter

from lakatos.verdicts import ReceiptChainBroken
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

    # R5(후속 PROM): G1 체인의 첫 공개 읽기표면 — R4(원장 완결) *후에만* 배선(선배선=거짓 변조 알람).
    #   lineage 의 rebuild_verify(동명이인, 데이터 계보용)와 의도적으로 경로/이름 구분.
    @router.get("/api/tree/{name}/node/{tag}/receipts")
    def node_receipts(name: str, tag: str):
        return service_factory().load_receipt_chain(name, tag)

    @router.get("/api/tree/{name}/node/{tag}/receipts/verify")
    def verify_verdict(name: str, tag: str):
        """체인 fold 재유도 vs 캐시 대조. 부패(dangling/끊김)는 500 이 아니라 열거 finding
        (RECEIPT_CHAIN_MISMATCH — fsck SSOT 어휘, G8 규율: 부패는 감사 발견으로)."""
        try:
            return service_factory().verify_verdict_chain(name, tag)
        except ReceiptChainBroken as e:
            return {'ok': False, 'finding': 'RECEIPT_CHAIN_MISMATCH', 'detail': str(e)}

    return router
