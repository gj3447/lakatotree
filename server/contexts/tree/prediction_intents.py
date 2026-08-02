"""Exact validation of preregistration receipt/history commit intents."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from lakatos import temporal as temporal_mod
from lakatos.io.reconcile import canonical_history_payload, validate_history_record
from lakatos.verdicts import (
    prediction_content_sha,
    prediction_history_payload_sha,
)
from server.contexts.tree.schemas import PredictionIn


class PredictionIntentError(ValueError):
    """A prediction outbox is not exactly bound to its receipt and node."""


def effective_prediction_anchors(payload: dict[str, Any]) -> list[dict]:
    """Canonicalize the mutually-exclusive single/list request surfaces."""

    many = payload.get("temporal_anchors")
    if many is not None:
        return list(many)
    single = payload.get("temporal_anchor")
    return [] if single is None else [single]


def _canonical_request(payload_text: Any, tree: str, tag: str, event_id: str) -> dict:
    if not isinstance(payload_text, str):
        raise PredictionIntentError("prediction history payload is not text")
    try:
        payload = json.loads(
            payload_text,
            object_pairs_hook=lambda pairs: _unique_object(pairs),
        )
        parsed = PredictionIn.model_validate(payload).model_dump()
        canonical = validate_history_record(
            tree, "prediction_register", tag, parsed, event_id
        )
    except (TypeError, ValueError, UnicodeError) as exc:
        raise PredictionIntentError("prediction history payload is invalid") from exc
    if not isinstance(payload, dict) or parsed != payload or canonical != payload_text:
        raise PredictionIntentError("prediction history payload is not exact canonical input")
    return parsed


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise PredictionIntentError(f"duplicate prediction history key: {key}")
        out[key] = value
    return out


def _validate_anchor_bundle(receipt: dict[str, Any], payload: dict[str, Any]) -> None:
    bundle_text = receipt.get("anchor_bundle_json")
    bundle_sha = receipt.get("anchor_bundle_sha256")
    if not (
        isinstance(bundle_text, str)
        and isinstance(bundle_sha, str)
        and re.fullmatch(r"[0-9a-f]{64}", bundle_sha)
    ):
        raise PredictionIntentError("prediction V3 anchor bundle is missing")
    try:
        bundle = json.loads(bundle_text, object_pairs_hook=_unique_object)
        canonical = canonical_history_payload(bundle)
    except (TypeError, ValueError, UnicodeError) as exc:
        raise PredictionIntentError("prediction anchor bundle is invalid") from exc
    if (
        canonical != bundle_text
        or hashlib.sha256(bundle_text.encode("utf-8")).hexdigest() != bundle_sha
        or not isinstance(bundle, dict)
        or set(bundle) != {
            "schema", "spec_digest", "witness_dids",
            "witness_threshold", "anchors",
        }
        or bundle.get("schema") != "lakatotree-prediction-anchor-bundle/v1"
        or not isinstance(bundle.get("witness_dids"), list)
        or not all(isinstance(item, str) and item for item in bundle["witness_dids"])
        or type(bundle.get("witness_threshold")) is not int
        or bundle["witness_threshold"] < 1
        or not isinstance(bundle.get("anchors"), list)
        or not all(isinstance(item, dict) for item in bundle["anchors"])
    ):
        raise PredictionIntentError("prediction anchor bundle shape/hash diverges")
    effective_anchors = effective_prediction_anchors(payload)
    if bundle["anchors"] != effective_anchors:
        raise PredictionIntentError("prediction anchor bundle swaps submitted anchors")
    spec_digest = temporal_mod.spec_digest({
        key: value
        for key, value in payload.items()
        if key not in ("write_cert", "temporal_anchor", "temporal_anchors")
    })
    if bundle.get("spec_digest") != spec_digest:
        raise PredictionIntentError("prediction anchor bundle targets another request")
    anchors = bundle["anchors"]
    witnesses = bundle["witness_dids"]
    if anchors:
        if not witnesses:
            raise PredictionIntentError("prediction anchors lack a sealed witness policy")
        try:
            temporal_mod.verify_temporal_quorum(
                anchors,
                expect_receipt_sha=spec_digest,
                witness_allowlist=witnesses,
                threshold=bundle["witness_threshold"],
            )
        except temporal_mod.AnchorInvalid as exc:
            raise PredictionIntentError("prediction temporal quorum no longer verifies") from exc


def validate_prediction_register_intent(
    *,
    tree: Any,
    tag: Any,
    receipt_sha: Any,
    receipt: Any,
    current: Any,
    outbox: Any,
    require_current_effect: bool,
) -> dict[str, Any]:
    """Return the sealed request or raise on any semantic divergence."""

    if not (
        isinstance(tree, str) and tree
        and isinstance(tag, str) and tag
        and isinstance(receipt_sha, str)
        and re.fullmatch(r"[0-9a-f]{64}", receipt_sha)
        and isinstance(receipt, dict)
        and isinstance(current, dict)
        and isinstance(outbox, dict)
    ):
        raise PredictionIntentError("prediction authority is incomplete")
    event_id = f"ob-prediction-register-{receipt_sha}"
    status = outbox.get("status")
    pending = status == "pending" and outbox.get("applied_at") is None
    applied = status == "applied" and outbox.get("applied_at") is not None
    if not (
        outbox.get("id") == event_id
        and outbox.get("tree") == tree
        and outbox.get("op") == "prediction_register"
        and outbox.get("node_tag") == tag
        and outbox.get("reason") == "prediction_register_commit_intent"
        and outbox.get("created_at") is not None
        and outbox.get("adopted_by") is None
        and outbox.get("adopted_at") is None
        and outbox.get("causal_group") is None
        and outbox.get("causal_index") is None
        and outbox.get("request_sha256") is None
        and outbox.get("demoted_tag") is None
        and outbox.get("demoted_receipt_sha") is None
        and outbox.get("receipt_sha") == receipt_sha
        and (pending or applied)
    ):
        raise PredictionIntentError("prediction outbox envelope is not exact")
    payload = _canonical_request(outbox.get("payload"), tree, tag, event_id)
    if not (
        receipt.get("receipt_sha") == receipt_sha
        and receipt.get("receipt_kind") == "prediction"
        and receipt.get("tree") == tree
        and receipt.get("tag") == tag
        and receipt.get("registered_at") == outbox.get("created_at")
        and receipt.get("history_payload_sha256")
        == prediction_history_payload_sha(payload)
        and prediction_content_sha(receipt) == receipt_sha
    ):
        raise PredictionIntentError("prediction receipt does not seal its complete history")
    _validate_anchor_bundle(receipt, payload)

    cache_fields = {
        "pred_metric": "metric_name",
        "pred_direction": "direction",
        "pred_baseline": "baseline_value",
        "pred_noise_band": "noise_band",
        "pred_scale_type": "scale_type",
        "pred_novel": "novel_prediction",
        "pred_closes": "closes_question",
        "pred_novel_metric": "novel_metric",
        "pred_novel_direction": "novel_direction",
        "pred_novel_threshold": "novel_threshold",
        "pred_script_sha": "judge_script_sha",
        "pred_credence": "credence",
    }
    if any(current.get(cache) != payload.get(source) for cache, source in cache_fields.items()):
        raise PredictionIntentError("prediction node cache diverges from sealed request")
    if not (
        current.get("pred_receipt_sha") == receipt_sha
        and current.get("pred_registered_at") == receipt.get("registered_at")
        and current.get("baseline_lineage") == receipt.get("baseline_lineage")
        and bool(current.get("novel_registered"))
        == (payload.get("novel_metric") is not None)
        and current.get("pred_question_bound") is True
    ):
        raise PredictionIntentError("prediction node authority diverges from receipt")
    if require_current_effect and current.get("current_receipt_sha") != receipt_sha:
        raise PredictionIntentError("pending prediction intent no longer owns current head")
    return payload
