"""Standalone, engine-import-forbidden verification of frozen two-ended proofs.

The verifier consumes only canonical JSON, re-derives every receipt byte, the
genesis-to-verdict prefix, authority policy, T1 commitment, V7 causal seal and
both witness quorums, then verifies a separately administered time-authority
attestation over the exact proof and verifier artifact identities.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from typing import Any, Mapping

if __package__:  # Package import and isolated direct-script execution.
    from ._ed25519 import (
        KeyTypeError,
        did_key_decode,
        did_key_encode,
        ed25519_public_key_is_strict,
        ed25519_verify,
    )
    from .jcs import JcsError, jcs, parse_canonical
    from .receipts import (
        PREDICTION_RECEIPT_FIELDS_V3,
        RECEIPT_FIELDS_V7,
        prediction_content_sha,
        receipt_content_sha,
    )
else:  # pragma: no cover - subprocess tests exercise this path
    from _ed25519 import (
        KeyTypeError,
        did_key_decode,
        did_key_encode,
        ed25519_public_key_is_strict,
        ed25519_verify,
    )
    from jcs import JcsError, jcs, parse_canonical
    from receipts import (
        PREDICTION_RECEIPT_FIELDS_V3,
        RECEIPT_FIELDS_V7,
        prediction_content_sha,
        receipt_content_sha,
    )


BATCH_REQUEST_SCHEMA = "lakatotree-c1-two-ended-temporal-batch/v1"
PROOF_REQUEST_SCHEMA = "lakatotree-c1-two-ended-temporal-proof/v1"
BATCH_REPORT_SCHEMA = "lakatotree-c1-two-ended-temporal-report/v1"
TIME_AUTHORITY_ATTESTATION_SCHEMA = (
    "lakatotree-independent-time-authority-attestation/v1"
)
TEMPORAL_AUTHORITY_POLICY_SCHEMA = "lakatotree-temporal-authority-policy/v1"
TWO_ENDED_SIDECAR_SCHEMA = "lakatotree-two-ended-temporal-sidecar/v1"
PREDICTION_COMMITMENT_SCHEMA = (
    "lakatotree-prediction-temporal-commitment/v1"
)
RECEIPT_GRAPH_PREFIX_SCHEMA = "lakatotree-receipt-graph-prefix/v1"

TEMPORAL_AUTHORITY_POLICY_DOMAIN = b"lakatotree-temporal-authority-policy/v1\0"
TWO_ENDED_SIDECAR_DOMAIN = b"lakatotree-two-ended-temporal-sidecar/v1\0"
PREDICTION_COMMITMENT_DOMAIN = b"lakatotree-prediction-temporal-commitment/v1\0"
RECEIPT_GRAPH_PREFIX_DOMAIN = b"lakatotree-receipt-graph-prefix/v1\0"
TEMPORAL_ANCHOR_DOMAIN = b"lakatotree-temporal-anchor/v1\n"
TIME_AUTHORITY_ATTESTATION_DOMAIN = (
    b"lakatotree-independent-time-authority-attestation/v1\0"
)
TEMPORAL_REQUEST_ID_DOMAIN = b"lakatotree-independent-temporal-request/v1\0"

MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_PROOFS = 64
MAX_RECEIPTS = 256
MAX_ANCHORS = 32
MAX_AUTHORITY_LIFETIME = timedelta(minutes=5)

_HEX = frozenset("0123456789abcdef")
_BATCH_KEYS = frozenset({
    "schema_version",
    "expected_time_authority_did",
    "verifier_artifact_sha256",
    "verifier_python_sha256",
    "authority_challenge_sha256",
    "proofs",
})
_PROOF_KEYS = frozenset({
    "schema_version",
    "request_id",
    "tree_incarnation_id",
    "tree",
    "tag",
    "current_head_sha256",
    "stored_sidecar_sha256",
    "authority_policy",
    "sidecar",
    "chain",
    "receipts",
    "time_authority_attestation",
})
_POLICY_KEYS = frozenset({
    "schema_version",
    "threshold",
    "witness_allowlist",
    "producer_dids",
    "attestor_dids",
    "endpoint_signer_rule",
    "evidence_refs",
})
_SIDECAR_KEYS = frozenset({
    "schema_version",
    "authority_policy_sha256",
    "threshold",
    "witness_allowlist",
    "prediction_receipt_sha256",
    "verdict_receipt_sha256",
    "receipt_graph_sha256",
    "prediction_anchors",
    "verdict_anchors",
})
_ANCHOR_KEYS = frozenset({
    "witness_did", "digest", "gen_time", "signature", "channel",
})
_ATTESTATION_BODY_KEYS = frozenset({
    "schema_version",
    "challenge_sha256",
    "request_id",
    "signer_did",
    "tree_incarnation_id",
    "tree",
    "tag",
    "authority_policy_sha256",
    "sidecar_sha256",
    "receipt_graph_sha256",
    "prediction_receipt_sha256",
    "verdict_receipt_sha256",
    "prediction_temporal_commitment_sha256",
    "witness_dids",
    "threshold",
    "verifier_artifact_sha256",
    "verifier_python_sha256",
    "observed_at",
    "valid_until",
})
_ATTESTATION_KEYS = _ATTESTATION_BODY_KEYS | {"signature"}
RECEIPT_TRANSPORT_FIELDS = tuple(sorted(
    set(RECEIPT_FIELDS_V7)
    | set(PREDICTION_RECEIPT_FIELDS_V3)
    | {"receipt_sha", "receipt_kind"}
))
_RECEIPT_TRANSPORT_KEYS = frozenset(RECEIPT_TRANSPORT_FIELDS)


class TemporalSidecarError(ValueError):
    """Any ambiguous, malformed, stale or cryptographically invalid proof."""


def _mapping(value: Any, *, path: str, keys: frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise TemporalSidecarError(f"{path}.field_set")
    return value


def _sha(value: Any, *, path: str) -> str:
    if not (
        isinstance(value, str)
        and len(value) == 64
        and all(char in _HEX for char in value)
    ):
        raise TemporalSidecarError(f"{path}.sha256")
    return value


def _text(value: Any, *, path: str, maximum: int = 512) -> str:
    if not (
        isinstance(value, str)
        and value
        and value == value.strip()
        and len(value) <= maximum
        and "\x00" not in value
    ):
        raise TemporalSidecarError(f"{path}.text")
    return value


def _time(value: Any, *, path: str) -> datetime:
    rendered = _text(value, path=path, maximum=64)
    try:
        parsed = datetime.fromisoformat(rendered.replace("Z", "+00:00"))
    except (ValueError, OverflowError, TypeError) as exc:
        raise TemporalSidecarError(f"{path}.timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TemporalSidecarError(f"{path}.timezone")
    return parsed.astimezone(timezone.utc)


def _did(value: Any, *, path: str) -> tuple[str, bytes]:
    rendered = _text(value, path=path, maximum=256)
    try:
        public = did_key_decode(rendered)
    except (KeyTypeError, ValueError, TypeError, AttributeError) as exc:
        raise TemporalSidecarError(f"{path}.did_key") from exc
    if (
        did_key_encode(public) != rendered
        or not ed25519_public_key_is_strict(public)
    ):
        raise TemporalSidecarError(f"{path}.did_key")
    return rendered, public


def _did_list(value: Any, *, path: str, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise TemporalSidecarError(f"{path}.list")
    if len(value) > MAX_ANCHORS:
        raise TemporalSidecarError(f"{path}.oversized")
    rendered = tuple(_did(item, path=f"{path}[{index}]")[0]
                     for index, item in enumerate(value))
    if rendered != tuple(sorted(rendered)) or len(set(rendered)) != len(rendered):
        raise TemporalSidecarError(f"{path}.canonical_order")
    return rendered


def _domain_sha(domain: bytes, value: Mapping[str, Any]) -> str:
    return hashlib.sha256(domain + jcs(dict(value))).hexdigest()


def authority_policy_sha256(policy: Mapping[str, Any]) -> str:
    return _domain_sha(TEMPORAL_AUTHORITY_POLICY_DOMAIN, policy)


def sidecar_sha256(sidecar: Mapping[str, Any]) -> str:
    return _domain_sha(TWO_ENDED_SIDECAR_DOMAIN, sidecar)


def commitment_sha256(commitment: Mapping[str, Any]) -> str:
    return _domain_sha(PREDICTION_COMMITMENT_DOMAIN, commitment)


def receipt_graph_sha256(
    *,
    tree_incarnation_id: str,
    tree: str,
    tag: str,
    prediction_receipt_sha256: str,
    verdict_receipt_sha256: str,
    chain: list[str],
) -> tuple[str, str]:
    body = {
        "schema_version": RECEIPT_GRAPH_PREFIX_SCHEMA,
        "tree_incarnation_id": tree_incarnation_id,
        "tree": tree,
        "tag": tag,
        "prediction_receipt_sha256": prediction_receipt_sha256,
        "verdict_receipt_sha256": verdict_receipt_sha256,
        "chain": chain,
    }
    return _domain_sha(RECEIPT_GRAPH_PREFIX_DOMAIN, body)


def time_authority_signed_bytes(attestation: Mapping[str, Any]) -> bytes:
    body = dict(attestation)
    body.pop("signature", None)
    _mapping(body, path="time_authority_attestation.body", keys=_ATTESTATION_BODY_KEYS)
    return TIME_AUTHORITY_ATTESTATION_DOMAIN + jcs(body)


def _policy(value: Any) -> tuple[dict[str, Any], tuple[str, ...], int]:
    policy = _mapping(value, path="authority_policy", keys=_POLICY_KEYS)
    if policy.get("schema_version") != TEMPORAL_AUTHORITY_POLICY_SCHEMA:
        raise TemporalSidecarError("authority_policy.schema")
    witnesses = _did_list(policy.get("witness_allowlist"), path="authority_policy.witnesses")
    producers = _did_list(policy.get("producer_dids"), path="authority_policy.producers")
    attestors = _did_list(policy.get("attestor_dids"), path="authority_policy.attestors")
    threshold = policy.get("threshold")
    if type(threshold) is not int or threshold < 2 or threshold > len(witnesses):
        raise TemporalSidecarError("authority_policy.threshold")
    if set(producers) & set(attestors):
        raise TemporalSidecarError("authority_policy.role_overlap")
    if set(witnesses) & (set(producers) | set(attestors)):
        raise TemporalSidecarError("authority_policy.witness_role_overlap")
    if policy.get("endpoint_signer_rule") != "same-authority-set":
        raise TemporalSidecarError("authority_policy.endpoint_rule")
    refs = policy.get("evidence_refs")
    if not (
        isinstance(refs, list)
        and refs
        and all(isinstance(item, str) and item and item == item.strip() for item in refs)
        and refs == sorted(refs)
        and len(refs) == len(set(refs))
    ):
        raise TemporalSidecarError("authority_policy.evidence_refs")
    return policy, witnesses, threshold


def _sidecar(value: Any) -> dict[str, Any]:
    sidecar = _mapping(value, path="sidecar", keys=_SIDECAR_KEYS)
    if sidecar.get("schema_version") != TWO_ENDED_SIDECAR_SCHEMA:
        raise TemporalSidecarError("sidecar.schema")
    for field in (
        "authority_policy_sha256",
        "prediction_receipt_sha256",
        "verdict_receipt_sha256",
        "receipt_graph_sha256",
    ):
        _sha(sidecar.get(field), path=f"sidecar.{field}")
    _did_list(sidecar.get("witness_allowlist"), path="sidecar.witnesses")
    if type(sidecar.get("threshold")) is not int:
        raise TemporalSidecarError("sidecar.threshold")
    return sidecar


def _anchor_set(
    value: Any,
    *,
    path: str,
    receipt_sha: str,
    witnesses: tuple[str, ...],
    threshold: int,
) -> tuple[tuple[str, ...], tuple[datetime, ...], tuple[str, ...]]:
    if not isinstance(value, list) or not value or len(value) > MAX_ANCHORS:
        raise TemporalSidecarError(f"{path}.list")
    submitted = []
    parsed_times = []
    rendered_times = []
    wanted_digest = hashlib.sha256(
        TEMPORAL_ANCHOR_DOMAIN + receipt_sha.encode("utf-8")
    ).hexdigest()
    for index, raw in enumerate(value):
        anchor = _mapping(raw, path=f"{path}[{index}]", keys=_ANCHOR_KEYS)
        witness, public = _did(anchor.get("witness_did"), path=f"{path}[{index}].witness")
        if witness not in witnesses or anchor.get("digest") != wanted_digest:
            raise TemporalSidecarError(f"{path}[{index}].binding")
        rendered = _text(anchor.get("gen_time"), path=f"{path}[{index}].gen_time", maximum=64)
        parsed = _time(rendered, path=f"{path}[{index}].gen_time")
        signature = anchor.get("signature")
        if not (
            isinstance(signature, str)
            and len(signature) == 128
            and all(char in _HEX for char in signature)
            and anchor.get("channel") == "ed25519-witness"
        ):
            raise TemporalSidecarError(f"{path}[{index}].signature_shape")
        signed = TEMPORAL_ANCHOR_DOMAIN + jcs({
            "digest": wanted_digest,
            "gen_time": rendered,
        })
        if not ed25519_verify(public, signed, bytes.fromhex(signature)):
            raise TemporalSidecarError(f"{path}[{index}].signature")
        submitted.append(witness)
        parsed_times.append(parsed)
        rendered_times.append(rendered)
    if submitted != sorted(submitted) or len(set(submitted)) != len(submitted):
        raise TemporalSidecarError(f"{path}.canonical_signers")
    if len(submitted) < threshold:
        raise TemporalSidecarError(f"{path}.threshold")
    return tuple(submitted), tuple(parsed_times), tuple(rendered_times)


def _receipt_prefix(
    proof: Mapping[str, Any],
    *,
    tree: str,
    tag: str,
    prediction_sha: str,
    verdict_sha: str,
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    chain = proof.get("chain")
    receipts = proof.get("receipts")
    if (
        not isinstance(chain, list)
        or not chain
        or len(chain) > MAX_RECEIPTS
        or len(set(chain)) != len(chain)
        or not isinstance(receipts, list)
        or len(receipts) != len(chain)
    ):
        raise TemporalSidecarError("receipt_prefix.cardinality")
    for index, sha in enumerate(chain):
        _sha(sha, path=f"chain[{index}]")
    by_sha: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(receipts):
        receipt = _mapping(
            raw,
            path=f"receipts[{index}]",
            keys=_RECEIPT_TRANSPORT_KEYS,
        )
        receipt_sha = _sha(receipt.get("receipt_sha"), path=f"receipts[{index}].receipt_sha")
        if receipt_sha in by_sha:
            raise TemporalSidecarError("receipt_prefix.duplicate_receipt")
        is_prediction = receipt.get("receipt_kind") == "prediction"
        if not is_prediction and receipt.get("receipt_kind") is not None:
            raise TemporalSidecarError("receipt_prefix.receipt_kind")
        derived = (
            prediction_content_sha(receipt)
            if is_prediction
            else receipt_content_sha(receipt)
        )
        if derived != receipt_sha:
            raise TemporalSidecarError("receipt_prefix.content_sha")
        by_sha[receipt_sha] = receipt
    if set(by_sha) != set(chain):
        raise TemporalSidecarError("receipt_prefix.side_branch_or_missing")
    if chain[-1] != verdict_sha or proof.get("current_head_sha256") != verdict_sha:
        raise TemporalSidecarError("receipt_prefix.stale_head")
    if prediction_sha not in by_sha:
        raise TemporalSidecarError("receipt_prefix.prediction_missing")
    previous = None
    for receipt_sha in chain:
        receipt = by_sha[receipt_sha]
        if not (
            receipt.get("tree") == tree
            and receipt.get("tag") == tag
            and receipt.get("prev_receipt_sha") == previous
        ):
            raise TemporalSidecarError("receipt_prefix.scope_or_link")
        previous = receipt_sha
    if by_sha[prediction_sha].get("receipt_kind") != "prediction":
        raise TemporalSidecarError("receipt_prefix.prediction_kind")
    if by_sha[verdict_sha].get("receipt_kind") is not None:
        raise TemporalSidecarError("receipt_prefix.verdict_kind")
    return chain, by_sha


def _verify_attestation(
    value: Any,
    *,
    expected_signer_did: str,
    challenge_sha: str,
    evaluated_at: datetime,
    policy: Mapping[str, Any],
    bindings: Mapping[str, Any],
    witnesses: tuple[str, ...],
    threshold: int,
    t2_times: tuple[datetime, ...],
    verifier_artifact_sha: str,
    verifier_python_sha: str,
) -> str:
    attestation = _mapping(
        value,
        path="time_authority_attestation",
        keys=_ATTESTATION_KEYS,
    )
    if attestation.get("schema_version") != TIME_AUTHORITY_ATTESTATION_SCHEMA:
        raise TemporalSidecarError("time_authority.schema")
    signer, public = _did(attestation.get("signer_did"), path="time_authority.signer")
    if signer != expected_signer_did:
        raise TemporalSidecarError("time_authority.signer_pin")
    roles = (
        set(policy["witness_allowlist"])
        | set(policy["producer_dids"])
        | set(policy["attestor_dids"])
    )
    if signer in roles:
        raise TemporalSidecarError("time_authority.role_overlap")
    expected = {
        "challenge_sha256": challenge_sha,
        "request_id": bindings["request_id"],
        "tree_incarnation_id": bindings["tree_incarnation_id"],
        "tree": bindings["tree"],
        "tag": bindings["tag"],
        "authority_policy_sha256": bindings["authority_policy_sha256"],
        "sidecar_sha256": bindings["sidecar_sha256"],
        "receipt_graph_sha256": bindings["receipt_graph_sha256"],
        "prediction_receipt_sha256": bindings["prediction_receipt_sha256"],
        "verdict_receipt_sha256": bindings["verdict_receipt_sha256"],
        "prediction_temporal_commitment_sha256": bindings[
            "prediction_temporal_commitment_sha256"
        ],
        "witness_dids": list(witnesses),
        "threshold": threshold,
        "verifier_artifact_sha256": verifier_artifact_sha,
        "verifier_python_sha256": verifier_python_sha,
    }
    for field, expected_value in expected.items():
        if attestation.get(field) != expected_value:
            raise TemporalSidecarError(f"time_authority.{field}_binding")
    observed_at = _time(attestation.get("observed_at"), path="time_authority.observed_at")
    valid_until = _time(attestation.get("valid_until"), path="time_authority.valid_until")
    if not (
        max(t2_times) <= observed_at <= evaluated_at <= valid_until
        and timedelta(0) < valid_until - observed_at <= MAX_AUTHORITY_LIFETIME
    ):
        raise TemporalSidecarError("time_authority.validity_window")
    signature = attestation.get("signature")
    if not (
        isinstance(signature, str)
        and len(signature) == 128
        and all(char in _HEX for char in signature)
        and ed25519_verify(
            public,
            time_authority_signed_bytes(attestation),
            bytes.fromhex(signature),
        )
    ):
        raise TemporalSidecarError("time_authority.signature")
    return (
        "did-key-sha256:" + hashlib.sha256(signer.encode("utf-8")).hexdigest(),
        attestation["valid_until"],
    )


def _verify_proof(
    raw: Any,
    *,
    evaluated_at: datetime,
    expected_time_authority_did: str,
    authority_challenge_sha: str,
    verifier_artifact_sha: str,
    verifier_python_sha: str,
) -> dict[str, Any]:
    proof = _mapping(raw, path="proof", keys=_PROOF_KEYS)
    if proof.get("schema_version") != PROOF_REQUEST_SCHEMA:
        raise TemporalSidecarError("proof.schema")
    request_id = _sha(proof.get("request_id"), path="proof.request_id")
    incarnation = _text(proof.get("tree_incarnation_id"), path="proof.tree_incarnation_id")
    tree = _text(proof.get("tree"), path="proof.tree")
    tag = _text(proof.get("tag"), path="proof.tag")
    current_head = _sha(proof.get("current_head_sha256"), path="proof.current_head")
    stored_sidecar_sha = _sha(proof.get("stored_sidecar_sha256"), path="proof.sidecar_sha")

    policy, witnesses, threshold = _policy(proof.get("authority_policy"))
    policy_sha = authority_policy_sha256(policy)
    sidecar = _sidecar(proof.get("sidecar"))
    if sidecar_sha256(sidecar) != stored_sidecar_sha:
        raise TemporalSidecarError("sidecar.content_sha")
    if not (
        sidecar.get("authority_policy_sha256") == policy_sha
        and sidecar.get("threshold") == threshold
        and sidecar.get("witness_allowlist") == list(witnesses)
    ):
        raise TemporalSidecarError("sidecar.policy_binding")

    prediction_sha = sidecar["prediction_receipt_sha256"]
    verdict_sha = sidecar["verdict_receipt_sha256"]
    chain, receipts = _receipt_prefix(
        proof,
        tree=tree,
        tag=tag,
        prediction_sha=prediction_sha,
        verdict_sha=verdict_sha,
    )
    if current_head != verdict_sha:
        raise TemporalSidecarError("proof.current_head_binding")
    expected_request_id = hashlib.sha256(
        TEMPORAL_REQUEST_ID_DOMAIN + jcs({
            "tree_incarnation_id": incarnation,
            "tree": tree,
            "tag": tag,
            "verdict_receipt_sha256": verdict_sha,
        })
    ).hexdigest()
    if request_id != expected_request_id:
        raise TemporalSidecarError("proof.request_id_binding")
    graph_sha = receipt_graph_sha256(
        tree_incarnation_id=incarnation,
        tree=tree,
        tag=tag,
        prediction_receipt_sha256=prediction_sha,
        verdict_receipt_sha256=verdict_sha,
        chain=chain,
    )
    if sidecar.get("receipt_graph_sha256") != graph_sha:
        raise TemporalSidecarError("sidecar.receipt_graph_binding")

    t1_signers, t1_times, t1_rendered = _anchor_set(
        sidecar.get("prediction_anchors"),
        path="prediction_anchors",
        receipt_sha=prediction_sha,
        witnesses=witnesses,
        threshold=threshold,
    )
    t2_signers, t2_times, t2_rendered = _anchor_set(
        sidecar.get("verdict_anchors"),
        path="verdict_anchors",
        receipt_sha=verdict_sha,
        witnesses=witnesses,
        threshold=threshold,
    )
    if t1_signers != t2_signers:
        raise TemporalSidecarError("anchors.signer_set_mismatch")
    if max(t1_times) >= min(t2_times):
        raise TemporalSidecarError("anchors.non_strict_interval")

    commitment = {
        "schema_version": PREDICTION_COMMITMENT_SCHEMA,
        "tree_incarnation_id": incarnation,
        "tree": tree,
        "tag": tag,
        "prediction_receipt_sha256": prediction_sha,
        "authority_policy_sha256": policy_sha,
        "prediction_anchors": sidecar["prediction_anchors"],
    }
    commitment_sha = commitment_sha256(commitment)
    if (
        receipts[verdict_sha].get("prediction_temporal_commitment_sha256")
        != commitment_sha
    ):
        raise TemporalSidecarError("verdict.v7_commitment_seal")

    bindings = {
        "request_id": request_id,
        "tree_incarnation_id": incarnation,
        "tree": tree,
        "tag": tag,
        "authority_policy_sha256": policy_sha,
        "sidecar_sha256": stored_sidecar_sha,
        "receipt_graph_sha256": graph_sha,
        "prediction_receipt_sha256": prediction_sha,
        "verdict_receipt_sha256": verdict_sha,
        "prediction_temporal_commitment_sha256": commitment_sha,
    }
    time_authority, independent_valid_until = _verify_attestation(
        proof.get("time_authority_attestation"),
        expected_signer_did=expected_time_authority_did,
        challenge_sha=authority_challenge_sha,
        evaluated_at=evaluated_at,
        policy=policy,
        bindings=bindings,
        witnesses=t1_signers,
        threshold=threshold,
        t2_times=t2_times,
        verifier_artifact_sha=verifier_artifact_sha,
        verifier_python_sha=verifier_python_sha,
    )
    latest_t1 = t1_rendered[t1_times.index(max(t1_times))]
    earliest_t2 = t2_rendered[t2_times.index(min(t2_times))]
    authority_identity_sha256s = sorted({
        hashlib.sha256(did.encode("utf-8")).hexdigest()
        for did in (
            *policy["witness_allowlist"],
            *policy["producer_dids"],
            *policy["attestor_dids"],
            expected_time_authority_did,
        )
    })
    return {
        "request_id": request_id,
        "status": "VERIFIED",
        "component_ok": True,
        "l3_eligible": True,
        "reason_code": "independent_two_ended_temporal_verified",
        **bindings,
        "threshold": threshold,
        "t1_latest": latest_t1,
        "t2_earliest": earliest_t2,
        "independent_verifier": "sha256:" + verifier_artifact_sha,
        "time_authority": time_authority,
        "independent_valid_until": independent_valid_until,
        "authority_identity_sha256s": authority_identity_sha256s,
    }


def verify_batch_value(
    request: Mapping[str, Any],
    *,
    actual_verifier_artifact_sha256: str,
    actual_verifier_python_sha256: str,
    evaluated_at: datetime,
) -> dict[str, Any]:
    batch = _mapping(dict(request), path="batch", keys=_BATCH_KEYS)
    if batch.get("schema_version") != BATCH_REQUEST_SCHEMA:
        raise TemporalSidecarError("batch.schema")
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise TemporalSidecarError("batch.verifier_clock")
    evaluated_at = evaluated_at.astimezone(timezone.utc)
    expected_time_authority_did = _did(
        batch.get("expected_time_authority_did"),
        path="batch.expected_time_authority_did",
    )[0]
    verifier_artifact_sha = _sha(
        batch.get("verifier_artifact_sha256"),
        path="batch.verifier_artifact_sha256",
    )
    verifier_python_sha = _sha(
        batch.get("verifier_python_sha256"),
        path="batch.verifier_python_sha256",
    )
    authority_challenge_sha = _sha(
        batch.get("authority_challenge_sha256"),
        path="batch.authority_challenge_sha256",
    )
    if not (
        verifier_artifact_sha == actual_verifier_artifact_sha256
        and verifier_python_sha == actual_verifier_python_sha256
    ):
        raise TemporalSidecarError("batch.verifier_artifact_identity")
    proofs = batch.get("proofs")
    if not isinstance(proofs, list) or not proofs or len(proofs) > MAX_PROOFS:
        raise TemporalSidecarError("batch.proofs")
    results = []
    seen: set[str] = set()
    for raw in proofs:
        request_id = raw.get("request_id") if isinstance(raw, dict) else None
        try:
            result = _verify_proof(
                raw,
                evaluated_at=evaluated_at,
                expected_time_authority_did=expected_time_authority_did,
                authority_challenge_sha=authority_challenge_sha,
                verifier_artifact_sha=verifier_artifact_sha,
                verifier_python_sha=verifier_python_sha,
            )
        except TemporalSidecarError as exc:
            result = {
                "request_id": request_id if isinstance(request_id, str) else None,
                "status": "REJECTED",
                "component_ok": False,
                "l3_eligible": False,
                "reason_code": str(exc),
            }
        if result["request_id"] in seen or result["request_id"] is None:
            raise TemporalSidecarError("batch.request_id_ambiguous")
        seen.add(result["request_id"])
        results.append(result)
    return {
        "schema_version": BATCH_REPORT_SCHEMA,
        "status": (
            "VERIFIED"
            if all(result["status"] == "VERIFIED" for result in results)
            else "REJECTED"
        ),
        "verifier_artifact_sha256": verifier_artifact_sha,
        "verifier_python_sha256": verifier_python_sha,
        "results": results,
    }


def verify_batch_bytes(
    data: bytes,
    *,
    actual_verifier_artifact_sha256: str,
    actual_verifier_python_sha256: str,
    evaluated_at: datetime,
) -> dict[str, Any]:
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_INPUT_BYTES:
        raise TemporalSidecarError("batch.input_size")
    try:
        request = parse_canonical(data)
    except JcsError as exc:
        raise TemporalSidecarError("batch.canonical_json") from exc
    return verify_batch_value(
        request,
        actual_verifier_artifact_sha256=actual_verifier_artifact_sha256,
        actual_verifier_python_sha256=actual_verifier_python_sha256,
        evaluated_at=evaluated_at,
    )


__all__ = [
    "BATCH_REPORT_SCHEMA",
    "BATCH_REQUEST_SCHEMA",
    "MAX_INPUT_BYTES",
    "PROOF_REQUEST_SCHEMA",
    "RECEIPT_TRANSPORT_FIELDS",
    "TIME_AUTHORITY_ATTESTATION_SCHEMA",
    "TemporalSidecarError",
    "authority_policy_sha256",
    "commitment_sha256",
    "receipt_graph_sha256",
    "sidecar_sha256",
    "time_authority_signed_bytes",
    "verify_batch_bytes",
    "verify_batch_value",
]
