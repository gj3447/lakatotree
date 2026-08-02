"""Standalone Gate-4 two-ended temporal verifier tests (engine imports forbidden)."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from c1verify import _ed25519 as ed
from c1verify.artifact import temporal_artifact_sha256
from c1verify.jcs import jcs
from c1verify.receipts import prediction_content_sha, receipt_content_sha
from c1verify.temporal_sidecar import (
    BATCH_REQUEST_SCHEMA,
    PROOF_REQUEST_SCHEMA,
    RECEIPT_TRANSPORT_FIELDS,
    TIME_AUTHORITY_ATTESTATION_SCHEMA,
    TemporalSidecarError,
    authority_policy_sha256,
    commitment_sha256,
    receipt_graph_sha256,
    sidecar_sha256,
    time_authority_signed_bytes,
    verify_batch_bytes,
)


def _point_compress(point) -> bytes:
    inverse = pow(point[2], ed._P - 2, ed._P)
    x = point[0] * inverse % ed._P
    y = point[1] * inverse % ed._P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _public(secret: bytes) -> bytes:
    digest = ed._sha512(secret)
    scalar = int.from_bytes(digest[:32], "little")
    scalar &= (1 << 254) - 8
    scalar |= 1 << 254
    return _point_compress(ed._point_mul(scalar, ed._B))


def _sign(secret: bytes, message: bytes) -> bytes:
    digest = ed._sha512(secret)
    scalar = int.from_bytes(digest[:32], "little")
    scalar &= (1 << 254) - 8
    scalar |= 1 << 254
    public = _point_compress(ed._point_mul(scalar, ed._B))
    nonce = int.from_bytes(ed._sha512(digest[32:] + message), "little") % ed._L
    encoded_r = _point_compress(ed._point_mul(nonce, ed._B))
    challenge = int.from_bytes(
        ed._sha512(encoded_r + public + message), "little"
    ) % ed._L
    return encoded_r + ((nonce + challenge * scalar) % ed._L).to_bytes(32, "little")


_SECRETS = {name: bytes([value]) * 32 for name, value in {
    "producer": 101,
    "attestor": 102,
    "w1": 103,
    "w2": 104,
    "time": 105,
}.items()}
_DIDS = {name: ed.did_key_encode(_public(secret)) for name, secret in _SECRETS.items()}
_FIXED_EVALUATED_AT = datetime(2026, 8, 2, 0, 5, tzinfo=timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _empty_receipt() -> dict:
    return {field: None for field in RECEIPT_TRANSPORT_FIELDS}


def _anchor(name: str, receipt_sha: str, timestamp: str) -> dict:
    digest = hashlib.sha256(
        b"lakatotree-temporal-anchor/v1\n" + receipt_sha.encode("utf-8")
    ).hexdigest()
    signed = b"lakatotree-temporal-anchor/v1\n" + jcs({
        "digest": digest,
        "gen_time": timestamp,
    })
    return {
        "witness_did": _DIDS[name],
        "digest": digest,
        "gen_time": timestamp,
        "signature": _sign(_SECRETS[name], signed).hex(),
        "channel": "ed25519-witness",
    }


def _fixture(
    *, evaluated_at: datetime = _FIXED_EVALUATED_AT,
) -> tuple[dict, str, str]:
    artifact_sha = temporal_artifact_sha256()
    python_sha = hashlib.sha256(
        Path(sys.executable).resolve(strict=True).read_bytes()
    ).hexdigest()
    policy = {
        "schema_version": "lakatotree-temporal-authority-policy/v1",
        "threshold": 2,
        "witness_allowlist": sorted([_DIDS["w1"], _DIDS["w2"]]),
        "producer_dids": [_DIDS["producer"]],
        "attestor_dids": [_DIDS["attestor"]],
        "endpoint_signer_rule": "same-authority-set",
        "evidence_refs": [
            "kg://LakatosTree/T/research-layout",
            "kg://LakatosTree/T/temporal-witness-policy",
        ],
    }
    policy_sha = authority_policy_sha256(policy)
    prediction = _empty_receipt()
    prediction.update(
        receipt_kind="prediction",
        tree="T",
        tag="n",
        metric_name="m",
        direction="higher",
        baseline_value=0.0,
        noise_band=0.0,
        scale_type="ratio",
        novel_prediction=False,
        closes_question=False,
        credence=0.5,
        registered_at="2026-08-02T00:00:00+00:00",
        prev_receipt_sha=None,
    )
    prediction["receipt_sha"] = prediction_content_sha(prediction)
    t1 = sorted([
        _anchor("w1", prediction["receipt_sha"], _iso(evaluated_at - timedelta(minutes=4))),
        _anchor("w2", prediction["receipt_sha"], _iso(evaluated_at - timedelta(minutes=4) + timedelta(seconds=1))),
    ], key=lambda item: item["witness_did"])
    commitment = {
        "schema_version": "lakatotree-prediction-temporal-commitment/v1",
        "tree_incarnation_id": "incarnation-1",
        "tree": "T",
        "tag": "n",
        "prediction_receipt_sha256": prediction["receipt_sha"],
        "authority_policy_sha256": policy_sha,
        "prediction_anchors": t1,
    }
    commitment_sha = commitment_sha256(commitment)
    verdict = _empty_receipt()
    verdict.update(
        tree="T",
        tag="n",
        target_id="n",
        verdict="progressive",
        verdict_source="scripted",
        metric_name="m",
        metric_value=1.0,
        novel_confirmed=False,
        lakatos_status="progressive",
        judged_at="2026-08-02T00:02:00+00:00",
        judge_script_sha="1" * 64,
        prev_receipt_sha=prediction["receipt_sha"],
        measurement_grade="server_regenerated",
        engine_rule_sha="2" * 64,
        comment_sha="3" * 64,
        replay_status="verified",
        replay_reason="exact",
        regenerated_metric=1.0,
        judge_script_path="/sealed/judge.py",
        result_path="/sealed/result.json",
        result_sha256="4" * 64,
        measurement_lock_sha="5" * 64,
        source_script_path="/source/judge.py",
        source_result_path="/source/result.json",
        history_payload_sha256="6" * 64,
        prediction_temporal_commitment_sha256=commitment_sha,
    )
    verdict["receipt_sha"] = receipt_content_sha(verdict)
    t2 = sorted([
        _anchor("w1", verdict["receipt_sha"], _iso(evaluated_at - timedelta(minutes=2))),
        _anchor("w2", verdict["receipt_sha"], _iso(evaluated_at - timedelta(minutes=2) + timedelta(seconds=1))),
    ], key=lambda item: item["witness_did"])
    chain = [prediction["receipt_sha"], verdict["receipt_sha"]]
    graph_sha = receipt_graph_sha256(
        tree_incarnation_id="incarnation-1",
        tree="T",
        tag="n",
        prediction_receipt_sha256=prediction["receipt_sha"],
        verdict_receipt_sha256=verdict["receipt_sha"],
        chain=chain,
    )
    sidecar = {
        "schema_version": "lakatotree-two-ended-temporal-sidecar/v1",
        "authority_policy_sha256": policy_sha,
        "threshold": 2,
        "witness_allowlist": policy["witness_allowlist"],
        "prediction_receipt_sha256": prediction["receipt_sha"],
        "verdict_receipt_sha256": verdict["receipt_sha"],
        "receipt_graph_sha256": graph_sha,
        "prediction_anchors": t1,
        "verdict_anchors": t2,
    }
    stored_sidecar_sha = sidecar_sha256(sidecar)
    request_id = hashlib.sha256(
        b"lakatotree-independent-temporal-request/v1\0" + jcs({
            "tree_incarnation_id": "incarnation-1",
            "tree": "T",
            "tag": "n",
            "verdict_receipt_sha256": verdict["receipt_sha"],
        })
    ).hexdigest()
    challenge_sha = "7" * 64
    attestation = {
        "schema_version": TIME_AUTHORITY_ATTESTATION_SCHEMA,
        "challenge_sha256": challenge_sha,
        "request_id": request_id,
        "signer_did": _DIDS["time"],
        "tree_incarnation_id": "incarnation-1",
        "tree": "T",
        "tag": "n",
        "authority_policy_sha256": policy_sha,
        "sidecar_sha256": stored_sidecar_sha,
        "receipt_graph_sha256": graph_sha,
        "prediction_receipt_sha256": prediction["receipt_sha"],
        "verdict_receipt_sha256": verdict["receipt_sha"],
        "prediction_temporal_commitment_sha256": commitment_sha,
        "witness_dids": sorted([_DIDS["w1"], _DIDS["w2"]]),
        "threshold": 2,
        "verifier_artifact_sha256": artifact_sha,
        "verifier_python_sha256": python_sha,
        "observed_at": _iso(evaluated_at - timedelta(seconds=30)),
        "valid_until": _iso(evaluated_at + timedelta(minutes=1)),
        "signature": None,
    }
    attestation["signature"] = _sign(
        _SECRETS["time"], time_authority_signed_bytes(attestation)
    ).hex()
    proof = {
        "schema_version": PROOF_REQUEST_SCHEMA,
        "request_id": request_id,
        "tree_incarnation_id": "incarnation-1",
        "tree": "T",
        "tag": "n",
        "current_head_sha256": verdict["receipt_sha"],
        "stored_sidecar_sha256": stored_sidecar_sha,
        "authority_policy": policy,
        "sidecar": sidecar,
        "chain": chain,
        "receipts": [prediction, verdict],
        "time_authority_attestation": attestation,
    }
    batch = {
        "schema_version": BATCH_REQUEST_SCHEMA,
        "expected_time_authority_did": _DIDS["time"],
        "verifier_artifact_sha256": artifact_sha,
        "verifier_python_sha256": python_sha,
        "authority_challenge_sha256": challenge_sha,
        "proofs": [proof],
    }
    return batch, artifact_sha, python_sha


def _verify(batch: dict) -> dict:
    _fixture_batch, artifact_sha, python_sha = _fixture()
    return verify_batch_bytes(
        jcs(batch),
        actual_verifier_artifact_sha256=artifact_sha,
        actual_verifier_python_sha256=python_sha,
        evaluated_at=_FIXED_EVALUATED_AT,
    )


def test_two_ended_temporal_bundle_rederives_and_authorizes_l3():
    batch, artifact_sha, python_sha = _fixture()
    report = verify_batch_bytes(
        jcs(batch),
        actual_verifier_artifact_sha256=artifact_sha,
        actual_verifier_python_sha256=python_sha,
        evaluated_at=_FIXED_EVALUATED_AT,
    )

    assert report["status"] == "VERIFIED"
    result = report["results"][0]
    assert result["component_ok"] is True
    assert result["l3_eligible"] is True
    assert result["prediction_temporal_commitment_sha256"] == (
        batch["proofs"][0]["time_authority_attestation"]
        ["prediction_temporal_commitment_sha256"]
    )
    assert result["independent_verifier"] == "sha256:" + artifact_sha
    assert result["time_authority"].startswith("did-key-sha256:")


@pytest.mark.parametrize("mutation", [
    "receipt_reorder",
    "sidecar_splice",
    "v7_commitment_splice",
    "time_signature",
    "time_signer_pin",
    "future_anchor",
    "request_id_splice",
])
def test_splice_and_authority_attacks_reject(mutation):
    batch, _artifact_sha, _python_sha = _fixture()
    proof = batch["proofs"][0]
    if mutation == "receipt_reorder":
        proof["chain"].reverse()
        proof["receipts"].reverse()
    elif mutation == "sidecar_splice":
        proof["sidecar"]["receipt_graph_sha256"] = "0" * 64
    elif mutation == "v7_commitment_splice":
        proof["receipts"][-1]["prediction_temporal_commitment_sha256"] = "0" * 64
    elif mutation == "time_signature":
        proof["time_authority_attestation"]["signature"] = "0" * 128
    elif mutation == "time_signer_pin":
        batch["expected_time_authority_did"] = _DIDS["w1"]
    elif mutation == "future_anchor":
        proof["time_authority_attestation"]["observed_at"] = (
            "2026-08-02T00:02:00+00:00"
        )
    elif mutation == "request_id_splice":
        proof["request_id"] = "0" * 64

    report = _verify(batch)

    assert report["status"] == "REJECTED"
    assert report["results"][0]["l3_eligible"] is False


def test_v7_causal_seal_check_is_reached_after_consistent_rehashing():
    batch, _artifact_sha, _python_sha = _fixture()
    proof = batch["proofs"][0]
    verdict = proof["receipts"][-1]
    verdict["prediction_temporal_commitment_sha256"] = "0" * 64
    verdict["receipt_sha"] = receipt_content_sha(verdict)
    verdict_sha = verdict["receipt_sha"]
    proof["chain"][-1] = verdict_sha
    proof["current_head_sha256"] = verdict_sha
    proof["sidecar"]["verdict_receipt_sha256"] = verdict_sha
    proof["sidecar"]["verdict_anchors"] = sorted([
        _anchor("w1", verdict_sha, "2026-08-02T00:03:00+00:00"),
        _anchor("w2", verdict_sha, "2026-08-02T00:03:01+00:00"),
    ], key=lambda item: item["witness_did"])
    proof["sidecar"]["receipt_graph_sha256"] = receipt_graph_sha256(
        tree_incarnation_id=proof["tree_incarnation_id"],
        tree=proof["tree"],
        tag=proof["tag"],
        prediction_receipt_sha256=proof["sidecar"]["prediction_receipt_sha256"],
        verdict_receipt_sha256=verdict_sha,
        chain=proof["chain"],
    )
    proof["stored_sidecar_sha256"] = sidecar_sha256(proof["sidecar"])
    proof["request_id"] = hashlib.sha256(
        b"lakatotree-independent-temporal-request/v1\0" + jcs({
            "tree_incarnation_id": proof["tree_incarnation_id"],
            "tree": proof["tree"],
            "tag": proof["tag"],
            "verdict_receipt_sha256": verdict_sha,
        })
    ).hexdigest()
    attestation = proof["time_authority_attestation"]
    attestation.update({
        "request_id": proof["request_id"],
        "sidecar_sha256": proof["stored_sidecar_sha256"],
        "receipt_graph_sha256": proof["sidecar"]["receipt_graph_sha256"],
        "verdict_receipt_sha256": verdict_sha,
    })
    attestation["signature"] = _sign(
        _SECRETS["time"], time_authority_signed_bytes(attestation)
    ).hex()

    report = _verify(batch)

    assert report["status"] == "REJECTED"
    assert report["results"][0]["reason_code"] == "verdict.v7_commitment_seal"


def test_caller_cannot_backdate_or_supply_the_c1_evaluation_clock():
    batch, artifact_sha, python_sha = _fixture()
    expired = verify_batch_bytes(
        jcs(batch),
        actual_verifier_artifact_sha256=artifact_sha,
        actual_verifier_python_sha256=python_sha,
        evaluated_at=_FIXED_EVALUATED_AT + timedelta(minutes=2),
    )
    assert expired["status"] == "REJECTED"
    assert expired["results"][0]["reason_code"] == "time_authority.validity_window"

    batch["evaluated_at"] = _FIXED_EVALUATED_AT.isoformat()
    with pytest.raises(TemporalSidecarError, match="batch.field_set"):
        verify_batch_bytes(
            jcs(batch),
            actual_verifier_artifact_sha256=artifact_sha,
            actual_verifier_python_sha256=python_sha,
            evaluated_at=_FIXED_EVALUATED_AT,
        )


def test_duplicate_key_and_noncanonical_input_fail_before_proof_evaluation():
    batch, artifact_sha, python_sha = _fixture()
    raw = jcs(batch)
    noncanonical = b" " + raw
    with pytest.raises(TemporalSidecarError):
        verify_batch_bytes(
            noncanonical,
            actual_verifier_artifact_sha256=artifact_sha,
            actual_verifier_python_sha256=python_sha,
            evaluated_at=_FIXED_EVALUATED_AT,
        )

    duplicate = raw[:-1] + b',"schema_version":"duplicate"}'
    with pytest.raises(TemporalSidecarError):
        verify_batch_bytes(
            duplicate,
            actual_verifier_artifact_sha256=artifact_sha,
            actual_verifier_python_sha256=python_sha,
            evaluated_at=_FIXED_EVALUATED_AT,
        )


def test_verifier_artifact_or_interpreter_pin_mismatch_is_batch_error():
    batch, artifact_sha, python_sha = _fixture()
    with pytest.raises(TemporalSidecarError, match="verifier_artifact_identity"):
        verify_batch_bytes(
            jcs(batch),
            actual_verifier_artifact_sha256="0" * 64,
            actual_verifier_python_sha256=python_sha,
            evaluated_at=_FIXED_EVALUATED_AT,
        )
    with pytest.raises(TemporalSidecarError, match="verifier_artifact_identity"):
        verify_batch_bytes(
            jcs(batch),
            actual_verifier_artifact_sha256=artifact_sha,
            actual_verifier_python_sha256="0" * 64,
            evaluated_at=_FIXED_EVALUATED_AT,
        )


def test_isolated_cli_process_accepts_honest_and_rejects_spliced_bundle():
    batch, _artifact_sha, _python_sha = _fixture(
        evaluated_at=datetime.now(timezone.utc)
    )
    cli = Path(__file__).resolve().parents[1] / "temporal_cli.py"

    accepted = subprocess.run(
        [sys.executable, "-I", "-S", "-B", str(cli)],
        input=jcs(batch),
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert accepted.returncode == 0 and accepted.stderr == b""
    accepted_report = json.loads(accepted.stdout)
    assert accepted_report["status"] == "VERIFIED"
    assert accepted_report["input_sha256"] == hashlib.sha256(jcs(batch)).hexdigest()

    batch["proofs"][0]["receipts"][-1]["verdict"] = "rejected"
    rejected = subprocess.run(
        [sys.executable, "-I", "-S", "-B", str(cli)],
        input=jcs(batch),
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert rejected.returncode == 1 and rejected.stderr == b""
    assert json.loads(rejected.stdout)["status"] == "REJECTED"
