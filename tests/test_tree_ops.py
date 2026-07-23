"""Tree materialization dry-run and Neo4j index diagnostics.

# KG: seed-lkt-engine-materialization-dryrun-20260616, seed-lkt-engine-neo4j-index-diagnostics-20260616
"""

from __future__ import annotations

from fastapi import HTTPException
import pytest

from server.contexts.tree.diagnostics import diagnose_required_constraints
from server.contexts.tree.materialization import TreeMaterializationPlanner
from server.contexts.tree.mutations import TreeMutationService, TreeSpec
from server.contexts.tree.schemas import NodeIn, QuestionIn
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
    assert plan.tx_count == 8
    assert plan.op_count == 8
    assert plan.rows == 13
    assert plan.to_dict()["dry_run"] is True


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
        {"name": "lkt_tree_name_unique", "labelsOrTypes": ["LakatosTree"], "properties": ["name"]},
        {"name": "custom_node_name", "labelsOrTypes": ["LakatosNode"], "properties": ["name"]},
    ])

    assert report["ok"] is False
    assert "LakatosTree.name" in report["present"]
    assert "LakatosNode.name" in report["present"]
    assert {"OpenQuestion.(tree+name)", "ResearchEvent.id", "ResearchTradition.tradition_id"} <= set(report["missing"])
    assert report["migration_cypher"] == [
        "CREATE CONSTRAINT lkt_open_question_tree_name_key IF NOT EXISTS FOR (n:OpenQuestion) REQUIRE (n.tree, n.name) IS NODE KEY",
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
            {"name": "lkt_tree_name_unique", "labelsOrTypes": ["LakatosTree"], "properties": ["name"]},
        ],
    )

    report = app.neo4j_constraint_diagnostics()

    assert seen == ["SHOW CONSTRAINTS"]
    assert report["ok"] is False
    assert "LakatosTree.name" in report["present"]
