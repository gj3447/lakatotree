"""Chunked KG writer for Lakatos tree mutations.

# KG: seed-lkt-engine-mutation-writer-20260616
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from lakatos import assurance
from lakatos.node_state import NodeState
from lakatos.verdicts import FORCEFUL_SOURCES, is_self_report_blocked_verdict
from server.contexts.tree.schemas import NodeIn, ParentEdgeIn, QuestionIn
from server.ports import KgTx

# G1(git-흡수 2026-07-02, S3 봉합): 노드-쓰기는 verdict 의 유일 발행처가 아니다 — 채점(scripted/engine/…)은
#   judgement_service 가 CAS 로 쓴다. 그런데 add_node/upsert_nodes 가 verdict/node_state/metric_* 를 무가드
#   블랭킷 SET 해, 이미 채점된 tag 를 같은 tag 로 다시 쓰면 scripted 'rejected'(BF 1/6)가 draft 'proof' 로 덮여
#   부적 증거가 credence 에서 지워졌다(H9 리터럴 스캐너가 못 보는 파라미터화 SET). git 의 first-write-wins
#   발행(object-file.c:408-472: 이미 바인딩된 이름은 재바인딩 불가)을 이식: 기존 노드의 verdict_source 가
#   *영수증*(FORCEFUL_SOURCES)이면 verdict-bearing 필드를 MATCH 시 보존, 아니면(draft) 정상 갱신. DB-side CASE 라
#   원자적(읽고-쓰기 race 없음). verdict *권위*는 여전히 judge/set_verdict 층에 — writer 는 파괴만 못 한다.
#   verdict-bearing 필드만 CASE 로 가드; 메타(comment/algorithm/script/…)는 항상 갱신(draft 편집 보존).
_FORCEFUL = sorted(FORCEFUL_SOURCES)
_PRESERVE_IF_SCORED = (
    "e.verdict = CASE WHEN coalesce(e.verdict_source,'') IN $forceful THEN e.verdict ELSE {v} END, "
    "e.node_state = CASE WHEN coalesce(e.verdict_source,'') IN $forceful THEN e.node_state ELSE {ns} END, "
    "e.metric_name = CASE WHEN coalesce(e.verdict_source,'') IN $forceful THEN e.metric_name ELSE {mn} END, "
    "e.metric_value = CASE WHEN coalesce(e.verdict_source,'') IN $forceful THEN e.metric_value ELSE {mv} END, "
    "e.metric_scope = CASE WHEN coalesce(e.verdict_source,'') IN $forceful THEN e.metric_scope ELSE {ms} END"
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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


class TierDowngrade(Exception):
    """G6: assurance_tier 다운그레이드 선언이 단조 ratchet CAS 에 거부됨 — mutations 가 409 로 번역.
    DB-side CASE(assurance.cypher_tier_rank_case 생성물)가 원자 판정하고, writer 는 RETURN 된 결과가
    선언과 다르면(=하향이라 관철 안 됨) raise 한다(읽고-쓰기 race 없음)."""


# G6 단조 ratchet 의 DB-side 랭크 CASE — 서열 정본(assurance.TIER_RANK)에서 생성(표류 불가).
_TIER_RANK_CASE = assurance.cypher_tier_rank_case("t.assurance_tier")


class TreeKgWriter:
    """Owns Cypher write shape for the tree context."""

    # KG: seed-lkt-engine-mutation-writer-20260616

    def __init__(self, kg_tx: KgTx, *, chunk_size: int = 100):
        self.kg_tx = kg_tx
        self.chunk_size = max(1, chunk_size)

    def add_node(self, tree: str, node: NodeIn, parent_edges: Sequence[ParentEdgeIn]) -> WriteSummary:
        """Single-node compatibility path: node and branch edges share one tx."""
        _reject_scored([node])   # prom-honesty/1: 스크립트 판결 self-report 차단(by-construction)
        ops: list[tuple[str, dict]] = [
            (
                """MATCH (t:LakatosTree {name:$tree})
               MERGE (e:LakatosNode:PrismExperiment {name:$tree+'/'+$tag})
               SET e.tag=$tag, e.script=$script, e.result_path=$result_path,
                   e.algorithm=$algorithm, e.comment=$comment, e.limitation=$limitation,
                   e.open_question=$open_question, e.recorded_at=$ts, e.author=$author,
                   """ + _PRESERVE_IF_SCORED.format(
                       v="$verdict", ns="$node_state",
                       mn="$metric_name", mv="$metric_value", ms="$metric_scope") + """
               MERGE (t)-[:HAS_NODE]->(e)
               RETURN t AS t""",
                dict(tree=tree, ts=_utc_now(), node_state=NodeState.DRAFT.value,
                     forceful=_FORCEFUL, **node.model_dump()),
            )
        ]
        for edge in parent_edges:
            ops.append(
                (
                    """MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:$tag})
                       MATCH (t)-[:HAS_NODE]->(p {tag:$parent})
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
                       MERGE (q:OpenQuestion {name:$qname})
                         ON CREATE SET q.status='OPEN', q.created_at=$ts
                       MERGE (e)-[:RAISES_QUESTION]->(q)
                       MERGE (t)-[:HAS_FRONTIER]->(q)""",
                    dict(tree=tree, tag=node.tag, qname=node.open_question.strip(), ts=_utc_now()),
                )
            )
        results = self.kg_tx(ops)
        if not results or not results[0]:   # MATCH 0행 = 나무 미존재 → 침묵 no-op 금지(fail-loud)
            raise TreeNotFound(tree)
        return WriteSummary(tx_count=1, op_count=len(ops), rows=1)

    def delete_tree(self, tree: str) -> WriteSummary:
        """나무 + 노드 + frontier 를 cascade DETACH DELETE(파괴적·복구불가). 미존재면 TreeNotFound(0행).

        op1(RETURN t)로 존재 확인 → op2 가 같은 tx 에서 삭제. 미존재 시 op2 는 no-op(삭제 0)이고 raise."""
        results = self.kg_tx([
            ("MATCH (t:LakatosTree {name:$tree}) RETURN t AS t", dict(tree=tree)),
            (
                """MATCH (t:LakatosTree {name:$tree})
                   OPTIONAL MATCH (t)-[:HAS_NODE]->(e)
                   OPTIONAL MATCH (t)-[:HAS_FRONTIER]->(q)
                   DETACH DELETE e, q, t""",
                dict(tree=tree),
            ),
        ])
        if not results or not results[0]:   # op1 0행 = 나무 미존재 (op2 삭제는 no-op)
            raise TreeNotFound(tree)
        return WriteSummary(tx_count=1, op_count=2, rows=1)

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
        ontology: str = "",
        require_novel_anchor: bool = False,
        assurance_tier: str | None = None,
        attestor_dids: Sequence[str] | None = None,
    ) -> WriteSummary:
        # G6: 신규 트리는 ON CREATE 로만 tier 스탬프(기본 anchored — git default-OFF 반전). 기존 트리는
        #   tier 미선언 upsert 에 절대 안 덮인다(T2 write-clobber 교정: TreeSpec 기본값 flip 이 아니라
        #   ON CREATE SET). 선언 시엔 DB-side 단조 ratchet CASE(랭크 정본=assurance.TIER_RANK 생성물)가
        #   원자 판정 — 상향만 관철, 하향은 기존값 유지 → RETURN 불일치로 TierDowngrade(→409).
        # G10: attestor_dids(서명자 allow-list=키 실물)도 tier 와 같은 非클로버 규율 — None(미선언)은
        #   기존값 불변, 선언 시에만 교체(revocation 은 정당한 운영이라 ratchet 아님·명시 교체).
        results = self.kg_tx([
            (
                """MERGE (t:LakatosTree {name:$tree})
                     ON CREATE SET t.assurance_tier = coalesce($declared_tier, $default_tier)
                   SET t.title=$title, t.hard_core=$hard_core, t.frontier_rule=$frontier_rule,
                       t.doc=$doc, t.coverage_backlog=$coverage_backlog,
                       t.coverage_statement=$coverage_statement, t.ontology=$ontology,
                       t.require_novel_anchor=$require_novel_anchor, t.updated_at=$ts
                   SET t.assurance_tier = CASE
                         WHEN $declared_tier IS NULL THEN t.assurance_tier
                         WHEN $declared_rank >= """ + _TIER_RANK_CASE + """ THEN $declared_tier
                         ELSE t.assurance_tier END
                   SET t.attestor_dids = CASE
                         WHEN $attestor_dids IS NULL THEN t.attestor_dids
                         ELSE $attestor_dids END
                   RETURN t.assurance_tier AS assurance_tier""",
                dict(
                    tree=name,
                    title=title,
                    hard_core=hard_core,
                    frontier_rule=frontier_rule,
                    doc=doc,
                    coverage_backlog=list(coverage_backlog),
                    coverage_statement=coverage_statement,
                    ontology=ontology,
                    require_novel_anchor=require_novel_anchor,
                    declared_tier=assurance_tier,
                    declared_rank=assurance.tier_rank(assurance_tier),
                    default_tier=assurance.DEFAULT_NEW_TREE_TIER,
                    attestor_dids=(None if attestor_dids is None else list(attestor_dids)),
                    ts=_utc_now(),
                ),
            )
        ])
        if assurance_tier is not None:
            got = (results[0][0] or {}).get("assurance_tier") if results and results[0] else None
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
                       UNWIND $rows AS row
                       MERGE (e:LakatosNode:PrismExperiment {name:$tree+'/'+row.tag})
                       SET e.tag=row.tag, e.script=row.script,
                           e.result_path=row.result_path, e.algorithm=row.algorithm,
                           e.comment=row.comment, e.limitation=row.limitation,
                           e.open_question=row.open_question, e.recorded_at=row.ts,
                           """ + _PRESERVE_IF_SCORED.format(
                               v="row.verdict", ns="$node_state",
                               mn="row.metric_name", mv="row.metric_value", ms="row.metric_scope") + """
                       MERGE (t)-[:HAS_NODE]->(e)""",
                    dict(tree=tree, rows=rows, node_state=NodeState.DRAFT.value, forceful=_FORCEFUL),
                )
            ])
            total = total.plus(WriteSummary(tx_count=1, op_count=1, rows=len(rows)))
        return total

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
                       UNWIND $rows AS row
                       MATCH (t)-[:HAS_NODE]->(e {tag:row.tag})
                       MATCH (t)-[:HAS_NODE]->(p {tag:row.parent})
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
                       UNWIND $rows AS row
                       MERGE (qn:OpenQuestion {name:row.qname})
                       SET qn.body=row.body, qn.status='OPEN', qn.created_at=row.ts,
                           qn.expected_gain=row.expected_gain, qn.cost=row.cost,
                           qn.n_visits=coalesce(qn.n_visits, 0)
                       MERGE (t)-[:HAS_FRONTIER]->(qn)""",
                    dict(tree=tree, rows=rows),
                )
            ])
            total = total.plus(WriteSummary(tx_count=1, op_count=1, rows=len(rows)))
        return total
