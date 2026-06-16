"""FastAPI composition root helpers.

# KG: span_lakatotree_server_architecture
"""

from __future__ import annotations

from fastapi import FastAPI


def create_fastapi_app(*, lifespan) -> FastAPI:
    return FastAPI(
        title="Lakatos Server",
        version="1.0",
        lifespan=lifespan,
        description=(
            "연구 프로그램 트리(Lakatos/Laudan/Bayesian)의 KG+DB 백엔드. "
            "Neo4j(나무 그래프)+PostgreSQL(append-only 이력)+MongoDB(산출물). "
            "판결은 스크립트 채점 전용(LLM 점수 금지) · 행정판결은 /verdict(ADMIN_VERDICTS). "
            "계보=W3C PROV-O, 재현=rebuild-verify, 탐색=VoI/UCB directions."
        ),
    )
