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
    # AGM belief identity is tree-local. Apply scripts/migrate_belief_tree_scope_20260728.cypher first.
    CompositeUniqueSpec("lkt_belief_tree_id_key", "Belief", ("tree", "belief_id")),
    # Arguments use the globally unique ``tree/arg`` content identity.  The application also
    # serializes writes on the tree node; this constraint catches out-of-band writers.
    ConstraintSpec("lkt_argument_id_unique", "LakatosArgument", "id"),
    # Atomic critique history depends on one durable intent per stable history event.  A
    # same-named but differently-shaped constraint must not satisfy this requirement.
    ConstraintSpec("lkt_outbox_id_unique", "OutboxEntry", "id"),
    ConstraintSpec("lkt_research_event_id_unique", "ResearchEvent", "id"),
    # ① real-KG: 연구전통 tradition_id uniqueness — set_tradition 의 MERGE 키 중복(같은 id 두 전통) 방지.
    ConstraintSpec("lkt_research_tradition_id_unique", "ResearchTradition", "tradition_id"),
    ConstraintSpec(
        "lkt_prediction_temporal_commitment_sha_unique",
        "PredictionTemporalCommitment",
        "commitment_sha256",
    ),
    CompositeUniqueSpec(
        "lkt_prediction_temporal_commitment_target_unique",
        "PredictionTemporalCommitment",
        ("tree_incarnation_id", "tree", "tag", "prediction_receipt_sha256"),
    ),
    ConstraintSpec(
        "lkt_temporal_proof_sidecar_sha_unique",
        "TemporalProofSidecar",
        "sidecar_sha256",
    ),
    CompositeUniqueSpec(
        "lkt_temporal_proof_sidecar_target_unique",
        "TemporalProofSidecar",
        ("tree_incarnation_id", "tree", "tag", "verdict_receipt_sha256"),
    ),
)


# The structural-batch/CAS surface has a narrower, fail-closed deployment gate.
# Keep it separate from the legacy programme diagnostic: enabling the new
# endpoint must not silently redefine readiness for unrelated routes.
STRUCTURAL_BATCH_REQUIRED_CONSTRAINTS = (
    ConstraintSpec("lkt_tree_name_unique", "LakatosTree", "name"),
    ConstraintSpec("lkt_node_name_unique", "LakatosNode", "name"),
    CompositeUniqueSpec(
        "lkt_open_question_tree_name_key", "OpenQuestion", ("tree", "name")
    ),
    ConstraintSpec("lkt_outbox_id_unique", "OutboxEntry", "id"),
    ConstraintSpec(
        "lkt_foundation_requirement_name_unique",
        "FoundationRequirement",
        "name",
    ),
    ConstraintSpec("lkt_element_name_unique", "LakatosElement", "name"),
    ConstraintSpec(
        "lkt_structural_batch_receipt_id_unique",
        "StructuralBatchReceipt",
        "id",
    ),
)


def structural_batch_identity_audit_query() -> str:
    """Return one read-only population-audit row per batch identity.

    Neo4j uniqueness constraints do not reject ``null`` identity properties,
    and a missing constraint can coexist with duplicate values.  The batch
    readiness gate therefore checks both facts explicitly before it grants the
    writer permission to enter the managed transaction.
    """

    branches: list[str] = []
    for spec in STRUCTURAL_BATCH_REQUIRED_CONSTRAINTS:
        if len(spec.properties) == 1:
            prop = spec.properties[0]
            null_predicate = f"n.{prop} IS NULL"
            identity = f"n.{prop}"
            duplicate_value = f"{{value:identity,copies:copies}}"
        else:
            null_predicate = " OR ".join(
                f"n.{prop} IS NULL" for prop in spec.properties
            )
            identity = "[" + ",".join(f"n.{prop}" for prop in spec.properties) + "]"
            duplicate_value = f"{{values:identity,copies:copies}}"
        branches.append(
            f"""
CALL {{
  MATCH (n:{spec.label})
  RETURN sum(CASE WHEN {null_predicate} THEN 1 ELSE 0 END) AS null_count
}}
CALL {{
  MATCH (n:{spec.label})
  WHERE NOT ({null_predicate})
  WITH {identity} AS identity, count(*) AS copies
  WHERE copies > 1
  RETURN collect({duplicate_value}) AS duplicate_keys
}}
RETURN '{spec.key}' AS key, null_count, duplicate_keys
""".strip()
        )
    return "\nUNION ALL\n".join(branches)


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


def diagnose_structural_batch_constraints(
    rows: Iterable[dict],
    identity_rows: Iterable[dict],
) -> dict:
    """Require exact constraints and complete, duplicate-free identity columns.

    ``identity_rows`` is a read-only population audit with one row per required
    identity: ``key``, ``null_count`` and ``duplicate_keys``.  The function is
    deliberately pure so the HTTP service cannot mistake a health endpoint for
    migration authority.
    """

    constraint_rows = list(rows)
    population = list(identity_rows)
    present = {
        spec.key
        for spec in STRUCTURAL_BATCH_REQUIRED_CONSTRAINTS
        if any(_row_satisfies(row, spec) for row in constraint_rows)
    }
    missing = [
        spec
        for spec in STRUCTURAL_BATCH_REQUIRED_CONSTRAINTS
        if spec.key not in present
    ]
    shape_conflicts = sorted({
        str(row.get("name"))
        for spec in STRUCTURAL_BATCH_REQUIRED_CONSTRAINTS
        for row in constraint_rows
        if row.get("name") == spec.name and not _row_satisfies(row, spec)
    })
    by_key = {
        row.get("key"): row
        for row in population
        if isinstance(row, dict) and isinstance(row.get("key"), str)
    }
    null_identities: list[dict] = []
    duplicate_keys: list[dict] = []
    for spec in STRUCTURAL_BATCH_REQUIRED_CONSTRAINTS:
        row = by_key.get(spec.key)
        if row is None:
            null_identities.append({"key": spec.key, "count": None})
            duplicate_keys.append({"key": spec.key, "values": None})
            continue
        null_count = row.get("null_count")
        duplicates = row.get("duplicate_keys")
        if type(null_count) is not int or null_count < 0:
            null_identities.append({"key": spec.key, "count": None})
        elif null_count:
            null_identities.append({"key": spec.key, "count": null_count})
        if not isinstance(duplicates, list):
            duplicate_keys.append({"key": spec.key, "values": None})
        elif duplicates:
            duplicate_keys.append({"key": spec.key, "values": duplicates})
    return {
        "ok": not (missing or shape_conflicts or null_identities or duplicate_keys),
        "required": [spec.key for spec in STRUCTURAL_BATCH_REQUIRED_CONSTRAINTS],
        "present": sorted(present),
        "missing": [spec.key for spec in missing],
        "shape_conflicts": shape_conflicts,
        "null_identities": null_identities,
        "duplicate_keys": duplicate_keys,
        "migration_cypher": [spec.migration_cypher for spec in missing],
    }


def _row_satisfies(row: dict, spec) -> bool:
    """Require the exact named node-uniqueness constraint shape.

    ``SHOW CONSTRAINTS`` is deployment evidence, not a fuzzy discovery surface.  The
    previous name-only shortcut and subset comparison could report readiness for a
    relationship constraint, an existence constraint, or a wider composite key.  All of
    those are unsafe false positives for MERGE concurrency.
    """

    uniqueness_types = {
        "UNIQUENESS",                 # Neo4j 5.x compatibility spelling
        "NODE_UNIQUENESS",
        "NODE_PROPERTY_UNIQUENESS",
        "NODE_KEY",
    }
    labels = _as_tuple(row.get("labelsOrTypes") or row.get("labels"))
    properties = _as_tuple(
        row.get("properties") or row.get("property") or row.get("propertyNames")
    )
    return (
        row.get("name") == spec.name
        and row.get("entityType") == "NODE"
        and row.get("type") in uniqueness_types
        and labels == (spec.label,)
        and properties == tuple(spec.properties)
    )


def _as_tuple(value) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)
