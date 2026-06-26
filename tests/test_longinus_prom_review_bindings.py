"""Longinus PROM review correction manifest checks.

These tests prevent review prose from being misreported as a verified Longinus
piercing. A PIERCED row must be concrete; preliminary critique must stay marked
as CANDIDATE/PRELIMINARY with a confidence tier.
# KG: CT_LakatoTree_3D_PROM_LonginusReview_20260624
"""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "longinus_prom_review_bindings_20260624.json"


def _load() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_manifest_schema_and_paths_resolve() -> None:
    data = _load()
    assert data["policy"]["allowed_confidence"] == ["EXTRACTED", "INFERRED", "AMBIGUOUS"]
    assert data["policy"]["allowed_binding_state"] == ["CANDIDATE", "PRELIMINARY", "PIERCED"]

    for item in data["bindings"]:
        assert item["sourceId"]
        assert item["sourcePath"]
        assert item["kg_anchor"]
        assert item["confidence"] in data["policy"]["allowed_confidence"]
        assert item["binding_state"] in data["policy"]["allowed_binding_state"]
        assert item["drift_type"] in {"Missing", "Orphan", "SigMismatch", "PatternDiv", "LabelRot"}
        assert item["lens_law"] in {"GetPut", "PutGet", "PutPut"}
        path = item["sourcePath"].split(":", 1)[0]
        assert (ROOT / path).exists(), item


def test_preliminary_claims_are_not_marked_pierced() -> None:
    data = _load()
    preliminary = [
        item for item in data["bindings"]
        if item["confidence"] in {"INFERRED", "AMBIGUOUS"}
    ]
    assert preliminary, "The review manifest must keep unverified critique separate from PIERCED."
    assert all(item["binding_state"] != "PIERCED" for item in preliminary)


def test_pierced_claims_have_rerunnable_acceptance() -> None:
    data = _load()
    pierced = [item for item in data["bindings"] if item["binding_state"] == "PIERCED"]
    assert pierced
    for item in pierced:
        assert item["confidence"] == "EXTRACTED"
        assert item["acceptance_check"].startswith("python -m pytest ")
        assert all((ROOT / ev.split(":", 1)[0]).exists() for ev in item["evidence"] if ev.startswith("docs/"))
