"""Evidence, argument, standing, and certificate HTTP routes for tree nodes.

# KG: seed-lkt-engine-route-evidence-claim-extract-20260616
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter

from server.contexts.tree.evidence_claim_service import EvidenceClaimService
from server.contexts.tree.schemas import CritiqueIn, ObservationIn, ResearchEventIn, WorldActionIn


def create_evidence_claim_router(service_factory: Callable[[], EvidenceClaimService]) -> APIRouter:
    """Create context-owned routes. Routes call the service directly — no
    intermediate Surface of positional callables (one HTTP surface, SSOT)."""

    # KG: seed-lkt-engine-route-evidence-claim-extract-20260616

    router = APIRouter()

    @router.get("/api/tree/{name}/node/{tag}/provenance")
    def provenance(name: str, tag: str):
        return service_factory().provenance(name, tag)

    @router.post("/api/tree/{name}/node/{tag}/critique")
    def add_critique(name: str, tag: str, c: CritiqueIn):
        return service_factory().add_critique(name, tag, c)

    @router.post("/api/tree/{name}/node/{tag}/event")
    def add_research_event(name: str, tag: str, ev: ResearchEventIn):
        return service_factory().add_research_event(name, tag, ev)

    @router.post("/api/tree/{name}/node/{tag}/observation")
    def add_observation(name: str, tag: str, o: ObservationIn):
        return service_factory().add_observation(name, tag, o)

    @router.post("/api/tree/{name}/node/{tag}/world-action")
    def add_world_action(name: str, tag: str, a: WorldActionIn):
        return service_factory().add_world_action(name, tag, a)

    @router.get("/api/tree/{name}/node/{tag}/standing")
    def standing(name: str, tag: str):
        return service_factory().standing(name, tag)

    @router.get("/api/tree/{name}/node/{tag}/events")
    def research_events(name: str, tag: str):
        return service_factory().research_events(name, tag)

    @router.get("/api/tree/{name}/node/{tag}/claim-standing")
    def claim_standing(name: str, tag: str, require_replay: bool = True):
        return service_factory().claim_standing(name, tag, require_replay=require_replay)

    @router.get("/api/tree/{name}/node/{tag}/certificate")
    def node_certificate(name: str, tag: str):
        return service_factory().node_certificate(name, tag)

    return router
