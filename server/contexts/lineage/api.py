"""HTTP adapter for artifact lineage routes.

# KG: seed-lkt-engine-route-lineage-extract-20260616
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter

from server.contexts.lineage.schemas import DerivationIn
from server.contexts.lineage.service import LineageService


def create_lineage_router(service_factory: Callable[[], LineageService]) -> APIRouter:
    """Create context-owned lineage routes without letting server.app own HTTP handlers."""

    # KG: seed-lkt-engine-route-lineage-extract-20260616

    router = APIRouter()

    @router.post("/api/lineage/derivation")
    def record_derivation(d: DerivationIn):
        return service_factory().record_derivation(d)

    @router.get("/api/openlineage/{artifact:path}")
    def artifact_openlineage(artifact: str):
        return service_factory().artifact_openlineage(artifact)

    @router.post("/api/openlineage/{artifact:path}/marquez")
    def send_artifact_to_marquez(artifact: str):
        return service_factory().send_artifact_to_marquez(artifact)

    @router.get("/api/dvc/{artifact:path}")
    def artifact_dvc(artifact: str):
        return service_factory().artifact_dvc(artifact)

    @router.get("/api/prov/{artifact:path}")
    def artifact_prov(artifact: str, format: str | None = None):
        return service_factory().artifact_prov(artifact, format=format)

    @router.get("/api/rebuild-verify/{artifact:path}")
    def rebuild_verify(artifact: str):
        return service_factory().rebuild_verify(artifact)

    @router.get("/api/lineage-script/{producer:path}")
    def get_script_history(producer: str):
        return service_factory().get_script_history(producer)

    @router.get("/api/lineage/{artifact:path}")
    def get_lineage(artifact: str, stale: bool = False):
        return service_factory().get_lineage(artifact, stale=stale)

    return router

