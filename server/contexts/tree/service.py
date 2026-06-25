"""Tree context application service.

# KG: span_lakatotree_server_tree_context
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json

from fastapi import HTTPException

from server.contexts.tree.schemas import CreateTreeIn, NodeIn, ParentEdgeIn, QuestionIn
from server.contexts.tree.mutations import TreeMutationService, TreeSpec
from server.contexts.tree.repository import TreeKgRepository
from server.contexts.tree.validation import LakatosSemanticValidator
from server.contexts.tree.writer import TreeKgWriter
from server.read_models import compute_tree_metrics
from server.ports import HistoryAppend, KgQuery, KgTx, PgFactory


@dataclass(frozen=True)
class TreeService:
    kg: KgQuery
    kg_tx: KgTx
    hist: HistoryAppend
    pg: PgFactory
    repo: TreeKgRepository | None = None
    validator: LakatosSemanticValidator | None = None
    mutations: TreeMutationService | None = None

    def _repo(self) -> TreeKgRepository:
        return self.repo or TreeKgRepository(self.kg)

    def _validator(self) -> LakatosSemanticValidator:
        return self.validator or LakatosSemanticValidator()

    def _mutations(self) -> TreeMutationService:
        return self.mutations or TreeMutationService(
            writer=TreeKgWriter(self.kg_tx),
            validator=self._validator(),
            hist=self.hist,
        )

    def list_trees(self) -> list[dict]:
        return self._repo().list_trees()

    def tree_data(self, name: str) -> dict:
        return self._repo().load_tree_data(name)

    def compute_metrics(self, td: dict) -> dict:
        return compute_tree_metrics(td)

    def metrics(self, name: str, snapshot: bool = False) -> dict:
        m = self.compute_metrics(self.tree_data(name))
        if snapshot:
            with self.pg() as c, c.cursor() as cur:
                cur.execute(
                    "INSERT INTO metric_snapshots(tree, metrics) VALUES (%s,%s)",
                    (name, json.dumps(m, ensure_ascii=False)),
                )
        return m

    def normalized_parent_edges(self, node: NodeIn) -> list[ParentEdgeIn]:
        return self._validator().normalized_parent_edges(node)

    def add_node(self, name: str, node: NodeIn, tree_data: dict | None = None) -> dict:
        td = tree_data if tree_data is not None else self.tree_data(name)
        return self._mutations().add_node(name, node, td)

    def create_tree(self, name: str, spec: CreateTreeIn) -> dict:
        """나무 생성/메타 upsert(MERGE LakatosTree). 멱등·last-write-wins. hard_core/frontier_rule
        비우면 policy_warnings 경고만(차단 아님). 노드/질문은 별도 라우트."""
        return self._mutations().upsert_tree(TreeSpec(
            name=name,
            title=spec.title,
            hard_core=spec.hard_core,
            frontier_rule=spec.frontier_rule,
            doc=spec.doc,
            coverage_statement=spec.coverage_statement,
            coverage_backlog=tuple(spec.coverage_backlog),
        ))

    def open_question(self, name: str, question: QuestionIn) -> dict:
        self.kg(
            """MATCH (t:LakatosTree {name:$tree})
          MERGE (qn:OpenQuestion {name:$qn})
          SET qn.body=$body, qn.status='OPEN', qn.created_at=$ts,
              qn.expected_gain=$expected_gain, qn.cost=$cost,
              qn.n_visits=coalesce(qn.n_visits, 0)
          MERGE (t)-[:HAS_FRONTIER]->(qn)""",
            tree=name,
            qn=question.qname,
            body=question.body,
            expected_gain=question.expected_gain,
            cost=question.cost,
            ts=datetime.now(timezone.utc).isoformat(),
        )
        self.hist(name, "question_open", None, question.model_dump())
        return {"ok": True}

    def close_question(self, name: str, qname: str, closed_by: str = "") -> dict:
        ts = datetime.now(timezone.utc).isoformat()
        closure_id = f'{name}/{qname}/closure/{closed_by or "unknown"}@{ts}'
        rows = self.kg(
            """MATCH (t:LakatosTree {name:$tree})-[:HAS_FRONTIER]->(q {name:$qn})
              SET q.status='CLOSED',
                  q.n_visits=coalesce(q.n_visits, 0) + 1,
                  q.closed_by=CASE
                    WHEN q.closed_by IS NULL THEN [$by]
                    WHEN $by IN q.closed_by THEN q.closed_by
                    ELSE q.closed_by + $by
                  END,
                  q.closed_events=CASE
                    WHEN q.closed_events IS NULL THEN [$closure_id]
                    ELSE q.closed_events + $closure_id
                  END
              MERGE (c:QuestionClosure {id:$closure_id})
              SET c.closed_by=$by, c.at=$ts, c.tree=$tree, c.question=$qn
              MERGE (q)-[:HAS_CLOSURE]->(c)
              RETURN q.name AS name""",
            tree=name,
            qn=qname,
            by=closed_by,
            closure_id=closure_id,
            ts=ts,
        )
        if not rows:
            raise HTTPException(404, f"질문 없음: {qname}")
        self.hist(name, "question_close", closed_by, {"question": qname})
        return {"ok": True}
