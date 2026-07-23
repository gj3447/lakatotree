"""Longinus-bind the HSWM related-work boundary without inventing a runtime owner.

The machine-readable reference registry is grounded into the Longinus manifest,
mirrored in the research-programme prose, and represented as an honest Meaning-SRP
gap until agent attachment and verdict-driven redispatch actually exist.

# KG: span_lakatotree_hswm_related_work
"""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELATED = ROOT / "docs" / "hswm_related_work.json"
LONGINUS = ROOT / "docs" / "longinus_bindings.json"
MEANINGS = ROOT / "docs" / "meaning_units.json"
PROGRAMME = ROOT / "docs" / "HSWM_RESEARCH_PROGRAMME.md"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_related_work_registry_is_longinus_grounded_and_unique():
    related = _load(RELATED)
    longinus = _load(LONGINUS)
    refs = related["references"]

    assert related["status"] == "grounding-boundary-not-priority-claim"
    assert related["candidate_contribution"]["status"] == "unverified-contribution-hypothesis"
    assert related["longinus_anchor"] in longinus["kg_anchors"]

    source_refs = [ref["source_ref"] for ref in refs]
    urls = [ref["url"] for ref in refs]
    assert len(refs) == 6
    assert len(source_refs) == len(set(source_refs))
    assert len(urls) == len(set(urls))
    assert set(source_refs) <= set(longinus["accepted_grounding_refs"])


def test_related_work_registry_pierces_the_human_readable_boundary():
    related = _load(RELATED)
    prose = PROGRAMME.read_text(encoding="utf-8")

    for ref in related["references"]:
        assert ref["url"] in prose
        assert ref["non_novel_claim"] in prose
        assert ref["evidence_tier"] in {
            "peer-reviewed-primary", "preprint", "workshop-position", "workshop-poster"
        }

    assert related["candidate_contribution"]["claim"] in prose
    assert "systematic review receipt 없이는 “최초”를 주장하지 않는다" in prose


def test_unimplemented_hswm_runtime_is_an_honest_meaning_gap():
    related = _load(RELATED)
    meanings = _load(MEANINGS)["meaning_units"]
    unit = next(u for u in meanings if u["unit"].startswith("HSWM attached-agent causal redispatch"))

    assert unit["status"] == "gap"
    assert unit["owner"] is None
    assert "no generic agent attachment" in unit["reason"]
    assert set(ref["source_ref"] for ref in related["references"]) <= set(unit["source_refs"])
    assert "unique runtime owner" in unit["next_action"]
