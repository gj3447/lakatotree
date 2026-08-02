"""Application service for evidence, standing, and claim certification.

# KG: seed-lkt-engine-route-evidence-claim-extract-20260616
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from contextlib import nullcontext
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from lakatos.engine_identity import ENGINE_RULE_SHA, effective_floor
from lakatos.verdict.argue import assemble_af, grounded_extension
from server.contexts.tree.repository import assurance_with_context
from lakatos.verdict.spine import reconcile_standing
from lakatos.verdicts import format_verdict_with_val, receipt_content_sha, verdict_assurance
from lakatos.verdict.certify import gate_check, certify_claim, next_actions as cert_next_actions, is_measurement_owned
from lakatos.claim import ClaimStandingPolicy, evaluate_claim_standing
from lakatos.engine import (
    CredibilityTier,
    EmbeddedInternetEvidence,
    FoundationMap,
    InternetObservation,
    LonginusRef,
    Possibility,
    Realm,
    ResearchEvent,
    ResearchFrame,
    ResearchProject,
    RivalProgrammeLink,
    SourceCredibilityScore,
    TheoryEmbedding,
)
from lakatos.io.replay import LineageReplayGate
from lakatos.io.reconcile import (
    HistoryPayloadError,
    history_event_id,
    validate_history_record,
)
from lakatos.io.envfp import environment_fingerprint as default_environment_fingerprint
from lakatos.io.envfp import fingerprint_sha as default_fingerprint_sha
from lakatos.io.lineage import by_output
from lakatos.io.prov import replay_command
from lakatos.measurement_lock import lock_sha as measurement_lock_content_sha
from lakatos.node_state import NodeState
from lakatos.world_gates import scan_prompt_injection, web_gate, world_action_gate
from server.contexts.audit import fsck as audit_fsck
from server.contexts.tree.judgement_service import (RESULT_MAX_BYTES, SCRIPT_MAX_BYTES,
                                                     isolate_script_file)
from server.contexts.tree.schemas import CritiqueIn, ObservationIn, ResearchEventIn, WorldActionIn
from server.file_hashing import file_sha
from server.ports import (
    GuardedKgOps,
    HistoryAppend,
    KgQuery,
    KgTx,
    KgTxGuardFailed,
    WriterFenceLost,
)


FoundationProvider = Callable[[str], FoundationMap | None]
LineageProvider = Callable[[], Iterable[Any]]
EnvironmentProvider = Callable[[], dict]
FingerprintProvider = Callable[[dict], str]
ReproducibleProvider = Callable[[str, str], bool | None]
StandingProvider = Callable[[str, str], dict]
CalibrationProvider = Callable[[str], dict]
StoreResearchEvent = Callable[[str, str, str, str, str, str, Iterable[str] | None, dict], str]


def _serialized_critique_command(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        scope = getattr(self, 'critique_scope', None) or (lambda: nullcontext())
        with scope():
            return method(self, *args, **kwargs)

    return wrapped


def normalize_critique_attack(
    tree: str,
    node_tag: str,
    raw: str,
) -> tuple[str, bool, bool]:
    """Return canonical attack, direct-node flag, and unambiguous-reference flag."""
    if raw == node_tag:
        return node_tag, True, True
    prefix = tree + "/"
    normalized = raw[len(prefix):] if raw.startswith(prefix) else raw
    return normalized, False, bool(normalized) and "/" not in normalized


def _is_sha256(value) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _is_canonical_absolute_path(value) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        path = Path(value)
        return path.is_absolute() and str(path.resolve()) == value
    except OSError:
        return False


def _bound_measurement_lock(head: dict, locks: list[dict]) -> dict | None:
    """Return the one semantically bound lock payload; duplicate matching locks are corruption."""
    sealed_sha = head.get("measurement_lock_sha")
    if not _is_sha256(sealed_sha):
        return None
    matches = [lock for lock in locks
               if isinstance(lock, dict) and lock.get("lock_sha") == sealed_sha]
    if len(matches) > 1:
        raise HTTPException(409, 'provenance 무결성 실패: duplicate current MeasurementLock')
    if not matches:
        return None
    raw = matches[0].get("payload_json")
    try:
        payload = json.loads(raw) if isinstance(raw, str) else None
        if not isinstance(payload, dict) or measurement_lock_content_sha(payload) != sealed_sha:
            return None
    except (TypeError, ValueError):
        return None
    if not audit_fsck.measurement_lock_payload_matches_head(head, payload):
        return None
    return payload


def _rehash_current_artifact(path: str, expected_sha: str, max_bytes: int, label: str) -> None:
    """Allowed-root, regular-file and size-capped read-time drift check."""
    resolved, info = isolate_script_file(path, max_bytes)
    if resolved is None or str(resolved) != path:
        reason = info.get('reason') if isinstance(info, dict) else 'unresolvable'
        raise HTTPException(409, f'provenance artifact drift: {label} unavailable ({reason})')
    try:
        current_sha = file_sha(str(resolved))
    except OSError as exc:
        raise HTTPException(409, f'provenance artifact drift: {label} rehash failed') from exc
    if current_sha != expected_sha:
        raise HTTPException(409, f'provenance artifact drift: {label} sha256 mismatch')


class EvidenceClaimService:
    """Owns evidence ingestion, standing, claim-standing, and certificates."""

    # KG: seed-lkt-engine-route-evidence-claim-extract-20260616

    def __init__(
        self,
        *,
        kg: KgQuery,
        hist: HistoryAppend,
        foundation: FoundationProvider,
        load_lineage: LineageProvider,
        reproducible_for_node: ReproducibleProvider,
        kg_tx: KgTx | None = None,
        critique_kg_tx: KgTx | None = None,
        standing: StandingProvider | None = None,
        calibration: CalibrationProvider | None = None,
        store_research_event: StoreResearchEvent | None = None,
        environment_fingerprint: EnvironmentProvider = default_environment_fingerprint,
        fingerprint_sha: FingerprintProvider = default_fingerprint_sha,
        critique_ready: Callable[[], None] | None = None,
        critique_scope=None,
        on_semantic_divergence: Callable[[str], None] | None = None,
    ):
        self.kg = kg
        self.kg_tx = kg_tx
        self.critique_kg_tx = critique_kg_tx or kg_tx
        self.hist = hist
        self.foundation = foundation
        self.load_lineage = load_lineage
        self.reproducible_for_node = reproducible_for_node
        self.standing_provider = standing or self.standing
        self.calibration_provider = calibration or (lambda _name: {"n": 0})
        self.store_research_event_provider = store_research_event or self.store_research_event
        self.environment_fingerprint = environment_fingerprint
        self.fingerprint_sha = fingerprint_sha
        self.critique_ready = critique_ready
        self.critique_scope = critique_scope or (lambda: nullcontext())
        self.on_semantic_divergence = on_semantic_divergence

    def _signal_semantic_divergence(self, reason: str) -> None:
        """Close the process-local critique gate after a committed semantic lag."""

        callback = self.on_semantic_divergence
        if callback is not None:
            callback(reason)

    def provenance(self, name: str, tag: str) -> dict:
        rows = self.kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                     OPTIONAL MATCH (e)-[:HAS_RECEIPT]->(hr:VerdictReceipt)
                       WHERE hr.receipt_sha = e.current_receipt_sha
                     WITH e, collect(hr {.*}) AS head_receipts
                     OPTIONAL MATCH (e)-[:HAS_LOCK]->(ml:MeasurementLock)
                     WITH e, head_receipts, collect(ml {.*}) AS measurement_locks
                     OPTIONAL MATCH (e)-[:HAS_PROV]->(p:ProvNode)
                     RETURN e.judge_script AS script, e.result_path AS rp, e.verdict AS verdict,
                            e.judge_script_sha AS sha, e.result_sha256 AS result_sha256,
                            e.source_judge_script_path AS source_script_path,
                            e.source_result_path AS source_result_path,
                            e.measurement_lock_sha AS measurement_lock_sha,
                            e.replay_status AS replay_status, e.replay_reason AS replay_reason,
                            e.regenerated_metric AS regenerated_metric,
                            e.current_receipt_sha AS current_receipt_sha,
                            head_receipts, measurement_locks,
                            collect({id:p.id,kind:p.kind,type:p.type}) AS prov""",
                       tree=name, tag=tag)
        if not rows:
            raise HTTPException(404, '채점 이력 없음')
        if len(rows) != 1:
            raise HTTPException(409, 'provenance 무결성 실패: node projection cardinality '
                                f'{len(rows)} (exactly one required)')
        x = rows[0]
        head_sha = x.get('current_receipt_sha')
        heads = x.get('head_receipts') or []
        graph = [p for p in (x.get('prov') or []) if p.get('id')]

        # No receipt pointer is a pre-ledger row.  It remains inspectable, but mutable node
        # metadata cannot be presented as an authoritative replay recipe.
        if not head_sha:
            if x.get('script') is None:
                raise HTTPException(404, '채점 이력 없음')
            return dict(tag=tag, verdict=x.get('verdict'), script=x.get('script'),
                        script_sha=x.get('sha'), result_path=x.get('rp'), prov_graph=graph,
                        replay=None, authoritative=False,
                        authority_reason='legacy_receipt_not_artifact_bound')
        if len(heads) != 1:
            raise HTTPException(409, 'provenance 무결성 실패: current receipt head cardinality '
                                f'{len(heads)} (exactly one required)')
        head = heads[0]

        # A v1-v3 receipt is honest legacy but does not bind replay inputs.  Never synthesize an
        # authoritative command from its mutable node cache.
        if head.get('replay_status') is None:
            return dict(tag=tag, verdict=x.get('verdict'), script=x.get('script'),
                        script_sha=x.get('sha'), result_path=x.get('rp'), prov_graph=graph,
                        replay=None, authoritative=False,
                        authority_reason='legacy_receipt_not_artifact_bound')

        record = dict(
            verdict=x.get('verdict'), current_receipt_sha=head_sha,
            judge_script=x.get('script'), judge_script_sha=x.get('sha'),
            result_path=x.get('rp'),
            source_judge_script_path=x.get('source_script_path'),
            source_result_path=x.get('source_result_path'),
            result_sha256=x.get('result_sha256'),
            measurement_lock_sha=x.get('measurement_lock_sha'),
            replay_status=x.get('replay_status'), replay_reason=x.get('replay_reason'),
            regenerated_metric=x.get('regenerated_metric'), receipts=[head],
            measurement_locks=x.get('measurement_locks') or [],
        )
        if audit_fsck.valid_replay_head(record) is None:
            raise HTTPException(409, 'provenance 무결성 실패: current replay receipt 내용주소 불일치')
        integrity_ids = {
            'RECEIPT_SHA_CONTENT_MISMATCH', 'REPLAY_DIAGNOSTIC_CACHE_MISMATCH',
            'REPLAY_INPUT_CACHE_MISMATCH', 'RECEIPT_CHAIN_MISMATCH',
        }
        failures = [f for f in audit_fsck.fsck_node(record) if f.check_id in integrity_ids]
        if failures:
            raise HTTPException(409, 'provenance 무결성 실패: '
                                + ', '.join(sorted({f.check_id for f in failures})))

        script, result_path = head.get('judge_script_path'), head.get('result_path')
        if audit_fsck.valid_artifact_head(record) is None:
            return dict(tag=tag, verdict=head.get('verdict'), script=None,
                        script_sha=head.get('judge_script_sha'), result_path=None,
                        result_sha256=None, measurement_lock_sha=None,
                        receipt_sha=head_sha, prov_graph=graph, replay=None,
                        authoritative=False, authority_reason='v4_receipt_not_artifact_bound')

        locks = x.get('measurement_locks') or []
        bound_lock = _bound_measurement_lock(head, locks)
        fully_bound = (
            _is_canonical_absolute_path(script)
            and _is_canonical_absolute_path(result_path)
            and _is_sha256(head.get('judge_script_sha'))
            and _is_sha256(head.get('result_sha256'))
            and bound_lock is not None
        )
        if not fully_bound:
            return dict(tag=tag, verdict=head.get('verdict'), script=script,
                        script_sha=head.get('judge_script_sha'), result_path=result_path,
                        result_sha256=head.get('result_sha256'),
                        measurement_lock_sha=head.get('measurement_lock_sha'),
                        receipt_sha=head_sha, prov_graph=graph, replay=None,
                        authoritative=False, authority_reason='v5_replay_inputs_unbound')

        try:
            current_env_sha = self.fingerprint_sha(self.environment_fingerprint())
        except Exception:  # noqa: BLE001 — inability to establish the current env is non-authority
            return dict(tag=tag, verdict=head.get('verdict'), script=script,
                        script_sha=head.get('judge_script_sha'), result_path=result_path,
                        result_sha256=head.get('result_sha256'),
                        measurement_lock_sha=head.get('measurement_lock_sha'),
                        receipt_sha=head_sha, prov_graph=graph, replay=None,
                        authoritative=False,
                        authority_reason='measurement_environment_unverifiable')
        if bound_lock.get('env_sha') != current_env_sha:
            return dict(tag=tag, verdict=head.get('verdict'), script=script,
                        script_sha=head.get('judge_script_sha'), result_path=result_path,
                        result_sha256=head.get('result_sha256'),
                        measurement_lock_sha=head.get('measurement_lock_sha'),
                        receipt_sha=head_sha, prov_graph=graph, replay=None,
                        authoritative=False, authority_reason='measurement_environment_drift')

        _rehash_current_artifact(script, head['judge_script_sha'], SCRIPT_MAX_BYTES, 'judge_script')
        _rehash_current_artifact(result_path, head['result_sha256'], RESULT_MAX_BYTES, 'result')
        return dict(tag=tag, verdict=head.get('verdict'), script=script,
                    script_sha=head.get('judge_script_sha'), result_path=result_path,
                    result_sha256=head.get('result_sha256'),
                    measurement_lock_sha=head.get('measurement_lock_sha'),
                    receipt_sha=head_sha, prov_graph=graph,
                    replay=replay_command(script or '', result_path or ''),
                    authoritative=True, authority_reason='content_valid_v5_receipt')

    def _critique_standing_snapshot(self, name: str, tag: str) -> dict | None:
        rows = self.kg(
            """MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
               OPTIONAL MATCH (e)-[:HAS_ARGUMENT]->(a:Argument)
               WITH e, [x IN collect({id:a.id, attacks:a.attacks, by:a.by})
                        WHERE x.id IS NOT NULL | x] AS args
               RETURN e.verdict AS verdict,
                      e.valid_until_rebutted AS vur,
                      e.current_receipt_sha AS prev_receipt_sha,
                      args""",
            tree=name,
            tag=tag,
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise HistoryPayloadError(
                f"critique standing node identity is duplicated: {name}/{tag}"
            )
        row = dict(rows[0])
        raw_vur = row.get("vur")
        if raw_vur is not None and type(raw_vur) is not bool:
            raise HistoryPayloadError(
                f"critique standing valid_until_rebutted is malformed: {name}/{tag}"
            )
        row["vur"] = True if raw_vur is None else raw_vur
        args = row.get("args")
        if not isinstance(args, list) or not all(
            isinstance(item, dict)
            and isinstance(item.get("id"), str)
            and isinstance(item.get("attacks"), str)
            and isinstance(item.get("by"), str)
            for item in args
        ):
            raise HistoryPayloadError(
                f"critique standing argument projection is malformed: {name}/{tag}"
            )
        row["args"] = sorted(
            ({"id": item["id"], "attacks": item["attacks"], "by": item["by"]}
             for item in args),
            key=lambda item: (item["id"], item["attacks"], item["by"]),
        )
        return row

    @staticmethod
    def _critique_standing_decision(tag: str, snapshot: dict) -> dict:
        verdict_arg = f"verdict:{tag}"
        arguments, attacks = assemble_af(tag, snapshot["args"])
        stands = verdict_arg in grounded_extension(arguments, attacks)
        decision = reconcile_standing(
            snapshot.get("verdict"),
            stands=stands,
            valid_until_rebutted=bool(snapshot.get("vur")),
        )
        return {"stands": stands, **decision}

    def _reconcile_one_critique_standing(
        self,
        name: str,
        tag: str,
        *,
        attempts: int = 2,
        project_history: bool = True,
    ) -> dict | None:
        """Repair one derived standing invariant with an actor-aware exact CAS."""

        last: dict | None = None
        for _attempt in range(max(1, attempts)):
            snapshot = self._critique_standing_snapshot(name, tag)
            if snapshot is None:
                return None
            decision = self._critique_standing_decision(tag, snapshot)
            last = dict(decision)
            if decision.get("demoted") is not True:
                return last

            ts = datetime.now(timezone.utc).isoformat()
            previous_receipt = snapshot.get("prev_receipt_sha")
            receipt_sha = receipt_content_sha({
                "tree": name,
                "tag": tag,
                "target_id": None,
                "verdict": "former_canonical",
                "verdict_source": "engine",
                "metric_name": None,
                "metric_value": None,
                "novel_confirmed": None,
                "lakatos_status": None,
                "judged_at": ts,
                "judge_script_sha": None,
                "prev_receipt_sha": previous_receipt,
                "engine_rule_sha": ENGINE_RULE_SHA,
            })
            retraction_event_id = f"ob-standing-{receipt_sha}"
            retraction_payload = {
                "from": "CANONICAL",
                "to": "former_canonical",
                "reason": decision["reason"],
                "receipt_sha": receipt_sha,
            }
            retraction_payload_json = validate_history_record(
                name,
                "standing_retraction",
                tag,
                retraction_payload,
                retraction_event_id,
            )
            retraction_query = """MATCH (t:LakatosTree {name:$tree})
                   SET t._tree_write_cas=coalesce(t._tree_write_cas,0)+0
                   WITH t
                   MATCH (t)-[:HAS_NODE]->(e {tag:$tag})
                   SET e._cas=coalesce(e._cas,0)+0
                   WITH t, e
                   WHERE coalesce(e.verdict,'')=coalesce($exp_verdict,'')
                     AND coalesce(e.current_receipt_sha,'')=coalesce($prev_rsha,'')
                     AND coalesce(e.valid_until_rebutted,true)=$exp_vur
                   OPTIONAL MATCH (e)-[:HAS_ARGUMENT]->(a:Argument)
                   WITH t, e, [x IN collect({id:a.id, attacks:a.attacks, by:a.by})
                                    WHERE x.id IS NOT NULL | x] AS arg_fp
                   WHERE size(arg_fp)=size($exp_args)
                     AND all(x IN arg_fp WHERE x IN $exp_args)
                   OPTIONAL MATCH (existing_rec:VerdictReceipt {receipt_sha:$rsha})
                   WITH t, e, arg_fp,
                        [r IN collect(existing_rec) WHERE r IS NOT NULL] AS recs
                   OPTIONAL MATCH (existing_outbox:OutboxEntry {id:$event_id})
                   WITH t, e, arg_fp, recs,
                        [o IN collect(existing_outbox) WHERE o IS NOT NULL] AS outboxes
                   WHERE (size(recs)=0 OR (size(recs)=1 AND coalesce(
                     recs[0].tree=$tree AND recs[0].tag=$tag
                     AND recs[0].verdict='former_canonical'
                     AND recs[0].verdict_source='engine'
                     AND recs[0].judged_at=$ts
                     AND coalesce(recs[0].prev_receipt_sha,'')=coalesce($prev_rsha,'')
                     AND recs[0].engine_rule_sha=$engine_rule_sha, false)))
                     AND (size(outboxes)=0 OR (size(outboxes)=1 AND coalesce(
                       outboxes[0].tree=$tree
                       AND outboxes[0].op='standing_retraction'
                       AND outboxes[0].node_tag=$tag
                       AND outboxes[0].payload=$payload
                       AND outboxes[0].reason='standing_retraction_commit_intent'
                       AND outboxes[0].created_at=$ts
                       AND ((outboxes[0].status='pending'
                             AND outboxes[0].applied_at IS NULL)
                            OR (outboxes[0].status='applied'
                                AND outboxes[0].applied_at IS NOT NULL)), false)))
                   MERGE (rec:VerdictReceipt {receipt_sha:$rsha})
                     ON CREATE SET rec.tree=$tree, rec.tag=$tag,
                       rec.verdict='former_canonical', rec.verdict_source='engine',
                       rec.judged_at=$ts, rec.prev_receipt_sha=$prev_rsha,
                       rec.engine_rule_sha=$engine_rule_sha
                   MERGE (o:OutboxEntry {id:$event_id})
                     ON CREATE SET o.tree=$tree, o.op='standing_retraction',
                       o.node_tag=$tag, o.payload=$payload, o.status='pending',
                       o.created_at=$ts,
                       o.reason='standing_retraction_commit_intent'
                   SET e.verdict='former_canonical', e.verdict_source='engine',
                       e.node_state=$former_node_state,
                       e.current_best_pointer=false, e.standing_retracted_at=$ts,
                       e.current_receipt_sha=$rsha
                   MERGE (e)-[:HAS_RECEIPT]->(rec)
                   RETURN e.tag AS tag,
                     o.tree=$tree AND o.op='standing_retraction'
                     AND o.node_tag=$tag AND o.payload=$payload
                     AND o.reason='standing_retraction_commit_intent'
                     AND ((o.status='pending' AND o.applied_at IS NULL)
                          OR (o.status='applied' AND o.applied_at IS NOT NULL))
                       AS outbox_valid"""
            retraction_params = dict(
                tree=name, tag=tag,
                exp_verdict=snapshot.get("verdict"),
                exp_vur=bool(snapshot.get("vur")), exp_args=snapshot["args"],
                ts=ts, prev_rsha=previous_receipt, rsha=receipt_sha,
                engine_rule_sha=ENGINE_RULE_SHA,
                event_id=retraction_event_id, payload=retraction_payload_json,
                former_node_state=NodeState.FORMER_CANONICAL.value,
            )
            tx_port = getattr(self, "critique_kg_tx", None)
            if tx_port is None:
                rows = self.kg(retraction_query, **retraction_params)
            else:
                tx_rows = tx_port([(retraction_query, retraction_params)])
                rows = tx_rows[0] if tx_rows else []
            if len(rows) == 1 and rows[0].get("outbox_valid") is True:
                if project_history:
                    self.hist(
                        name,
                        "standing_retraction",
                        tag,
                        retraction_payload,
                        event_id=retraction_event_id,
                    )
                return last

        snapshot = self._critique_standing_snapshot(name, tag)
        if snapshot is None:
            return None
        last = self._critique_standing_decision(tag, snapshot)
        if last.get("demoted") is True:
            last = {**last, "demoted": False, "demote_skipped": "concurrent_change"}
        return last

    def audit_critique_standing(self) -> dict:
        """Read-only exhaustive report of standing and persisted-state violations."""

        try:
            rows = self.kg(
                """MATCH (t:LakatosTree)-[:HAS_NODE]->(e)
                   WHERE e.verdict IN ['CANONICAL','former_canonical']
                   OPTIONAL MATCH (e)-[:HAS_ARGUMENT]->(a:Argument)
                   WITH t, e, [x IN collect({id:a.id, attacks:a.attacks, by:a.by})
                                    WHERE x.id IS NOT NULL | x] AS args
                   RETURN t.name AS tree, e.tag AS tag, e.verdict AS verdict,
                          e.node_state AS node_state, args
                   ORDER BY tree, tag"""
            )
            violations = []
            state_violations = []
            for row in rows:
                tree = row.get("tree")
                tag = row.get("tag")
                if not isinstance(tree, str) or not isinstance(tag, str):
                    raise HistoryPayloadError("semantic standing projection is malformed")
                if row.get("verdict") == "former_canonical":
                    if row.get("node_state") != NodeState.FORMER_CANONICAL.value:
                        state_violations.append({
                            "tree": tree,
                            "tag": tag,
                            "node_state": row.get("node_state"),
                        })
                    continue
                snapshot = self._critique_standing_snapshot(tree, tag)
                if snapshot is None:
                    raise HistoryPayloadError("semantic standing node disappeared")
                decision = self._critique_standing_decision(tag, snapshot)
                if decision.get("demoted") is True:
                    violations.append({"tree": tree, "tag": tag})
            failures = []
            if violations:
                failures.append("semantic.critique_standing")
            if state_violations:
                failures.append("semantic.former_node_state")
            return {
                "ok": not failures,
                "checked": len(rows),
                "violations": violations,
                "state_violations": state_violations,
                "failures": failures,
            }
        except Exception as exc:  # noqa: BLE001 - audit is fail-closed and path-safe
            return {
                "ok": False,
                "checked": 0,
                "violations": [],
                "state_violations": [],
                "failures": [f"semantic.audit.{type(exc).__name__}"],
            }

    def _repair_legacy_former_node_state(
        self, name: str, tag: str, expected_state: Any
    ) -> bool:
        tx_port = getattr(self, "critique_kg_tx", None)
        query = (
            """MATCH (t:LakatosTree {name:$tree})
               SET t._tree_write_cas=coalesce(t._tree_write_cas,0)+0
               WITH t
               MATCH (t)-[:HAS_NODE]->(e {tag:$tag})
               WHERE e.verdict='former_canonical'
                 AND ((e.node_state IS NULL AND $expected_state IS NULL)
                      OR e.node_state=$expected_state)
               SET e.node_state=$former_node_state
               RETURN e.tag AS tag"""
        )
        params = dict(
            tree=name, tag=tag, expected_state=expected_state,
            former_node_state=NodeState.FORMER_CANONICAL.value,
        )
        if tx_port is None:
            rows = self.kg(query, **params)
        else:
            tx_rows = tx_port([(query, params)])
            rows = tx_rows[0] if tx_rows else []
        return len(rows) == 1

    def reconcile_critique_standing(self) -> dict:
        """Repair every derived standing violation, then prove a fresh clean scan."""

        initial = self.audit_critique_standing()
        repaired = []
        state_repaired = []
        for item in initial.get("violations", []):
            outcome = self._reconcile_one_critique_standing(
                item["tree"], item["tag"]
            )
            if outcome and outcome.get("demoted") is True:
                repaired.append({"tree": item["tree"], "tag": item["tag"]})
        for item in initial.get("state_violations", []):
            if self._repair_legacy_former_node_state(
                item["tree"], item["tag"], item.get("node_state")
            ):
                state_repaired.append({"tree": item["tree"], "tag": item["tag"]})
        final = self.audit_critique_standing()
        return {
            "ok": final.get("ok") is True,
            "checked": final.get("checked", 0),
            "repaired": repaired,
            "state_repaired": state_repaired,
            "violations": final.get("violations", []),
            "state_violations": final.get("state_violations", []),
            "failures": final.get("failures", []),
        }

    @_serialized_critique_command
    def add_critique(self, name: str, tag: str, c: CritiqueIn) -> dict:
        ready = getattr(self, "critique_ready", None)
        if ready is not None:
            ready()
        arg_full = f'{name}/{c.arg_id}'
        create_claim = uuid4().hex
        (
            normalized_history_attacks,
            attack_targets_node,
            attack_reference_valid,
        ) = normalize_critique_attack(
            name,
            tag,
            c.attacks,
        )
        history_payload = c.model_dump()
        history_payload['attacks'] = normalized_history_attacks
        critique_event_id = history_event_id(name, 'critique', arg_full)
        # Validate before the atomic Neo4j mutation.  Neo4j accepts some strings
        # (notably NUL escapes and lone surrogates) that PostgreSQL JSONB cannot
        # project; committing such an intent would permanently poison replay.
        try:
            history_payload_json = validate_history_record(
                name,
                "critique",
                tag,
                history_payload,
                critique_event_id,
            )
        except HistoryPayloadError as exc:
            raise HTTPException(
                422, "critique contains text PostgreSQL JSONB cannot represent"
            ) from exc
        mutation_ts = datetime.now(timezone.utc).isoformat()
        # fail-loud(나생문 #13): MERGE 가 노드 부재 시 no-op 이면 형제 mutation 과 달리 200·history 를
        #   남겨 provenance 를 오염한다 → RETURN e.tag 로 매칭 확인, 0행이면 hist 전에 404.
        # Lock the tree before re-reading the tree-global argument id.  Argument ids are encoded as
        # ``tree/arg``; the tree lock therefore serializes every contender for that identity even
        # when they target different nodes.  The guarded MERGE is first-write-wins and never SETs
        # an existing argument.  ``lkt_argument_id_unique`` is the schema-level second line of
        # defence for writers outside this service.
        mutation_query = """MATCH (t:LakatosTree {name:$tree})
              SET t._tree_write_cas=coalesce(t._tree_write_cas,0)+0
              WITH t
              MATCH (t)-[:HAS_NODE]->(e {tag:$tag})
              SET e._tree_write_cas=coalesce(e._tree_write_cas,0)+0
              WITH t, e
              OPTIONAL MATCH (existing:Argument {id:$arg_full})
              WITH t, e, [a IN collect(existing) WHERE a IS NOT NULL] AS existing_nodes
              OPTIONAL MATCH (e)-[:HAS_ARGUMENT]->(target:Argument)
                WHERE $attack_reference_valid AND NOT $attack_targets_node
                  AND target.id=$tree+'/'+$normalized_attacks
              WITH t, e, existing_nodes, collect(target.id) AS target_ids
              OPTIONAL MATCH (prior_intent:OutboxEntry {id:$history_event_id})
              WITH t, e, existing_nodes, target_ids,
                   [o IN collect(prior_intent) WHERE o IS NOT NULL] AS prior_intents
              WITH t, e, existing_nodes, prior_intents,
                   CASE WHEN $attack_targets_node THEN $normalized_attacks
                        WHEN $attack_reference_valid AND size(target_ids)=1
                          THEN $normalized_attacks
                        ELSE null END AS normalized_attacks
              WITH t, e, existing_nodes, prior_intents, normalized_attacks,
                   size(existing_nodes) AS preexisting_count,
                   normalized_attacks IS NOT NULL AS target_valid,
                   CASE
                     WHEN size(prior_intents)=0 THEN true
                     WHEN size(prior_intents)=1 THEN coalesce(
                       prior_intents[0].tree=$tree
                       AND prior_intents[0].op='critique'
                       AND prior_intents[0].node_tag=$tag
                       AND prior_intents[0].payload=$history_payload_json
                       AND prior_intents[0].reason='critique_commit_intent'
                       AND prior_intents[0].created_at IS NOT NULL
                       AND ((prior_intents[0].status='pending'
                             AND prior_intents[0].applied_at IS NULL)
                            OR (prior_intents[0].status='applied'
                                AND prior_intents[0].applied_at IS NOT NULL)),
                       false)
                     ELSE false
                   END AS intent_prevalid
              FOREACH (_ IN CASE WHEN target_valid AND preexisting_count=0
                                      AND intent_prevalid THEN [1] ELSE [] END |
                MERGE (a:Argument {id:$arg_full})
                  ON CREATE SET a:LakatosArgument, a._argument_create_claim=$create_claim,
                                a.tree_name=$tree, a.local_id=$arg,
                                a.by=$by, a.kind=$kind, a.body=$body,
                                a.attacks=normalized_attacks, a.at=$ts)
              WITH t, e, normalized_attacks, target_valid, intent_prevalid
              OPTIONAL MATCH (actual:Argument {id:$arg_full})
              WITH t, e, normalized_attacks, target_valid, intent_prevalid,
                   [a IN collect(actual) WHERE a IS NOT NULL] AS actual_nodes
              WITH t, e, normalized_attacks, target_valid, intent_prevalid, actual_nodes,
                   size(actual_nodes) AS existing_count,
                   CASE WHEN size(actual_nodes)=1 THEN actual_nodes[0] ELSE null END AS actual
              WITH t, e, normalized_attacks, target_valid, intent_prevalid,
                   existing_count, actual,
                   coalesce(actual._argument_create_claim=$create_claim, false) AS created,
                   coalesce(existing_count=1
                     AND actual:LakatosArgument
                     AND actual._argument_create_claim IS NULL
                     AND actual.tree_name=$tree AND actual.local_id=$arg
                     AND actual.by=$by AND actual.kind=$kind
                     AND actual.body=$body AND actual.attacks=normalized_attacks
                     AND actual.at IS NOT NULL
                     AND COUNT { MATCH (owner)-[:HAS_ARGUMENT]->(actual) }=1
                     AND EXISTS { MATCH (e)-[:HAS_ARGUMENT]->(actual) }, false) AS idempotent
              FOREACH (_ IN CASE WHEN created THEN [1] ELSE [] END |
                MERGE (e)-[:HAS_ARGUMENT]->(actual)
                REMOVE actual._argument_create_claim)
              FOREACH (_ IN CASE WHEN (created OR idempotent) AND intent_prevalid
                                      THEN [1] ELSE [] END |
                MERGE (o:OutboxEntry {id:$history_event_id, tree:$tree,
                                      op:'critique', node_tag:$tag,
                                      payload:$history_payload_json})
                  ON CREATE SET o.status='pending', o.created_at=$ts,
                                o.reason='critique_commit_intent')
              WITH t, e, normalized_attacks, target_valid, existing_count,
                   created, idempotent
              OPTIONAL MATCH (final_intent:OutboxEntry {id:$history_event_id})
              WITH e, normalized_attacks, target_valid, existing_count,
                   created, idempotent,
                   [o IN collect(final_intent) WHERE o IS NOT NULL] AS final_intents
              WITH e, normalized_attacks, target_valid, existing_count,
                   created, idempotent, final_intents,
                   CASE WHEN size(final_intents)=1 THEN coalesce(
                     final_intents[0].tree=$tree
                     AND final_intents[0].op='critique'
                     AND final_intents[0].node_tag=$tag
                     AND final_intents[0].payload=$history_payload_json
                     AND final_intents[0].reason='critique_commit_intent'
                     AND final_intents[0].created_at IS NOT NULL
                     AND ((final_intents[0].status='pending'
                           AND final_intents[0].applied_at IS NULL)
                          OR (final_intents[0].status='applied'
                              AND final_intents[0].applied_at IS NOT NULL)),
                     false) ELSE false END AS intent_valid
              RETURN e.tag AS tag, target_valid,
                     created,
                     coalesce(idempotent, false) AS idempotent,
                     existing_count AS existing_count,
                     normalized_attacks AS attacks,
                     size(final_intents) AS intent_count,
                     intent_valid AS intent_valid"""
        mutation_params = dict(
            tree=name, tag=tag, arg=c.arg_id, arg_full=arg_full,
            create_claim=create_claim,
            by=c.by, kind=c.kind, body=c.body,
            normalized_attacks=normalized_history_attacks,
            attack_targets_node=attack_targets_node,
            attack_reference_valid=attack_reference_valid,
            ts=mutation_ts,
            history_event_id=critique_event_id,
            history_payload_json=history_payload_json,
        )
        tx_port = getattr(self, "critique_kg_tx", None)
        if tx_port is None:
            tx_port = getattr(self, "kg_tx", None)
        if tx_port is None:
            # Lightweight test/in-process ports predate the transaction seam.
            rows = self.kg(mutation_query, **mutation_params)
        else:
            try:
                tx_rows = tx_port(GuardedKgOps([
                    (
                        """MATCH (t:LakatosTree {name:$tree})
                           SET t._tree_write_cas=coalesce(t._tree_write_cas,0)+0
                           RETURN t.name AS tree""",
                        {"tree": name},
                    ),
                    (mutation_query, mutation_params),
                ]))
            except WriterFenceLost as exc:
                self._signal_semantic_divergence(
                    "runtime.global_writer_fence.lost"
                )
                raise HTTPException(
                    503, "critique writer authority was lost before commit"
                ) from exc
            except KgTxGuardFailed as exc:
                raise HTTPException(
                    404, f'노드 없음: {tag} (critique 대상 부재 — 등재 거부)'
                ) from exc
            rows = tx_rows[1] if len(tx_rows) > 1 else []
        if not rows:
            raise HTTPException(404, f'노드 없음: {tag} (critique 대상 부재 — 등재 거부)')
        claim = rows[0]
        required_result = {
            'target_valid',
            'created',
            'idempotent',
            'existing_count',
            'attacks',
            'intent_count',
            'intent_valid',
        }
        missing_result = required_result.difference(claim)
        if missing_result:
            raise HTTPException(
                500,
                'argument integrity result incomplete: '
                + ', '.join(sorted(missing_result)),
            )
        target_valid = claim['target_valid']
        created = claim['created']
        idempotent = claim['idempotent']
        existing_count = claim['existing_count']
        normalized_attacks = claim['attacks']
        intent_count = claim['intent_count']
        intent_valid = claim['intent_valid']
        result_types_valid = (
            type(target_valid) is bool
            and type(created) is bool
            and type(idempotent) is bool
            and type(existing_count) is int
            and existing_count >= 0
            and (normalized_attacks is None or isinstance(normalized_attacks, str))
            and type(intent_count) is int
            and intent_count >= 0
            and type(intent_valid) is bool
        )
        result_state_valid = (
            (not target_valid or normalized_attacks == normalized_history_attacks)
            and (not created or (
                target_valid and existing_count == 1
                and not idempotent and bool(normalized_attacks)
            ))
            and (not idempotent or (
                target_valid and existing_count == 1
                and not created and bool(normalized_attacks)
            ))
            and (
                (bool(normalized_attacks) and existing_count >= 1)
                if target_valid
                else normalized_attacks is None and not created and not idempotent
            )
            and (not (created or idempotent) or (
                intent_count == 1 and intent_valid
            ))
        )
        if not result_types_valid or not result_state_valid:
            raise HTTPException(500, 'argument integrity result inconsistent')
        if not target_valid:
            raise HTTPException(422, f"attacks target '{c.attacks}' disappeared before commit")
        if not created and not idempotent:
            raise HTTPException(
                409, f"argument '{c.arg_id}' is immutable; concurrent content won the identity")

        # Creators and exact retries persist the same intent atomically with the accepted domain
        # state. PostgreSQL adopts an exact legacy row or inserts once, then verifies immutable
        # content before the pending intent is marked applied.
        history_payload['attacks'] = normalized_attacks
        cause_projected = self.hist(
            name,
            'critique',
            tag,
            history_payload,
            event_id=critique_event_id,
        )
        # Exact retries and the autonomous startup/operator sweep share the same
        # actor-aware standing CAS.  Demotion, receipt, and its PG outbox intent
        # commit in one Neo transaction; process death can therefore be replayed
        # without another client retry.
        out: dict = {
            'ok': True,
            'note': (
                'identical concurrent critique retry — immutable no-op'
                if idempotent else '비판 등재 — 코드 빌딩은 순수 agent(test_result) 담당'
            ),
        }
        if idempotent:
            out['idempotent'] = True
        try:
            standing_result = self._reconcile_one_critique_standing(
                name, tag, project_history=cause_projected is not False
            )
        except Exception:  # noqa: BLE001 - critique+intent already committed
            self._signal_semantic_divergence(
                "runtime.critique_standing.reconciliation_failed"
            )
            out["standing_reconciliation_pending"] = True
        else:
            if standing_result is not None:
                out['standing'] = standing_result
            if cause_projected is False and standing_result is not None:
                self._signal_semantic_divergence(
                    "runtime.critique_standing.causal_projection_pending"
                )
                out["standing_reconciliation_pending"] = True
            if standing_result and standing_result.get("demote_skipped"):
                self._signal_semantic_divergence(
                    "runtime.critique_standing.reconciliation_incomplete"
                )
        return out

    def add_research_event(self, name: str, tag: str, ev: ResearchEventIn) -> dict:
        engine_event = ev.to_engine(tag)
        if engine_event.realm in (Realm.INTERNET, Realm.BASH):
            raise HTTPException(422, f'{engine_event.realm.value} 증거는 generic /event 우회 불가 — '
                                     f'POST /observation(G-Web) 또는 /world-action(G-WorldAction) 게이트 경로 사용')
        ts = ev.created_at or datetime.now(timezone.utc).isoformat()
        event_id = f'{name}/{tag}/event/{engine_event.name}'
        rows = self.kg("""MATCH (t:LakatosTree {name:$tree})
                     SET t._tree_write_cas=coalesce(t._tree_write_cas,0)+0
                     WITH t
                     MATCH (t)-[:HAS_NODE]->(e {tag:$tag})
                     MERGE (ev:ResearchEvent {id:$id})
                     ON CREATE SET ev.name=$event_name, ev.realm=$realm, ev.actor=$actor,
                                   ev.action=$action, ev.target=$tag,
                                   ev.evidence_refs=$evidence_refs, ev.payload=$payload,
                                   ev.created_at=$ts
                     MERGE (e)-[:HAS_RESEARCH_EVENT]->(ev)
                     RETURN ev.id AS id""",
                       tree=name, tag=tag, id=event_id, event_name=engine_event.name,
                       realm=engine_event.realm.value, actor=engine_event.actor,
                       action=engine_event.action, evidence_refs=list(engine_event.evidence_refs),
                       payload=json.dumps(dict(engine_event.payload), ensure_ascii=False), ts=ts)
        if not rows:
            raise HTTPException(404, f'노드 없음: {tag}')
        self.hist(name, 'research_event', tag, {**engine_event.db_record(), 'id': event_id})
        return {'ok': True, 'id': event_id, 'event': engine_event.name}

    def store_research_event(
        self,
        name: str,
        tag: str,
        event_id: str,
        realm: str,
        action: str,
        actor: str,
        evidence_refs: Iterable[str] | None,
        payload: dict,
    ) -> str:
        rows = self.kg("""MATCH (t:LakatosTree {name:$tree})
                     SET t._tree_write_cas=coalesce(t._tree_write_cas,0)+0
                     WITH t
                     MATCH (t)-[:HAS_NODE]->(e {tag:$tag})
                     MERGE (ev:ResearchEvent {id:$id})
                     ON CREATE SET ev.name=$id, ev.realm=$realm, ev.actor=$actor,
                                   ev.action=$action, ev.target=$tag,
                                   ev.evidence_refs=$evidence_refs, ev.payload=$payload,
                                   ev.created_at=$ts
                     MERGE (e)-[:HAS_RESEARCH_EVENT]->(ev)
                     RETURN ev.id AS id""",
                       tree=name, tag=tag, id=event_id, realm=realm, actor=actor, action=action,
                       evidence_refs=list(evidence_refs or []),
                       payload=json.dumps(payload, ensure_ascii=False),
                       ts=datetime.now(timezone.utc).isoformat())
        if not rows:
            raise HTTPException(404, f'노드 없음: {tag}')
        return event_id

    def add_observation(self, name: str, tag: str, o: ObservationIn) -> dict:
        from lakatos.grounding import GROUNDED

        injection = scan_prompt_injection(o.content)
        comps = dict(source_class_weight=o.source_class_weight, link_authority=o.link_authority,
                     primary_source_bonus=o.primary_source_bonus, provenance_score=o.provenance_score,
                     corroboration_score=o.corroboration_score, recency_score=o.recency_score,
                     supply_chain_score=o.supply_chain_score)
        obs = dict(url=o.url, retrieved_at=o.retrieved_at, content_hash=o.content_hash,
                   raw_snapshot_path=o.raw_snapshot_path, source_type=o.source_type,
                   lakatos_location=o.lakatos_location, **comps)
        gate = web_gate(obs, injection=injection)
        if not gate.passed:
            detail = list(gate.reasons)
            if 'trust_components' in detail:
                detail.append('G-Trust: 분해 신뢰 성분 1+ 양수 필요 (bare trust 미지원)')
            raise HTTPException(422, f'G-Web 미통과 — 누락/위반: {detail}')
        payload = {k: str(v) for k, v in obs.items() if v not in (None, '')}
        payload['injection_risk'] = str(injection['risk'])
        payload['injection_signals'] = ','.join(injection['signals'])
        score = SourceCredibilityScore(injection_penalty=injection['risk'],
                                       **{k: (v or 0.0) for k, v in comps.items()})
        payload.update({k: str(round(v, 4)) for k, v in score.as_components().items()})
        tier = score.tier
        if injection['risk'] >= GROUNDED['injection_high_risk_floor']['value'] and tier.value == 'EXTRACTED':
            tier = CredibilityTier.AMBIGUOUS
            payload['injection_tier_capped'] = 'true'
        payload['tier'] = tier.value
        payload['credibility_decomposed'] = 'true'
        payload['confidence'] = str(round(score.trust, 4))
        embedded = self.embedded_observation(name, tag, o, score)
        if embedded is not None:
            projection = embedded.kg_projection()
            payload['theory_basis'] = projection['embedding']['theoretical_basis']
            payload['foundation_refs'] = ','.join(projection['embedding']['foundation_refs'])
            payload['longinus_sourceIds'] = ','.join(projection['edges']['BOUND_BY'])
            payload['rival_programmes'] = ','.join(projection['edges']['RIVAL_EVIDENCE'])
        eid = f'{name}/{tag}/obs/{o.event_id}'
        self.store_research_event_provider(name, tag, eid, 'internet', 'fetch', o.actor, o.evidence_refs, payload)
        if embedded is not None:
            self.bind_embedded_observation(name, tag, eid, embedded)
        self.hist(name, 'observation', tag, {'id': eid, 'url': o.url, 'injection_risk': injection['risk']})
        cred = {'decomposed': payload.get('credibility_decomposed') == 'true',
                'confidence': float(payload['confidence']), 'tier': payload.get('tier'),
                'components': {k: float(payload[k]) for k in SourceCredibilityScore().as_components()
                               if k in payload}}
        out = {'ok': True, 'id': eid, 'gate': 'G-Web', 'injection': injection, 'credibility': cred}
        if embedded is not None:
            out['embedding'] = embedded.kg_projection()
        return out

    @staticmethod
    def _retrieved_at(value: str) -> datetime:
        try:
            return datetime.fromisoformat((value or '').replace('Z', '+00:00'))
        except ValueError:
            return datetime.now(timezone.utc)

    @staticmethod
    def _has_embedding_fields(o: ObservationIn) -> bool:
        return any((
            o.theory_basis,
            o.foundation_refs,
            o.rival_name,
            o.rival_relation,
            o.rival_node,
            o.comparison_axes,
            o.longinus_refs,
        ))

    def embedded_observation(
        self,
        name: str,
        tag: str,
        o: ObservationIn,
        score: SourceCredibilityScore,
    ) -> EmbeddedInternetEvidence | None:
        if not self._has_embedding_fields(o):
            return None
        longinus_refs = tuple(
            LonginusRef(sourceId=ref.sourceId, sourcePath=ref.sourcePath,
                        layer=ref.layer, note=ref.note)
            for ref in o.longinus_refs
        )
        rival_links: tuple[RivalProgrammeLink, ...] = ()
        if o.rival_name or o.rival_relation or o.rival_node or o.comparison_axes:
            if not (o.rival_name and o.rival_relation):
                raise HTTPException(422, 'rival evidence requires rival_name and rival_relation')
            rival_links = (
                RivalProgrammeLink(
                    programme=o.rival_name,
                    relation=o.rival_relation,
                    rival_node=o.rival_node,
                    comparison_axes=tuple(o.comparison_axes),
                    evidence_refs=tuple(o.evidence_refs),
                ),
            )
        try:
            return EmbeddedInternetEvidence(
                observation=InternetObservation(
                    name=o.event_id,
                    url=o.url,
                    query=o.query,
                    retrieved_at=self._retrieved_at(o.retrieved_at),
                    content_hash=o.content_hash or o.raw_snapshot_path,
                    fetch_tool=o.fetch_tool,
                    source_type=o.source_type,
                    credibility=score,
                    raw_snapshot_path=o.raw_snapshot_path or None,
                ),
                tree_name=name,
                node_tag=tag,
                embedding=TheoryEmbedding(
                    lakatos_location=o.lakatos_location,
                    theoretical_basis=o.theory_basis,
                    foundation_refs=tuple(o.foundation_refs),
                    longinus_refs=longinus_refs,
                ),
                rival_links=rival_links,
            )
        except ValueError as exc:
            msg = str(exc)
            if 'longinus' in msg.lower():
                msg = f'Longinus binding required for rival evidence: {msg}'
            raise HTTPException(422, msg) from exc

    def _run_tx(self, ops: list) -> None:
        """B1-step1: 여러 KG write 를 한 단위로. kg_tx 주입됐으면 단일 트랜잭션(원자적),
        없으면 self.kg 순차 실행으로 하위호환(기존 직접 생성 경로 보존)."""
        if not ops:
            return
        if self.kg_tx is not None:
            self.kg_tx(ops)
        else:
            for cypher, params in ops:
                self.kg(cypher, **params)

    def bind_embedded_observation(
        self,
        name: str,
        tag: str,
        event_id: str,
        embedded: EmbeddedInternetEvidence,
    ) -> None:
        """B1-step1: 한 관측의 bind write(LOCATED_IN / longinus / rival)를 단일 kg_tx 로 — 부분 bind
        (위치는 됐는데 longinus/rival 미바인딩)가 갈라지지 않게 한 단위로 커밋. (cross-service run_cycle
        의 의도된 비원자성 결정과는 별개의 좁은 within-method 개선; store↔bind 간은 MERGE 멱등+재실행이 덮음.)"""
        projection = embedded.kg_projection()
        emb = projection['embedding']
        ts = datetime.now(timezone.utc).isoformat()
        ops = [("""MATCH (t:LakatosTree {name:$tree})
              SET t._tree_write_cas=coalesce(t._tree_write_cas,0)+0
              WITH t
              MATCH (t)-[:HAS_NODE]->(e {tag:$tag})
              MATCH (ev:ResearchEvent {id:$event_id})
              SET ev.lakatos_location=$lakatos_location,
                  ev.theoretical_basis=$theoretical_basis,
                  ev.foundation_refs=$foundation_refs
              MERGE (ev)-[:LOCATED_IN]->(e)""",
                dict(tree=name, tag=tag, event_id=event_id,
                     lakatos_location=emb['lakatos_location'],
                     theoretical_basis=emb['theoretical_basis'],
                     foundation_refs=emb['foundation_refs']))]
        if projection['longinus_refs']:
            ops.append(("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                  MATCH (ev:ResearchEvent {id:$event_id})
                  UNWIND $refs AS ref
                  MERGE (rs:ReferenceSite:Longinus {sourceId: ref.sourceId})
                    ON CREATE SET rs.name=ref.sourceId, rs.created_at=$ts
                  SET rs.repo='lakatotree', rs.sourcePath=ref.sourcePath,
                      rs.layer=ref.layer, rs.note=ref.note, rs.updated_at=$ts
                  MERGE (ev)-[:BOUND_BY]->(rs)
                  MERGE (e)-[:BOUND_BY]->(rs)""",
                        dict(tree=name, tag=tag, event_id=event_id,
                             refs=projection['longinus_refs'], ts=ts)))
        if projection['rival_links']:
            ops.append(("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                  MATCH (ev:ResearchEvent {id:$event_id})
                  UNWIND $links AS link
                  MERGE (r:LakatosRivalProgramme {name: link.programme})
                    ON CREATE SET r.created_at=$ts
                  SET r.updated_at=$ts
                  MERGE (t)-[:HAS_RIVAL]->(r)
                  MERGE (ev)-[evr:EVIDENCE_FOR_RIVAL]->(r)
                  SET evr.relation=link.relation, evr.rival_node=link.rival_node,
                      evr.comparison_axes=link.comparison_axes, evr.evidence_refs=link.evidence_refs,
                      evr.observation_event_id=$event_id, evr.updated_at=$ts
                  MERGE (e)-[rr:RIVAL_EVIDENCE]->(r)
                  SET rr.relation=link.relation, rr.rival_node=link.rival_node,
                      rr.comparison_axes=link.comparison_axes, rr.evidence_refs=link.evidence_refs,
                      rr.observation_event_id=$event_id, rr.updated_at=$ts""",
                        dict(tree=name, tag=tag, event_id=event_id,
                             links=projection['rival_links'], ts=ts)))
        self._run_tx(ops)

    def add_world_action(self, name: str, tag: str, a: WorldActionIn) -> dict:
        act = dict(command=a.command, cwd=a.cwd, exit_code=a.exit_code,
                   stdout_summary=a.stdout_summary, stderr_summary=a.stderr_summary,
                   touched_files=a.touched_files, git_diff_hash=a.git_diff_hash)
        gate = world_action_gate(act, require_git_diff=a.require_git_diff)
        if not gate.passed:
            raise HTTPException(422, f'G-WorldAction 미통과 — 누락: {list(gate.reasons)}')
        payload = {'command': a.command, 'cwd': a.cwd, 'exit_code': str(a.exit_code),
                   'stdout_summary': a.stdout_summary[:500], 'stderr_summary': a.stderr_summary[:500],
                   'touched_files': ','.join(a.touched_files)}
        if a.git_diff_hash:
            payload['git_diff_hash'] = a.git_diff_hash
        payload['confidence'] = '0.8' if a.exit_code == 0 else '0.2'
        eid = f'{name}/{tag}/act/{a.event_id}'
        self.store_research_event_provider(name, tag, eid, 'bash', a.command[:60] or 'bash_run',
                                           a.actor, a.evidence_refs, payload)
        self.hist(name, 'world_action', tag, {'id': eid, 'exit_code': a.exit_code})
        return {'ok': True, 'id': eid, 'gate': 'G-WorldAction'}

    def standing(self, name: str, tag: str) -> dict:
        rows = self.kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                     OPTIONAL MATCH (e)-[:HAS_ARGUMENT]->(a:Argument)
                     OPTIONAL MATCH (e)-[:HAS_RECEIPT]->(hr:VerdictReceipt {receipt_sha: e.current_receipt_sha})
                     RETURN e.verdict AS verdict, e.verdict_source AS verdict_source,
                            e.current_receipt_sha AS current_receipt_sha,
                            e.measurement_grade AS measurement_grade, e.replay_status AS replay_status,
                            e.measurement_lock_sha AS measurement_lock_sha,
                            e.assurance_tier_resolved AS assurance_tier_resolved,
                            e.attested_by_did AS attested_by_did,
                            e.temporal_witness_verified AS temporal_witness_verified,
                            t.attestor_dids AS attestor_dids,
                            hr.engine_rule_sha AS engine_rule_sha,
                            collect({id:a.id, attacks:a.attacks, kind:a.kind, by:a.by}) AS args""",
                       tree=name, tag=tag)
        if not rows:
            raise HTTPException(404, f'노드 없음: {tag}')
        verdict_arg = f'verdict:{tag}'
        arguments, attacks = assemble_af(tag, rows[0]['args'])
        ext = grounded_extension(arguments, attacks)
        stands = verdict_arg in ext
        # EXTAUDIT S3 (SLSA 흡수): 채점/진보 어휘는 bare 방출 금지 — VAL 등급을 표면에 강제 동봉.
        # 도출은 읽기 시점(저장 금지) — armed/disarmed progressive 가 표면에서 구분된다(급소 #5).
        # P3(2026-07-28): repository 와 동일 파생으로 L2/L3 까지 재도출(이전엔 무-kwargs L1 천장).
        _att = [str(d).strip() for d in (rows[0].get('attestor_dids') or []) if d and str(d).strip()]
        assurance = assurance_with_context(rows[0], tree_attestors=_att,
                                           engine_rule_floor=effective_floor())
        return dict(tag=tag, verdict=format_verdict_with_val(rows[0]['verdict'], assurance),
                    assurance=assurance, stands=stands,
                    grounded_extension=sorted(ext),
                    # A3: 어느 논증이 *패퇴*했는지(공격받고 grounded extension 밖) 명시 — 사람이 왜
                    # 판결이 서는지/안 서는지 본다. Dung 경로는 이미 e2e 배선됨, 이건 가시성 echo.
                    defeated=sorted(set(arguments) - set(ext)),
                    note='stands=False → 막지 못한 의문 존재, 판결 재검토 필요 (코드빌딩=순수agent)')

    def research_events(self, name: str, tag: str) -> dict:
        rows = self.research_event_rows(name, tag)
        if not rows:
            raise HTTPException(404, f'노드 없음: {tag}')
        events = [event for row in rows if (event := self.event_row_dict(tag, row)) is not None]
        return {"tag": tag, "count": len(events), "events": events}

    def claim_standing(self, name: str, tag: str, require_replay: bool = True) -> dict:
        rows = self.kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                     OPTIONAL MATCH (e)-[:HAS_ARGUMENT]->(a:Argument)
                     RETURN e.tag AS tag, e.verdict AS verdict, e.source_trust AS source_trust,
                            e.verdict_source AS verdict_source, e.judge_script AS judge_script,
                            e.judge_script_sha AS judge_script_sha,
                            coalesce(e.source_result_path, e.result_path) AS result_path,
                            collect({id:a.id, attacks:a.attacks, kind:a.kind, by:a.by}) AS args""",
                       tree=name, tag=tag)
        if not rows:
            raise HTTPException(404, f'노드 없음: {tag}')
        x = rows[0]
        result_path = x.get('result_path') or ''
        frame = ResearchFrame(ResearchProject(name=name, goal='claim standing'))
        frame.open_possibility(Possibility(tag, f'claim standing for {name}/{tag}',
                                           evidence_refs=((result_path,) if result_path else ())))
        # ``source_trust``, script and result_path are metadata, not observations.  Upper/lower
        # standing consumes only append-only ResearchEvent rows below; a real BASH run enters via
        # the gated world-action route, and internet evidence via the observation route.
        for arg in x.get('args') or []:
            event = self.event_from_argument(tag, arg)
            if event is not None:
                frame.record_event(event)
        for row in self.research_event_rows(name, tag):
            event = self.event_from_row(tag, row)
            if event is not None:
                frame.record_event(event)

        lineage = None
        if result_path:
            ds = list(self.load_lineage())
            if result_path in by_output(ds):
                cur_env = self.fingerprint_sha(self.environment_fingerprint())
                lineage = LineageReplayGate.evaluate(
                    result_path,
                    ds,
                    sources={d.output for d in ds if d.kind == 'source'},
                    current_env=cur_env,
                )

        standing_result = evaluate_claim_standing(
            tag,
            frame=frame,
            foundation=self.foundation(name),
            lineage=lineage,
            policy=ClaimStandingPolicy(require_replay=require_replay),
        )
        return standing_result.to_dict()

    def node_certificate(self, name: str, tag: str) -> dict:
        rows = self.kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                     OPTIONAL MATCH (e)-[:HAS_RECEIPT]->(hr:VerdictReceipt)
                       WHERE hr.receipt_sha = e.current_receipt_sha
                     WITH e, collect(hr {.*}) AS head_receipts
                     OPTIONAL MATCH (e)-[:HAS_LOCK]->(ml:MeasurementLock)
                     RETURN e.verdict AS verdict, e.verdict_source AS vsrc,
                            e.pred_metric AS pm, e.judge_script AS script,
                            e.judge_script_sha AS sha, e.result_path AS rp,
                            e.result_sha256 AS result_sha256,
                            e.source_judge_script_path AS source_script_path,
                            e.source_result_path AS source_result_path,
                            e.measurement_lock_sha AS measurement_lock_sha,
                            e.replay_status AS replay_status,
                            e.replay_reason AS replay_reason,
                            e.regenerated_metric AS regenerated_metric,
                            e.current_receipt_sha AS current_receipt_sha,
                            e.measurement_grade AS mg, e.metric_value AS mv,
                            head_receipts, collect(ml {.*}) AS measurement_locks""",
                       tree=name, tag=tag)
        if not rows:
            raise HTTPException(404, f'노드 없음: {tag}')
        if len(rows) != 1:
            raise HTTPException(409, 'certificate 무결성 실패: node projection cardinality '
                                f'{len(rows)} (exactly one required)')
        x = rows[0]
        checks = []
        prereg = x['vsrc'] == 'scripted' and x['pm'] is not None and bool(x['script'])
        checks.append(gate_check('preregistered', prereg,
                                 f"{x['script']}:{(x['sha'] or '')[:12]}" if prereg else '',
                                 '' if prereg else '사전등록+스크립트 채점 이력 없음(또는 script 미기록)'))
        rep = self.reproducible_for_node(name, tag)
        checks.append(gate_check('reproducible', rep is True,
                                 x['rp'] or '' if rep is True else '',
                                 '' if rep is True else
                                 ('계보 미기록 — 인증은 기록을 요구' if rep is None else 'raw root 재생성 불가')))
        st = self.standing_provider(name, tag)
        checks.append(gate_check('stands', bool(st['stands']),
                                 ','.join(st['grounded_extension']) if st['stands'] else '',
                                 '' if st['stands'] else '미해소 의문 존재'))
        from lakatos.grounding import GROUNDED
        cal = self.calibration_provider(name)
        # verifier-rigor 연구 P0-#2 (2026-07-21): 옛 G4 는 판관이 이미 계산해 손에 쥔 ECE(provider dict 의
        #   calibration_error)를 버리고 존재(n≥1)만 확인해 ECE=0.57 과신도 'calibrated' 인증했다(활성
        #   name↔behavior lie: certify.py:9 는 'ECE 검사'라 주장). grounded ECE 상한 강제 — 방법=Guo2017,
        #   고정-bin ECE=하한(Kumar2019)이라 BLOCK 방향 보수적(위양성 차단 없음), n<min_n 은 noise→abstain.
        _ece_max = GROUNDED['ece_gate_max']['value']
        _ece_min_n = GROUNDED['ece_gate_min_n']['value']
        _ece = cal.get('calibration_error')
        _cal_ok = cal['n'] >= _ece_min_n and _ece is not None and _ece <= _ece_max
        checks.append(gate_check('calibrated', _cal_ok,
                                 f"/api/tree/{name}/calibration n={cal['n']} ECE={_ece}≤{_ece_max} "
                                 f"(tree-level, Guo2017; 고정-bin ECE=하한 Kumar2019)" if _cal_ok else '',
                                 '' if _cal_ok else (
                                     'novel 등록 예측의 보정 기록 0건(트리 수준)' if cal['n'] == 0 else
                                     f'보정 표본 부족 n={cal["n"]}<{_ece_min_n}(ECE noise)' if cal['n'] < _ece_min_n else
                                     'ECE 미제공' if _ece is None else
                                     f'ECE={_ece}>{_ece_max}(과신/과소보정)')))

        valid_tiers = {'literature', 'policy_in_scale', 'policy'}
        grounded_ok = bool(GROUNDED) and all(g.get('tier') in valid_tiers for g in GROUNDED.values())
        checks.append(gate_check('grounded', grounded_ok,
                                 'lakatos/grounding.py GROUNDED tier registry' if grounded_ok else '',
                                 '시스템 수준 불변식 — 채점 상수 전부 tier 공개(노드별 아님)'
                                 if grounded_ok else 'GROUNDED 레지스트리에 tier 미표기 상수 존재'))
        # G6 measurement_owned (측정주권 load-bearing, 2026-07-03): client_asserted(무replay·무서명) 측정값은
        # 인증 불가. 측정값 없는 노드(mv is None: 질적/problem)는 측정소유 무의미 → 자동통과(SCOPED).
        mg = x['mg']
        has_metric = x['mv'] is not None
        grade_owned = is_measurement_owned(mg, has_metric)
        measurement_bound = not has_metric
        binding_reason = ''
        heads = x.get('head_receipts') or []
        head = heads[0] if len(heads) == 1 else None
        if has_metric and grade_owned:
            if head is None:
                binding_reason = (f'current receipt head cardinality={len(heads)} '
                                  '(exactly one required)')
            else:
                record = dict(
                    verdict=x.get('verdict'), current_receipt_sha=x.get('current_receipt_sha'),
                    judge_script=x.get('script'), judge_script_sha=x.get('sha'),
                    result_path=x.get('rp'), result_sha256=x.get('result_sha256'),
                    source_judge_script_path=x.get('source_script_path'),
                    source_result_path=x.get('source_result_path'),
                    measurement_lock_sha=x.get('measurement_lock_sha'),
                    replay_status=x.get('replay_status'), replay_reason=x.get('replay_reason'),
                    regenerated_metric=x.get('regenerated_metric'), receipts=[head],
                    measurement_locks=x.get('measurement_locks') or [],
                )
                integrity_ids = {
                    'RECEIPT_SHA_CONTENT_MISMATCH', 'REPLAY_DIAGNOSTIC_CACHE_MISMATCH',
                    'REPLAY_INPUT_CACHE_MISMATCH', 'MEASUREMENT_LOCK_CONTENT_MISMATCH',
                    'RECEIPT_CHAIN_MISMATCH',
                }
                failures = [f for f in audit_fsck.fsck_node(record)
                            if f.check_id in integrity_ids]
                artifact_shape_valid = (
                    _is_canonical_absolute_path(head.get('judge_script_path'))
                    and _is_canonical_absolute_path(head.get('result_path'))
                    and _is_sha256(head.get('judge_script_sha'))
                    and _is_sha256(head.get('result_sha256'))
                )
                bound_lock = (_bound_measurement_lock(
                    head, x.get('measurement_locks') or [])
                    if (audit_fsck.valid_artifact_head(record) is not None
                        and artifact_shape_valid and not failures)
                    else None)
                node_semantics_match = (
                    head.get('measurement_grade') == mg
                    and head.get('metric_value') == x.get('mv')
                    and head.get('replay_status') == x.get('replay_status')
                )
                if failures:
                    binding_reason = 'receipt/lock integrity: ' + ', '.join(
                        sorted({f.check_id for f in failures}))
                elif bound_lock is None:
                    binding_reason = 'current v5 receipt has no content/semantic-valid bound lock'
                elif not node_semantics_match:
                    binding_reason = 'node measurement cache differs from current v5 receipt'
                else:
                    try:
                        current_env_sha = self.fingerprint_sha(self.environment_fingerprint())
                    except Exception:  # noqa: BLE001 — certificate must fail closed
                        binding_reason = 'current measurement environment unavailable'
                    else:
                        if bound_lock.get('env_sha') != current_env_sha:
                            binding_reason = 'measurement environment drift'
                        else:
                            try:
                                _rehash_current_artifact(
                                    head.get('judge_script_path'), head.get('judge_script_sha'),
                                    SCRIPT_MAX_BYTES, 'judge_script')
                                _rehash_current_artifact(
                                    head.get('result_path'), head.get('result_sha256'),
                                    RESULT_MAX_BYTES, 'result')
                            except HTTPException as exc:
                                binding_reason = str(exc.detail)
                            else:
                                measurement_bound = True
        owned = grade_owned and measurement_bound
        checks.append(gate_check('measurement_owned', owned,
                                 (f"measurement_grade={mg or 'n/a(측정값 없음)'}"
                                  + (f" lock={head.get('measurement_lock_sha')}" if has_metric else ''))
                                 if owned else '',
                                 '' if owned else
                                 ((binding_reason + '; ') if binding_reason else '')
                                 + f"측정값 grade={mg or 'client_asserted'} — 값소유(server_regenerated: "
                                   'replay 재유도) 또는 attested(트리 attestor_dids 선언 allow-list 신원 서명) '
                                   '및 current v5 MeasurementLock 필요; authored(자기서명)는 authorship 증명일 뿐 '
                                   '권위 아님(jp5)'))
        # jp1: 판관 정체성을 인증서 payload 에 동봉 — sealed(head receipt 봉인값; v1 legacy=None=익명 판관)
        #   vs current(이 프로세스의 규칙 정체성). 독자는 '누가 찍었고 지금 판관과 같은가'를 읽을 수 있다.
        cert = certify_claim(f'{name}/{tag}', checks, dict(
            as_of=datetime.now(timezone.utc).isoformat(),
            engine_rule_sha=dict(sealed=head.get('engine_rule_sha') if head else None,
                                 current=ENGINE_RULE_SHA),
            shas={k: v for k, v in {(x['script'] or ''): (x['sha'] or '')}.items() if k and v}))
        return dict(claim_id=cert.claim_id, certified=cert.certified, missing=list(cert.missing),
                    checks=[dict(gate=c.gate, passed=c.passed, evidence_ref=c.evidence_ref,
                                 note=c.note) for c in cert.checks],
                    evidence_window=cert.evidence_window, limits=cert.limits,
                    next_actions=cert_next_actions(cert))

    def research_event_rows(self, name: str, tag: str) -> list[dict]:
        return self.kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                     OPTIONAL MATCH (e)-[:HAS_RESEARCH_EVENT]->(ev:ResearchEvent)
                     RETURN ev.id AS id, ev.name AS name, ev.realm AS realm, ev.actor AS actor,
                            ev.action AS action, ev.evidence_refs AS evidence_refs,
                            ev.payload AS payload, ev.created_at AS created_at,
                            ev.lakatos_location AS lakatos_location,
                            ev.theoretical_basis AS theoretical_basis,
                            ev.foundation_refs AS foundation_refs,
                            [(ev)-[evr:EVIDENCE_FOR_RIVAL]->(rp:LakatosRivalProgramme) |
                              {programme:rp.name, relation:evr.relation,
                               rival_node:evr.rival_node,
                               comparison_axes:evr.comparison_axes,
                               evidence_refs:evr.evidence_refs}] AS rival_links,
                            [(ev)-[:BOUND_BY]->(rs:ReferenceSite) |
                              {sourceId:rs.sourceId, sourcePath:rs.sourcePath,
                               layer:rs.layer, note:rs.note}] AS longinus_refs
                     ORDER BY ev.created_at, ev.name""", tree=name, tag=tag)

    @staticmethod
    def event_from_argument(tag: str, arg: dict) -> ResearchEvent | None:
        if not arg.get('id'):
            return None
        short = arg['id'].split('/')[-1]
        kind = (arg.get('kind') or 'comment').lower()
        action = 'doubt' if kind == 'doubt' else ('human_verdict' if kind in {'evaluation', 'verdict'} else kind)
        payload = (('confidence', '0.75'),) if action == 'human_verdict' else ()
        return ResearchEvent(
            name=short,
            realm=Realm.HUMAN,
            actor=arg.get('by') or 'human',
            action=action,
            target=tag,
            evidence_refs=(arg['id'],),
            payload=payload,
        )

    @staticmethod
    def event_from_row(tag: str, row: dict) -> ResearchEvent | None:
        if not row.get('name') or not row.get('realm'):
            return None
        try:
            realm = Realm(row['realm'])
        except ValueError:
            return None
        payload_raw = row.get('payload') or '{}'
        if isinstance(payload_raw, str):
            try:
                payload = json.loads(payload_raw)
            except json.JSONDecodeError:
                payload = {}
        else:
            payload = payload_raw
        return ResearchEvent(
            name=row['name'],
            realm=realm,
            actor=row.get('actor') or '',
            action=row.get('action') or '',
            target=tag,
            evidence_refs=tuple(row.get('evidence_refs') or []),
            payload=tuple((str(k), str(v)) for k, v in payload.items()),
        )

    @classmethod
    def event_row_dict(cls, tag: str, row: dict) -> dict | None:
        event = cls.event_from_row(tag, row)
        if event is None:
            return None
        return {
            "id": row.get("id") or "",
            "name": event.name,
            "realm": event.realm.value,
            "actor": event.actor,
            "action": event.action,
            "target": event.target,
            "evidence_refs": list(event.evidence_refs),
            "payload": dict(event.payload),
            "lakatos_location": row.get("lakatos_location") or "",
            "theoretical_basis": row.get("theoretical_basis") or "",
            "foundation_refs": list(row.get("foundation_refs") or []),
            "rival_links": list(row.get("rival_links") or []),
            "longinus_refs": list(row.get("longinus_refs") or []),
            "created_at": row.get("created_at"),
        }
