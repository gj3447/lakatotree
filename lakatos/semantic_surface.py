"""Semantic surface contract.

The project has dense methodology. This module keeps that density honest by
checking that each named meaning has exactly one owning code symbol, tests, and
documentation.
# KG: span_lakatotree_semantic_surface
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from pathlib import Path


@dataclass(frozen=True)
class SemanticUnit:
    meaning_id: str
    owner_sourceId: str
    layer: str
    change_actor: str
    source_refs: tuple[str, ...]
    tests: tuple[str, ...]
    docs: tuple[str, ...]


@dataclass(frozen=True)
class SemanticSurfaceReport:
    ok: bool
    unit_count: int
    errors: tuple[str, ...] = ()


def load_surface(path: str | Path) -> tuple[SemanticUnit, ...]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return tuple(
        SemanticUnit(
            meaning_id=item["meaning_id"],
            owner_sourceId=item["owner_sourceId"],
            layer=item["layer"],
            change_actor=item.get("change_actor", ""),
            source_refs=tuple(item.get("source_refs") or ()),
            tests=tuple(item.get("tests") or ()),
            docs=tuple(item.get("docs") or ()),
        )
        for item in data.get("semantic_units", ())
    )


def validate_surface(
    units: tuple[SemanticUnit, ...],
    *,
    root: Path,
    longinus_manifest: dict,
) -> SemanticSurfaceReport:
    errors: list[str] = []
    if not units:
        errors.append("semantic_units_empty")

    ids = [u.meaning_id for u in units]
    owners = [u.owner_sourceId for u in units]
    for duplicate in _duplicates(ids):
        errors.append(f"duplicate_meaning_id:{duplicate}")
    for duplicate in _duplicates(owners):
        errors.append(f"duplicate_owner_sourceId:{duplicate}")

    longinus_ids = {b["sourceId"] for b in longinus_manifest.get("bindings", ())}
    for unit in units:
        if unit.owner_sourceId not in longinus_ids:
            errors.append(f"{unit.meaning_id}:owner_not_longinus_bound:{unit.owner_sourceId}")
        if not unit.change_actor.strip():
            errors.append(f"{unit.meaning_id}:missing_change_actor")
        if not unit.source_refs:
            errors.append(f"{unit.meaning_id}:missing_source_refs")
        for ref in unit.source_refs:
            if not _source_ref_valid(root, ref):
                errors.append(f"{unit.meaning_id}:source_ref_invalid:{ref}")
        if not unit.tests:
            errors.append(f"{unit.meaning_id}:missing_tests")
        for ref in unit.tests:
            if not _test_ref_exists(root, ref):
                errors.append(f"{unit.meaning_id}:test_ref_missing:{ref}")
        if not unit.docs:
            errors.append(f"{unit.meaning_id}:missing_docs")
        for ref in unit.docs:
            if not _doc_ref_exists(root, ref):
                errors.append(f"{unit.meaning_id}:doc_ref_missing:{ref}")

    return SemanticSurfaceReport(ok=not errors, unit_count=len(units), errors=tuple(errors))


def _duplicates(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    dup: set[str] = set()
    for value in values:
        if value in seen:
            dup.add(value)
        seen.add(value)
    return tuple(sorted(dup))


def _test_ref_exists(root: Path, ref: str) -> bool:
    path_s, _, symbol = ref.partition("::")
    path = root / path_s
    if not path.exists() or not symbol:
        return False
    pattern = re.compile(rf"^\s*def\s+{re.escape(symbol)}\s*\(")
    return any(pattern.search(line) for line in path.read_text(encoding="utf-8").splitlines())


def _doc_ref_exists(root: Path, ref: str) -> bool:
    path_s = ref.split("#", 1)[0].split(":", 1)[0]
    return bool(path_s) and (root / path_s).exists()


def _source_ref_valid(root: Path, ref: str) -> bool:
    if not ref.strip():
        return False
    if ref.startswith("repo:"):
        path_s = ref.removeprefix("repo:").split("#", 1)[0].split(":", 1)[0]
        return bool(path_s) and (root / path_s).exists()
    return ref.startswith(("external:", "kg:"))
