"""Gate-3 storage/application flow: T1 commit -> V7 verdict -> T2 sidecar."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from lakatos.layout import canonical_layout_blob
from lakatos.temporal import build_temporal_anchor
from lakatos.verdicts import prediction_content_sha, receipt_content_sha
from lakatos.write_cert import (
    did_key_encode,
    ed25519_public_key,
    ed25519_sign,
)
from server.contexts.tree.judgement_policy import build_receipt_fields
from server.contexts.tree.temporal_api import create_temporal_router
from server.contexts.tree.temporal_proof import TemporalProofInvalid
from server.contexts.tree.temporal_service import (
    TEMPORAL_SCOPE_SNAPSHOT_CYPHER,
    TemporalProofService,
)


_SECRETS = {
    name: bytes([value]) * 32
    for name, value in {
        "owner": 221,
        "producer": 222,
        "attestor": 223,
        "w1": 224,
        "w2": 225,
        "w3": 226,
    }.items()
}
_DIDS = {
    name: did_key_encode(ed25519_public_key(secret))
    for name, secret in _SECRETS.items()
}


def _anchors(names, receipt_sha, timestamp):
    return sorted(
        [
            build_temporal_anchor(
                _SECRETS[name], receipt_sha, timestamp, _DIDS[name]
            )
            for name in names
        ],
        key=lambda item: item["witness_did"],
    )


def _receipt_item(receipt):
    return {
        "receipt_element_id": f"receipt-{receipt['receipt_sha']}",
        "binding_element_id": f"binding-{receipt['receipt_sha']}",
        "binding_count": 1,
        "global_binding_count": 1,
        "physical_count": 1,
        "receipt": deepcopy(receipt),
    }


def _layout():
    value = {
        "layout_version": 1,
        "steps": [
            {
                "verb": "register_prediction",
                "pubkeys": [_DIDS["producer"]],
                "threshold": 1,
            },
            {
                "verb": "submit_test_result",
                "pubkeys": [_DIDS["attestor"]],
                "threshold": 1,
            },
        ],
        "disjoint_roles": [["register_prediction", "submit_test_result"]],
    }
    signature = ed25519_sign(
        _SECRETS["owner"], canonical_layout_blob(value)
    ).hex()
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ), signature


class _World:
    def __init__(self, *, tag: str = "n"):
        self.tag = tag
        layout, signature = _layout()
        prediction = {
            "receipt_kind": "prediction",
            "tree": "T",
            "tag": tag,
            "metric_name": "m",
            "direction": "lower",
            "baseline_value": 2.0,
            "noise_band": 0.0,
            "scale_type": "ratio",
            "novel_prediction": "",
            "novel_metric": None,
            "novel_direction": None,
            "novel_threshold": None,
            "judge_script_sha": "1" * 64,
            "closes_question": "",
            "credence": None,
            "baseline_lineage": "no_prior",
            "registered_at": "2026-08-02T00:59:00+00:00",
            "prev_receipt_sha": None,
            "anchor_bundle_sha256": "2" * 64,
            "history_payload_sha256": "3" * 64,
        }
        prediction["receipt_sha"] = prediction_content_sha(prediction)
        self.prediction_sha = prediction["receipt_sha"]
        self.now = datetime(2026, 8, 2, 1, 2, tzinfo=timezone.utc)
        self.state = {
            "tree": {
                "name": "T",
                "tree_incarnation_id": "incarnation-1",
                "research_layout": layout,
                "layout_owner_did": _DIDS["owner"],
                "layout_sig": signature,
                "attestor_dids": [_DIDS["attestor"]],
                "witness_dids": sorted(
                    [_DIDS["w1"], _DIDS["w2"], _DIDS["w3"]]
                ),
                "witness_threshold": 2,
            },
            "node": {
                "tag": tag,
                "current_receipt_sha": self.prediction_sha,
                "pred_receipt_sha": self.prediction_sha,
            },
            "receipts": [_receipt_item(prediction)],
            "commitments": [],
            "sidecars": [],
        }
        self.history = []

    def snapshot(self, tree, tag):
        assert (tree, tag) == ("T", self.tag)
        return deepcopy(self.state)

    def tx(self, operations):
        query, params = list(operations)[0]
        if "CREATE (commitment:PredictionTemporalCommitment" in query:
            assert "COMMITS_TO_PREDICTION" in query
            assert "$research_layout" in query
            record = {
                "commitment_sha256": params["commitment_sha"],
                "prediction_receipt_sha256": params["prediction_sha"],
                "authority_policy_sha256": params["policy_sha"],
                "tree_incarnation_id": params["incarnation"],
                "tree": params["tree"],
                "tag": params["tag"],
                "commitment_json": params["commitment_json"],
                "authority_policy_json": params["policy_json"],
                "created_at": params["ts"],
            }
            self.state["commitments"] = [{
                "commitment_element_id": "commitment-1",
                "binding_element_id": "commitment-binding-1",
                "binding_count": 1,
                "global_binding_count": 1,
                "physical_count": 1,
                "prediction_binding_count": 1,
                "global_prediction_binding_count": 1,
                "commitment": record,
                "outbox": {
                    "id": params["event_id"],
                    "tree": params["tree"],
                    "op": params["op"],
                    "node_tag": params["tag"],
                    "payload": params["payload"],
                    "status": "pending",
                    "created_at": params["ts"],
                    "reason": "prediction_temporal_commitment_intent",
                    "receipt_sha": params["prediction_sha"],
                    "applied_at": None,
                },
            }]
        elif "CREATE (sidecar:TemporalProofSidecar" in query:
            assert "USES_PREDICTION_COMMITMENT" in query
            assert "STARTS_AT" in query
            assert "ENDS_AT" in query
            assert "$research_layout" in query
            record = {
                "sidecar_sha256": params["sidecar_sha"],
                "verdict_receipt_sha256": params["verdict_sha"],
                "prediction_receipt_sha256": params["prediction_sha"],
                "prediction_temporal_commitment_sha256": params["commitment_sha"],
                "receipt_graph_sha256": params["graph_sha"],
                "authority_policy_sha256": params["policy_sha"],
                "tree_incarnation_id": params["incarnation"],
                "tree": params["tree"],
                "tag": params["tag"],
                "sidecar_json": params["sidecar_json"],
                "authority_policy_json": params["policy_json"],
                "created_at": params["ts"],
            }
            self.state["sidecars"] = [{
                "sidecar_element_id": "sidecar-1",
                "binding_element_id": "sidecar-binding-1",
                "binding_count": 1,
                "global_binding_count": 1,
                "physical_count": 1,
                "commitment_binding_count": 1,
                "global_commitment_binding_count": 1,
                "prediction_binding_count": 1,
                "global_prediction_binding_count": 1,
                "verdict_binding_count": 1,
                "global_verdict_binding_count": 1,
                "sidecar": record,
                "outbox": {
                    "id": params["event_id"],
                    "tree": params["tree"],
                    "op": params["op"],
                    "node_tag": params["tag"],
                    "payload": params["payload"],
                    "status": "pending",
                    "created_at": params["ts"],
                    "reason": "temporal_proof_sidecar_intent",
                    "receipt_sha": params["verdict_sha"],
                    "applied_at": None,
                },
            }]
        else:  # pragma: no cover - catches query drift loudly
            raise AssertionError(query)
        return [[{"ok": True}]]

    def hist(self, tree, op, tag, payload, *, event_id):
        self.history.append((tree, op, tag, deepcopy(payload), event_id))
        for key in ("commitments", "sidecars"):
            for item in self.state[key]:
                if item["outbox"]["id"] == event_id:
                    item["outbox"]["status"] = "applied"
                    item["outbox"]["applied_at"] = self.now.isoformat()
        return True

    def service(self):
        return TemporalProofService(
            kg=lambda *_a, **_k: [],
            ledger_kg_tx=self.tx,
            hist=self.hist,
            clock=lambda: self.now,
            snapshot_provider=self.snapshot,
        )

    def mint_verdict(self, commitment_sha=None):
        verdict = build_receipt_fields(
            tree="T",
            tag=self.tag,
            target_id=None,
            verdict="progressive",
            metric_name="m",
            metric_value=1.0,
            novel_confirmed=False,
            lakatos_status="progressive",
            judged_at="2026-08-02T01:02:30+00:00",
            judge_script_sha="1" * 64,
            prev_receipt_sha=self.prediction_sha,
            measurement_grade="server_regenerated",
            engine_rule_sha="4" * 64,
            prediction_temporal_commitment_sha256=commitment_sha,
        )
        verdict["receipt_sha"] = receipt_content_sha(verdict)
        self.state["receipts"].append(_receipt_item(verdict))
        self.state["node"]["current_receipt_sha"] = verdict["receipt_sha"]
        return verdict["receipt_sha"]


def test_t1_commitment_is_preverdict_immutable_and_idempotent():
    world = _World()
    service = world.service()
    anchors = _anchors(
        ("w1", "w2"), world.prediction_sha, "2026-08-02T01:00:00+00:00"
    )

    first = service.attach_prediction_commitment(
        "T",
        "n",
        anchors,
        expected_prediction_receipt_sha256=world.prediction_sha,
    )
    second = service.attach_prediction_commitment(
        "T",
        "n",
        anchors,
        expected_prediction_receipt_sha256=world.prediction_sha,
    )

    assert first["commitment_sha256"] == second["commitment_sha256"]
    assert service.verified_prediction_commitment(
        "T", "n"
    ).commitment_sha256 == first["commitment_sha256"]
    changed = _anchors(
        ("w1", "w2"), world.prediction_sha, "2026-08-02T01:00:01+00:00"
    )
    with pytest.raises(HTTPException, match="different prediction T1"):
        service.attach_prediction_commitment("T", "n", changed)


def test_t1_retry_rejects_outbox_receipt_pointer_splice():
    world = _World()
    service = world.service()
    anchors = _anchors(
        ("w1", "w2"), world.prediction_sha, "2026-08-02T01:00:00+00:00"
    )
    service.attach_prediction_commitment("T", "n", anchors)
    world.state["commitments"][0]["outbox"]["receipt_sha"] = "f" * 64

    with pytest.raises(HTTPException, match="outbox immutable binding"):
        service.attach_prediction_commitment("T", "n", anchors)


def test_t1_cannot_be_retrofitted_after_verdict():
    world = _World()
    world.mint_verdict()
    anchors = _anchors(
        ("w1", "w2"), world.prediction_sha, "2026-08-02T01:00:00+00:00"
    )

    with pytest.raises(HTTPException, match="before verdict"):
        world.service().attach_prediction_commitment("T", "n", anchors)


def test_v7_seal_then_t2_sidecar_reverifies_but_remains_gate3_l2():
    world = _World()
    service = world.service()
    t1 = service.attach_prediction_commitment(
        "T",
        "n",
        _anchors(
            ("w1", "w2"), world.prediction_sha, "2026-08-02T01:00:00+00:00"
        ),
    )
    verdict_sha = world.mint_verdict(t1["commitment_sha256"])
    world.now = datetime(2026, 8, 2, 1, 4, tzinfo=timezone.utc)
    t2 = _anchors(("w1", "w2"), verdict_sha, "2026-08-02T01:03:00+00:00")

    finalized = service.finalize_sidecar(
        "T",
        "n",
        t2,
        expected_verdict_receipt_sha256=verdict_sha,
    )
    retried = service.finalize_sidecar("T", "n", t2)
    readback = service.read_proof("T", "n")

    assert finalized["sidecar_sha256"] == retried["sidecar_sha256"]
    assert readback.component_ok is True
    assert readback.chain_ok is True
    assert readback.l3_eligible is False
    assert readback.reason == "independent_verifier_and_time_authority_pending"


def test_sidecar_rejects_unsealed_verdict_and_stale_read_fails_closed():
    world = _World()
    service = world.service()
    t1 = service.attach_prediction_commitment(
        "T",
        "n",
        _anchors(
            ("w1", "w2"), world.prediction_sha, "2026-08-02T01:00:00+00:00"
        ),
    )
    verdict_sha = world.mint_verdict()
    world.now = datetime(2026, 8, 2, 1, 4, tzinfo=timezone.utc)
    t2 = _anchors(("w1", "w2"), verdict_sha, "2026-08-02T01:03:00+00:00")
    with pytest.raises(TemporalProofInvalid):
        service.finalize_sidecar("T", "n", t2)

    # Repair the fixture with an honestly sealed verdict, then prove a later
    # head change immediately invalidates the old sidecar at read time.
    world = _World()
    service = world.service()
    t1 = service.attach_prediction_commitment(
        "T",
        "n",
        _anchors(
            ("w1", "w2"), world.prediction_sha, "2026-08-02T01:00:00+00:00"
        ),
    )
    verdict_sha = world.mint_verdict(t1["commitment_sha256"])
    world.now = datetime(2026, 8, 2, 1, 4, tzinfo=timezone.utc)
    service.finalize_sidecar(
        "T", "n", _anchors(("w1", "w2"), verdict_sha, "2026-08-02T01:03:00+00:00")
    )
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
    world.state["receipts"].append(_receipt_item(later))
    world.state["node"]["current_receipt_sha"] = later["receipt_sha"]

    stale = service.read_proof("T", "n")
    assert stale.component_ok is False
    assert stale.l3_eligible is False
    assert stale.reason == "temporal_proof_invalid"
    assert stale.chain_ok is True


def test_read_proofs_for_heads_batches_and_binds_observed_head_once():
    world = _World()
    calls = []

    def kg(query, **params):
        calls.append((query, params))
        assert query == TEMPORAL_SCOPE_SNAPSHOT_CYPHER
        return [{
            "requested_tag": "n",
            **deepcopy(world.state),
        }]

    service = TemporalProofService(
        kg=kg,
        ledger_kg_tx=world.tx,
        hist=world.hist,
        clock=lambda: world.now,
    )
    proofs = service.read_proofs_for_heads(
        "T",
        {"n": world.prediction_sha, "missing": None},
    )

    assert len(calls) == 1
    assert calls[0][1] == {"tree": "T", "tags": ["missing", "n"]}
    assert proofs["n"].chain_ok is True
    assert proofs["n"].reason == "prediction_commitment_missing"
    assert proofs["missing"].chain_ok is None


def test_batch_head_race_is_unknown_not_a_broken_chain():
    world = _World()
    service = TemporalProofService(
        kg=lambda _query, **_params: [{
            "requested_tag": "n",
            **deepcopy(world.state),
        }],
        ledger_kg_tx=world.tx,
        hist=world.hist,
        clock=lambda: world.now,
    )

    proof = service.read_proofs_for_heads("T", {"n": "f" * 64})["n"]

    assert proof.reason == "temporal_head_changed"
    assert proof.chain_ok is None


def test_temporal_api_translates_kernel_input_failure_to_422():
    class BrokenService:
        def read_proof(self, _tree, _tag):
            raise TemporalProofInvalid("non-canonical sidecar")

    app = FastAPI()
    app.include_router(create_temporal_router(lambda: BrokenService()))

    response = TestClient(app).get("/api/tree/T/node/n/temporal-proof")

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "temporal proof invalid: non-canonical sidecar"
    )
