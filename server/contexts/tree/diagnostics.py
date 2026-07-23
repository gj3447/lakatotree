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
    def properties(self) -> tuple[str, ...]:
        return (self.property,)

    @property
    def migration_cypher(self) -> str:
        return (
            f"CREATE CONSTRAINT {self.name} IF NOT EXISTS "
            f"FOR (n:{self.label}) REQUIRE n.{self.property} IS UNIQUE"
        )


@dataclass(frozen=True)
class CompositeUniqueSpec:
    """복합 UNIQUE 제약 — 2026-07-23 OpenQuestion 트리-스코프 수리로 도입.

    종전 lkt_open_question_name_unique(name 전역 UNIQUE)는 두 트리의 같은 qname 공존을
    제약 수준에서 봉쇄해 전역 공유 노드(충돌)를 구조적으로 강제했다. (tree, name) 복합
    UNIQUE 로 교체 — 트리별 같은 qname 허용, 같은 트리 안 중복만 봉쇄.
    (NODE KEY 는 Enterprise 전용이라 Community 호환을 위해 UNIQUE — tree 존재 강제는
    writer 가 MERGE 키로 항상 세팅하므로 애플리케이션 레벨에서 보장.)"""

    name: str
    label: str
    properties: tuple[str, ...]

    @property
    def key(self) -> str:
        return f"{self.label}.({'+'.join(self.properties)})"

    @property
    def migration_cypher(self) -> str:
        props = ", ".join(f"n.{p}" for p in self.properties)
        return (
            f"CREATE CONSTRAINT {self.name} IF NOT EXISTS "
            f"FOR (n:{self.label}) REQUIRE ({props}) IS UNIQUE"
        )


REQUIRED_CONSTRAINTS = (
    ConstraintSpec("lkt_tree_name_unique", "LakatosTree", "name"),
    ConstraintSpec("lkt_node_name_unique", "LakatosNode", "name"),
    # (tree, name) 복합키 — name 전역 UNIQUE 였던 것을 2026-07-23 트리-스코프 수리로 교체.
    # 적용 전 선행 마이그레이션 필수(기존 노드 tree 박기): scripts/migrate_open_question_tree_scope_20260723.cypher
    CompositeUniqueSpec("lkt_open_question_tree_name_key", "OpenQuestion", ("tree", "name")),
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


def _row_satisfies(row: dict, spec) -> bool:
    if row.get("name") == spec.name:
        return True
    labels = _as_set(row.get("labelsOrTypes") or row.get("labels") or row.get("entityType"))
    properties = _as_set(row.get("properties") or row.get("property") or row.get("propertyNames"))
    return spec.label in labels and set(spec.properties) <= properties


def _as_set(value) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {value}
    return {str(item) for item in value}
