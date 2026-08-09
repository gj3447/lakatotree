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
from server.contexts.tree.schemas import (
    NodeIn,
    ParentEdgeIn,
    QuestionIn,
    StructuralBatchIn,
)
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


@dataclass(frozen=True)
class DurableStructuralBatchWrite:
    """One immutable additive structural commit plus its history intents."""

    summary: WriteSummary
    receipt_id: str
    batch_id: str
    manifest_sha256: str
    request_sha256: str
    created_at: str
    prestate: dict
    poststate: dict
    event_intents: tuple[dict, ...]
    idempotent: bool = False


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_structural_utc_timestamp(value: object) -> datetime:
    """Parse the one canonical UTC timestamp form used by batch evidence."""

    if not isinstance(value, str):
        raise ValueError("structural timestamp must be canonical text")
    parsed = datetime.fromisoformat(value)
    if not (
        parsed.tzinfo is not None
        and parsed.utcoffset() == timezone.utc.utcoffset(None)
        and parsed.isoformat() == value
    ):
        raise ValueError("structural timestamp must be canonical UTC text")
    return parsed


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


class StructuralBatchNotFound(Exception):
    """The target tree or immutable structural-batch receipt was not found."""


class StructuralBatchIdempotencyConflict(Exception):
    """A structural batch identity was reused for different canonical bytes."""


class StructuralPrestateMismatch(Exception):
    """The locked tree no longer equals the caller's complete expected state."""


class StructuralConstraintUnavailable(Exception):
    """Required uniqueness/identity constraints are not installed and healthy."""


class StructuralOwnershipConflict(Exception):
    """A create-only identity is already owned or has a divergent definition."""


class StructuralReferenceConflict(Exception):
    """An incoming parent, question, or element-use reference is unresolved."""


class StructuralInvariantFailure(Exception):
    """A durable receipt, result, or postcondition is internally inconsistent."""


def _structural_batch_managed_ops(
    ops: Sequence[tuple[str, dict]],
) -> GuardedKgOps:
    """The deliberately load-bearing single-transaction CAS boundary."""

    return GuardedKgOps(
        ops,
        guard_field="guard_status",
        guard_expected="ok",
    )


def _canonical_json(value: object) -> str:
    """Canonical JSON for immutable structural-batch identities and receipts."""

    return json.dumps(
        _history_request_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def structural_batch_receipt_id(tree: str, batch_id: str) -> str:
    """Content identity used by apply, replay, and the status surface."""

    return "sbr-" + hashlib.sha256(
        _canonical_json([
            "lakatotree-structural-batch-receipt/v1",
            tree,
            batch_id,
        ]).encode("utf-8")
    ).hexdigest()


def structural_batch_request_document(
    tree: str,
    command: StructuralBatchIn,
    idempotency_key: str,
) -> dict:
    """Build the exact durable request whose hash owns the batch receipt."""

    return {
        "schema": "lakatotree-structural-batch-request/v1",
        "tree": tree,
        "idempotency_key": idempotency_key,
        "command": command.model_dump(mode="json"),
    }


def _strict_structural_batch_result(value: object) -> dict:
    """Decode the immutable Neo4j receipt without accepting shape drift."""

    parsed = _strict_canonical_json_object(value)
    expected = {
        "batch_id",
        "event_intents",
        "manifest_sha256",
        "poststate",
        "prestate",
        "created_at",
        "receipt_id",
        "request_sha256",
        "schema_version",
    }
    if set(parsed) != expected:
        raise ValueError("structural batch result has an invalid shape")
    if parsed.get("schema_version") != "lakatotree-structural-batch-result/v1":
        raise ValueError("structural batch result schema is invalid")
    parse_structural_utc_timestamp(parsed.get("created_at"))
    if not (
        isinstance(parsed.get("batch_id"), str)
        and bool(parsed["batch_id"])
        and isinstance(parsed.get("receipt_id"), str)
        and parsed["receipt_id"].startswith("sbr-")
        and _is_lower_hex(parsed["receipt_id"][4:], 64)
        and _is_lower_hex(parsed.get("manifest_sha256"), 64)
        and _is_lower_hex(parsed.get("request_sha256"), 64)
    ):
        raise ValueError("structural batch result identity is invalid")
    for key in ("prestate", "poststate"):
        state = parsed.get(key)
        if not isinstance(state, dict) or set(state) != {
            "authority",
            "counts",
            "state_sha256",
            "structural_revision",
            "tree_incarnation_id",
        }:
            raise ValueError(f"structural batch {key} has an invalid shape")
        counts = state.get("counts")
        if not isinstance(counts, dict) or set(counts) != {
            "elements",
            "element_uses",
            "foundations",
            "nodes",
            "parent_edges",
            "questions",
        }:
            raise ValueError(f"structural batch {key} counts have an invalid shape")
        authority = state.get("authority")
        if not isinstance(authority, dict) or set(authority) != {
            "predictions", "progress_verdicts", "results", "verdict_receipts",
        }:
            raise ValueError(f"structural batch {key} authority has an invalid shape")
        if not (
            isinstance(state.get("tree_incarnation_id"), str)
            and bool(state["tree_incarnation_id"])
            and _is_lower_hex(state.get("state_sha256"), 64)
            and _is_nonnegative_int(state.get("structural_revision"))
            and all(_is_nonnegative_int(item) for item in counts.values())
            and all(_is_nonnegative_int(item) for item in authority.values())
        ):
            raise ValueError(f"structural batch {key} values are invalid")
    events = parsed.get("event_intents")
    if not isinstance(events, list):
        raise ValueError("structural batch result event intents must be a list")
    event_ids: set[str] = set()
    allowed_ops = {
        "element_upsert",
        "element_use",
        "foundation_upsert",
        "node_create",
        "question_open",
    }
    for event in events:
        if not isinstance(event, dict) or set(event) != {
            "event_id", "node_tag", "op", "payload", "tree",
        }:
            raise ValueError("structural batch result event intent has an invalid shape")
        if not (
            isinstance(event.get("event_id"), str)
            and event["event_id"].startswith("ob-structural-")
            and isinstance(event.get("tree"), str)
            and bool(event["tree"])
            and event.get("op") in allowed_ops
            and (
                event.get("node_tag") is None
                if event.get("op") == "question_open"
                else isinstance(event.get("node_tag"), str)
                and bool(event["node_tag"])
            )
            and isinstance(event.get("payload"), dict)
        ):
            raise ValueError("structural batch result event payload must be an object")
        if event["event_id"] in event_ids:
            raise ValueError("structural batch result event ids must be unique")
        event_ids.add(event["event_id"])
        validate_history_record(
            event["tree"],
            event["op"],
            event["node_tag"],
            event["payload"],
            event["event_id"],
        )
    return parsed


def _is_lower_hex(value: object, length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0


def _strict_canonical_json_array(value: object) -> list:
    if not isinstance(value, str):
        raise ValueError("durable array must be canonical JSON text")
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
    if not isinstance(parsed, list) or _canonical_json(parsed) != value:
        raise ValueError("durable array is not canonical JSON")
    return parsed


def _structural_result_from_receipt_row(row: Mapping[str, object]) -> dict:
    """Reconstruct the public result from immutable scalar/JSON receipt fields."""

    prestate = _strict_canonical_json_object(row.get("prestate_json"))
    events = _strict_canonical_json_array(row.get("event_intents_json"))
    poststate = {
        "authority": {
            "predictions": row.get("post_predictions"),
            "progress_verdicts": row.get("post_progress_verdicts"),
            "results": row.get("post_results"),
            "verdict_receipts": row.get("post_verdict_receipts"),
        },
        "counts": {
            "elements": row.get("post_elements"),
            "element_uses": row.get("post_element_uses"),
            "foundations": row.get("post_foundations"),
            "nodes": row.get("post_nodes"),
            "parent_edges": row.get("post_parent_edges"),
            "questions": row.get("post_questions"),
        },
        "state_sha256": row.get("post_state_sha256"),
        "structural_revision": row.get("post_structural_revision"),
        "tree_incarnation_id": row.get("tree_incarnation_id"),
    }
    result = {
        "batch_id": row.get("batch_id"),
        "event_intents": events,
        "manifest_sha256": row.get("manifest_sha256"),
        "poststate": poststate,
        "prestate": prestate,
        "created_at": row.get("created_at"),
        "receipt_id": row.get("receipt_id"),
        "request_sha256": row.get("request_sha256"),
        "schema_version": "lakatotree-structural-batch-result/v1",
    }
    # Round-trip through the strict parser so corrupt or partially populated
    # receipts fail loudly instead of being treated as successful replays.
    return _strict_structural_batch_result(_canonical_json(result))


def _structural_result_matches_expected(
    result: Mapping[str, object],
    *,
    prestate: dict,
    expected_counts: dict,
    expected_authority: dict,
    expected_revision: int,
    expected_incarnation: str,
    expected_events: Sequence[dict],
) -> bool:
    """Bind an immutable receipt to the exact admitted command and event plan."""

    poststate = result.get("poststate")
    return bool(
        result.get("prestate") == prestate
        and isinstance(poststate, dict)
        and poststate.get("counts") == expected_counts
        and poststate.get("authority") == expected_authority
        and poststate.get("structural_revision") == expected_revision
        and poststate.get("tree_incarnation_id") == expected_incarnation
        and result.get("event_intents") == list(expected_events)
    )


def _structural_outbox_timestamps_match(
    rows: object,
    *,
    expected_events: Sequence[dict],
    receipt_created_at: str,
) -> bool:
    """Bind replay evidence to the receipt clock and exact event-id set."""

    parse_structural_utc_timestamp(receipt_created_at)
    if not isinstance(rows, list):
        return False
    expected_ids = [event.get("event_id") for event in expected_events]
    actual_ids: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != {"created_at", "event_id"}:
            return False
        event_id = row.get("event_id")
        created_at = row.get("created_at")
        if not isinstance(event_id, str):
            return False
        try:
            parse_structural_utc_timestamp(created_at)
        except (TypeError, ValueError):
            return False
        if created_at != receipt_created_at:
            return False
        actual_ids.append(event_id)
    return (
        len(actual_ids) == len(set(actual_ids))
        and sorted(actual_ids) == sorted(expected_ids)
    )


def _structural_batch_event_intents(
    tree: str,
    command: StructuralBatchIn,
    request_sha256: str,
) -> tuple[dict, ...]:
    """Build PG-safe, stable event intents before entering the managed tx."""

    raw: list[tuple[str, str | None, dict]] = []
    for question in command.questions:
        payload = question.model_dump(exclude={"state"}, mode="json")
        raw.append(("question_open", None, payload))
    for node in command.nodes:
        payload = node.model_dump(mode="json")
        raw.append(("node_create", node.tag, payload))
    for foundation in command.foundations:
        raw.append(
            (
                "foundation_upsert",
                foundation.name,
                foundation.to_engine().db_record(),
            )
        )
    for element in command.elements:
        raw.append(("element_upsert", element.name, element.model_dump(mode="json")))
    for use in command.element_uses:
        raw.append(
            (
                "element_use",
                use.tag,
                {
                    "element": use.element_name,
                    "note": use.note,
                    "evidence_ref": use.evidence_ref,
                },
            )
        )

    intents: list[dict] = []
    for ordinal, (op, node_tag, payload) in enumerate(raw):
        event_id = (
            f"ob-structural-{request_sha256}-"
            f"{ordinal:04d}-{hashlib.sha256(_canonical_json([op, node_tag, payload]).encode('utf-8')).hexdigest()[:16]}"
        )
        payload_json = validate_history_record(
            tree, op, node_tag, payload, event_id,
        )
        intents.append(
            {
                "event_id": event_id,
                "tree": tree,
                "op": op,
                "node_tag": node_tag,
                "payload": json.loads(payload_json),
                "payload_json": payload_json,
            }
        )
    return tuple(intents)


# This projection is intentionally complete for the additive structural surface.
# Both GET structural-state and the first statement of apply_structural_batch use
# this exact fragment, so the caller's digest cannot be checked against a weaker
# count-only view.  Ordering happens before every collect; apoc.convert.toJson then
# hashes one deterministic JSON projection inside the locked Neo4j transaction.
_STRUCTURAL_STATE_PROJECTION = r"""
CALL (t) {
  WITH t
  OPTIONAL MATCH (t)-[:HAS_NODE]->(n:LakatosNode)
  WITH n ORDER BY n.tag, n.name
  RETURN [x IN collect(CASE WHEN n IS NULL THEN null ELSE {
    algorithm:n.algorithm, author:n.author, comment:n.comment,
    limitation:n.limitation, metric_name:n.metric_name,
    metric_scope:n.metric_scope, metric_value:n.metric_value,
    name:n.name, node_state:n.node_state, open_question:n.open_question,
    result_path:n.result_path, script:n.script, tag:n.tag,
    verdict:n.verdict, verdict_source:n.verdict_source
  } END) WHERE x IS NOT NULL] AS structural_nodes
}
CALL (t) {
  WITH t
  OPTIONAL MATCH (t)-[:HAS_FRONTIER]->(q:OpenQuestion)
  WITH q ORDER BY q.name
  RETURN [x IN collect(CASE WHEN q IS NULL THEN null ELSE {
    body:q.body, cost:q.cost, expected_gain:q.expected_gain,
    name:q.name, state:coalesce(q.status,'OPEN'), tree:q.tree
  } END) WHERE x IS NOT NULL] AS structural_questions
}
CALL (t) {
  WITH t
  OPTIONAL MATCH (t)-[:HAS_NODE]->(child:LakatosNode)
                 -[edge:BRANCHED_FROM]->(parent:LakatosNode)<-[:HAS_NODE]-(t)
  WITH child, edge, parent ORDER BY child.tag, parent.tag,
       edge.relation_kind, edge.evidence_ref
  RETURN [x IN collect(CASE WHEN edge IS NULL THEN null ELSE {
    child:child.tag, evidence_ref:edge.evidence_ref,
    inferred:coalesce(edge.inferred,false), parent:parent.tag,
    relation_kind:edge.relation_kind
  } END) WHERE x IS NOT NULL] AS structural_parent_edges
}
CALL (t) {
  WITH t
  OPTIONAL MATCH (t)-[:HAS_NODE]->(n:LakatosNode)-[:RAISES_QUESTION]->(q:OpenQuestion)
  WITH n, q ORDER BY n.tag, q.name
  RETURN [x IN collect(CASE WHEN q IS NULL THEN null ELSE {
    node:n.tag, question:q.name
  } END) WHERE x IS NOT NULL] AS structural_question_links
}
CALL (t) {
  WITH t
  OPTIONAL MATCH (t)-[:HAS_FOUNDATION]->(f:FoundationRequirement)
  WITH f ORDER BY f.short_name, f.name
  RETURN [x IN collect(CASE WHEN f IS NULL THEN null ELSE {
    acceptance_criteria:f.acceptance_criteria, evidence_refs:f.evidence_refs,
    kind:f.kind, name:f.name, optional:f.optional, owner:f.owner,
    question:f.question, risk_if_missing:f.risk_if_missing,
    satisfied:f.satisfied, short_name:f.short_name, status:f.status,
    why_needed:f.why_needed
  } END) WHERE x IS NOT NULL] AS structural_foundations
}
CALL (t) {
  WITH t
  OPTIONAL MATCH (t)-[:HAS_ELEMENT]->(el:LakatosElement)
  WITH el ORDER BY el.name
  RETURN [x IN collect(CASE WHEN el IS NULL THEN null ELSE {
    definition:el.definition, implication:el.implication,
    lifecycle:el.lifecycle, name:el.name, scope:el.scope
  } END) WHERE x IS NOT NULL] AS structural_elements
}
CALL (t) {
  WITH t
  OPTIONAL MATCH (t)-[:HAS_NODE]->(n:LakatosNode)-[u:USES_ELEMENT]->(el:LakatosElement)<-[:HAS_ELEMENT]-(t)
  WITH n, u, el ORDER BY n.tag, el.name
  RETURN [x IN collect(CASE WHEN u IS NULL THEN null ELSE {
    element:el.name, evidence_ref:u.evidence_ref, node:n.tag, note:u.note
  } END) WHERE x IS NOT NULL] AS structural_element_uses
}
CALL (t) {
  WITH t
  OPTIONAL MATCH (t)-[:HAS_NODE]->(n:LakatosNode)-[:HAS_RECEIPT]->(r:VerdictReceipt)
  RETURN count(DISTINCT r) AS structural_verdict_receipts,
         count(DISTINCT CASE WHEN r.receipt_kind='prediction' THEN r END)
           AS structural_predictions,
         count(DISTINCT CASE WHEN coalesce(r.receipt_kind,'verdict')<>'prediction'
                             THEN r END) AS structural_results
}
CALL (t) {
  WITH t
  OPTIONAL MATCH (t)-[:HAS_NODE]->(n:LakatosNode)
  WHERE coalesce(n.node_state,'DRAFT') <> 'DRAFT'
     OR NOT coalesce(n.verdict,'proof') IN ['', 'proof']
     OR coalesce(n.verdict_source,'') <> ''
  RETURN count(DISTINCT n) AS structural_progress_verdicts
}
WITH t, structural_nodes, structural_questions, structural_parent_edges,
     structural_question_links, structural_foundations, structural_elements,
     structural_element_uses,
     {
       predictions:structural_predictions,
       progress_verdicts:structural_progress_verdicts,
       results:structural_results,
       verdict_receipts:structural_verdict_receipts
     } AS structural_authority,
     {
       elements:size(structural_elements),
       element_uses:size(structural_element_uses),
       foundations:size(structural_foundations),
       nodes:size(structural_nodes),
       parent_edges:size(structural_parent_edges),
       questions:size(structural_questions)
     } AS structural_counts
WITH t, structural_authority, structural_counts,
     structural_nodes, structural_questions, structural_parent_edges,
     structural_question_links, structural_foundations, structural_elements,
     structural_element_uses,
     {
       authority:structural_authority,
       elements:structural_elements,
       element_uses:structural_element_uses,
       foundations:structural_foundations,
       nodes:structural_nodes,
       parent_edges:structural_parent_edges,
       question_links:structural_question_links,
       questions:structural_questions,
       structural_revision:coalesce(t.structural_revision,0),
       tree_incarnation_id:t.tree_incarnation_id
     } AS structural_state
WITH t, structural_authority, structural_counts,
     structural_nodes, structural_questions, structural_elements,
     structural_state, apoc.convert.toJson(structural_state) AS structural_state_json
WITH t, structural_authority, structural_counts,
     structural_nodes, structural_questions, structural_elements,
     structural_state, structural_state_json,
     apoc.util.sha256([structural_state_json]) AS structural_state_sha256
"""


def structural_state_query() -> str:
    """Return the exact projection used by the managed-transaction CAS guard."""

    return (
        "MATCH (t:LakatosTree {name:$tree}) WITH t\n"
        + _STRUCTURAL_STATE_PROJECTION
        + """
RETURN t.name AS tree,
       t.tree_incarnation_id AS tree_incarnation_id,
       coalesce(t.structural_revision,0) AS structural_revision,
       structural_state AS structural_state,
       structural_state_json AS structural_state_json,
       structural_state_sha256 AS state_sha256,
       structural_counts AS counts,
       structural_authority AS authority
"""
    )


def parse_structural_state_row(row: Mapping[str, object]) -> dict:
    """Validate the complete read projection before exposing it as CAS input."""

    state_json = row.get("structural_state_json")
    if not isinstance(state_json, str):
        raise ValueError("structural state JSON is missing")

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate structural state key: {key}")
            result[key] = value
        return result

    parsed = json.loads(state_json, object_pairs_hook=unique_object)
    state = row.get("structural_state")
    if not isinstance(parsed, dict) or not isinstance(state, Mapping):
        raise ValueError("structural state projection must be an object")
    state = dict(state)
    expected_state_keys = {
        "authority",
        "elements",
        "element_uses",
        "foundations",
        "nodes",
        "parent_edges",
        "question_links",
        "questions",
        "structural_revision",
        "tree_incarnation_id",
    }
    list_keys = {
        "elements",
        "element_uses",
        "foundations",
        "nodes",
        "parent_edges",
        "question_links",
        "questions",
    }
    count_keys = {
        "elements",
        "element_uses",
        "foundations",
        "nodes",
        "parent_edges",
        "questions",
    }
    authority_keys = {
        "predictions", "progress_verdicts", "results", "verdict_receipts",
    }
    state_sha256 = row.get("state_sha256")
    counts = row.get("counts")
    authority = row.get("authority")
    if not (
        parsed == state
        and _is_lower_hex(state_sha256, 64)
        and hashlib.sha256(state_json.encode("utf-8")).hexdigest() == state_sha256
        and isinstance(row.get("tree"), str)
        and bool(row["tree"])
        and isinstance(row.get("tree_incarnation_id"), str)
        and bool(row["tree_incarnation_id"])
        and _is_nonnegative_int(row.get("structural_revision"))
        and isinstance(counts, Mapping)
        and isinstance(authority, Mapping)
        and set(state) == expected_state_keys
        and all(isinstance(state.get(key), list) for key in list_keys)
        and set(counts) == count_keys
        and all(_is_nonnegative_int(value) for value in counts.values())
        and set(authority) == authority_keys
        and all(_is_nonnegative_int(value) for value in authority.values())
    ):
        raise ValueError("structural state projection binding is invalid")
    public = {
        "schema": "lakatotree.structural-state.v1",
        "tree": row["tree"],
        "tree_incarnation_id": row["tree_incarnation_id"],
        "structural_revision": row["structural_revision"],
        "state_sha256": state_sha256,
        "counts": dict(counts),
        "authority": dict(authority),
        "structural_state": state,
    }
    if not (
        state.get("tree_incarnation_id") == public["tree_incarnation_id"]
        and state.get("structural_revision") == public["structural_revision"]
        and state.get("authority") == public["authority"]
        and {
            "nodes": len(state["nodes"]),
            "questions": len(state["questions"]),
            "foundations": len(state["foundations"]),
            "elements": len(state["elements"]),
            "element_uses": len(state["element_uses"]),
            "parent_edges": len(state["parent_edges"]),
        } == public["counts"]
    ):
        raise ValueError("structural state projection counts are inconsistent")
    return public


def structural_batch_receipt_query() -> str:
    """Read one immutable receipt by tree and batch identity."""

    return r"""
MATCH (t:LakatosTree {name:$tree})-[:HAS_STRUCTURAL_BATCH_RECEIPT]->
      (receipt:StructuralBatchReceipt {
        id:$receipt_id, tree:$tree, batch_id:$batch_id
      })
RETURN receipt.id AS receipt_id,
       receipt.tree AS receipt_tree,
       receipt.request_json AS request_json,
       receipt.prestate_json AS prestate_json,
       receipt.event_intents_json AS event_intents_json,
       receipt.post_predictions AS post_predictions,
       receipt.post_progress_verdicts AS post_progress_verdicts,
       receipt.post_results AS post_results,
       receipt.post_verdict_receipts AS post_verdict_receipts,
       receipt.post_elements AS post_elements,
       receipt.post_element_uses AS post_element_uses,
       receipt.post_foundations AS post_foundations,
       receipt.post_nodes AS post_nodes,
       receipt.post_parent_edges AS post_parent_edges,
       receipt.post_questions AS post_questions,
       receipt.post_state_sha256 AS post_state_sha256,
       receipt.post_structural_revision AS post_structural_revision,
       receipt.tree_incarnation_id AS tree_incarnation_id,
       receipt.batch_id AS batch_id,
       receipt.manifest_sha256 AS manifest_sha256,
       receipt.receipt_id AS recorded_receipt_id,
       receipt.request_sha256 AS request_sha256,
       receipt.created_at AS created_at
"""


def parse_structural_batch_receipt_row(row: Mapping[str, object]) -> dict:
    """Public strict decoder shared by apply replay and status reads."""

    normalized = dict(row)
    recorded = normalized.pop("recorded_receipt_id", normalized.get("receipt_id"))
    if recorded != normalized.get("receipt_id"):
        raise ValueError("structural batch receipt identity fields diverged")
    return _structural_result_from_receipt_row(normalized)


def validate_structural_batch_receipt_binding(
    *,
    tree: str,
    batch_id: str,
    row: Mapping[str, object],
) -> tuple[dict, StructuralBatchIn]:
    """Bind a status read to its exact canonical request and result receipt."""

    expected_receipt_id = structural_batch_receipt_id(tree, batch_id)
    if not (
        row.get("receipt_id") == expected_receipt_id
        and row.get("recorded_receipt_id") == expected_receipt_id
        and row.get("receipt_tree") == tree
        and row.get("batch_id") == batch_id
    ):
        raise ValueError("structural batch receipt lookup binding is invalid")

    request_json = row.get("request_json")
    request = _strict_canonical_json_object(request_json)
    if set(request) != {"command", "idempotency_key", "schema", "tree"}:
        raise ValueError("structural batch durable request has an invalid shape")
    if not (
        request.get("schema") == "lakatotree-structural-batch-request/v1"
        and request.get("tree") == tree
        and request.get("idempotency_key") == batch_id
        and isinstance(request.get("command"), dict)
        and hashlib.sha256(request_json.encode("utf-8")).hexdigest()
        == row.get("request_sha256")
    ):
        raise ValueError("structural batch durable request binding is invalid")
    command = StructuralBatchIn.model_validate(request["command"])
    if command.batch_id != batch_id:
        raise ValueError("structural batch command identity is invalid")

    result = parse_structural_batch_receipt_row(row)
    expected_events = [
        {key: value for key, value in event.items() if key != "payload_json"}
        for event in _structural_batch_event_intents(
            tree,
            command,
            result["request_sha256"],
        )
    ]
    if not (
        result["receipt_id"] == expected_receipt_id
        and result["batch_id"] == batch_id
        and result["manifest_sha256"] == command.manifest_sha256
        and _structural_result_matches_expected(
            result,
            prestate=command.expected_prestate.model_dump(mode="json"),
            expected_counts=command.expected_post_counts.model_dump(mode="json"),
            expected_authority=command.expected_prestate.authority.model_dump(mode="json"),
            expected_revision=command.expected_prestate.structural_revision + 1,
            expected_incarnation=command.expected_prestate.tree_incarnation_id,
            expected_events=expected_events,
        )
    ):
        raise ValueError("structural batch receipt does not bind its durable request")
    return result, command


def structural_batch_outbox_query() -> str:
    """Read every outbox row owned by one structural-batch receipt."""

    return r"""
MATCH (o:OutboxEntry {tree:$tree, structural_batch_id:$batch_id})
RETURN o.id AS event_id,
       o.tree AS tree,
       o.op AS op,
       o.node_tag AS node_tag,
       o.payload AS payload,
       o.status AS status,
       o.created_at AS created_at,
       o.reason AS reason,
       o.applied_at AS applied_at,
       o.adopted_by AS adopted_by,
       o.adopted_at AS adopted_at,
       o.request_sha256 AS request_sha256,
       o.structural_batch_id AS structural_batch_id
ORDER BY o.id
"""


# G6 단조 ratchet 의 DB-side 랭크 CASE — 서열 정본(assurance.TIER_RANK)에서 생성(표류 불가).
_TIER_RANK_CASE = assurance.cypher_tier_rank_case("t.assurance_tier")


class TreeKgWriter:
    """Owns Cypher write shape for the tree context."""

    # KG: seed-lkt-engine-mutation-writer-20260616

    def __init__(self, kg_tx: KgTx, *, chunk_size: int = 100):
        self.kg_tx = kg_tx
        self.chunk_size = max(1, chunk_size)

    def apply_structural_batch(
        self,
        *,
        name: str,
        command: StructuralBatchIn,
        idempotency_key: str,
        constraints_ready: bool = False,
    ) -> DurableStructuralBatchWrite:
        """Commit one create-only structural delta behind an exact-state CAS.

        The first Cypher statement locks the tree, computes the same complete
        projection exposed by the structural-state read surface, and decides
        replay/conflict/prestate/reference guards.  Every domain write, durable
        history intent, revision increment, postcondition, and receipt then runs
        in the *same* managed Neo4j transaction.  PostgreSQL history is only a
        later projection of the committed outbox intents.
        """

        if not (
            isinstance(idempotency_key, str)
            and 1 <= len(idempotency_key) <= 256
            and idempotency_key.isascii()
            and idempotency_key.isprintable()
        ):
            raise ValueError(
                "structural batch idempotency key must be 1..256 printable ASCII characters"
            )
        if idempotency_key != command.batch_id:
            raise ValueError("structural batch idempotency key must equal batch_id")
        if constraints_ready is not True:
            raise StructuralConstraintUnavailable(name)

        request_document = structural_batch_request_document(
            name,
            command,
            idempotency_key,
        )
        request_json = _canonical_json(request_document)
        request_sha256 = hashlib.sha256(request_json.encode("utf-8")).hexdigest()
        receipt_id = structural_batch_receipt_id(name, command.batch_id)
        ts = _utc_now()

        event_intents = _structural_batch_event_intents(
            name, command, request_sha256,
        )
        public_events = [
            {key: value for key, value in intent.items() if key != "payload_json"}
            for intent in event_intents
        ]
        event_intents_json = _canonical_json(public_events)
        outbox_rows = [
            {
                "event_id": intent["event_id"],
                "tree": intent["tree"],
                "op": intent["op"],
                "node_tag": intent["node_tag"],
                "payload": intent["payload_json"],
            }
            for intent in event_intents
        ]

        prestate = command.expected_prestate.model_dump(mode="json")
        prestate_json = _canonical_json(prestate)
        expected_counts = command.expected_post_counts.model_dump(mode="json")
        expected_pre_counts = command.expected_prestate.counts.model_dump(mode="json")
        expected_authority = command.expected_prestate.authority.model_dump(mode="json")

        questions = [
            question.model_dump(exclude={"state"}, mode="json")
            for question in command.questions
        ]
        nodes = [
            {
                "tag": node.tag,
                "author": node.author,
                "verdict": node.verdict,
                "script": node.script,
                "result_path": node.result_path,
                "algorithm": node.algorithm,
                "comment": node.comment,
                "limitation": node.limitation,
                "open_question": node.open_question.strip(),
            }
            for node in command.nodes
        ]
        parent_edges = [
            {
                "tag": node.tag,
                "parent": edge.tag,
                "inferred": edge.inferred,
                "relation_kind": edge.relation_kind,
                "evidence_ref": edge.evidence_ref,
            }
            for node in command.nodes
            for edge in node.parent_edges
        ]
        question_links = [
            {"tag": node.tag, "qname": node.open_question.strip()}
            for node in command.nodes
            if node.open_question.strip()
        ]
        foundations = [
            foundation.to_engine().db_record()
            for foundation in command.foundations
        ]
        elements = [element.model_dump(mode="json") for element in command.elements]
        element_uses = [
            use.model_dump(mode="json") for use in command.element_uses
        ]

        incoming_node_names = [f"{name}/{row['tag']}" for row in nodes]
        incoming_foundation_names = [
            f"{name}/{row['name']}" for row in foundations
        ]
        incoming_question_names = [row["qname"] for row in questions]
        incoming_element_names = [row["name"] for row in elements]
        incoming_node_tags = [row["tag"] for row in nodes]
        required_parent_tags = sorted({row["parent"] for row in parent_edges})
        required_question_names = sorted({row["qname"] for row in question_links})
        required_use_tags = sorted({row["tag"] for row in element_uses})
        required_use_elements = sorted({row["element_name"] for row in element_uses})
        incoming_outbox_ids = [row["event_id"] for row in outbox_rows]

        guard_query = (
            """MATCH (t:LakatosTree {name:$tree})
               SET t._tree_write_cas=coalesce(t._tree_write_cas,0)+0
               WITH t
            """
            + _STRUCTURAL_STATE_PROJECTION
            + r"""
CALL (t) {
  WITH t
  OPTIONAL MATCH (existing_node:LakatosNode)
  WHERE existing_node.name IN $incoming_node_names
  RETURN count(existing_node) AS existing_node_conflicts
}
CALL (t) {
  WITH t
  OPTIONAL MATCH (existing_question:OpenQuestion {tree:$tree})
  WHERE existing_question.name IN $incoming_question_names
  RETURN count(existing_question) AS existing_question_conflicts
}
CALL (t) {
  WITH t
  OPTIONAL MATCH (existing_foundation:FoundationRequirement)
  WHERE existing_foundation.name IN $incoming_foundation_names
  RETURN count(existing_foundation) AS existing_foundation_conflicts
}
CALL (t) {
  WITH t
  OPTIONAL MATCH (existing_element:LakatosElement)
  WHERE existing_element.name IN $incoming_element_names
  RETURN count(existing_element) AS existing_element_conflicts
}
CALL (t) {
  WITH t
  OPTIONAL MATCH (t)-[:HAS_NODE]->(use_node:LakatosNode)
                 -[existing_use:USES_ELEMENT]->(use_element:LakatosElement)
  WHERE any(pair IN $incoming_use_pairs
            WHERE pair.tag=use_node.tag AND pair.element_name=use_element.name)
  RETURN count(existing_use) AS existing_use_conflicts
}
CALL () {
  OPTIONAL MATCH (existing_outbox:OutboxEntry)
  WHERE existing_outbox.id IN $incoming_outbox_ids
  RETURN count(existing_outbox) AS existing_outbox_conflicts
}
CALL () {
  OPTIONAL MATCH (prior_outbox:OutboxEntry {
    tree:$tree, structural_batch_id:$batch_id
  })
  WITH [item IN collect(
    CASE WHEN prior_outbox IS NULL THEN null
         ELSE {event_id:prior_outbox.id, created_at:prior_outbox.created_at}
    END
  ) WHERE item IS NOT NULL] AS rows
  RETURN rows AS prior_outboxes
}
OPTIONAL MATCH (prior:StructuralBatchReceipt {id:$receipt_id})
WITH t, structural_authority, structural_counts, structural_state_sha256,
     structural_nodes, structural_questions, structural_elements,
     existing_node_conflicts, existing_question_conflicts,
     existing_foundation_conflicts, existing_element_conflicts,
     existing_use_conflicts, existing_outbox_conflicts, prior_outboxes,
     [item IN collect(prior) WHERE item IS NOT NULL] AS priors,
     [item IN structural_nodes | item.tag] + $incoming_node_tags AS known_tags,
     [item IN structural_questions | item.name] + $incoming_question_names AS known_questions,
     [item IN structural_elements | item.name] + $incoming_element_names AS known_elements
WITH t, structural_authority, structural_counts, structural_state_sha256,
     existing_node_conflicts, existing_question_conflicts,
     existing_foundation_conflicts, existing_element_conflicts,
     existing_use_conflicts, existing_outbox_conflicts, prior_outboxes, priors,
     CASE WHEN size(priors)=1 THEN priors[0] ELSE null END AS prior,
     known_tags, known_questions, known_elements
RETURN
  CASE
    WHEN size(priors)>1 THEN 'idempotency_conflict'
    WHEN size(priors)=1 AND coalesce(
      prior.tree=$tree
      AND prior.batch_id=$batch_id
      AND prior.manifest_sha256=$manifest_sha256
      AND prior.request_sha256=$request_sha256
      AND prior.receipt_id=$receipt_id,
      false) THEN 'already_committed'
    WHEN size(priors)=1 OR existing_outbox_conflicts>0
      THEN 'idempotency_conflict'
    WHEN NOT $constraints_ready THEN 'constraint_missing'
    WHEN coalesce(t.tree_incarnation_id,'') <> $expected_incarnation
      OR coalesce(t.structural_revision,0) <> $expected_revision
      OR structural_state_sha256 <> $expected_state_sha256
      OR structural_counts <> $expected_pre_counts
      OR structural_authority <> $expected_authority
      THEN 'prestate_mismatch'
    WHEN existing_node_conflicts>0 OR existing_question_conflicts>0
      OR existing_foundation_conflicts>0 OR existing_element_conflicts>0
      OR existing_use_conflicts>0
      THEN 'ownership_conflict'
    WHEN any(tag IN $required_parent_tags WHERE NOT tag IN known_tags)
      OR any(qname IN $required_question_names WHERE NOT qname IN known_questions)
      OR any(tag IN $required_use_tags WHERE NOT tag IN known_tags)
      OR any(elname IN $required_use_elements WHERE NOT elname IN known_elements)
      THEN 'invariant_conflict'
    ELSE 'ok'
  END AS guard_status,
  prior.prestate_json AS prestate_json,
  prior.event_intents_json AS event_intents_json,
  prior.post_predictions AS post_predictions,
  prior.post_progress_verdicts AS post_progress_verdicts,
  prior.post_results AS post_results,
  prior.post_verdict_receipts AS post_verdict_receipts,
  prior.post_elements AS post_elements,
  prior.post_element_uses AS post_element_uses,
  prior.post_foundations AS post_foundations,
  prior.post_nodes AS post_nodes,
  prior.post_parent_edges AS post_parent_edges,
  prior.post_questions AS post_questions,
  prior.post_state_sha256 AS post_state_sha256,
  prior.post_structural_revision AS post_structural_revision,
  prior.tree_incarnation_id AS tree_incarnation_id,
  prior.batch_id AS batch_id,
  prior.manifest_sha256 AS manifest_sha256,
  prior.receipt_id AS receipt_id,
  prior.request_sha256 AS request_sha256,
  prior.created_at AS created_at,
  prior_outboxes AS prior_outboxes
"""
        )

        common = {
            "tree": name,
            "batch_id": command.batch_id,
            "manifest_sha256": command.manifest_sha256,
            "request_sha256": request_sha256,
            "receipt_id": receipt_id,
            "constraints_ready": bool(constraints_ready),
            "expected_incarnation": command.expected_prestate.tree_incarnation_id,
            "expected_revision": command.expected_prestate.structural_revision,
            "expected_state_sha256": command.expected_prestate.state_sha256,
            "expected_pre_counts": expected_pre_counts,
            "expected_authority": expected_authority,
            "incoming_node_names": incoming_node_names,
            "incoming_question_names": incoming_question_names,
            "incoming_foundation_names": incoming_foundation_names,
            "incoming_element_names": incoming_element_names,
            "incoming_node_tags": incoming_node_tags,
            "incoming_use_pairs": element_uses,
            "incoming_outbox_ids": incoming_outbox_ids,
            "required_parent_tags": required_parent_tags,
            "required_question_names": required_question_names,
            "required_use_tags": required_use_tags,
            "required_use_elements": required_use_elements,
        }

        ops: list[tuple[str, dict]] = [(guard_query, common)]
        ops.append((
            """UNWIND $events AS event
               CREATE (intent:OutboxEntry {id:event.event_id})
               SET intent.tree=event.tree, intent.op=event.op,
                   intent.node_tag=event.node_tag, intent.payload=event.payload,
                   intent.status='pending', intent.created_at=$ts,
                   intent.reason='structural_batch_commit_intent',
                   intent.request_sha256=$request_sha256,
                   intent.structural_batch_id=$batch_id
               WITH count(intent) AS actual
               CALL apoc.util.validate(
                 actual <> $expected, 'structural_batch_outbox_count_mismatch',
                 [actual, $expected]
               )
               RETURN actual AS event_count""",
            {
                "events": outbox_rows,
                "expected": len(outbox_rows),
                "ts": ts,
                "request_sha256": request_sha256,
                "batch_id": command.batch_id,
            },
        ))
        ops.append((
            """MATCH (t:LakatosTree {name:$tree})
               UNWIND $rows AS row
               CREATE (q:OpenQuestion {name:row.qname, tree:$tree})
               SET q.body=row.body, q.expected_gain=row.expected_gain,
                   q.cost=row.cost, q.status='OPEN', q.created_at=$ts
               CREATE (t)-[:HAS_FRONTIER]->(q)
               WITH count(q) AS actual
               CALL apoc.util.validate(
                 actual <> $expected, 'structural_batch_question_count_mismatch',
                 [actual, $expected]
               )
               RETURN actual AS questions""",
            {"tree": name, "rows": questions, "ts": ts, "expected": len(questions)},
        ))
        ops.append((
            """MATCH (t:LakatosTree {name:$tree})
               UNWIND $rows AS row
               CREATE (node:LakatosNode:PrismExperiment {name:$tree+'/'+row.tag})
               SET node.tag=row.tag, node.author=row.author,
                   node.verdict='proof', node.verdict_source=null,
                   node.node_state='DRAFT', node.script=row.script,
                   node.result_path=row.result_path, node.algorithm=row.algorithm,
                   node.comment=row.comment, node.limitation=row.limitation,
                   node.open_question=row.open_question,
                   node.metric_name=null, node.metric_value=null,
                   node.metric_scope=null, node.recorded_at=$ts
               CREATE (t)-[:HAS_NODE]->(node)
               WITH count(node) AS actual
               CALL apoc.util.validate(
                 actual <> $expected, 'structural_batch_node_count_mismatch',
                 [actual, $expected]
               )
               RETURN actual AS nodes""",
            {"tree": name, "rows": nodes, "ts": ts, "expected": len(nodes)},
        ))
        ops.append((
            """UNWIND $rows AS row
               MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(node:LakatosNode {tag:row.tag})
               MATCH (t)-[:HAS_FRONTIER]->(q:OpenQuestion {name:row.qname})
               CREATE (node)-[:RAISES_QUESTION]->(q)
               WITH count(q) AS actual
               CALL apoc.util.validate(
                 actual <> $expected,
                 'structural_batch_question_link_count_mismatch',
                 [actual, $expected]
               )
               RETURN actual AS question_links""",
            {"tree": name, "rows": question_links, "expected": len(question_links)},
        ))
        ops.append((
            """UNWIND $rows AS row
               MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(child:LakatosNode {tag:row.tag})
               MATCH (t)-[:HAS_NODE]->(parent:LakatosNode {tag:row.parent})
               CREATE (child)-[edge:BRANCHED_FROM]->(parent)
               SET edge.inferred=false, edge.relation_kind=row.relation_kind,
                   edge.evidence_ref=row.evidence_ref
               WITH count(edge) AS actual
               CALL apoc.util.validate(
                 actual <> $expected,
                 'structural_batch_parent_edge_count_mismatch',
                 [actual, $expected]
               )
               RETURN actual AS parent_edges""",
            {"tree": name, "rows": parent_edges, "expected": len(parent_edges)},
        ))
        ops.append((
            """MATCH (t:LakatosTree {name:$tree})
               UNWIND $rows AS row
               CREATE (foundation:FoundationRequirement {name:$tree+'/'+row.name})
               SET foundation.short_name=row.name, foundation.kind=row.kind,
                   foundation.question=row.question,
                   foundation.why_needed=row.why_needed,
                   foundation.acceptance_criteria=row.acceptance_criteria,
                   foundation.evidence_refs=row.evidence_refs,
                   foundation.status=row.status, foundation.optional=row.optional,
                   foundation.owner=row.owner,
                   foundation.risk_if_missing=row.risk_if_missing,
                   foundation.satisfied=row.satisfied,
                   foundation.updated_at=$ts
               CREATE (t)-[:HAS_FOUNDATION]->(foundation)
               WITH count(foundation) AS actual
               CALL apoc.util.validate(
                 actual <> $expected,
                 'structural_batch_foundation_count_mismatch',
                 [actual, $expected]
               )
               RETURN actual AS foundations""",
            {
                "tree": name,
                "rows": foundations,
                "ts": ts,
                "expected": len(foundations),
            },
        ))
        ops.append((
            """MATCH (t:LakatosTree {name:$tree})
               UNWIND $rows AS row
               CREATE (element:LakatosElement {name:row.name})
               SET element.definition=row.definition,
                   element.implication=row.implication,
                   element.lifecycle=row.lifecycle, element.scope=row.scope,
                   element.updated_at=$ts
               CREATE (t)-[:HAS_ELEMENT]->(element)
               WITH count(element) AS actual
               CALL apoc.util.validate(
                 actual <> $expected, 'structural_batch_element_count_mismatch',
                 [actual, $expected]
               )
               RETURN actual AS elements""",
            {"tree": name, "rows": elements, "ts": ts, "expected": len(elements)},
        ))
        ops.append((
            """UNWIND $rows AS row
               MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(node:LakatosNode {tag:row.tag})
               MATCH (t)-[:HAS_ELEMENT]->(element:LakatosElement {name:row.element_name})
               CREATE (node)-[use:USES_ELEMENT]->(element)
               SET use.note=row.note, use.evidence_ref=row.evidence_ref, use.at=$ts
               WITH count(use) AS actual
               CALL apoc.util.validate(
                 actual <> $expected,
                 'structural_batch_element_use_count_mismatch',
                 [actual, $expected]
               )
               RETURN actual AS element_uses""",
            {
                "tree": name,
                "rows": element_uses,
                "ts": ts,
                "expected": len(element_uses),
            },
        ))

        final_query = (
            """MATCH (t:LakatosTree {name:$tree})
               SET t.structural_revision=coalesce(t.structural_revision,0)+1
               WITH t
            """
            + _STRUCTURAL_STATE_PROJECTION
            + r"""
CALL apoc.util.validate(
  structural_counts <> $expected_post_counts
  OR structural_authority <> $expected_authority,
  'structural_batch_postcondition_mismatch',
  []
)
CREATE (receipt:StructuralBatchReceipt {id:$receipt_id})
SET receipt.receipt_id=$receipt_id, receipt.tree=$tree,
    receipt.batch_id=$batch_id, receipt.manifest_sha256=$manifest_sha256,
    receipt.request_sha256=$request_sha256, receipt.request_json=$request_json,
    receipt.prestate_json=$prestate_json,
    receipt.event_intents_json=$event_intents_json,
    receipt.tree_incarnation_id=t.tree_incarnation_id,
    receipt.post_structural_revision=t.structural_revision,
    receipt.post_state_sha256=structural_state_sha256,
    receipt.post_nodes=structural_counts.nodes,
    receipt.post_questions=structural_counts.questions,
    receipt.post_foundations=structural_counts.foundations,
    receipt.post_elements=structural_counts.elements,
    receipt.post_element_uses=structural_counts.element_uses,
    receipt.post_parent_edges=structural_counts.parent_edges,
    receipt.post_predictions=structural_authority.predictions,
    receipt.post_results=structural_authority.results,
    receipt.post_verdict_receipts=structural_authority.verdict_receipts,
    receipt.post_progress_verdicts=structural_authority.progress_verdicts,
    receipt.created_at=$ts
CREATE (t)-[:HAS_STRUCTURAL_BATCH_RECEIPT]->(receipt)
RETURN receipt.prestate_json AS prestate_json,
       receipt.event_intents_json AS event_intents_json,
       receipt.post_predictions AS post_predictions,
       receipt.post_progress_verdicts AS post_progress_verdicts,
       receipt.post_results AS post_results,
       receipt.post_verdict_receipts AS post_verdict_receipts,
       receipt.post_elements AS post_elements,
       receipt.post_element_uses AS post_element_uses,
       receipt.post_foundations AS post_foundations,
       receipt.post_nodes AS post_nodes,
       receipt.post_parent_edges AS post_parent_edges,
       receipt.post_questions AS post_questions,
       receipt.post_state_sha256 AS post_state_sha256,
       receipt.post_structural_revision AS post_structural_revision,
       receipt.tree_incarnation_id AS tree_incarnation_id,
       receipt.batch_id AS batch_id,
       receipt.manifest_sha256 AS manifest_sha256,
       receipt.receipt_id AS receipt_id,
       receipt.request_sha256 AS request_sha256,
       receipt.created_at AS created_at
"""
        )
        ops.append((
            final_query,
            {
                "tree": name,
                "expected_post_counts": expected_counts,
                "expected_authority": expected_authority,
                "receipt_id": receipt_id,
                "batch_id": command.batch_id,
                "manifest_sha256": command.manifest_sha256,
                "request_sha256": request_sha256,
                "request_json": request_json,
                "prestate_json": prestate_json,
                "event_intents_json": event_intents_json,
                "ts": ts,
            },
        ))

        try:
            results = self.kg_tx(_structural_batch_managed_ops(ops))
        except KgTxGuardFailed as exc:
            state = exc.actual
            if state == "already_committed":
                try:
                    replay = _structural_result_from_receipt_row(exc.row or {})
                except (TypeError, ValueError, json.JSONDecodeError) as replay_exc:
                    raise StructuralInvariantFailure(
                        f"structural batch durable receipt is corrupt: {receipt_id}"
                    ) from replay_exc
                if (
                    replay["receipt_id"] != receipt_id
                    or replay["batch_id"] != command.batch_id
                    or replay["manifest_sha256"] != command.manifest_sha256
                    or replay["request_sha256"] != request_sha256
                ):
                    raise StructuralBatchIdempotencyConflict(command.batch_id) from exc
                if not _structural_result_matches_expected(
                    replay,
                    prestate=prestate,
                    expected_counts=expected_counts,
                    expected_authority=expected_authority,
                    expected_revision=command.expected_prestate.structural_revision + 1,
                    expected_incarnation=command.expected_prestate.tree_incarnation_id,
                    expected_events=public_events,
                ) or not _structural_outbox_timestamps_match(
                    (exc.row or {}).get("prior_outboxes"),
                    expected_events=public_events,
                    receipt_created_at=replay["created_at"],
                ):
                    raise StructuralInvariantFailure(
                        f"structural batch replay receipt binding mismatch: {receipt_id}"
                    ) from exc
                return DurableStructuralBatchWrite(
                    summary=WriteSummary(tx_count=1, op_count=len(ops), rows=1),
                    receipt_id=receipt_id,
                    batch_id=command.batch_id,
                    manifest_sha256=command.manifest_sha256,
                    request_sha256=request_sha256,
                    created_at=replay["created_at"],
                    prestate=replay["prestate"],
                    poststate=replay["poststate"],
                    event_intents=tuple(replay["event_intents"]),
                    idempotent=True,
                )
            if state == "idempotency_conflict":
                raise StructuralBatchIdempotencyConflict(command.batch_id) from exc
            if state == "prestate_mismatch":
                raise StructuralPrestateMismatch(name) from exc
            if state == "constraint_missing":
                raise StructuralConstraintUnavailable(name) from exc
            if state == "ownership_conflict":
                raise StructuralOwnershipConflict(name) from exc
            if state == "invariant_conflict":
                raise StructuralReferenceConflict(name) from exc
            raise StructuralBatchNotFound(name) from exc

        if not results or not results[0]:
            raise StructuralBatchNotFound(name)
        final_rows = results[-1] if results else []
        if len(final_rows) != 1:
            raise StructuralInvariantFailure(
                f"structural batch final receipt cardinality is {len(final_rows)}"
            )
        try:
            result = _structural_result_from_receipt_row(final_rows[0])
        except (TypeError, ValueError, json.JSONDecodeError) as result_exc:
            raise StructuralInvariantFailure(
                f"structural batch result is corrupt: {receipt_id}"
            ) from result_exc
        if (
            result["receipt_id"] != receipt_id
            or result["batch_id"] != command.batch_id
            or result["manifest_sha256"] != command.manifest_sha256
            or result["request_sha256"] != request_sha256
            or result["created_at"] != ts
            or not _structural_result_matches_expected(
                result,
                prestate=prestate,
                expected_counts=expected_counts,
                expected_authority=expected_authority,
                expected_revision=command.expected_prestate.structural_revision + 1,
                expected_incarnation=command.expected_prestate.tree_incarnation_id,
                expected_events=public_events,
            )
        ):
            raise StructuralInvariantFailure("structural batch receipt binding mismatch")
        logical_rows = (
            len(questions) + len(nodes) + len(question_links) + len(parent_edges)
            + len(foundations)
            + len(elements) + len(element_uses) + len(event_intents) + 1
        )
        return DurableStructuralBatchWrite(
            summary=WriteSummary(tx_count=1, op_count=len(ops), rows=logical_rows),
            receipt_id=receipt_id,
            batch_id=command.batch_id,
            manifest_sha256=command.manifest_sha256,
            request_sha256=request_sha256,
            created_at=result["created_at"],
            prestate=result["prestate"],
            poststate=result["poststate"],
            event_intents=tuple(result["event_intents"]),
            idempotent=False,
        )

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
