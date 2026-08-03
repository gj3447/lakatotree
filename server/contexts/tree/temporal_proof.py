"""Frozen two-ended temporal proof kernel used by runtime permanent reads.

This module implements the exact sidecar contract exercised by the production
readiness harness.  T1 signs the content-addressed prediction receipt, T2 signs
the content-addressed verdict receipt, and the sidecar seals the logical receipt
prefix plus a server-derived authority-policy snapshot.  No stored boolean is
an input to this verifier.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Iterable, Mapping

from lakatos import layout as layout_mod
from lakatos.io.reconcile import canonical_history_payload
from lakatos.temporal import (
    AnchorInvalid,
    TEMPORAL_AUTHORITY_POLICY_SCHEMA,
    TWO_ENDED_SIDECAR_SCHEMA,
    temporal_authority_policy_sha256,
    two_ended_temporal_sidecar_sha256,
    verify_temporal_anchor,
)
from lakatos.verdicts import match_receipt_encoding
from lakatos.write_cert import (
    did_key_decode,
    did_key_encode,
    ed25519_public_key_is_strict,
)
from server.contexts.tree.receipt_chain import receipt_graph_prefix_sha256


POLICY_KEYS = frozenset({
    "schema_version",
    "threshold",
    "witness_allowlist",
    "producer_dids",
    "attestor_dids",
    "endpoint_signer_rule",
    "evidence_refs",
})
SIDECAR_KEYS = frozenset({
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
ANCHOR_KEYS = frozenset({
    "witness_did", "digest", "gen_time", "signature", "channel",
})
MAX_TEMPORAL_ANCHORS = 32
PREDICTION_COMMITMENT_SCHEMA = "lakatotree-prediction-temporal-commitment/v1"
PREDICTION_COMMITMENT_DOMAIN = b"lakatotree-prediction-temporal-commitment/v1\0"
PREDICTION_COMMITMENT_KEYS = frozenset({
    "schema_version",
    "tree_incarnation_id",
    "tree",
    "tag",
    "prediction_receipt_sha256",
    "authority_policy_sha256",
    "prediction_anchors",
})


class TemporalProofInvalid(ValueError):
    """The sidecar or one of its immutable dependencies failed closed."""


@dataclass(frozen=True)
class TemporalProof:
    """Typed read-time result; never persist this as a node-cache claim."""

    component_ok: bool
    l3_eligible: bool
    reason: str
    chain_ok: bool | None = None
    sidecar_sha256: str | None = None
    authority_policy_sha256: str | None = None
    receipt_graph_sha256: str | None = None
    prediction_receipt_sha256: str | None = None
    verdict_receipt_sha256: str | None = None
    prediction_temporal_commitment_sha256: str | None = None
    witness_dids: tuple[str, ...] = ()
    threshold: int | None = None
    t1_latest: str | None = None
    t2_earliest: str | None = None
    independent_verifier: str | None = None
    time_authority: str | None = None
    independent_input_sha256: str | None = None
    independent_valid_until: str | None = None
    authority_identity_sha256s: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "component_ok": self.component_ok,
            "l3_eligible": self.l3_eligible,
            "reason": self.reason,
            "chain_ok": self.chain_ok,
            "sidecar_sha256": self.sidecar_sha256,
            "authority_policy_sha256": self.authority_policy_sha256,
            "receipt_graph_sha256": self.receipt_graph_sha256,
            "prediction_receipt_sha256": self.prediction_receipt_sha256,
            "verdict_receipt_sha256": self.verdict_receipt_sha256,
            "prediction_temporal_commitment_sha256": (
                self.prediction_temporal_commitment_sha256
            ),
            "witness_dids": list(self.witness_dids),
            "threshold": self.threshold,
            "t1_latest": self.t1_latest,
            "t2_earliest": self.t2_earliest,
            "independent_verifier": self.independent_verifier,
            "time_authority": self.time_authority,
            "independent_input_sha256": self.independent_input_sha256,
            "independent_valid_until": self.independent_valid_until,
            "authority_identity_sha256s": list(self.authority_identity_sha256s),
        }


@dataclass(frozen=True)
class VerifiedPredictionTemporalCommitment:
    commitment_sha256: str
    authority_policy_sha256: str
    prediction_receipt_sha256: str
    witness_dids: tuple[str, ...]
    threshold: int
    t1_latest: str


def unavailable_temporal_proof(
    reason: str,
    *,
    chain_ok: bool | None = None,
) -> TemporalProof:
    return TemporalProof(
        component_ok=False,
        l3_eligible=False,
        reason=reason,
        chain_ok=chain_ok,
    )


def _sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _canonical_did(value: Any) -> bool:
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    try:
        public = did_key_decode(value)
        return (
            did_key_encode(public) == value
            and ed25519_public_key_is_strict(public)
        )
    except (TypeError, ValueError, OverflowError):
        return False


def _parse_time(value: Any) -> datetime:
    if not isinstance(value, str) or not value or value != value.strip():
        raise TemporalProofInvalid("temporal anchor time is malformed")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise TemporalProofInvalid("temporal anchor time is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TemporalProofInvalid("temporal anchor time lacks a timezone")
    return parsed.astimezone(timezone.utc)


def _canonical_did_list(
    values: Any,
    *,
    label: str,
    allow_empty: bool,
) -> tuple[str, ...]:
    if not isinstance(values, list) or (not allow_empty and not values):
        raise TemporalProofInvalid(f"{label} is empty or malformed")
    if not all(_canonical_did(value) for value in values):
        raise TemporalProofInvalid(f"{label} contains a non-canonical did:key")
    canonical = tuple(sorted(values))
    if tuple(values) != canonical or len(set(values)) != len(values):
        raise TemporalProofInvalid(f"{label} must be sorted and unique")
    return canonical


def build_temporal_authority_policy(
    *,
    threshold: int,
    witness_allowlist: Iterable[str],
    producer_dids: Iterable[str],
    attestor_dids: Iterable[str],
    evidence_refs: Iterable[str],
) -> dict[str, Any]:
    """Build the policy from server-owned tree/layout state, never request data."""

    policy = {
        "schema_version": TEMPORAL_AUTHORITY_POLICY_SCHEMA,
        "threshold": threshold,
        "witness_allowlist": sorted(witness_allowlist),
        "producer_dids": sorted(producer_dids),
        "attestor_dids": sorted(attestor_dids),
        "endpoint_signer_rule": "same-authority-set",
        "evidence_refs": sorted(evidence_refs),
    }
    _validate_policy(policy)
    return policy


def derive_temporal_authority_policy(
    tree_name: str,
    tree_record: Mapping[str, Any],
    *,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    """Derive the temporal policy only from a signed server-owned tree layout."""

    record = dict(tree_record)
    raw_layout = record.get("research_layout")
    if not isinstance(raw_layout, str) or not raw_layout.strip():
        raise TemporalProofInvalid(
            "receipt-bound temporal proof requires a research layout"
        )
    try:
        role_layout = layout_mod.parse_role_layout(raw_layout)
    except layout_mod.LayoutError as exc:
        raise TemporalProofInvalid("research layout is malformed") from exc
    if role_layout is None or layout_mod.layout_expired(
        role_layout, now=evaluated_at
    ):
        raise TemporalProofInvalid("research layout is missing or expired")
    if not layout_mod.verify_layout_sig(
        role_layout,
        str(record.get("layout_owner_did") or ""),
        str(record.get("layout_sig") or ""),
    ):
        raise TemporalProofInvalid("research layout owner signature is invalid")
    producer_dids = layout_mod.pubkeys_for_verb(
        role_layout, "register_prediction"
    )
    tree_attestors = [
        item.strip()
        for item in (record.get("attestor_dids") or [])
        if isinstance(item, str) and item.strip()
    ]
    attestor_dids = layout_mod.role_allowlist(
        role_layout, "submit_test_result", tree_attestors
    )
    witnesses = record.get("witness_dids")
    threshold = record.get("witness_threshold")
    if not producer_dids:
        raise TemporalProofInvalid(
            "research layout does not identify prediction producers"
        )
    if not attestor_dids:
        raise TemporalProofInvalid(
            "research layout does not identify verdict attestors"
        )
    if not isinstance(witnesses, list) or not witnesses:
        raise TemporalProofInvalid("tree lacks a temporal witness allowlist")
    if type(threshold) is not int or threshold < 2:
        raise TemporalProofInvalid(
            "two-ended temporal proof requires witness threshold at least two"
        )
    return build_temporal_authority_policy(
        threshold=threshold,
        witness_allowlist=witnesses,
        producer_dids=producer_dids,
        attestor_dids=attestor_dids,
        evidence_refs=[
            f"kg://LakatosTree/{tree_name}/research-layout",
            f"kg://LakatosTree/{tree_name}/temporal-witness-policy",
        ],
    )


def build_two_ended_sidecar(
    *,
    authority_policy: Mapping[str, Any],
    prediction_receipt_sha256: str,
    verdict_receipt_sha256: str,
    receipt_graph_sha256: str,
    prediction_anchors: list[dict[str, Any]],
    verdict_anchors: list[dict[str, Any]],
) -> dict[str, Any]:
    policy = dict(authority_policy)
    _validate_policy(policy)
    sidecar = {
        "schema_version": TWO_ENDED_SIDECAR_SCHEMA,
        "authority_policy_sha256": temporal_authority_policy_sha256(policy),
        "threshold": policy["threshold"],
        "witness_allowlist": list(policy["witness_allowlist"]),
        "prediction_receipt_sha256": prediction_receipt_sha256,
        "verdict_receipt_sha256": verdict_receipt_sha256,
        "receipt_graph_sha256": receipt_graph_sha256,
        "prediction_anchors": prediction_anchors,
        "verdict_anchors": verdict_anchors,
    }
    _validate_sidecar(sidecar)
    return sidecar


def build_prediction_temporal_commitment(
    *,
    tree_incarnation_id: str,
    tree: str,
    tag: str,
    prediction_receipt_sha256: str,
    authority_policy: Mapping[str, Any],
    prediction_anchors: list[dict[str, Any]],
) -> dict[str, Any]:
    policy = dict(authority_policy)
    _validate_policy(policy)
    commitment = {
        "schema_version": PREDICTION_COMMITMENT_SCHEMA,
        "tree_incarnation_id": tree_incarnation_id,
        "tree": tree,
        "tag": tag,
        "prediction_receipt_sha256": prediction_receipt_sha256,
        "authority_policy_sha256": temporal_authority_policy_sha256(policy),
        "prediction_anchors": prediction_anchors,
    }
    _validate_prediction_commitment(commitment)
    return commitment


def canonical_prediction_commitment_json(commitment: Mapping[str, Any]) -> str:
    value = dict(commitment)
    _validate_prediction_commitment(value)
    return canonical_history_payload(value)


def prediction_temporal_commitment_sha256(
    commitment: Mapping[str, Any],
) -> str:
    return hashlib.sha256(
        PREDICTION_COMMITMENT_DOMAIN
        + canonical_prediction_commitment_json(commitment).encode("utf-8")
    ).hexdigest()


def canonical_policy_json(policy: Mapping[str, Any]) -> str:
    value = dict(policy)
    _validate_policy(value)
    return canonical_history_payload(value)


def canonical_sidecar_json(sidecar: Mapping[str, Any]) -> str:
    value = dict(sidecar)
    _validate_sidecar(value)
    return canonical_history_payload(value)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise TemporalProofInvalid(f"duplicate JSON key: {key}")
        out[key] = value
    return out


def _parse_canonical(raw: Any, *, label: str, validator) -> dict[str, Any]:
    if not isinstance(raw, str):
        raise TemporalProofInvalid(f"{label} is not text")
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TemporalProofInvalid(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise TemporalProofInvalid(f"{label} is not an object")
    validator(value)
    if canonical_history_payload(value) != raw:
        raise TemporalProofInvalid(f"{label} is not canonical")
    return value


def parse_canonical_policy(raw: Any) -> dict[str, Any]:
    return _parse_canonical(raw, label="authority_policy_json", validator=_validate_policy)


def parse_canonical_sidecar(raw: Any) -> dict[str, Any]:
    return _parse_canonical(raw, label="sidecar_json", validator=_validate_sidecar)


def parse_canonical_prediction_commitment(raw: Any) -> dict[str, Any]:
    return _parse_canonical(
        raw,
        label="prediction_commitment_json",
        validator=_validate_prediction_commitment,
    )


def _validate_policy(policy: dict[str, Any]) -> None:
    if not isinstance(policy, dict) or set(policy) != POLICY_KEYS:
        raise TemporalProofInvalid("authority policy field set is not exact")
    if policy.get("schema_version") != TEMPORAL_AUTHORITY_POLICY_SCHEMA:
        raise TemporalProofInvalid("authority policy schema is unsupported")
    witnesses = _canonical_did_list(
        policy.get("witness_allowlist"),
        label="witness allowlist",
        allow_empty=False,
    )
    producers = _canonical_did_list(
        policy.get("producer_dids"),
        label="producer roles",
        allow_empty=False,
    )
    attestors = _canonical_did_list(
        policy.get("attestor_dids"),
        label="attestor roles",
        allow_empty=False,
    )
    threshold = policy.get("threshold")
    if type(threshold) is not int or threshold < 2 or threshold > len(witnesses):
        raise TemporalProofInvalid("authority threshold must be 2..N")
    if set(producers) & set(attestors):
        raise TemporalProofInvalid("producer and attestor roles overlap")
    if set(witnesses) & (set(producers) | set(attestors)):
        raise TemporalProofInvalid("witness and producer/attestor roles overlap")
    if policy.get("endpoint_signer_rule") != "same-authority-set":
        raise TemporalProofInvalid("endpoint signer rule is unsupported")
    refs = policy.get("evidence_refs")
    if (
        not isinstance(refs, list)
        or not refs
        or not all(isinstance(item, str) and item and item == item.strip() for item in refs)
        or refs != sorted(refs)
        or len(set(refs)) != len(refs)
    ):
        raise TemporalProofInvalid("authority evidence refs must be sorted and unique")


def _validate_sidecar(sidecar: dict[str, Any]) -> None:
    if not isinstance(sidecar, dict) or set(sidecar) != SIDECAR_KEYS:
        raise TemporalProofInvalid("two-ended sidecar field set is not exact")
    if sidecar.get("schema_version") != TWO_ENDED_SIDECAR_SCHEMA:
        raise TemporalProofInvalid("two-ended sidecar schema is unsupported")
    if not all(
        _sha256(sidecar.get(field))
        for field in (
            "authority_policy_sha256",
            "prediction_receipt_sha256",
            "verdict_receipt_sha256",
            "receipt_graph_sha256",
        )
    ):
        raise TemporalProofInvalid("two-ended sidecar identity is malformed")
    _canonical_did_list(
        sidecar.get("witness_allowlist"),
        label="sidecar witness allowlist",
        allow_empty=False,
    )
    if type(sidecar.get("threshold")) is not int:
        raise TemporalProofInvalid("sidecar threshold is malformed")
    for endpoint in ("prediction", "verdict"):
        anchors = sidecar.get(f"{endpoint}_anchors")
        if (
            not isinstance(anchors, list)
            or not anchors
            or len(anchors) > MAX_TEMPORAL_ANCHORS
        ):
            raise TemporalProofInvalid(f"{endpoint} anchor set is empty or oversized")


def _validate_prediction_commitment(commitment: dict[str, Any]) -> None:
    if not isinstance(commitment, dict) or set(commitment) != PREDICTION_COMMITMENT_KEYS:
        raise TemporalProofInvalid("prediction commitment field set is not exact")
    if commitment.get("schema_version") != PREDICTION_COMMITMENT_SCHEMA:
        raise TemporalProofInvalid("prediction commitment schema is unsupported")
    if not all(
        isinstance(commitment.get(field), str) and bool(commitment[field])
        for field in ("tree_incarnation_id", "tree", "tag")
    ):
        raise TemporalProofInvalid("prediction commitment scope is malformed")
    if not all(
        _sha256(commitment.get(field))
        for field in ("prediction_receipt_sha256", "authority_policy_sha256")
    ):
        raise TemporalProofInvalid("prediction commitment identity is malformed")
    anchors = commitment.get("prediction_anchors")
    if not isinstance(anchors, list) or not anchors or len(anchors) > MAX_TEMPORAL_ANCHORS:
        raise TemporalProofInvalid("prediction commitment anchors are empty or oversized")


def _strict_anchor_set(
    anchors: Any,
    *,
    endpoint: str,
    receipt_sha256: str,
    allowlist: tuple[str, ...],
    threshold: int,
) -> tuple[tuple[str, ...], tuple[datetime, ...], tuple[str, ...]]:
    if not isinstance(anchors, list) or not anchors or len(anchors) > MAX_TEMPORAL_ANCHORS:
        raise TemporalProofInvalid(f"{endpoint} anchor set is empty or oversized")
    if not all(isinstance(item, dict) and set(item) == ANCHOR_KEYS for item in anchors):
        raise TemporalProofInvalid(f"{endpoint} anchor field set is not exact")
    submitted = [item.get("witness_did") for item in anchors]
    if submitted != sorted(submitted) or len(set(submitted)) != len(submitted):
        raise TemporalProofInvalid(f"{endpoint} anchors must use sorted unique witnesses")
    times: list[datetime] = []
    rendered: list[str] = []
    for anchor in anchors:
        try:
            timestamp = verify_temporal_anchor(
                anchor,
                expect_receipt_sha=receipt_sha256,
                witness_allowlist=list(allowlist),
            )
        except (AnchorInvalid, TypeError, ValueError, OverflowError) as exc:
            raise TemporalProofInvalid(f"{endpoint} anchor set contains an invalid member") from exc
        times.append(_parse_time(timestamp))
        rendered.append(timestamp)
    signers = tuple(submitted)
    if len(signers) < threshold:
        raise TemporalProofInvalid(f"{endpoint} anchor threshold is not met")
    return signers, tuple(times), tuple(rendered)


def _validate_receipt_prefix(
    *,
    tree: str,
    tag: str,
    tree_incarnation_id: str,
    prediction_receipt_sha256: str,
    verdict_receipt_sha256: str,
    current_head_sha256: str,
    chain: Iterable[str],
    receipt_by_sha: Mapping[str, Mapping[str, Any]],
) -> tuple[tuple[str, ...], str]:
    ordered = tuple(chain)
    if (
        not ordered
        or len(set(ordered)) != len(ordered)
        or ordered[-1] != verdict_receipt_sha256
        or current_head_sha256 != verdict_receipt_sha256
        or prediction_receipt_sha256 not in ordered
    ):
        raise TemporalProofInvalid("receipt prefix is stale, ambiguous, or lacks prediction ancestry")
    previous: str | None = None
    for index, receipt_sha in enumerate(ordered):
        receipt = receipt_by_sha.get(receipt_sha)
        if not isinstance(receipt, Mapping):
            raise TemporalProofInvalid("receipt prefix has a missing receipt")
        material = dict(receipt)
        if not (
            _sha256(receipt_sha)
            and material.get("receipt_sha") == receipt_sha
            and material.get("tree") == tree
            and material.get("tag") == tag
            and material.get("prev_receipt_sha") == previous
            and match_receipt_encoding(material, receipt_sha) == "current"
        ):
            raise TemporalProofInvalid("receipt prefix content does not rederive")
        if index == 0 and material.get("prev_receipt_sha") is not None:
            raise TemporalProofInvalid("receipt prefix does not begin at genesis")
        previous = receipt_sha
    prediction = dict(receipt_by_sha[prediction_receipt_sha256])
    verdict = dict(receipt_by_sha[verdict_receipt_sha256])
    if prediction.get("receipt_kind") != "prediction":
        raise TemporalProofInvalid("prediction endpoint is not a prediction receipt")
    if verdict.get("receipt_kind") == "prediction":
        raise TemporalProofInvalid("verdict endpoint is a prediction receipt")
    graph_sha = receipt_graph_prefix_sha256(
        tree_incarnation_id=tree_incarnation_id,
        tree=tree,
        tag=tag,
        prediction_receipt_sha256=prediction_receipt_sha256,
        verdict_receipt_sha256=verdict_receipt_sha256,
        chain=ordered,
    )
    return ordered, graph_sha


def verify_prediction_temporal_commitment(
    commitment: Mapping[str, Any],
    *,
    stored_commitment_sha256: str,
    authority_policy: Mapping[str, Any],
    tree_incarnation_id: str,
    tree: str,
    tag: str,
    prediction_receipt_sha256: str,
    prediction_receipt: Mapping[str, Any],
    current_head_sha256: str,
    evaluated_at: datetime,
) -> VerifiedPredictionTemporalCommitment:
    """Verify T1 while the prediction receipt is still the current head."""

    if current_head_sha256 != prediction_receipt_sha256:
        raise TemporalProofInvalid("prediction commitment is post-verdict")
    return verify_prediction_temporal_commitment_content(
        commitment,
        stored_commitment_sha256=stored_commitment_sha256,
        authority_policy=authority_policy,
        tree_incarnation_id=tree_incarnation_id,
        tree=tree,
        tag=tag,
        prediction_receipt_sha256=prediction_receipt_sha256,
        prediction_receipt=prediction_receipt,
        evaluated_at=evaluated_at,
    )


def verify_prediction_temporal_commitment_content(
    commitment: Mapping[str, Any],
    *,
    stored_commitment_sha256: str,
    authority_policy: Mapping[str, Any],
    tree_incarnation_id: str,
    tree: str,
    tag: str,
    prediction_receipt_sha256: str,
    prediction_receipt: Mapping[str, Any],
    evaluated_at: datetime,
) -> VerifiedPredictionTemporalCommitment:
    """Verify immutable T1 content without making a current-head claim."""

    return _verify_prediction_temporal_commitment(
        commitment,
        stored_commitment_sha256=stored_commitment_sha256,
        authority_policy=authority_policy,
        tree_incarnation_id=tree_incarnation_id,
        tree=tree,
        tag=tag,
        prediction_receipt_sha256=prediction_receipt_sha256,
        prediction_receipt=prediction_receipt,
        current_head_sha256=prediction_receipt_sha256,
        evaluated_at=evaluated_at,
        require_prediction_head=False,
    )


def verify_sealed_prediction_temporal_commitment(
    commitment: Mapping[str, Any],
    *,
    stored_commitment_sha256: str,
    authority_policy: Mapping[str, Any],
    tree_incarnation_id: str,
    tree: str,
    tag: str,
    prediction_receipt_sha256: str,
    prediction_receipt: Mapping[str, Any],
    current_head_sha256: str,
    verdict_receipt: Mapping[str, Any],
    evaluated_at: datetime,
) -> VerifiedPredictionTemporalCommitment:
    """Verify a pre-verdict T1 commitment through its verdict-receipt seal."""

    verdict = dict(verdict_receipt)
    if not (
        verdict.get("receipt_sha") == current_head_sha256
        and verdict.get("receipt_kind") != "prediction"
        and verdict.get("tree") == tree
        and verdict.get("tag") == tag
        and verdict.get("prediction_temporal_commitment_sha256")
        == stored_commitment_sha256
        and match_receipt_encoding(verdict, current_head_sha256) == "current"
    ):
        raise TemporalProofInvalid(
            "verdict receipt does not seal the stored prediction commitment"
        )
    return verify_prediction_temporal_commitment_content(
        commitment,
        stored_commitment_sha256=stored_commitment_sha256,
        authority_policy=authority_policy,
        tree_incarnation_id=tree_incarnation_id,
        tree=tree,
        tag=tag,
        prediction_receipt_sha256=prediction_receipt_sha256,
        prediction_receipt=prediction_receipt,
        evaluated_at=evaluated_at,
    )


def _verify_prediction_temporal_commitment(
    commitment: Mapping[str, Any],
    *,
    stored_commitment_sha256: str,
    authority_policy: Mapping[str, Any],
    tree_incarnation_id: str,
    tree: str,
    tag: str,
    prediction_receipt_sha256: str,
    prediction_receipt: Mapping[str, Any],
    current_head_sha256: str,
    evaluated_at: datetime,
    require_prediction_head: bool,
) -> VerifiedPredictionTemporalCommitment:

    body = dict(commitment)
    policy = dict(authority_policy)
    _validate_prediction_commitment(body)
    _validate_policy(policy)
    if not _sha256(stored_commitment_sha256) or (
        prediction_temporal_commitment_sha256(body) != stored_commitment_sha256
    ):
        raise TemporalProofInvalid("prediction commitment hash does not rederive")
    if not (
        body.get("tree_incarnation_id") == tree_incarnation_id
        and body.get("tree") == tree
        and body.get("tag") == tag
        and body.get("prediction_receipt_sha256") == prediction_receipt_sha256
    ):
        raise TemporalProofInvalid("prediction commitment scope is swapped")
    if require_prediction_head and current_head_sha256 != prediction_receipt_sha256:
        raise TemporalProofInvalid("prediction commitment is post-verdict")
    receipt = dict(prediction_receipt)
    if not (
        receipt.get("receipt_sha") == prediction_receipt_sha256
        and receipt.get("receipt_kind") == "prediction"
        and receipt.get("tree") == tree
        and receipt.get("tag") == tag
        and match_receipt_encoding(receipt, prediction_receipt_sha256) == "current"
    ):
        raise TemporalProofInvalid("prediction commitment endpoint does not rederive")
    policy_sha = temporal_authority_policy_sha256(policy)
    if body.get("authority_policy_sha256") != policy_sha:
        raise TemporalProofInvalid("prediction commitment policy hash does not rederive")
    allowlist = tuple(policy["witness_allowlist"])
    signers, times, rendered = _strict_anchor_set(
        body["prediction_anchors"],
        endpoint="prediction",
        receipt_sha256=prediction_receipt_sha256,
        allowlist=allowlist,
        threshold=policy["threshold"],
    )
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise TemporalProofInvalid("evaluation time must be timezone-aware")
    evaluation_time = evaluated_at.astimezone(timezone.utc)
    if any(timestamp > evaluation_time for timestamp in times):
        raise TemporalProofInvalid("prediction anchor is after the evaluation time")
    latest = max(times)
    return VerifiedPredictionTemporalCommitment(
        commitment_sha256=stored_commitment_sha256,
        authority_policy_sha256=policy_sha,
        prediction_receipt_sha256=prediction_receipt_sha256,
        witness_dids=signers,
        threshold=policy["threshold"],
        t1_latest=rendered[times.index(latest)],
    )


def verify_two_ended_temporal_sidecar(
    sidecar: Mapping[str, Any],
    *,
    stored_sidecar_sha256: str,
    stored_authority_policy: Mapping[str, Any],
    current_authority_policy: Mapping[str, Any],
    tree: str,
    tag: str,
    tree_incarnation_id: str,
    current_head_sha256: str,
    chain: Iterable[str],
    receipt_by_sha: Mapping[str, Mapping[str, Any]],
    evaluated_at: datetime,
) -> TemporalProof:
    """Reverify the exact Gate-3 component from immutable storage facts.

    A success intentionally remains ``l3_eligible=False`` until Gate 4 adds an
    engine-independent verifier and independently administered time authority.
    """

    body = dict(sidecar)
    _validate_sidecar(body)
    stored_policy = dict(stored_authority_policy)
    current_policy = dict(current_authority_policy)
    _validate_policy(stored_policy)
    _validate_policy(current_policy)
    if stored_policy != current_policy:
        raise TemporalProofInvalid("current authority policy differs from the sealed policy")
    if body.get("verdict_receipt_sha256") != current_head_sha256:
        raise TemporalProofInvalid(
            "receipt prefix is stale, ambiguous, or lacks prediction ancestry"
        )
    return verify_two_ended_temporal_sidecar_prefix(
        body,
        stored_sidecar_sha256=stored_sidecar_sha256,
        authority_policy=stored_policy,
        tree=tree,
        tag=tag,
        tree_incarnation_id=tree_incarnation_id,
        chain=chain,
        receipt_by_sha=receipt_by_sha,
        evaluated_at=evaluated_at,
    )


def verify_two_ended_temporal_sidecar_prefix(
    sidecar: Mapping[str, Any],
    *,
    stored_sidecar_sha256: str,
    authority_policy: Mapping[str, Any],
    tree: str,
    tag: str,
    tree_incarnation_id: str,
    chain: Iterable[str],
    receipt_by_sha: Mapping[str, Mapping[str, Any]],
    evaluated_at: datetime,
) -> TemporalProof:
    """Verify a frozen genesis-to-verdict prefix without current-state claims."""

    body = dict(sidecar)
    if not isinstance(tree_incarnation_id, str) or not tree_incarnation_id:
        raise TemporalProofInvalid("tree incarnation identity is missing")
    stored_policy = dict(authority_policy)
    _validate_sidecar(body)
    _validate_policy(stored_policy)
    policy_sha = temporal_authority_policy_sha256(stored_policy)
    if body.get("authority_policy_sha256") != policy_sha:
        raise TemporalProofInvalid("sidecar authority-policy hash does not rederive")
    if not (
        body.get("threshold") == stored_policy["threshold"]
        and body.get("witness_allowlist") == stored_policy["witness_allowlist"]
    ):
        raise TemporalProofInvalid("sidecar witness policy differs from authority policy")
    if not _sha256(stored_sidecar_sha256) or (
        two_ended_temporal_sidecar_sha256(body) != stored_sidecar_sha256
    ):
        raise TemporalProofInvalid("sidecar content hash does not rederive")

    prediction_sha = body["prediction_receipt_sha256"]
    verdict_sha = body["verdict_receipt_sha256"]
    ordered, graph_sha = _validate_receipt_prefix(
        tree=tree,
        tag=tag,
        tree_incarnation_id=tree_incarnation_id,
        prediction_receipt_sha256=prediction_sha,
        verdict_receipt_sha256=verdict_sha,
        current_head_sha256=verdict_sha,
        chain=chain,
        receipt_by_sha=receipt_by_sha,
    )
    if body.get("receipt_graph_sha256") != graph_sha:
        raise TemporalProofInvalid("sidecar receipt-graph hash does not rederive")

    allowlist = tuple(stored_policy["witness_allowlist"])
    threshold = stored_policy["threshold"]
    t1_signers, t1_times, t1_rendered = _strict_anchor_set(
        body["prediction_anchors"],
        endpoint="prediction",
        receipt_sha256=prediction_sha,
        allowlist=allowlist,
        threshold=threshold,
    )
    t2_signers, t2_times, t2_rendered = _strict_anchor_set(
        body["verdict_anchors"],
        endpoint="verdict",
        receipt_sha256=verdict_sha,
        allowlist=allowlist,
        threshold=threshold,
    )
    if t1_signers != t2_signers:
        raise TemporalProofInvalid("T1 and T2 signer sets are not identical")
    if max(t1_times) >= min(t2_times):
        raise TemporalProofInvalid("temporal interval is not strict T1 < T2")
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise TemporalProofInvalid("evaluation time must be timezone-aware")
    evaluation_time = evaluated_at.astimezone(timezone.utc)
    if any(timestamp > evaluation_time for timestamp in (*t1_times, *t2_times)):
        raise TemporalProofInvalid("temporal anchor is after the evaluation time")

    commitment = build_prediction_temporal_commitment(
        tree_incarnation_id=tree_incarnation_id,
        tree=tree,
        tag=tag,
        prediction_receipt_sha256=prediction_sha,
        authority_policy=stored_policy,
        prediction_anchors=body["prediction_anchors"],
    )
    commitment_sha = prediction_temporal_commitment_sha256(commitment)
    verdict_receipt = receipt_by_sha.get(verdict_sha)
    if not isinstance(verdict_receipt, Mapping) or (
        verdict_receipt.get("prediction_temporal_commitment_sha256")
        != commitment_sha
    ):
        raise TemporalProofInvalid(
            "verdict receipt does not causally seal the prediction commitment"
        )

    return TemporalProof(
        component_ok=True,
        l3_eligible=False,
        reason="independent_verifier_and_time_authority_pending",
        chain_ok=True,
        sidecar_sha256=stored_sidecar_sha256,
        authority_policy_sha256=policy_sha,
        receipt_graph_sha256=graph_sha,
        prediction_receipt_sha256=prediction_sha,
        verdict_receipt_sha256=verdict_sha,
        prediction_temporal_commitment_sha256=commitment_sha,
        witness_dids=t1_signers,
        threshold=threshold,
        t1_latest=t1_rendered[t1_times.index(max(t1_times))],
        t2_earliest=t2_rendered[t2_times.index(min(t2_times))],
    )
