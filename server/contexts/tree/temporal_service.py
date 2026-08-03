"""Immutable Gate-3 temporal commitment and two-ended sidecar service.

The service owns the only write path for receipt-bound T1 commitments and T2
sidecars.  Both objects are append-only adjuncts: neither operation advances a
node's current receipt head, and every read rederives the receipt chain,
authority policy, signatures, hashes, and causal seal from stored facts.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime, timezone
import re
from typing import Any

from fastapi import HTTPException

from lakatos.io.reconcile import HistoryPayloadError, validate_history_record
from lakatos.verdicts import ReceiptChainBroken, fold_receipt_chain, match_receipt_encoding
from server.contexts.tree.receipt_chain import receipt_graph_prefix_sha256
from server.contexts.tree.temporal_proof import (
    TemporalProof,
    TemporalProofInvalid,
    VerifiedPredictionTemporalCommitment,
    build_prediction_temporal_commitment,
    build_two_ended_sidecar,
    canonical_policy_json,
    canonical_prediction_commitment_json,
    canonical_sidecar_json,
    derive_temporal_authority_policy,
    parse_canonical_policy,
    parse_canonical_prediction_commitment,
    parse_canonical_sidecar,
    prediction_temporal_commitment_sha256,
    unavailable_temporal_proof,
    verify_prediction_temporal_commitment,
    verify_sealed_prediction_temporal_commitment,
    verify_two_ended_temporal_sidecar,
)
from server.contexts.tree.temporal_intents import (
    PREDICTION_TEMPORAL_HISTORY_SCHEMA,
    PREDICTION_TEMPORAL_OP,
    PREDICTION_TEMPORAL_REASON,
    TEMPORAL_SIDECAR_HISTORY_SCHEMA,
    TEMPORAL_SIDECAR_OP,
    TEMPORAL_SIDECAR_REASON,
)
from server.contexts.tree.temporal_verifier_port import (
    IndependentTemporalCandidate,
    IndependentTemporalResult,
    IndependentTemporalVerifierUnavailable,
    temporal_request_id,
    transport_receipt,
)
from lakatos.temporal import two_ended_temporal_sidecar_sha256
from server.ports import GuardedKgOps, KgTxGuardFailed


TEMPORAL_SCOPE_SNAPSHOT_CYPHER = """
UNWIND $tags AS requested_tag
MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:requested_tag})
CALL {
  WITH e
  OPTIONAL MATCH (e)-[binding:HAS_RECEIPT]->(receipt:VerdictReceipt)
  WITH e, binding, receipt
  ORDER BY receipt.receipt_sha
  RETURN [item IN collect(CASE WHEN receipt IS NULL THEN null ELSE {
    receipt_element_id:elementId(receipt),
    binding_element_id:elementId(binding),
    binding_count:COUNT { MATCH (e)-[:HAS_RECEIPT]->(receipt) },
    global_binding_count:COUNT { MATCH ()-[:HAS_RECEIPT]->(receipt) },
    physical_count:COUNT { MATCH (other:VerdictReceipt {
      receipt_sha:receipt.receipt_sha}) },
    receipt:properties(receipt)
  } END) WHERE item IS NOT NULL] AS receipts
}
CALL {
  WITH e
  OPTIONAL MATCH (e)-[binding:HAS_PREDICTION_TEMPORAL_COMMITMENT]->
                 (commitment:PredictionTemporalCommitment)
  OPTIONAL MATCH (outbox:OutboxEntry {
    id:'ob-prediction-temporal-'+commitment.commitment_sha256})
  WITH e, binding, commitment, outbox
  ORDER BY commitment.commitment_sha256
  RETURN [item IN collect(CASE WHEN commitment IS NULL THEN null ELSE {
    commitment_element_id:elementId(commitment),
    binding_element_id:elementId(binding),
    binding_count:COUNT {
      MATCH (e)-[:HAS_PREDICTION_TEMPORAL_COMMITMENT]->(commitment) },
    global_binding_count:COUNT {
      MATCH ()-[:HAS_PREDICTION_TEMPORAL_COMMITMENT]->(commitment) },
    physical_count:COUNT { MATCH (other:PredictionTemporalCommitment {
      commitment_sha256:commitment.commitment_sha256}) },
    prediction_binding_count:COUNT {
      MATCH (commitment)-[:COMMITS_TO_PREDICTION]->
            (:VerdictReceipt {
              receipt_sha:commitment.prediction_receipt_sha256}) },
    global_prediction_binding_count:COUNT {
      MATCH (commitment)-[:COMMITS_TO_PREDICTION]->() },
    commitment:properties(commitment), outbox:properties(outbox)
  } END) WHERE item IS NOT NULL] AS commitments
}
CALL {
  WITH e
  OPTIONAL MATCH (e)-[binding:HAS_TEMPORAL_PROOF]->
                 (sidecar:TemporalProofSidecar)
  OPTIONAL MATCH (outbox:OutboxEntry {
    id:'ob-temporal-proof-'+sidecar.sidecar_sha256})
  WITH e, binding, sidecar, outbox
  ORDER BY sidecar.sidecar_sha256
  RETURN [item IN collect(CASE WHEN sidecar IS NULL THEN null ELSE {
    sidecar_element_id:elementId(sidecar),
    binding_element_id:elementId(binding),
    binding_count:COUNT { MATCH (e)-[:HAS_TEMPORAL_PROOF]->(sidecar) },
    global_binding_count:COUNT { MATCH ()-[:HAS_TEMPORAL_PROOF]->(sidecar) },
    physical_count:COUNT { MATCH (other:TemporalProofSidecar {
      sidecar_sha256:sidecar.sidecar_sha256}) },
    commitment_binding_count:COUNT {
      MATCH (sidecar)-[:USES_PREDICTION_COMMITMENT]->
            (:PredictionTemporalCommitment {
              commitment_sha256:
                sidecar.prediction_temporal_commitment_sha256}) },
    global_commitment_binding_count:COUNT {
      MATCH (sidecar)-[:USES_PREDICTION_COMMITMENT]->() },
    prediction_binding_count:COUNT {
      MATCH (sidecar)-[:STARTS_AT]->(:VerdictReceipt {
        receipt_sha:sidecar.prediction_receipt_sha256}) },
    global_prediction_binding_count:COUNT {
      MATCH (sidecar)-[:STARTS_AT]->() },
    verdict_binding_count:COUNT {
      MATCH (sidecar)-[:ENDS_AT]->(:VerdictReceipt {
        receipt_sha:sidecar.verdict_receipt_sha256}) },
    global_verdict_binding_count:COUNT {
      MATCH (sidecar)-[:ENDS_AT]->() },
    sidecar:properties(sidecar), outbox:properties(outbox)
  } END) WHERE item IS NOT NULL] AS sidecars
}
RETURN requested_tag, elementId(t) AS tree_element_id, properties(t) AS tree,
       elementId(e) AS node_element_id, properties(e) AS node,
       receipts, commitments, sidecars
ORDER BY requested_tag
"""


_HEX64 = re.compile(r"[0-9a-f]{64}\Z")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TemporalProofService:
    """Application service for Gate-3 temporal proof persistence and reads."""

    def __init__(
        self,
        *,
        kg,
        ledger_kg_tx,
        hist,
        ledger_ready: Callable[[], None] | None = None,
        ledger_scope=None,
        clock: Callable[[], datetime] | None = None,
        snapshot_provider: Callable[[str, str], Mapping[str, Any] | None]
        | None = None,
        independent_verifier=None,
    ):
        self.kg = kg
        self.ledger_kg_tx = ledger_kg_tx
        self.hist = hist
        self.ledger_ready = ledger_ready or (lambda: None)
        self.ledger_scope = ledger_scope or (lambda: nullcontext())
        self.clock = clock or _utc_now
        self.snapshot_provider = snapshot_provider or self._load_snapshot
        self.independent_verifier = independent_verifier

    def _now(self) -> datetime:
        value = self.clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise HTTPException(500, "temporal verifier clock is not timezone-aware")
        return value.astimezone(timezone.utc)

    def _load_snapshot(self, tree: str, tag: str) -> dict[str, Any] | None:
        rows = self.kg(TEMPORAL_SCOPE_SNAPSHOT_CYPHER, tree=tree, tags=[tag])
        if not rows:
            return None
        if len(rows) != 1:
            raise HTTPException(500, "temporal scope identity is ambiguous")
        return dict(rows[0])

    def _snapshot(self, tree: str, tag: str) -> dict[str, Any]:
        raw = self.snapshot_provider(tree, tag)
        if raw is None:
            raise HTTPException(404, f"노드 없음: {tag}")
        snapshot = dict(raw)
        if not (
            isinstance(snapshot.get("tree"), Mapping)
            and isinstance(snapshot.get("node"), Mapping)
            and isinstance(snapshot.get("receipts"), list)
            and isinstance(snapshot.get("commitments"), list)
            and isinstance(snapshot.get("sidecars"), list)
        ):
            raise HTTPException(500, "temporal scope snapshot is malformed")
        return snapshot

    @staticmethod
    def _coerce_batch_snapshot(raw: Any) -> dict[str, Any]:
        if not isinstance(raw, Mapping):
            raise TemporalProofInvalid("temporal batch snapshot is malformed")
        snapshot = dict(raw)
        if not (
            isinstance(snapshot.get("tree"), Mapping)
            and isinstance(snapshot.get("node"), Mapping)
            and isinstance(snapshot.get("receipts"), list)
            and isinstance(snapshot.get("commitments"), list)
            and isinstance(snapshot.get("sidecars"), list)
        ):
            raise TemporalProofInvalid("temporal batch snapshot is malformed")
        return snapshot

    @staticmethod
    def _policy(tree_name: str, tree: Mapping[str, Any]) -> dict[str, Any]:
        try:
            return derive_temporal_authority_policy(tree_name, tree)
        except TemporalProofInvalid as exc:
            raise HTTPException(409, f"temporal authority policy is invalid: {exc}") from exc

    @staticmethod
    def _scope(
        tree_name: str, tag: str, snapshot: Mapping[str, Any]
    ) -> tuple[str, str, tuple[str, ...], dict[str, dict[str, Any]]]:
        tree = dict(snapshot["tree"])
        node = dict(snapshot["node"])
        incarnation = tree.get("tree_incarnation_id")
        current = node.get("current_receipt_sha")
        prediction = node.get("pred_receipt_sha")
        if not (
            isinstance(incarnation, str)
            and incarnation
            and isinstance(current, str)
            and _HEX64.fullmatch(current)
            and isinstance(prediction, str)
            and _HEX64.fullmatch(prediction)
        ):
            raise TemporalProofInvalid("temporal scope lacks exact receipt/incarnation identity")

        receipt_by_sha: dict[str, dict[str, Any]] = {}
        for item in snapshot["receipts"]:
            if not isinstance(item, Mapping):
                raise TemporalProofInvalid("receipt snapshot member is malformed")
            receipt = item.get("receipt")
            if not (
                isinstance(receipt, Mapping)
                and item.get("binding_count") == 1
                and item.get("global_binding_count") == 1
                and item.get("physical_count") == 1
            ):
                raise TemporalProofInvalid("receipt physical binding is not exact")
            material = dict(receipt)
            receipt_sha = material.get("receipt_sha")
            if not (
                isinstance(receipt_sha, str)
                and _HEX64.fullmatch(receipt_sha)
                and receipt_sha not in receipt_by_sha
                and material.get("tree") == tree_name
                and material.get("tag") == tag
                and match_receipt_encoding(material, receipt_sha) == "current"
            ):
                raise TemporalProofInvalid("receipt content or scope does not rederive")
            receipt_by_sha[receipt_sha] = material
        try:
            fold_receipt_chain(list(receipt_by_sha.values()), current)
        except (ReceiptChainBroken, KeyError, TypeError) as exc:
            raise TemporalProofInvalid("receipt chain is broken") from exc
        head_to_genesis: list[str] = []
        seen: set[str] = set()
        cursor: str | None = current
        while cursor is not None:
            if cursor in seen or cursor not in receipt_by_sha:
                raise TemporalProofInvalid("receipt ancestry cannot reach genesis")
            seen.add(cursor)
            head_to_genesis.append(cursor)
            cursor = receipt_by_sha[cursor].get("prev_receipt_sha")
        if seen != set(receipt_by_sha):
            raise TemporalProofInvalid("receipt scope contains a side branch")
        ordered = tuple(reversed(head_to_genesis))
        if (
            prediction not in seen
            or receipt_by_sha[prediction].get("receipt_kind") != "prediction"
        ):
            raise TemporalProofInvalid("prediction pointer is not current ancestry")
        return incarnation, current, ordered, receipt_by_sha

    @staticmethod
    def _one_adjunct(
        snapshot: Mapping[str, Any], key: str, object_key: str
    ) -> tuple[dict[str, Any], dict[str, Any] | None] | None:
        items = snapshot.get(key)
        if not isinstance(items, list):
            raise TemporalProofInvalid(f"{key} snapshot is malformed")
        if not items:
            return None
        if len(items) != 1 or not isinstance(items[0], Mapping):
            raise TemporalProofInvalid(f"{key} cardinality is not exact")
        item = dict(items[0])
        value = item.get(object_key)
        if not (
            isinstance(value, Mapping)
            and item.get("binding_count") == 1
            and item.get("global_binding_count") == 1
            and item.get("physical_count") == 1
        ):
            raise TemporalProofInvalid(f"{key} physical binding is not exact")
        required_link_counts = {
            "commitments": (
                "prediction_binding_count",
                "global_prediction_binding_count",
            ),
            "sidecars": (
                "commitment_binding_count",
                "global_commitment_binding_count",
                "prediction_binding_count",
                "global_prediction_binding_count",
                "verdict_binding_count",
                "global_verdict_binding_count",
            ),
        }.get(key, ())
        if any(item.get(count_key) != 1 for count_key in required_link_counts):
            raise TemporalProofInvalid(f"{key} receipt binding is not exact")
        outbox = item.get("outbox")
        if outbox is not None and not isinstance(outbox, Mapping):
            raise TemporalProofInvalid(f"{key} outbox is malformed")
        return dict(value), (dict(outbox) if isinstance(outbox, Mapping) else None)

    @staticmethod
    def _history_payload(
        *,
        schema: str,
        object_name: str,
        object_sha: str,
        body: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "schema_version": schema,
            f"{object_name}_sha256": object_sha,
            object_name: dict(body),
        }

    @staticmethod
    def _outbox_exact(
        outbox: Mapping[str, Any] | None,
        *,
        event_id: str,
        tree: str,
        tag: str,
        op: str,
        reason: str,
        payload_json: str,
        receipt_sha: str,
        record_created_at: Any,
    ) -> None:
        if not isinstance(outbox, Mapping) or not (
            outbox.get("id") == event_id
            and outbox.get("tree") == tree
            and outbox.get("node_tag") == tag
            and outbox.get("op") == op
            and outbox.get("reason") == reason
            and outbox.get("payload") == payload_json
            and outbox.get("receipt_sha") == receipt_sha
            and outbox.get("created_at") == record_created_at
            and all(
                outbox.get(key) is None
                for key in (
                    "adopted_by", "adopted_at", "causal_group", "causal_index",
                    "request_sha256", "demoted_tag", "demoted_receipt_sha",
                )
            )
            and (
                (outbox.get("status") == "pending" and outbox.get("applied_at") is None)
                or (outbox.get("status") == "applied" and outbox.get("applied_at") is not None)
            )
        ):
            raise TemporalProofInvalid("temporal outbox immutable binding is not exact")

    def _write(self, query: str, params: dict[str, Any]) -> None:
        try:
            results = self.ledger_kg_tx(GuardedKgOps([(query, params)]))
        except KgTxGuardFailed as exc:
            raise HTTPException(409, "temporal proof CAS or immutable identity conflict") from exc
        if not (
            isinstance(results, list)
            and len(results) == 1
            and isinstance(results[0], list)
            and len(results[0]) == 1
            and results[0][0].get("ok") is True
        ):
            raise HTTPException(409, "temporal proof CAS or immutable identity conflict")

    def _project_history(
        self,
        *,
        tree: str,
        tag: str,
        op: str,
        payload: dict[str, Any],
        event_id: str,
    ) -> bool:
        projected = self.hist(tree, op, tag, payload, event_id=event_id)
        return projected is not False

    def _verified_commitment_from_snapshot(
        self,
        tree_name: str,
        tag: str,
        snapshot: Mapping[str, Any],
        *,
        evaluated_at: datetime,
    ) -> VerifiedPredictionTemporalCommitment | None:
        adjunct = self._one_adjunct(snapshot, "commitments", "commitment")
        if adjunct is None:
            return None
        stored, _outbox = adjunct
        tree = dict(snapshot["tree"])
        node = dict(snapshot["node"])
        policy = self._policy(tree_name, tree)
        incarnation, current, _ordered, receipts = self._scope(
            tree_name, tag, snapshot
        )
        commitment = parse_canonical_prediction_commitment(
            stored.get("commitment_json")
        )
        stored_policy = parse_canonical_policy(stored.get("authority_policy_json"))
        if stored_policy != policy:
            raise TemporalProofInvalid("stored prediction policy is no longer current")
        commitment_sha = stored.get("commitment_sha256")
        prediction_sha = node.get("pred_receipt_sha")
        if not isinstance(commitment_sha, str) or not isinstance(prediction_sha, str):
            raise TemporalProofInvalid("prediction commitment identity is malformed")
        if current == prediction_sha:
            return verify_prediction_temporal_commitment(
                commitment,
                stored_commitment_sha256=commitment_sha,
                authority_policy=stored_policy,
                tree_incarnation_id=incarnation,
                tree=tree_name,
                tag=tag,
                prediction_receipt_sha256=prediction_sha,
                prediction_receipt=receipts[prediction_sha],
                current_head_sha256=current,
                evaluated_at=evaluated_at,
            )
        return verify_sealed_prediction_temporal_commitment(
            commitment,
            stored_commitment_sha256=commitment_sha,
            authority_policy=stored_policy,
            tree_incarnation_id=incarnation,
            tree=tree_name,
            tag=tag,
            prediction_receipt_sha256=prediction_sha,
            prediction_receipt=receipts[prediction_sha],
            current_head_sha256=current,
            verdict_receipt=receipts[current],
            evaluated_at=evaluated_at,
        )

    def verified_prediction_commitment(
        self, tree: str, tag: str
    ) -> VerifiedPredictionTemporalCommitment | None:
        """Judgement-service port: rederive T1 before minting/freshening v7."""

        with self.ledger_scope():
            snapshot = self._snapshot(tree, tag)
            try:
                return self._verified_commitment_from_snapshot(
                    tree, tag, snapshot, evaluated_at=self._now()
                )
            except TemporalProofInvalid as exc:
                raise HTTPException(409, f"prediction temporal commitment invalid: {exc}") from exc

    def attach_prediction_commitment(
        self,
        tree: str,
        tag: str,
        prediction_anchors: list[dict[str, Any]],
        *,
        expected_prediction_receipt_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Persist a receipt-bound T1 only while the prediction is current."""

        with self.ledger_scope():
            self.ledger_ready()
            evaluated_at = self._now()
            snapshot = self._snapshot(tree, tag)
            tree_record = dict(snapshot["tree"])
            policy = self._policy(tree, tree_record)
            incarnation, current, _ordered, receipts = self._scope(tree, tag, snapshot)
            prediction_sha = dict(snapshot["node"]).get("pred_receipt_sha")
            if (
                expected_prediction_receipt_sha256 is not None
                and prediction_sha != expected_prediction_receipt_sha256
            ):
                raise HTTPException(409, "prediction receipt path is not the current prediction")
            if current != prediction_sha:
                raise HTTPException(409, "prediction T1 must be committed before verdict minting")
            commitment = build_prediction_temporal_commitment(
                tree_incarnation_id=incarnation,
                tree=tree,
                tag=tag,
                prediction_receipt_sha256=prediction_sha,
                authority_policy=policy,
                prediction_anchors=prediction_anchors,
            )
            commitment_sha = prediction_temporal_commitment_sha256(commitment)
            verified = verify_prediction_temporal_commitment(
                commitment,
                stored_commitment_sha256=commitment_sha,
                authority_policy=policy,
                tree_incarnation_id=incarnation,
                tree=tree,
                tag=tag,
                prediction_receipt_sha256=prediction_sha,
                prediction_receipt=receipts[prediction_sha],
                current_head_sha256=current,
                evaluated_at=evaluated_at,
            )
            payload = self._history_payload(
                schema=PREDICTION_TEMPORAL_HISTORY_SCHEMA,
                object_name="commitment",
                object_sha=commitment_sha,
                body=commitment,
            )
            event_id = f"ob-prediction-temporal-{commitment_sha}"
            try:
                payload_json = validate_history_record(
                    tree, PREDICTION_TEMPORAL_OP, tag, payload, event_id
                )
            except HistoryPayloadError as exc:
                raise HTTPException(422, "temporal commitment history is not representable") from exc

            existing = self._one_adjunct(snapshot, "commitments", "commitment")
            if existing is not None:
                stored, outbox = existing
                if not (
                    stored.get("commitment_sha256") == commitment_sha
                    and stored.get("prediction_receipt_sha256") == prediction_sha
                    and stored.get("commitment_json")
                    == canonical_prediction_commitment_json(commitment)
                    and stored.get("authority_policy_json") == canonical_policy_json(policy)
                ):
                    raise HTTPException(409, "a different prediction T1 is already committed")
                try:
                    self._outbox_exact(
                        outbox,
                        event_id=event_id,
                        tree=tree,
                        tag=tag,
                        op=PREDICTION_TEMPORAL_OP,
                        reason=PREDICTION_TEMPORAL_REASON,
                        payload_json=payload_json,
                        receipt_sha=prediction_sha,
                        record_created_at=stored.get("created_at"),
                    )
                except TemporalProofInvalid as exc:
                    raise HTTPException(409, str(exc)) from exc
            else:
                ts = evaluated_at.isoformat()
                self._write(
                    """MATCH (t:LakatosTree {
                         name:$tree, tree_incarnation_id:$incarnation,
                         research_layout:$research_layout,
                         layout_owner_did:$layout_owner_did,
                         layout_sig:$layout_sig,
                         witness_threshold:$witness_threshold})
                       -[:HAS_NODE]->(e {tag:$tag, current_receipt_sha:$prediction_sha,
                                        pred_receipt_sha:$prediction_sha})
                       MATCH (e)-[:HAS_RECEIPT]->
                         (prediction:VerdictReceipt {
                           receipt_sha:$prediction_sha,
                           receipt_kind:'prediction'})
                       SET t._tree_write_cas=coalesce(t._tree_write_cas,0)+0,
                           e._cas=coalesce(e._cas,0)+0
                       WITH t, e, prediction
                       WHERE t.witness_dids=$witness_dids
                         AND t.attestor_dids=$attestor_dids
                         AND NOT (e)-[:HAS_PREDICTION_TEMPORAL_COMMITMENT]->()
                         AND NOT EXISTS { MATCH (:PredictionTemporalCommitment {
                           prediction_receipt_sha256:$prediction_sha}) }
                         AND NOT EXISTS { MATCH (:OutboxEntry {id:$event_id}) }
                       CREATE (commitment:PredictionTemporalCommitment {
                         commitment_sha256:$commitment_sha,
                         prediction_receipt_sha256:$prediction_sha,
                         authority_policy_sha256:$policy_sha,
                         tree_incarnation_id:$incarnation, tree:$tree, tag:$tag,
                         commitment_json:$commitment_json,
                         authority_policy_json:$policy_json, created_at:$ts})
                       CREATE (e)-[:HAS_PREDICTION_TEMPORAL_COMMITMENT]->(commitment)
                       CREATE (commitment)-[:COMMITS_TO_PREDICTION]->(prediction)
                       CREATE (:OutboxEntry {
                         id:$event_id, tree:$tree, op:$op, node_tag:$tag,
                         payload:$payload, status:'pending', created_at:$ts,
                         reason:$reason,
                         receipt_sha:$prediction_sha})
                       RETURN true AS ok""",
                    {
                        "tree": tree,
                        "tag": tag,
                        "incarnation": incarnation,
                        "prediction_sha": prediction_sha,
                        "commitment_sha": commitment_sha,
                        "policy_sha": verified.authority_policy_sha256,
                        "commitment_json": canonical_prediction_commitment_json(commitment),
                        "policy_json": canonical_policy_json(policy),
                        "research_layout": tree_record.get("research_layout"),
                        "layout_owner_did": tree_record.get("layout_owner_did"),
                        "layout_sig": tree_record.get("layout_sig"),
                        "witness_threshold": tree_record.get("witness_threshold"),
                        "witness_dids": tree_record.get("witness_dids"),
                        "attestor_dids": tree_record.get("attestor_dids"),
                        "event_id": event_id,
                        "op": PREDICTION_TEMPORAL_OP,
                        "reason": PREDICTION_TEMPORAL_REASON,
                        "payload": payload_json,
                        "ts": ts,
                    },
                )
            persisted = self._one_adjunct(
                self._snapshot(tree, tag), "commitments", "commitment"
            )
            if persisted is None:
                raise HTTPException(409, "prediction T1 exact readback is missing")
            persisted_record, persisted_outbox = persisted
            if not (
                persisted_record.get("commitment_sha256") == commitment_sha
                and persisted_record.get("prediction_receipt_sha256") == prediction_sha
                and persisted_record.get("commitment_json")
                == canonical_prediction_commitment_json(commitment)
                and persisted_record.get("authority_policy_json")
                == canonical_policy_json(policy)
            ):
                raise HTTPException(409, "prediction T1 exact readback diverged")
            try:
                self._outbox_exact(
                    persisted_outbox,
                    event_id=event_id,
                    tree=tree,
                    tag=tag,
                    op=PREDICTION_TEMPORAL_OP,
                    reason=PREDICTION_TEMPORAL_REASON,
                    payload_json=payload_json,
                    receipt_sha=prediction_sha,
                    record_created_at=persisted_record.get("created_at"),
                )
            except TemporalProofInvalid as exc:
                raise HTTPException(409, str(exc)) from exc
            history_ok = self._project_history(
                tree=tree,
                tag=tag,
                op=PREDICTION_TEMPORAL_OP,
                payload=payload,
                event_id=event_id,
            )
            return {
                "ok": True,
                "history_pending": not history_ok,
                "commitment_sha256": commitment_sha,
                "prediction_receipt_sha256": prediction_sha,
                "authority_policy_sha256": verified.authority_policy_sha256,
                "threshold": verified.threshold,
                "witness_dids": list(verified.witness_dids),
                "t1_latest": verified.t1_latest,
            }

    def finalize_sidecar(
        self,
        tree: str,
        tag: str,
        verdict_anchors: list[dict[str, Any]],
        *,
        expected_verdict_receipt_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Attach T2 and freeze the exact two-ended sidecar for current verdict."""

        with self.ledger_scope():
            self.ledger_ready()
            evaluated_at = self._now()
            snapshot = self._snapshot(tree, tag)
            tree_record = dict(snapshot["tree"])
            policy = self._policy(tree, tree_record)
            incarnation, current, ordered, receipts = self._scope(tree, tag, snapshot)
            prediction_sha = dict(snapshot["node"]).get("pred_receipt_sha")
            if (
                expected_verdict_receipt_sha256 is not None
                and current != expected_verdict_receipt_sha256
            ):
                raise HTTPException(409, "verdict receipt path is not the current head")
            if current == prediction_sha or receipts[current].get("receipt_kind") == "prediction":
                raise HTTPException(409, "a verdict receipt is required before T2 finalization")
            verified_commitment = self._verified_commitment_from_snapshot(
                tree, tag, snapshot, evaluated_at=evaluated_at
            )
            if verified_commitment is None:
                raise HTTPException(409, "prediction temporal commitment is missing")
            commitment_record, _commitment_outbox = self._one_adjunct(
                snapshot, "commitments", "commitment"
            ) or ({}, None)
            commitment = parse_canonical_prediction_commitment(
                commitment_record.get("commitment_json")
            )
            graph_sha = receipt_graph_prefix_sha256(
                tree_incarnation_id=incarnation,
                tree=tree,
                tag=tag,
                prediction_receipt_sha256=prediction_sha,
                verdict_receipt_sha256=current,
                chain=ordered,
            )
            sidecar = build_two_ended_sidecar(
                authority_policy=policy,
                prediction_receipt_sha256=prediction_sha,
                verdict_receipt_sha256=current,
                receipt_graph_sha256=graph_sha,
                prediction_anchors=list(commitment["prediction_anchors"]),
                verdict_anchors=verdict_anchors,
            )
            sidecar_sha = two_ended_temporal_sidecar_sha256(sidecar)
            proof = verify_two_ended_temporal_sidecar(
                sidecar,
                stored_sidecar_sha256=sidecar_sha,
                stored_authority_policy=policy,
                current_authority_policy=policy,
                tree=tree,
                tag=tag,
                tree_incarnation_id=incarnation,
                current_head_sha256=current,
                chain=ordered,
                receipt_by_sha=receipts,
                evaluated_at=evaluated_at,
            )
            payload = self._history_payload(
                schema=TEMPORAL_SIDECAR_HISTORY_SCHEMA,
                object_name="sidecar",
                object_sha=sidecar_sha,
                body=sidecar,
            )
            event_id = f"ob-temporal-proof-{sidecar_sha}"
            try:
                payload_json = validate_history_record(
                    tree, TEMPORAL_SIDECAR_OP, tag, payload, event_id
                )
            except HistoryPayloadError as exc:
                raise HTTPException(422, "temporal sidecar history is not representable") from exc

            existing = self._one_adjunct(snapshot, "sidecars", "sidecar")
            if existing is not None:
                stored, outbox = existing
                if not (
                    stored.get("sidecar_sha256") == sidecar_sha
                    and stored.get("verdict_receipt_sha256") == current
                    and stored.get("sidecar_json") == canonical_sidecar_json(sidecar)
                    and stored.get("authority_policy_json") == canonical_policy_json(policy)
                ):
                    raise HTTPException(409, "a different temporal sidecar is already attached")
                try:
                    self._outbox_exact(
                        outbox,
                        event_id=event_id,
                        tree=tree,
                        tag=tag,
                        op=TEMPORAL_SIDECAR_OP,
                        reason=TEMPORAL_SIDECAR_REASON,
                        payload_json=payload_json,
                        receipt_sha=current,
                        record_created_at=stored.get("created_at"),
                    )
                except TemporalProofInvalid as exc:
                    raise HTTPException(409, str(exc)) from exc
            else:
                ts = evaluated_at.isoformat()
                self._write(
                    """MATCH (t:LakatosTree {
                         name:$tree, tree_incarnation_id:$incarnation,
                         research_layout:$research_layout,
                         layout_owner_did:$layout_owner_did,
                         layout_sig:$layout_sig,
                         witness_threshold:$witness_threshold})
                       -[:HAS_NODE]->(e {tag:$tag, current_receipt_sha:$verdict_sha,
                                        pred_receipt_sha:$prediction_sha})
                       MATCH (e)-[:HAS_RECEIPT]->(prediction:VerdictReceipt {
                         receipt_sha:$prediction_sha, receipt_kind:'prediction'})
                       MATCH (e)-[:HAS_RECEIPT]->(verdict:VerdictReceipt {
                         receipt_sha:$verdict_sha,
                         prediction_temporal_commitment_sha256:$commitment_sha})
                       MATCH (e)-[:HAS_PREDICTION_TEMPORAL_COMMITMENT]->
                         (commitment:PredictionTemporalCommitment {
                           commitment_sha256:$commitment_sha,
                           prediction_receipt_sha256:$prediction_sha})
                       SET t._tree_write_cas=coalesce(t._tree_write_cas,0)+0,
                           e._cas=coalesce(e._cas,0)+0
                       WITH t, e, prediction, verdict, commitment
                       WHERE t.witness_dids=$witness_dids
                         AND t.attestor_dids=$attestor_dids
                         AND NOT (e)-[:HAS_TEMPORAL_PROOF]->()
                         AND NOT EXISTS { MATCH (:TemporalProofSidecar {
                           verdict_receipt_sha256:$verdict_sha}) }
                         AND NOT EXISTS { MATCH (:OutboxEntry {id:$event_id}) }
                       CREATE (sidecar:TemporalProofSidecar {
                         sidecar_sha256:$sidecar_sha,
                         verdict_receipt_sha256:$verdict_sha,
                         prediction_receipt_sha256:$prediction_sha,
                         prediction_temporal_commitment_sha256:$commitment_sha,
                         receipt_graph_sha256:$graph_sha,
                         authority_policy_sha256:$policy_sha,
                         tree_incarnation_id:$incarnation, tree:$tree, tag:$tag,
                         sidecar_json:$sidecar_json,
                         authority_policy_json:$policy_json, created_at:$ts})
                       CREATE (e)-[:HAS_TEMPORAL_PROOF]->(sidecar)
                       CREATE (sidecar)-[:USES_PREDICTION_COMMITMENT]->(commitment)
                       CREATE (sidecar)-[:STARTS_AT]->(prediction)
                       CREATE (sidecar)-[:ENDS_AT]->(verdict)
                       CREATE (:OutboxEntry {
                         id:$event_id, tree:$tree, op:$op, node_tag:$tag,
                         payload:$payload, status:'pending', created_at:$ts,
                         reason:$reason,
                         receipt_sha:$verdict_sha})
                       RETURN true AS ok""",
                    {
                        "tree": tree,
                        "tag": tag,
                        "incarnation": incarnation,
                        "prediction_sha": prediction_sha,
                        "verdict_sha": current,
                        "commitment_sha": verified_commitment.commitment_sha256,
                        "sidecar_sha": sidecar_sha,
                        "graph_sha": graph_sha,
                        "policy_sha": proof.authority_policy_sha256,
                        "sidecar_json": canonical_sidecar_json(sidecar),
                        "policy_json": canonical_policy_json(policy),
                        "research_layout": tree_record.get("research_layout"),
                        "layout_owner_did": tree_record.get("layout_owner_did"),
                        "layout_sig": tree_record.get("layout_sig"),
                        "witness_threshold": tree_record.get("witness_threshold"),
                        "witness_dids": tree_record.get("witness_dids"),
                        "attestor_dids": tree_record.get("attestor_dids"),
                        "event_id": event_id,
                        "op": TEMPORAL_SIDECAR_OP,
                        "reason": TEMPORAL_SIDECAR_REASON,
                        "payload": payload_json,
                        "ts": ts,
                    },
                )
            persisted = self._one_adjunct(
                self._snapshot(tree, tag), "sidecars", "sidecar"
            )
            if persisted is None:
                raise HTTPException(409, "temporal sidecar exact readback is missing")
            persisted_record, persisted_outbox = persisted
            if not (
                persisted_record.get("sidecar_sha256") == sidecar_sha
                and persisted_record.get("verdict_receipt_sha256") == current
                and persisted_record.get("sidecar_json")
                == canonical_sidecar_json(sidecar)
                and persisted_record.get("authority_policy_json")
                == canonical_policy_json(policy)
            ):
                raise HTTPException(409, "temporal sidecar exact readback diverged")
            try:
                self._outbox_exact(
                    persisted_outbox,
                    event_id=event_id,
                    tree=tree,
                    tag=tag,
                    op=TEMPORAL_SIDECAR_OP,
                    reason=TEMPORAL_SIDECAR_REASON,
                    payload_json=payload_json,
                    receipt_sha=current,
                    record_created_at=persisted_record.get("created_at"),
                )
            except TemporalProofInvalid as exc:
                raise HTTPException(409, str(exc)) from exc
            history_ok = self._project_history(
                tree=tree,
                tag=tag,
                op=TEMPORAL_SIDECAR_OP,
                payload=payload,
                event_id=event_id,
            )
            return {"ok": True, "history_pending": not history_ok, **proof.public_dict()}

    def _proof_from_snapshot(
        self,
        tree: str,
        tag: str,
        snapshot: Mapping[str, Any],
        *,
        evaluated_at: datetime,
    ) -> TemporalProof:
        """Total current-head proof evaluation with precise chain semantics."""

        try:
            incarnation, current, ordered, receipts = self._scope(tree, tag, snapshot)
        except TemporalProofInvalid:
            return unavailable_temporal_proof(
                "receipt_chain_invalid", chain_ok=False
            )
        try:
            policy = self._policy(tree, snapshot["tree"])
            sidecar_adjunct = self._one_adjunct(snapshot, "sidecars", "sidecar")
            if sidecar_adjunct is None:
                commitment = self._one_adjunct(
                    snapshot, "commitments", "commitment"
                )
                return unavailable_temporal_proof(
                    "prediction_commitment_missing"
                    if commitment is None
                    else "verdict_anchor_sidecar_missing",
                    chain_ok=True,
                )
            stored, _outbox = sidecar_adjunct
            sidecar = parse_canonical_sidecar(stored.get("sidecar_json"))
            stored_policy = parse_canonical_policy(
                stored.get("authority_policy_json")
            )
            return verify_two_ended_temporal_sidecar(
                sidecar,
                stored_sidecar_sha256=stored.get("sidecar_sha256"),
                stored_authority_policy=stored_policy,
                current_authority_policy=policy,
                tree=tree,
                tag=tag,
                tree_incarnation_id=incarnation,
                current_head_sha256=current,
                chain=ordered,
                receipt_by_sha=receipts,
                evaluated_at=evaluated_at,
            )
        except (HTTPException, TemporalProofInvalid):
            return unavailable_temporal_proof(
                "temporal_proof_invalid", chain_ok=True
            )

    def _independent_candidate(
        self,
        tree: str,
        tag: str,
        snapshot: Mapping[str, Any],
        proof: TemporalProof,
    ) -> IndependentTemporalCandidate:
        incarnation, current, ordered, receipts = self._scope(tree, tag, snapshot)
        sidecar_adjunct = self._one_adjunct(snapshot, "sidecars", "sidecar")
        if sidecar_adjunct is None:
            raise TemporalProofInvalid("independent verifier sidecar is missing")
        sidecar_record, _outbox = sidecar_adjunct
        sidecar = parse_canonical_sidecar(sidecar_record.get("sidecar_json"))
        policy = parse_canonical_policy(
            sidecar_record.get("authority_policy_json")
        )
        required = (
            proof.sidecar_sha256,
            proof.authority_policy_sha256,
            proof.receipt_graph_sha256,
            proof.prediction_receipt_sha256,
            proof.verdict_receipt_sha256,
            proof.prediction_temporal_commitment_sha256,
        )
        if not all(isinstance(value, str) and _HEX64.fullmatch(value) for value in required):
            raise TemporalProofInvalid("independent verifier proof identity is incomplete")
        if proof.verdict_receipt_sha256 != current or proof.threshold is None:
            raise TemporalProofInvalid("independent verifier proof is not current")
        request_id = temporal_request_id(
            tree_incarnation_id=incarnation,
            tree=tree,
            tag=tag,
            verdict_receipt_sha256=current,
        )
        return IndependentTemporalCandidate(
            request_id=request_id,
            tree_incarnation_id=incarnation,
            tree=tree,
            tag=tag,
            current_head_sha256=current,
            stored_sidecar_sha256=proof.sidecar_sha256,
            authority_policy=policy,
            sidecar=sidecar,
            chain=ordered,
            receipts=tuple(transport_receipt(receipts[sha]) for sha in ordered),
            authority_policy_sha256=proof.authority_policy_sha256,
            receipt_graph_sha256=proof.receipt_graph_sha256,
            prediction_receipt_sha256=proof.prediction_receipt_sha256,
            verdict_receipt_sha256=proof.verdict_receipt_sha256,
            prediction_temporal_commitment_sha256=(
                proof.prediction_temporal_commitment_sha256
            ),
            witness_dids=proof.witness_dids,
            threshold=proof.threshold,
        )

    def _apply_independent_verifier(
        self,
        proofs: dict[str, TemporalProof],
        candidates: Mapping[str, IndependentTemporalCandidate],
    ) -> dict[str, TemporalProof]:
        verifier = self.independent_verifier
        if verifier is None or not candidates:
            return proofs
        try:
            results = verifier.verify_batch(
                tuple(sorted(candidates.values(), key=lambda item: item.request_id))
            )
        except (
            IndependentTemporalVerifierUnavailable,
            OSError,
            TypeError,
            ValueError,
            AttributeError,
        ):
            for tag in candidates:
                proofs[tag] = replace(
                    proofs[tag],
                    l3_eligible=False,
                    reason="independent_verifier_unavailable",
                    independent_verifier=None,
                    time_authority=None,
                    independent_input_sha256=None,
                    independent_valid_until=None,
                    authority_identity_sha256s=(),
                )
            return proofs
        expected_result_ids = {
            candidate.request_id for candidate in candidates.values()
        }
        if not isinstance(results, Mapping) or set(results) != expected_result_ids:
            results = {}
        for tag, candidate in candidates.items():
            proof = proofs[tag]
            result = results.get(candidate.request_id)
            exact = (
                isinstance(result, IndependentTemporalResult)
                and result.request_id == candidate.request_id
                and result.reason == "independent_two_ended_temporal_verified"
                and proof.component_ok is True
                and proof.chain_ok is True
                and _HEX64.fullmatch(result.input_sha256) is not None
                and result.sidecar_sha256 == proof.sidecar_sha256
                and result.authority_policy_sha256
                == proof.authority_policy_sha256
                and result.receipt_graph_sha256 == proof.receipt_graph_sha256
                and result.prediction_receipt_sha256
                == proof.prediction_receipt_sha256
                and result.verdict_receipt_sha256
                == proof.verdict_receipt_sha256
                and result.prediction_temporal_commitment_sha256
                == proof.prediction_temporal_commitment_sha256
                and result.threshold == proof.threshold
                and result.t1_latest == proof.t1_latest
                and result.t2_earliest == proof.t2_earliest
                and isinstance(result.independent_verifier, str)
                and result.independent_verifier.startswith("sha256:")
                and _HEX64.fullmatch(result.independent_verifier[7:]) is not None
                and isinstance(result.time_authority, str)
                and result.time_authority.startswith("did-key-sha256:")
                and _HEX64.fullmatch(result.time_authority[15:]) is not None
                and isinstance(result.independent_valid_until, str)
                and bool(result.independent_valid_until)
                and bool(result.authority_identity_sha256s)
                and all(
                    _HEX64.fullmatch(value) is not None
                    for value in result.authority_identity_sha256s
                )
            )
            if isinstance(result, IndependentTemporalResult) and not result.accepted:
                proofs[tag] = replace(
                    proof,
                    l3_eligible=False,
                    reason="independent_verifier_rejected",
                    independent_verifier=None,
                    time_authority=None,
                    independent_input_sha256=None,
                    independent_valid_until=None,
                    authority_identity_sha256s=(),
                )
            elif not exact or result is None or not result.accepted:
                proofs[tag] = replace(
                    proof,
                    l3_eligible=False,
                    reason="independent_verifier_unavailable",
                    independent_verifier=None,
                    time_authority=None,
                    independent_input_sha256=None,
                    independent_valid_until=None,
                    authority_identity_sha256s=(),
                )
            else:
                proofs[tag] = replace(
                    proof,
                    l3_eligible=True,
                    reason=result.reason,
                    independent_verifier=result.independent_verifier,
                    time_authority=result.time_authority,
                    independent_input_sha256=result.input_sha256,
                    independent_valid_until=result.independent_valid_until,
                    authority_identity_sha256s=(
                        result.authority_identity_sha256s
                    ),
                )
        return proofs

    def read_proof(self, tree: str, tag: str) -> TemporalProof:
        """Reverify Gate-3 evidence for the current receipt head on every read."""

        snapshot = self._snapshot(tree, tag)
        proof = self._proof_from_snapshot(
            tree, tag, snapshot, evaluated_at=self._now()
        )
        if not proof.component_ok:
            return proof
        try:
            candidate = self._independent_candidate(tree, tag, snapshot, proof)
        except TemporalProofInvalid:
            return replace(
                proof,
                reason="independent_verifier_input_unavailable",
            )
        return self._apply_independent_verifier(
            {tag: proof}, {tag: candidate}
        )[tag]

    def read_proofs_for_heads(
        self,
        tree: str,
        heads_by_tag: Mapping[str, str | None],
    ) -> dict[str, TemporalProof]:
        """Batch reverify one tree at one clock instant, bound to caller heads."""

        requested = {
            str(tag): head
            for tag, head in heads_by_tag.items()
            if isinstance(tag, str) and tag
        }
        if not requested:
            return {}
        rows = self.kg(
            TEMPORAL_SCOPE_SNAPSHOT_CYPHER,
            tree=tree,
            tags=sorted(requested),
        )
        snapshots: dict[str, dict[str, Any]] = {}
        malformed_tags: set[str] = set()
        for raw in rows or []:
            requested_tag = raw.get("requested_tag") if isinstance(raw, Mapping) else None
            if not isinstance(requested_tag, str) or requested_tag not in requested:
                continue
            if requested_tag in snapshots:
                malformed_tags.add(requested_tag)
                continue
            try:
                snapshots[requested_tag] = self._coerce_batch_snapshot(raw)
            except TemporalProofInvalid:
                malformed_tags.add(requested_tag)
        evaluated_at = self._now()
        proofs: dict[str, TemporalProof] = {}
        candidates: dict[str, IndependentTemporalCandidate] = {}
        for tag, expected_head in requested.items():
            snapshot = snapshots.get(tag)
            if tag in malformed_tags or snapshot is None:
                proofs[tag] = unavailable_temporal_proof(
                    "temporal_snapshot_unavailable", chain_ok=None
                )
                continue
            observed_head = dict(snapshot["node"]).get("current_receipt_sha")
            if expected_head is not None and observed_head != expected_head:
                proofs[tag] = unavailable_temporal_proof(
                    "temporal_head_changed", chain_ok=None
                )
                continue
            proof = self._proof_from_snapshot(
                tree,
                tag,
                snapshot,
                evaluated_at=evaluated_at,
            )
            proofs[tag] = proof
            if proof.component_ok:
                try:
                    candidates[tag] = self._independent_candidate(
                        tree, tag, snapshot, proof
                    )
                except TemporalProofInvalid:
                    proofs[tag] = replace(
                        proof,
                        reason="independent_verifier_input_unavailable",
                    )
        return self._apply_independent_verifier(proofs, candidates)
