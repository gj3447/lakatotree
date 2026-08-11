"""Tree context application service.

# KG: span_lakatotree_server_tree_context
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json

from fastapi import HTTPException

from lakatos.programme.consilience import (
    ConsilienceTargetMissing,
    branch_verdict_sequences,
    consilience_report,
    project_tree_rows,
    report_bytes,
)

from lakatos.verdicts import FORCEFUL_SOURCES as _FORCEFUL_SOURCES
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

    def consilience(self, name: str, leaf1: str, leaf2: str, credence: bool = False) -> dict:
        """G7 재합류 연산자 표면(R9-CONSIL) — 두 leaf 의 incore 3-way 병합 리포트. 무변이(GET 계약):
        tree_data 소비만, 그래프 쓰기 0, verdict_mutation=False(canonical 화는 기존 게이트로).

        credence=False 기본 — 레거시 트리는 pred_closes 가 대부분 빈값이라 true 기본은 전면 422 오폭.
        credence=True 면 두 leaf 의 루트경로(조상 전체) verdict 시퀀스로 union_credence 동봉 —
        BF>1 무타깃 확증은 ConsilienceTargetMissing → 422 번역(무음 병합 금지, fail-closed).
        report_sha = report_bytes(canonical JSON) 의 sha256 16자 — 수송 가능한 증거 지문."""
        td = self.tree_data(name)   # 미존재 트리 = 404 (repo 계약)
        parents, stances, verdicts = project_tree_rows(td.get("nodes") or [])
        missing = [leaf for leaf in (leaf1, leaf2) if leaf not in parents]
        if missing:
            raise HTTPException(404, f"노드 없음: {missing} — 빈 조상 무음 병합 금지")
        bv = branch_verdict_sequences(parents, verdicts, leaf1, leaf2) if credence else None
        try:
            report = consilience_report(parents=parents, stances=stances,
                                        leaf1=leaf1, leaf2=leaf2, branch_verdicts=bv)
        except ConsilienceTargetMissing as exc:
            raise HTTPException(422, f"consilience credence fail-closed: {exc}") from exc
        rb = report_bytes(report)
        return {"tree": name, "leaf1": leaf1, "leaf2": leaf2, "report": report,
                "report_sha": hashlib.sha256(rb.encode("utf-8")).hexdigest()[:16]}

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
            coverage_status=spec.coverage_status,
            coverage_statement=spec.coverage_statement,
            coverage_backlog=tuple(spec.coverage_backlog),
            ontology=spec.ontology,
            require_novel_anchor=spec.require_novel_anchor,
            require_certified_evidence=spec.require_certified_evidence,
            assurance_tier=spec.assurance_tier,
            attestor_dids=(None if spec.attestor_dids is None else tuple(spec.attestor_dids)),
            research_layout=spec.research_layout,
            layout_owner_did=spec.layout_owner_did,
            layout_sig=spec.layout_sig,
            witness_dids=(None if spec.witness_dids is None else tuple(spec.witness_dids)),
            witness_threshold=spec.witness_threshold,
            cycle_budget=spec.cycle_budget,
        ))

    def delete_tree(self, name: str, cascade: bool = False) -> dict:
        """나무 삭제(파괴적·복구불가) — create_tree 의 짝. 미존재=404. empty-guard: 노드가 있으면
        cascade=True 일 때만 전체삭제(아니면 409) — typo 로 진짜 연구트리 날리기 방지.

        R10-s4(후속 PROM): engine verdict/:VerdictReceipt 보유 트리는 cascade 여도 409 하드가드 —
        cascade 한 방이 증거불멸(G1/G9)을 물리 파기하는 열린 창을 봉합. 조회 실패=409 fail-safe
        (불확실하면 안 지움 — CLAUDE.md §4 파괴적 결정 규율). full tombstone(포인터죽음화)은 DEFER."""
        n = len(self.tree_data(name).get("nodes", []))   # 404 if missing
        if n and not cascade:
            raise HTTPException(409, f"나무에 노드 {n}개 — cascade=true 로만 전체 삭제(파괴적·복구불가)")
        if n:   # cascade=True 여도 원장 보유면 하드가드(영수증 물리파괴 방지)
            try:
                probe = self.kg("MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e) "
                                "WHERE e.verdict_source IN $forceful OR e.current_receipt_sha IS NOT NULL "
                                "RETURN count(e) AS n",
                                tree=name, forceful=sorted(_FORCEFUL_SOURCES))
                receipted = int((probe[0].get("n") if probe else 0) or 0)
            except Exception:
                raise HTTPException(409, "삭제 전 원장 확인 실패 — fail-safe 차단(불확실하면 안 지움). "
                                         "KG 연결 확인 후 재시도.")
            if receipted:
                raise HTTPException(409, f"engine 판결/영수증 보유 노드 {receipted}개 — cascade 삭제 차단"
                                         f"(증거불멸 G1/G9: 영수증 물리파괴 금지). demote/포인터죽음은 별도 경로.")
        self._mutations().delete_tree(name)
        return {"ok": True, "tree": name, "deleted_nodes": n, "cascade": cascade}

    def open_question(self, name: str, question: QuestionIn) -> dict:
        # 2026-07-23 트리-스코프 수리: MERGE 키를 (tree, name) 복합으로 — 종전 {name} 전역 MERGE 는
        # 두 트리가 같은 qname 을 쓰면 *하나의* OpenQuestion 을 공유해 body last-write-wins 덮어씀·
        # close/n_visits 오염이 트리를 걸쳐 새는 결함이었다(실충돌 관측: judgment-ledger-repair-20260723).
        # V2 수리(2026-07-28 검증 감사): 재-MERGE 가 무가드 status='OPEN' + created_at=$ts 였다 —
        #   CLOSED 질문이 침묵 재개방되고(QuestionClosure 잔존과 모순) 원 등록 시각이 파괴됐다.
        #   가드를 같은 쿼리의 WHERE 로 넣어 원자적으로(읽고-쓰기 race 없음) CLOSED 를 0행 처리하고,
        #   created_at 은 coalesce 로 보존한다. 0행의 사유(트리/질문 부재 vs CLOSED)는 아래서 구분.
        rows = self.kg(
            """MATCH (t:LakatosTree {name:$tree})
          OPTIONAL MATCH (t)-[:HAS_FRONTIER]->(prior {name:$qn})
          WITH t, prior WHERE prior IS NULL OR coalesce(prior.status, 'OPEN') <> 'CLOSED'
          MERGE (qn:OpenQuestion {name:$qn, tree:$tree})
          SET qn.body=$body, qn.status='OPEN', qn.created_at=coalesce(qn.created_at, $ts),
              qn.expected_gain=$expected_gain, qn.cost=$cost,
              qn.n_visits=coalesce(qn.n_visits, 0)
          MERGE (t)-[:HAS_FRONTIER]->(qn)
          RETURN qn.name AS name""",
            tree=name,
            qn=question.qname,
            body=question.body,
            expected_gain=question.expected_gain,
            cost=question.cost,
            ts=datetime.now(timezone.utc).isoformat(),
        )
        if not rows:   # 0행 = 나무 미존재 *또는* CLOSED 가드 미통과(V2) — 사유를 구분해 보고한다.
            closed = self.kg(
                "MATCH (t:LakatosTree {name:$tree})-[:HAS_FRONTIER]->(q {name:$qn}) "
                "WHERE coalesce(q.status,'OPEN')='CLOSED' RETURN q.name AS name",
                tree=name, qn=question.qname)
            if closed:
                raise HTTPException(409, f"이미 CLOSED 인 질문({question.qname}) — 침묵 재개방 금지. "
                                         f"재탐색은 새 질문으로 분기하라(폐쇄 이력·등록시각 보존).")
            raise HTTPException(404, f"나무 없음: {name} (질문 열기 실패 — 침묵 no-op 금지)")
        self.hist(name, "question_open", None, question.model_dump())
        return {"ok": True}

    def close_question(self, name: str, qname: str, closed_by: str = "") -> dict:
        ts = datetime.now(timezone.utc).isoformat()
        closure_id = f'{name}/{qname}/closure/{closed_by or "unknown"}@{ts}'
        # V2 수리(2026-07-28): OPEN 가드 — 종전엔 이미 CLOSED 인 질문의 재폐쇄가 매 호출
        #   n_visits 증가 + closed_events append + QuestionClosure 생성을 했다(멱등도 거부도 아님).
        #   이제 CLOSED 는 already_closed 로 멱등 반환(침묵 성공 금지 — 응답에 표기).
        rows = self.kg(
            """MATCH (t:LakatosTree {name:$tree})-[:HAS_FRONTIER]->(q {name:$qn})
              WHERE coalesce(q.status,'OPEN')='OPEN'
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
            # 0행 = 질문 부재 *또는* 이미 CLOSED(OPEN 가드 미통과) — 둘을 구분해 보고한다.
            existing = self.kg(
                "MATCH (t:LakatosTree {name:$tree})-[:HAS_FRONTIER]->(q {name:$qn}) "
                "RETURN q.status AS status", tree=name, qn=qname)
            if existing:
                return {"ok": True, "already_closed": True,
                        "note": "이미 닫힌 질문 — 멱등 no-op(방문수·폐쇄이력 미증가)"}
            raise HTTPException(404, f"질문 없음: {qname}")
        self.hist(name, "question_close", closed_by, {"question": qname})
        return {"ok": True, "already_closed": False}
