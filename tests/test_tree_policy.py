"""Executable Lakatos tree policy tests.

# KG: seed-lkt-engine-policy-canonical-frontier-20260616
"""

from __future__ import annotations

from fastapi import HTTPException
import pytest

from server.api_schemas import NodeIn, ParentEdgeIn
from server.contexts.tree.mutations import TreeMutationService, TreeSpec
from server.contexts.tree.validation import LakatosPolicy, LakatosSemanticValidator
from server.contexts.tree.writer import TreeKgWriter


def test_policy_rejects_canonical_without_metric_and_provenance_before_write():
    wrote = []
    svc = TreeMutationService(
        writer=TreeKgWriter(lambda ops: wrote.append(ops)),
        validator=LakatosSemanticValidator(),
        hist=lambda *a: None,
    )
    spec = TreeSpec(
        name="T",
        hard_core="hc",
        frontier_rule="close real frontier questions before promotion",
        nodes=(
            NodeIn(tag="root"),
            NodeIn(tag="best", parent="root", verdict="canonical_stage"),
        ),
    )

    with pytest.raises(HTTPException) as exc:
        svc.upsert_tree(spec)

    assert exc.value.status_code == 422
    assert "canonical_metric_required" in exc.value.detail
    assert "canonical_provenance_required" in exc.value.detail
    assert wrote == []


def test_policy_rejects_inferred_parent_edge_without_evidence_ref():
    validator = LakatosSemanticValidator()
    tree = {"nodes": [{"tag": "root"}]}

    with pytest.raises(HTTPException) as exc:
        validator.validate_node_create(
            "T",
            tree,
            NodeIn(tag="child", parent_edges=[ParentEdgeIn(tag="root", inferred=True)]),
        )

    assert exc.value.status_code == 422
    assert "parent_edge_provenance_required" in exc.value.detail


def test_policy_rejects_tree_without_hard_core_and_frontier_rule_before_write():
    wrote = []
    svc = TreeMutationService(
        writer=TreeKgWriter(lambda ops: wrote.append(ops)),
        validator=LakatosSemanticValidator(),
        hist=lambda *a: None,
    )

    with pytest.raises(HTTPException) as exc:
        svc.upsert_tree(TreeSpec(name="T", nodes=(NodeIn(tag="root"),)))

    assert exc.value.status_code == 422
    assert "hard_core_required" in exc.value.detail
    assert "frontier_rule_required" in exc.value.detail
    assert wrote == []


def test_legacy_warn_policy_reports_findings_without_blocking_old_shape():
    validator = LakatosSemanticValidator(policy=LakatosPolicy.legacy_warn())
    result = validator.validate_node_create_result(
        "T",
        {"nodes": [{"tag": "root"}]},
        NodeIn(tag="best", parent="root", verdict="canonical_stage"),
    )

    assert [edge.tag for edge in result.parent_edges] == ["root"]
    assert {finding.code for finding in result.policy_findings} == {
        "canonical_metric_required",
        "canonical_provenance_required",
    }
    assert all(finding.severity == "warn" for finding in result.policy_findings)
