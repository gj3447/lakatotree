"""Application service for node judgement and scripted verdicts.

# KG: seed-lkt-engine-route-judgement-extract-20260616
"""

from __future__ import annotations

import json
import hashlib
import math
import os
import tempfile
from collections.abc import Callable
from contextlib import nullcontext
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path, PurePosixPath

from fastapi import HTTPException

from lakatos import assurance, layout as layout_mod, longinus, temporal as temporal_mod
from lakatos import measurement_lock as mlock_mod
from lakatos import replay_artifacts as replay_artifact_mod
from lakatos.io import envfp as envfp_mod
from lakatos.io.reconcile import (
    HistoryPayloadError,
    canonical_history_payload,
    validate_history_record,
)
from lakatos.io.replay import ProducerReplayVerdict
from lakatos.engine_identity import ENGINE_RULE_SHA, effective_floor
from lakatos.frontier_state import (
    QuestionEvent,
    QuestionState,
    receipt_backed_conclusive,
    step as step_question,
)
from lakatos.node_state import NodeState, assert_transition_allowed, derive_node_state
from lakatos.trust import INTERNAL_SOURCE_TRUST
from lakatos.verdict.argue import assemble_af, grounded_extension
from lakatos.eureka import classify as eureka_classify
from lakatos.engine import FoundationMap, LakatosEvidence, LakatosGate
from lakatos.ontology import DomainOntology
from lakatos.verdict.judge import NovelTarget, Prediction, PredictionMissing, judge
from lakatos.verdict.pnr import CounterexampleType, ProofGeneratedConcept, Response, appraise_response
from lakatos.io.prov import prov_triples, replay_command
from lakatos.verdict.spine import credibility_from_trust, dialectical_verdict, synthesize_promotion
from lakatos.verdicts import (ADMIN_VERDICTS, FORCEFUL_SOURCES, RECEIPT_FIELDS,
                              comment_seal_sha,
                              fold_receipt_chain, is_admin_verdict, normalize_source,
                              prediction_content_sha, prediction_history_payload_sha,
                              receipt_content_sha,
                              verdict_history_payload_sha)
from lakatos.write_cert import (CertError, CertSignerNotAllowed, operation_payload_sha256,
                                verify_write_cert)
from server.contexts.audit import fsck as audit_fsck
from server.contexts.tree.cycle_budget import (
    LOCKED_BUDGET_GUARD,
    assert_scoring_budget,
    raise_after_locked_budget_rejection,
)
from server.contexts.tree.admin_intents import (
    AdminIntentError,
    validate_admin_verdict_intent,
)
from server.contexts.tree.prediction_intents import effective_prediction_anchors
from server.contexts.tree.layout_gate import resolve_role_layout
from server.contexts.tree.judgement_policy import (apply_verdict_demotes, build_receipt_fields,
                                                   engine_freshness_fires, qualitative_flags,
                                                   resolve_measurement, response_assurance)
from server.engine_freshness import freshness_provider_from_env
from server.contexts.tree.schemas import PredictionIn, TestResultIn, VerdictIn
from server.contexts.tree.verdict_intents import (
    VerdictIntentError,
    validate_verdict_intent_group,
)
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
ReproducibleProvider = Callable[[str, str], bool | None]


def _serialized_ledger_command(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        scope = getattr(self, 'ledger_scope', None) or (lambda: nullcontext())
        with scope():
            return method(self, *args, **kwargs)

    return wrapped


def _canonical_history_object(payload_text: object) -> dict:
    """Decode one canonical durable-history JSON object without key smuggling."""
    if not isinstance(payload_text, str):
        raise ValueError('history payload must be canonical JSON text')

    def unique_object(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError(f'duplicate JSON key: {key}')
            out[key] = value
        return out

    value = json.loads(
        payload_text,
        object_pairs_hook=unique_object,
        parse_constant=lambda token: (_ for _ in ()).throw(
            ValueError(f'non-finite JSON number: {token}')
        ),
    )
    if not isinstance(value, dict):
        raise ValueError('history payload must be an object')
    if canonical_history_payload(value) != payload_text:
        raise ValueError('history payload is not canonical')
    return value


# FF4 (보안, deep-dive 2026-06-26): judge-script sha 재유도가 *임의* 절대파일을 읽지 않도록 허용 루트 안으로
#   containment(relative traversal 거부와 대칭). 허용 = repo ROOT + OS temp(테스트/런타임 작업영역) + 선택 env.
def _allowed_script_roots() -> list[Path]:
    roots = [Path(longinus.ROOT).resolve(), Path(tempfile.gettempdir()).resolve(),
             replay_artifact_mod.replay_cache_root()]
    for part in os.environ.get('LAKATOS_SCRIPT_ROOTS', '').split(os.pathsep):
        part = part.strip()
        if part:
            try:
                roots.append(Path(part).resolve())
            except OSError:
                pass
    return roots


# FF4 판정의 단일 출처 — sha 재유도(JudgementService._isolate_script_file)와 AG2 replay 실행(app._replay_run)이
#   *같은* 격리를 공유한다(보안 로직 이중화 = drift 위험). 통과=(resolved, {}) / 거부=(None, {'reason': ...}).
SCRIPT_MAX_BYTES = 8 << 20   # FF4: 무제한 read/exec RAM-DoS 차단 (judge 스크립트는 작다)
RESULT_MAX_BYTES = 64 << 20  # replay artifact hash 상한(대형 임의파일 read/DoS 차단)


def isolate_script_file(file_str: str, max_bytes: int = SCRIPT_MAX_BYTES) -> tuple[Path | None, dict]:
    """허용 루트(repo ROOT + OS temp + env) 안, size-cap 이하, 존재하는 정규파일로 격리.
    상대경로는 ROOT 기준 join 후 traversal 거부, 절대경로는 _allowed_script_roots() 안일 때만 허용."""
    root = Path(longinus.ROOT).resolve()
    p = Path(file_str)
    if p.is_absolute():
        try:
            resolved = p.resolve()
        except OSError:
            return None, {'reason': 'unresolvable', 'script': file_str}
        # 절대경로도 허용 루트 안에 있어야 — 임의 파일 sha 오라클 + 무인증 RAM-DoS 차단.
        if not any(r == resolved or r in resolved.parents for r in _allowed_script_roots()):
            return None, {'reason': 'out_of_root', 'script': file_str}
    else:
        try:
            resolved = (root / p).resolve()
        except OSError:
            return None, {'reason': 'unresolvable', 'script': file_str}
        if root not in resolved.parents and resolved != root:   # ../ 탈출 = traversal 거부
            return None, {'reason': 'path_traversal', 'script': file_str}
    try:
        if not resolved.is_file():   # 미존재/비정규 = 재계산 불가
            return None, {'reason': 'not_a_file', 'script': file_str}
    except OSError:
        # ENAMETOOLONG 등 경로 자체를 stat 할 수 없는 입력은 client 오류지 서버 크래시가 아니다.
        return None, {'reason': 'unresolvable', 'script': file_str}
    try:   # unbounded read 차단 — size cap (대용량 파일 RAM-exhaustion 방지)
        if resolved.stat().st_size > max_bytes:
            return None, {'reason': 'too_large', 'script': file_str, 'size': resolved.stat().st_size}
    except OSError:
        return None, {'reason': 'read_error', 'script': file_str}
    return resolved, {}


def isolate_portable_replay_file(
    file_str: str,
    max_bytes: int,
) -> tuple[Path | None, str, dict]:
    """Resolve one canonical repo-relative POSIX replay input.

    This is deliberately stricter than :func:`isolate_script_file`.  The latter remains the
    compatibility boundary for legacy/notebook commands and server-private replay snapshots;
    receipted artifacts must not encode a submitter host's absolute/temp/env-root identity.
    Success returns the resolved local path plus the normalized repo-relative spelling.  The
    caller keeps the raw request untouched for request/history/certificate hashes.
    """
    if not isinstance(file_str, str) or not file_str:
        return None, '', {'reason': 'empty_path'}
    raw = file_str
    if '\x00' in raw:
        return None, '', {'reason': 'nul_byte', 'path': raw}
    if '\\' in raw:
        return None, '', {'reason': 'non_posix_separator', 'path': raw}
    if '::' in raw:
        return None, '', {'reason': 'symbol_path_not_portable', 'path': raw}
    if raw.startswith('~'):
        return None, '', {'reason': 'home_relative', 'path': raw}
    if len(raw) >= 2 and raw[0].isalpha() and raw[1] == ':':
        return None, '', {'reason': 'windows_drive', 'path': raw}
    try:
        portable = PurePosixPath(raw)
        parts = portable.parts
        normalized = portable.as_posix()
    except (OSError, ValueError):
        return None, '', {'reason': 'unresolvable', 'path': raw}
    if portable.is_absolute():
        return None, '', {'reason': 'absolute_path', 'path': raw}
    if '..' in parts:
        return None, '', {'reason': 'path_traversal', 'path': raw}
    if not parts or raw != normalized or normalized in ('', '.'):
        return None, '', {'reason': 'noncanonical_posix_path', 'path': raw}
    try:
        root = Path(longinus.ROOT).resolve()
        resolved = (root / Path(*parts)).resolve()
    except (OSError, ValueError):
        return None, '', {'reason': 'unresolvable', 'path': raw}
    if resolved != root and root not in resolved.parents:
        return None, '', {'reason': 'symlink_escape', 'path': raw}
    try:
        if not resolved.is_file():
            return None, '', {'reason': 'not_a_file', 'path': raw}
        size = resolved.stat().st_size
    except (OSError, ValueError):
        return None, '', {'reason': 'read_error', 'path': raw}
    if size > max_bytes:
        return None, '', {'reason': 'too_large', 'path': raw, 'size': size}
    return resolved, normalized, {}


def _is_lower_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(ch in '0123456789abcdef' for ch in value)
    )

# #H2 (human-attestation): floor 의 human 영수증으로 인정하는 KG Argument 의 kind 토큰.
#   evidence_claim_service.event_from_argument 와 *동일* 집합(kind∈{evaluation,verdict}→human_verdict action) —
#   인간 attestation 의 단일 어휘 정본. doubt/comment/rebuttal 등은 human 평가가 아니라 제외.
_HUMAN_ATTESTATION_KINDS = frozenset({'evaluation', 'verdict'})


def _is_human_attestation_arg(arg: dict) -> bool:
    """KG Argument 가 *실제 human attestation* 인가 — kind∈human 집합 AND by(사람 actor) 존재.
    client 의 1비트가 아니라 *영속된* Argument 존재로 판정(H2 우회 봉쇄). by 가 비면(익명) human 으로 안 침."""
    if not arg or not arg.get('id'):
        return False
    if (arg.get('kind') or '').strip().lower() not in _HUMAN_ATTESTATION_KINDS:
        return False
    return bool((arg.get('by') or '').strip())


def _require_state_transition(before, after: NodeState) -> None:
    try:
        assert_transition_allowed(before, after)
    except ValueError as e:
        raise HTTPException(409, str(e))


class JudgementService:
    """Owns node verdict, prediction, and scripted test-result mutations."""

    # KG: seed-lkt-engine-route-judgement-extract-20260616

    _SCRIPT_MAX_BYTES = SCRIPT_MAX_BYTES   # FF4 size cap — 모듈 정본(isolate_script_file 과 공유)
    _RESULT_MAX_BYTES = RESULT_MAX_BYTES

    def __init__(
        self,
        *,
        kg: KgQuery,
        kg_tx: KgTx,
        hist: HistoryAppend,
        foundation: FoundationProvider,
        reproducible_for_node: ReproducibleProvider,
        producer_replay_for_node: ReproducibleProvider | None = None,
        producer_replay_submit=None,
        engine_freshness=None,
        ledger_ready: Callable[[], None] | None = None,
        ledger_kg_tx: KgTx | None = None,
        ledger_scope=None,
        prediction_temporal_commitment_provider=None,
        temporal_proof_provider=None,
    ):
        self.kg = kg
        self.kg_tx = kg_tx
        self.hist = hist
        self.foundation = foundation
        self.reproducible_for_node = reproducible_for_node
        # 나생문 #1 근본 봉합(live): 채점 스크립트 재실행으로 측정 외부검증(미주입=None 반환 no-op = 거동 불변).
        self.producer_replay_for_node = producer_replay_for_node or (lambda _n, _t: None)
        # AG3/R-SOV V1 (측정주권 2026-07-03): submit 시 *들어온* 값을 서버가 재유도 → 전체 ProducerReplayVerdict
        #   (regenerated 포함). 값소유 치환의 원천. 미주입=None 반환 no-op(거동 불변: client 값 그대로 봉인).
        self.producer_replay_submit = producer_replay_submit or (lambda *_a, **_k: None)
        # jp4: 판관 자기신원/능력 provider — 미주입=env opt-in 기본(미설정=None=게이트 완전 사체,
        #   비파괴; 테스트는 명시 주입으로만 무장). app.py 무편집 라이브 배선 = 이 env-default.
        self.engine_freshness = (engine_freshness if engine_freshness is not None
                                 else freshness_provider_from_env())
        # The production composition root injects the cross-store readiness
        # gate and the writer-fenced Neo4j transaction port.  Keeping both
        # optional preserves the small in-memory application-service seam used
        # by unit tests and non-server library consumers; it does not weaken
        # the live HTTP path, where both are mandatory by construction.
        self.ledger_ready = ledger_ready or (lambda: None)
        self.ledger_kg_tx = ledger_kg_tx
        self.ledger_scope = ledger_scope or (lambda: nullcontext())
        self.prediction_temporal_commitment_provider = (
            prediction_temporal_commitment_provider or (lambda _name, _tag: None)
        )
        self.temporal_proof_provider = temporal_proof_provider

    def _prediction_temporal_binding(
        self,
        name: str,
        tag: str,
        prediction_row: dict,
    ) -> tuple[str | None, str | None]:
        """Resolve an attached T1 commitment without imposing Gate 3 on legacy nodes."""

        raw_count = prediction_row.get("prediction_temporal_commitment_count", 0)
        if type(raw_count) is not int or raw_count not in {0, 1}:
            raise HTTPException(
                409,
                "prediction temporal commitment cardinality is invalid",
            )
        if raw_count == 0:
            return None, None

        temporal_commitment = self.prediction_temporal_commitment_provider(
            name, tag
        )
        if temporal_commitment is None:
            raise HTTPException(
                409,
                "prediction temporal commitment is unavailable",
            )
        commitment_sha = getattr(temporal_commitment, "commitment_sha256", None)
        policy_sha = getattr(
            temporal_commitment, "authority_policy_sha256", None
        )
        if not (
            getattr(temporal_commitment, "prediction_receipt_sha256", None)
            == prediction_row.get("pred_receipt_sha")
            and isinstance(commitment_sha, str)
            and isinstance(policy_sha, str)
        ):
            raise HTTPException(
                409,
                "prediction temporal commitment does not bind the current prediction",
            )
        return commitment_sha, policy_sha

    def _require_ledger_ready(self) -> None:
        self.ledger_ready()

    def _ledger_write(self, query: str, **params) -> list[dict]:
        """Execute one ledger mutation through the live writer fence.

        Legacy application-service tests inject only ``kg``.  The fallback is
        deliberately confined to that uncomposed seam; ``server.app`` always
        supplies ``ledger_kg_tx``.  A live ledger statement must return its
        success row while the managed callback is still open; an empty final
        projection rolls the complete statement back.
        """

        if self.ledger_kg_tx is None:
            return self.kg(query, **params)
        try:
            results = self.ledger_kg_tx(GuardedKgOps([(query, params)]))
        except KgTxGuardFailed:
            # Raised inside execute_write before commit: callers retain their
            # empty-row CAS handling without admitting partial ledger effects.
            return []
        if not isinstance(results, list) or len(results) != 1:
            raise HTTPException(500, 'ledger mutation returned an invalid transaction shape')
        rows = results[0]
        if not isinstance(rows, list):
            raise HTTPException(500, 'ledger mutation returned an invalid row shape')
        return rows

    def _ledger_transaction(self, ops) -> list:
        return (self.ledger_kg_tx or self.kg_tx)(ops)

    def _project_pending_admin_predecessors(
        self, name: str, tag: str
    ) -> None:
        """Project every pending admin intent that still owns this head.

        A compound CANONICAL transition owns both the promoted and demoted
        receipt effects.  Advancing either head while its PostgreSQL event is
        pending would make the immutable intent unrecoverable.  The process
        readiness gate normally prevents that; this receipt-bound check is the
        independent domain fence and also protects callers with stale cached
        readiness.
        """

        rows = self.kg(
            """MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
               OPTIONAL MATCH (e)-[:HAS_RECEIPT]->(head_receipt:VerdictReceipt {
                 receipt_sha:e.current_receipt_sha})
               OPTIONAL MATCH (direct:OutboxEntry {
                 id:'ob-verdict-'+e.current_receipt_sha})
               OPTIONAL MATCH (predecessor:OutboxEntry {
                 demoted_receipt_sha:e.current_receipt_sha,
                 status:'pending'})
               RETURN properties(head_receipt) AS head_receipt,
                      properties(direct) AS direct_outbox,
                      [item IN collect(properties(predecessor))
                       WHERE item.id IS NOT NULL] AS pending_predecessors""",
            tree=name,
            tag=tag,
        )
        if not rows:
            return
        if len(rows) != 1:
            raise HTTPException(500, 'administrative head fence cardinality conflict')
        row = rows[0]
        receipt = row.get('head_receipt') or {}
        direct = row.get('direct_outbox')
        is_admin_v6 = (
            receipt.get('verdict_source') == 'admin'
            and receipt.get('history_payload_sha256') is not None
        )
        if is_admin_v6 and not isinstance(direct, dict):
            raise HTTPException(500, 'V6 administrative receipt lacks its intent')
        if isinstance(direct, dict) and not is_admin_v6:
            raise HTTPException(
                500, 'administrative outbox is attached to a non-admin V6 head'
            )

        candidates: dict[str, dict] = {}
        if isinstance(direct, dict):
            direct_id = direct.get('id')
            if not isinstance(direct_id, str) or not direct_id:
                raise HTTPException(500, 'administrative intent lacks an id')
            candidates[direct_id] = direct
        predecessors = row.get('pending_predecessors') or []
        if not isinstance(predecessors, list):
            raise HTTPException(500, 'administrative predecessor set is malformed')
        for predecessor in predecessors:
            if (
                not isinstance(predecessor, dict)
                or not isinstance(predecessor.get('id'), str)
                or not predecessor['id']
            ):
                raise HTTPException(500, 'administrative predecessor is malformed')
            candidates[predecessor['id']] = predecessor

        for event_id, candidate in candidates.items():
            status = candidate.get('status')
            if status == 'applied':
                if candidate.get('applied_at') is None:
                    raise HTTPException(500, 'administrative applied intent lacks timestamp')
                continue
            if status != 'pending' or candidate.get('applied_at') is not None:
                raise HTTPException(500, 'administrative intent has an invalid state')
            authority_rows = self.kg(
                """MATCH (o:OutboxEntry {id:$event_id})
                   OPTIONAL MATCH (t:LakatosTree {name:o.tree})-[:HAS_NODE]->
                                  (promoted {tag:o.node_tag})
                   OPTIONAL MATCH (promoted)-[:HAS_RECEIPT]->
                                  (rec:VerdictReceipt {receipt_sha:o.receipt_sha})
                   OPTIONAL MATCH (t)-[:HAS_NODE]->(demoted {tag:o.demoted_tag})
                                  -[:HAS_RECEIPT]->
                                  (demoted_rec:VerdictReceipt {
                                    receipt_sha:o.demoted_receipt_sha})
                   RETURN properties(o) AS outbox,
                          promoted.current_receipt_sha AS current_receipt_sha,
                          promoted.verdict AS current_verdict,
                          promoted.verdict_source AS current_verdict_source,
                          properties(rec) AS receipt,
                          CASE WHEN demoted IS NULL THEN null ELSE {
                            tag:demoted.tag,
                            current_receipt_sha:demoted.current_receipt_sha,
                            verdict:demoted.verdict,
                            verdict_source:demoted.verdict_source
                          } END AS demoted_current,
                          properties(demoted_rec) AS demoted_receipt""",
                event_id=event_id,
            )
            if len(authority_rows) != 1:
                raise HTTPException(500, 'administrative predecessor authority conflict')
            authority = authority_rows[0]
            outbox = authority.get('outbox')
            try:
                payload = validate_admin_verdict_intent(
                    tree=outbox.get('tree') if isinstance(outbox, dict) else None,
                    tag=outbox.get('node_tag') if isinstance(outbox, dict) else None,
                    receipt_sha=(
                        outbox.get('receipt_sha')
                        if isinstance(outbox, dict) else None
                    ),
                    receipt=authority.get('receipt'),
                    current={
                        'current_receipt_sha': authority.get(
                            'current_receipt_sha'
                        ),
                        'verdict': authority.get('current_verdict'),
                        'verdict_source': authority.get(
                            'current_verdict_source'
                        ),
                    },
                    outbox=outbox,
                    demoted_receipt=authority.get('demoted_receipt'),
                    demoted_current=authority.get('demoted_current'),
                    require_current_effect=True,
                )
            except (AdminIntentError, AttributeError) as exc:
                raise HTTPException(
                    500, f'administrative predecessor intent corrupt: {exc}'
                ) from exc
            projected = self.hist(
                outbox['tree'],
                'verdict',
                outbox['node_tag'],
                payload,
                event_id=event_id,
            )
            if projected is False:
                raise HTTPException(
                    503,
                    'prior administrative verdict history is pending; head advancement deferred',
                )
            applied_rows = self.kg(
                """MATCH (o:OutboxEntry {id:$event_id})
                   RETURN o.status AS status, o.applied_at AS applied_at""",
                event_id=event_id,
            )
            if not (
                len(applied_rows) == 1
                and applied_rows[0].get('status') == 'applied'
                and applied_rows[0].get('applied_at') is not None
            ):
                raise HTTPException(
                    503,
                    'administrative verdict projection lacks applied readback; head advancement deferred',
                )

    def _node_eigentrust(self, name: str, tag: str) -> tuple[str | None, float | None, bool]:
        """노드의 인터넷 관측 그래프 eigentrust → (src, eigen, backed). src=None: internal 노드
        (인터넷 주장 없음 / 식별 source 없음). seed 자격은 *서버검증 URL 도메인*(#1 R3 forge 봉쇄) —
        client 의 source_type 라벨이 아니다. credibility 게이트(#1)와 eureka source_trust(#4)가
        *동일* 산출을 공유한다(no whack-a-mole). (repository.internet_observations 와 동형 — D9 백로그:
        단일 헬퍼로 통합 후보.)"""
        import json
        rows = self.kg(
            "MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})-[:HAS_RESEARCH_EVENT]->"
            "(ev:ResearchEvent {realm:'internet'}) RETURN ev.payload AS payload ORDER BY ev.created_at",
            tree=name, tag=tag)
        if not rows:
            return None, None, False
        observations, src = [], None
        for r in rows:
            try:
                p = json.loads(r.get('payload') or '{}')
            except (ValueError, TypeError):
                p = {}
            s = (p.get('url') or p.get('source_type') or '').strip()
            if not s:
                continue
            if src is None:
                src = s
            observations.append(dict(source=s, url=p.get('url') or '',   # seed 는 서버검증 URL 도메인으로
                                     source_type=p.get('source_type') or '', node=tag,
                                     corroboration_score=float(p.get('corroboration_score') or 0.0)))
        if src is None:
            return None, None, False
        from lakatos.trust import global_source_trust
        gst = global_source_trust(observations)
        eigen = gst['trust'].get(src)
        backed = eigen is not None and gst['coverage']['mode'] != 'uniform_unlearned'
        return src, eigen, backed

    def _eigentrust_credibility(self, name: str, tag: str, *, novel_confirmed: bool,
                                has_human_verdict: bool) -> dict | None:
        """prom-honesty/credibility (정본 prom 2026-06-21): CANONICAL 승격의 credibility 게이트 입력을
        client-self-reported source_trust 대신 *노드의 인터넷 관측 그래프 eigentrust* 로 산출한다.
          - 인터넷 관측이 없으면 internal 노드 → None(credibility 게이트 생략; constitution+reproducible 가 영수증).
            단 human 이 vouch 하면 그 영수증을 보존한다(credibility=None 이면 floor 가 human 신호 유실, D2↔floor).
          - 있으면 그 source 의 eigentrust(네트워크 신뢰, sybil 저항)로 backed 판정 — self-report 1.0 으론 통과 못 함."""
        src, eigen, backed = self._node_eigentrust(name, tag)
        if src is None:
            return (credibility_from_trust(0.0, trust_backed=False, novel_confirmed=novel_confirmed,
                                           has_human_verdict=True) if has_human_verdict else None)
        return credibility_from_trust(
            float(eigen) if backed else 0.0, trust_backed=backed,
            novel_confirmed=novel_confirmed, has_human_verdict=has_human_verdict)

    def _eigentrust_source_trust(self, name: str, tag: str) -> float:
        """#4 (prom-honesty/provenance_reality_derived): eureka BF 의 source_trust 를 client-self-reported
        r.source_trust 가 아니라 *노드 인터넷 관측 eigentrust* 로 재유도 — forged source_trust 로 BF 를
        부풀려 true-eureka 를 살 수 없다(credibility 게이트와 동일 원천). internal 노드(인터넷 주장 없음)
        =1.0(스크립트 측정 영수증, credibility 주장 아님). 인터넷 노드: backed=그 source eigentrust,
        미뒷받침(forged source_type/junk URL → #1 URL-도메인 seed gating)=0.0(BF 중립). receipt:
        tests/test_eureka_source_trust_eigentrust.py."""
        src, eigen, backed = self._node_eigentrust(name, tag)
        if src is None:
            return INTERNAL_SOURCE_TRUST
        return float(eigen) if backed else 0.0

    def _isolate_script_file(self, file_str: str) -> tuple[Path | None, dict]:
        """FF4 경로격리(모듈 정본 isolate_script_file 로 위임) — 평이경로/`file::symbol` 양 분기 *공용*
        (나생문 #12: 분기 비대칭 봉합). sha 재유도와 AG2 replay 실행이 같은 격리를 쓴다."""
        return isolate_script_file(file_str, self._SCRIPT_MAX_BYTES)

    def _recompute_script_sha(self, script: str) -> tuple[str | None, dict]:
        """#H3 (prom-honesty/receipt-integrity): judge_script_sha 를 *서버가 파일 내용에서 재유도*.

        '어느 스크립트가 채점했나' 영수증은 client 문자열 신뢰면 동어반복(client psha vs client script_sha).
        r.script 가 읽을 수 있는 소스면 서버가 그 본문으로 sha256 을 재계산해 영수증을 현실에 묶는다.
          - 'file::symbol' 형태 → longinus.symbol_body_sha (CPG 본문해시; 부재/모호=None).
          - 평이한 경로 → 파일 내용 hashlib.sha256.
        두 분기 모두 _isolate_script_file 로 FF4 격리(허용 루트·size-cap)를 *동일하게* 거친다.
        재계산 불가(inline/미존재/traversal/심볼 모호/루트 밖)면 (None, …) 반환 → 호출부가 정직 fallback
        (client 값 유지 + server_verified=False).
        """
        s = (script or '').strip()
        if not s:
            return None, {'reason': 'empty_script'}
        if '::' in s:   # file::symbol — Longinus CPG 본문해시(심볼 실존검증)
            file_part, _, symbol = s.partition('::')
            resolved, info = self._isolate_script_file(file_part)   # FF4 격리: 평이경로 분기와 대칭
            if resolved is None:
                return None, info
            try:
                sha, sinfo = longinus.symbol_body_sha(str(resolved), symbol)
            except OSError:
                return None, {'reason': 'symbol_io_error', 'script': s}
            if sha is None:
                return None, {'reason': 'symbol_unresolved', **sinfo}
            return sha, {'reason': 'symbol_body_sha', **sinfo}
        resolved, info = self._isolate_script_file(s)
        if resolved is None:
            return None, info
        try:
            sha = file_sha(str(resolved))
        except OSError:
            return None, {'reason': 'read_error', 'script': s}
        return sha, {'reason': 'file_content_sha', 'path': str(resolved)}

    def _recompute_result_sha(self, result_path: str) -> tuple[str | None, str, dict]:
        """Resolve and hash a replay artifact within allowed roots and a bounded size."""
        raw = (result_path or '').strip()
        if not raw:
            return None, '', {'reason': 'empty_result_path'}
        resolved, info = isolate_script_file(raw, self._RESULT_MAX_BYTES)
        if resolved is None:
            return None, raw, info
        try:
            sha = file_sha(str(resolved))
        except OSError:
            return None, str(resolved), {'reason': 'read_error', 'result_path': raw}
        return sha, str(resolved), {'reason': 'file_content_sha'}

    @_serialized_ledger_command
    def set_verdict(self, name: str, tag: str, v: VerdictIn) -> dict:
        verdict_payload = v.model_dump()
        try:
            verdict_payload_json = validate_history_record(
                name, 'verdict', tag, verdict_payload,
                'ob-verdict-preflight',
            )
        except HistoryPayloadError as exc:
            raise HTTPException(
                422, 'verdict history contains text PostgreSQL JSONB cannot represent'
            ) from exc
        # prom-honesty/3 (적대감사 2026-06-20): 결합 불변식의 핵심 게이트 — scripted 판결 수동 지정 시 403.
        #   회귀가드: tests/test_prom_honesty_node_gating.py::test_set_verdict_403_on_scripted_verdict.
        #   (노드-쓰기 우회는 prom-honesty/1 에서 validator 422 + writer by-construction 으로 차단.)
        if not is_admin_verdict(v.verdict):
            raise HTTPException(403, f'판결 어휘({v.verdict})는 test_result 스크립트 전용 — 수동 지정 금지. '
                                     f'행정 상태만: {sorted(ADMIN_VERDICTS)}')
        self._require_ledger_ready()
        self._project_pending_admin_predecessors(name, tag)

        def mint_admin_effect(
            *,
            effect_tag: str,
            effect_verdict: str,
            source: str,
            previous: str | None,
            judged_at: str,
            effect_summary: dict,
            history_preimage: dict,
        ) -> tuple[dict, dict]:
            fields = {key: None for key in RECEIPT_FIELDS}
            fields.update(
                tree=name,
                tag=effect_tag,
                verdict=effect_verdict,
                verdict_source=source,
                judged_at=judged_at,
                prev_receipt_sha=previous,
                engine_rule_sha=ENGINE_RULE_SHA,
                history_payload_sha256=verdict_history_payload_sha(
                    history_preimage
                ),
            )
            receipt_sha = receipt_content_sha(fields)
            effect = {
                **effect_summary,
                'receipt_sha': receipt_sha,
            }
            return effect, fields
        # A committed administrative receipt owns a deterministic outbox.  An
        # exact lost-ACK/history retry must be repaired before the budget gate;
        # otherwise an already-consumed budget can make recovery impossible.
        replay_rows = self.kg(
            """MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
               OPTIONAL MATCH (e)-[:HAS_RECEIPT]->(rec:VerdictReceipt {
                 receipt_sha:e.current_receipt_sha})
               OPTIONAL MATCH (o:OutboxEntry {
                 id:'ob-verdict-'+e.current_receipt_sha})
               OPTIONAL MATCH (t)-[:HAS_NODE]->(demoted {
                 tag:o.demoted_tag})-[:HAS_RECEIPT]->(demoted_rec:VerdictReceipt {
                 receipt_sha:o.demoted_receipt_sha})
               RETURN e.current_receipt_sha AS receipt_sha,
                      e.verdict AS current_verdict,
                      e.verdict_source AS current_verdict_source,
                      properties(rec) AS receipt,
                      properties(o) AS outbox,
                      CASE WHEN demoted IS NULL THEN null ELSE {
                        tag:demoted.tag,
                        current_receipt_sha:demoted.current_receipt_sha,
                        verdict:demoted.verdict,
                        verdict_source:demoted.verdict_source
                      } END AS demoted_current,
                      properties(demoted_rec) AS demoted_receipt""",
            tree=name,
            tag=tag,
        )
        if len(replay_rows or []) > 1:
            raise HTTPException(500, 'administrative replay cardinality conflict')
        if replay_rows:
            replay = replay_rows[0]
            receipt = replay.get('receipt') or {}
            outbox = replay.get('outbox')
            is_admin_v6 = (
                receipt.get('verdict_source') == 'admin'
                and receipt.get('history_payload_sha256') is not None
            )
            if outbox is not None:
                if not is_admin_v6:
                    raise HTTPException(
                        500,
                        'administrative outbox is attached to a non-admin V6 head',
                    )
                try:
                    committed_payload = validate_admin_verdict_intent(
                        tree=name,
                        tag=tag,
                        receipt_sha=replay.get('receipt_sha'),
                        receipt=receipt,
                        current={
                            'current_receipt_sha': replay.get('receipt_sha'),
                            'verdict': replay.get('current_verdict'),
                            'verdict_source': replay.get('current_verdict_source'),
                        },
                        outbox=outbox,
                        demoted_receipt=replay.get('demoted_receipt'),
                        demoted_current=replay.get('demoted_current'),
                    )
                except AdminIntentError as exc:
                    raise HTTPException(
                        500, f'administrative durable intent corrupt: {exc}'
                    ) from exc
                expected_event_id = f"ob-verdict-{replay.get('receipt_sha')}"
                projected = self.hist(
                    name, 'verdict', tag, committed_payload,
                    event_id=expected_event_id,
                )
                if committed_payload.get('request') == verdict_payload:
                    return {
                        'ok': True,
                        'idempotent': True,
                        'history_pending': projected is False,
                    }
                if projected is False:
                    raise HTTPException(
                        503,
                        'prior administrative verdict history is pending; head advancement deferred',
                    )
                # The prior immutable admin transition is fully projected.  A
                # different request is a legitimate successor, not a replay
                # conflict; continue through the ordinary FSM/CAS path.
            elif is_admin_v6:
                raise HTTPException(
                    500, 'V6 administrative receipt lacks its intent'
                )
        # ⓪ 루프-경계 예산(PROM16 S1/S5) — set_verdict 도 verdict + :VerdictReceipt 를 민팅해 scored_nodes
        #    를 늘릴 수 있는 verb 다(미채점 draft 에 행정 판결을 찍으면 새 소모 1). run_cycle 만 막던
        #    첫 구현의 우회 통로 중 하나 — 같은 게이트를 여기서도 지난다(cycle_budget SSOT).
        assert_scoring_budget(self.kg, name, 'set_verdict')
        if v.verdict == 'CANONICAL':
            # R4(후속 PROM): 승격도 원장에 산다 — 포인터/직전-canonical 스냅샷을 pre 에서 읽어 receipt 를
            #   Python 에서 내용주소로 선계산(prev 체인), write CAS 가 두 스냅샷을 재검증한다.
            pre = self.kg('''MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(cur {tag:$tag})
                        OPTIONAL MATCH (cur)-[:HAS_ARGUMENT]->(a:Argument)
                        WITH t, cur, collect({id:a.id, attacks:a.attacks, by:a.by, kind:a.kind}) AS args
                        OPTIONAL MATCH (t)-[:HAS_NODE]->(old {verdict:'CANONICAL'})
                        WHERE old.tag <> $tag
                        WITH t, cur, args,
                             [item IN collect({
                               tag:old.tag, prev:old.current_receipt_sha
                             }) WHERE item.tag IS NOT NULL] AS oldrecs
                        RETURN cur.verdict AS verdict,
                               cur.verdict_source AS verdict_source,
                               cur.node_state AS node_state,
                               cur.source_trust AS source_trust,
                               cur.novel_confirmed AS novel_confirmed,
                               cur.qualitative_self_report AS qualitative_self_report,
                               cur.author AS author,
                               t.assurance_tier AS assurance_tier,
                               t.attestor_dids AS attestor_dids,
                               cur.current_receipt_sha AS prev_receipt_sha,
                               oldrecs,
                               args AS args''',
                          tree=name, tag=tag)
            if not pre:
                raise HTTPException(404, f'노드 없음: {tag}')
            cand = pre[0]
            oldrecs = cand.get('oldrecs')
            if not isinstance(oldrecs, list):
                raise HTTPException(500, 'canonical incumbent snapshot is malformed')
            if len(oldrecs) > 1:
                raise HTTPException(
                    500,
                    'multiple CANONICAL incumbents detected; repair required before promotion',
                )
            # AG5-IDENT (측정주권 2026-07-03): 비가역 verb(CANONICAL 승격) 서명강제 + verb-바인딩 cert.
            #   dead-σ(FE5 open-but-observable): cert 강제는 트리가 attestor 를 선언(attestor_dids)했을 때만 —
            #   무-attestor 트리는 무인증 CANONICAL 유지(키 없는 배포 안 잠금). cert 명령이 verb 를 실어
            #   submit 용 cert 를 canonical 승격에 재생(sign-X-execute-Y)하지 못하게 봉인한다.
            tier = assurance.resolve_tier(cand.get('assurance_tier'))
            attestors = [str(d).strip() for d in (cand.get('attestor_dids') or []) if d and str(d).strip()]
            canonical_cert_required = (assurance.GATE_WRITE_CERT
                                       in assurance.gates_for('set_verdict_canonical', tier) and bool(attestors))
            if canonical_cert_required or v.write_cert is not None:
                if v.write_cert is None:
                    raise HTTPException(403, f'write-cert 필수 — attestor 선언 {tier} 트리의 CANONICAL 승격은 '
                                             f'서명 명령만 인정(allow-list {len(attestors)}명). 비가역 verb '
                                             f'서명강제(AG5-IDENT).')
                expected_command = dict(tree=name, tag=tag, prev_receipt_sha=cand.get('prev_receipt_sha'),
                                        metric_value=None, script_sha=None,
                                        verb='set_verdict_canonical', command_version='v4',
                                        operation_payload_sha256=operation_payload_sha256(
                                            'set_verdict_canonical',
                                            v.model_dump(exclude={'write_cert'})))
                try:
                    verify_write_cert(v.write_cert.model_dump(), expected_command=expected_command,
                                      allowlist=attestors if attestors else [v.write_cert.signer_did])
                except CertError as _ce:
                    raise HTTPException(403, f'write-cert 검증 실패(CANONICAL 승격, sign-X-execute-Y 봉인): '
                                             f'{type(_ce).__name__} — {_ce}')
            _require_state_transition(derive_node_state(cand), NodeState.CANONICAL)
            # #H5 (설계감사 2026-06-26): floor 판정의 스냅샷 지문 — verdict/source/qsr + 논증집합.
            #   write 가 이 지문을 원자 CAS 로 재검증해, read→write 사이 동시변경 시 0행 → 409(stale 승격 차단).
            snap_arg_fp = sorted(f"{a['id']}|{a.get('attacks') or ''}"
                                 for a in (cand.get('args') or []) if a.get('id'))
            # #H8 (설계감사 2026-06-26): floor 의 stands 도 actor-aware assemble_af 정본으로 — 인라인 AF
            #   조립(by 무시) 폐기. cand.args 가 이미 by 를 싣고 있어, 작성자가 자기 doubt 를 자기 rebuttal 로
            #   막아 CANONICAL floor 를 통과하던 self-vouch 가 여기서도 봉쇄된다(add_critique/standing 과 통일).
            arguments, attacks = assemble_af(tag, cand.get('args') or [])
            stands = f'verdict:{tag}' in grounded_extension(arguments, attacks)
            # #H2 (human-attestation): floor 의 has_human 은 client 1비트(v.human_verdict)가 *단독* 으로 못 연다.
            #   v.human_verdict 는 'KG 에서 그 human Argument 를 찾아라'는 *요청* 으로만 쓰고, 실제 영수증은
            #   *영속된* human attestation Argument 존재(kind∈{evaluation,verdict} AND by 사람 actor)로 판정.
            #   영수증 0 인 노드에 client True 만으론 CANONICAL floor 가 안 열린다(no_receipt_for_canonical).
            #   (Sybil 한계: by 가 노드 작성자와 다른지는 노드 author 가 KG 에 미식별이라 미강제 — 후속.)
            # FF3 (설계감사 2026-06-26): human attestation 의 actor(by)가 *노드 작성자(author)와 다를 때만* 인정 —
            #   작성자가 자기 노드에 자기 인장을 찍어 floor 를 여는 self-vouch 봉쇄(H2 의 'Sybil 한계: author 미식별'
            #   후속). author 미설정(legacy/익명)이면 by≠'' 로 기존 동작 보존(비파괴); 설정 시에만 by≠author 강제.
            #   ★Sybil 천장: author/by 둘 다 client 선언 — 한 actor 가 두 정체성을 쓰면 우회 가능(실 auth 전 한계).
            _author = (cand.get('author') or '').strip()
            has_human = bool(v.human_verdict) and any(
                _is_human_attestation_arg(a) and (a.get('by') or '').strip() != _author
                for a in (cand.get('args') or []))
            credibility = self._eigentrust_credibility(
                name, tag, novel_confirmed=bool(cand.get('novel_confirmed')),
                has_human_verdict=has_human)
            # G6 S4 (git-흡수): anchored tier 의 replay 승격 FLOOR — producer replay 가 *실행되어 실패*
            #   (False)했으면 CANONICAL 승격 차단. 재실행이 측정을 반증한 노드를 최강 주장으로 못 올린다.
            #   dead-σ 교정(관통위험 ④): LAKATOS_REPLAY_EXEC off 면 replay=None(검증 불가)로 *비차단* —
            #   floor 를 exec-트리거로 오설정하면 exec-OFF 배포가 anchored 승격 전부 409 lock 이 된다.
            #   (tier 는 위 AG5-IDENT cert 게이트에서 이미 resolve 됨 — 재계산 안 함.)
            replay_v = self.producer_replay_for_node(name, tag)
            if (assurance.GATE_REPLAY_FLOOR in assurance.gates_for('set_verdict_canonical', tier)
                    and replay_v is False):
                raise HTTPException(409, "CANONICAL 승격 차단(G6 anchored replay floor): producer replay "
                                         "가 실행되어 측정 재검증에 *실패*했다 — 재측정과 모순되는 노드는 "
                                         "최강 주장이 될 수 없다(재실험 또는 새 노드로 분기).")
            decision = synthesize_promotion(
                scripted_verdict=cand.get('verdict') or 'proof',
                verdict_source=cand.get('verdict_source'),   # SSOT floor: 레거시 NULL-source 는 영수증 아님
                stands=stands,
                foundation=self.foundation(name),
                credibility=credibility,
                reproducible=self.reproducible_for_node(name, tag),
                qualitative_self_report=bool(cand.get('qualitative_self_report')),   # #H1: 질적 self-report 표식 → 메트릭 단독 floor 차단
                producer_replay_verified=replay_v,   # 나생문 #1 live: 재실행 검증 → 세 번째 외부앵커(G6 floor 와 동일 관측 1회)
            )
            if not decision['ok']:
                raise HTTPException(409, f"CANONICAL 승격 차단(합성 엔진 게이트): {list(decision['reasons'])}. "
                                         f"게이트별: {decision['gates']}")
            # jp4 CA fail-closed: stale/무능력 판관은 CANONICAL 을 못 연다 — 하드 409. provisional
            #   CANONICAL 은 형용모순(최강 주장 + 임시 태그)이고 승격은 저빈도 운영 verb 라 루프 안 막음.
            _fresh = self.engine_freshness() if self.engine_freshness else None
            if engine_freshness_fires(_fresh):
                raise HTTPException(409, f"CANONICAL 승격 차단(jp4 CA fail-closed): 서빙 판관이 stale/무능력 — "
                                         f"boot_git_sha={(_fresh or {}).get('boot_git_sha')} "
                                         f"disk_head_sha={(_fresh or {}).get('disk_head_sha')} "
                                         f"missing={(_fresh or {}).get('missing')}. "
                                         f"scripts/dev_server_restart.sh 재기동 후 재시도.")
            # 나생문 #1: 측정 외부성(reproducible|human|producer-replay 검증)을 노드에 *persist* — floor 의
            #   honest-exposure 를 실제 관측가능하게(judge_receipt 단독 CANONICAL 은 anchored=False 로 보인다).
            floor_anchored = bool(decision['gates'].get('floor', {}).get('measurement_externally_anchored'))
            # #H5 원자 CAS: 스냅샷(verdict/source/qsr + 논증집합 지문)이 write 시점에도 동일할 때만 승격.
            #   동시 재채점(source 변경)·반박 critique(논증집합 변경)가 끼면 0행 → 409. (M5 의 submit 원자가드를
            #   verdict-승격 경로로 미러. 단 credibility/foundation/reproducible 등 광역 신뢰그래프 race 는
            #   지문 밖 — 노드 자체 verdict/source/qsr/논증까지만 낙관적 락; 광역은 후속.)
            # #M12: 직전 canonical 강등을 verdict_source='engine' 으로 귀속(다른 강등경로와 정합).
            # R4(후속 PROM): 승격·강등 모두 *같은 statement* 에서 v1 null-스펙 :VerdictReceipt 를 민팅하고
            #   포인터를 전진시킨다 — 측정 필드는 전부 null(측정영수증 위장 금지, null 이 정직), prev 링크가
            #   reflog 동형 복구영수증('(was <tag>)' = prev 한 칸 걷기). 포인터/old 스냅샷도 CAS 에 편입:
            #   pre-read 와 write 사이에 head 전진·canonical 교체가 끼면 0행 → 409(어차피 floor 재평가 대상).
            ts = datetime.now(timezone.utc).isoformat()
            prev_rsha = cand.get('prev_receipt_sha')
            old_tag = oldrecs[0]['tag'] if oldrecs else None
            old_prev = oldrecs[0].get('prev') if oldrecs else None
            demoted_effect = None
            demoted_fields = None
            if old_tag is not None:
                demoted_summary = {
                    'tag': old_tag,
                    'verdict': 'former_canonical',
                    'verdict_source': 'engine',
                    'prev_receipt_sha': old_prev,
                }
                demoted_effect, demoted_fields = mint_admin_effect(
                    effect_tag=old_tag,
                    effect_verdict='former_canonical',
                    source='engine',
                    previous=old_prev,
                    judged_at=ts,
                    effect_summary=demoted_summary,
                    history_preimage=demoted_summary,
                )
            promoted_summary = {
                'tag': tag,
                'verdict': 'CANONICAL',
                'verdict_source': 'admin',
                'prev_receipt_sha': prev_rsha,
            }
            promotion_preimage = {
                'request': verdict_payload,
                'promoted': promoted_summary,
                'demoted': demoted_effect,
            }
            promoted_effect, promoted_fields = mint_admin_effect(
                effect_tag=tag,
                effect_verdict='CANONICAL',
                source='admin',
                previous=prev_rsha,
                judged_at=ts,
                effect_summary=promoted_summary,
                history_preimage=promotion_preimage,
            )
            rsha = promoted_effect['receipt_sha']
            old_rsha = (
                demoted_effect['receipt_sha'] if demoted_effect is not None else None
            )
            history_event_id = f'ob-verdict-{rsha}'
            compound_payload = {
                'request': verdict_payload,
                'promoted': promoted_effect,
                'demoted': demoted_effect,
            }
            try:
                history_payload_json = validate_history_record(
                    name, 'verdict', tag, compound_payload, history_event_id
                )
            except HistoryPayloadError as exc:
                raise HTTPException(
                    422, 'administrative intent is not PostgreSQL JSONB-safe'
                ) from exc
            rows = self._ledger_write(('''MATCH (t:LakatosTree {name:$tree})
                  ''' + LOCKED_BUDGET_GUARD + '''
                  MATCH (t)-[:HAS_NODE]->(cur {tag:$tag})
                  SET cur._cas = coalesce(cur._cas,0) + 0
                  WITH t, cur
                  WHERE coalesce(cur.verdict,'') = coalesce($exp_verdict,'')
                    AND coalesce(cur.verdict_source,'') = coalesce($exp_source,'')
                    AND coalesce(cur.qualitative_self_report,false) = $exp_qsr
                    AND coalesce(cur.current_receipt_sha,'') = coalesce($prev_rsha,'')
                  WITH t, cur
                  OPTIONAL MATCH (cur)-[:HAS_ARGUMENT]->(a:Argument)
                  WITH t, cur, [x IN collect(a.id + '|' + coalesce(a.attacks,'')) WHERE x IS NOT NULL | x] AS arg_fp
                  WHERE size(arg_fp) = $exp_argn AND all(x IN arg_fp WHERE x IN $exp_arg_fp)
                  WITH t, cur
                  OPTIONAL MATCH (t)-[:HAS_NODE]->(old {verdict:'CANONICAL'})
                  WHERE old.tag <> $tag
                  WITH t, cur,
                       [candidate IN collect(old) WHERE candidate IS NOT NULL]
                         AS canonical_incumbents
                  WHERE size(canonical_incumbents) = CASE
                          WHEN $old_tag IS NULL THEN 0 ELSE 1 END
                    AND ($old_tag IS NULL OR (
                      canonical_incumbents[0].tag = $old_tag
                      AND coalesce(
                        canonical_incumbents[0].current_receipt_sha, '')
                        = coalesce($old_prev, '')))
                  WITH t, cur, head(canonical_incumbents) AS old
                  OPTIONAL MATCH (prior_history:OutboxEntry {id:$history_event_id})
                  WITH t, cur, old, count(prior_history) AS prior_history_count
                  WHERE prior_history_count=0
                  FOREACH (_ IN CASE WHEN old IS NOT NULL THEN [1] ELSE [] END |
                      SET old.verdict='former_canonical', old.verdict_source='engine',
                          old.current_best_pointer=false, old.node_state=$former_state,
                          old.demoted_at=$ts, old.current_receipt_sha=$old_rsha
                      MERGE (orec:VerdictReceipt {receipt_sha:$old_rsha})
                        ON CREATE SET orec.tree=$tree, orec.tag=$old_tag,
                          orec.verdict='former_canonical', orec.verdict_source='engine',
                          orec.judged_at=$ts, orec.prev_receipt_sha=$old_prev,
                          orec.engine_rule_sha=$engine_rule_sha,
                          orec.history_payload_sha256=$old_history_payload_sha256
                      MERGE (old)-[:HAS_RECEIPT]->(orec)
                  )
                  SET cur.verdict='CANONICAL', cur.verdict_source='admin',
                      cur.node_state=$canonical_state,
                      cur.current_best_pointer=true,
                      cur.canonical_scope=$scope,
                      cur.canonical_assumptions=$assumptions,
                      cur.canonical_evidence_window=$evidence_window,
                      cur.valid_until_rebutted=$valid_until_rebutted,
                      cur.measurement_externally_anchored=$mea
                  MERGE (rec:VerdictReceipt {receipt_sha:$rsha})
                    ON CREATE SET rec.tree=$tree, rec.tag=$tag, rec.verdict='CANONICAL',
                      rec.verdict_source='admin', rec.judged_at=$ts, rec.prev_receipt_sha=$prev_rsha,
                      rec.engine_rule_sha=$engine_rule_sha,
                      rec.history_payload_sha256=$history_payload_sha256
                  MERGE (cur)-[:HAS_RECEIPT]->(rec)
                  SET cur.current_receipt_sha=$rsha
                  CREATE (:OutboxEntry {
                    id:$history_event_id, tree:$tree, op:'verdict',
                    node_tag:$tag, payload:$history_payload_json,
                    status:'pending', created_at:$ts,
                    reason:'verdict_commit_intent', receipt_sha:$rsha,
                    demoted_tag:$old_tag, demoted_receipt_sha:$old_rsha
                  })
                  RETURN cur.tag AS tag'''),
                    tree=name, tag=tag,
                    exp_verdict=cand.get('verdict'), exp_source=cand.get('verdict_source'),
                    exp_qsr=bool(cand.get('qualitative_self_report')),
                    exp_argn=len(snap_arg_fp), exp_arg_fp=snap_arg_fp,
                    former_state=NodeState.FORMER_CANONICAL.value,
                    canonical_state=NodeState.CANONICAL.value,
                    scope=v.scope, assumptions=v.assumptions,
                    evidence_window=v.evidence_window, valid_until_rebutted=v.valid_until_rebutted,
                    mea=floor_anchored,
                    ts=ts, prev_rsha=prev_rsha, rsha=rsha,
                    old_tag=old_tag, old_prev=old_prev, old_rsha=old_rsha,
                    history_event_id=history_event_id,
                    history_payload_json=history_payload_json,
                    history_payload_sha256=promoted_fields[
                        'history_payload_sha256'
                    ],
                    old_history_payload_sha256=(
                        demoted_fields['history_payload_sha256']
                        if demoted_fields is not None else None
                    ),
                    forceful=sorted(FORCEFUL_SOURCES),
                    engine_rule_sha=ENGINE_RULE_SHA)
            if not rows:   # 원자 CAS 0행 = read→write 사이 스냅샷 변경(동시 승격/재채점/반박/head 전진) → 차단
                raise_after_locked_budget_rejection(
                    self.kg, name, 'set_verdict'
                )
                raise HTTPException(409, '동시변경 감지(CANONICAL 원자 CAS 0행) — floor 판정 스냅샷'
                                         '(verdict/source/qsr/논증집합/영수증 포인터/직전 canonical)이 승격 직전 '
                                         '변해 무효. 최신상태 재평가 필요.')
        else:
            state_rows = self.kg('''MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                       RETURN e.verdict AS verdict, e.verdict_source AS verdict_source,
                              e.node_state AS node_state, e.pred_registered_at AS pred_registered_at,
                              e.judged_at AS judged_at, e.metric_value AS metric_value,
                              e.current_receipt_sha AS prev_receipt_sha''',
                                 tree=name, tag=tag)
            if not state_rows:
                raise HTTPException(404, f'노드 없음: {tag}')
            next_state = derive_node_state({'verdict': v.verdict, 'verdict_source': 'admin'})
            _require_state_transition(derive_node_state(state_rows[0]), next_state)
            # R4(후속 PROM): 행정 verdict 이동도 원장에 산다 — v1 null-스펙 receipt + 포인터 전진,
            #   mini-CAS(verdict/포인터 스냅샷)로 read→write race 는 0행 → 409.
            ts = datetime.now(timezone.utc).isoformat()
            prev_rsha = state_rows[0].get('prev_receipt_sha')
            promoted_summary = {
                'tag': tag,
                'verdict': v.verdict,
                'verdict_source': 'admin',
                'prev_receipt_sha': prev_rsha,
            }
            promotion_preimage = {
                'request': verdict_payload,
                'promoted': promoted_summary,
                'demoted': None,
            }
            promoted_effect, promoted_fields = mint_admin_effect(
                effect_tag=tag,
                effect_verdict=v.verdict,
                source='admin',
                previous=prev_rsha,
                judged_at=ts,
                effect_summary=promoted_summary,
                history_preimage=promotion_preimage,
            )
            rsha = promoted_effect['receipt_sha']
            history_event_id = f'ob-verdict-{rsha}'
            compound_payload = {
                'request': verdict_payload,
                'promoted': promoted_effect,
                'demoted': None,
            }
            try:
                history_payload_json = validate_history_record(
                    name, 'verdict', tag, compound_payload, history_event_id
                )
            except HistoryPayloadError as exc:
                raise HTTPException(
                    422, 'administrative intent is not PostgreSQL JSONB-safe'
                ) from exc
            rows = self._ledger_write(('''MATCH (t:LakatosTree {name:$tree})
                      ''' + LOCKED_BUDGET_GUARD + '''
                      MATCH (t)-[:HAS_NODE]->(e {tag:$tag})
                      WHERE coalesce(e.verdict,'') = coalesce($exp_verdict,'')
                        AND coalesce(e.current_receipt_sha,'') = coalesce($prev_rsha,'')
                      WITH e
                      OPTIONAL MATCH (prior_history:OutboxEntry {id:$history_event_id})
                      WITH e, count(prior_history) AS prior_history_count
                      WHERE prior_history_count=0
                      SET e.verdict=$verdict, e.verdict_source='admin', e.node_state=$node_state
                      MERGE (rec:VerdictReceipt {receipt_sha:$rsha})
                        ON CREATE SET rec.tree=$tree, rec.tag=$tag, rec.verdict=$verdict,
                          rec.verdict_source='admin', rec.judged_at=$ts, rec.prev_receipt_sha=$prev_rsha,
                          rec.engine_rule_sha=$engine_rule_sha,
                          rec.history_payload_sha256=$history_payload_sha256
                      MERGE (e)-[:HAS_RECEIPT]->(rec)
                      SET e.current_receipt_sha=$rsha
                      CREATE (:OutboxEntry {
                        id:$history_event_id, tree:$tree, op:'verdict',
                        node_tag:$tag, payload:$history_payload_json,
                        status:'pending', created_at:$ts,
                        reason:'verdict_commit_intent', receipt_sha:$rsha,
                        demoted_tag:null, demoted_receipt_sha:null
                      })
                      RETURN e.tag AS tag'''),
                           tree=name, tag=tag, verdict=v.verdict,
                           node_state=next_state.value,
                           exp_verdict=state_rows[0].get('verdict'),
                           prev_rsha=prev_rsha, rsha=rsha, ts=ts,
                           history_event_id=history_event_id,
                           history_payload_json=history_payload_json,
                           history_payload_sha256=promoted_fields[
                               'history_payload_sha256'
                           ],
                           forceful=sorted(FORCEFUL_SOURCES),
                           engine_rule_sha=ENGINE_RULE_SHA)
            if not rows:   # mini-CAS 0행 = read→write 사이 동시변경(재채점/head 전진) → stale 이동 차단
                raise_after_locked_budget_rejection(
                    self.kg, name, 'set_verdict'
                )
                raise HTTPException(409, '동시변경 감지(행정 verdict mini-CAS 0행) — 최신상태 재평가 필요.')
        if not rows:
            raise HTTPException(404, f'노드 없음: {tag}')
        projected = self.hist(
            name, 'verdict', tag, compound_payload,
            event_id=history_event_id,
        )
        return {
            'ok': True,
            'idempotent': False,
            'history_pending': projected is False,
        }

    def node_eureka(self, name: str, tag: str) -> dict:
        """A1: 노드별 measurement-grade eureka 읽기 — 판결 seam(submit_test_result)이 같은 kg_tx 로
        영속한 felt/true/hallucinated/reasons/bf. standing(promotion)은 별도 상위 층이라 제외
        (seam 이 require_promotion=False 로 산출). 미채점 노드는 judged=False."""
        rows = self.kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                     RETURN e.tag AS tag, e.verdict AS verdict, e.eureka_felt AS felt,
                            e.eureka_true AS true, e.eureka_hallucinated AS hallucinated,
                            e.eureka_reasons AS reasons, e.eureka_bf AS bf""", tree=name, tag=tag)
        if not rows:
            raise HTTPException(404, f'노드 없음: {tag}')
        x = rows[0]
        if x.get('felt') is None:
            return dict(tag=tag, judged=False, felt=False, true=False, hallucinated=False,
                        reasons=[], note='스크립트 채점 전 — eureka 는 test_result 판결 seam 에서 산출됨')
        return dict(tag=tag, judged=True, verdict=x.get('verdict'), felt=bool(x['felt']),
                    true=bool(x['true']), hallucinated=bool(x['hallucinated']), bf=x.get('bf'),
                    reasons=list(x.get('reasons') or []),
                    note='measurement-grade: felt=novel 등록, true=확증+substantial BF+순문제폐쇄. standing 은 별도 층')

    def _baseline_lineage(self, name: str, tag: str, p: PredictionIn) -> str:
        """R12(ManifestoGap S1): 예측 baseline 을 부모의 서버-persist measured 에 앵커.
        anchored=부모 measured 와 |Δ|≤noise_band · unanchored=벗어남(전략적 부풀림 노출) ·
        no_prior=부모 measured 없음(콜드스타트 명시). 비파괴 마크(강제 아님) + fail-safe(조회 실패=no_prior)."""
        try:
            rows = self.kg(
                "MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})-[:BRANCHED_FROM]->(par) "
                "WHERE par.metric_value IS NOT NULL "
                "RETURN par.metric_value AS parent_measured ORDER BY par.judged_at DESC LIMIT 1",
                tree=name, tag=tag)
        except Exception:
            return "no_prior"
        if not rows or rows[0].get("parent_measured") is None:
            return "no_prior"
        pm = float(rows[0]["parent_measured"])
        return "anchored" if abs(float(p.baseline_value) - pm) <= float(p.noise_band or 0.0) else "unanchored"

    @_serialized_ledger_command
    def register_prediction(self, name: str, tag: str, p: PredictionIn) -> dict:
        spec = p.model_dump()
        try:
            # Reject PostgreSQL-hostile tree/tag/payload text before storage
            # authority is consulted or any Neo4j read/repair can occur.
            history_payload_json = validate_history_record(
                name, 'prediction_register', tag, spec,
                'ob-prediction-register-preflight',
            )
        except HistoryPayloadError as exc:
            raise HTTPException(
                422, 'prediction history contains text PostgreSQL JSONB cannot represent'
            ) from exc
        prediction_payload_sha256 = prediction_history_payload_sha(spec)
        self._require_ledger_ready()
        self._project_pending_admin_predecessors(name, tag)
        # Read the actual ledger tip before certificate verification.  The same value is signed,
        # sealed into the PredictionReceipt, and CAS-checked by the write below.
        def _prediction_head():
            return self.kg(
                """MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                  OPTIONAL MATCH (e)-[:HAS_RECEIPT]->(pr:VerdictReceipt {
                    receipt_sha:e.pred_receipt_sha})
                  OPTIONAL MATCH (po:OutboxEntry {
                    id:'ob-prediction-register-'+e.pred_receipt_sha})
                  RETURN e.current_receipt_sha AS prev_rsha,
                         e.pred_receipt_sha AS pred_receipt_sha,
                         pr.registered_at AS pred_registered_at,
                         pr.prev_receipt_sha AS pred_prev_receipt_sha,
                         pr.baseline_lineage AS pred_baseline_lineage,
                         pr.anchor_bundle_sha256 AS pred_anchor_bundle_sha256,
                         pr.anchor_bundle_json AS pred_anchor_bundle_json,
                         pr.history_payload_sha256 AS pred_history_payload_sha256,
                         po.payload AS pred_history_payload,
                         e.pred_anchor_verified AS pred_anchor_verified,
                         e.pred_anchor_gen_time AS pred_anchor_gen_time,
                         e.pred_anchor_quorum AS pred_anchor_quorum,
                         e.pred_anchor_threshold AS pred_anchor_threshold""",
                tree=name,
                tag=tag,
            )

        head_rows = _prediction_head()
        if not head_rows:
            raise HTTPException(404, f'노드 없음: {tag}')
        prev_rsha = head_rows[0].get('prev_rsha')
        existing_pred_sha = head_rows[0].get('pred_receipt_sha')
        history_payload_json = ''
        anchors: list = []
        witnesses: list[str] = []
        anchor_rows: list[dict] = []
        anchor_bundle_json: str | None = None
        anchor_bundle_sha256: str | None = None
        anchor_quorum = 0
        threshold = 1
        sdg = gt = None
        retry_snapshot: dict | None = None
        idempotent_retry = False
        if existing_pred_sha:
            retry_snapshot = head_rows[0]
            retry_fields = dict(
                receipt_kind='prediction', tree=name, tag=tag,
                baseline_lineage=head_rows[0].get('pred_baseline_lineage'),
                registered_at=head_rows[0].get('pred_registered_at'),
                prev_receipt_sha=head_rows[0].get('pred_prev_receipt_sha'),
                anchor_bundle_sha256=head_rows[0].get(
                    'pred_anchor_bundle_sha256'
                ),
                history_payload_sha256=head_rows[0].get(
                    'pred_history_payload_sha256'
                ),
                **spec,
            )
            if prediction_content_sha(retry_fields) == existing_pred_sha:
                # The receipt is the first durable point, not the end of the
                # workflow.  Continue through idempotent anchor/history repair
                # so a crash immediately after minting cannot strand the node.
                idempotent_retry = True
                rsha = existing_pred_sha
                prediction_event_id = f'ob-prediction-register-{rsha}'
                ts = head_rows[0].get('pred_registered_at')
                baseline_lineage = head_rows[0].get('pred_baseline_lineage')
                anchor_verified_response = bool(
                    head_rows[0].get('pred_anchor_verified')
                )
                anchor_bundle_sha256 = head_rows[0].get(
                    'pred_anchor_bundle_sha256'
                )
                anchor_bundle_json = head_rows[0].get(
                    'pred_anchor_bundle_json'
                )
            else:
                raise HTTPException(
                    409,
                    '이미 다른 예측/후속 영수증이 있는 노드 — exact prediction retry만 허용',
                )
        else:
            meta = self.kg("""MATCH (t:LakatosTree {name:$n})
                      RETURN t.ontology AS ontology, t.research_layout AS research_layout,
                             t.layout_owner_did AS layout_owner_did, t.layout_sig AS layout_sig,
                             t.witness_dids AS witness_dids,
                             t.witness_threshold AS witness_threshold""", n=name)
            m0 = meta[0] if meta else {}
            onto = DomainOntology.from_json(m0.get("ontology")) if meta else None
            _rl = resolve_role_layout(m0)
            _predict_keys = (
                layout_mod.pubkeys_for_verb(_rl, 'register_prediction')
                if _rl else None
            )
            if _predict_keys is not None:
                if p.write_cert is None:
                    raise HTTPException(
                        403, 'write-cert 필수 — layout 이 register_prediction 역할을 선언한 '
                        '트리의 예측등록은 서명 명령만 인정(무서명 예측 봉합, S6b)'
                    )
                _dv = layout_mod.disjoint_violation(
                    _rl, p.write_cert.signer_did, 'register_prediction'
                )
                if _dv:
                    raise HTTPException(403, f'역할분리 위반: {_dv}')
                _expected = dict(
                    tree=name, tag=tag, prev_receipt_sha=prev_rsha,
                    metric_value=None, script_sha=p.judge_script_sha,
                    verb='register_prediction', command_version='v4',
                    operation_payload_sha256=operation_payload_sha256(
                        'register_prediction', p.model_dump(exclude={'write_cert'})
                    ),
                )
                try:
                    verify_write_cert(
                        p.write_cert.model_dump(), expected_command=_expected,
                        allowlist=_predict_keys,
                    )
                except CertSignerNotAllowed as e:
                    raise HTTPException(403, str(e))
                except CertError as e:
                    raise HTTPException(422, str(e))
            baseline_lineage = self._baseline_lineage(name, tag, p)
            if onto is not None:
                viols = (
                    onto.metric_violations(p.metric_name, p.direction)
                    + onto.metric_violations(p.novel_metric, p.novel_direction)
                )
                if viols:
                    raise HTTPException(422, f"metric 온톨로지 위반: {viols}")
            ts = datetime.now(timezone.utc).isoformat()
            pred_receipt_fields = dict(
                receipt_kind='prediction', tree=name, tag=tag,
                baseline_lineage=baseline_lineage, registered_at=ts,
                prev_receipt_sha=prev_rsha,
                history_payload_sha256=prediction_payload_sha256,
                **spec,
            )
            rsha = prediction_content_sha(pred_receipt_fields)
            prediction_event_id = f'ob-prediction-register-{rsha}'
            raw_witnesses = m0.get('witness_dids')
            if raw_witnesses is not None and not isinstance(
                raw_witnesses, list
            ):
                raise HTTPException(500, 'tree witness policy is corrupt')
            witnesses = [
                str(d).strip() for d in (raw_witnesses or [])
                if isinstance(d, str) and d.strip()
            ]
            anchors = effective_prediction_anchors(spec)
            raw_threshold = m0.get('witness_threshold')
            if raw_threshold is None:
                threshold = 1
            elif type(raw_threshold) is int and raw_threshold >= 1:
                threshold = raw_threshold
            else:
                raise HTTPException(500, 'tree witness threshold is corrupt')
            if anchors and not witnesses:
                raise HTTPException(
                    422,
                    'temporal anchors require a non-empty sealed witness policy',
                )
            sdg = temporal_mod.spec_digest({
                k: v for k, v in spec.items()
                if k not in ('write_cert', 'temporal_anchor', 'temporal_anchors')
            })
            if anchors:
                try:
                    gt = temporal_mod.verify_temporal_quorum(
                        anchors, expect_receipt_sha=sdg,
                        witness_allowlist=witnesses, threshold=threshold,
                    )
                except temporal_mod.AnchorInvalid as e:
                    raise HTTPException(422, f'temporal 정족수 무효: {e}')
            anchor_bundle = {
                'schema': 'lakatotree-prediction-anchor-bundle/v1',
                'spec_digest': sdg,
                'witness_dids': witnesses,
                'witness_threshold': threshold,
                'anchors': anchors,
            }
            anchor_bundle_json = canonical_history_payload(anchor_bundle)
            anchor_bundle_sha256 = hashlib.sha256(
                anchor_bundle_json.encode('utf-8')
            ).hexdigest()
            if anchors and witnesses:
                adg = temporal_mod.anchor_digest(sdg)
                anchor_rows = [
                    {
                        'digest': adg,
                        'witness_did': a.get('witness_did'),
                        'gen_time': a.get('gen_time'),
                        'channel': a.get('channel'),
                        'signature': a.get('signature'),
                    }
                    for a in anchors
                    if temporal_mod._safe_verify(a, sdg, witnesses)
                ]
                for row in anchor_rows:
                    row['id'] = 'ta-' + hashlib.sha256(
                        canonical_history_payload(row).encode('utf-8')
                    ).hexdigest()
                anchor_quorum = len({
                    str(row['witness_did']).strip() for row in anchor_rows
                })
            anchor_verified_response = bool(
                anchor_rows and anchor_quorum >= threshold
            )
            pred_receipt_fields['anchor_bundle_sha256'] = anchor_bundle_sha256
            rsha = prediction_content_sha(pred_receipt_fields)
            prediction_event_id = f'ob-prediction-register-{rsha}'
        # The preflight canonical text is independent of the event id.  Re-run
        # the validator against the final content-addressed identity so future
        # event-id-sensitive validation cannot silently bypass this binding.
        try:
            history_payload_json = validate_history_record(
                name, 'prediction_register', tag, spec, prediction_event_id,
            )
        except HistoryPayloadError as exc:
            raise HTTPException(
                422, 'prediction history contains text PostgreSQL JSONB cannot represent'
            ) from exc
        if idempotent_retry:
            if (
                retry_snapshot is None
                or retry_snapshot.get('pred_history_payload') != history_payload_json
            ):
                raise HTTPException(
                    409,
                    'prediction receipt와 durable request가 다름 — exact retry만 허용',
                )
            if anchor_bundle_sha256 is not None:
                if not isinstance(anchor_bundle_json, str):
                    raise HTTPException(500, 'prediction anchor bundle is missing')
                try:
                    anchor_bundle = json.loads(anchor_bundle_json)
                    canonical_bundle = canonical_history_payload(anchor_bundle)
                except (json.JSONDecodeError, HistoryPayloadError, TypeError) as exc:
                    raise HTTPException(500, 'prediction anchor bundle is corrupt') from exc
                if (
                    canonical_bundle != anchor_bundle_json
                    or hashlib.sha256(anchor_bundle_json.encode('utf-8')).hexdigest()
                        != anchor_bundle_sha256
                    or not isinstance(anchor_bundle, dict)
                    or set(anchor_bundle) != {
                        'schema', 'spec_digest', 'witness_dids',
                        'witness_threshold', 'anchors',
                    }
                    or anchor_bundle.get('schema')
                        != 'lakatotree-prediction-anchor-bundle/v1'
                    or not isinstance(anchor_bundle.get('spec_digest'), str)
                    or not isinstance(anchor_bundle.get('witness_dids'), list)
                    or not all(
                        isinstance(item, str) and item
                        for item in anchor_bundle['witness_dids']
                    )
                    or type(anchor_bundle.get('witness_threshold')) is not int
                    or anchor_bundle['witness_threshold'] < 1
                    or not isinstance(anchor_bundle.get('anchors'), list)
                    or not all(isinstance(item, dict) for item in anchor_bundle['anchors'])
                ):
                    raise HTTPException(500, 'prediction anchor bundle is corrupt')
                candidate_sdg = temporal_mod.spec_digest({
                    k: v for k, v in spec.items()
                    if k not in ('write_cert', 'temporal_anchor', 'temporal_anchors')
                })
                if anchor_bundle['spec_digest'] != candidate_sdg:
                    raise HTTPException(409, 'prediction anchor bundle is not this request')
                anchors = list(anchor_bundle['anchors'])
                witnesses = list(anchor_bundle['witness_dids'])
                threshold = anchor_bundle['witness_threshold']
                sdg = anchor_bundle['spec_digest']
                if anchors:
                    try:
                        gt = temporal_mod.verify_temporal_quorum(
                            anchors,
                            expect_receipt_sha=sdg,
                            witness_allowlist=witnesses,
                            threshold=threshold,
                        )
                    except temporal_mod.AnchorInvalid as exc:
                        raise HTTPException(
                            500, 'sealed prediction anchor bundle no longer verifies'
                        ) from exc
                    adg = temporal_mod.anchor_digest(sdg)
                    anchor_rows = [
                        {
                            'digest': adg,
                            'witness_did': a.get('witness_did'),
                            'gen_time': a.get('gen_time'),
                            'channel': a.get('channel'),
                            'signature': a.get('signature'),
                        }
                        for a in anchors
                        if temporal_mod._safe_verify(a, sdg, witnesses)
                    ]
                    for row in anchor_rows:
                        row['id'] = 'ta-' + hashlib.sha256(
                            canonical_history_payload(row).encode('utf-8')
                        ).hexdigest()
                    anchor_quorum = len({
                        str(row['witness_did']).strip() for row in anchor_rows
                    })
                anchor_verified_response = bool(
                    anchor_rows and anchor_quorum >= threshold
                )
        if not idempotent_retry:
            rows = self._ledger_write("""MATCH (t:LakatosTree {name:$tree})
                  SET t._tree_write_cas=coalesce(t._tree_write_cas,0)+0
                  WITH t
                  MATCH (t)-[:HAS_NODE]->(e {tag:$tag})
                  SET e._tree_write_cas=coalesce(e._tree_write_cas,0)+0
                  WITH t, e
                  OPTIONAL MATCH (t)-[:HAS_FRONTIER]->(q:OpenQuestion {name:$closes_question})
                  WITH e, q
                  FOREACH (_ IN CASE WHEN q IS NULL THEN [] ELSE [1] END |
                    SET q._cas=coalesce(q._cas, 0) + 0)
                  WITH e, q,
                    CASE WHEN q IS NULL THEN null
                         ELSE coalesce(q.status, '__MISSING__') END AS question_state
                  OPTIONAL MATCH (prior_outbox:OutboxEntry {id:$history_event_id})
                  WITH e, q, question_state,
                       [o IN collect(prior_outbox) WHERE o IS NOT NULL] AS prior_outboxes
                  WITH e, q, question_state, prior_outboxes,
                    CASE
                      WHEN size(prior_outboxes)=0 THEN true
                      WHEN size(prior_outboxes)=1 THEN coalesce(
                        prior_outboxes[0].tree=$tree
                        AND prior_outboxes[0].op='prediction_register'
                        AND prior_outboxes[0].node_tag=$tag
                        AND prior_outboxes[0].payload=$history_payload_json
                        AND prior_outboxes[0].reason='prediction_register_commit_intent'
                        AND prior_outboxes[0].receipt_sha=$rsha
                        AND prior_outboxes[0].created_at IS NOT NULL
                        AND prior_outboxes[0].adopted_by IS NULL
                        AND prior_outboxes[0].adopted_at IS NULL
                        AND prior_outboxes[0].causal_group IS NULL
                        AND prior_outboxes[0].causal_index IS NULL
                        AND prior_outboxes[0].request_sha256 IS NULL
                        AND prior_outboxes[0].demoted_tag IS NULL
                        AND prior_outboxes[0].demoted_receipt_sha IS NULL
                        AND ((prior_outboxes[0].status='pending'
                              AND prior_outboxes[0].applied_at IS NULL)
                             OR (prior_outboxes[0].status='applied'
                                 AND prior_outboxes[0].applied_at IS NOT NULL)),
                        false)
                      ELSE false
                    END AS intent_prevalid
                  WHERE (e.verdict_source IS NULL OR e.verdict_source <> 'scripted')
                        AND e.pred_registered_at IS NULL
                        AND coalesce(e.node_state, 'DRAFT') IN $allowed_from
                        AND coalesce(e.current_receipt_sha,'') = coalesce($prev_rsha,'')
                        AND ($closes_question = '' OR question_state = $open_state)
                        AND intent_prevalid
                  SET e.pred_metric=$metric_name, e.pred_direction=$direction,
                      e.pred_baseline=$baseline_value, e.pred_noise_band=$noise_band,
                      e.pred_scale_type=$scale_type,
                      e.pred_novel=$novel_prediction, e.pred_closes=$closes_question,
                      e.pred_novel_metric=$novel_metric, e.pred_novel_direction=$novel_direction,
                      e.pred_novel_threshold=$novel_threshold, e.pred_script_sha=$judge_script_sha,
                      e.pred_credence=$credence,
                      e.novel_registered = ($novel_metric IS NOT NULL),
                      e.pred_registered_at=$ts,
                      e.node_state=$node_state,
                      e.baseline_lineage=$baseline_lineage,
                      e.pred_question_bound=($closes_question = '' OR q IS NOT NULL)
                  FOREACH (_ IN CASE WHEN $closes_question = '' THEN [] ELSE [1] END |
                    SET q.n_visits=coalesce(q.n_visits, 0) + 1)
                  WITH e
                  MERGE (rec:VerdictReceipt {receipt_sha:$rsha})
                    ON CREATE SET rec.receipt_kind='prediction', rec.tree=$tree, rec.tag=$tag,
                      rec.metric_name=$metric_name, rec.direction=$direction,
                      rec.baseline_value=$baseline_value, rec.noise_band=$noise_band,
                      rec.scale_type=$scale_type, rec.novel_prediction=$novel_prediction,
                      rec.novel_metric=$novel_metric, rec.novel_direction=$novel_direction,
                      rec.novel_threshold=$novel_threshold, rec.judge_script_sha=$judge_script_sha,
                      rec.closes_question=$closes_question, rec.credence=$credence,
                      rec.baseline_lineage=$baseline_lineage, rec.registered_at=$ts,
                      rec.prev_receipt_sha=$prev_rsha,
                      rec.anchor_bundle_sha256=$anchor_bundle_sha256,
                      rec.anchor_bundle_json=$anchor_bundle_json,
                      rec.history_payload_sha256=$prediction_payload_sha256
                  MERGE (e)-[:HAS_RECEIPT]->(rec)
                  SET e.current_receipt_sha=$rsha, e.pred_receipt_sha=$rsha
                  FOREACH (anchor IN $anchor_rows |
                    MERGE (an:TemporalAnchor {id:anchor.id})
                    ON CREATE SET an.digest=anchor.digest,
                                  an.witness_did=anchor.witness_did,
                                  an.gen_time=anchor.gen_time,
                                  an.channel=anchor.channel,
                                  an.signature=anchor.signature,
                                  an.kind='prediction'
                    MERGE (e)-[:PRED_ANCHORED_BY]->(an))
                  FOREACH (_ IN CASE WHEN size($anchor_rows)>0 THEN [1] ELSE [] END |
                    SET e.pred_anchor_verified=true,
                        e.pred_anchor_gen_time=$anchor_gen_time,
                        e.pred_anchor_quorum=$anchor_quorum,
                        e.pred_anchor_threshold=$anchor_threshold)
                  REMOVE e._cycle_created_by, e._cycle_claimed_at
                  MERGE (o:OutboxEntry {id:$history_event_id})
                    ON CREATE SET o.tree=$tree, o.op='prediction_register',
                                  o.node_tag=$tag, o.payload=$history_payload_json,
                                  o.status='pending', o.created_at=$ts,
                                  o.reason='prediction_register_commit_intent',
                                  o.receipt_sha=$rsha
                  WITH e, o
                  WHERE o.tree=$tree AND o.op='prediction_register'
                    AND o.node_tag=$tag AND o.payload=$history_payload_json
                    AND o.reason='prediction_register_commit_intent'
                    AND o.receipt_sha=$rsha
                    AND o.created_at IS NOT NULL
                    AND o.adopted_by IS NULL AND o.adopted_at IS NULL
                    AND o.causal_group IS NULL AND o.causal_index IS NULL
                    AND o.request_sha256 IS NULL
                    AND o.demoted_tag IS NULL
                    AND o.demoted_receipt_sha IS NULL
                    AND ((o.status='pending' AND o.applied_at IS NULL)
                         OR (o.status='applied' AND o.applied_at IS NOT NULL))
                  RETURN e.tag AS tag""",
                       tree=name, tag=tag, ts=ts,
                       node_state=NodeState.PREDICTED.value,
                       open_state='OPEN',
                       baseline_lineage=baseline_lineage,   # R12: 계보 앵커 마크(비파괴)
                       allowed_from=[NodeState.DRAFT.value, NodeState.ADMINISTRATIVE.value],
                       rsha=rsha, prev_rsha=prev_rsha,
                       history_event_id=prediction_event_id,
                       history_payload_json=history_payload_json,
                       prediction_payload_sha256=prediction_payload_sha256,
                       anchor_bundle_sha256=anchor_bundle_sha256,
                       anchor_bundle_json=anchor_bundle_json,
                       anchor_rows=anchor_rows,
                       anchor_gen_time=gt,
                       anchor_quorum=anchor_quorum,
                       anchor_threshold=threshold,
                       **spec)
            if not rows:
                # A concurrent identical registration can win after our head
                # read but before this CAS.  Re-read the immutable prediction
                # receipt and adopt it only when its complete content hashes to
                # the stored pointer.  This closes the prediction-stage false
                # 409 without admitting a different prediction or question.
                latest_rows = _prediction_head()
                latest = latest_rows[0] if len(latest_rows) == 1 else {}
                latest_sha = latest.get('pred_receipt_sha')
                retry_fields = dict(
                    receipt_kind='prediction',
                    tree=name,
                    tag=tag,
                    baseline_lineage=latest.get('pred_baseline_lineage'),
                    registered_at=latest.get('pred_registered_at'),
                    prev_receipt_sha=latest.get('pred_prev_receipt_sha'),
                    anchor_bundle_sha256=latest.get(
                        'pred_anchor_bundle_sha256'
                    ),
                    history_payload_sha256=latest.get(
                        'pred_history_payload_sha256'
                    ),
                    **spec,
                )
                if latest_sha and prediction_content_sha(retry_fields) == latest_sha:
                    # Re-enter through the ordinary exact-retry branch.  It
                    # validates the winner's immutable outbox and sealed
                    # anchor bundle before projecting history.
                    return self.register_prediction(name, tag, p)
                else:
                    raise HTTPException(
                        409,
                        '노드 없음/이미 채점됨 또는 closes_question 이 이 트리의 OPEN 질문이 아님 '
                        '— 사후 예측등록·유령 질문 target 금지',
                    )
        # Fresh registrations persist anchors in the receipt/outbox statement
        # above.  An exact retry may repair a v3 receipt written by an older
        # process only from its sealed anchor bundle and exact durable request.
        if (
            idempotent_retry
            and anchor_rows
            and not bool(retry_snapshot and retry_snapshot.get('pred_anchor_verified'))
        ):
            repaired = self._ledger_write(
                """MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                   MATCH (e)-[:HAS_RECEIPT]->(rec:VerdictReceipt {
                     receipt_sha:$rsha})
                   MATCH (o:OutboxEntry {id:$history_event_id})
                   WHERE e.pred_receipt_sha=$rsha
                     AND rec.anchor_bundle_sha256=$anchor_bundle_sha256
                     AND rec.anchor_bundle_json=$anchor_bundle_json
                     AND rec.history_payload_sha256=$prediction_payload_sha256
                     AND o.tree=$tree AND o.op='prediction_register'
                     AND o.node_tag=$tag AND o.payload=$history_payload_json
                     AND o.reason='prediction_register_commit_intent'
                     AND o.receipt_sha=$rsha
                     AND o.created_at IS NOT NULL
                     AND ((o.status='pending' AND o.applied_at IS NULL)
                          OR (o.status='applied' AND o.applied_at IS NOT NULL))
                   FOREACH (anchor IN $anchor_rows |
                     MERGE (an:TemporalAnchor {id:anchor.id})
                     ON CREATE SET an.digest=anchor.digest,
                                   an.witness_did=anchor.witness_did,
                                   an.gen_time=anchor.gen_time,
                                   an.channel=anchor.channel,
                                   an.signature=anchor.signature,
                                   an.kind='prediction'
                     MERGE (e)-[:PRED_ANCHORED_BY]->(an))
                   SET e.pred_anchor_verified=true,
                       e.pred_anchor_gen_time=$anchor_gen_time,
                       e.pred_anchor_quorum=$anchor_quorum,
                       e.pred_anchor_threshold=$anchor_threshold
                   RETURN e.tag AS tag""",
                tree=name,
                tag=tag,
                rsha=rsha,
                history_event_id=prediction_event_id,
                history_payload_json=history_payload_json,
                prediction_payload_sha256=prediction_payload_sha256,
                anchor_bundle_sha256=anchor_bundle_sha256,
                anchor_bundle_json=anchor_bundle_json,
                anchor_rows=anchor_rows,
                anchor_gen_time=gt,
                anchor_quorum=anchor_quorum,
                anchor_threshold=threshold,
            )
            if not repaired:
                raise HTTPException(500, 'prediction anchor repair guard rejected')
            anchor_verified_response = True
        intent_rows = self.kg(
            """MATCH (o:OutboxEntry {id:$id})
               RETURN o.id AS id, o.tree AS tree, o.op AS op,
                      o.node_tag AS node_tag, o.payload AS payload,
                      o.status AS status, o.created_at AS created_at,
                      o.reason AS reason, o.applied_at AS applied_at,
                      o.receipt_sha AS receipt_sha,
                      o.adopted_by AS adopted_by,
                      o.adopted_at AS adopted_at,
                      o.causal_group AS causal_group,
                      o.causal_index AS causal_index,
                      o.request_sha256 AS request_sha256,
                      o.demoted_tag AS demoted_tag,
                      o.demoted_receipt_sha AS demoted_receipt_sha""",
            id=prediction_event_id,
        )
        intent_valid = (
            len(intent_rows) == 1
            and intent_rows[0].get('id') == prediction_event_id
            and intent_rows[0].get('tree') == name
            and intent_rows[0].get('op') == 'prediction_register'
            and intent_rows[0].get('node_tag') == tag
            and intent_rows[0].get('payload') == history_payload_json
            and intent_rows[0].get('reason') == 'prediction_register_commit_intent'
            and intent_rows[0].get('receipt_sha') == rsha
            and intent_rows[0].get('created_at') is not None
            and intent_rows[0].get('adopted_by') is None
            and intent_rows[0].get('adopted_at') is None
            and intent_rows[0].get('causal_group') is None
            and intent_rows[0].get('causal_index') is None
            and intent_rows[0].get('request_sha256') is None
            and intent_rows[0].get('demoted_tag') is None
            and intent_rows[0].get('demoted_receipt_sha') is None
            and (
                (intent_rows[0].get('status') == 'pending'
                 and intent_rows[0].get('applied_at') is None)
                or (intent_rows[0].get('status') == 'applied'
                    and intent_rows[0].get('applied_at') is not None)
            )
        )
        if not intent_valid:
            raise HTTPException(
                500,
                'prediction receipt lacks its exact durable history intent',
            )
        self.hist(
            name,
            'prediction_register',
            tag,
            p.model_dump(),
            event_id=prediction_event_id,
        )
        return {'ok': True, 'idempotent': idempotent_retry,
                'pred_receipt_sha': rsha,
                'pred_anchor_verified': anchor_verified_response,
                'question_bound': bool(p.closes_question),
                'note': '예측 사전등록 완료 — 이제 실험을 실행하고 test_result 를 스크립트로 제출'}

    @_serialized_ledger_command
    def submit_test_result(
        self,
        name: str,
        tag: str,
        r: TestResultIn,
        *,
        cycle_claim: str | None = None,
        cycle_request: list | None = None,
    ) -> dict:
        if cycle_claim is not None:
            suffix = cycle_claim.removeprefix('cycle-')
            if (
                not cycle_claim.startswith('cycle-')
                or len(suffix) != 64
                or any(ch not in '0123456789abcdef' for ch in suffix)
                or not isinstance(cycle_request, list)
                or len(cycle_request) != 2
                or cycle_request[0] != name
                or not isinstance(cycle_request[1], dict)
                or hashlib.sha256(json.dumps(
                    cycle_request,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(',', ':'),
                    allow_nan=False,
                ).encode('utf-8')).hexdigest() != suffix
            ):
                raise HTTPException(500, 'invalid internal cycle claim identity')
        elif cycle_request is not None:
            raise HTTPException(500, 'cycle request supplied without cycle claim')
        validated_counterexample_response = None
        validated_counterexample_type = None
        if r.counterexample_response:
            try:
                validated_counterexample_response = Response(
                    r.counterexample_response
                )
            except ValueError:
                raise HTTPException(
                    422,
                    f'알 수 없는 반례 대응: {r.counterexample_response} — '
                    f'{[e.value for e in Response]} 중 하나',
                )
        if r.counterexample_type:
            try:
                validated_counterexample_type = CounterexampleType(
                    r.counterexample_type
                )
            except ValueError:
                raise HTTPException(
                    422,
                    f'알 수 없는 반례유형: {r.counterexample_type} — '
                    f'{[e.value for e in CounterexampleType]} 중 하나',
                )
        submit_request_document = {
            'tree': name,
            'tag': tag,
            'request': r.model_dump(),
            'cycle_claim': cycle_claim,
            'cycle_request': cycle_request,
        }
        try:
            submit_request_json = validate_history_record(
                name,
                'test_result',
                tag,
                submit_request_document,
                'ob-test-result-preflight',
            )
        except HistoryPayloadError as exc:
            raise HTTPException(
                422, 'test result request contains text PostgreSQL JSONB cannot represent'
            ) from exc
        submit_request_sha256 = hashlib.sha256(
            submit_request_json.encode('utf-8')
        ).hexdigest()
        self._require_ledger_ready()
        self._project_pending_admin_predecessors(name, tag)
        # Direct-submit lost ACK/history recovery.  A cycle has its own
        # command-level recovery in ProgrammeService; keep this branch for the
        # direct REST/MCP verb so it can repair PG projection before the budget
        # gate and without minting a second verdict.
        if cycle_claim is None:
            replay_rows = self.kg(
                """MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                   OPTIONAL MATCH (e)-[:HAS_RECEIPT]->(rec:VerdictReceipt {
                     receipt_sha:e.current_receipt_sha, tree:$tree, tag:$tag})
                   OPTIONAL MATCH (test_o:OutboxEntry {
                     id:'ob-test-result-'+e.current_receipt_sha})
                   OPTIONAL MATCH (close_o:OutboxEntry {
                     id:'ob-question-close-'+e.current_receipt_sha})
                   OPTIONAL MATCH (t)-[:HAS_FRONTIER]->(q:OpenQuestion {
                     name:rec.target_id})
                   OPTIONAL MATCH (q)-[:HAS_CLOSURE]->(closure:QuestionClosure {
                     id:e.current_receipt_sha})
                   CALL {
                     WITH e
                     OPTIONAL MATCH (group_o:OutboxEntry {
                       causal_group:e.current_receipt_sha})
                     WITH [entry IN collect(group_o {
                       .id, .tree, .op, .node_tag, .payload, .status,
                       .created_at, .reason, .applied_at, .receipt_sha,
                       .causal_group, .causal_index, .request_sha256
                     }) WHERE entry.id IS NOT NULL] AS group_outboxes
                     RETURN group_outboxes
                   }
                   RETURN e.current_receipt_sha AS receipt_sha,
                          e.verdict_source AS verdict_source,
                          e.verdict AS verdict, e.lakatos_status AS lakatos_status,
                          e.metric_value AS metric_value,
                          e.measurement_grade AS measurement_grade,
                          e.replay_status AS replay_status,
                          e.assurance_tier_resolved AS assurance_tier_resolved,
                          e.attested_by_did AS attested_by_did,
                          e.measurement_lock_sha AS measurement_lock_sha,
                          e.eureka_felt AS eureka_felt,
                          e.eureka_true AS eureka_true,
                          e.eureka_hallucinated AS eureka_hallucinated,
                          e.eureka_reasons AS eureka_reasons,
                          e.eureka_bf AS eureka_bf,
                          rec.receipt_sha AS bound_receipt_sha,
                          rec.receipt_kind AS receipt_kind,
                          rec.tree AS receipt_tree, rec.tag AS receipt_tag,
                          rec.target_id AS target_id,
                          rec.verdict AS receipt_verdict,
                          rec.verdict_source AS receipt_verdict_source,
                          rec.metric_name AS receipt_metric_name,
                          rec.metric_value AS receipt_metric_value,
                          rec.novel_confirmed AS receipt_novel_confirmed,
                          rec.lakatos_status AS receipt_lakatos_status,
                          rec.judged_at AS receipt_judged_at,
                          rec.judge_script_sha AS receipt_judge_script_sha,
                          rec.prev_receipt_sha AS receipt_prev_receipt_sha,
                          rec.measurement_grade AS receipt_measurement_grade,
                          rec.engine_rule_sha AS engine_rule_sha,
                          rec.comment_sha AS receipt_comment_sha,
                          rec.replay_status AS receipt_replay_status,
                          rec.replay_reason AS receipt_replay_reason,
                          rec.regenerated_metric AS receipt_regenerated_metric,
                          rec.judge_script_path AS receipt_judge_script_path,
                          rec.result_path AS receipt_result_path,
                          rec.result_sha256 AS receipt_result_sha256,
                          rec.measurement_lock_sha AS receipt_measurement_lock_sha,
                          rec.source_script_path AS receipt_source_script_path,
                          rec.source_result_path AS receipt_source_result_path,
                          rec.history_payload_sha256 AS receipt_history_payload_sha256,
                          rec.prediction_temporal_commitment_sha256 AS
                            receipt_prediction_temporal_commitment_sha256,
                          t.attestor_dids AS attestor_dids,
                          q.status AS question_state,
                          q.closed_by AS question_closed_by,
                          q.closed_events AS question_closed_events,
                          closure.id AS closure_id,
                          closure.closed_by AS closure_closed_by,
                          closure.at AS closure_at,
                          closure.tree AS closure_tree,
                          closure.question AS closure_question,
                          closure.trigger AS closure_trigger,
                          closure.verdict AS closure_verdict,
                          closure.receipt_sha AS closure_receipt_sha,
                          COUNT { MATCH (q)-[:HAS_CLOSURE]->
                            (:QuestionClosure {id:e.current_receipt_sha})-
                            [:CAUSED_BY]->(rec) } AS closure_bound_count,
                          COUNT { MATCH (:QuestionClosure {
                            id:e.current_receipt_sha}) } AS closure_global_count,
                          COUNT { MATCH (e)-[:CLOSES_QUESTION]->(q) }
                            AS closes_rel_count,
                          head([(e)-[rel:CLOSES_QUESTION]->(q) |
                            rel.receipt_sha]) AS closes_rel_receipt_sha,
                          head([(e)-[rel:CLOSES_QUESTION]->(q) |
                            rel.verdict]) AS closes_rel_verdict,
                          head([(e)-[rel:CLOSES_QUESTION]->(q) |
                            rel.at]) AS closes_rel_at,
                          group_outboxes,
                          test_o.id AS test_event_id,
                          test_o.tree AS test_tree, test_o.op AS test_op,
                          test_o.node_tag AS test_tag,
                          test_o.payload AS test_payload,
                          test_o.status AS test_status,
                          test_o.created_at AS test_created_at,
                          test_o.reason AS test_reason,
                          test_o.applied_at AS test_applied_at,
                          test_o.receipt_sha AS test_receipt_sha,
                          test_o.causal_group AS test_causal_group,
                          test_o.causal_index AS test_causal_index,
                          test_o.request_sha256 AS request_sha256,
                          close_o.id AS close_event_id,
                          close_o.tree AS close_tree, close_o.op AS close_op,
                          close_o.node_tag AS close_tag,
                          close_o.payload AS close_payload,
                          close_o.status AS close_status,
                          close_o.created_at AS close_created_at,
                          close_o.reason AS close_reason,
                          close_o.applied_at AS close_applied_at,
                          close_o.receipt_sha AS close_receipt_sha,
                          close_o.causal_group AS close_causal_group,
                          close_o.causal_index AS close_causal_index""",
                tree=name,
                tag=tag,
            )
            if len(replay_rows or []) > 1:
                raise HTTPException(500, 'test result replay cardinality conflict')
            if (
                replay_rows
                and replay_rows[0].get('receipt_kind') != 'prediction'
                and replay_rows[0].get('receipt_history_payload_sha256') is not None
                and replay_rows[0].get('test_event_id') is None
            ):
                raise HTTPException(
                    500, 'V6 verdict receipt lacks its test-result intent'
                )
            if replay_rows and replay_rows[0].get('test_event_id') is not None:
                replay = replay_rows[0]
                receipt_sha = replay.get('receipt_sha')
                group_outboxes = replay.get('group_outboxes')
                if not isinstance(group_outboxes, list):
                    raise HTTPException(
                        500, 'test result causal group snapshot missing'
                    )
                test_event_id = f'ob-test-result-{receipt_sha}'
                receipt_snapshot = {
                    key: replay.get(
                        'engine_rule_sha'
                        if key == 'engine_rule_sha'
                        else f'receipt_{key}'
                    )
                    for key in RECEIPT_FIELDS
                }
                receipt_snapshot['receipt_sha'] = replay.get('bound_receipt_sha')
                current_snapshot = {
                    'current_receipt_sha': receipt_sha,
                    'verdict': replay.get('verdict'),
                    'verdict_source': replay.get('verdict_source'),
                    'lakatos_status': replay.get('lakatos_status'),
                    'metric_value': replay.get('metric_value'),
                }
                test_snapshot = {
                    'id': replay.get('test_event_id'),
                    'tree': replay.get('test_tree'),
                    'op': replay.get('test_op'),
                    'node_tag': replay.get('test_tag'),
                    'payload': replay.get('test_payload'),
                    'status': replay.get('test_status'),
                    'created_at': replay.get('test_created_at'),
                    'reason': replay.get('test_reason'),
                    'applied_at': replay.get('test_applied_at'),
                    'receipt_sha': replay.get('test_receipt_sha'),
                    'causal_group': replay.get('test_causal_group'),
                    'causal_index': replay.get('test_causal_index'),
                    'request_sha256': replay.get('request_sha256'),
                }
                close_snapshot = None
                if replay.get('close_event_id') is not None:
                    close_snapshot = {
                        'id': replay.get('close_event_id'),
                        'tree': replay.get('close_tree'),
                        'op': replay.get('close_op'),
                        'node_tag': replay.get('close_tag'),
                        'payload': replay.get('close_payload'),
                        'status': replay.get('close_status'),
                        'created_at': replay.get('close_created_at'),
                        'reason': replay.get('close_reason'),
                        'applied_at': replay.get('close_applied_at'),
                        'receipt_sha': replay.get('close_receipt_sha'),
                        'causal_group': replay.get('close_causal_group'),
                        'causal_index': replay.get('close_causal_index'),
                    }
                closure_snapshot = {
                    'question_state': replay.get('question_state'),
                    'question_closed_by': replay.get('question_closed_by'),
                    'question_closed_events': replay.get('question_closed_events'),
                    'closure_id': replay.get('closure_id'),
                    'closure_closed_by': replay.get('closure_closed_by'),
                    'closure_at': replay.get('closure_at'),
                    'closure_tree': replay.get('closure_tree'),
                    'closure_question': replay.get('closure_question'),
                    'closure_trigger': replay.get('closure_trigger'),
                    'closure_verdict': replay.get('closure_verdict'),
                    'closure_receipt_sha': replay.get('closure_receipt_sha'),
                    'closure_bound': replay.get('closure_bound_count') == 1,
                    'closure_global_count': replay.get('closure_global_count'),
                    'closes_rel_count': replay.get('closes_rel_count'),
                    'closes_rel_receipt_sha': replay.get('closes_rel_receipt_sha'),
                    'closes_rel_verdict': replay.get('closes_rel_verdict'),
                    'closes_rel_at': replay.get('closes_rel_at'),
                }
                try:
                    validated_group = validate_verdict_intent_group(
                        tree=name,
                        tag=tag,
                        receipt_sha=receipt_sha,
                        receipt=receipt_snapshot,
                        current=current_snapshot,
                        outboxes=list(group_outboxes or []),
                        closure=closure_snapshot,
                        require_cycle=False,
                    )
                except VerdictIntentError as exc:
                    raise HTTPException(
                        500, f'test result durable intent corrupt: {exc}'
                    ) from exc
                try:
                    datetime.fromisoformat(str(replay.get('test_created_at')))
                except (TypeError, ValueError) as exc:
                    raise HTTPException(500, 'test result intent timestamp corrupt') from exc
                binding_ok = (
                    isinstance(receipt_sha, str)
                    and len(receipt_sha) == 64
                    and replay.get('bound_receipt_sha') == receipt_sha
                    and replay.get('test_event_id') == test_event_id
                    and replay.get('test_tree') == name
                    and replay.get('test_op') == 'test_result'
                    and replay.get('test_tag') == tag
                    and replay.get('test_reason') == 'test_result_commit_intent'
                    and replay.get('test_receipt_sha') == receipt_sha
                    and (
                        (replay.get('test_status') == 'pending'
                         and replay.get('test_applied_at') is None)
                        or (replay.get('test_status') == 'applied'
                            and replay.get('test_applied_at') is not None)
                    )
                )
                if not binding_ok:
                    raise HTTPException(500, 'test result durable intent binding conflict')
                exact_request_replay = (
                    replay.get('request_sha256') == submit_request_sha256
                )
                explicit_freshen = not exact_request_replay
                if explicit_freshen:
                    if not (
                        r.freshen
                        and r.supersedes_receipt_sha == receipt_sha
                        and replay.get('verdict_source') == 'scripted'
                        and replay.get('verdict') == 'partial'
                        and replay.get('lakatos_status') in {
                            'novel_not_server_anchored',
                            'provisional_stale_engine',
                        }
                        and replay.get('metric_value') == r.metric_value
                    ):
                        raise HTTPException(409, 'different test result already committed')
                if replay.get('test_event_id') is not None:
                    prior_payload = dict(validated_group.test_payload)
                    expected_keys = {
                        'attested_by', 'baseline', 'delta', 'freshen', 'lakatos',
                        'measurement_lock_sha', 'metric_verdict', 'novel',
                        'novel_server_anchored', 'receipt_sha',
                        'regenerated_metric', 'replay_reason', 'replay_status',
                        'requires_human', 'result_path', 'result_sha256', 'rule',
                        'script', 'script_sha', 'script_sha_server_verified',
                        'source_result_path', 'source_script_path', 'value', 'verdict',
                        'cycle_claim', 'cycle_request_sha256', 'request_sha256',
                        'assurance', 'eureka_closed', 'eureka_open',
                        'qualitative_self_report', 'replay_authoritative',
                        'verdict_display',
                    }
                    finite_fields = ('value', 'baseline', 'delta')
                    if (
                        set(prior_payload) != expected_keys
                        or prior_payload.get('receipt_sha') != receipt_sha
                        or any(
                            type(prior_payload.get(key)) not in (int, float)
                            or not math.isfinite(float(prior_payload[key]))
                            for key in finite_fields
                        )
                        or not isinstance(prior_payload.get('verdict'), str)
                        or not isinstance(prior_payload.get('lakatos'), str)
                        or type(prior_payload.get('freshen')) is not bool
                        or type(prior_payload.get('novel_server_anchored')) is not bool
                        or type(prior_payload.get('requires_human')) is not bool
                        or type(prior_payload.get('script_sha_server_verified')) is not bool
                        or type(prior_payload.get('qualitative_self_report')) is not bool
                        or prior_payload.get('novel') is not None
                           and type(prior_payload.get('novel')) is not bool
                    ):
                        raise HTTPException(500, 'test result intent payload shape conflict')
                    test_projected = self.hist(
                        name,
                        'test_result',
                        tag,
                        prior_payload,
                        event_id=test_event_id,
                    )
                    history_pending = test_projected is False
                    if test_projected is False:
                        if explicit_freshen:
                            raise HTTPException(
                                503,
                                'test result history pending; freshen deferred',
                            )
                    close_event_id = (
                        f'ob-question-close-{receipt_sha}'
                        if validated_group.close_payload is not None else None
                    )
                    question_closed = close_event_id is not None
                    if question_closed and test_projected is not False:
                        expected_close_id = f'ob-question-close-{receipt_sha}'
                        try:
                            datetime.fromisoformat(str(replay.get('close_created_at')))
                            close_payload = dict(validated_group.close_payload)
                        except (TypeError, ValueError, json.JSONDecodeError) as exc:
                            raise HTTPException(500, 'question close intent corrupt') from exc
                        if not (
                            close_event_id == expected_close_id
                            and replay.get('close_tree') == name
                            and replay.get('close_op') == 'question_close'
                            and replay.get('close_tag') == tag
                            and replay.get('close_reason') == 'question_close_commit_intent'
                            and replay.get('close_receipt_sha') == receipt_sha
                            and set(close_payload) == {
                                'question', 'receipt_sha', 'trigger', 'verdict'
                            }
                            and close_payload.get('receipt_sha') == receipt_sha
                            and close_payload.get('question') == replay.get('target_id')
                            and close_payload.get('trigger') == 'ADJUDICATED'
                            and (
                                (replay.get('close_status') == 'pending'
                                 and replay.get('close_applied_at') is None)
                                or (replay.get('close_status') == 'applied'
                                    and replay.get('close_applied_at') is not None)
                            )
                        ):
                            raise HTTPException(500, 'question close intent binding conflict')
                        close_projected = self.hist(
                            name,
                            'question_close',
                            tag,
                            close_payload,
                            event_id=expected_close_id,
                        )
                        if close_projected is False:
                            history_pending = True
                            if explicit_freshen:
                                raise HTTPException(
                                    503,
                                    'question close history pending; freshen deferred',
                                )
                    if explicit_freshen:
                        expected_ids = [
                            test_event_id,
                            *([f'ob-question-close-{receipt_sha}']
                              if question_closed else []),
                        ]
                        applied_rows = self.kg(
                            "MATCH (o:OutboxEntry) WHERE o.id IN $ids "
                            "RETURN o.id AS id, o.status AS status, "
                            "o.applied_at AS applied_at",
                            ids=expected_ids,
                        )
                        applied_by_id = {
                            row.get('id'): row for row in (applied_rows or [])
                        }
                        if not (
                            len(applied_by_id) == len(expected_ids)
                            and all(
                                applied_by_id.get(event_id, {}).get('status')
                                    == 'applied'
                                and applied_by_id[event_id].get('applied_at')
                                    is not None
                                for event_id in expected_ids
                            )
                        ):
                            raise HTTPException(
                                503,
                                'prior verdict history is not durably applied; freshen deferred',
                            )
                    # Exact command identity is a replay even when the stored
                    # result is freshen-eligible.  A new adjudication reaches
                    # this point only through an explicit head-bound command
                    # whose request hash differs from the stored intent.
                    if exact_request_replay:
                        target_id = replay.get('target_id')
                        question_state = replay.get('question_state')
                        question_transition = (
                            'adjudication-close' if question_closed
                            else 'duplicate-adjudication'
                            if question_state == QuestionState.CLOSED.value
                            else 'adjudication-retain-open'
                        )
                        return {
                            'ok': True,
                            'idempotent': True,
                            'history_pending': history_pending,
                            'freshen': prior_payload['freshen'],
                            'verdict': prior_payload['verdict'],
                            'verdict_display': prior_payload['verdict_display'],
                            'assurance': prior_payload['assurance'],
                            'delta': prior_payload['delta'],
                            'novel': prior_payload['novel'],
                            'novel_server_anchored': prior_payload[
                                'novel_server_anchored'
                            ],
                            'lakatos': prior_payload['lakatos'],
                            'metric_verdict': prior_payload['metric_verdict'],
                            'requires_human': prior_payload['requires_human'],
                            'script_sha_server_verified': prior_payload[
                                'script_sha_server_verified'
                            ],
                            'judge_script_sha': prior_payload['script_sha'],
                            'judge_script_path': prior_payload['script'],
                            'result_path': prior_payload['result_path'],
                            'result_sha256': prior_payload['result_sha256'],
                            'source_script_path': prior_payload['source_script_path'],
                            'source_result_path': prior_payload['source_result_path'],
                            'measurement_lock_sha': prior_payload[
                                'measurement_lock_sha'
                            ],
                            'replay_status': prior_payload['replay_status'],
                            'replay_reason': prior_payload['replay_reason'],
                            'regenerated_metric': prior_payload['regenerated_metric'],
                            'question': ({
                                'target': target_id,
                                'closed': question_closed,
                                'state': question_state,
                                'transition': question_transition,
                            } if target_id else None),
                            'attested_by': prior_payload['attested_by'],
                            'eureka': prior_payload[
                                'eureka_closed' if question_closed else 'eureka_open'
                            ],
                            'rule': prior_payload['rule'],
                            'replay_authoritative': prior_payload[
                                'replay_authoritative'
                            ],
                            'replay': (
                                replay_command(
                                    prior_payload['script'],
                                    prior_payload['result_path'],
                                )
                                if prior_payload['replay_authoritative'] else None
                            ),
                        }
        # ⓪ 루프-경계 예산(PROM16 S1/S5) — *진짜 초크포인트*. 채점은 결국 전부 여기로 들어온다
        #    (REST POST /node/{tag}/test_result · MCP submit_result · run_cycle 내부호출). 첫 구현은
        #    run_cycle 만 거부해 3-verb 경로(add_node+register_prediction+submit_result)로 갈아타면
        #    그대로 채점됐다 = 에이전트가 고르는 정지(적대검증 2026-07-15). 판결 민팅 전에 429.
        #    (run_cycle 은 자기 게이트를 이미 통과했어도 여기서 1-read 를 다시 낸다 — 중복 read 1회는
        #     초크포인트를 호출자 신뢰에 의존시키지 않기 위한 값이다. 예측등록은 소모가 아니므로
        #     cycle_budget 술어상 자기 사이클이 자기를 거부하는 일은 없다.)
        assert_scoring_budget(self.kg, name, 'submit_test_result')
        rows = self.kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                     RETURN e.pred_metric AS m, e.pred_direction AS d, e.pred_baseline AS b,
                            e.pred_noise_band AS nb, e.pred_scale_type AS scale,
                            e.pred_novel AS novel, e.verdict_source AS vsrc,
                            e.pred_novel_metric AS nmet, e.pred_novel_direction AS ndir,
                            e.pred_novel_threshold AS nthr, e.pred_script_sha AS psha,
                            e.pred_registered_at AS pred_registered_at,
                            e.node_state AS node_state, e.judged_at AS judged_at,
                            e.metric_value AS existing_metric_value,
                            coalesce(e.source_result_path, e.result_path) AS existing_result_path,
                            e.verdict AS existing_verdict, e.lakatos_status AS existing_lstat,
                            e.current_receipt_sha AS prev_receipt_sha,
                            e.pred_receipt_sha AS pred_receipt_sha,
                            e.comment AS node_comment,
                            e.pred_closes AS closes,
                            size([(e)-[:RAISES_QUESTION]->(q) | q.name]) AS n_opened,
                            t.hard_core AS hard_core,
                            t.require_novel_anchor AS require_novel_anchor,
                            t.assurance_tier AS assurance_tier,
                            t.attestor_dids AS attestor_dids,
                            t.research_layout AS research_layout,
                            t.layout_owner_did AS layout_owner_did,
                            t.layout_sig AS layout_sig, t.witness_dids AS witness_dids,
                            size([(e)-[:HAS_PREDICTION_TEMPORAL_COMMITMENT]->() | 1])
                              AS prediction_temporal_commitment_count,
                            e.pred_anchor_verified AS pred_anchor_verified,
                            e.pred_anchor_gen_time AS pred_anchor_gen_time""", tree=name, tag=tag)
        if not rows:
            raise HTTPException(404, f'노드 없음: {tag}')
        pr = rows[0]
        (
            prediction_temporal_commitment_sha256,
            prediction_temporal_policy_sha256,
        ) = self._prediction_temporal_binding(name, tag, pr)
        if r.freshen and pr.get('vsrc') != 'scripted':
            raise HTTPException(
                409,
                'freshen 대상 없음 — 먼저 존재하는 recoverable partial receipt를 '
                'supersedes_receipt_sha로 지정해야 한다',
            )
        # G6(git-흡수): tier 정책은 assurance 디스패치 테이블(SSOT)이 결정 — 핸들러가 하드코딩하지 않는다.
        #   receipted/anchored tier 는 novel-anchor 게이트를 무장(신규 트리 기본=anchored, git default-OFF 반전);
        #   legacy(무tier)/notebook 은 트리의 opt-in 플래그(FF1)로만 발동(거동 불변, 소급 강등 없음).
        tier = assurance.resolve_tier(pr.get('assurance_tier'))
        require_novel_anchor = (
            assurance.GATE_NOVEL_ANCHOR in assurance.gates_for('submit_test_result', tier)
            or bool(pr.get('require_novel_anchor')))   # FF1 phase2: opt-in tree policy 는 그대로 존중
        # RP-1: fresh, explicitly artifact-bearing submits at receipted+ tiers must carry a
        # host-independent request identity.  This runs *after* exact lost-ACK replay returned
        # above, so historical absolute-path receipts remain repairable, and keys only on
        # r.result_path (not an inherited stored path) so result-less/freshen behavior is stable.
        portable_artifact_required = (
            assurance.GATE_REPLAY_PORTABILITY
            in assurance.gates_for('submit_test_result', tier)
            and bool(r.result_path)
        )
        portable_script_path = portable_result_path = None
        portable_script_rel = portable_result_rel = ''
        portable_script_body = portable_result_body = None
        portable_script_sha = portable_result_sha = None
        if portable_artifact_required:
            portable_script_path, portable_script_rel, portable_script_info = (
                isolate_portable_replay_file(r.script, self._SCRIPT_MAX_BYTES)
            )
            if portable_script_path is None:
                raise HTTPException(
                    422,
                    'portable replay script 거부 — canonical repo-relative POSIX 정규파일 필요 '
                    f'({portable_script_info.get("reason")})',
                )
            portable_result_path, portable_result_rel, portable_result_info = (
                isolate_portable_replay_file(r.result_path, self._RESULT_MAX_BYTES)
            )
            if portable_result_path is None:
                raise HTTPException(
                    422,
                    'portable replay result 거부 — canonical repo-relative POSIX 정규파일 필요 '
                    f'({portable_result_info.get("reason")})',
                )
            if not _is_lower_sha256(r.script_sha):
                raise HTTPException(
                    422, 'portable replay script_sha는 정확한 lowercase sha256이어야 함'
                )
            if not _is_lower_sha256(pr.get('psha')):
                raise HTTPException(
                    409, 'portable replay 사전등록 judge_script_sha는 정확한 lowercase sha256이어야 함'
                )
            # Re-resolve from an open root fd and capture the bytes now.  Returning a checked Path
            # and reopening it later is racy: a parent directory can be swapped for a symlink
            # between containment and hash/snapshot.  Strict replay never reopens these sources.
            try:
                portable_script_body, portable_script_sha = (
                    replay_artifact_mod.read_portable_repo_file(
                        repo_root=longinus.ROOT,
                        relative_path=portable_script_rel,
                        max_bytes=self._SCRIPT_MAX_BYTES,
                    )
                )
            except replay_artifact_mod.ReplayArtifactError as exc:
                raise HTTPException(422, f'portable replay script capture 거부: {exc}')
            if portable_script_sha != r.script_sha:
                raise HTTPException(
                    422, f"judge_script_sha 서버재계산 불일치 — 파일 "
                         f"{portable_script_sha[:12]} ≠ 제출 {(r.script_sha or '')[:12]} "
                         f"(fd_anchored_file_content_sha)"
                )
            if portable_script_sha != pr.get('psha'):
                raise HTTPException(
                    409, f"채점 스크립트 sha256 불일치 — 사전등록 "
                         f"{str(pr.get('psha'))[:12]} ≠ 서버재계산 "
                         f"{portable_script_sha[:12]} (fd-anchored repo read)"
                )
            try:
                portable_result_body, portable_result_sha = (
                    replay_artifact_mod.read_portable_repo_file(
                        repo_root=longinus.ROOT,
                        relative_path=portable_result_rel,
                        max_bytes=self._RESULT_MAX_BYTES,
                    )
                )
            except replay_artifact_mod.ReplayArtifactError as exc:
                raise HTTPException(422, f'portable replay result capture 거부: {exc}')
        # jp4 판관 자기고유수용감각 — stale(코드경로 한정)/무능력 판정. 3중 fail-open: 미주입(None)=
        #   'unchecked' 무강등 / 판정불가(stale_code None)='indeterminate' 무발화(부재≠반증) / 발화는
        #   engine_freshness_fires 가 is True·is False 만 문다. 발화해도 거부가 아니라 ④ provisional
        #   강등(채점 흐름은 계속 — 정직 라벨) — 재기동 후 동일값 재제출 freshen 으로 승급.
        fresh = self.engine_freshness() if self.engine_freshness else None
        fresh_fire = engine_freshness_fires(fresh)
        efresh = ('unchecked' if fresh is None else
                  'incapable' if fresh.get('capable') is False else
                  'stale_code' if fresh.get('stale_code') is True else
                  'indeterminate' if fresh.get('stale_code') is None else 'fresh')
        # novel-anchor freshen (2026-07-03): 앵커-데모트 partial 은 *동일 metric_value* 의 서버앵커
        #   재제출로만 승급 가능(G1 "바이트동일 재제출=freshen" 정합). 값이 다르면 re-roll → 409 유지.
        #   앵커 성립 여부는 아래 sha 재유도 후 재검(freshen_anchor 인데 미앵커면 409) — client 문자열
        #   재제출로는 이 통로를 못 연다(FF1 봉합 유지).
        # jp4 확장: provisional_stale_engine partial 도 같은 좁은통로(동일값 재제출)로 — 단 판관이
        #   *여전히* stale/무능력이면 409(재기동 먼저).
        freshen_anchor = False
        freshen_reason = None
        # FSM 감사 수리(2026-07-28): raw =='scripted' 만 보면 engine/human/reproducible 로 강등된
        # 노드(former_canonical 등)의 재제출이 통과해 강등이 지워졌다 — FORCEFUL 멤버십으로 확장.
        # (freshen 좁은통로는 scripted 판정에만 유효하므로 그 안에서 다시 좁힌다.)
        if normalize_source(pr['vsrc']) in FORCEFUL_SOURCES and pr['vsrc'] != 'scripted':
            raise HTTPException(409, f"영수증 판정({pr['vsrc']})이 이미 선 노드 — 재채점 금지. "
                                     f"강등/판정을 되돌리려면 새 노드로 분기하라(강등 세탁 차단).")
        if pr['vsrc'] == 'scripted':
            can_freshen = (r.freshen
                           and r.supersedes_receipt_sha == pr.get('prev_receipt_sha')
                           and pr.get('existing_verdict') == 'partial'
                           and pr.get('existing_lstat') in ('novel_not_server_anchored',
                                                            'provisional_stale_engine')
                           and r.metric_value == pr.get('existing_metric_value'))
            if not can_freshen:
                raise HTTPException(409, '이미 스크립트로 채점된 노드 — 재채점 금지 (re-roll 조작 차단). '
                                         '새 노드로 분기할 것 (예외: novel_not_server_anchored/'
                                         'provisional_stale_engine partial 은 동일 metric_value 재제출로 '
                                         'freshen 가능 — 전자는 서버앵커, 후자는 비-stale 판관 요구)')
            freshen_anchor = True
            freshen_reason = pr.get('existing_lstat')
            if freshen_reason == 'provisional_stale_engine' and fresh_fire:
                raise HTTPException(409, f"freshen 거부 — 판관이 여전히 stale/무능력: "
                                         f"boot_git_sha={(fresh or {}).get('boot_git_sha')} vs "
                                         f"disk_head_sha={(fresh or {}).get('disk_head_sha')}, "
                                         f"missing={(fresh or {}).get('missing')}. "
                                         f"scripts/dev_server_restart.sh 재기동 후 동일값 재제출.")
        # #H3 (receipt-integrity): server_sha 를 r.script 파일 *내용*에서 재유도해 영수증을 현실에 묶는다.
        #   불일치 비교 대상을 client-vs-client(psha vs script_sha, 동어반복) → server-vs-client/registered 로 교체.
        if portable_artifact_required:
            server_sha = portable_script_sha
            sha_info = {
                'reason': 'file_content_sha',
                'path': portable_script_rel,
                'capture': 'repo_dirfd_nofollow',
            }
        else:
            server_sha, sha_info = self._recompute_script_sha(r.script)
        sha_verified = server_sha is not None
        if sha_verified:
            if r.script_sha and server_sha != r.script_sha:   # 제출 sha 가 파일 내용과 불일치 → 날조 봉쇄
                raise HTTPException(422, f"judge_script_sha 서버재계산 불일치 — 파일 {server_sha[:12]} ≠ 제출 "
                                         f"{(r.script_sha or '')[:12]} ({sha_info.get('reason')})")
            if pr['psha'] and server_sha != pr['psha']:   # 사전등록 psha 가 채점 스크립트 내용과 불일치
                raise HTTPException(409, f"채점 스크립트 sha256 불일치 — 사전등록 {pr['psha'][:12]} ≠ 서버재계산 "
                                         f"{server_sha[:12]} (서버가 r.script 내용에서 재유도)")
        else:
            # 재계산 불가(inline/미존재 파일/심볼 모호) — 정직 fallback: 레거시 client-vs-client 비교 유지.
            #   sha 영수증은 server-미검증이므로 응답에 script_sha_server_verified=False 로 노출(동어반복 위험 숨김 금지).
            if pr['psha'] and r.script_sha and pr['psha'] != r.script_sha:
                raise HTTPException(409, f"채점 스크립트 sha256 불일치 — 사전등록 {pr['psha'][:12]} ≠ 제출 {r.script_sha[:12]}")
        # 저장·prov 는 server_sha(파일 재유도) 우선; 재계산 불가면 client 값 보존(server-미검증 플래그와 함께).
        stored_sha = server_sha if sha_verified else (r.script_sha or '')
        source_script_path = (sha_info.get('path') if sha_verified and sha_info.get('path')
                              else r.script)
        # ``file::symbol`` can have a server-derived body hash, but it is not an executable file
        # identity.  Never turn that hash into replay authority or pass the symbol string to Python.
        script_replay_bound = bool(
            sha_verified and sha_info.get('reason') == 'file_content_sha'
            and sha_info.get('path') and len(stored_sha) == 64)
        requested_result_path = r.result_path or pr.get('existing_result_path') or ''
        if portable_artifact_required:
            result_sha_before = portable_result_sha
            source_result_path = portable_result_rel
            result_info = {
                'reason': 'file_content_sha',
                'path': portable_result_rel,
                'capture': 'repo_dirfd_nofollow',
            }
        else:
            result_sha_before, source_result_path, result_info = (
                self._recompute_result_sha(requested_result_path)
            )
        replay_inputs_bound = bool(
            script_replay_bound
            and result_sha_before is not None and len(result_sha_before) == 64)
        sealed_script_path = source_script_path
        sealed_result_path = source_result_path
        snapshot_script_path = snapshot_result_path = None
        if replay_inputs_bound:
            try:
                snapshot_script_path = str(replay_artifact_mod.snapshot_path(
                    kind='script', sha256=stored_sha, source_path=source_script_path))
                snapshot_result_path = str(replay_artifact_mod.snapshot_path(
                    kind='result', sha256=result_sha_before, source_path=source_result_path))
            except replay_artifact_mod.ReplayArtifactError as exc:
                raise HTTPException(422, f'replay snapshot identity 거부: {exc}')
        # G10(git-흡수): attestor 선언 트리의 판결 쓰기는 *서명 cert 가 유일한 명령원*(push-cert 이식,
        #   receive-pack.c:2179-2199 — cert 와 다른 명령의 동시 제출=프로토콜 에러). 발동 = tier 게이트
        #   무장(assurance.GATE_WRITE_CERT) ∧ attestor allow-list(키 실물) 선언 — on/off 플래그가 아니라
        #   키 선언이 스위치(advisory GIT_PUSH_CERT_STATUS 는 정확히 P1 실패라 반전). allow-list 없는
        #   트리는 서명자 자체가 없어 잠글 수 없다(dead-σ: 키 없는 배포를 409 로 잠그지 않는다).
        #   명령 바인딩 = {tree, tag, prev_receipt_sha(G1 체인 포인터 CAS), metric_value, script_sha}
        #   → sign-X-execute-Y 불가 + replay 는 옛 포인터 서명이 되어 구조적으로 죽는다.
        #   author 는 client 문자열이 아니라 서명(signer_did)에서 유도되어 스탬프된다(Sybil 갭 봉합).
        attestors = [str(d).strip() for d in (pr.get('attestor_dids') or []) if d and str(d).strip()]
        # EXTAUDIT S6 (역할분리, in-toto 흡수): layout 이 선언됐으면 이 verb 의 allow-list 를 그 verb 의
        #   pubkeys 로 좁힌다(역할=다른 열쇠). owner 서명 무효/만료면 layout 무시(dead-σ: 위조된 정책은
        #   적용 안 함, 폴백은 attestors). layout 미선언 트리는 attestors 그대로 — 라이브 무회귀.
        # 2026-07-28 fail-closed 정합: 선언된 layout 이 무효면 422(종전엔 침묵 폴백 — 역할 좁힘·
        #   disjoint 검사가 통째로 사라졌다). 미선언 트리는 None → attestors 폴백(무회귀).
        role_layout = resolve_role_layout(pr)
        submit_allowlist = layout_mod.role_allowlist(role_layout, 'submit_test_result', attestors)
        cert_required = (assurance.GATE_WRITE_CERT in assurance.gates_for('submit_test_result', tier)
                         and bool(attestors))
        attested_by_did = None
        if cert_required or r.write_cert is not None:
            if r.write_cert is None:
                raise HTTPException(403, f'write-cert 필수 — attestor 선언 {tier} 트리의 판결 쓰기는 서명 '
                                         f'명령만 인정(allow-list {len(attestors)}명). client author 문자열은 '
                                         f'authorship 이 아니다(G10 Sybil 봉합)')
            # Every new mutation uses v4 full-payload binding.  An explicitly supplied/pre-existing
            # result additionally requires host-independent script/result content hashes; a truly
            # result-less v4 attestation remains non-replay-authoritative.
            artifact_command_required = bool(requested_result_path)
            if artifact_command_required and not replay_inputs_bound:
                raise HTTPException(
                    422, 'artifact-bound write-cert 거부 — submit 스크립트와 result_path 모두 '
                         f'허용 루트의 정규파일·서버 SHA여야 함 '
                         f'(result={result_info.get("reason")}, script={sha_info.get("reason")})')
            expected_command = dict(tree=name, tag=tag, prev_receipt_sha=pr.get('prev_receipt_sha'),
                                    metric_value=r.metric_value, script_sha=stored_sha,
                                    verb='submit_test_result', command_version='v4',
                                    operation_payload_sha256=operation_payload_sha256(
                                        'submit_test_result',
                                        r.model_dump(exclude={'write_cert'})))
            if artifact_command_required:
                # v4 certificates bind host-independent content identity.  Absolute cache paths
                # belong to this server deployment and are sealed only after materialisation in
                # the verdict receipt/MeasurementLock; a remote CLI must not predict server HOME.
                expected_command.update(result_sha256=result_sha_before)
            # S6: disjoint_roles 위반(같은 서명자가 predict/attest 겸직) 선차단 — 급소 #2 직접 답.
            if role_layout is not None:
                _dv = layout_mod.disjoint_violation(role_layout, r.write_cert.signer_did,
                                                    'submit_test_result')
                if _dv:
                    raise HTTPException(403, f'역할분리 위반: {_dv}')
            try:
                attestation = verify_write_cert(
                    r.write_cert.model_dump(),
                    expected_command=expected_command,
                    # 자발적 cert(비강제 트리): allow-list 없으면 자기서명 검증만 — authorship 증명이지
                    # 권위 주장이 아니다(권위 필터는 allow-list 가 정본). S6: layout 선언 트리는
                    # submit_allowlist(verb 좁힘)가 attestors 를 대체 — 역할 밖 서명자는 403.
                    allowlist=(submit_allowlist if attestors else [r.write_cert.signer_did]))
            except CertSignerNotAllowed as e:
                raise HTTPException(403, str(e))
            except CertError as e:
                raise HTTPException(422, str(e))
            attested_by_did = attestation['signer_did']
        nt = None
        if pr['nmet'] and pr['ndir'] and pr['nthr'] is not None:
            nt = NovelTarget(metric_name=pr['nmet'], direction=pr['ndir'], threshold=pr['nthr'])
        # #H6 (설계감사 2026-06-26): novel 독립성(measured_sha≠novel_sha)을 client 문자열이 아니라 *양측
        #   서버재계산* 에 묶는다. 예측측=H3 stored_sha(sha_verified 일 때 파일 재유도값), novel측=r.novel_script
        #   본문 재유도(novel_server_sha). 둘 다 서버앵커일 때만 독립 후보 — 어느 한쪽이라도 client-only
        #   (novel_script 미제공/재계산불가, 또는 예측 script inline=sha 미검증)이면 ''로 넘겨 같은-metric novel
        #   을 비독립 demote. 독립은 *두 개의 서로 다른 실재 산출물* 로 증명(client novel_sha 한 줄로 못 산다).
        #   다른 metric novel 은 그 자체로 독립 사실이라 judge 의 same-metric 게이트 밖(영향 없음).
        novel_server_sha, _ = (self._recompute_script_sha(r.novel_script)
                               if r.novel_script else (None, {'reason': 'no_novel_script'}))
        # freshen 자격 재검: 이번 재제출이 *양측 서버앵커* 를 실제로 성립시켜야만 좁은 통로가 열린다.
        #   (jp4: 이 요구는 novel-anchor 사유 전용 — provisional_stale_engine 은 novel_script 가 애초에
        #   없던 단순 metric 노드도 있어 비-stale 판관 재검(위)만 요구한다.)
        if (freshen_anchor and freshen_reason == 'novel_not_server_anchored'
                and not (sha_verified and novel_server_sha is not None)):
            raise HTTPException(409, 'freshen 거부 — 재제출의 script 와 novel_script 가 둘 다 서버가 '
                                     '읽을 수 있는 파일 경로여야 한다 (client 문자열로는 승급 불가)')
        both_anchored = sha_verified and novel_server_sha is not None
        novel_server_anchored = novel_server_sha is not None              # FF1: novel 측정이 서버 재유도됨
        cross_metric_novel = pr['nmet'] is not None and pr['nmet'] != pr['m']
        judge_measured_sha = stored_sha if both_anchored else ''
        judge_novel_sha = novel_server_sha if both_anchored else ''
        try:
            v = judge(None if pr['m'] is None else Prediction(
                metric_name=pr['m'], direction=pr['d'], baseline_value=pr['b'],
                noise_band=pr['nb'] or 0.0, novel_prediction=pr['novel'] or '',
                scale_type=pr.get('scale') or 'ratio'),   # Stevens 가드 reachable (옛 노드 null→ratio)
                r.metric_value, novel_target=nt, novel_measured=r.novel_measured,
                measured_sha=judge_measured_sha, novel_sha=judge_novel_sha)
        except PredictionMissing as e:
            raise HTTPException(409, str(e))
        except ValueError as e:
            raise HTTPException(422, str(e))
        # #H1-hardcore (설계감사 frontier 닫기): hard_core 보존을 client self-report bool 이 아니라
        #   negative_heuristic(touched_assumptions ∩ tree.hard_core)로 *구조적으로 파생*. 제출이 touched
        #   가정을 선언하고 그게 tree 의 hard core 를 건드리면(protected≠∅) 아래에서 different_programme 로
        #   강등 — self-report bool(lakatos_hardcore=True)로 위반을 못 숨긴다. touched 미제공 시 레거시 폴백.
        #   잔여 frontier: touched-set 은 아직 제출자 선언 — git-diff ∩ Longinus 로 파생은 후속.
        _hc = pr.get('hard_core') or ''
        if isinstance(_hc, (list, tuple)):   # trees created with array hard_core (e.g. ooptdd_ontology)
            _hc = ','.join(str(x) for x in _hc)
        _raw_core = str(_hc).replace(';', ',').replace('\n', ',')
        _core_tokens = {tok.strip().lower() for tok in _raw_core.split(',') if tok.strip()}
        _touched = [tok.strip().lower() for tok in (r.touched_assumptions or []) if tok and tok.strip()]
        hc_derived = None
        if _touched and _core_tokens:
            from lakatos.programme.heuristic import negative_heuristic
            hc_derived = not negative_heuristic(hard_core=_core_tokens,
                                                refuted_assumptions=_touched)['protected']
        lak_result = None
        have_qual = None not in (r.lakatos_anomaly, r.lakatos_consequence, r.lakatos_excess, r.lakatos_hardcore)
        if have_qual or r.human_verdict_required:
            lak_result = LakatosGate.evaluate(LakatosEvidence(
                theory_laden_anomaly=bool(r.lakatos_anomaly),
                independent_testable_consequence=bool(r.lakatos_consequence),
                excess_empirical_content=bool(r.lakatos_excess),
                hard_core_preserved=(hc_derived if hc_derived is not None else bool(r.lakatos_hardcore)),
                implementation_complete=r.implementation_complete,
                data_branch=r.data_branch,
                data_replay_passed=r.data_replay_passed,
                human_verdict_required=r.human_verdict_required))
        pnr_appraisal = None
        if validated_counterexample_response is not None:
            resp = validated_counterexample_response
            ce_type = validated_counterexample_type
            pgc = None
            if r.ce_proof_concept_name:
                pgc = ProofGeneratedConcept(
                    name=r.ce_proof_concept_name,
                    born_from_counterexample=r.ce_proof_born_from or '',
                    incorporated_lemma=r.ce_proof_incorporated_lemma or '')
            pnr_appraisal = appraise_response(
                resp, excess_content=r.ce_excess_content, novel_corroborated=r.ce_novel_corroborated,
                in_heuristic_spirit=r.ce_in_heuristic_spirit,
                hard_core_preserved=(hc_derived if hc_derived is not None
                                     else (r.lakatos_hardcore if r.lakatos_hardcore is not None else True)),
                counterexample_type=ce_type, proof_generated_concept=pgc)
        decided = dialectical_verdict(v.verdict, pnr_appraisal=pnr_appraisal, lakatos_result=lak_result)
        # AG4/R-SOV V2 재현성 천장(측정주권 2026-07-03): tier 게이트(assurance SSOT)가 무장하고 노드
        #   재현성이 *구조적으로 반증*(reproducible is False: lineage dangling/비-source root)이면
        #   apply_verdict_demotes 가 progressive→partial 천장. ★불가 None(result_path 없음/미검증)은
        #   천장 안 함(부재≠반증, dead-σ) — 라이브 노드(result_path='')는 None → 무회귀.
        _repro = self.reproducible_for_node(name, tag)
        _repro_ceiling = assurance.GATE_REPRODUCIBILITY_CEILING in assurance.gates_for('submit_test_result', tier)
        # DE1: 구조적 강등 체인(#H1-hardcore + AG4 재현성천장 + FF1 novel-anchor)을 순수 정책으로 추출.
        _dec = apply_verdict_demotes(
            decided['verdict'], decided['lakatos'], hc_derived=hc_derived,
            require_novel_anchor=require_novel_anchor, novel=bool(v.novel),
            cross_metric_novel=cross_metric_novel, novel_server_anchored=novel_server_anchored,
            reproducible=_repro, reproducibility_ceiling=_repro_ceiling,
            engine_fresh_fire=fresh_fire)   # jp4 ④: stale/무능력 판관 → provisional 강등(마지막)
        verdict, lakatos_status, novel_independent = _dec.verdict, _dec.lakatos_status, _dec.novel_independent
        # #H1/#H10 질적 backing(서버앵커 독립 novel + ce_novel_corroborated) — DE1 순수 추출.
        qualitative_claim = have_qual or pnr_appraisal is not None
        qual_backed, qual_self_report = qualitative_flags(
            have_qual=qualitative_claim, verdict=verdict,
            novel_server_anchored=novel_server_anchored,
            ce_novel_corroborated=bool(r.ce_novel_corroborated))
        # A1: measurement-grade eureka at the judgement seam — felt(novel registered) vs
        # true(confirmed + substantial BF + net problem closure). Built from the just-scored fields
        # (require_promotion=False: standing lives in the standing layer, not on a node) and persisted
        # in the SAME kg_tx op-list below — atomic with the verdict, no second non-atomic write (B1).
        # opened = questions this node raises (n_opened); closed = 1 if it closes a frontier question.
        # #4 (provenance_reality_derived): eureka BF 의 source_trust 는 client r.source_trust 가 아니라
        # 노드 인터넷 관측 eigentrust 로 재유도 — forged source_trust 로 true-eureka 를 못 산다(credibility 와
        # 동일 원천). internal 노드=1.0. 영속(e.source_trust)도 이 값으로 → tree-level eureka_over_tree 도 정직.
        est = self._eigentrust_source_trust(name, tag)
        eu_input = {
            'novel_registered': bool(pr['nmet']), 'novel_confirmed': novel_independent,
            'verdict': verdict,
            'delta': v.delta, 'noise_band': pr['nb'], 'source_trust': est,
            'opened': int(pr.get('n_opened') or 0),
        }
        # Closure credit is selected only after the managed transaction locks and
        # reads the actual question state. Merely declaring pred_closes is not a
        # solved problem: partial/unverified outcomes must not mint true Eureka.
        eu_open = eureka_classify({**eu_input, 'closed': 0}, require_promotion=False)
        eu_closed = eureka_classify({**eu_input, 'closed': 1}, require_promotion=False)
        eu = eu_open
        ts = datetime.now(timezone.utc).isoformat()
        # AG3/R-SOV V1 값소유(측정주권 2026-07-03): submit 시 *들어온* 값을 서버가 재유도 → 전체 verdict.
        #   persisted 노드가 아니라 incoming(r.script/result_path/metric_value)을 replay 하므로 신규노드도
        #   seal 전에 소유(AG6/V4 ordering 역전 교정 — 기존 producer_replay_for_node 는 아직 persist 안 된
        #   e.metric_value=None 을 읽어 submit 시 항상 not_attempted 로 죽어 있었다). resolve_measurement 이
        #   verified∧regenerated 부분집합에서만 regenerated 를 SSOT 로 치환(SCOPED — 외부/반증값 파괴 금지).
        #   여기서 계산해 next_state·receipt·SET·hist 가 *같은* effective_metric/measurement_grade 를 봉인.
        if replay_inputs_bound:
            # Copy both inputs into a server-private content-addressed cache *before* execution.
            # The scorer never receives the submitter-writable source paths, closing the
            # swap->execute->restore race that pre/post hashing alone cannot detect.
            try:
                if portable_artifact_required:
                    if portable_script_body is None or portable_result_body is None:
                        raise replay_artifact_mod.ReplayArtifactError(
                            'portable capture bytes unavailable'
                        )
                    sealed_script_path = replay_artifact_mod.materialize_snapshot_bytes(
                        body=portable_script_body, source_path=source_script_path,
                        expected_sha256=stored_sha, kind='script',
                        max_bytes=self._SCRIPT_MAX_BYTES)
                    sealed_result_path = replay_artifact_mod.materialize_snapshot_bytes(
                        body=portable_result_body, source_path=source_result_path,
                        expected_sha256=result_sha_before, kind='result',
                        max_bytes=self._RESULT_MAX_BYTES)
                else:
                    sealed_script_path = replay_artifact_mod.materialize_snapshot(
                        source_path=source_script_path, expected_sha256=stored_sha,
                        kind='script', max_bytes=self._SCRIPT_MAX_BYTES)
                    sealed_result_path = replay_artifact_mod.materialize_snapshot(
                        source_path=source_result_path, expected_sha256=result_sha_before,
                        kind='result', max_bytes=self._RESULT_MAX_BYTES)
            except (OSError, replay_artifact_mod.ReplayArtifactError) as exc:
                raise HTTPException(409, f'replay immutable snapshot 실패 — 재제출 필요: {exc}')
            _vo = self.producer_replay_submit(
                sealed_script_path, sealed_result_path, r.metric_value)
            # Private snapshots are still re-hashed after execution as corruption detection.
            result_sha_after, result_path_after, _ = self._recompute_result_sha(
                sealed_result_path)
            script_sha_after, script_info_after = self._recompute_script_sha(sealed_script_path)
            if (result_sha_before != result_sha_after
                    or sealed_result_path != result_path_after
                    or stored_sha != script_sha_after
                    or sealed_script_path != script_info_after.get('path')):
                raise HTTPException(
                    409, 'replay input changed during producer replay (TOCTOU) — 재제출 필요')
            result_sha = result_sha_after
        else:
            # Never pass an out-of-root/missing/unhashed result argument to a scorer.  A successful
            # scorer without immutable input identity is not external verification.
            unbound_reason = (f'unsealed_script:{sha_info.get("reason")}' if not script_replay_bound else
                              f'unsealed_result:{result_info.get("reason")}')
            _vo = ProducerReplayVerdict(
                verified=None, regenerated=None, recorded=r.metric_value,
                reason=unbound_reason)
            result_sha = None
        # AG5/R-SOV V3 + jp5: 권위(attested)는 *트리가 선언한* non-empty allow-list 대비 서명만 —
        #   empty-attestor fallback 자기서명은 authorship('authored', OWNED_GRADES 밖 → G6 fail-closed)
        #   이지 attestation 이 아니다(버리는 키페어로 G6 를 사는 인센티브 역전 봉합). :654 의 fallback
        #   검증 자체는 유지(서명 유효성+verb 바인딩 = sign-X-execute-Y 봉쇄는 self-sign 에도 가치).
        attested_by_allowlist = attested_by_did is not None and bool(attestors)
        authored_self_signed = attested_by_did is not None and not attestors
        effective_metric, measurement_grade, replay_status = resolve_measurement(
            _vo, r.metric_value, attested=attested_by_allowlist, authored=authored_self_signed,
            artifact_bound=replay_inputs_bound)
        # replay_status 는 요약 label 이다. 실제 조치(값 불일치 재실험 vs scorer 계약/실행 수리)를
        # 결정할 수 있도록 서버 판정의 세부 원인과 재생성 값을 별도 진단 provenance 로 보존한다.
        # 아래 v4 verdict receipt에도 함께 봉인해 node cache만 바꿔 운영 진단을 위조할 수 없게 한다.
        replay_reason = _vo.reason if _vo is not None else None
        regenerated_metric = _vo.regenerated if _vo is not None else None
        # S7 temporal witness and S8 MeasurementLock are computed before the verdict receipt so
        # the lock SHA can be sealed and minted atomically with the guarded verdict write.
        # A signed prediction anchor is only T1.  ``ts`` is this process's
        # wall clock and cannot stand in for the independently signed T2
        # verdict anchor required by has_valid_temporal_witness().  The submit
        # contract does not yet carry a verdict anchor, so fail closed at L2.
        temporal_witness = False
        _lock = None
        _lsha = _lkey = _lock_payload_json = _env_sha = None
        if replay_inputs_bound:
            try:
                _env_sha = envfp_mod.fingerprint_sha(envfp_mod.environment_fingerprint())
                deps = [
                    {'path': sealed_script_path, 'sha256': stored_sha},
                    {'path': sealed_result_path, 'sha256': result_sha},
                ]
                _lock = mlock_mod.build_measurement_lock(
                    cmd=replay_command(sealed_script_path, sealed_result_path),
                    deps=deps,
                    params={'metric_name': pr['m'], 'noise_band': pr.get('nb')},
                    env_sha=_env_sha,
                    outs=[{'name': pr['m'], 'value': effective_metric}],
                    measurement_grade=measurement_grade, replay_status=replay_status)
                _lsha, _lkey = mlock_mod.lock_sha(_lock), mlock_mod.lock_key(_lock)
                _lock_payload_json = json.dumps(
                    _lock, sort_keys=True, separators=(',', ':'),
                    ensure_ascii=False, allow_nan=False)
            except Exception as exc:  # noqa: BLE001 — no verified grade may exist without its lock
                raise HTTPException(
                    503, f'MeasurementLock mint 실패 — 판결을 저장하지 않음: {type(exc).__name__}: {exc}')
        next_state = derive_node_state({
            'verdict': verdict,
            'verdict_source': 'scripted',
            'novel_confirmed': novel_independent,
            'metric_value': effective_metric,
            'judged_at': ts,
        })
        # FSM 감사 수리(2026-07-28): before-상태 재유도에 verdict 를 실어야 한다 — 빼면
        # former_canonical/degenerating(engine·human 강등) 노드가 JUDGED_SCRIPTED 로 오판정돼
        # 강등 세탁 재채점이 전이 가드를 침묵 통과했다(읽기 쿼리는 existing_verdict 를 이미 반환).
        _require_state_transition(
            derive_node_state({
                'verdict': pr.get('existing_verdict'),
                'node_state': pr.get('node_state'),
                'verdict_source': pr.get('vsrc'),
                'pred_registered_at': pr.get('pred_registered_at'),
                'pred_metric': pr.get('m'),
                'metric_value': pr.get('existing_metric_value'),
                'judged_at': pr.get('judged_at'),
            }),
            next_state,
        )
        # #M5 (atomic-rescore): 판결 SET 의 *첫 절* 을 원자 CAS claim 으로 — register_prediction 의 원자
        #   write-WHERE 패턴 답습. WHERE (vsrc IS NULL OR vsrc<>'scripted') 가드로 단일 managed-write tx
        #   안에서 동시 submit 중 한쪽만 SET 매칭 → 이중채점(TOCTOU) 봉쇄. judge() 검증을 다 통과한 *뒤*
        #   이 SET 이 실행되므로 거부 시 노드가 빈 scripted 로 잠기지 않는다. RETURN e.tag(claimed)=0행이면
        #   이미 scripted → 아래에서 409. (상단 238행 read-check 는 빠른 거절, 이 가드가 원자 권위.)
        # G1(git-흡수): 이 scripted 판결을 *불변 내용주소 :VerdictReceipt* 로 발행한다. receipt_sha =
        #   sha256(canonical payload) 를 Python 에서 미리 계산(prev=노드의 현 포인터로 체인). 아래 #M5 CAS
        #   *같은 statement* 안에서 SET 직후 MERGE(rec {receipt_sha}) ON CREATE SET + 포인터 전진 →
        #   CAS 가드가 0행이면 receipt 도 안 생김(원자성 보존, 신규 race 창 0). e.verdict 는 체인 head 의 파생 캐시.
        # P0a (ManifestoGap R8): producer replay 상태를 판결에 persist — 채점 스크립트 재실행 검증이
        #   시도됐나/일치했나를 label 로 공시(TOUCH_THE_SKY '영수증은 현실이 끊어 준다'의 관측가능화).
        #   not_attempted = LAKATOS_REPLAY_EXEC off(dead-σ 교정: 검증 불가는 부재지 반증 아님) 또는 미주입;
        #   verified = 재실행 측정이 제출값과 일치; mismatch = 불일치(승격 floor 가 이걸로 차단);
        #   not_replayable = 재실행 시도했으나 실행 불가(CLI 계약 비호환 등 — 2026-07-13, mismatch 오분류 교정).
        #   (replay_status·effective_metric·measurement_grade 는 위 값소유 seam 에서 이미 계산됨.)
        prev_rsha = pr.get('prev_receipt_sha')
        target_id = pr.get('closes')   # q_target_identity_scheme: 선언 의미키(pred_closes)
        # DE1: G1 receipt 봉인필드 조립을 순수 정책으로 추출 — AG3 measurement_grade 봉인(server_regenerated/
        #   client_asserted). metric_value 도 값소유 결과(effective_metric)를 봉인한다.
        # EXTAUDIT S4: 판정 시점 해석층 봉인 — comment 의 sha 를 v3 봉인 필드로(사후 개서는 fsck 가 검출).
        csha = comment_seal_sha(pr.get('node_comment'))
        cycle_request_sha256 = (
            cycle_claim.removeprefix('cycle-') if cycle_claim is not None else None
        )
        sealed_display, sealed_assurance = response_assurance(
            verdict=verdict,
            current_receipt_sha='pending-v6-receipt',
            measurement_grade=measurement_grade,
            replay_status=replay_status,
            assurance_tier_resolved=tier,
            attested_by_did=attested_by_did,
            engine_rule_sha=ENGINE_RULE_SHA,
            tree_attestors=attestors,
            engine_rule_floor=effective_floor(),
            temporal_witness=temporal_witness,
            measurement_lock_bound=bool(_lsha),
        )
        sealed_assurance = {
            'val': sealed_assurance['val'],
            'basis': list(sealed_assurance.get('basis') or ()),
        }
        sealed_eureka_open = {
            'felt': eu_open.felt,
            'true': eu_open.true,
            'hallucinated': eu_open.hallucinated,
            'reasons': list(eu_open.reasons),
            'bf': round(eu_open.bf, 3),
        }
        sealed_eureka_closed = {
            'felt': eu_closed.felt,
            'true': eu_closed.true,
            'hallucinated': eu_closed.hallucinated,
            'reasons': list(eu_closed.reasons),
            'bf': round(eu_closed.bf, 3),
        }
        test_result_summary = dict(
            value=effective_metric,
            baseline=pr['b'],
            delta=round(v.delta, 4),
            verdict=verdict,
            script=sealed_script_path,
            result_path=sealed_result_path,
            source_script_path=source_script_path,
            source_result_path=source_result_path,
            result_sha256=result_sha,
            measurement_lock_sha=_lsha,
            novel=v.novel,
            script_sha=stored_sha,
            freshen=freshen_anchor,
            replay_status=replay_status,
            replay_reason=replay_reason,
            regenerated_metric=regenerated_metric,
            lakatos=lakatos_status,
            metric_verdict=v.verdict,
            novel_server_anchored=novel_server_anchored,
            requires_human=bool(decided.get('requires_human')),
            script_sha_server_verified=sha_verified,
            rule=v.reason,
            attested_by=attested_by_did,
            cycle_claim=cycle_claim,
            cycle_request_sha256=cycle_request_sha256,
            request_sha256=submit_request_sha256,
            verdict_display=sealed_display,
            assurance=sealed_assurance,
            qualitative_self_report=qual_self_report,
            replay_authoritative=bool(replay_inputs_bound and _lsha is not None),
            eureka_open=sealed_eureka_open,
            eureka_closed=sealed_eureka_closed,
        )
        history_payload_sha256 = verdict_history_payload_sha(test_result_summary)
        receipt_fields = build_receipt_fields(
            tree=name, tag=tag, target_id=target_id, verdict=verdict, metric_name=pr['m'],
            metric_value=effective_metric, novel_confirmed=novel_independent, lakatos_status=lakatos_status,
            judged_at=ts, judge_script_sha=stored_sha, prev_receipt_sha=prev_rsha,
            measurement_grade=measurement_grade,
            engine_rule_sha=ENGINE_RULE_SHA,   # jp1: 판관 정체성 봉인(v2) — 명시 전달(가드가 핀)
            comment_sha=csha,   # S4: 해석층 봉인(v3) — 명시 전달
            replay_status=replay_status, replay_reason=replay_reason,
            regenerated_metric=regenerated_metric,
            judge_script_path=sealed_script_path, result_path=sealed_result_path,
            result_sha256=result_sha, measurement_lock_sha=_lsha,
            source_script_path=source_script_path,
            source_result_path=source_result_path,
            history_payload_sha256=history_payload_sha256,
            prediction_temporal_commitment_sha256=(
                prediction_temporal_commitment_sha256
            ))
        rsha = receipt_content_sha(receipt_fields)
        test_result_event_id = f'ob-test-result-{rsha}'
        test_result_payload = dict(test_result_summary, receipt_sha=rsha)
        try:
            test_result_payload_json = validate_history_record(
                name,
                'test_result',
                tag,
                test_result_payload,
                test_result_event_id,
            )
        except HistoryPayloadError as exc:
            raise HTTPException(
                422, 'test result history contains text PostgreSQL JSONB cannot represent'
            ) from exc
        question_close_event_id = f'ob-question-close-{rsha}'
        question_close_payload = {
            'question': target_id,
            'trigger': 'ADJUDICATED',
            'verdict': verdict,
            'receipt_sha': rsha,
        }
        question_close_payload_json = None
        if target_id:
            try:
                question_close_payload_json = validate_history_record(
                    name,
                    'question_close',
                    tag,
                    question_close_payload,
                    question_close_event_id,
                )
            except HistoryPayloadError as exc:
                raise HTTPException(
                    422,
                    'question close history contains text PostgreSQL JSONB cannot represent',
                ) from exc
        close_question_from_verdict = bool(
            target_id and receipt_backed_conclusive(
                verdict,
                rsha,
                assurance_level=sealed_assurance['val'],
                qualitative_self_report=qual_self_report,
            )
        )
        cycle_event_id = None
        cycle_payload = None
        cycle_payload_json = None
        cycle_payload_closed = None
        cycle_payload_closed_json = None
        if cycle_claim is not None:
            suffix = cycle_claim.removeprefix('cycle-')
            cycle_event_id = f'ob-cycle-result-{suffix}'
            cycle_payload = {
                'cycle_claim': cycle_claim,
                'cycle_request': cycle_request,
                'verdict_receipt_sha': rsha,
                'dependent_history_event_ids': [test_result_event_id],
                'result': {
                    'verdict': verdict,
                    'novel': v.novel,
                    'lakatos': lakatos_status,
                    'delta': round(v.delta, 4),
                    'novel_server_anchored': novel_server_anchored,
                },
            }
            cycle_payload_closed = {
                **cycle_payload,
                'dependent_history_event_ids': [
                    test_result_event_id,
                    *(
                        [question_close_event_id]
                        if close_question_from_verdict else []
                    ),
                ],
            }
            try:
                cycle_payload_json = validate_history_record(
                    name,
                    'cycle_result',
                    tag,
                    cycle_payload,
                    cycle_event_id,
                )
                cycle_payload_closed_json = validate_history_record(
                    name,
                    'cycle_result',
                    tag,
                    cycle_payload_closed,
                    cycle_event_id,
                )
            except HistoryPayloadError as exc:
                raise HTTPException(
                    422,
                    'cycle result history contains text PostgreSQL JSONB cannot represent',
                ) from exc
        # The adjudication event is the immutable verdict receipt itself.  Keep the persisted
        # QuestionClosure identity and q.closed_events exactly aligned with the FSM effect binding
        # (RecordQuestionClosure.event_id = event.receipt_sha); manual CLOSE events retain their
        # separate operator-supplied/stable identifiers in TreeService.
        closure_id = rsha if target_id else None
        ops = [(("""MATCH (t:LakatosTree {name:$tree})
                   """ + LOCKED_BUDGET_GUARD + """
                   MATCH (t)-[:HAS_NODE]->(e {tag:$tag})
                   SET e._cas = coalesce(e._cas,0) + 0
                   WITH t, e
                   OPTIONAL MATCH (e)-[:HAS_PREDICTION_TEMPORAL_COMMITMENT]->
                     (temporal_commitment:PredictionTemporalCommitment)
                   WITH t, e,
                     [item IN collect(temporal_commitment) WHERE item IS NOT NULL]
                       AS temporal_commitments
                   WHERE ($prediction_temporal_commitment_sha256 IS NULL
                          AND size(temporal_commitments)=0)
                      OR ($prediction_temporal_commitment_sha256 IS NOT NULL
                          AND size(temporal_commitments)=1
                          AND temporal_commitments[0].commitment_sha256=
                            $prediction_temporal_commitment_sha256
                          AND temporal_commitments[0].prediction_receipt_sha256=
                            e.pred_receipt_sha
                          AND temporal_commitments[0].authority_policy_sha256=
                            $prediction_temporal_policy_sha256)
                   WITH t, e
                   OPTIONAL MATCH (history_prior:OutboxEntry)
                     WHERE history_prior.id IN $history_event_ids
                   WITH t, e,
                        [o IN collect(history_prior) WHERE o IS NOT NULL] AS history_priors
                   WHERE size(history_priors)=0
                     AND (e.verdict_source IS NULL OR e.verdict_source <> 'scripted'
                      OR ($freshen AND e.verdict = 'partial'
                          AND e.lakatos_status IN ['novel_not_server_anchored', 'provisional_stale_engine']
                          AND e.metric_value = $mv))
                     AND coalesce(e.current_receipt_sha,'') = coalesce($prev_rsha,'')
                   OPTIONAL MATCH (t)-[:HAS_FRONTIER]->(q:OpenQuestion {name:$target_id})
                   WITH t, e, q
                   WHERE NOT $has_target OR q IS NOT NULL
                   FOREACH (_ IN CASE WHEN q IS NULL THEN [] ELSE [1] END |
                     SET q._cas=coalesce(q._cas, 0) + 0)
                   WITH t, e, q,
                     CASE WHEN q IS NULL THEN null
                          ELSE coalesce(q.status, $open_state) END AS question_before_state
                   WHERE NOT $has_target
                      OR question_before_state IN [$open_state, $closed_state]
                   SET e.metric_name=$mn, e.metric_value=$mv, e.verdict=$v,
                       e.verdict_source='scripted', e.node_state=$node_state,
                       e.judge_script=$script, e.judge_script_sha=$sha,
                       e.result_path=$rp, e.result_sha256=$result_sha256, e.judged_at=$ts,
                       e.source_judge_script_path=$source_script,
                       e.source_result_path=$source_rp,
                       e.novel_confirmed=$novel, e.source_trust=$st, e.lakatos_status=$lstat,
                       e.qualitative_self_report=$qsr,
                       e.novel_server_anchored=$nsa, e.assurance_tier_resolved=$atier,
                       e.attested_by_did=$attested_by_did, e.replay_status=$replay_status,
                       e.replay_reason=$replay_reason, e.regenerated_metric=$regenerated_metric,
                       e.measurement_grade=$mg, e.comment_sha_at_verdict=$csha,
                       e.engine_freshness=$efresh, e.judged_by_boot_git_sha=$boot_sha,
                       e.measurement_lock_sha=$lsha, e.measurement_lock_key=$lkey,
                       e.temporal_witness_verified=$tw
                   WITH t, e, q, question_before_state
                   MERGE (rec:VerdictReceipt {receipt_sha:$rsha})
                     ON CREATE SET rec.tree=$tree, rec.tag=$tag, rec.target_id=$target_id,
                       rec.verdict=$v, rec.verdict_source='scripted', rec.metric_name=$mn,
                       rec.metric_value=$mv, rec.novel_confirmed=$novel, rec.lakatos_status=$lstat,
                       rec.judged_at=$ts, rec.judge_script_sha=$sha, rec.prev_receipt_sha=$prev_rsha,
                       rec.measurement_grade=$mg, rec.engine_rule_sha=$engine_rule_sha,
                       rec.comment_sha=$csha, rec.replay_status=$replay_status,
                       rec.replay_reason=$replay_reason, rec.regenerated_metric=$regenerated_metric,
                       rec.judge_script_path=$script, rec.result_path=$rp,
                       rec.result_sha256=$result_sha256, rec.measurement_lock_sha=$lsha,
                       rec.source_script_path=$source_script,
                       rec.source_result_path=$source_rp,
                       rec.history_payload_sha256=$history_payload_sha256,
                       rec.prediction_temporal_commitment_sha256=
                         $prediction_temporal_commitment_sha256
                   MERGE (e)-[:HAS_RECEIPT]->(rec)
                   SET e.current_receipt_sha=$rsha
                   FOREACH (_ IN CASE WHEN $lsha IS NULL THEN [] ELSE [1] END |
                     MERGE (ml:MeasurementLock {lock_sha:$lsha})
                     SET ml.lock_key=$lkey, ml.cmd=$lock_cmd, ml.env_sha=$lock_env,
                         ml.measurement_grade=$mg, ml.replay_status=$replay_status,
                         ml.payload_json=$lock_payload_json
                     MERGE (e)-[:HAS_LOCK]->(ml)
                   )
                   WITH e, rec, q, question_before_state,
                     ($close_question AND question_before_state = $open_state) AS question_closed
                   FOREACH (_ IN CASE WHEN question_closed THEN [1] ELSE [] END |
                     SET q.status=$closed_state,
                         q.n_visits=coalesce(q.n_visits, 0) + 1,
                         q.closed_by=CASE
                           WHEN q.closed_by IS NULL THEN [$tag]
                           WHEN $tag IN q.closed_by THEN q.closed_by
                           ELSE q.closed_by + $tag
                         END,
                         q.closed_events=CASE
                           WHEN q.closed_events IS NULL THEN [$closure_id]
                           WHEN $closure_id IN q.closed_events THEN q.closed_events
                           ELSE q.closed_events + $closure_id
                         END
                     MERGE (c:QuestionClosure {id:$closure_id})
                     ON CREATE SET c.closed_by=$tag, c.at=$ts, c.tree=$tree,
                                   c.question=$target_id, c.trigger='ADJUDICATED',
                                   c.verdict=$v, c.receipt_sha=$rsha
                     MERGE (q)-[:HAS_CLOSURE]->(c)
                     MERGE (e)-[cq:CLOSES_QUESTION]->(q)
                     SET cq.receipt_sha=$rsha, cq.verdict=$v, cq.at=$ts
                     MERGE (c)-[:CAUSED_BY]->(rec)
                   )
                   SET e.eureka_felt=CASE WHEN question_closed THEN $eu_closed_felt ELSE $eu_open_felt END,
                       e.eureka_true=CASE WHEN question_closed THEN $eu_closed_true ELSE $eu_open_true END,
                       e.eureka_hallucinated=CASE WHEN question_closed THEN $eu_closed_hall ELSE $eu_open_hall END,
                       e.eureka_reasons=CASE WHEN question_closed THEN $eu_closed_reasons ELSE $eu_open_reasons END,
                       e.eureka_bf=CASE WHEN question_closed THEN $eu_closed_bf ELSE $eu_open_bf END
                   CREATE (test_history:OutboxEntry {
                     id:$test_result_event_id, tree:$tree, op:'test_result',
                     node_tag:$tag, payload:$test_result_payload,
                     status:'pending', created_at:$ts,
                     reason:'test_result_commit_intent',
                     receipt_sha:$rsha, causal_group:$rsha, causal_index:0,
                     request_sha256:$submit_request_sha256
                   })
                   FOREACH (_ IN CASE WHEN question_closed THEN [1] ELSE [] END |
                     CREATE (:OutboxEntry {
                       id:$question_close_event_id, tree:$tree, op:'question_close',
                       node_tag:$tag, payload:$question_close_payload,
                       status:'pending', created_at:$ts,
                       reason:'question_close_commit_intent',
                       receipt_sha:$rsha, causal_group:$rsha, causal_index:1
                     }))
                   FOREACH (_ IN CASE WHEN $cycle_event_id IS NULL THEN [] ELSE [1] END |
                     CREATE (:OutboxEntry {
                       id:$cycle_event_id, tree:$tree, op:'cycle_result',
                       node_tag:$tag,
                       payload:CASE WHEN question_closed
                                    THEN $cycle_payload_closed
                                    ELSE $cycle_payload END,
                       status:'pending', created_at:$ts,
                       reason:'cycle_result_commit_intent',
                       receipt_sha:$rsha, causal_group:$rsha, causal_index:2
                     }))
                   RETURN e.tag AS claimed, question_before_state, question_closed,
                          CASE WHEN question_closed THEN $closed_state
                               ELSE question_before_state END AS question_state"""),
                dict(tree=name, tag=tag, mn=pr['m'], mv=effective_metric, v=verdict,
                     mg=measurement_grade,   # AG3: 측정 출처등급(server_regenerated/client_asserted) 봉인
                     freshen=freshen_anchor,   # novel-anchor freshen: CAS 탈출은 앵커-데모트 partial 동일값 재제출만
                     script=sealed_script_path, sha=stored_sha, rp=sealed_result_path,
                     source_script=source_script_path, source_rp=source_result_path,
                     history_payload_sha256=history_payload_sha256,
                     prediction_temporal_commitment_sha256=(
                         prediction_temporal_commitment_sha256
                     ),
                     prediction_temporal_policy_sha256=(
                         prediction_temporal_policy_sha256
                     ),
                     result_sha256=result_sha, ts=ts, novel=novel_independent,
                     node_state=next_state.value,
                     st=est, lstat=lakatos_status, qsr=qual_self_report,
                     nsa=(novel_server_sha is not None),   # FF1 phase1: cross-metric novel 서버앵커 여부(가시성, 점수 불변)
                     atier=tier,   # G6 S5: 이 판결이 어느 tier 로 resolve 됐는지 스탬프(fsck tier-resolve 흔적)
                     attested_by_did=attested_by_did,   # G10: author=서명 유도(client 문자열 아님), 무cert=null
                     replay_status=replay_status,   # P0a: producer replay 상태(not_attempted/verified/mismatch/not_replayable)
                     replay_reason=replay_reason, regenerated_metric=regenerated_metric,
                     rsha=rsha, target_id=target_id, prev_rsha=prev_rsha,   # G1: 내용주소 receipt + 체인 포인터
                     has_target=bool(target_id),
                     close_question=close_question_from_verdict,
                     closure_id=closure_id, open_state='OPEN', closed_state='CLOSED',
                     engine_rule_sha=ENGINE_RULE_SHA,   # jp1: 판관 정체성(v2 봉인 필드) persist — 누락=위양성 mismatch
                     csha=csha,   # S4: 판정 시점 comment 봉인 미러 + receipt v3 필드 persist
                     cycle_event_id=cycle_event_id,
                     cycle_payload=cycle_payload_json,
                     cycle_payload_closed=cycle_payload_closed_json,
                     test_result_event_id=test_result_event_id,
                     test_result_payload=test_result_payload_json,
                     question_close_event_id=question_close_event_id,
                     question_close_payload=question_close_payload_json,
                     history_event_ids=[
                         test_result_event_id,
                         *([question_close_event_id] if target_id else []),
                         *([cycle_event_id] if cycle_event_id is not None else []),
                     ],
                     submit_request_sha256=submit_request_sha256,
                     lsha=_lsha, lkey=_lkey,
                     lock_cmd=(_lock or {}).get('cmd'), lock_env=_env_sha,
                     lock_payload_json=_lock_payload_json, tw=temporal_witness,
                     efresh=efresh,                     # jp4: 판관 자기진단 관측화(unchecked/fresh/stale_code/incapable/indeterminate)
                     boot_sha=(fresh or {}).get('boot_git_sha'),   # jp4: 노드-레벨 판관 신원 provenance(영수증 봉인은 jp1 engine_rule_sha 가 정본)
                     eu_open_felt=eu_open.felt, eu_open_true=eu_open.true,
                     eu_open_hall=eu_open.hallucinated,
                     eu_open_reasons=list(eu_open.reasons), eu_open_bf=round(eu_open.bf, 6),
                     eu_closed_felt=eu_closed.felt, eu_closed_true=eu_closed.true,
                     eu_closed_hall=eu_closed.hallucinated,
                     eu_closed_reasons=list(eu_closed.reasons), eu_closed_bf=round(eu_closed.bf, 6),
                     forceful=sorted(FORCEFUL_SOURCES)))]
        for tr in prov_triples(name, tag, sealed_script_path, sealed_result_path,
                               verdict, stored_sha, ts):
            if tr.get('kind'):
                ops.append(("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->
                                   (e {tag:$tag, current_receipt_sha:$rsha})
                      MERGE (p:ProvNode {id:$id}) SET p.kind=$kind, p.type=$type, p.sha256=$sha
                      MERGE (e)-[:HAS_PROV]->(p)""",
                            dict(tree=name, tag=tag, rsha=rsha, id=tr['id'], kind=tr['kind'],
                                 type=tr.get('type'), sha=tr.get('sha256'))))
            else:
                ops.append(("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->
                                   (e {tag:$tag, current_receipt_sha:$rsha})
                      MERGE (a:ProvNode {id:$f}) MERGE (b:ProvNode {id:$to})
                      MERGE (a)-[rel:PROV_REL {kind:$rk}]->(b)""",
                            dict(tree=name, tag=tag, rsha=rsha,
                                 f=tr['from'], to=tr['to'], rk=tr['rel'])))
        # R6(후속 PROM): pre-commit fsck 시트 — 이제 쓸 record 를 *쓰기 전에* 같은 체커(boundary_fsck ==
        #   fsck_node == 감사)로 검사. 정상 경로는 by-construction 통과(prereg 필수·tier/receipt 스탬프
        #   동봉)라 이 시트의 가치는 활성 필터가 아니라 **드리프트 보험**: 미래의 어떤 write 경로 변경이
        #   스탬프를 빠뜨리면 라이브에서 즉시 422(원자성 무훼손 — kg_tx 이전 거부, 잠긴 노드 없음).
        #   prereg 다리: judge() 가 이미 PredictionMissing 으로 구조 강제하므로(여기 도달 = pred_metric
        #   실재), 시트에는 실측 timestamp 또는 metric-등록 증거를 싣는다 — 시트의 실이빨은 tier/원장
        #   스탬프 드리프트(레거시 read-double 이 timestamp 필드를 안 실어도 prereg 로 오발화하지 않음).
        _prospective = dict(verdict=verdict, verdict_source='scripted',
                            pred_registered_at=(pr.get('pred_registered_at')
                                                or ('(pred-metric-registered)' if pr.get('m') else None)),
                            judged_at=ts,
                            source_trust=est, assurance_tier_resolved=tier,
                            current_receipt_sha=rsha, qualitative_self_report=qual_self_report)
        _seat = audit_fsck.boundary_fsck(_prospective)
        if _seat:
            raise HTTPException(422, f'pre-commit fsck 거부(쓰기 전 — 원장/스탬프 드리프트): '
                                     f'{[(f.check_id, f.severity) for f in _seat]}')
        try:
            tx_result = self._ledger_transaction(GuardedKgOps(ops))
        except WriterFenceLost:
            raise
        except KgTxGuardFailed:
            raise_after_locked_budget_rejection(
                self.kg, name, 'submit_test_result'
            )
            raise HTTPException(
                409, '동시/재채점 차단 — receipt tip CAS 불일치(트랜잭션 전체 rollback)')
        # #M5: 원자 CAS claim 결과 판정 — 첫 op(가드된 판결 SET)이 0행이면 동시 submit 이 이미 점유 → 409.
        #   per-op 결과 shape(len==ops, 각 op 의 .data() 리스트)일 때만 검사(실제 KG 트랜잭션). 그 외(미모델
        #   테스트 더블/None)는 상단 read-check 가 권위 — 하위호환 보존(좁은 검사로 거짓 409 회피).
        if (isinstance(tx_result, list) and len(tx_result) == len(ops)
                and isinstance(tx_result[0], list) and not tx_result[0]):
            raise HTTPException(409, '동시/재채점 차단 — 이미 scripted (원자 CAS claim 0행; 새 노드로 분기할 것)')
        first_row = (tx_result[0][0]
                     if isinstance(tx_result, list) and tx_result
                     and isinstance(tx_result[0], list) and tx_result[0]
                     and isinstance(tx_result[0][0], dict) else {})
        question_closed = bool(first_row.get('question_closed'))
        if cycle_event_id is not None and question_closed:
            cycle_payload = cycle_payload_closed
        question_before_state = first_row.get('question_before_state')
        question_state = first_row.get('question_state')
        question_transition = None
        if target_id and question_before_state in {state.value for state in QuestionState}:
            question_transition = step_question(
                QuestionState(question_before_state),
                QuestionEvent.ADJUDICATED,
                verdict=verdict,
                receipt_sha=rsha,
                assurance_level=sealed_assurance['val'],
                qualitative_self_report=qual_self_report,
            )
        eu = eu_closed if question_closed else eu_open
        test_projected = self.hist(
            name,
            'test_result',
            tag,
            test_result_payload,
            event_id=test_result_event_id,
        )
        history_pending = test_projected is False
        if test_projected is False:
            if cycle_event_id is not None:
                raise HTTPException(
                    503, 'test result history pending; causal successors deferred'
                )
        if question_closed and test_projected is not False:
            close_projected = self.hist(
                name,
                'question_close',
                tag,
                question_close_payload,
                event_id=question_close_event_id,
            )
            if close_projected is False:
                history_pending = True
                if cycle_event_id is not None:
                    raise HTTPException(
                        503, 'question close history pending; causal successors deferred'
                    )
        # EXTAUDIT S3b/S7b: VAL 재도출 — L3 은 attestation(allow-list)+engine floor+temporal witness 가 다 설 때.
        response = {'ok': True, 'freshen': freshen_anchor,
                'history_pending': history_pending,
                'verdict': verdict, 'verdict_display': sealed_display,
                'assurance': sealed_assurance,
                'delta': round(v.delta, 4), 'novel': v.novel,
                'novel_server_anchored': novel_server_anchored,
                'lakatos': lakatos_status, 'metric_verdict': v.verdict,
                'requires_human': bool(decided.get('requires_human')),
                # #H3: sha 영수증이 서버 파일재계산으로 검증됐는지(False=inline/미존재 → 정직 fallback, client 값).
                'script_sha_server_verified': sha_verified, 'judge_script_sha': stored_sha,
                'judge_script_path': sealed_script_path,
                'result_path': sealed_result_path, 'result_sha256': result_sha,
                'source_script_path': source_script_path,
                'source_result_path': source_result_path,
                'measurement_lock_sha': _lsha,
                'verdict_receipt_sha256': rsha,
                'prediction_temporal_commitment_sha256': (
                    prediction_temporal_commitment_sha256
                ),
                'replay_status': replay_status, 'replay_reason': replay_reason,
                'regenerated_metric': regenerated_metric,
                'question': ({'target': target_id, 'closed': question_closed,
                              'state': question_state,
                              'transition': (question_transition.transition_id
                                             if question_transition else None)}
                             if target_id else None),
                # G10: authorship 은 서명에서 유도(무cert=None) — client 문자열이 아니다.
                'attested_by': attested_by_did,
                'eureka': (sealed_eureka_closed if question_closed
                           else sealed_eureka_open),
                'rule': v.reason,
                'replay_authoritative': test_result_summary['replay_authoritative'],
                'replay': (replay_command(sealed_script_path, sealed_result_path)
                           if replay_inputs_bound and _lsha is not None else None)}
        if cycle_event_id is not None:
            response['_cycle_event_id'] = cycle_event_id
            response['_cycle_payload'] = cycle_payload
        return response

    def load_receipt_chain(self, name: str, tag: str) -> dict:
        """노드의 :VerdictReceipt 체인 + 현 포인터 로드(G1). fold/verify 의 read 경로."""
        head_rows = self.kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                     RETURN e.current_receipt_sha AS head, e.verdict AS cache_verdict,
                            e.verdict_source AS cache_source""", tree=name, tag=tag)
        if not head_rows:
            raise HTTPException(404, f'노드 없음: {tag}')
        h = head_rows[0]
        # C1 S3-engine: receipt_kind + prediction 봉인필드도 노출 — 외부검증자(c1verify)가 read 표면
        #   바이트만으로 prediction blob 을 재유도(sha 재계산)할 수 있어야 한다(포인터 신뢰 금지).
        # jp1: verdict 봉인필드(tree/tag/target_id/metric_value/novel_confirmed/lakatos_status/
        #   measurement_grade/engine_rule_sha)도 전량 노출 — v1/v2 verdict blob 재유도가 같은 표면에서
        #   성립(jp3 recompute·외부검증자 소비). judged_at 는 기존 노출분 재사용 불가라 명시 추가.
        recs = self.kg("""MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})-[:HAS_RECEIPT]->(r:VerdictReceipt)
                     RETURN r.receipt_sha AS receipt_sha, r.prev_receipt_sha AS prev_receipt_sha,
                            r.verdict AS verdict, r.verdict_source AS verdict_source,
                            r.receipt_kind AS receipt_kind, r.metric_name AS metric_name,
                            r.direction AS direction, r.baseline_value AS baseline_value,
                            r.noise_band AS noise_band, r.scale_type AS scale_type,
                            r.novel_prediction AS novel_prediction, r.novel_metric AS novel_metric,
                            r.novel_direction AS novel_direction, r.novel_threshold AS novel_threshold,
                            r.judge_script_sha AS judge_script_sha, r.closes_question AS closes_question,
                            r.credence AS credence, r.baseline_lineage AS baseline_lineage,
                            r.registered_at AS registered_at,
                            r.anchor_bundle_sha256 AS anchor_bundle_sha256,
                            r.anchor_bundle_json AS anchor_bundle_json,
                            r.tree AS tree, r.tag AS tag, r.target_id AS target_id,
                            r.metric_value AS metric_value, r.novel_confirmed AS novel_confirmed,
                            r.lakatos_status AS lakatos_status, r.judged_at AS judged_at,
                            r.measurement_grade AS measurement_grade,
                            r.engine_rule_sha AS engine_rule_sha, r.comment_sha AS comment_sha,
                            r.replay_status AS replay_status, r.replay_reason AS replay_reason,
                            r.regenerated_metric AS regenerated_metric,
                            r.judge_script_path AS judge_script_path,
                            r.result_path AS result_path, r.result_sha256 AS result_sha256,
                            r.measurement_lock_sha AS measurement_lock_sha,
                            r.source_script_path AS source_script_path,
                            r.source_result_path AS source_result_path,
                            r.history_payload_sha256 AS history_payload_sha256,
                            r.prediction_temporal_commitment_sha256 AS
                              prediction_temporal_commitment_sha256""",
                     tree=name, tag=tag)
        result = {'head': h.get('head'), 'cache_verdict': h.get('cache_verdict'),
                  'cache_source': h.get('cache_source'), 'receipts': list(recs or [])}
        temporal_provider = getattr(self, 'temporal_proof_provider', None)
        if temporal_provider is not None:
            temporal_proof = temporal_provider(
                name,
                {tag: h.get('head')},
            ).get(tag)
            if temporal_proof is not None:
                result['temporal_proof'] = temporal_proof.public_dict()
        return result

    def verify_verdict_chain(self, name: str, tag: str) -> dict:
        """G1 rebuild_verify(verdict 판): 체인 fold 로 현재 verdict 를 *재유도*해 e.verdict 캐시와 대조.

        캐시를 손상시키면(또는 포인터 dangling) 불일치/ReceiptChainBroken 으로 검출 — '캐시 신뢰 금지, 재유도가 판관'.
        """
        chain = self.load_receipt_chain(name, tag)
        folded = fold_receipt_chain(chain['receipts'], chain['head'],
                                    cache_verdict=chain['cache_verdict'], cache_source=chain['cache_source'])
        ok = folded['verdict'] == chain['cache_verdict']
        result = {'ok': ok, 'rederived': folded['verdict'], 'cache': chain['cache_verdict'],
                  'from_receipt': folded['from_receipt']}
        if 'temporal_proof' in chain:
            result['temporal_proof'] = chain['temporal_proof']
        return result

    @_serialized_ledger_command
    def demote_stale_canonical(self, name: str, *, dry_run: bool = True) -> dict:
        """jp1 stale-CANONICAL 재심 스윕(opt-in ops verb) — '오늘 판관이면 이걸 여전히 CANONICAL 이라
        부를까?'를 원장 수준에서 집행. head receipt 의 sealed engine_rule_sha 가 유효 floor
        (docs/data/engine_rule_floor.json 선언분 ∪ 현 ENGINE_RULE_SHA) 밖이면 — v1 legacy 의 필드 부재
        (익명 판관) 포함 — 재심 전까지 former_canonical 강등 + v2 engine receipt mint(원장 append,
        app.py AGM per-tag CAS 패턴 계승). dry_run 기본 true = 후보 열거만(비파괴 기본off).
        인간 잠금(valid_until_rebutted=false)은 강등하지 않고 skipped_locked 로 보고만.
        demoted 카운트가 novel 오라클(stale_canonical_auto_demoted)의 실측값."""
        floor = effective_floor()
        if not dry_run:
            self._require_ledger_ready()
        rows = self.kg('''MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {verdict:'CANONICAL'})
                  OPTIONAL MATCH (e)-[:HAS_RECEIPT]->(r:VerdictReceipt {receipt_sha:e.current_receipt_sha})
                  RETURN e.tag AS tag, e.current_receipt_sha AS prev_rsha,
                         r.engine_rule_sha AS ers,
                         coalesce(e.valid_until_rebutted, true) AS vur''', tree=name)
        stale = [x for x in (rows or []) if x.get('ers') not in floor]
        locked = [x['tag'] for x in stale if x.get('vur') is False]
        candidates = [x for x in stale if x.get('vur') is not False]
        out = {'tree': name, 'dry_run': dry_run, 'floor_size': len(floor),
               'canonical_total': len(rows or []),
               'candidates': [{'tag': x['tag'], 'sealed_engine_rule_sha': x.get('ers')}
                              for x in candidates],
               'skipped_locked': locked, 'demoted': []}
        if dry_run:
            return out
        for candidate in candidates:
            self._project_pending_admin_predecessors(name, candidate['tag'])
        ts = datetime.now(timezone.utc).isoformat()
        for x in candidates:
            prev = x.get('prev_rsha')
            rsha = receipt_content_sha(dict(
                tree=name, tag=x['tag'], target_id=None, verdict='former_canonical',
                verdict_source='engine', metric_name=None, metric_value=None,
                novel_confirmed=None, lakatos_status=None, judged_at=ts,
                judge_script_sha=None, prev_receipt_sha=prev, engine_rule_sha=ENGINE_RULE_SHA))
            done = self._ledger_write('''MATCH (t:LakatosTree {name:$tree})
                      SET t._tree_write_cas=coalesce(t._tree_write_cas,0)+0
                      WITH t
                      MATCH (t)-[:HAS_NODE]->(e {tag:$tag})
                      WHERE e.verdict='CANONICAL'
                        AND coalesce(e.current_receipt_sha,'') = coalesce($prev,'')
                      SET e.verdict='former_canonical', e.verdict_source='engine',
                          e.current_best_pointer=false, e.node_state=$former_state,
                          e.demoted_at=$ts, e.stale_engine_rule_demoted_at=$ts
                      MERGE (rec:VerdictReceipt {receipt_sha:$rsha})
                        ON CREATE SET rec.tree=$tree, rec.tag=$tag, rec.verdict='former_canonical',
                          rec.verdict_source='engine', rec.judged_at=$ts, rec.prev_receipt_sha=$prev,
                          rec.engine_rule_sha=$engine_rule_sha
                      MERGE (e)-[:HAS_RECEIPT]->(rec)
                      SET e.current_receipt_sha=$rsha
                      RETURN e.tag AS tag''',
                           tree=name, tag=x['tag'], prev=prev, rsha=rsha, ts=ts,
                           former_state=NodeState.FORMER_CANONICAL.value,
                           engine_rule_sha=ENGINE_RULE_SHA)
            if done:
                out['demoted'].append(x['tag'])
                self.hist(name, 'stale_engine_demotion', x['tag'],
                          {'sealed': x.get('ers'), 'floor_size': len(floor), 'receipt_sha': rsha})
        return out
