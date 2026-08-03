"""Gate 3: frozen receipt-bound two-ended temporal sidecar kernel."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from lakatos.temporal import build_temporal_anchor, two_ended_temporal_sidecar_sha256
from lakatos.verdicts import prediction_content_sha, receipt_content_sha
from lakatos.write_cert import did_key_encode, ed25519_public_key
from server.contexts.tree.judgement_policy import build_receipt_fields
from server.contexts.tree.receipt_chain import receipt_graph_prefix_sha256
from server.contexts.tree.temporal_proof import (
    TemporalProofInvalid,
    build_prediction_temporal_commitment,
    build_temporal_authority_policy,
    build_two_ended_sidecar,
    prediction_temporal_commitment_sha256,
    verify_prediction_temporal_commitment,
    verify_two_ended_temporal_sidecar,
)


_SECRETS = {name: bytes([value]) * 32 for name, value in {
    "w1": 201,
    "w2": 202,
    "w3": 203,
    "producer": 204,
    "attestor": 205,
}.items()}
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


def _case(
    *,
    threshold=2,
    t1_names=("w1", "w2"),
    t2_names=("w1", "w2"),
    t1_time="2026-08-02T01:00:00+00:00",
    t2_time="2026-08-02T01:01:00+00:00",
    witnesses=("w1", "w2", "w3"),
):
    tree, tag = "T", "n"
    prediction = {
        "receipt_kind": "prediction",
        "tree": tree,
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
    prediction_sha = prediction_content_sha(prediction)
    prediction["receipt_sha"] = prediction_sha
    policy = build_temporal_authority_policy(
        threshold=threshold,
        witness_allowlist=[_DIDS[name] for name in witnesses],
        producer_dids=[_DIDS["producer"]],
        attestor_dids=[_DIDS["attestor"]],
        evidence_refs=["kg://T/research-layout"],
    )
    prediction_anchors = _anchors(t1_names, prediction_sha, t1_time)
    commitment = build_prediction_temporal_commitment(
        tree_incarnation_id="incarnation-1",
        tree=tree,
        tag=tag,
        prediction_receipt_sha256=prediction_sha,
        authority_policy=policy,
        prediction_anchors=prediction_anchors,
    )
    commitment_sha = prediction_temporal_commitment_sha256(commitment)
    verdict = build_receipt_fields(
        tree=tree,
        tag=tag,
        target_id=None,
        verdict="progressive",
        metric_name="m",
        metric_value=1.0,
        novel_confirmed=False,
        lakatos_status="progressive",
        judged_at="2026-08-02T01:00:30+00:00",
        judge_script_sha="1" * 64,
        prev_receipt_sha=prediction_sha,
        measurement_grade="server_regenerated",
        engine_rule_sha="4" * 64,
        prediction_temporal_commitment_sha256=commitment_sha,
    )
    verdict_sha = receipt_content_sha(verdict)
    verdict["receipt_sha"] = verdict_sha
    chain = (prediction_sha, verdict_sha)
    graph_sha = receipt_graph_prefix_sha256(
        tree_incarnation_id="incarnation-1",
        tree=tree,
        tag=tag,
        prediction_receipt_sha256=prediction_sha,
        verdict_receipt_sha256=verdict_sha,
        chain=chain,
    )
    sidecar = build_two_ended_sidecar(
        authority_policy=policy,
        prediction_receipt_sha256=prediction_sha,
        verdict_receipt_sha256=verdict_sha,
        receipt_graph_sha256=graph_sha,
        prediction_anchors=prediction_anchors,
        verdict_anchors=_anchors(t2_names, verdict_sha, t2_time),
    )
    return sidecar, {
        "stored_sidecar_sha256": two_ended_temporal_sidecar_sha256(sidecar),
        "stored_authority_policy": policy,
        "current_authority_policy": policy,
        "tree": tree,
        "tag": tag,
        "tree_incarnation_id": "incarnation-1",
        "current_head_sha256": verdict_sha,
        "chain": chain,
        "receipt_by_sha": {
            prediction_sha: prediction,
            verdict_sha: verdict,
        },
        "evaluated_at": datetime(2026, 8, 2, 1, 2, tzinfo=timezone.utc),
    }


def _verify(sidecar, kwargs):
    return verify_two_ended_temporal_sidecar(sidecar, **kwargs)


def test_receipt_bound_two_ended_component_is_valid_but_gate4_keeps_l3_closed():
    sidecar, kwargs = _case()

    proof = _verify(sidecar, kwargs)

    assert proof.component_ok is True
    assert proof.chain_ok is True
    assert proof.l3_eligible is False
    assert proof.reason == "independent_verifier_and_time_authority_pending"
    assert proof.prediction_receipt_sha256 == sidecar["prediction_receipt_sha256"]
    assert proof.verdict_receipt_sha256 == sidecar["verdict_receipt_sha256"]
    assert proof.prediction_temporal_commitment_sha256 == kwargs[
        "receipt_by_sha"
    ][sidecar["verdict_receipt_sha256"]][
        "prediction_temporal_commitment_sha256"
    ]


def test_prediction_t1_commitment_requires_prediction_to_still_be_current():
    sidecar, kwargs = _case()
    prediction_sha = sidecar["prediction_receipt_sha256"]
    policy = kwargs["stored_authority_policy"]
    commitment = build_prediction_temporal_commitment(
        tree_incarnation_id=kwargs["tree_incarnation_id"],
        tree=kwargs["tree"],
        tag=kwargs["tag"],
        prediction_receipt_sha256=prediction_sha,
        authority_policy=policy,
        prediction_anchors=sidecar["prediction_anchors"],
    )
    commitment_sha = prediction_temporal_commitment_sha256(commitment)

    verified = verify_prediction_temporal_commitment(
        commitment,
        stored_commitment_sha256=commitment_sha,
        authority_policy=policy,
        tree_incarnation_id=kwargs["tree_incarnation_id"],
        tree=kwargs["tree"],
        tag=kwargs["tag"],
        prediction_receipt_sha256=prediction_sha,
        prediction_receipt=kwargs["receipt_by_sha"][prediction_sha],
        current_head_sha256=prediction_sha,
        evaluated_at=datetime(2026, 8, 2, 1, 0, 10, tzinfo=timezone.utc),
    )
    assert verified.commitment_sha256 == commitment_sha

    with pytest.raises(TemporalProofInvalid, match="post-verdict"):
        verify_prediction_temporal_commitment(
            commitment,
            stored_commitment_sha256=commitment_sha,
            authority_policy=policy,
            tree_incarnation_id=kwargs["tree_incarnation_id"],
            tree=kwargs["tree"],
            tag=kwargs["tag"],
            prediction_receipt_sha256=prediction_sha,
            prediction_receipt=kwargs["receipt_by_sha"][prediction_sha],
            current_head_sha256=sidecar["verdict_receipt_sha256"],
            evaluated_at=datetime(2026, 8, 2, 1, 1, tzinfo=timezone.utc),
        )


@pytest.mark.parametrize(
    "case_kwargs, message",
    [
        ({"threshold": 1}, "threshold"),
        ({"t1_names": ("w1", "w1")}, "unique witnesses"),
        ({"t2_names": ("w1", "w3")}, "signer sets"),
        ({"t2_time": "2026-08-02T01:00:00+00:00"}, "strict T1 < T2"),
        ({"t2_time": "2026-08-02T01:03:00+00:00"}, "after the evaluation"),
    ],
)
def test_quorum_identity_order_and_time_fail_closed(case_kwargs, message):
    if case_kwargs.get("threshold") == 1:
        with pytest.raises(TemporalProofInvalid, match=message):
            _case(**case_kwargs)
        return
    sidecar, kwargs = _case(**case_kwargs)
    with pytest.raises(TemporalProofInvalid, match=message):
        _verify(sidecar, kwargs)


def test_wrong_endpoint_signature_is_rejected_even_when_sidecar_is_rehashed():
    sidecar, kwargs = _case()
    changed = deepcopy(sidecar)
    changed["prediction_anchors"] = _anchors(
        ("w1", "w2"), changed["verdict_receipt_sha256"],
        "2026-08-02T01:00:00+00:00",
    )
    kwargs["stored_sidecar_sha256"] = two_ended_temporal_sidecar_sha256(changed)

    with pytest.raises(TemporalProofInvalid, match="invalid member"):
        _verify(changed, kwargs)


def test_policy_receipt_graph_and_current_head_splices_are_rejected():
    sidecar, kwargs = _case()

    drifted_policy = deepcopy(kwargs)
    policy = deepcopy(kwargs["current_authority_policy"])
    policy["evidence_refs"] = ["kg://T/changed-layout"]
    drifted_policy["current_authority_policy"] = policy
    with pytest.raises(TemporalProofInvalid, match="current authority policy"):
        _verify(sidecar, drifted_policy)

    graph_splice = deepcopy(sidecar)
    graph_splice["receipt_graph_sha256"] = "f" * 64
    graph_kwargs = deepcopy(kwargs)
    graph_kwargs["stored_sidecar_sha256"] = two_ended_temporal_sidecar_sha256(
        graph_splice
    )
    with pytest.raises(TemporalProofInvalid, match="receipt-graph"):
        _verify(graph_splice, graph_kwargs)

    stale = deepcopy(kwargs)
    stale["current_head_sha256"] = sidecar["prediction_receipt_sha256"]
    with pytest.raises(TemporalProofInvalid, match="stale"):
        _verify(sidecar, stale)


def test_witness_role_overlap_and_receipt_tamper_are_rejected():
    with pytest.raises(TemporalProofInvalid, match="overlap"):
        build_temporal_authority_policy(
            threshold=2,
            witness_allowlist=[_DIDS["w1"], _DIDS["w2"]],
            producer_dids=[_DIDS["w1"]],
            attestor_dids=[_DIDS["attestor"]],
            evidence_refs=["kg://T/research-layout"],
        )

    sidecar, kwargs = _case()
    tampered = deepcopy(kwargs)
    verdict_sha = sidecar["verdict_receipt_sha256"]
    tampered["receipt_by_sha"][verdict_sha]["metric_value"] = 99.0
    with pytest.raises(TemporalProofInvalid, match="content does not rederive"):
        _verify(sidecar, tampered)
