"""Internet observations embedded into Lakatos theory/rival space.

This pins the missing joint: web data is not just a citation. It must be
located in the programme's theoretical structure, linked to rival programmes,
and bound through Longinus source refs.
"""

from datetime import datetime, timezone
import importlib
import os

import pytest
from fastapi import HTTPException

from lakatos.engine import (
    EmbeddedInternetEvidence,
    InternetObservation,
    LonginusRef,
    RivalProgrammeLink,
    RivalRelation,
    SourceCredibilityScore,
    TheoryEmbedding,
)


def _obs() -> InternetObservation:
    return InternetObservation(
        name="obs:w3c-prov",
        url="https://www.w3.org/TR/prov-o/",
        query="PROV-O provenance model",
        retrieved_at=datetime(2026, 6, 18, tzinfo=timezone.utc),
        content_hash="abc123",
        fetch_tool="web",
        source_type="standard",
        credibility=SourceCredibilityScore(
            source_class_weight=0.95,
            primary_source_bonus=0.9,
            provenance_score=1.0,
            recency_score=0.7,
        ),
    )


def test_embedded_internet_evidence_projects_theory_rival_and_longinus():
    embedded = EmbeddedInternetEvidence(
        observation=_obs(),
        tree_name="LakatoTree",
        node_tag="g-web",
        embedding=TheoryEmbedding(
            lakatos_location="protective_belt",
            theoretical_basis="InternetObservation is an append-only external-world observation.",
            foundation_refs=("trust-and-provenance-contract",),
            longinus_refs=(
                LonginusRef(
                    sourceId="world_gates.web_gate",
                    sourcePath="lakatos/world_gates.py:60",
                    layer="protective_belt",
                ),
            ),
        ),
        rival_links=(
            RivalProgrammeLink(
                programme="citation-pile",
                relation=RivalRelation.CONTRADICTS,
                rival_node="untyped_web_quote",
                comparison_axes=("provenance", "trust_decomposition"),
                evidence_refs=("obs:w3c-prov",),
            ),
        ),
    )

    projection = embedded.kg_projection()
    assert projection["observation"]["name"] == "obs:w3c-prov"
    assert projection["embedding"]["lakatos_location"] == "protective_belt"
    assert projection["longinus_refs"][0]["sourceId"] == "world_gates.web_gate"
    assert projection["rival_links"][0]["relation"] == "contradicts"
    assert projection["edges"] == {
        "LOCATED_IN": "LakatoTree/g-web",
        "BOUND_BY": ["world_gates.web_gate"],
        "RIVAL_EVIDENCE": ["citation-pile"],
    }


def test_rival_embedding_requires_longinus_ref():
    with pytest.raises(ValueError, match="longinus"):
        EmbeddedInternetEvidence(
            observation=_obs(),
            tree_name="LakatoTree",
            node_tag="g-web",
            embedding=TheoryEmbedding(lakatos_location="hard_core"),
            rival_links=(RivalProgrammeLink(programme="rival", relation="supports"),),
        )


def test_theory_embedding_rejects_bad_lakatos_location():
    with pytest.raises(ValueError, match="lakatos_location"):
        TheoryEmbedding(lakatos_location="citation_bucket")


def load_app():
    os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
    os.environ.setdefault("NEO4J_USER", "neo4j")
    os.environ.setdefault("NEO4J_PASSWORD", "test")
    return importlib.import_module("server.app")


def test_observation_endpoint_wires_theory_rival_and_longinus(monkeypatch):
    app = load_app()
    calls = []

    def fake_kg(query, **kw):
        calls.append((query, kw))
        return [{"id": kw.get("id", "ok")}]

    monkeypatch.setattr(app, "kg", fake_kg)
    monkeypatch.setattr(app, "hist", lambda *a, **k: None)

    out = app.add_observation(
        "T",
        "g-web",
        app.ObservationIn(
            event_id="o1",
            url="https://www.w3.org/TR/prov-o/",
            retrieved_at="2026-06-18T00:00:00Z",
            content_hash="abc",
            source_type="standard",
            source_class_weight=0.95,
            primary_source_bonus=0.9,
            provenance_score=1.0,
            lakatos_location="protective_belt",
            theory_basis="PROV-O anchors provenance semantics for InternetObservation.",
            foundation_refs=["trust-and-provenance-contract"],
            rival_name="citation-pile",
            rival_relation="contradicts",
            rival_node="untyped_web_quote",
            comparison_axes=["provenance", "trust_decomposition"],
            longinus_refs=[
                app.LonginusRefIn(
                    sourceId="world_gates.web_gate",
                    sourcePath="lakatos/world_gates.py:60",
                    layer="protective_belt",
                )
            ],
        ),
    )

    assert out["embedding"]["rival_links"][0]["programme"] == "citation-pile"
    assert out["embedding"]["longinus_refs"][0]["sourceId"] == "world_gates.web_gate"
    assert any("RIVAL_EVIDENCE" in q for q, _ in calls)
    assert any("ReferenceSite:Longinus" in q for q, _ in calls)


def test_rival_observation_endpoint_requires_longinus(monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, "kg", lambda *a, **k: [{"id": "ok"}])
    monkeypatch.setattr(app, "hist", lambda *a, **k: None)

    with pytest.raises(HTTPException) as exc:
        app.add_observation(
            "T",
            "g-web",
            app.ObservationIn(
                event_id="o2",
                url="https://example.org",
                retrieved_at="2026-06-18T00:00:00Z",
                content_hash="abc",
                source_type="paper",
                source_class_weight=0.8,
                lakatos_location="hard_core",
                rival_name="rival",
                rival_relation="supports",
            ),
        )
    assert exc.value.status_code == 422
    assert "Longinus" in exc.value.detail
