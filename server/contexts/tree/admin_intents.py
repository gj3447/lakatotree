"""Strict validation for atomic administrative-verdict history intents."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from lakatos.io.reconcile import canonical_history_payload
from lakatos.verdicts import (
    ADMIN_VERDICTS,
    RECEIPT_FIELDS,
    receipt_content_sha,
    verdict_history_payload_sha,
)


class AdminIntentError(ValueError):
    """An administrative receipt, effect, or outbox is inconsistent."""


def _hex64(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise AdminIntentError(f"{label} timestamp is not ISO text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AdminIntentError(f"{label} timestamp is invalid") from exc
    if parsed.utcoffset() is None:
        raise AdminIntentError(f"{label} timestamp lacks timezone")
    return parsed


def _canonical_object(raw: Any) -> dict[str, Any]:
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise AdminIntentError(f"admin payload has duplicate key {key!r}")
            result[key] = value
        return result

    if not isinstance(raw, str):
        raise AdminIntentError("admin payload is not text")
    try:
        value = json.loads(raw, object_pairs_hook=unique_object)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AdminIntentError("admin payload is not valid JSON") from exc
    if not isinstance(value, dict) or canonical_history_payload(value) != raw:
        raise AdminIntentError("admin payload is not a canonical object")
    return value


def _receipt_fields(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {key: snapshot.get(key) for key in RECEIPT_FIELDS}


def _validate_admin_receipt(
    *,
    tree: str,
    effect: dict[str, Any],
    receipt: dict[str, Any],
    source: str,
) -> dict[str, Any]:
    fields = _receipt_fields(receipt)
    receipt_sha = effect.get("receipt_sha")
    semantic_nulls = {
        "target_id", "metric_name", "metric_value", "novel_confirmed",
        "lakatos_status", "judge_script_sha", "measurement_grade",
        "comment_sha", "replay_status", "replay_reason",
        "regenerated_metric", "judge_script_path", "result_path",
        "result_sha256", "measurement_lock_sha", "source_script_path",
        "source_result_path",
    }
    if not (
        set(effect) == {
            "tag", "verdict", "verdict_source", "prev_receipt_sha",
            "receipt_sha",
        }
        and _hex64(receipt_sha)
        and receipt.get("receipt_sha") == receipt_sha
        and fields["tree"] == tree
        and fields["tag"] == effect["tag"]
        and fields["verdict"] == effect["verdict"]
        and fields["verdict_source"] == source == effect["verdict_source"]
        and fields["prev_receipt_sha"] == effect["prev_receipt_sha"]
        and effect["verdict"] in ADMIN_VERDICTS
        and all(fields[key] is None for key in semantic_nulls)
        and _hex64(fields["engine_rule_sha"])
        and _hex64(fields["history_payload_sha256"])
        and receipt_content_sha(fields) == receipt_sha
    ):
        raise AdminIntentError("administrative receipt content or scope mismatch")
    _timestamp(fields["judged_at"], "administrative receipt")
    return fields


def validate_admin_verdict_intent(
    *,
    tree: str,
    tag: str,
    receipt_sha: str,
    receipt: dict[str, Any],
    current: dict[str, Any],
    outbox: dict[str, Any],
    demoted_receipt: dict[str, Any] | None = None,
    demoted_current: dict[str, Any] | None = None,
    require_current_effect: bool = True,
) -> dict[str, Any]:
    """Return the validated compound payload for one administrative command."""

    if type(require_current_effect) is not bool:
        raise AdminIntentError("current-effect validation mode is not boolean")

    payload = _canonical_object(outbox.get("payload"))
    if set(payload) != {"request", "promoted", "demoted"}:
        raise AdminIntentError("administrative payload shape mismatch")
    request = payload.get("request")
    promoted = payload.get("promoted")
    demoted = payload.get("demoted")
    if not isinstance(request, dict) or not isinstance(promoted, dict):
        raise AdminIntentError("administrative request/effect is malformed")
    promoted_fields = _validate_admin_receipt(
        tree=tree,
        effect=promoted,
        receipt=receipt,
        source="admin",
    )
    if not (
        promoted["tag"] == tag
        and promoted["receipt_sha"] == receipt_sha
        and (
            not require_current_effect
            or (
                current.get("current_receipt_sha") == receipt_sha
                and current.get("verdict") == promoted["verdict"]
                and current.get("verdict_source") == "admin"
            )
        )
    ):
        raise AdminIntentError("promoted node cache diverges from receipt")

    expected_event_id = f"ob-verdict-{receipt_sha}"
    created_at = _timestamp(outbox.get("created_at"), "administrative outbox")
    if not (
        outbox.get("id") == expected_event_id
        and outbox.get("tree") == tree
        and outbox.get("op") == "verdict"
        and outbox.get("node_tag") == tag
        and outbox.get("reason") == "verdict_commit_intent"
        and outbox.get("receipt_sha") == receipt_sha
        and outbox.get("demoted_tag") == (
            demoted.get("tag") if isinstance(demoted, dict) else None
        )
        and outbox.get("demoted_receipt_sha") == (
            demoted.get("receipt_sha") if isinstance(demoted, dict) else None
        )
        and outbox.get("created_at") == promoted_fields["judged_at"]
        and (
            (outbox.get("status") == "pending" and outbox.get("applied_at") is None)
            or (outbox.get("status") == "applied"
                and outbox.get("applied_at") is not None)
        )
    ):
        raise AdminIntentError("administrative outbox envelope mismatch")
    if outbox.get("status") == "applied":
        applied_at = _timestamp(outbox["applied_at"], "administrative outbox applied")
        if applied_at < created_at:
            raise AdminIntentError("administrative applied timestamp precedes creation")

    if demoted is None:
        if demoted_receipt is not None or demoted_current is not None:
            raise AdminIntentError("unexpected demotion effect binding")
    else:
        if not isinstance(demoted, dict):
            raise AdminIntentError("demotion effect is malformed")
        if demoted_receipt is None or demoted_current is None:
            raise AdminIntentError("demotion receipt/effect binding is missing")
        demoted_fields = _validate_admin_receipt(
            tree=tree,
            effect=demoted,
            receipt=demoted_receipt,
            source="engine",
        )
        demotion_summary = {
            key: value for key, value in demoted.items() if key != "receipt_sha"
        }
        if not (
            demoted["verdict"] == "former_canonical"
            and verdict_history_payload_sha(demotion_summary)
                == demoted_fields["history_payload_sha256"]
            and demoted_current.get("tag") == demoted["tag"]
            and (
                not require_current_effect
                or (
                    demoted_current.get("current_receipt_sha")
                        == demoted["receipt_sha"]
                    and demoted_current.get("verdict") == "former_canonical"
                    and demoted_current.get("verdict_source") == "engine"
                )
            )
        ):
            raise AdminIntentError("demotion effect diverges from its receipt")

    promotion_preimage = {
        "request": request,
        "promoted": {
            key: value for key, value in promoted.items() if key != "receipt_sha"
        },
        "demoted": demoted,
    }
    if verdict_history_payload_sha(promotion_preimage) != promoted_fields[
        "history_payload_sha256"
    ]:
        raise AdminIntentError("administrative payload commitment mismatch")
    return payload
