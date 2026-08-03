"""Pure authorization for durable Gate-3 temporal history intents.

The adjunct node and its outbox are only projection authority when their
content identities, physical topology, receipt ancestry, policy, signatures,
and causal ordering all rederive.  Candidate classification is deliberately
broad so a malformed protected row can never downgrade into generic replay.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
from typing import Any, Literal, Mapping

from lakatos.io.reconcile import canonical_history_payload
from lakatos.temporal import two_ended_temporal_sidecar_sha256
from server.contexts.tree.receipt_chain import ReceiptChainIndex
from server.contexts.tree.temporal_proof import (
    TemporalProofInvalid,
    canonical_policy_json,
    canonical_prediction_commitment_json,
    canonical_sidecar_json,
    derive_temporal_authority_policy,
    parse_canonical_policy,
    parse_canonical_prediction_commitment,
    parse_canonical_sidecar,
    prediction_temporal_commitment_sha256,
    verify_prediction_temporal_commitment,
    verify_prediction_temporal_commitment_content,
    verify_sealed_prediction_temporal_commitment,
    verify_two_ended_temporal_sidecar_prefix,
)


PREDICTION_TEMPORAL_OP = "prediction_temporal_commitment"
PREDICTION_TEMPORAL_REASON = "prediction_temporal_commitment_intent"
PREDICTION_TEMPORAL_PREFIX = "ob-prediction-temporal-"
PREDICTION_TEMPORAL_HISTORY_SCHEMA = (
    "lakatotree-prediction-temporal-history/v1"
)
TEMPORAL_SIDECAR_OP = "temporal_proof_sidecar"
TEMPORAL_SIDECAR_REASON = "temporal_proof_sidecar_intent"
TEMPORAL_SIDECAR_PREFIX = "ob-temporal-proof-"
TEMPORAL_SIDECAR_HISTORY_SCHEMA = "lakatotree-temporal-sidecar-history/v1"

_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_COMMITMENT_RECORD_KEYS = frozenset({
    "commitment_sha256",
    "prediction_receipt_sha256",
    "authority_policy_sha256",
    "tree_incarnation_id",
    "tree",
    "tag",
    "commitment_json",
    "authority_policy_json",
    "created_at",
})
_SIDECAR_RECORD_KEYS = frozenset({
    "sidecar_sha256",
    "verdict_receipt_sha256",
    "prediction_receipt_sha256",
    "prediction_temporal_commitment_sha256",
    "receipt_graph_sha256",
    "authority_policy_sha256",
    "tree_incarnation_id",
    "tree",
    "tag",
    "sidecar_json",
    "authority_policy_json",
    "created_at",
})
_FORBIDDEN_OUTBOX_METADATA = (
    "adopted_by",
    "adopted_at",
    "causal_group",
    "causal_index",
    "request_sha256",
    "demoted_tag",
    "demoted_receipt_sha",
)
_COMMITMENT_COUNT_KEYS = (
    "outbox_copies",
    "trees",
    "node_bindings",
    "nodes",
    "local_bindings",
    "adjunct_nodes",
    "global_bindings",
    "sha_copies",
    "target_copies",
    "endpoint_bindings",
    "global_endpoint_bindings",
)
_SIDECAR_COUNT_KEYS = (
    "outbox_copies",
    "trees",
    "node_bindings",
    "nodes",
    "local_bindings",
    "adjunct_nodes",
    "global_bindings",
    "sha_copies",
    "target_copies",
    "commitment_bindings",
    "global_commitment_bindings",
    "prediction_bindings",
    "global_prediction_bindings",
    "verdict_bindings",
    "global_verdict_bindings",
)


# One row per physical adjunct.  These scans intentionally start from the
# adjunct labels, not the outbox, so orphan and malformed nodes remain visible
# before uniqueness DDL and during every storage audit.
PREDICTION_TEMPORAL_IDENTITY_CYPHER = """
MATCH (adjunct:PredictionTemporalCommitment)
WITH adjunct,
     'ob-prediction-temporal-'+adjunct.commitment_sha256 AS expected_event_id
OPTIONAL MATCH (outbox:OutboxEntry {id:expected_event_id})
WITH adjunct, expected_event_id, collect(outbox) AS outboxes
RETURN elementId(adjunct) AS adjunct_element_id,
       expected_event_id AS event_id,
       size(outboxes) AS outbox_copies,
       CASE WHEN size(outboxes)=1 THEN properties(outboxes[0]) ELSE null END
         AS outbox,
       COUNT { MATCH (:LakatosTree)-[:HAS_NODE]->
               ()-[:HAS_PREDICTION_TEMPORAL_COMMITMENT]->(adjunct) } AS trees,
       COUNT { MATCH (:LakatosTree)-[r:HAS_NODE]->
               ()-[:HAS_PREDICTION_TEMPORAL_COMMITMENT]->(adjunct) } AS node_bindings,
       COUNT { MATCH (:LakatosTree)-[:HAS_NODE]->
               (owner)-[:HAS_PREDICTION_TEMPORAL_COMMITMENT]->(adjunct) } AS nodes,
       head([(tree:LakatosTree)-[:HAS_NODE]->
              (owner)-[:HAS_PREDICTION_TEMPORAL_COMMITMENT]->(adjunct)
              | properties(tree)]) AS tree_record,
       head([(:LakatosTree)-[:HAS_NODE]->
              (owner)-[:HAS_PREDICTION_TEMPORAL_COMMITMENT]->(adjunct)
              | properties(owner)]) AS node_record,
       COUNT { MATCH ()-[:HAS_PREDICTION_TEMPORAL_COMMITMENT]->
               (adjunct) } AS local_bindings,
       1 AS adjunct_nodes,
       COUNT { MATCH ()-[:HAS_PREDICTION_TEMPORAL_COMMITMENT]->
               (adjunct) } AS global_bindings,
       COUNT { MATCH (:PredictionTemporalCommitment {
                 commitment_sha256:adjunct.commitment_sha256}) } AS sha_copies,
       COUNT { MATCH (:PredictionTemporalCommitment {
                 tree_incarnation_id:adjunct.tree_incarnation_id,
                 tree:adjunct.tree, tag:adjunct.tag,
                 prediction_receipt_sha256:
                   adjunct.prediction_receipt_sha256}) } AS target_copies,
       COUNT { MATCH (adjunct)-[:COMMITS_TO_PREDICTION]->
               (:VerdictReceipt {
                 receipt_sha:adjunct.prediction_receipt_sha256}) }
         AS endpoint_bindings,
       COUNT { MATCH (adjunct)-[:COMMITS_TO_PREDICTION]->() }
         AS global_endpoint_bindings,
       labels(adjunct) AS adjunct_labels,
       [()-[r:HAS_PREDICTION_TEMPORAL_COMMITMENT]->(adjunct)
          | properties(r)]
       + [(adjunct)-[r:COMMITS_TO_PREDICTION]->() | properties(r)]
         AS relationship_property_keys,
       properties(adjunct) AS adjunct_record
ORDER BY adjunct_element_id
"""


TEMPORAL_SIDECAR_IDENTITY_CYPHER = """
MATCH (adjunct:TemporalProofSidecar)
WITH adjunct,
     'ob-temporal-proof-'+adjunct.sidecar_sha256 AS expected_event_id
OPTIONAL MATCH (outbox:OutboxEntry {id:expected_event_id})
WITH adjunct, expected_event_id, collect(outbox) AS outboxes
OPTIONAL MATCH (adjunct)-[:USES_PREDICTION_COMMITMENT]->
  (linked:PredictionTemporalCommitment {
    commitment_sha256:adjunct.prediction_temporal_commitment_sha256})
WITH adjunct, expected_event_id, outboxes,
     collect(DISTINCT linked) AS linked_commitments
WITH adjunct, expected_event_id, outboxes,
     CASE WHEN size(linked_commitments)=1
          THEN linked_commitments[0] ELSE null END AS commitment
OPTIONAL MATCH (commitment_outbox:OutboxEntry {
  id:'ob-prediction-temporal-'+commitment.commitment_sha256})
WITH adjunct, expected_event_id, outboxes, commitment,
     collect(commitment_outbox) AS commitment_outboxes
RETURN elementId(adjunct) AS adjunct_element_id,
       expected_event_id AS event_id,
       size(outboxes) AS outbox_copies,
       CASE WHEN size(outboxes)=1 THEN properties(outboxes[0]) ELSE null END
         AS outbox,
       COUNT { MATCH (:LakatosTree)-[:HAS_NODE]->
               ()-[:HAS_TEMPORAL_PROOF]->(adjunct) } AS trees,
       COUNT { MATCH (:LakatosTree)-[r:HAS_NODE]->
               ()-[:HAS_TEMPORAL_PROOF]->(adjunct) } AS node_bindings,
       COUNT { MATCH (:LakatosTree)-[:HAS_NODE]->
               (owner)-[:HAS_TEMPORAL_PROOF]->(adjunct) } AS nodes,
       head([(tree:LakatosTree)-[:HAS_NODE]->
              (owner)-[:HAS_TEMPORAL_PROOF]->(adjunct)
              | properties(tree)]) AS tree_record,
       head([(:LakatosTree)-[:HAS_NODE]->
              (owner)-[:HAS_TEMPORAL_PROOF]->(adjunct)
              | properties(owner)]) AS node_record,
       COUNT { MATCH ()-[:HAS_TEMPORAL_PROOF]->(adjunct) } AS local_bindings,
       1 AS adjunct_nodes,
       COUNT { MATCH ()-[:HAS_TEMPORAL_PROOF]->(adjunct) } AS global_bindings,
       COUNT { MATCH (:TemporalProofSidecar {
                 sidecar_sha256:adjunct.sidecar_sha256}) } AS sha_copies,
       COUNT { MATCH (:TemporalProofSidecar {
                 tree_incarnation_id:adjunct.tree_incarnation_id,
                 tree:adjunct.tree, tag:adjunct.tag,
                 verdict_receipt_sha256:adjunct.verdict_receipt_sha256}) }
         AS target_copies,
       COUNT { MATCH (adjunct)-[:USES_PREDICTION_COMMITMENT]->
               (:PredictionTemporalCommitment {
                 commitment_sha256:
                   adjunct.prediction_temporal_commitment_sha256}) }
         AS commitment_bindings,
       COUNT { MATCH (adjunct)-[:USES_PREDICTION_COMMITMENT]->() }
         AS global_commitment_bindings,
       COUNT { MATCH (adjunct)-[:STARTS_AT]->(:VerdictReceipt {
                 receipt_sha:adjunct.prediction_receipt_sha256}) }
         AS prediction_bindings,
       COUNT { MATCH (adjunct)-[:STARTS_AT]->() }
         AS global_prediction_bindings,
       COUNT { MATCH (adjunct)-[:ENDS_AT]->(:VerdictReceipt {
                 receipt_sha:adjunct.verdict_receipt_sha256}) }
         AS verdict_bindings,
       COUNT { MATCH (adjunct)-[:ENDS_AT]->() }
         AS global_verdict_bindings,
       labels(adjunct) AS adjunct_labels,
       [()-[r:HAS_TEMPORAL_PROOF]->(adjunct) | properties(r)]
       + [(adjunct)-[r:USES_PREDICTION_COMMITMENT]->() | properties(r)]
       + [(adjunct)-[r:STARTS_AT]->() | properties(r)]
       + [(adjunct)-[r:ENDS_AT]->() | properties(r)]
         AS relationship_property_keys,
       properties(adjunct) AS adjunct_record,
       CASE WHEN size(commitment_outboxes)=1
            THEN properties(commitment_outboxes[0]) ELSE null END
         AS commitment_outbox,
       properties(commitment) AS commitment_record,
       {
         outbox_copies:size(commitment_outboxes),
         trees:COUNT { MATCH (:LakatosTree)-[:HAS_NODE]->
           (owner)-[:HAS_TEMPORAL_PROOF]->(adjunct)
           MATCH (owner)-[:HAS_PREDICTION_TEMPORAL_COMMITMENT]->(commitment) },
         node_bindings:COUNT { MATCH (:LakatosTree)-[r:HAS_NODE]->
           (owner)-[:HAS_TEMPORAL_PROOF]->(adjunct)
           MATCH (owner)-[:HAS_PREDICTION_TEMPORAL_COMMITMENT]->(commitment) },
         nodes:COUNT { MATCH (:LakatosTree)-[:HAS_NODE]->
           (owner)-[:HAS_TEMPORAL_PROOF]->(adjunct)
           MATCH (owner)-[:HAS_PREDICTION_TEMPORAL_COMMITMENT]->(commitment) },
         local_bindings:COUNT { MATCH ()-[:HAS_PREDICTION_TEMPORAL_COMMITMENT]->
           (commitment) },
         adjunct_nodes:CASE WHEN commitment IS NULL THEN 0 ELSE 1 END,
         global_bindings:COUNT { MATCH ()-[:HAS_PREDICTION_TEMPORAL_COMMITMENT]->
           (commitment) },
         sha_copies:COUNT { MATCH (:PredictionTemporalCommitment {
           commitment_sha256:commitment.commitment_sha256}) },
         target_copies:COUNT { MATCH (:PredictionTemporalCommitment {
           tree_incarnation_id:commitment.tree_incarnation_id,
           tree:commitment.tree, tag:commitment.tag,
           prediction_receipt_sha256:commitment.prediction_receipt_sha256}) },
         endpoint_bindings:COUNT { MATCH (commitment)-[:COMMITS_TO_PREDICTION]->
           (:VerdictReceipt {receipt_sha:commitment.prediction_receipt_sha256}) },
         global_endpoint_bindings:COUNT {
           MATCH (commitment)-[:COMMITS_TO_PREDICTION]->() },
         expected_label:'PredictionTemporalCommitment',
         adjunct_labels:labels(commitment),
         relationship_property_keys:
           [()-[r:HAS_PREDICTION_TEMPORAL_COMMITMENT]->(commitment)
              | properties(r)]
           + [(commitment)-[r:COMMITS_TO_PREDICTION]->() | properties(r)]
       } AS commitment_identity_counts
ORDER BY adjunct_element_id
"""


class TemporalIntentError(ValueError):
    """A temporal adjunct/outbox snapshot lacks projection authority."""


@dataclass(frozen=True)
class ValidatedTemporalIntent:
    kind: Literal["commitment", "sidecar"]
    outbox: dict[str, Any]
    payload: dict[str, Any]
    object_sha256: str
    receipt_sha256: str


def classify_temporal_intent(
    entry: Mapping[str, Any],
) -> Literal["commitment", "sidecar"] | None:
    event_id = entry.get("id")
    commitment = (
        entry.get("op") == PREDICTION_TEMPORAL_OP
        or entry.get("reason") == PREDICTION_TEMPORAL_REASON
        or (
            isinstance(event_id, str)
            and event_id.startswith(PREDICTION_TEMPORAL_PREFIX)
        )
    )
    sidecar = (
        entry.get("op") == TEMPORAL_SIDECAR_OP
        or entry.get("reason") == TEMPORAL_SIDECAR_REASON
        or (
            isinstance(event_id, str)
            and event_id.startswith(TEMPORAL_SIDECAR_PREFIX)
        )
    )
    if commitment and sidecar:
        raise TemporalIntentError("temporal intent mixes protected namespaces")
    if commitment:
        return "commitment"
    if sidecar:
        return "sidecar"
    return None


def _canonical_object(raw: Any, label: str) -> dict[str, Any]:
    def unique_object(pairs):
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise TemporalIntentError(
                    f"{label} has duplicate key {key!r}"
                )
            value[key] = item
        return value

    if not isinstance(raw, str):
        raise TemporalIntentError(f"{label} is not JSON text")
    try:
        value = json.loads(raw, object_pairs_hook=unique_object)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TemporalIntentError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict) or canonical_history_payload(value) != raw:
        raise TemporalIntentError(f"{label} is not a canonical object")
    return value


def _time(value: Any, label: str) -> datetime:
    if hasattr(value, "iso_format"):
        value = value.iso_format()
    if not isinstance(value, str) or not value:
        raise TemporalIntentError(f"{label} is not an aware timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise TemporalIntentError(f"{label} is not an aware timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TemporalIntentError(f"{label} is not an aware timestamp")
    return parsed.astimezone(timezone.utc)


def _exact_counts(identity: Mapping[str, Any], keys: tuple[str, ...]) -> None:
    if any(type(identity.get(key)) is not int or identity.get(key) != 1 for key in keys):
        raise TemporalIntentError("temporal physical identity is not exact")
    if set(identity.get("adjunct_labels") or ()) != {
        identity.get("expected_label")
    }:
        raise TemporalIntentError("temporal adjunct label set is not exact")
    relationship_keys = identity.get("relationship_property_keys")
    if not (
        isinstance(relationship_keys, list)
        and relationship_keys
        and all(isinstance(item, Mapping) and not item for item in relationship_keys)
    ):
        raise TemporalIntentError("temporal relationship carries mutable properties")


def _scope(
    *,
    tree_record: Mapping[str, Any],
    node_record: Mapping[str, Any],
    chain_index: ReceiptChainIndex,
) -> tuple[str, str, str, tuple[str, ...]]:
    tree = tree_record.get("name")
    tag = node_record.get("tag")
    if not (
        isinstance(tree, str)
        and tree
        and isinstance(tag, str)
        and tag
    ):
        raise TemporalIntentError("temporal owner scope is malformed")
    scope = (tree, tag)
    incarnation = chain_index.tree_incarnation_by_scope.get(scope)
    ordered = chain_index.ordered_ancestry_by_scope.get(scope)
    if not isinstance(incarnation, str) or not incarnation or not ordered:
        raise TemporalIntentError("temporal owner lacks an exact receipt incarnation")
    return tree, tag, incarnation, ordered


def _envelope(
    *,
    outbox: Mapping[str, Any],
    kind: Literal["commitment", "sidecar"],
    object_sha256: str,
    receipt_sha256: str,
    tree: str,
    tag: str,
    record_created_at: Any,
    require_current_effect: bool,
) -> tuple[dict[str, Any], datetime]:
    expected = {
        "commitment": (
            PREDICTION_TEMPORAL_PREFIX,
            PREDICTION_TEMPORAL_OP,
            PREDICTION_TEMPORAL_REASON,
        ),
        "sidecar": (
            TEMPORAL_SIDECAR_PREFIX,
            TEMPORAL_SIDECAR_OP,
            TEMPORAL_SIDECAR_REASON,
        ),
    }[kind]
    prefix, op, reason = expected
    event_id = f"{prefix}{object_sha256}"
    created_at = _time(outbox.get("created_at"), "outbox created_at")
    if _time(record_created_at, "temporal record created_at") != created_at:
        raise TemporalIntentError("temporal record/outbox creation times diverge")
    status = outbox.get("status")
    state_ok = (
        status == "pending" and outbox.get("applied_at") is None
    ) or (
        status == "applied" and outbox.get("applied_at") is not None
    )
    if require_current_effect and status != "pending":
        state_ok = False
    if not state_ok:
        raise TemporalIntentError("temporal outbox state is invalid")
    if status == "applied" and _time(
        outbox.get("applied_at"), "outbox applied_at"
    ) < created_at:
        raise TemporalIntentError("temporal outbox applied before creation")
    if not (
        _HEX64.fullmatch(object_sha256 or "")
        and _HEX64.fullmatch(receipt_sha256 or "")
        and outbox.get("id") == event_id
        and outbox.get("tree") == tree
        and outbox.get("node_tag") == tag
        and outbox.get("op") == op
        and outbox.get("reason") == reason
        and outbox.get("receipt_sha") == receipt_sha256
        and all(outbox.get(key) is None for key in _FORBIDDEN_OUTBOX_METADATA)
    ):
        raise TemporalIntentError("temporal outbox immutable envelope mismatch")
    if classify_temporal_intent(outbox) != kind:
        raise TemporalIntentError("temporal outbox namespace mismatch")
    return _canonical_object(outbox.get("payload"), "temporal outbox payload"), created_at


def _receipt_prefix(
    *,
    chain_index: ReceiptChainIndex,
    scope: tuple[str, str],
    prediction_sha: str,
    verdict_sha: str | None = None,
) -> tuple[str, ...]:
    ordered = chain_index.ordered_ancestry_by_scope.get(scope, ())
    target = prediction_sha if verdict_sha is None else verdict_sha
    try:
        target_index = ordered.index(target)
    except ValueError as exc:
        raise TemporalIntentError("temporal target is not current-chain ancestry") from exc
    prefix = ordered[: target_index + 1]
    if prediction_sha not in prefix:
        raise TemporalIntentError("temporal target lacks prediction ancestry")
    return prefix


def validate_prediction_temporal_commitment_intent(
    *,
    outbox: Mapping[str, Any],
    tree_record: Mapping[str, Any],
    node_record: Mapping[str, Any],
    commitment_record: Mapping[str, Any],
    identity_counts: Mapping[str, Any],
    chain_index: ReceiptChainIndex,
    require_current_effect: bool,
) -> ValidatedTemporalIntent:
    _exact_counts(identity_counts, _COMMITMENT_COUNT_KEYS)
    record = dict(commitment_record)
    if set(record) != _COMMITMENT_RECORD_KEYS:
        raise TemporalIntentError("prediction temporal record shape is not exact")
    tree, tag, incarnation, ordered = _scope(
        tree_record=tree_record,
        node_record=node_record,
        chain_index=chain_index,
    )
    scope = (tree, tag)
    commitment_sha = record.get("commitment_sha256")
    prediction_sha = record.get("prediction_receipt_sha256")
    payload, created_at = _envelope(
        outbox=outbox,
        kind="commitment",
        object_sha256=commitment_sha,
        receipt_sha256=prediction_sha,
        tree=tree,
        tag=tag,
        record_created_at=record.get("created_at"),
        require_current_effect=require_current_effect,
    )
    commitment = parse_canonical_prediction_commitment(
        record.get("commitment_json")
    )
    policy = parse_canonical_policy(record.get("authority_policy_json"))
    if not (
        record.get("tree_incarnation_id") == incarnation
        and record.get("tree") == tree
        and record.get("tag") == tag
        and record.get("authority_policy_sha256")
        == commitment.get("authority_policy_sha256")
        and record.get("commitment_json")
        == canonical_prediction_commitment_json(commitment)
        and record.get("authority_policy_json") == canonical_policy_json(policy)
        and prediction_temporal_commitment_sha256(commitment) == commitment_sha
        and payload
        == {
            "schema_version": PREDICTION_TEMPORAL_HISTORY_SCHEMA,
            "commitment_sha256": commitment_sha,
            "commitment": commitment,
        }
    ):
        raise TemporalIntentError("prediction temporal content binding mismatch")
    _receipt_prefix(
        chain_index=chain_index,
        scope=scope,
        prediction_sha=prediction_sha,
    )
    prediction_receipt = chain_index.receipt_by_sha.get(prediction_sha)
    if not isinstance(prediction_receipt, Mapping):
        raise TemporalIntentError("prediction receipt is absent")
    current = chain_index.current_by_scope.get(scope)
    try:
        if require_current_effect:
            current_policy = derive_temporal_authority_policy(
                tree, tree_record, evaluated_at=created_at
            )
            if current_policy != policy:
                raise TemporalIntentError(
                    "pending prediction temporal policy is no longer current"
                )
            verify_prediction_temporal_commitment(
                commitment,
                stored_commitment_sha256=commitment_sha,
                authority_policy=policy,
                tree_incarnation_id=incarnation,
                tree=tree,
                tag=tag,
                prediction_receipt_sha256=prediction_sha,
                prediction_receipt=prediction_receipt,
                current_head_sha256=current,
                evaluated_at=created_at,
            )
        else:
            verify_prediction_temporal_commitment_content(
                commitment,
                stored_commitment_sha256=commitment_sha,
                authority_policy=policy,
                tree_incarnation_id=incarnation,
                tree=tree,
                tag=tag,
                prediction_receipt_sha256=prediction_sha,
                prediction_receipt=prediction_receipt,
                evaluated_at=created_at,
            )
            if current != prediction_sha:
                sealed = [
                    chain_index.receipt_by_sha[receipt_sha]
                    for receipt_sha in ordered
                    if receipt_sha != prediction_sha
                    and chain_index.receipt_by_sha[receipt_sha].get(
                        "prediction_temporal_commitment_sha256"
                    ) == commitment_sha
                ]
                if not sealed:
                    raise TemporalIntentError(
                        "historical prediction commitment lacks a verdict seal"
                    )
                seal = sealed[0]
                verify_sealed_prediction_temporal_commitment(
                    commitment,
                    stored_commitment_sha256=commitment_sha,
                    authority_policy=policy,
                    tree_incarnation_id=incarnation,
                    tree=tree,
                    tag=tag,
                    prediction_receipt_sha256=prediction_sha,
                    prediction_receipt=prediction_receipt,
                    current_head_sha256=seal["receipt_sha"],
                    verdict_receipt=seal,
                    evaluated_at=created_at,
                )
    except TemporalIntentError:
        raise
    except (TemporalProofInvalid, KeyError, TypeError, ValueError) as exc:
        raise TemporalIntentError(
            f"prediction temporal verification failed: {exc}"
        ) from exc
    return ValidatedTemporalIntent(
        kind="commitment",
        outbox=dict(outbox),
        payload=payload,
        object_sha256=commitment_sha,
        receipt_sha256=prediction_sha,
    )


def validate_temporal_proof_sidecar_intent(
    *,
    outbox: Mapping[str, Any],
    tree_record: Mapping[str, Any],
    node_record: Mapping[str, Any],
    sidecar_record: Mapping[str, Any],
    identity_counts: Mapping[str, Any],
    commitment_outbox: Mapping[str, Any],
    commitment_record: Mapping[str, Any],
    commitment_identity_counts: Mapping[str, Any],
    chain_index: ReceiptChainIndex,
    require_current_effect: bool,
) -> ValidatedTemporalIntent:
    _exact_counts(identity_counts, _SIDECAR_COUNT_KEYS)
    record = dict(sidecar_record)
    if set(record) != _SIDECAR_RECORD_KEYS:
        raise TemporalIntentError("temporal sidecar record shape is not exact")
    tree, tag, incarnation, _ordered = _scope(
        tree_record=tree_record,
        node_record=node_record,
        chain_index=chain_index,
    )
    scope = (tree, tag)
    sidecar_sha = record.get("sidecar_sha256")
    verdict_sha = record.get("verdict_receipt_sha256")
    prediction_sha = record.get("prediction_receipt_sha256")
    payload, created_at = _envelope(
        outbox=outbox,
        kind="sidecar",
        object_sha256=sidecar_sha,
        receipt_sha256=verdict_sha,
        tree=tree,
        tag=tag,
        record_created_at=record.get("created_at"),
        require_current_effect=require_current_effect,
    )
    sidecar = parse_canonical_sidecar(record.get("sidecar_json"))
    policy = parse_canonical_policy(record.get("authority_policy_json"))
    if not (
        record.get("tree_incarnation_id") == incarnation
        and record.get("tree") == tree
        and record.get("tag") == tag
        and record.get("authority_policy_sha256")
        == sidecar.get("authority_policy_sha256")
        and record.get("prediction_receipt_sha256")
        == sidecar.get("prediction_receipt_sha256")
        and record.get("verdict_receipt_sha256")
        == sidecar.get("verdict_receipt_sha256")
        and record.get("receipt_graph_sha256")
        == sidecar.get("receipt_graph_sha256")
        and record.get("sidecar_json") == canonical_sidecar_json(sidecar)
        and record.get("authority_policy_json") == canonical_policy_json(policy)
        and two_ended_temporal_sidecar_sha256(sidecar) == sidecar_sha
        and payload
        == {
            "schema_version": TEMPORAL_SIDECAR_HISTORY_SCHEMA,
            "sidecar_sha256": sidecar_sha,
            "sidecar": sidecar,
        }
    ):
        raise TemporalIntentError("temporal sidecar content binding mismatch")
    commitment_validated = validate_prediction_temporal_commitment_intent(
        outbox=commitment_outbox,
        tree_record=tree_record,
        node_record=node_record,
        commitment_record=commitment_record,
        identity_counts=commitment_identity_counts,
        chain_index=chain_index,
        require_current_effect=False,
    )
    if commitment_outbox.get("status") != "applied":
        raise TemporalIntentError("temporal sidecar commitment is not projected")
    commitment_applied_at = _time(
        commitment_outbox.get("applied_at"), "commitment applied_at"
    )
    commitment_created_at = _time(
        commitment_record.get("created_at"), "commitment created_at"
    )
    if not commitment_created_at <= commitment_applied_at <= created_at:
        raise TemporalIntentError("temporal sidecar causal history is out of order")
    commitment = parse_canonical_prediction_commitment(
        commitment_record.get("commitment_json")
    )
    if not (
        commitment_validated.object_sha256
        == record.get("prediction_temporal_commitment_sha256")
        and sidecar.get("prediction_anchors")
        == commitment.get("prediction_anchors")
    ):
        raise TemporalIntentError("sidecar does not reuse the committed T1")
    prefix = _receipt_prefix(
        chain_index=chain_index,
        scope=scope,
        prediction_sha=prediction_sha,
        verdict_sha=verdict_sha,
    )
    if require_current_effect:
        if chain_index.current_by_scope.get(scope) != verdict_sha:
            raise TemporalIntentError("pending temporal sidecar target is no longer current")
        try:
            current_policy = derive_temporal_authority_policy(
                tree, tree_record, evaluated_at=created_at
            )
        except TemporalProofInvalid as exc:
            raise TemporalIntentError(
                f"pending temporal policy cannot be derived: {exc}"
            ) from exc
        if current_policy != policy:
            raise TemporalIntentError(
                "pending temporal sidecar policy is no longer current"
            )
    try:
        verify_two_ended_temporal_sidecar_prefix(
            sidecar,
            stored_sidecar_sha256=sidecar_sha,
            authority_policy=policy,
            tree=tree,
            tag=tag,
            tree_incarnation_id=incarnation,
            chain=prefix,
            receipt_by_sha=chain_index.receipt_by_sha,
            evaluated_at=created_at,
        )
    except (TemporalProofInvalid, KeyError, TypeError, ValueError) as exc:
        raise TemporalIntentError(
            f"temporal sidecar verification failed: {exc}"
        ) from exc
    return ValidatedTemporalIntent(
        kind="sidecar",
        outbox=dict(outbox),
        payload=payload,
        object_sha256=sidecar_sha,
        receipt_sha256=verdict_sha,
    )


def _row_identity_counts(
    row: Mapping[str, Any],
    *,
    expected_label: str,
    keys: tuple[str, ...],
) -> dict[str, Any]:
    return {
        **{key: row.get(key) for key in keys},
        "expected_label": expected_label,
        "adjunct_labels": row.get("adjunct_labels"),
        "relationship_property_keys": row.get("relationship_property_keys"),
    }


def validate_prediction_temporal_identity_row(
    row: Mapping[str, Any],
    *,
    chain_index: ReceiptChainIndex,
    require_current_effect: bool,
) -> ValidatedTemporalIntent:
    if not all(
        isinstance(row.get(key), Mapping)
        for key in ("outbox", "tree_record", "node_record", "adjunct_record")
    ):
        raise TemporalIntentError(
            "prediction temporal authority snapshot is incomplete"
        )
    return validate_prediction_temporal_commitment_intent(
        outbox=row["outbox"],
        tree_record=row["tree_record"],
        node_record=row["node_record"],
        commitment_record=row["adjunct_record"],
        identity_counts=_row_identity_counts(
            row,
            expected_label="PredictionTemporalCommitment",
            keys=_COMMITMENT_COUNT_KEYS,
        ),
        chain_index=chain_index,
        require_current_effect=require_current_effect,
    )


def validate_temporal_sidecar_identity_row(
    row: Mapping[str, Any],
    *,
    chain_index: ReceiptChainIndex,
    require_current_effect: bool,
) -> ValidatedTemporalIntent:
    if not all(
        isinstance(row.get(key), Mapping)
        for key in (
            "outbox",
            "tree_record",
            "node_record",
            "adjunct_record",
            "commitment_outbox",
            "commitment_record",
            "commitment_identity_counts",
        )
    ):
        raise TemporalIntentError("temporal sidecar authority snapshot is incomplete")
    return validate_temporal_proof_sidecar_intent(
        outbox=row["outbox"],
        tree_record=row["tree_record"],
        node_record=row["node_record"],
        sidecar_record=row["adjunct_record"],
        identity_counts=_row_identity_counts(
            row,
            expected_label="TemporalProofSidecar",
            keys=_SIDECAR_COUNT_KEYS,
        ),
        commitment_outbox=row["commitment_outbox"],
        commitment_record=row["commitment_record"],
        commitment_identity_counts=row["commitment_identity_counts"],
        chain_index=chain_index,
        require_current_effect=require_current_effect,
    )
