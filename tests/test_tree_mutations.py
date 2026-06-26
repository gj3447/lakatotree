"""Tree mutation engine tests.

# KG: seed-lkt-engine-mutation-writer-20260616, seed-lkt-engine-mutation-service-20260616
"""

from __future__ import annotations

from fastapi import HTTPException
import pytest

from server.api_schemas import NodeIn, ParentEdgeIn, QuestionIn
from server.contexts.tree.mutations import TreeMutationService, TreeSpec
from server.contexts.tree.validation import LakatosSemanticValidator
from server.contexts.tree.writer import TreeKgWriter


def test_writer_bulk_upsert_nodes_chunks_and_preserves_all_tags():
    txs = []
    writer = TreeKgWriter(lambda ops: txs.append(ops) or [[]], chunk_size=2)
    nodes = [NodeIn(tag=f"n{i}") for i in range(5)]

    summary = writer.upsert_nodes("T", nodes)

    assert summary.rows == 5
    assert summary.tx_count == 3
    rows = [row for tx in txs for _, params in tx for row in params["rows"]]
    assert [row["tag"] for row in rows] == ["n0", "n1", "n2", "n3", "n4"]
    assert all("UNWIND $rows AS row" in tx[0][0] for tx in txs)
    assert all("MERGE (e:LakatosNode:PrismExperiment" in tx[0][0] for tx in txs)


def test_writer_single_node_keeps_node_and_edges_in_one_tx():
    txs = []
    writer = TreeKgWriter(lambda ops: txs.append(ops) or [[{"ok": True}] for _ in ops])

    writer.add_node(
        "T",
        NodeIn(tag="child", parent_edges=[ParentEdgeIn(tag="root", inferred=True)]),
        [ParentEdgeIn(tag="root", inferred=True)],
    )

    assert len(txs) == 1
    assert len(txs[0]) == 2
    assert "MERGE (t)-[:HAS_NODE]->(e)" in txs[0][0][0]
    assert "MERGE (e)-[r:BRANCHED_FROM]->(p)" in txs[0][1][0]


def test_mutation_service_rejects_missing_parent_before_bulk_write():
    wrote = []
    svc = TreeMutationService(
        writer=TreeKgWriter(lambda ops: wrote.append(ops)),
        validator=LakatosSemanticValidator(),
        hist=lambda *a: None,
    )
    spec = TreeSpec(name="T", nodes=(NodeIn(tag="child", parent="ghost"),))

    with pytest.raises(HTTPException) as exc:
        svc.upsert_tree(spec)

    assert exc.value.status_code == 400
    assert wrote == []


def test_mutation_service_upsert_tree_writes_tree_nodes_edges_and_questions():
    txs = []
    svc = TreeMutationService(
        writer=TreeKgWriter(lambda ops: txs.append(ops) or [[]], chunk_size=2),
        validator=LakatosSemanticValidator(),
        hist=lambda *a: None,
    )
    spec = TreeSpec(
        name="T",
        title="Tree",
        hard_core="hc",
        frontier_rule="close measured frontier questions",
        nodes=(
            NodeIn(tag="root"),
            NodeIn(
                tag="child",
                parent="root",
                # prom-honesty/1: 노드 업서트는 행정/구조 어휘만 — 스크립트 판결(progressive)은 judge 전용.
                #   (스크립트 판결 거부는 test_prom_honesty_node_gating.py 가 별도로 고정.)
                verdict="canonical_stage",
                result_path="runs/child.json",
                metric_name="p95",
                metric_value=0.4,
                metric_scope="lot",
            ),
        ),
        questions=(QuestionIn(qname="q1", body="why"),),
    )

    out = svc.upsert_tree(spec)

    assert out["ok"] is True
    assert out["nodes"] == 2
    assert out["questions"] == 1
    cyphers = [cypher for tx in txs for cypher, _ in tx]
    assert any("MERGE (t:LakatosTree {name:$tree})" in q for q in cyphers)
    assert any("MERGE (e:LakatosNode:PrismExperiment" in q for q in cyphers)
    assert any("MERGE (e)-[r:BRANCHED_FROM]->(p)" in q for q in cyphers)
    assert any("MERGE (qn:OpenQuestion {name:row.qname})" in q for q in cyphers)
