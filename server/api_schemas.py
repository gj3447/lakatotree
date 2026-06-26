"""Compatibility facade for HTTP request contracts.

Tree-context models live in ``server.contexts.tree.schemas``. This module
re-exports them so existing callers that import ``server.api_schemas`` keep
working while new context code imports local schemas directly.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from server.contexts.lineage.schemas import DerivationIn
from server.contexts.tree.schemas import (
    ArtifactIn,
    CritiqueIn,
    CycleIn,
    ElementIn,
    ElementUseIn,
    FoundationRequirementIn,
    LonginusRefIn,
    NodeIn,
    ObservationIn,
    ParentEdgeIn,
    PredictionIn,
    QuestionIn,
    ResearchEventIn,
    TestResultIn,
    VerdictIn,
    WorldActionIn,
)


class BeliefIn(BaseModel):
    belief_id: str
    statement: str = ""
    kind: str = "protective_belt"
    credence: float = Field(0.5, ge=0, le=1)
    problem_balance: int = 0
    connectivity: int = 0
    depends_on: list[str] = Field(default_factory=list)


class AgmReviseIn(BaseModel):
    op: str = "revision"
    tree: str = ""          # A4: 주면 stateful — 트리의 영속 belief base 로드/저장 + auto-rejudge
    base: list[BeliefIn] = Field(default_factory=list)
    new: BeliefIn | None = None
    target_id: str | None = None
    contradicts: list[str] = Field(default_factory=list)
    old_canonical_id: str | None = None
    allow_hard_core: bool = False


__all__ = [
    "AgmReviseIn",
    "ArtifactIn",
    "BeliefIn",
    "CritiqueIn",
    "CycleIn",
    "DerivationIn",
    "ElementIn",
    "ElementUseIn",
    "FoundationRequirementIn",
    "LonginusRefIn",
    "NodeIn",
    "ObservationIn",
    "ParentEdgeIn",
    "PredictionIn",
    "QuestionIn",
    "ResearchEventIn",
    "TestResultIn",
    "VerdictIn",
    "WorldActionIn",
]
