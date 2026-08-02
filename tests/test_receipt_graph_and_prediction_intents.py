"""Receipt ancestry and prediction-history authority fail closed."""

from __future__ import annotations

import copy
import hashlib

import pytest

from lakatos import temporal as temporal_mod
from lakatos.io.reconcile import canonical_history_payload
from lakatos.verdicts import (
    RECEIPT_FIELDS,
    prediction_content_sha,
    prediction_history_payload_sha,
    receipt_content_sha,
)
from server.contexts.tree.prediction_intents import (
    PredictionIntentError,
    validate_prediction_register_intent,
)
from server.contexts.tree.receipt_chain import (
    ReceiptGraphError,
    validate_receipt_graph,
)
from server.contexts.tree.schemas import PredictionIn
from server.storage_contract import _diagnose_neo_outbox_projection


TS = "2026-08-02T00:00:00+00:00"


def _verdict_receipt(*, previous=None, verdict="progressive"):
    fields = {key: None for key in RECEIPT_FIELDS}
    fields.update(
        tree="T",
        tag="n",
        verdict=verdict,
        verdict_source="scripted",
        judged_at=TS,
        prev_receipt_sha=previous,
    )
    sha = receipt_content_sha(fields)
    return {"receipt_sha": sha, **fields}


def _graph(receipts, *, head=None, prediction=None):
    if head is None and receipts:
        head = receipts[-1]["receipt_sha"]
    node = {
        "node_element_id": "node-n",
        "tree": "T",
        "tag": "n",
        "current_receipt_sha": head,
        "pred_receipt_sha": prediction,
        "receipts": [
            {"receipt_element_id": f"receipt-{index}", "receipt": receipt}
            for index, receipt in enumerate(receipts)
        ],
    }
    identities = [
        {
            "receipt_element_id": f"receipt-{index}",
            "receipt_sha": receipt["receipt_sha"],
            "receipt": receipt,
            "all_bindings": 1,
            "owners": [{
                "node_element_id": "node-n", "tree": "T", "tag": "n",
            }],
        }
        for index, receipt in enumerate(receipts)
    ]
    return [node], identities


def test_receipt_graph_accepts_one_complete_head_to_genesis_chain():
    genesis = _verdict_receipt()
    head = _verdict_receipt(previous=genesis["receipt_sha"], verdict="rejected")
    nodes, identities = _graph([genesis, head])

    index = validate_receipt_graph(nodes, identities)

    assert index.ancestors_by_scope[("T", "n")] == frozenset({
        genesis["receipt_sha"], head["receipt_sha"],
    })


@pytest.mark.parametrize("corruption", ["missing_parent", "side_branch", "orphan", "tamper"])
def test_receipt_graph_rejects_every_non_chain_storage_shape(corruption):
    genesis = _verdict_receipt()
    head = _verdict_receipt(previous=genesis["receipt_sha"], verdict="rejected")
    receipts = [genesis, head]
    nodes, identities = _graph(receipts)
    if corruption == "missing_parent":
        broken = _verdict_receipt(previous="f" * 64, verdict="rejected")
        nodes, identities = _graph([broken])
    elif corruption == "side_branch":
        branch = _verdict_receipt(previous=genesis["receipt_sha"], verdict="partial")
        nodes, identities = _graph([genesis, head, branch], head=head["receipt_sha"])
    elif corruption == "orphan":
        orphan = _verdict_receipt(verdict="partial")
        identities.append({
            "receipt_element_id": "receipt-orphan",
            "receipt_sha": orphan["receipt_sha"],
            "receipt": orphan,
            "all_bindings": 0,
            "owners": [],
        })
    else:
        nodes[0]["receipts"][0]["receipt"]["verdict"] = "partial"
        identities[0]["receipt"]["verdict"] = "partial"

    with pytest.raises(ReceiptGraphError):
        validate_receipt_graph(nodes, identities)


def _prediction_fixture(*, status="applied"):
    payload = PredictionIn(
        metric_name="latency",
        direction="lower",
        baseline_value=10.0,
        noise_band=0.5,
    ).model_dump()
    bundle = {
        "schema": "lakatotree-prediction-anchor-bundle/v1",
        "spec_digest": temporal_mod.spec_digest({
            key: value
            for key, value in payload.items()
            if key not in ("write_cert", "temporal_anchor", "temporal_anchors")
        }),
        "witness_dids": [],
        "witness_threshold": 1,
        "anchors": [],
    }
    bundle_json = canonical_history_payload(bundle)
    receipt_fields = {
        "receipt_kind": "prediction",
        "tree": "T",
        "tag": "n",
        "baseline_lineage": "no_prior",
        "registered_at": TS,
        "prev_receipt_sha": None,
        "anchor_bundle_sha256": hashlib.sha256(
            bundle_json.encode("utf-8")
        ).hexdigest(),
        "anchor_bundle_json": bundle_json,
        "history_payload_sha256": prediction_history_payload_sha(payload),
        **payload,
    }
    receipt_sha = prediction_content_sha(receipt_fields)
    receipt = {"receipt_sha": receipt_sha, **receipt_fields}
    event_id = f"ob-prediction-register-{receipt_sha}"
    outbox = {
        "id": event_id,
        "tree": "T",
        "op": "prediction_register",
        "node_tag": "n",
        "payload": canonical_history_payload(payload),
        "status": status,
        "created_at": TS,
        "reason": "prediction_register_commit_intent",
        "applied_at": TS if status == "applied" else None,
        "adopted_by": None,
        "adopted_at": None,
        "receipt_sha": receipt_sha,
        "causal_group": None,
        "causal_index": None,
        "request_sha256": None,
        "demoted_tag": None,
        "demoted_receipt_sha": None,
    }
    current = {
        "current_receipt_sha": receipt_sha,
        "pred_receipt_sha": receipt_sha,
        "pred_registered_at": TS,
        "baseline_lineage": "no_prior",
        "pred_metric": payload["metric_name"],
        "pred_direction": payload["direction"],
        "pred_baseline": payload["baseline_value"],
        "pred_noise_band": payload["noise_band"],
        "pred_scale_type": payload["scale_type"],
        "pred_novel": payload["novel_prediction"],
        "pred_closes": payload["closes_question"],
        "pred_novel_metric": payload["novel_metric"],
        "pred_novel_direction": payload["novel_direction"],
        "pred_novel_threshold": payload["novel_threshold"],
        "pred_script_sha": payload["judge_script_sha"],
        "pred_credence": payload["credence"],
        "novel_registered": False,
        "pred_question_bound": True,
    }
    return payload, receipt, outbox, current


def test_prediction_intent_v3_seals_complete_history_receipt_and_node_cache():
    _payload, receipt, outbox, current = _prediction_fixture()

    validated = validate_prediction_register_intent(
        tree="T", tag="n", receipt_sha=receipt["receipt_sha"],
        receipt=receipt, current=current, outbox=outbox,
        require_current_effect=False,
    )

    assert validated["metric_name"] == "latency"


@pytest.mark.parametrize("corruption", ["payload", "receipt", "cache", "event_id", "bundle"])
def test_prediction_intent_v3_rejects_every_semantic_divergence(corruption):
    _payload, receipt, outbox, current = _prediction_fixture(status="pending")
    if corruption == "payload":
        changed = copy.deepcopy(_payload)
        changed["write_cert"] = {
            "signer_did": "did:key:forged",
            "signature": "00",
            "issued_at": TS,
            "command": {
                "tree": "T", "tag": "n", "command_version": "v4",
            },
        }
        outbox["payload"] = canonical_history_payload(changed)
    elif corruption == "receipt":
        receipt["history_payload_sha256"] = "f" * 64
    elif corruption == "cache":
        current["pred_baseline"] = 999.0
    elif corruption == "event_id":
        outbox["id"] = f"ob-prediction-register-{'f' * 64}"
    else:
        receipt["anchor_bundle_json"] = canonical_history_payload({"forged": True})

    with pytest.raises(PredictionIntentError):
        validate_prediction_register_intent(
            tree="T", tag="n", receipt_sha=receipt["receipt_sha"],
            receipt=receipt, current=current, outbox=outbox,
            require_current_effect=True,
        )


def _neo_constraints():
    return [
        {
            "name": name,
            "type": "UNIQUENESS",
            "entityType": "NODE",
            "labelsOrTypes": [label],
            "properties": [prop],
        }
        for name, label, prop in (
            ("lkt_outbox_id_unique", "OutboxEntry", "id"),
            ("lkt_argument_id_unique", "LakatosArgument", "id"),
            ("lkt_runtime_writer_lease_name_unique", "RuntimeWriterLease", "name"),
        )
    ]


def test_storage_audit_cannot_launder_forged_prediction_via_matching_pg_row():
    _payload, receipt, outbox, current = _prediction_fixture()
    nodes, receipt_identities = _graph(
        [receipt], head=receipt["receipt_sha"], prediction=receipt["receipt_sha"]
    )
    projection = {
        "history_id": 1,
        "tree": "T",
        "op": "prediction_register",
        "node_tag": "n",
        "payload": outbox["payload"],
        "event_id": outbox["id"],
        "stable_event_id": None,
    }

    forged = _diagnose_neo_outbox_projection(
        _neo_constraints(),
        [{"id": outbox["id"], "copies": 1}],
        [outbox],
        [projection],
        prediction_authority_rows=[],
        receipt_chain_node_rows=nodes,
        receipt_identity_rows=receipt_identities,
    )
    assert "neo4j.outbox.prediction_intent_v3" in forged["failures"]

    authority = {
        "event_id": outbox["id"],
        "outbox": outbox,
        "trees": 1,
        "nodes": 1,
        "bindings": 1,
        "receipts": 1,
        "current": current,
        "receipt": receipt,
    }
    exact = _diagnose_neo_outbox_projection(
        _neo_constraints(),
        [{"id": outbox["id"], "copies": 1}],
        [outbox],
        [projection],
        prediction_authority_rows=[authority],
        receipt_chain_node_rows=nodes,
        receipt_identity_rows=receipt_identities,
    )
    assert "neo4j.outbox.prediction_intent_v3" not in exact["failures"]
    assert "neo4j.receipt_chain" not in exact["failures"]
