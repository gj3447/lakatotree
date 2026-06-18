"""Semantic meaning ↔ code ownership contract.

This is the anti-bloat version of "meaning/code 1:1": every high-level meaning
has exactly one primary owner sourceId, plus executable tests and docs.
# KG: span_lakatotree_semantic_surface
"""

import json
from pathlib import Path

from lakatos.semantic_surface import load_surface, validate_surface


ROOT = Path(__file__).resolve().parents[1]
SURFACE = ROOT / "docs" / "semantic_surface.json"
LONGINUS = ROOT / "docs" / "longinus_bindings.json"


def test_semantic_surface_maps_meanings_to_code_tests_and_docs():
    units = load_surface(SURFACE)
    manifest = json.loads(LONGINUS.read_text(encoding="utf-8"))

    report = validate_surface(units, root=ROOT, longinus_manifest=manifest)

    assert report.ok, report.errors
    assert report.unit_count >= 12


def test_semantic_surface_owner_is_one_to_one():
    units = load_surface(SURFACE)
    owners = [unit.owner_sourceId for unit in units]
    meanings = [unit.meaning_id for unit in units]

    assert len(owners) == len(set(owners))
    assert len(meanings) == len(set(meanings))


def test_semantic_surface_records_change_actor_and_source_refs():
    units = load_surface(SURFACE)

    assert all(unit.change_actor.strip() for unit in units)
    assert all(unit.source_refs for unit in units)
    assert any(ref.startswith("external:") for unit in units for ref in unit.source_refs)
    assert any(ref.startswith("kg:") for unit in units for ref in unit.source_refs)


def test_semantic_surface_catches_duplicate_owner():
    units = load_surface(SURFACE)
    bad = units + (units[0].__class__(
        meaning_id="duplicate_owner_probe",
        owner_sourceId=units[0].owner_sourceId,
        layer=units[0].layer,
        change_actor=units[0].change_actor,
        source_refs=units[0].source_refs,
        tests=units[0].tests,
        docs=units[0].docs,
    ),)

    report = validate_surface(
        bad,
        root=ROOT,
        longinus_manifest=json.loads(LONGINUS.read_text(encoding="utf-8")),
    )

    assert not report.ok
    assert any(err.startswith("duplicate_owner_sourceId:") for err in report.errors)


def test_semantic_surface_catches_missing_actor_and_source_refs():
    units = load_surface(SURFACE)
    bad = (units[0].__class__(
        meaning_id=units[0].meaning_id,
        owner_sourceId=units[0].owner_sourceId,
        layer=units[0].layer,
        change_actor="",
        source_refs=(),
        tests=units[0].tests,
        docs=units[0].docs,
    ),) + units[1:]

    report = validate_surface(
        bad,
        root=ROOT,
        longinus_manifest=json.loads(LONGINUS.read_text(encoding="utf-8")),
    )

    assert not report.ok
    assert f"{units[0].meaning_id}:missing_change_actor" in report.errors
    assert f"{units[0].meaning_id}:missing_source_refs" in report.errors
