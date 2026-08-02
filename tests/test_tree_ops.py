"""Tree materialization dry-run and Neo4j index diagnostics.

# KG: seed-lkt-engine-materialization-dryrun-20260616, seed-lkt-engine-neo4j-index-diagnostics-20260616
"""

from __future__ import annotations

from fastapi import HTTPException
import pytest

from server.contexts.tree.diagnostics import diagnose_required_constraints
from server.contexts.tree.materialization import TreeMaterializationPlanner
from server.contexts.tree.mutations import TreeMutationService, TreeSpec
from server.contexts.tree.schemas import NodeIn, ParentEdgeIn, QuestionIn
from server.contexts.tree.validation import LakatosSemanticValidator
from server.contexts.tree.writer import TreeKgWriter


def test_materialization_planner_reports_chunks_counts_and_no_cypher_writes():
    planner = TreeMaterializationPlanner(chunk_size=2)
    spec = TreeSpec(
        name="T",
        hard_core="hc",
        frontier_rule="close frontier before promotion",
        nodes=tuple(
            [NodeIn(tag="root")]
            + [NodeIn(tag=f"n{i}", parent="root") for i in range(1, 5)]
        ),
        questions=tuple(QuestionIn(qname=f"q{i}") for i in range(3)),
    )

    plan = planner.plan(spec)

    assert plan.tree == "T"
    assert plan.node_chunks == [2, 2, 1]
    assert plan.edge_chunks == [2, 2]
    assert plan.question_chunks == [2, 1]
    assert plan.tx_count == 1
    assert plan.op_count == 11
    assert plan.rows == 13
    assert plan.to_dict()["dry_run"] is True


def test_materialization_plan_matches_atomic_bundle_runtime_accounting():
    spec = TreeSpec(
        name="T",
        hard_core="hc",
        frontier_rule="close frontier before promotion",
        nodes=tuple(
            [NodeIn(tag="root")]
            + [NodeIn(tag=f"n{i}", parent="root") for i in range(1, 5)]
        ),
        questions=tuple(QuestionIn(qname=f"q{i}") for i in range(3)),
    )
    planner = TreeMaterializationPlanner(chunk_size=2)
    plan = planner.plan(spec)

    def kg_tx(ops):
        batch = list(ops)
        return [
            [{"guard_status": "ok", "created": True}],
            [{"tree_upsert_generation": 1}],
            *([[]] * (len(batch) - 2)),
        ]

    writer = TreeKgWriter(kg_tx, chunk_size=2)
    runtime = writer.upsert_tree_bundle(
        name=spec.name,
        metadata={
            "hard_core": spec.hard_core,
            "frontier_rule": spec.frontier_rule,
        },
        nodes=spec.nodes,
        parent_edges_by_tag={
            node.tag: ([ParentEdgeIn(tag=node.parent)] if node.parent else [])
            for node in spec.nodes
        },
        questions=spec.questions,
        history_payload={
            "nodes": len(spec.nodes),
            "questions": len(spec.questions),
            "tx_count": 1,
            "policy_warnings": [],
        },
    )

    assert runtime.summary.tx_count == plan.tx_count
    assert runtime.summary.op_count == plan.op_count
    assert runtime.summary.rows == plan.rows


def test_mutation_service_dry_run_validates_before_any_write():
    writes = []
    svc = TreeMutationService(
        writer=TreeKgWriter(lambda ops: writes.append(ops), chunk_size=2),
        validator=LakatosSemanticValidator(),
        hist=lambda *a: None,
    )

    with pytest.raises(HTTPException) as exc:
        svc.plan_upsert_tree(TreeSpec(name="T", nodes=(NodeIn(tag="root"),)))

    assert exc.value.status_code == 422
    assert writes == []


def test_neo4j_constraint_diagnostics_emit_safe_missing_migrations():
    report = diagnose_required_constraints([
        {"name": "lkt_tree_name_unique", "type": "UNIQUENESS", "entityType": "NODE",
         "labelsOrTypes": ["LakatosTree"], "properties": ["name"]},
        {"name": "custom_node_name", "type": "UNIQUENESS", "entityType": "NODE",
         "labelsOrTypes": ["LakatosNode"], "properties": ["name"]},
    ])

    assert report["ok"] is False
    assert "LakatosTree.name" in report["present"]
    assert "LakatosNode.name" in report["missing"]
    assert {"OpenQuestion.(tree+name)", "Belief.(tree+belief_id)", "LakatosArgument.id",
            "OutboxEntry.id", "ResearchEvent.id", "ResearchTradition.tradition_id"} <= set(report["missing"])
    assert report["migration_cypher"] == [
        "CREATE CONSTRAINT lkt_node_name_unique IF NOT EXISTS FOR (n:LakatosNode) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT lkt_open_question_tree_name_key IF NOT EXISTS FOR (n:OpenQuestion) REQUIRE (n.tree, n.name) IS UNIQUE",
        "CREATE CONSTRAINT lkt_belief_tree_id_key IF NOT EXISTS FOR (n:Belief) REQUIRE (n.tree, n.belief_id) IS UNIQUE",
        "CREATE CONSTRAINT lkt_argument_id_unique IF NOT EXISTS FOR (n:LakatosArgument) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT lkt_outbox_id_unique IF NOT EXISTS FOR (n:OutboxEntry) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT lkt_research_event_id_unique IF NOT EXISTS FOR (n:ResearchEvent) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT lkt_research_tradition_id_unique IF NOT EXISTS FOR (n:ResearchTradition) REQUIRE n.tradition_id IS UNIQUE",
    ]


def test_research_tradition_constraint_required():
    # ① real-KG 연동: 전통 tradition_id uniqueness 강제(MERGE 키 중복 방지)
    from server.contexts.tree.diagnostics import REQUIRED_CONSTRAINTS
    spec = next(s for s in REQUIRED_CONSTRAINTS if s.label == "ResearchTradition")
    assert spec.property == "tradition_id" and spec.name == "lkt_research_tradition_id_unique"
    assert spec.migration_cypher == ("CREATE CONSTRAINT lkt_research_tradition_id_unique IF NOT EXISTS "
                                     "FOR (n:ResearchTradition) REQUIRE n.tradition_id IS UNIQUE")


def test_neo4j_constraint_diagnostic_facade_reads_show_constraints(monkeypatch):
    import server.app as app

    seen = []
    monkeypatch.setattr(
        app,
        "kg",
        lambda query, **params: seen.append(query) or [
            {"name": "lkt_tree_name_unique", "type": "UNIQUENESS", "entityType": "NODE",
             "labelsOrTypes": ["LakatosTree"], "properties": ["name"]},
        ],
    )

    report = app.neo4j_constraint_diagnostics()

    assert seen == ["SHOW CONSTRAINTS"]
    assert report["ok"] is False
    assert "LakatosTree.name" in report["present"]


@pytest.mark.parametrize(
    "row",
    [
        # Correct name is insufficient when the database object has the wrong semantics.
        {"name": "lkt_tree_name_unique", "type": "NODE_PROPERTY_EXISTENCE",
         "entityType": "NODE", "labelsOrTypes": ["LakatosTree"], "properties": ["name"]},
        {"name": "lkt_tree_name_unique", "type": "UNIQUENESS",
         "entityType": "RELATIONSHIP", "labelsOrTypes": ["LakatosTree"], "properties": ["name"]},
        {"name": "lkt_tree_name_unique", "type": "UNIQUENESS", "entityType": "NODE",
         "labelsOrTypes": ["LakatosTree", "Other"], "properties": ["name"]},
        {"name": "lkt_tree_name_unique", "type": "UNIQUENESS", "entityType": "NODE",
         "labelsOrTypes": ["LakatosTree"], "properties": ["name", "other"]},
    ],
)
def test_neo4j_constraint_diagnostics_reject_same_name_wrong_shape(row):
    report = diagnose_required_constraints([row])
    assert "LakatosTree.name" in report["missing"]
