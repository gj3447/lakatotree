"""Pure validation for receipt-bound verdict history intents.

Neo4j is authoritative for the verdict mutation, while PostgreSQL is its
append-only projection.  These checks prevent an outbox-shaped document from
becoming projection authority unless it is bound to the exact content-addressed
receipt and its causal siblings agree on one semantic result.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from lakatos.io.reconcile import canonical_history_payload
from lakatos.frontier_state import receipt_backed_conclusive
from lakatos.verdicts import (
    ENGINE_VERDICTS,
    RECEIPT_FIELDS,
    SCRIPTED_VERDICTS,
    format_verdict_with_val,
    receipt_content_sha,
    verdict_assurance,
    verdict_history_payload_sha,
)


SCRIPTED_RESULT_VERDICTS = SCRIPTED_VERDICTS | ENGINE_VERDICTS
SCRIPTED_LAKATOS_STATUSES = frozenset({
    "n/a",
    "unverified",
    "progressive",
    "progressive_conditional",
    "degenerating",
    "different_programme",
    "ambiguous",
    "hard_core_violated_structural",
    "reproducibility_refuted",
    "novel_not_server_anchored",
    "provisional_stale_engine",
})


class VerdictIntentError(ValueError):
    """A durable verdict/outbox snapshot is internally inconsistent."""


TEST_RESULT_PAYLOAD_KEYS = frozenset({
    "attested_by", "baseline", "delta", "freshen", "lakatos",
    "measurement_lock_sha", "metric_verdict", "novel",
    "novel_server_anchored", "receipt_sha", "regenerated_metric",
    "replay_reason", "replay_status", "requires_human", "result_path",
    "result_sha256", "rule", "script", "script_sha",
    "script_sha_server_verified", "source_result_path",
    "source_script_path", "value", "verdict",
    "cycle_claim", "cycle_request_sha256", "request_sha256",
    "assurance", "eureka_closed", "eureka_open",
    "qualitative_self_report", "replay_authoritative", "verdict_display",
})


@dataclass(frozen=True)
class ValidatedVerdictIntentGroup:
    receipt: dict[str, Any]
    test_payload: dict[str, Any]
    close_payload: dict[str, Any] | None
    cycle_payload: dict[str, Any] | None


def _hex64(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _canonical_object(raw: Any, label: str) -> dict[str, Any]:
    def unique_object(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise VerdictIntentError(f"{label} has duplicate key {key!r}")
            out[key] = value
        return out

    if not isinstance(raw, str):
        raise VerdictIntentError(f"{label} payload is not text")
    try:
        value = json.loads(raw, object_pairs_hook=unique_object)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise VerdictIntentError(f"{label} payload is not valid JSON") from exc
    if not isinstance(value, dict):
        raise VerdictIntentError(f"{label} payload is not an object")
    if canonical_history_payload(value) != raw:
        raise VerdictIntentError(f"{label} payload is not canonical")
    return value


def _aware_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise VerdictIntentError(f"{label} timestamp is not ISO text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise VerdictIntentError(f"{label} timestamp is invalid") from exc
    if parsed.utcoffset() is None:
        raise VerdictIntentError(f"{label} timestamp lacks timezone")
    return parsed


def _finite_number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(float(value))


def _valid_eureka_summary(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"felt", "true", "hallucinated", "reasons", "bf"}
        and type(value.get("felt")) is bool
        and type(value.get("true")) is bool
        and type(value.get("hallucinated")) is bool
        and isinstance(value.get("reasons"), list)
        and all(isinstance(reason, str) for reason in value["reasons"])
        and _finite_number(value.get("bf"))
    )


def _valid_assurance(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"val", "basis"}
        and type(value.get("val")) is int
        and value["val"] in {0, 1, 2, 3}
        and isinstance(value.get("basis"), list)
        and all(isinstance(reason, str) for reason in value["basis"])
    )


def _validate_envelope(
    row: dict[str, Any],
    *,
    event_id: str,
    tree: str,
    tag: str,
    op: str,
    reason: str,
    receipt_sha: str,
    causal_index: int,
    judged_at: str,
) -> dict[str, Any]:
    created_at = _aware_timestamp(row.get("created_at"), event_id)
    if not (
        row.get("id") == event_id
        and row.get("tree") == tree
        and row.get("op") == op
        and row.get("node_tag") == tag
        and row.get("reason") == reason
        and row.get("receipt_sha") == receipt_sha
        and row.get("causal_group") == receipt_sha
        and row.get("causal_index") == causal_index
        and row.get("created_at") == judged_at
        and (
            (row.get("status") == "pending" and row.get("applied_at") is None)
            or (row.get("status") == "applied" and row.get("applied_at") is not None)
        )
    ):
        raise VerdictIntentError(f"{event_id} immutable envelope mismatch")
    if row.get("status") == "applied":
        applied_at = _aware_timestamp(
            row.get("applied_at"), f"{event_id} applied"
        )
        if applied_at < created_at:
            raise VerdictIntentError(
                f"{event_id} applied timestamp precedes creation"
            )
    return _canonical_object(row.get("payload"), event_id)


def _validate_receipt(
    *,
    tree: str,
    tag: str,
    receipt_sha: str,
    receipt: dict[str, Any],
    current: dict[str, Any],
    require_current_effect: bool = True,
) -> dict[str, Any]:
    if not _hex64(receipt_sha):
        raise VerdictIntentError("verdict receipt identity is not full lowercase SHA-256")
    fields = {key: receipt.get(key) for key in RECEIPT_FIELDS}
    if not (
        receipt.get("receipt_sha") == receipt_sha
        and fields["tree"] == tree
        and fields["tag"] == tag
        and fields["verdict_source"] == "scripted"
        and fields["verdict"] in SCRIPTED_RESULT_VERDICTS
        and fields["lakatos_status"] in SCRIPTED_LAKATOS_STATUSES
        and receipt_content_sha(fields) == receipt_sha
    ):
        raise VerdictIntentError("verdict receipt content hash or scope mismatch")
    _aware_timestamp(fields.get("judged_at"), "verdict receipt")
    if require_current_effect and not (
        current.get("current_receipt_sha") == receipt_sha
        and current.get("verdict") == fields["verdict"]
        and current.get("verdict_source") == fields["verdict_source"]
        and current.get("lakatos_status") == fields["lakatos_status"]
        and current.get("metric_value") == fields["metric_value"]
    ):
        raise VerdictIntentError("current node cache diverges from verdict receipt")
    return fields


def _validate_test_payload(
    payload: dict[str, Any],
    *,
    receipt_sha: str,
    receipt: dict[str, Any],
) -> None:
    expected_assurance_raw = verdict_assurance({
        "verdict": receipt.get("verdict"),
        "verdict_source": receipt.get("verdict_source"),
        "current_receipt_sha": receipt_sha,
        "measurement_grade": receipt.get("measurement_grade"),
        "replay_status": receipt.get("replay_status"),
        "measurement_lock_bound": receipt.get("measurement_lock_sha") is not None,
    })
    expected_assurance = {
        "val": expected_assurance_raw["val"],
        "basis": list(expected_assurance_raw.get("basis") or ()),
    }
    expected_display = format_verdict_with_val(
        receipt.get("verdict"), expected_assurance
    )
    if set(payload) != TEST_RESULT_PAYLOAD_KEYS:
        raise VerdictIntentError("test-result payload shape mismatch")
    if not all(_finite_number(payload.get(key)) for key in ("value", "baseline", "delta")):
        raise VerdictIntentError("test-result numeric field is non-finite or mistyped")
    summary = {key: value for key, value in payload.items() if key != "receipt_sha"}
    if not (
        payload.get("receipt_sha") == receipt_sha
        and _hex64(receipt.get("history_payload_sha256"))
        and verdict_history_payload_sha(summary)
            == receipt["history_payload_sha256"]
        and payload.get("verdict") == receipt["verdict"]
        and payload.get("lakatos") == receipt["lakatos_status"]
        and payload.get("value") == receipt["metric_value"]
        and payload.get("script_sha") == receipt["judge_script_sha"]
        and payload.get("script") == receipt["judge_script_path"]
        and payload.get("result_path") == receipt["result_path"]
        and payload.get("result_sha256") == receipt["result_sha256"]
        and payload.get("measurement_lock_sha") == receipt["measurement_lock_sha"]
        and payload.get("source_script_path") == receipt["source_script_path"]
        and payload.get("source_result_path") == receipt["source_result_path"]
        and payload.get("replay_status") == receipt["replay_status"]
        and payload.get("replay_reason") == receipt["replay_reason"]
        and payload.get("regenerated_metric") == receipt["regenerated_metric"]
        and payload.get("assurance") == expected_assurance
        and payload.get("verdict_display") == expected_display
        and isinstance(payload.get("verdict"), str)
        and isinstance(payload.get("lakatos"), str)
        and isinstance(payload.get("metric_verdict"), str)
        and isinstance(payload.get("rule"), str)
        and type(payload.get("freshen")) is bool
        and type(payload.get("novel_server_anchored")) is bool
        and type(payload.get("requires_human")) is bool
        and type(payload.get("script_sha_server_verified")) is bool
        and type(payload.get("replay_authoritative")) is bool
        and payload.get("replay_authoritative")
            == (receipt.get("measurement_lock_sha") is not None)
        and isinstance(payload.get("verdict_display"), str)
        and _valid_assurance(payload.get("assurance"))
        and type(payload.get("qualitative_self_report")) is bool
        and _valid_eureka_summary(payload.get("eureka_open"))
        and _valid_eureka_summary(payload.get("eureka_closed"))
        and (payload.get("novel") is None or type(payload.get("novel")) is bool)
        and (payload.get("attested_by") is None
             or isinstance(payload.get("attested_by"), str))
        and (
            (payload.get("cycle_claim") is None
             and payload.get("cycle_request_sha256") is None)
            or (
                isinstance(payload.get("cycle_claim"), str)
                and payload["cycle_claim"].startswith("cycle-")
                and _hex64(payload.get("cycle_request_sha256"))
                and payload["cycle_claim"]
                    == f"cycle-{payload['cycle_request_sha256']}"
            )
        )
    ):
        raise VerdictIntentError("test-result payload does not bind the receipt")


def validate_verdict_intent_group(
    *,
    tree: str,
    tag: str,
    receipt_sha: str,
    receipt: dict[str, Any],
    current: dict[str, Any],
    outboxes: list[dict[str, Any]],
    closure: dict[str, Any] | None = None,
    require_cycle: bool | None = None,
    require_current_effect: bool = True,
) -> ValidatedVerdictIntentGroup:
    """Validate one current verdict receipt and all history intents in its group."""

    receipt_fields = _validate_receipt(
        tree=tree,
        tag=tag,
        receipt_sha=receipt_sha,
        receipt=receipt,
        current=current,
        require_current_effect=require_current_effect,
    )
    by_index: dict[int, dict[str, Any]] = {}
    for row in outboxes:
        index = row.get("causal_index")
        if type(index) is not int or index not in {0, 1, 2} or index in by_index:
            raise VerdictIntentError("causal group has an invalid or duplicate index")
        by_index[index] = row
    if 0 not in by_index:
        raise VerdictIntentError("causal group lacks test-result predecessor")
    if require_cycle is True and 2 not in by_index:
        raise VerdictIntentError("causal group lacks required cycle result")
    if require_cycle is False and 2 in by_index:
        raise VerdictIntentError("unexpected cycle result in direct-submit group")

    test_id = f"ob-test-result-{receipt_sha}"
    test_payload = _validate_envelope(
        by_index[0], event_id=test_id, tree=tree, tag=tag,
        op="test_result", reason="test_result_commit_intent",
        receipt_sha=receipt_sha, causal_index=0,
        judged_at=receipt_fields["judged_at"],
    )
    request_sha = by_index[0].get("request_sha256")
    if not _hex64(request_sha):
        raise VerdictIntentError("test-result intent lacks exact request identity")
    _validate_test_payload(
        test_payload,
        receipt_sha=receipt_sha,
        receipt=receipt_fields,
    )
    if test_payload.get("request_sha256") != request_sha:
        raise VerdictIntentError("test-result request identity is not receipt-sealed")
    sealed_cycle = test_payload.get("cycle_claim") is not None
    if sealed_cycle != (2 in by_index):
        raise VerdictIntentError(
            "sealed cycle command and cycle-result intent presence disagree"
        )

    close_payload = None
    close_id = f"ob-question-close-{receipt_sha}"
    if 1 in by_index:
        close_payload = _validate_envelope(
            by_index[1], event_id=close_id, tree=tree, tag=tag,
            op="question_close", reason="question_close_commit_intent",
            receipt_sha=receipt_sha, causal_index=1,
            judged_at=receipt_fields["judged_at"],
        )
        if not (
            set(close_payload) == {"question", "receipt_sha", "trigger", "verdict"}
            and close_payload.get("question") == receipt_fields["target_id"]
            and close_payload.get("receipt_sha") == receipt_sha
            and close_payload.get("trigger") == "ADJUDICATED"
            and close_payload.get("verdict") == receipt_fields["verdict"]
            and receipt_backed_conclusive(
                receipt_fields["verdict"],
                receipt_sha,
                assurance_level=test_payload["assurance"]["val"],
                qualitative_self_report=test_payload[
                    "qualitative_self_report"
                ],
            )
            and closure is not None
            and closure.get("question_state") == "CLOSED"
            and closure.get("closure_id") == receipt_sha
            and closure.get("closure_tree") == tree
            and closure.get("closure_question") == receipt_fields["target_id"]
            and closure.get("closure_trigger") == "ADJUDICATED"
            and closure.get("closure_verdict") == receipt_fields["verdict"]
            and closure.get("closure_receipt_sha") == receipt_sha
            and closure.get("closure_bound") is True
            and closure.get("closure_at") == receipt_fields["judged_at"]
            and closure.get("closure_closed_by") == tag
            and isinstance(closure.get("question_closed_by"), list)
            and tag in closure["question_closed_by"]
            and isinstance(closure.get("question_closed_events"), list)
            and receipt_sha in closure["question_closed_events"]
            and closure.get("closure_global_count") == 1
            and closure.get("closes_rel_count") == 1
            and closure.get("closes_rel_receipt_sha") == receipt_sha
            and closure.get("closes_rel_verdict") == receipt_fields["verdict"]
            and closure.get("closes_rel_at") == receipt_fields["judged_at"]
        ):
            raise VerdictIntentError("question-close intent lacks exact FSM effect binding")
    elif closure is not None and (
        closure.get("closure_id") is not None
        or closure.get("closure_global_count") not in {None, 0}
        or closure.get("closes_rel_count") not in {None, 0}
    ):
        raise VerdictIntentError("closure effect exists without its history intent")

    cycle_payload = None
    if 2 in by_index:
        cycle_row = by_index[2]
        cycle_id = cycle_row.get("id")
        if not (
            isinstance(cycle_id, str)
            and re.fullmatch(r"ob-cycle-result-[0-9a-f]{64}", cycle_id)
        ):
            raise VerdictIntentError("cycle-result intent identity is malformed")
        cycle_payload = _validate_envelope(
            cycle_row, event_id=cycle_id, tree=tree, tag=tag,
            op="cycle_result", reason="cycle_result_commit_intent",
            receipt_sha=receipt_sha, causal_index=2,
            judged_at=receipt_fields["judged_at"],
        )
        result = cycle_payload.get("result")
        claim_suffix = cycle_id.removeprefix("ob-cycle-result-")
        expected_dependencies = [test_id, *([close_id] if close_payload else [])]
        if not (
            set(cycle_payload) == {
                "cycle_claim", "cycle_request", "dependent_history_event_ids",
                "result", "verdict_receipt_sha",
            }
            and cycle_payload.get("cycle_claim") == f"cycle-{claim_suffix}"
            and cycle_payload.get("cycle_claim") == test_payload["cycle_claim"]
            and test_payload.get("cycle_request_sha256") == claim_suffix
            and isinstance(cycle_payload.get("cycle_request"), list)
            and len(cycle_payload["cycle_request"]) == 2
            and cycle_payload["cycle_request"][0] == tree
            and isinstance(cycle_payload["cycle_request"][1], dict)
            and hashlib.sha256(json.dumps(
                cycle_payload["cycle_request"],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")).hexdigest() == claim_suffix
            and cycle_payload.get("verdict_receipt_sha") == receipt_sha
            and cycle_payload.get("dependent_history_event_ids")
                == expected_dependencies
            and isinstance(result, dict)
            and set(result) == {
                "delta", "lakatos", "novel", "novel_server_anchored",
                "verdict",
            }
            and result.get("verdict") == test_payload["verdict"]
            and result.get("lakatos") == test_payload["lakatos"]
            and result.get("delta") == test_payload["delta"]
            and result.get("novel") == test_payload["novel"]
            and result.get("novel_server_anchored")
                == test_payload["novel_server_anchored"]
        ):
            raise VerdictIntentError("cycle-result intent disagrees with its predecessors")

    return ValidatedVerdictIntentGroup(
        receipt=receipt_fields,
        test_payload=test_payload,
        close_payload=close_payload,
        cycle_payload=cycle_payload,
    )
