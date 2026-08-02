"""Chunked KG writer for Lakatos tree mutations.

# KG: seed-lkt-engine-mutation-writer-20260616
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from uuid import uuid4

from lakatos import assurance
from lakatos.io.reconcile import (
    HistoryPayloadError,
    canonical_history_payload,
    validate_history_record,
)
from lakatos.node_state import NodeState
from lakatos.verdicts import MUTATION_PROTECTED_SOURCES, is_self_report_blocked_verdict
from server.contexts.tree.schemas import NodeIn, ParentEdgeIn, QuestionIn
from server.ports import GuardedKgOps, KgTx, KgTxGuardFailed

# G1(git-흡수 2026-07-02, S3 봉합): 노드-쓰기는 verdict 의 유일 발행처가 아니다 — 채점(scripted/engine/…)은
#   judgement_service 가 CAS 로 쓴다. 그런데 add_node/upsert_nodes 가 verdict/node_state/metric_* 를 무가드
#   블랭킷 SET 해, 이미 채점된 tag 를 같은 tag 로 다시 쓰면 scripted 'rejected'(BF 1/6)가 draft 'proof' 로 덮여
#   부적 증거가 credence 에서 지워졌다(H9 리터럴 스캐너가 못 보는 파라미터화 SET). git 의 first-write-wins
#   발행(object-file.c:408-472: 이미 바인딩된 이름은 재바인딩 불가)을 이식: 기존 노드의 verdict_source 가
#   *영수증*(FORCEFUL_SOURCES)이면 verdict-bearing 필드를 MATCH 시 보존, 아니면(draft) 정상 갱신. DB-side CASE 라
#   원자적(읽고-쓰기 race 없음). verdict *권위*는 여전히 judge/set_verdict 층에 — writer 는 파괴만 못 한다.
#   verdict-bearing 필드만 CASE 로 가드; 메타(comment/algorithm/script/…)는 항상 갱신(draft 편집 보존).
# 2026-08-02 legacy audit: source/pointer가 유실된 정전 노드와 relationship-only receipt도
# authority다. cache 한 필드만 보는 술어는 복구 가능한 원장을 generic writer가 먼저 파괴한다.
_FORCEFUL = sorted(MUTATION_PROTECTED_SOURCES)
_PRESERVE_NODE_AUTHORITY = (
    "coalesce(e.verdict_source,'') IN $forceful "
    "OR NOT coalesce(e.verdict,'') IN ['', 'proof'] "
    "OR coalesce(e.node_state,'DRAFT') <> 'DRAFT' "
    "OR e.current_receipt_sha IS NOT NULL "
    "OR has_any_receipt"
)
_PRESERVE_IF_SCORED = (
    "e.verdict = CASE WHEN {preserve} THEN e.verdict ELSE {v} END, "
    "e.node_state = CASE WHEN {preserve} THEN e.node_state ELSE {ns} END, "
    "e.metric_name = CASE WHEN {preserve} THEN e.metric_name ELSE {mn} END, "
    "e.metric_value = CASE WHEN {preserve} THEN e.metric_value ELSE {mv} END, "
    "e.metric_scope = CASE WHEN {preserve} THEN e.metric_scope ELSE {ms} END"
)

# A receipt-backed measurement's result path is part of its content-addressed replay identity.
# Promotion changes scripted to admin without discarding that chain, so preservation follows judged
# non-prediction authority. A prediction receipt alone seals a spec, not a result path, and must not
# freeze a later legitimate result artifact.
_PRESERVE_MEASURED_AUTHORITY = (
    "coalesce(e.verdict_source,'') IN $forceful "
    "OR has_measured_receipt"
)
_PRESERVE_RESULT_PATH_IF_MEASURED = (
    "e.result_path = CASE WHEN {preserve} "
    "THEN e.result_path ELSE {rp} END"
)


@dataclass(frozen=True)
class WriteSummary:
    tx_count: int = 0
    op_count: int = 0
    rows: int = 0

    def plus(self, other: "WriteSummary") -> "WriteSummary":
        return WriteSummary(
            tx_count=self.tx_count + other.tx_count,
            op_count=self.op_count + other.op_count,
            rows=self.rows + other.rows,
        )


@dataclass(frozen=True)
class DurableTreeBundleWrite:
    """One committed tree bundle plus its retryable history intent."""

    summary: WriteSummary
    event_id: str
    payload: dict
    idempotent: bool = False
    generation: int | None = None
    superseded: bool = False


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tree_upsert_history_payload(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != {
        "nodes", "questions", "tx_count", "policy_warnings",
    }:
        raise ValueError("tree upsert history payload has an invalid shape")
    if not (
        type(value.get("nodes")) is int and value["nodes"] >= 0
        and type(value.get("questions")) is int and value["questions"] >= 0
        and value.get("tx_count") == 1
        and isinstance(value.get("policy_warnings"), list)
        and all(
            isinstance(item, str) and bool(item)
            for item in value["policy_warnings"]
        )
    ):
        raise ValueError("tree upsert history payload has invalid values")
    return dict(value)


def _strict_canonical_json_object(value: object) -> dict:
    if not isinstance(value, str):
        raise ValueError("durable payload must be canonical JSON text")

    def unique_object(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = item
        return result

    parsed = json.loads(
        value,
        object_pairs_hook=unique_object,
        parse_constant=lambda token: (_ for _ in ()).throw(
            ValueError(f"non-finite JSON number: {token}")
        ),
    )
    if not isinstance(parsed, dict):
        raise ValueError("durable payload must decode to an object")
    canonical = json.dumps(
        parsed,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    if canonical != value:
        raise ValueError("durable payload is not canonical JSON")
    return parsed


def _history_request_value(value: object) -> object:
    """Convert immutable request collections to their JSON representation."""
    if isinstance(value, Mapping):
        return {str(key): _history_request_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_history_request_value(item) for item in value]
    return value


def _chunks(items: Sequence, size: int):
    size = max(1, size)
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _node_row(node: NodeIn, ts: str) -> dict:
    return {**node.model_dump(), "ts": ts}


def _question_row(question: QuestionIn, ts: str) -> dict:
    return {**question.model_dump(), "ts": ts}


def _reject_scored(nodes: Sequence[NodeIn]) -> None:
    """prom-honesty/1 (적대감사 2026-06-20, 재검증 강화 2026-06-21): writer 는 e.verdict 의 *유일 발행처* —
    *스코어링·진보* 판결(scripted ∪ engine ∪ PROGRESS_VERDICTS: progressive·progressive_conditional·
    CANONICAL·former_canonical …)은 채점/promotion gate 만 부여한다. 노드-쓰기로 들어온 self-report 판결을
    by-construction 으로 거부(validator 422 의 구조적 백스톱; validator 를 우회한 내부 호출도 여기서 막는다).
    구조/행정 어휘만 통과. scripted/engine 만 막으면 CANONICAL/former_canonical 누수가 남는다(적대 재검증 발견)."""
    bad = [n.verdict for n in nodes if is_self_report_blocked_verdict(n.verdict)]
    if bad:
        raise ValueError(f"prom-honesty/1: 노드-쓰기로 스코어링/진보 판결 발행 불가(self-report 차단): {bad}")


class TreeNotFound(Exception):
    """add_node 대상 나무가 KG 에 없음(MATCH 0행). 침묵 no-op 대신 fail-loud — mutations 가 404 로 번역.
    (service 경로는 load_tree_data 가 먼저 404; 이건 writer 직접호출까지 막는 defense-in-depth.)"""


class TreeHistoryProtected(Exception):
    """A critique ledger still owns Argument/Outbox bindings under this tree."""


class TreeNotEmpty(Exception):
    """A non-cascade delete observed nodes while holding the tree lock."""


class TreeReceiptProtected(Exception):
    """An immutable verdict/prediction receipt protects this tree."""


class TreeScopeConflict(Exception):
    """Legacy cross-tree node/frontier sharing makes physical delete unsafe."""


class CycleClaimLost(Exception):
    """A run-cycle ownership token no longer names its node."""


class TreeAlreadyExists(Exception):
    """create-only 원자 claim 이 기존 동명 나무를 관측함 — mutations 가 409 로 번역."""


class TreeIdempotencyConflict(Exception):
    """One tree-mutation idempotency key was reused for a different request."""


class TreeIncarnationConflict(Exception):
    """A destructive write no longer targets the incarnation selected by its caller."""


class TierDowngrade(Exception):
    """G6: assurance_tier 다운그레이드 선언이 단조 ratchet CAS 에 거부됨 — mutations 가 409 로 번역.
    DB-side CASE(assurance.cypher_tier_rank_case 생성물)가 원자 판정하고, writer 는 RETURN 된 결과가
    선언과 다르면(=하향이라 관철 안 됨) raise 한다(읽고-쓰기 race 없음)."""


class BudgetRaiseConfirmationRequired(Exception):
    """The locked tree state makes this write a budget raise without confirmation."""


class BudgetRaiseCertificateRequired(Exception):
    """A locked attestor policy did not match a verified budget-raise certificate."""


class TreeBudgetStateCorrupt(Exception):
    """A legacy cycle_budget value is not an integer and cannot be compared safely."""


# G6 단조 ratchet 의 DB-side 랭크 CASE — 서열 정본(assurance.TIER_RANK)에서 생성(표류 불가).
_TIER_RANK_CASE = assurance.cypher_tier_rank_case("t.assurance_tier")


class TreeKgWriter:
    """Owns Cypher write shape for the tree context."""

    # KG: seed-lkt-engine-mutation-writer-20260616

    def __init__(self, kg_tx: KgTx, *, chunk_size: int = 100):
        self.kg_tx = kg_tx
        self.chunk_size = max(1, chunk_size)

    def add_node(
        self, tree: str, node: NodeIn, parent_edges: Sequence[ParentEdgeIn]
    ) -> WriteSummary:
        summary, _created = self._add_node(
            tree, node, parent_edges, cycle_claim=None
        )
        return summary

    def add_cycle_node(
        self,
        tree: str,
        node: NodeIn,
        parent_edges: Sequence[ParentEdgeIn],
        claim: str,
    ) -> tuple[WriteSummary, bool]:
        return self._add_node(tree, node, parent_edges, cycle_claim=claim)

    def _add_node(
        self,
        tree: str,
        node: NodeIn,
        parent_edges: Sequence[ParentEdgeIn],
        *,
        cycle_claim: str | None,
    ) -> tuple[WriteSummary, bool]:
        """Single-node compatibility path: node and branch edges share one tx."""
        _reject_scored([node])   # prom-honesty/1: 스크립트 판결 self-report 차단(by-construction)
        cycle_create_claim = uuid4().hex if cycle_claim is not None else None
        ops: list[tuple[str, dict]] = [
            (
                """MATCH (t:LakatosTree {name:$tree})
               SET t._tree_write_cas=coalesce(t._tree_write_cas,0)+0
               WITH t
               OPTIONAL MATCH (t)-[:HAS_NODE]->(required_parent)
                 WHERE required_parent.tag IN $parent_tags
               WITH t, count(DISTINCT required_parent) AS parent_count
               WHERE parent_count=size($parent_tags)
               MERGE (e:LakatosNode:PrismExperiment {name:$tree+'/'+$tag})
                 ON CREATE SET e._cycle_created_by=$cycle_claim,
                               e._cycle_claimed_at=$ts,
                               e._cycle_create_claim=$cycle_create_claim
               WITH t, e,
                    e._cycle_created_by IS NOT NULL
                      AND ($cycle_claim IS NULL
                           OR e._cycle_created_by <> $cycle_claim) AS claim_conflict,
                    $cycle_claim IS NOT NULL
                      AND coalesce(e._cycle_create_claim=$cycle_create_claim, false)
                        AS cycle_created
               OPTIONAL MATCH (e)-[:HAS_RECEIPT]->(authority_receipt:VerdictReceipt)
               WITH t, e, claim_conflict, cycle_created,
                    count(authority_receipt) > 0 AS has_any_receipt,
                    count(CASE
                      WHEN coalesce(authority_receipt.receipt_kind,'verdict')
                             <> 'prediction'
                      THEN authority_receipt
                    END) > 0 AS has_measured_receipt
               WITH t, e, claim_conflict, cycle_created, has_any_receipt,
                    (""" + _PRESERVE_NODE_AUTHORITY + """)
                      AS preserve_node_authority,
                    (""" + _PRESERVE_MEASURED_AUTHORITY + """)
                      AS preserve_measured_authority
               REMOVE e._cycle_create_claim
               FOREACH (_ IN CASE WHEN claim_conflict OR cycle_created THEN [] ELSE [1] END |
                 REMOVE e._cycle_created_by, e._cycle_claimed_at)
               FOREACH (_ IN CASE WHEN claim_conflict THEN [] ELSE [1] END |
                 SET e.tag=$tag, e.script=$script,
                   e.algorithm=$algorithm, e.comment=$comment, e.limitation=$limitation,
                   e.open_question=$open_question, e.recorded_at=$ts, e.author=$author
                 MERGE (t)-[:HAS_NODE]->(e))
               FOREACH (_ IN CASE
                 WHEN claim_conflict THEN [] ELSE [1] END |
                 SET """ + _PRESERVE_RESULT_PATH_IF_MEASURED.format(
                       preserve="preserve_measured_authority",
                       rp="$result_path") + """)
               FOREACH (_ IN CASE
                 WHEN claim_conflict THEN [] ELSE [1] END |
                 SET """ + _PRESERVE_IF_SCORED.format(
                       preserve=_PRESERVE_NODE_AUTHORITY,
                       v="$verdict", ns="$node_state",
                       mn="$metric_name", mv="$metric_value", ms="$metric_scope") + """)
               RETURN t AS t, cycle_created AS cycle_created,
                      CASE WHEN claim_conflict THEN 'claim_conflict' ELSE 'ok' END
                        AS guard_status""",
                dict(tree=tree, ts=_utc_now(), node_state=NodeState.DRAFT.value,
                     cycle_claim=cycle_claim,
                     cycle_create_claim=cycle_create_claim,
                     parent_tags=sorted({edge.tag for edge in parent_edges}),
                     forceful=_FORCEFUL, **node.model_dump()),
            )
        ]
        for edge in parent_edges:
            ops.append(
                (
                    """MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                       MATCH (t)-[:HAS_NODE]->(p {tag:$parent})
                       REMOVE p._cycle_created_by, p._cycle_claimed_at
                       MERGE (e)-[r:BRANCHED_FROM]->(p)
                       SET r.inferred=$inferred, r.relation_kind=$relation_kind, r.evidence_ref=$evidence_ref""",
                    dict(
                        tree=tree,
                        tag=node.tag,
                        parent=edge.tag,
                        inferred=edge.inferred,
                        relation_kind=edge.relation_kind,
                        evidence_ref=edge.evidence_ref,
                    ),
                )
            )
        if (node.open_question or "").strip():
            # M4(설계감사 2026-06-25): 노드가 여는 질문을 (e)-[:RAISES_QUESTION]->(q) 로 *실체화*한다.
            # 전엔 e.open_question 스칼라만 SET 하고 엣지를 안 써서 opened/n_opened 가 항상 0(problem_balance 붕괴).
            ops.append(
                (
                    """MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                       MERGE (q:OpenQuestion {name:$qname, tree:$tree})
                         ON CREATE SET q.status='OPEN', q.created_at=$ts
                       MERGE (e)-[:RAISES_QUESTION]->(q)
                       MERGE (t)-[:HAS_FRONTIER]->(q)""",
                    dict(tree=tree, tag=node.tag, qname=node.open_question.strip(), ts=_utc_now()),
                )
            )
        # The first MATCH is the transaction-local existence barrier.  The
        # adapter must inspect it *inside* execute_write: checking only after
        # commit would let a concurrently-created tree become visible to later
        # statements and receive partial node/edge side effects.
        try:
            results = self.kg_tx(GuardedKgOps(
                ops, guard_field="guard_status", guard_expected="ok"
            ))
        except KgTxGuardFailed as exc:
            if "claim_conflict" in str(exc):
                raise CycleClaimLost(
                    f"active cycle claim already owns {tree}/{node.tag}"
                ) from exc
            raise TreeNotFound(tree) from exc
        if not results or not results[0]:   # MATCH 0행 = 나무 미존재 → 침묵 no-op 금지(fail-loud)
            raise TreeNotFound(tree)
        created = results[0][0].get("cycle_created") is True
        return WriteSummary(tx_count=1, op_count=len(ops), rows=1), created

    def delete_tree(
        self,
        tree: str,
        *,
        cascade: bool = True,
        idempotency_key: str,
        require_empty: bool = False,
        require_incarnation_match: bool = False,
        expected_incarnation_id: str | None = None,
    ) -> dict:
        """Authorize and delete from one managed transaction under ``t→e→q`` locks.

        The returned outbox intent is committed with the graph deletion, so a
        later PostgreSQL/pool failure cannot turn a committed delete into a
        misleading 5xx with no recovery record.
        """
        if not (
            isinstance(idempotency_key, str)
            and 1 <= len(idempotency_key) <= 256
            and idempotency_key.isascii()
            and idempotency_key.isprintable()
        ):
            raise ValueError(
                "tree delete idempotency key must be 1..256 printable ASCII characters"
            )
        operation_json = canonical_history_payload(
            {
                "schema": "lakatotree-tree-delete-operation/v1",
                "domain": "lakatos-tree",
                "op": "tree_delete",
                "tree": tree,
                "idempotency_key": idempotency_key,
            },
        )
        operation_sha256 = hashlib.sha256(
            operation_json.encode("utf-8")
        ).hexdigest()
        idempotency_key_sha256 = hashlib.sha256(
            b"lakatotree-idempotency-key\x00v1\n"
            + idempotency_key.encode("ascii")
        ).hexdigest()
        event_id = f"ob-tree-delete-{operation_sha256}"
        event_ts = _utc_now()
        payload = {
            "cascade": bool(cascade),
            "require_empty": bool(require_empty),
        }
        payload_json = validate_history_record(
            tree, "tree_delete", None, payload, event_id,
        )
        request_json = canonical_history_payload(
            {
                "schema": "lakatotree-tree-delete-request/v1",
                "tree": tree,
                "cascade": bool(cascade),
                "require_empty": bool(require_empty),
                "require_incarnation_match": bool(require_incarnation_match),
                "expected_incarnation_id": expected_incarnation_id,
            },
        )
        request_sha256 = hashlib.sha256(
            request_json.encode("utf-8")
        ).hexdigest()
        incarnation_id = uuid4().hex
        try:
            results = self.kg_tx(GuardedKgOps([
                (
                """OPTIONAL MATCH (t:LakatosTree {name:$tree})
                   FOREACH (_ IN CASE WHEN t IS NULL THEN [] ELSE [1] END |
                     SET t._tree_write_cas=coalesce(t._tree_write_cas,0)+0)
                   WITH t
                   OPTIONAL MATCH (prior:OutboxEntry {id:$event_id})
                   WITH t, [o IN collect(prior) WHERE o IS NOT NULL] AS priors
                   WITH t, priors,
                     CASE
                       WHEN size(priors)>1 THEN 'intent_conflict'
                       WHEN size(priors)=1 AND coalesce(
                         priors[0].tree=$tree AND priors[0].op='tree_delete'
                         AND priors[0].node_tag IS NULL
                         AND priors[0].payload=$payload
                         AND priors[0].request_sha256=$request_sha256
                         AND priors[0].idempotency_key_sha256=
                             $idempotency_key_sha256
                         AND priors[0].tree_incarnation_id IS NOT NULL
                         AND priors[0].reason='tree_delete_commit_intent'
                         AND priors[0].created_at IS NOT NULL
                         AND priors[0].deleted_nodes IS NOT NULL
                         AND priors[0].deleted_nodes >= 0
                         AND ((priors[0].status='pending'
                               AND priors[0].applied_at IS NULL)
                              OR (priors[0].status='applied'
                                  AND priors[0].applied_at IS NOT NULL)),
                         false)
                         AND (t IS NULL OR t.tree_incarnation_id <>
                              priors[0].tree_incarnation_id)
                         THEN 'already_committed'
                       WHEN size(priors)=1 THEN 'intent_conflict'
                       WHEN t IS NULL THEN 'not_found'
                       WHEN $require_incarnation_match AND NOT (
                         ($expected_incarnation_id IS NULL
                          AND t.tree_incarnation_id IS NULL)
                         OR t.tree_incarnation_id=$expected_incarnation_id)
                         THEN 'incarnation_conflict'
                       ELSE 'proceed'
                     END AS guard_status
                   FOREACH (_ IN CASE WHEN guard_status='proceed' THEN [1] ELSE [] END |
                     SET t.tree_incarnation_id=coalesce(
                           t.tree_incarnation_id,$incarnation_id))
                   RETURN t.name AS tree, guard_status,
                          CASE WHEN size(priors)=1 THEN priors[0].id ELSE null END
                            AS prior_event_id,
                          CASE WHEN size(priors)=1 THEN priors[0].deleted_nodes ELSE null END
                            AS prior_deleted_nodes,
                          CASE WHEN size(priors)=1 THEN priors[0].created_at ELSE null END
                            AS prior_event_ts,
                          CASE WHEN size(priors)=1 AND t IS NOT NULL
                               THEN t.tree_incarnation_id <>
                                    priors[0].tree_incarnation_id
                               ELSE false END AS prior_superseded""",
                dict(
                    tree=tree,
                    event_id=event_id,
                    payload=payload_json,
                    request_sha256=request_sha256,
                    idempotency_key_sha256=idempotency_key_sha256,
                    incarnation_id=incarnation_id,
                    require_incarnation_match=bool(require_incarnation_match),
                    expected_incarnation_id=expected_incarnation_id,
                ),
                ),
                (
                """MATCH (:LakatosTree {name:$tree})-[:HAS_NODE]->(e)
                   WHERE NOT EXISTS { MATCH (:OutboxEntry {id:$event_id}) }
                   WITH e ORDER BY e.name
                   SET e._tree_write_cas=coalesce(e._tree_write_cas,0)+0
                   RETURN count(e) AS nodes_locked""",
                dict(tree=tree, event_id=event_id),
                ),
                (
                """MATCH (:LakatosTree {name:$tree})-[:HAS_FRONTIER]->(q)
                   WHERE NOT EXISTS { MATCH (:OutboxEntry {id:$event_id}) }
                   WITH q ORDER BY q.tree, q.name
                   SET q._tree_write_cas=coalesce(q._tree_write_cas,0)+0
                   RETURN count(q) AS questions_locked""",
                dict(tree=tree, event_id=event_id),
                ),
                (
                """MATCH (t:LakatosTree {name:$tree})
                   WHERE NOT EXISTS { MATCH (:OutboxEntry {id:$event_id}) }
                   OPTIONAL MATCH (t)-[:HAS_NODE]->(e)
                   WITH t, [n IN collect(DISTINCT e) WHERE n IS NOT NULL] AS nodes
                   OPTIONAL MATCH (t)-[:HAS_FRONTIER]->(q)
                   WITH t, nodes,
                        [n IN collect(DISTINCT q) WHERE n IS NOT NULL] AS questions
                   OPTIONAL MATCH (r:VerdictReceipt {tree:$tree})
                   WITH t, nodes, questions, count(DISTINCT r) AS tree_receipts
                   OPTIONAL MATCH (linked_node)-[:HAS_RECEIPT]->(linked_receipt:VerdictReceipt)
                     WHERE linked_node IN nodes
                   WITH t, nodes, questions, tree_receipts,
                        count(DISTINCT linked_receipt) AS linked_receipts
                   OPTIONAL MATCH (a:Argument)
                     WHERE a.tree_name=$tree OR a.id STARTS WITH $tree+'/'
                   WITH t, nodes, questions, tree_receipts, linked_receipts,
                        count(DISTINCT a) AS argument_history
                   OPTIONAL MATCH (o:OutboxEntry {tree:$tree, op:'critique'})
                   WITH t, nodes, questions, tree_receipts, linked_receipts,
                        argument_history,
                        count(DISTINCT o) AS critique_history
                   OPTIONAL MATCH (other_tree:LakatosTree)-[:HAS_NODE]->(shared_node)
                     WHERE shared_node IN nodes AND other_tree <> t
                   WITH t, nodes, questions, tree_receipts, linked_receipts,
                        argument_history,
                        critique_history, count(DISTINCT other_tree) AS foreign_node_owners
                   OPTIONAL MATCH (other_frontier:LakatosTree)-[:HAS_FRONTIER]->(shared_question)
                     WHERE shared_question IN questions AND other_frontier <> t
                   WITH t, nodes, questions, tree_receipts, linked_receipts,
                        argument_history,
                        critique_history, foreign_node_owners,
                        count(DISTINCT other_frontier) AS foreign_question_owners,
                        size([n IN nodes WHERE n.verdict_source IN $forceful
                             OR n.current_receipt_sha IS NOT NULL
                             OR n.pred_receipt_sha IS NOT NULL]) AS receipt_pointers,
                        size([n IN nodes WHERE n IN questions]) AS scope_overlap
                   OPTIONAL MATCH (owned_node)-[node_boundary]-(node_external)
                     WHERE owned_node IN nodes
                       AND node_external <> t
                       AND NOT node_external IN nodes
                       AND NOT node_external IN questions
                   WITH t, nodes, questions, tree_receipts, linked_receipts,
                        argument_history, critique_history, foreign_node_owners,
                        foreign_question_owners, receipt_pointers, scope_overlap,
                        count(DISTINCT node_boundary) AS node_boundaries
                   OPTIONAL MATCH (owned_question)-[question_boundary]-(question_external)
                     WHERE owned_question IN questions
                       AND question_external <> t
                       AND NOT question_external IN nodes
                       AND NOT question_external IN questions
                   WITH t, nodes, questions, tree_receipts, linked_receipts,
                        argument_history, critique_history, foreign_node_owners,
                        foreign_question_owners, receipt_pointers, scope_overlap,
                        node_boundaries,
                        count(DISTINCT question_boundary) AS question_boundaries
                   OPTIONAL MATCH (t)-[tree_boundary]-(tree_external)
                     WHERE NOT tree_external IN nodes
                       AND NOT tree_external IN questions
                   WITH t, nodes, questions,
                        tree_receipts, linked_receipts, argument_history,
                        critique_history, foreign_node_owners,
                        foreign_question_owners, receipt_pointers, scope_overlap,
                        node_boundaries, question_boundaries,
                        count(DISTINCT tree_boundary) AS tree_boundaries
                   WITH t, nodes, questions,
                        tree_receipts, linked_receipts, argument_history,
                        critique_history, foreign_node_owners,
                        foreign_question_owners, receipt_pointers, scope_overlap,
                        node_boundaries, question_boundaries, tree_boundaries,
                        CASE
                          WHEN size(nodes) > 0
                            AND ($require_empty OR NOT $cascade) THEN 'nonempty'
                          WHEN tree_receipts > 0 OR linked_receipts > 0
                            OR receipt_pointers > 0
                            THEN 'receipt'
                          WHEN argument_history > 0 OR critique_history > 0
                            THEN 'history'
                          WHEN foreign_node_owners > 0 OR foreign_question_owners > 0
                            OR scope_overlap > 0 OR node_boundaries > 0
                            OR question_boundaries > 0 OR tree_boundaries > 0
                            THEN 'scope_conflict'
                          ELSE 'deleted'
                        END AS state
                   FOREACH (_ IN CASE WHEN state='deleted' THEN [1] ELSE [] END |
                     CREATE (:OutboxEntry {
                       id:$event_id, tree:$tree, op:'tree_delete', node_tag:null,
                       payload:$payload, status:'pending', created_at:$ts,
                       reason:'tree_delete_commit_intent',
                       request_sha256:$request_sha256,
                       idempotency_key_sha256:$idempotency_key_sha256,
                       tree_incarnation_id:t.tree_incarnation_id,
                       deleted_nodes:size(nodes)
                     }))
                   FOREACH (n IN CASE WHEN state='deleted' THEN nodes ELSE [] END |
                     DETACH DELETE n)
                   FOREACH (n IN CASE WHEN state='deleted' THEN questions ELSE [] END |
                     DETACH DELETE n)
                   FOREACH (_ IN CASE WHEN state='deleted' THEN [1] ELSE [] END |
                     DETACH DELETE t)
                   RETURN state, size(nodes) AS node_count""",
                dict(
                    tree=tree,
                    cascade=bool(cascade),
                    require_empty=bool(require_empty),
                    forceful=_FORCEFUL,
                    event_id=event_id,
                    payload=payload_json,
                    ts=event_ts,
                    request_sha256=request_sha256,
                    idempotency_key_sha256=idempotency_key_sha256,
                ),
                ),
            ], guard_field="guard_status",
                guard_expected={"proceed", "already_committed"}))
        except KgTxGuardFailed as exc:
            if "intent_conflict" in str(exc):
                raise TreeIdempotencyConflict(
                    f"tree delete durable intent conflict: {event_id}"
                ) from exc
            if "incarnation_conflict" in str(exc):
                raise TreeIncarnationConflict(
                    f"tree incarnation changed before delete: {tree}"
                ) from exc
            raise TreeNotFound(tree) from exc
        if not results or not results[0]:
            raise TreeNotFound(tree)
        first = results[0][0]
        if first.get("guard_status") == "already_committed":
            node_count = int(first.get("prior_deleted_nodes", 0) or 0)
            return {
                "summary": WriteSummary(
                    tx_count=1, op_count=4, rows=node_count + 1
                ),
                "deleted_nodes": node_count,
                "event_id": event_id,
                "event_ts": first.get("prior_event_ts"),
                "payload": payload,
                "idempotent": True,
                "superseded": first.get("prior_superseded") is True,
            }
        report = (results[3][0] if len(results) > 3 and results[3] else {})
        state = report.get("state")
        node_count = int(report.get("node_count", 0) or 0)
        if state == "nonempty":
            raise TreeNotEmpty(node_count)
        if state == "receipt":
            raise TreeReceiptProtected(tree)
        if state == "history":
            raise TreeHistoryProtected(tree)
        if state == "scope_conflict":
            raise TreeScopeConflict(tree)
        if state != "deleted":
            raise RuntimeError(f"tree delete returned unknown state: {state!r}")
        return {
            "summary": WriteSummary(tx_count=1, op_count=4, rows=node_count + 1),
            "deleted_nodes": node_count,
            "event_id": event_id,
            "event_ts": event_ts,
            "payload": payload,
            "idempotent": False,
            "superseded": False,
        }

    def rollback_cycle_node(self, tree: str, tag: str, claim: str) -> str:
        """Delete only an owned pre-receipt node, or preserve history and release."""

        results = self.kg_tx([
            (
                """MATCH (t:LakatosTree {name:$tree})
                   SET t._tree_write_cas=coalesce(t._tree_write_cas,0)+0
                   WITH t
                   MATCH (t)-[:HAS_NODE]->(e {tag:$tag})
                   WHERE e._cycle_created_by=$claim
                   SET e._tree_write_cas=coalesce(e._tree_write_cas,0)+0
                   RETURN e.name AS node""",
                dict(tree=tree, tag=tag, claim=claim),
            ),
            (
                """MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                   WHERE e._cycle_created_by=$claim
                   OPTIONAL MATCH (e)-[:HAS_RECEIPT]->(r:VerdictReceipt)
                   WITH t, e, count(DISTINCT r) AS receipts
                   OPTIONAL MATCH (e)-[:HAS_ARGUMENT]->(a:Argument)
                   WITH t, e, receipts, count(DISTINCT a) AS arguments
                   OPTIONAL MATCH (o:OutboxEntry {tree:$tree, node_tag:$tag})
                   WITH t, e, receipts, arguments, count(DISTINCT o) AS outbox,
                        e.verdict_source IS NOT NULL
                          OR e.current_receipt_sha IS NOT NULL AS has_pointer
                   OPTIONAL MATCH (foreign_owner)-[incoming]->(e)
                     WHERE NOT (foreign_owner=t AND type(incoming)='HAS_NODE')
                   WITH e, receipts, arguments, outbox, has_pointer,
                        count(DISTINCT incoming) AS foreign_incoming
                   OPTIONAL MATCH (e)-[unexpected_outgoing]->()
                     WHERE NOT type(unexpected_outgoing) IN ['BRANCHED_FROM']
                   WITH e, receipts, arguments, outbox, has_pointer, foreign_incoming,
                        count(DISTINCT unexpected_outgoing) AS foreign_outgoing
                   WITH e, receipts > 0 OR arguments > 0 OR outbox > 0
                          OR has_pointer OR e.pred_registered_at IS NOT NULL
                          OR e.pred_receipt_sha IS NOT NULL
                          OR foreign_incoming > 0 OR foreign_outgoing > 0 AS protected
                   FOREACH (_ IN CASE WHEN protected THEN [1] ELSE [] END |
                     REMOVE e._cycle_created_by, e._cycle_claimed_at)
                   FOREACH (_ IN CASE WHEN protected THEN [] ELSE [1] END |
                     DETACH DELETE e)
                   RETURN CASE WHEN protected THEN 'preserved' ELSE 'deleted' END AS state""",
                dict(tree=tree, tag=tag, claim=claim),
            ),
        ])
        if not results or not results[0]:
            return "not_owned"
        report = results[1][0] if len(results) > 1 and results[1] else {}
        state = report.get("state")
        if state not in {"deleted", "preserved"}:
            return "not_owned"
        return state

    def release_cycle_node(self, tree: str, tag: str, claim: str) -> None:
        rows = self.kg_tx([(
            """MATCH (t:LakatosTree {name:$tree})
               SET t._tree_write_cas=coalesce(t._tree_write_cas,0)+0
               WITH t
               MATCH (t)-[:HAS_NODE]->(e {tag:$tag})
               WHERE e._cycle_created_by=$claim
               REMOVE e._cycle_created_by, e._cycle_claimed_at
               RETURN e.name AS node""",
            dict(tree=tree, tag=tag, claim=claim),
        )])
        # A concurrent writer may already have cleared the non-exclusive marker.
        # That is safe: it can only reduce this invocation's delete authority.

    def upsert_tree_meta(
        self,
        *,
        name: str,
        title: str = "",
        hard_core: str = "",
        frontier_rule: str = "",
        doc: str = "",
        coverage_backlog: Sequence[str] = (),
        coverage_statement: str = "",
        coverage_status: str = "unknown",
        ontology: str = "",
        require_novel_anchor: bool = False,
        require_certified_evidence: bool = False,
        assurance_tier: str | None = None,
        attestor_dids: Sequence[str] | None = None,
        research_layout: str | None = None,
        layout_owner_did: str | None = None,
        layout_sig: str | None = None,
        witness_dids: Sequence[str] | None = None,
        witness_threshold: int | None = None,
        cycle_budget: int | None = None,
        create_only: bool = False,
    ) -> WriteSummary:
        # G6: 신규 트리는 ON CREATE 로만 tier 스탬프(기본 anchored — git default-OFF 반전). 기존 트리는
        #   tier 미선언 upsert 에 절대 안 덮인다(T2 write-clobber 교정: TreeSpec 기본값 flip 이 아니라
        #   ON CREATE SET). 선언 시엔 DB-side 단조 ratchet CASE(랭크 정본=assurance.TIER_RANK 생성물)가
        #   원자 판정 — 상향만 관철, 하향은 기존값 유지 → RETURN 불일치로 TierDowngrade(→409).
        # G10: attestor_dids(서명자 allow-list=키 실물)도 tier 와 같은 非클로버 규율 — None(미선언)은
        #   기존값 불변, 선언 시에만 교체(revocation 은 정당한 운영이라 ratchet 아님·명시 교체).
        # create_only 는 별도 존재조회가 아니라 MERGE 의 ON CREATE 표식을 같은 DB transaction 에서
        # 판정한다. REQUIRED_CONSTRAINTS 의 lkt_tree_name_unique 가 경합 직렬화의 전제다. loser 는
        # conditional FOREACH 를 건너뛰므로 기존 metadata 를 한 필드도 건드리지 않는다. 임시 표식은
        # commit 전에 제거되어 저장 모델에는 노출되지 않는다.
        create_claim = uuid4().hex
        results = self.kg_tx([
            (
                """MERGE (t:LakatosTree {name:$tree})
                     ON CREATE SET t.assurance_tier = coalesce($declared_tier, $default_tier),
                                   t._create_claim = $create_claim
                   WITH t, coalesce(t._create_claim = $create_claim, false) AS created
                   FOREACH (_ IN CASE WHEN $create_only AND NOT created THEN [] ELSE [1] END |
                     SET t.title=$title, t.hard_core=$hard_core, t.frontier_rule=$frontier_rule,
                         t.doc=$doc, t.coverage_backlog=$coverage_backlog,
                         t.coverage_statement=$coverage_statement,
                         t.coverage_status=$coverage_status, t.ontology=$ontology,
                         t.require_novel_anchor=$require_novel_anchor,
                         t.require_certified_evidence=$require_certified_evidence, t.updated_at=$ts
                     SET t.assurance_tier = CASE
                           WHEN $declared_tier IS NULL THEN t.assurance_tier
                           WHEN $declared_rank >= """ + _TIER_RANK_CASE + """ THEN $declared_tier
                           ELSE t.assurance_tier END
                     SET t.attestor_dids = CASE
                           WHEN $attestor_dids IS NULL THEN t.attestor_dids
                           ELSE $attestor_dids END
                     SET t.research_layout = CASE
                           WHEN $research_layout IS NULL THEN t.research_layout
                           ELSE $research_layout END,
                         t.layout_owner_did = CASE
                           WHEN $layout_owner_did IS NULL THEN t.layout_owner_did
                           ELSE $layout_owner_did END,
                         t.layout_sig = CASE
                           WHEN $layout_sig IS NULL THEN t.layout_sig
                           ELSE $layout_sig END,
                         t.witness_dids = CASE
                           WHEN $witness_dids IS NULL THEN t.witness_dids
                           ELSE $witness_dids END,
                         t.witness_threshold = CASE
                           WHEN $witness_threshold IS NULL THEN t.witness_threshold
                           ELSE $witness_threshold END
                     SET t.cycle_budget = CASE
                           WHEN $cycle_budget IS NULL THEN t.cycle_budget
                           ELSE $cycle_budget END)
                   FOREACH (_ IN CASE WHEN created THEN [1] ELSE [] END |
                     REMOVE t._create_claim)
                   RETURN t.assurance_tier AS assurance_tier, created AS created""",
                dict(
                    tree=name,
                    title=title,
                    hard_core=hard_core,
                    frontier_rule=frontier_rule,
                    doc=doc,
                    coverage_backlog=list(coverage_backlog),
                    coverage_statement=coverage_statement,
                    coverage_status=coverage_status,
                    ontology=ontology,
                    require_novel_anchor=require_novel_anchor,
                    require_certified_evidence=require_certified_evidence,
                    declared_tier=assurance_tier,
                    declared_rank=assurance.tier_rank(assurance_tier),
                    default_tier=assurance.DEFAULT_NEW_TREE_TIER,
                    attestor_dids=(None if attestor_dids is None else list(attestor_dids)),
                    research_layout=research_layout,
                    layout_owner_did=layout_owner_did,
                    layout_sig=layout_sig,
                    witness_dids=(None if witness_dids is None else list(witness_dids)),
                    witness_threshold=witness_threshold,
                    create_only=create_only,
                    create_claim=create_claim,
                    # PROM16: 예산도 tier/attestor 와 같은 非클로버 규율 — None(미선언)=기존값 불변
                    #   (예산 없는 upsert 가 선언된 상한을 조용히 지우면 루프 상한이 무력화된다).
                    #   ★단 非클로버는 거기까지다 — tier 와 달리 단조 ratchet 이 *없다*(위 CASE 는 상향만
                    #   관철하지만 이 CASE 는 선언값을 그대로 쓴다 = plain last-write-wins). 그래서 소진된
                    #   에이전트가 같은 트리에 더 큰 cycle_budget 을 선언해 자기 천장을 올릴 수 있다
                    #   (알려진 구멍, 협조 전제): ratchet 은 운영자↔에이전트 authn 구분이 전제인데 현
                    #   표면엔 없어 설계 결정으로 남김. 잔여 비대칭 전체 = cycle_budget.py 모듈 docstring.
                    cycle_budget=cycle_budget,
                    ts=_utc_now(),
                ),
            )
        ])
        report = (results[0][0] or {}) if results and results[0] else {}
        if create_only and report.get("created") is not True:
            raise TreeAlreadyExists(name)
        if assurance_tier is not None:
            got = report.get("assurance_tier")
            if got != assurance_tier:   # ratchet 이 하향 선언을 거부하고 기존 tier 를 유지함
                raise TierDowngrade(
                    f"assurance_tier 다운그레이드 거부: 현재 '{got}' → 선언 '{assurance_tier}' (단조 ratchet)")
        return WriteSummary(tx_count=1, op_count=1, rows=1)

    def upsert_nodes(self, tree: str, nodes: Sequence[NodeIn]) -> WriteSummary:
        nodes = list(nodes)
        _reject_scored(nodes)   # prom-honesty/1: bulk 경로 by-construction 백스톱
        total = WriteSummary()
        ts = _utc_now()
        for chunk in _chunks(list(nodes), self.chunk_size):
            rows = [_node_row(node, ts) for node in chunk]
            self.kg_tx([
                (
                    """MATCH (t:LakatosTree {name:$tree})
                       SET t._tree_write_cas=coalesce(t._tree_write_cas,0)+0
                       WITH t
                       UNWIND $rows AS row
                       MERGE (e:LakatosNode:PrismExperiment {name:$tree+'/'+row.tag})
                       WITH t, row, e
                       OPTIONAL MATCH (e)-[:HAS_RECEIPT]->(authority_receipt:VerdictReceipt)
                       WITH t, row, e,
                            count(authority_receipt) > 0 AS has_any_receipt,
                            count(CASE
                              WHEN coalesce(authority_receipt.receipt_kind,'verdict')
                                     <> 'prediction'
                              THEN authority_receipt
                            END) > 0 AS has_measured_receipt
                       WITH t, row, e, has_any_receipt,
                            (""" + _PRESERVE_NODE_AUTHORITY + """)
                              AS preserve_node_authority,
                            (""" + _PRESERVE_MEASURED_AUTHORITY + """)
                              AS preserve_measured_authority
                       SET e.tag=row.tag, e.script=row.script,
                           e._cycle_created_by=null, e._cycle_claimed_at=null,
                           e.algorithm=row.algorithm,
                           e.comment=row.comment, e.limitation=row.limitation,
                           e.open_question=row.open_question, e.recorded_at=row.ts,
                           e.author=row.author
                       SET """ + _PRESERVE_RESULT_PATH_IF_MEASURED.format(
                               preserve="preserve_measured_authority",
                               rp="row.result_path") + """,
                           """ + _PRESERVE_IF_SCORED.format(
                               preserve=_PRESERVE_NODE_AUTHORITY,
                               v="row.verdict", ns="$node_state",
                               mn="row.metric_name", mv="row.metric_value", ms="row.metric_scope") + """
                       MERGE (t)-[:HAS_NODE]->(e)""",
                    dict(tree=tree, rows=rows, node_state=NodeState.DRAFT.value, forceful=_FORCEFUL),
                )
            ])
            total = total.plus(WriteSummary(tx_count=1, op_count=1, rows=len(rows)))
        return total

    def upsert_tree_bundle(
        self,
        *,
        name: str,
        metadata: Mapping[str, object],
        nodes: Sequence[NodeIn],
        parent_edges_by_tag: Mapping[str, Sequence[ParentEdgeIn]],
        questions: Sequence[QuestionIn],
        create_only: bool = False,
        history_payload: Mapping[str, object] | None = None,
        idempotency_key: str | None = None,
        budget_raise_confirmed: bool = False,
        budget_write_cert_verified: bool = False,
        budget_attestors_snapshot: Sequence[str] | None = None,
    ) -> DurableTreeBundleWrite:
        """Apply a complete tree materialization as one guarded transaction.

        Chunking controls statement size only; it must never become a commit
        boundary.  The first statement creates/locks the tree, rejects
        create-only, tier, and active-cycle conflicts inside the managed
        callback, and every remaining phase runs while that lock is held.
        """

        nodes = list(nodes)
        questions = list(questions)
        edge_count = sum(len(edges) for edges in parent_edges_by_tag.values())
        _reject_scored(nodes)
        collected: list[tuple[str, dict]] = []

        def collect(ops):
            batch = list(ops)
            collected.extend(batch)
            fake_tier = metadata.get("assurance_tier")
            if fake_tier is None:
                fake_tier = assurance.DEFAULT_NEW_TREE_TIER
            return [[{
                "assurance_tier": fake_tier,
                "created": True,
                "guard_status": "ok",
            }] for _ in batch]

        staged = TreeKgWriter(collect, chunk_size=self.chunk_size)
        staged.upsert_tree_meta(
            name=name,
            create_only=False,
            **dict(metadata),
        )
        staged.upsert_nodes(name, nodes)
        staged.link_branch_edges(name, parent_edges_by_tag)
        staged.upsert_questions(name, questions)

        request_document = {
            "tree": name,
            "metadata": _history_request_value(dict(metadata)),
            "nodes": [node.model_dump() for node in nodes],
            "parent_edges_by_tag": {
                tag: [edge.model_dump() for edge in edges]
                for tag, edges in sorted(parent_edges_by_tag.items())
            },
            "questions": [question.model_dump() for question in questions],
            "create_only": bool(create_only),
        }
        request_json = canonical_history_payload(request_document)
        request_sha256 = hashlib.sha256(request_json.encode("utf-8")).hexdigest()
        if idempotency_key is not None:
            if not (
                isinstance(idempotency_key, str)
                and 1 <= len(idempotency_key) <= 256
                and idempotency_key.isascii()
                and idempotency_key.isprintable()
            ):
                raise ValueError(
                    "tree upsert idempotency key must be 1..256 printable ASCII characters"
                )
            operation_document = {
                "schema": "lakatotree-tree-upsert-operation/v1",
                "op": "tree_upsert",
                "tree": name,
                "idempotency_key": idempotency_key,
            }
            operation_json = canonical_history_payload(
                operation_document,
            )
            operation_sha256 = hashlib.sha256(
                operation_json.encode("utf-8")
            ).hexdigest()
            idempotency_key_sha256: str | None = operation_sha256
        else:
            # No-key clients retain ordinary last-write-wins semantics.  This
            # UUID is created outside the managed callback, so a Neo4j driver
            # callback retry still reuses one durable operation identity.
            operation_sha256 = uuid4().hex + uuid4().hex
            idempotency_key_sha256 = None
        event_id = f"ob-tree-upsert-{operation_sha256}"
        event_ts = _utc_now()
        payload = _tree_upsert_history_payload(dict(history_payload or {
            "nodes": len(nodes),
            "questions": len(questions),
            "tx_count": 1,
            "policy_warnings": [],
        }))
        payload_json = validate_history_record(
            name, "tree_upsert", None, payload, event_id,
        )
        bundle_claim = uuid4().hex
        incarnation_id = uuid4().hex
        declared_tier = metadata.get("assurance_tier")
        guard_op = (
            """MERGE (t:LakatosTree {name:$tree})
                 ON CREATE SET
                   t.assurance_tier=coalesce($declared_tier,$default_tier),
                   t._bundle_create_claim=$bundle_claim,
                   t.tree_incarnation_id=$incarnation_id
               SET t.tree_incarnation_id=coalesce(
                     t.tree_incarnation_id,$incarnation_id),
                   t._tree_write_cas=coalesce(t._tree_write_cas,0)+0
               WITH t,
                    coalesce(t._bundle_create_claim=$bundle_claim,false) AS created
               OPTIONAL MATCH (t)-[:HAS_NODE]->(claimed)
                 WHERE claimed._cycle_created_by IS NOT NULL
               WITH t, created, count(DISTINCT claimed) AS active_claims
               OPTIONAL MATCH (prior:OutboxEntry {id:$event_id})
               WITH t, created, active_claims,
                    [o IN collect(prior) WHERE o IS NOT NULL] AS priors
               RETURN t.assurance_tier AS assurance_tier, created,
                 CASE
                   WHEN size(priors)>1 THEN 'intent_conflict'
                   WHEN size(priors)=1 AND coalesce(
                     priors[0].tree=$tree
                     AND priors[0].op='tree_upsert'
                     AND priors[0].node_tag IS NULL
                     AND priors[0].payload IS NOT NULL
                     AND priors[0].request_sha256=$request_sha256
                     AND coalesce(priors[0].idempotency_key_sha256,'')=
                         coalesce($idempotency_key_sha256,'')
                     AND priors[0].tree_incarnation_id=t.tree_incarnation_id
                     AND priors[0].tree_upsert_generation IS NOT NULL
                     AND priors[0].reason='tree_upsert_commit_intent'
                     AND priors[0].created_at IS NOT NULL
                     AND ((priors[0].status='pending'
                           AND priors[0].applied_at IS NULL)
                          OR (priors[0].status='applied'
                              AND priors[0].applied_at IS NOT NULL)),
                     false) THEN 'already_committed'
                   WHEN size(priors)=1 THEN 'intent_conflict'
                   WHEN t.cycle_budget IS NOT NULL
                     AND NOT (valueType(t.cycle_budget) STARTS WITH 'INTEGER')
                     THEN 'budget_corrupt'
                   WHEN $cycle_budget IS NOT NULL
                     AND t.cycle_budget IS NOT NULL
                     AND $cycle_budget > t.cycle_budget
                     AND NOT $budget_raise_confirmed
                     THEN 'budget_raise'
                   WHEN $cycle_budget IS NOT NULL
                     AND t.cycle_budget IS NOT NULL
                     AND $cycle_budget > t.cycle_budget
                     AND size(coalesce(t.attestor_dids,[])) > 0
                     AND (NOT $budget_write_cert_verified
                          OR coalesce(t.attestor_dids,[]) <>
                             coalesce($budget_attestors_snapshot,[]))
                     THEN 'budget_cert'
                   WHEN $create_only AND NOT created THEN 'already_exists'
                   WHEN $declared_tier IS NOT NULL
                     AND $declared_rank < """ + _TIER_RANK_CASE + """
                     THEN 'tier_downgrade'
                   WHEN active_claims > 0 THEN 'claim_conflict'
                   ELSE 'ok'
                 END AS guard_status,
                 CASE WHEN size(priors)=1
                      THEN priors[0].tree_upsert_generation ELSE null END
                   AS prior_generation,
                 CASE WHEN size(priors)=1
                      THEN priors[0].payload ELSE null END AS prior_payload,
                 CASE WHEN size(priors)=1
                      THEN coalesce(t.last_tree_upsert_event_id,'') <> $event_id
                      ELSE false END AS prior_superseded""",
            dict(
                tree=name,
                declared_tier=declared_tier,
                declared_rank=assurance.tier_rank(declared_tier),
                default_tier=assurance.DEFAULT_NEW_TREE_TIER,
                create_only=bool(create_only),
                bundle_claim=bundle_claim,
                incarnation_id=incarnation_id,
                event_id=event_id,
                payload=payload_json,
                request_sha256=request_sha256,
                idempotency_key_sha256=idempotency_key_sha256,
                cycle_budget=metadata.get("cycle_budget"),
                budget_raise_confirmed=bool(budget_raise_confirmed),
                budget_write_cert_verified=bool(budget_write_cert_verified),
                budget_attestors_snapshot=(
                    None
                    if budget_attestors_snapshot is None
                    else list(budget_attestors_snapshot)
                ),
            ),
        )
        intent_op = (
            """MATCH (t:LakatosTree {name:$tree})
               SET t.tree_upsert_generation=
                     coalesce(t.tree_upsert_generation,0)+1
               CREATE (o:OutboxEntry {
                 id:$event_id, tree:$tree, op:'tree_upsert', node_tag:null,
                 payload:$payload, status:'pending', created_at:$ts,
                 reason:'tree_upsert_commit_intent',
                 request_sha256:$request_sha256,
                 idempotency_key_sha256:$idempotency_key_sha256,
                 tree_incarnation_id:t.tree_incarnation_id,
                 tree_upsert_generation:t.tree_upsert_generation
               })
               RETURN o.id AS event_id,
                      o.tree_upsert_generation AS tree_upsert_generation""",
            {
                "tree": name,
                "event_id": event_id,
                "payload": payload_json,
                "ts": event_ts,
                "request_sha256": request_sha256,
                "idempotency_key_sha256": idempotency_key_sha256,
            },
        )
        cleanup_op = (
            """MATCH (t:LakatosTree {name:$tree})
               SET t.last_tree_upsert_event_id=$event_id
               FOREACH (_ IN CASE WHEN t._bundle_create_claim=$bundle_claim
                                   THEN [1] ELSE [] END |
                 REMOVE t._bundle_create_claim)
               RETURN t.name AS tree""",
            {
                "tree": name,
                "bundle_claim": bundle_claim,
                "event_id": event_id,
            },
        )
        try:
            results = self.kg_tx(GuardedKgOps(
                [guard_op, intent_op, *collected, cleanup_op],
                guard_field="guard_status",
                guard_expected="ok",
            ))
        except KgTxGuardFailed as exc:
            message = str(exc)
            if "already_exists" in message:
                raise TreeAlreadyExists(name) from exc
            if "tier_downgrade" in message:
                raise TierDowngrade(
                    f"assurance_tier 다운그레이드 거부: 선언 '{declared_tier}'"
                ) from exc
            if "budget_corrupt" in message:
                raise TreeBudgetStateCorrupt(
                    f"cycle_budget 저장값이 정수가 아님: {name}"
                ) from exc
            if "budget_raise" in message:
                raise BudgetRaiseConfirmationRequired(name) from exc
            if "budget_cert" in message:
                raise BudgetRaiseCertificateRequired(name) from exc
            if "claim_conflict" in message:
                raise CycleClaimLost(
                    f"active cycle claim conflicts with tree bundle {name}"
                ) from exc
            if "already_committed" in message:
                replay_row = exc.row or {}
                prior_generation = replay_row.get("prior_generation")
                try:
                    prior_payload = _tree_upsert_history_payload(
                        _strict_canonical_json_object(
                            replay_row.get("prior_payload")
                        )
                    )
                except (TypeError, ValueError, json.JSONDecodeError) as payload_exc:
                    raise RuntimeError(
                        f"tree bundle durable payload corrupt: {event_id}"
                    ) from payload_exc
                return DurableTreeBundleWrite(
                    summary=WriteSummary(
                        tx_count=1,
                        op_count=len(collected) + 3,
                        rows=1 + len(nodes) + edge_count + len(questions),
                    ),
                    event_id=event_id,
                    payload=prior_payload,
                    idempotent=True,
                    generation=(
                        int(prior_generation)
                        if type(prior_generation) is int and prior_generation >= 1
                        else None
                    ),
                    superseded=replay_row.get("prior_superseded") is True,
                )
            if "intent_conflict" in message:
                raise TreeIdempotencyConflict(
                    f"tree bundle durable intent conflict: {event_id}"
                ) from exc
            raise TreeNotFound(name) from exc
        if not results or not results[0]:
            raise TreeNotFound(name)
        first = results[0][0]
        if create_only and first.get("created") is not True:
            raise TreeAlreadyExists(name)
        if declared_tier is not None:
            observed_tier = first.get("assurance_tier")
            if (
                isinstance(observed_tier, str)
                and assurance.tier_rank(observed_tier)
                    > assurance.tier_rank(declared_tier)
            ):
                raise TierDowngrade(
                    f"assurance_tier 다운그레이드 거부: 현재 "
                    f"'{observed_tier}' → 선언 '{declared_tier}'"
                )
        if first.get("guard_status") not in (None, "ok"):
            raise RuntimeError(
                f"tree bundle guard returned unexpected state: "
                f"{first.get('guard_status')!r}"
            )
        intent_row = (
            results[1][0]
            if len(results) > 1 and results[1] and isinstance(results[1][0], dict)
            else {}
        )
        generation = intent_row.get("tree_upsert_generation")
        return DurableTreeBundleWrite(
            summary=WriteSummary(
                tx_count=1,
                op_count=len(collected) + 3,
                rows=1 + len(nodes) + edge_count + len(questions),
            ),
            event_id=event_id,
            payload=payload,
            generation=(
                int(generation)
                if type(generation) is int and generation >= 1
                else None
            ),
        )

    def link_branch_edges(
        self,
        tree: str,
        parent_edges_by_tag: Mapping[str, Sequence[ParentEdgeIn]],
    ) -> WriteSummary:
        rows = [
            {
                "tag": tag,
                "parent": edge.tag,
                "inferred": edge.inferred,
                "relation_kind": edge.relation_kind,
                "evidence_ref": edge.evidence_ref,
            }
            for tag, edges in parent_edges_by_tag.items()
            for edge in edges
        ]
        total = WriteSummary()
        for chunk in _chunks(rows, self.chunk_size):
            self.kg_tx([
                (
                    """MATCH (t:LakatosTree {name:$tree})
                       SET t._tree_write_cas=coalesce(t._tree_write_cas,0)+0
                       WITH t
                       UNWIND $rows AS row
                       MATCH (t)-[:HAS_NODE]->(e {tag:row.tag})
                       MATCH (t)-[:HAS_NODE]->(p {tag:row.parent})
                       SET e._cycle_created_by=null, e._cycle_claimed_at=null,
                           p._cycle_created_by=null, p._cycle_claimed_at=null
                       MERGE (e)-[r:BRANCHED_FROM]->(p)
                       SET r.inferred=row.inferred,
                           r.relation_kind=row.relation_kind,
                           r.evidence_ref=row.evidence_ref""",
                    dict(tree=tree, rows=list(chunk)),
                )
            ])
            total = total.plus(WriteSummary(tx_count=1, op_count=1, rows=len(chunk)))
        return total

    def upsert_questions(self, tree: str, questions: Sequence[QuestionIn]) -> WriteSummary:
        total = WriteSummary()
        ts = _utc_now()
        for chunk in _chunks(list(questions), self.chunk_size):
            rows = [_question_row(question, ts) for question in chunk]
            self.kg_tx([
                (
                    """MATCH (t:LakatosTree {name:$tree})
                       SET t._tree_write_cas=coalesce(t._tree_write_cas,0)+0
                       WITH t
                       UNWIND $rows AS row
                       MERGE (qn:OpenQuestion {name:row.qname, tree:$tree})
                       SET qn.body=row.body, qn.status='OPEN', qn.created_at=row.ts,
                           qn.expected_gain=row.expected_gain, qn.cost=row.cost,
                           qn.n_visits=coalesce(qn.n_visits, 0)
                       MERGE (t)-[:HAS_FRONTIER]->(qn)""",
                    dict(tree=tree, rows=rows),
                )
            ])
            total = total.plus(WriteSummary(tx_count=1, op_count=1, rows=len(rows)))
        return total
