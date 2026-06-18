"""Programme-level tree HTTP routes.

# KG: seed-lkt-engine-route-programme-extract-20260616
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter

from server.contexts.tree.programme_service import ProgrammeService
from server.contexts.tree.schemas import (
    ArtifactIn,
    CycleIn,
    ElementIn,
    ElementUseIn,
    FoundationRequirementIn,
)


def create_programme_router(service_factory: Callable[[], ProgrammeService]) -> APIRouter:
    """Create context-owned programme routes. Routes call the service directly —
    no intermediate Surface of positional callables (one HTTP surface, SSOT)."""

    # KG: seed-lkt-engine-route-programme-extract-20260616

    router = APIRouter()

    @router.get("/api/tree/{name}/calibration")
    def calibration(name: str):
        return service_factory().calibration(name)

    @router.get("/api/tree/{name}/directions")
    def directions(name: str):
        return service_factory().directions(name)

    @router.get("/api/tree/{name}/stack")
    def stack_view(name: str, leaf: str | None = None):
        return service_factory().stack_view(name, leaf=leaf)

    @router.get("/api/tree/{name}/lifecycle")
    def lifecycle_view(name: str, leaf: str | None = None):
        return service_factory().lifecycle_view(name, leaf=leaf)

    @router.get("/api/tree/{name}/heuristic")
    def heuristic_view(name: str, leaf: str | None = None):
        return service_factory().heuristic_view(name, leaf=leaf)

    @router.get("/api/tree/{name}/trust")
    def trust_view(name: str):
        return service_factory().trust_view(name)

    @router.post("/api/tree/{name}/cycle")
    def run_cycle(name: str, c: CycleIn):
        return service_factory().run_cycle(name, c)

    @router.post("/api/tree/{name}/artifact")
    def add_artifact(name: str, a: ArtifactIn):
        return service_factory().add_artifact(name, a)

    @router.post("/api/tree/{name}/element")
    def add_element(name: str, el: ElementIn):
        return service_factory().add_element(name, el)

    @router.post("/api/tree/{name}/node/{tag}/element/{element_name}")
    def attach_element(name: str, tag: str, element_name: str, use: ElementUseIn):
        return service_factory().attach_element(name, tag, element_name, use)

    @router.post("/api/tree/{name}/foundation")
    def add_foundation_requirement(name: str, req: FoundationRequirementIn):
        return service_factory().add_foundation_requirement(name, req)

    @router.get("/api/tree/{name}/foundation")
    def get_foundation_requirements(name: str):
        return service_factory().get_foundation_requirements(name)

    @router.get("/api/tree/{name}/history")
    def history(name: str, limit: int = 100):
        return service_factory().history(name, limit=limit)

    @router.get("/api/tree/ops/neo4j-constraints")
    def neo4j_constraint_diagnostics():
        return service_factory().neo4j_constraint_diagnostics()

    return router
