"""Request schemas for lineage routes.

# KG: seed-lkt-engine-route-lineage-extract-20260616
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DerivationIn(BaseModel):
    """Recorded data derivation: input sha + producer sha -> output sha."""

    # KG: seed-lkt-engine-route-lineage-extract-20260616

    output: str
    output_sha: str
    producer: str = ""
    producer_sha: str = ""
    inputs: list[tuple[str, str]] = Field(default_factory=list)
    params: dict = Field(default_factory=dict)
    kind: str = "intermediate"
    env: str = ""

