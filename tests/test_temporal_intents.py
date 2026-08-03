"""Durable temporal intents cannot downgrade into generic outbox replay."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from lakatos.verdicts import receipt_content_sha
from server.contexts.tree.judgement_policy import build_receipt_fields
from server.contexts.tree.receipt_chain import validate_receipt_graph
from server.contexts.tree.temporal_intents import (
    TemporalIntentError,
    classify_temporal_intent,
    validate_prediction_temporal_commitment_intent,
    validate_temporal_proof_sidecar_intent,
)
from server.storage_contract import _diagnose_neo_outbox_projection
from tests.test_storage_contract import _neo_constraints
from tests.test_temporal_proof_service import _World, _anchors


def _graph_rows(world: _World):
    bound = []
    identities = []
    for item in world.state["receipts"]:
        receipt = deepcopy(item["receipt"])
        element_id = item["receipt_element_id"]
        bound.append({
            "receipt_element_id": element_id,
            "receipt": receipt,
        })
        identities.append({
            "receipt_element_id": element_id,
            "receipt_sha": receipt["receipt_sha"],
            "receipt": receipt,
            "all_bindings": 1,
            "owners": [{
                "node_element_id": "node-1",
                "tree": "T",
                "tag": "n",
            }],
        })
    nodes = [{
            "node_element_id": "node-1",
            "tree": "T",
            "tag": "n",
            "tree_incarnation_id": "incarnation-1",
            "current_receipt_sha": world.state["node"]["current_receipt_sha"],
            "pred_receipt_sha": world.state["node"]["pred_receipt_sha"],
            "receipts": bound,
        }]
    return nodes, identities


def _chain(world: _World):
    nodes, identities = _graph_rows(world)
    return validate_receipt_graph(nodes, identities)


def _commitment_counts():
    return {
        **{key: 1 for key in (
            "outbox_copies", "trees", "node_bindings", "nodes",
            "local_bindings", "adjunct_nodes", "global_bindings",
            "sha_copies", "target_copies", "endpoint_bindings",
            "global_endpoint_bindings",
        )},
        "expected_label": "PredictionTemporalCommitment",
        "adjunct_labels": ["PredictionTemporalCommitment"],
        "relationship_property_keys": [{}, {}],
    }


def _sidecar_counts():
    return {
        **{key: 1 for key in (
            "outbox_copies", "trees", "node_bindings", "nodes",
            "local_bindings", "adjunct_nodes", "global_bindings",
            "sha_copies", "target_copies", "commitment_bindings",
            "global_commitment_bindings", "prediction_bindings",
            "global_prediction_bindings", "verdict_bindings",
            "global_verdict_bindings",
        )},
        "expected_label": "TemporalProofSidecar",
        "adjunct_labels": ["TemporalProofSidecar"],
        "relationship_property_keys": [{}, {}, {}, {}],
    }


def _attach_t1(world: _World):
    return world.service().attach_prediction_commitment(
        "T",
        "n",
        _anchors(
            ("w1", "w2"), world.prediction_sha,
            "2026-08-02T01:00:00+00:00",
        ),
    )


def _commitment_args(world: _World, *, pending: bool):
    item = deepcopy(world.state["commitments"][0])
    if pending:
        item["outbox"]["status"] = "pending"
        item["outbox"]["applied_at"] = None
    return {
        "outbox": item["outbox"],
        "tree_record": deepcopy(world.state["tree"]),
        "node_record": deepcopy(world.state["node"]),
        "commitment_record": item["commitment"],
        "identity_counts": _commitment_counts(),
        "chain_index": _chain(world),
        "require_current_effect": pending,
    }


def _sidecar_args(world: _World, *, pending: bool):
    sidecar_item = deepcopy(world.state["sidecars"][0])
    commitment_item = deepcopy(world.state["commitments"][0])
    if pending:
        sidecar_item["outbox"]["status"] = "pending"
        sidecar_item["outbox"]["applied_at"] = None
    return {
        "outbox": sidecar_item["outbox"],
        "tree_record": deepcopy(world.state["tree"]),
        "node_record": deepcopy(world.state["node"]),
        "sidecar_record": sidecar_item["sidecar"],
        "identity_counts": _sidecar_counts(),
        "commitment_outbox": commitment_item["outbox"],
        "commitment_record": commitment_item["commitment"],
        "commitment_identity_counts": _commitment_counts(),
        "chain_index": _chain(world),
        "require_current_effect": pending,
    }


def _finalized_world():
    world = _World()
    t1 = _attach_t1(world)
    verdict_sha = world.mint_verdict(t1["commitment_sha256"])
    world.now = datetime(2026, 8, 2, 1, 4, tzinfo=timezone.utc)
    world.service().finalize_sidecar(
        "T",
        "n",
        _anchors(("w1", "w2"), verdict_sha, "2026-08-02T01:03:00+00:00"),
    )
    return world, verdict_sha


def test_pending_commitment_is_exact_projection_authority():
    world = _World()
    _attach_t1(world)

    validated = validate_prediction_temporal_commitment_intent(
        **_commitment_args(world, pending=True)
    )

    assert validated.kind == "commitment"
    assert validated.receipt_sha256 == world.prediction_sha


@pytest.mark.parametrize("field", ["id", "op", "reason", "tree", "node_tag", "receipt_sha"])
def test_commitment_envelope_splice_fails_closed(field):
    world = _World()
    _attach_t1(world)
    args = _commitment_args(world, pending=True)
    args["outbox"][field] = "temporal_proof_sidecar"

    with pytest.raises(TemporalIntentError):
        validate_prediction_temporal_commitment_intent(**args)


def test_temporal_classification_protects_broad_markers_and_mixed_rows():
    assert classify_temporal_intent({"id": "ob-prediction-temporal-not-a-sha"}) == "commitment"
    assert classify_temporal_intent({"reason": "temporal_proof_sidecar_intent"}) == "sidecar"
    with pytest.raises(TemporalIntentError, match="mixes"):
        classify_temporal_intent({
            "id": "ob-prediction-temporal-x",
            "op": "temporal_proof_sidecar",
        })


def test_applied_commitment_remains_valid_after_policy_rotation_and_verdict():
    world = _World()
    t1 = _attach_t1(world)
    world.mint_verdict(t1["commitment_sha256"])
    args = _commitment_args(world, pending=False)
    args["tree_record"]["witness_threshold"] = 3

    validated = validate_prediction_temporal_commitment_intent(**args)

    assert validated.object_sha256 == t1["commitment_sha256"]


def test_pending_sidecar_requires_applied_commitment_and_exact_topology():
    world, _verdict_sha = _finalized_world()
    args = _sidecar_args(world, pending=True)
    validated = validate_temporal_proof_sidecar_intent(**args)
    assert validated.kind == "sidecar"

    pending_dependency = deepcopy(args)
    pending_dependency["commitment_outbox"] = deepcopy(args["commitment_outbox"])
    pending_dependency["commitment_outbox"]["status"] = "pending"
    pending_dependency["commitment_outbox"]["applied_at"] = None
    with pytest.raises(TemporalIntentError, match="not projected"):
        validate_temporal_proof_sidecar_intent(**pending_dependency)

    bad_count = deepcopy(args)
    bad_count["identity_counts"]["global_verdict_bindings"] = 2
    with pytest.raises(TemporalIntentError, match="physical identity"):
        validate_temporal_proof_sidecar_intent(**bad_count)


def test_applied_sidecar_uses_historical_prefix_after_later_head():
    world, verdict_sha = _finalized_world()
    later = build_receipt_fields(
        tree="T",
        tag="n",
        target_id=None,
        verdict="former_canonical",
        metric_name=None,
        metric_value=None,
        novel_confirmed=None,
        lakatos_status=None,
        judged_at="2026-08-02T01:05:00+00:00",
        judge_script_sha=None,
        prev_receipt_sha=verdict_sha,
        measurement_grade=None,
        engine_rule_sha="5" * 64,
    )
    later["receipt_sha"] = receipt_content_sha(later)
    world.state["receipts"].append({
        "receipt_element_id": f"receipt-{later['receipt_sha']}",
        "binding_element_id": f"binding-{later['receipt_sha']}",
        "binding_count": 1,
        "global_binding_count": 1,
        "physical_count": 1,
        "receipt": later,
    })
    world.state["node"]["current_receipt_sha"] = later["receipt_sha"]
    args = _sidecar_args(world, pending=False)
    args["tree_record"]["witness_threshold"] = 3

    validated = validate_temporal_proof_sidecar_intent(**args)

    assert validated.receipt_sha256 == verdict_sha


def test_storage_contract_global_temporal_scan_rejects_false_green_identity():
    world = _World()
    _attach_t1(world)
    args = _commitment_args(world, pending=True)
    counts = args["identity_counts"]
    authority_row = {
        **{key: value for key, value in counts.items()
           if key not in {"expected_label"}},
        "event_id": args["outbox"]["id"],
        "outbox": args["outbox"],
        "tree_record": args["tree_record"],
        "node_record": args["node_record"],
        "adjunct_record": args["commitment_record"],
    }
    node_rows, identity_rows = _graph_rows(world)
    report = _diagnose_neo_outbox_projection(
        _neo_constraints(),
        [{"id": args["outbox"]["id"], "copies": 1}],
        [args["outbox"]],
        prediction_temporal_rows=[authority_row],
        temporal_sidecar_rows=[],
        receipt_chain_node_rows=node_rows,
        receipt_identity_rows=identity_rows,
    )
    assert "neo4j.prediction_temporal_commitment.identity" not in report["failures"]
    assert report["details"]["prediction_temporal_nodes_checked"] == 1

    forged = deepcopy(authority_row)
    forged["sha_copies"] = 2
    report = _diagnose_neo_outbox_projection(
        _neo_constraints(),
        [{"id": args["outbox"]["id"], "copies": 1}],
        [args["outbox"]],
        prediction_temporal_rows=[forged],
        temporal_sidecar_rows=[],
        receipt_chain_node_rows=node_rows,
        receipt_identity_rows=identity_rows,
    )
    assert "neo4j.prediction_temporal_commitment.identity" in report["failures"]
