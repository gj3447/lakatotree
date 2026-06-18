"""Design-first guard for Laudan research-tradition work."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "THEORY" / "lakatotree-open-gaps" / "research_tradition_design.md"


def test_research_tradition_design_names_boundary_objects_and_authority():
    text = DOC.read_text(encoding="utf-8")

    for term in (
        "ResearchTradition",
        "TraditionCommitment",
        "TraditionRevision",
        "TraditionAppraisal",
        "diagnostic_only",
    ):
        assert term in text


def test_research_tradition_design_preserves_hard_core_boundary():
    text = DOC.read_text(encoding="utf-8")

    assert "LakatosGate" in text
    assert "HardCoreProtected" in text
    assert "different_programme" in text
    assert "must not silently override" in text


def test_research_tradition_design_has_future_ooptdd_contracts():
    text = DOC.read_text(encoding="utf-8")

    assert "Future OOPTDD Contracts" in text
    assert "same_tradition_revision" in text
    assert "tradition_drift" in text
    assert "different_programme_candidate" in text
