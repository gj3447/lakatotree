"""Chunked KG writer for Lakatos tree mutations.

# KG: seed-lkt-engine-mutation-writer-20260616
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from lakatos.node_state import NodeState
from lakatos.verdicts import is_self_report_blocked_verdict
from server.contexts.tree.schemas import NodeIn, ParentEdgeIn, QuestionIn
from server.ports import KgTx


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


class TreeKgWriter:
    """Owns Cypher write shape for the tree context."""

    # KG: seed-lkt-engine-mutation-writer-20260616

    def __init__(self, kg_tx: KgTx, *, chunk_size: int = 100):
        self.kg_tx = kg_tx
        self.chunk_size = max(1, chunk_size)

    def add_node(self, tree: str, node: NodeIn, parent_edges: Sequence[ParentEdgeIn]) -> WriteSummary:
        """Single-node compatibility path: node and branch edges share one tx."""
        _reject_scored([node])   # prom-honesty/1: 스크립트 판결 self-report 차단(by-construction)
        ops = [
            (
                """MATCH (t:LakatosTree {name:$tree})
               MERGE (e:LakatosNode:PrismExperiment {name:$tree+'/'+$tag})
               SET e.tag=$tag, e.verdict=$verdict, e.script=$script, e.result_path=$result_path,
                   e.algorithm=$algorithm, e.comment=$comment, e.limitation=$limitation,
                   e.open_question=$open_question, e.metric_name=$metric_name,
                   e.metric_value=$metric_value, e.metric_scope=$metric_scope,
                   e.recorded_at=$ts, e.node_state=$node_state
               MERGE (t)-[:HAS_NODE]->(e)
               RETURN t AS t""",
                dict(tree=tree, ts=_utc_now(), node_state=NodeState.DRAFT.value, **node.model_dump()),
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
    ) -> WriteSummary:
        self.kg_tx([
            (
                """MERGE (t:LakatosTree {name:$tree})
                   SET t.title=$title, t.hard_core=$hard_core, t.frontier_rule=$frontier_rule,
                       t.doc=$doc, t.coverage_backlog=$coverage_backlog,
                       t.coverage_statement=$coverage_statement, t.ontology=$ontology,
                       t.require_novel_anchor=$require_novel_anchor, t.updated_at=$ts""",
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
                    ts=_utc_now(),
                ),
            )
        ])
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
                       SET e.tag=row.tag, e.verdict=row.verdict, e.script=row.script,
                           e.result_path=row.result_path, e.algorithm=row.algorithm,
                           e.comment=row.comment, e.limitation=row.limitation,
                           e.open_question=row.open_question, e.metric_name=row.metric_name,
                           e.metric_value=row.metric_value, e.metric_scope=row.metric_scope,
                           e.recorded_at=row.ts, e.node_state=$node_state
                       MERGE (t)-[:HAS_NODE]->(e)""",
                    dict(tree=tree, rows=rows, node_state=NodeState.DRAFT.value),
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
