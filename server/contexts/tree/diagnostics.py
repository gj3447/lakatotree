"""Operational diagnostics for the tree KG surface.

# KG: seed-lkt-engine-neo4j-index-diagnostics-20260616
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ConstraintSpec:
    name: str
    label: str
    property: str

    @property
    def key(self) -> str:
        return f"{self.label}.{self.property}"

    @property
    def migration_cypher(self) -> str:
        return (
            f"CREATE CONSTRAINT {self.name} IF NOT EXISTS "
            f"FOR (n:{self.label}) REQUIRE n.{self.property} IS UNIQUE"
        )


REQUIRED_CONSTRAINTS = (
    ConstraintSpec("lkt_tree_name_unique", "LakatosTree", "name"),
    ConstraintSpec("lkt_node_name_unique", "LakatosNode", "name"),
    ConstraintSpec("lkt_open_question_name_unique", "OpenQuestion", "name"),
    ConstraintSpec("lkt_research_event_id_unique", "ResearchEvent", "id"),
    # ① real-KG: 연구전통 tradition_id uniqueness — set_tradition 의 MERGE 키 중복(같은 id 두 전통) 방지.
    ConstraintSpec("lkt_research_tradition_id_unique", "ResearchTradition", "tradition_id"),
)


def diagnose_required_constraints(rows: Iterable[dict]) -> dict:
    """Report required constraints present/missing from SHOW CONSTRAINTS rows."""

    # KG: seed-lkt-engine-neo4j-index-diagnostics-20260616

    present = {
        spec.key
        for spec in REQUIRED_CONSTRAINTS
        if any(_row_satisfies(row, spec) for row in rows)
    }
    missing = [spec for spec in REQUIRED_CONSTRAINTS if spec.key not in present]
    return {
        "ok": not missing,
        "required": [spec.key for spec in REQUIRED_CONSTRAINTS],
        "present": sorted(present),
        "missing": [spec.key for spec in missing],
        "migration_cypher": [spec.migration_cypher for spec in missing],
    }


def _row_satisfies(row: dict, spec: ConstraintSpec) -> bool:
    if row.get("name") == spec.name:
        return True
    labels = _as_set(row.get("labelsOrTypes") or row.get("labels") or row.get("entityType"))
    properties = _as_set(row.get("properties") or row.get("property") or row.get("propertyNames"))
    return spec.label in labels and spec.property in properties


def _as_set(value) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {value}
    return {str(item) for item in value}
