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
from lakatos.frontier_state import (
    InvalidQuestionTransition,
    QuestionEffect,
    QuestionEvent,
    QuestionState,
    step as step_question,
)

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

    def add_node(
        self,
        name: str,
        node: NodeIn,
        tree_data: dict | None = None,
        *,
        cycle_claim: str | None = None,
    ) -> dict:
        td = tree_data if tree_data is not None else self.tree_data(name)
        return self._mutations().add_node(
            name, node, td, cycle_claim=cycle_claim
        )

    def create_tree(
        self,
        name: str,
        spec: CreateTreeIn,
        create_only: bool = False,
        *,
        idempotency_key: str | None = None,
    ) -> dict:
        """나무 생성/메타 upsert(MERGE LakatosTree). 멱등·last-write-wins. hard_core/frontier_rule
        비우면 policy_warnings 경고만(차단 아님). create_only 는 동명 나무를 409 로 거부한다."""
        if not name or '/' in name:
            raise HTTPException(422, "tree name must be one non-empty path segment")
        if idempotency_key is not None and not (
            1 <= len(idempotency_key) <= 256
            and idempotency_key.isascii()
            and idempotency_key.isprintable()
        ):
            raise HTTPException(
                422,
                "Idempotency-Key must be 1..256 printable ASCII characters",
            )
        budget_auth = self._budget_raise_authorization(name, spec)
        tree_spec = TreeSpec(
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
        )
        return self._mutations().upsert_tree(
            tree_spec,
            create_only=create_only,
            idempotency_key=idempotency_key,
            budget_raise_confirmed=budget_auth[0],
            budget_write_cert_verified=budget_auth[1],
            budget_attestors_snapshot=budget_auth[2],
        )

    def _budget_raise_authorization(
        self,
        name: str,
        spec: CreateTreeIn,
    ) -> tuple[bool, bool, tuple[str, ...] | None]:
        """Prepare evidence; the writer decides whether it is needed under lock.

        Exact durable replays must win before mutable budget/attestor policy is
        consulted.  Consequently this pre-read never rejects: it only verifies
        a supplied certificate against the observed attestor snapshot.  The
        writer compares that snapshot and the budget again while holding the
        tree lock, closing both stale-read raises and A-B-A retry failures.
        """
        confirmed = bool(spec.confirm_budget_raise)
        if spec.cycle_budget is None:
            return confirmed, False, None
        try:
            td = self.tree_data(name)
        except Exception:  # noqa: BLE001 - evidence read must not preempt durable replay
            # A failed or malformed advisory read supplies no authorization
            # evidence.  The lock-held writer still decides safely: exact
            # durable replay succeeds; a real attested raise fails closed.
            return confirmed, False, None
        attestors = tuple(str(value) for value in (td.get("attestor_dids") or []))
        current = td.get("cycle_budget")
        should_verify = (
            type(current) is int
            and int(spec.cycle_budget) > current
            and confirmed
            and bool(attestors)
            and spec.write_cert is not None
        )
        if not should_verify:
            return confirmed, False, attestors

        from lakatos.write_cert import CertError, operation_payload_sha256, verify_write_cert

        verb = "create_tree.cycle_budget_raise"
        payload = spec.model_dump(exclude={"write_cert"})
        expected_command = {
            "tree": name,
            "tag": "__tree__",
            "prev_receipt_sha": None,
            "metric_value": None,
            "script_sha": None,
            "verb": verb,
            "command_version": "v4",
            "result_sha256": None,
            "operation_payload_sha256": operation_payload_sha256(verb, payload),
        }
        try:
            verify_write_cert(
                spec.write_cert.model_dump(),
                expected_command=expected_command,
                allowlist=list(attestors),
            )
        except CertError:
            return confirmed, False, attestors
        return confirmed, True, attestors

    def _assert_budget_raise_gate(self, name: str, spec: CreateTreeIn) -> None:
        """q-selfdev-budget-ratchet: cycle_budget 상향 self-raise 마찰.

        - 신규 트리 / 첫 선언(기존 None→N): 통과
        - 기존 N→M (M>N): confirm_budget_raise=true 필수
        - attestor_dids 비어있지 않으면 write_cert 도 필수(assurance 쓰기 대칭)
        조회 실패(나무 없음)=신규 경로로 통과. 하향(M<N)은 writer LWW 그대로(운영 축소 허용).
        """
        if spec.cycle_budget is None:
            return
        try:
            td = self.tree_data(name)
        except HTTPException as exc:
            if exc.status_code == 404:
                return
            raise
        cur = td.get("cycle_budget")
        if cur is None:
            return  # first declaration
        try:
            cur_i = int(cur)
        except (TypeError, ValueError):
            return
        if int(spec.cycle_budget) <= cur_i:
            return  # same or lower — not a raise
        if not spec.confirm_budget_raise:
            raise HTTPException(
                409,
                f"cycle_budget 상향 거부: 현재 {cur_i} → 선언 {spec.cycle_budget}. "
                f"confirm_budget_raise=true 필요(self-raise 마찰 게이트, q-selfdev-budget-ratchet).",
            )
        attestors = list(td.get("attestor_dids") or [])
        if attestors:
            if spec.write_cert is None:
                raise HTTPException(
                    403,
                    "cycle_budget 상향은 attestor write-cert 필수 "
                    "(assurance_tier 쓰기와 대칭, q-selfdev-budget-ratchet).",
                )
            _confirmed, verified, _snapshot = self._budget_raise_authorization(
                name, spec
            )
            if not verified:
                raise HTTPException(
                    403,
                    "cycle_budget 상향 write-cert 검증 실패 "
                    "(sign-X-execute-Y 또는 attestor allow-list 불일치).",
                )

    def list_index_janitor(self, *, delete_empty_probes: bool = False) -> dict:
        """q-selfdev-list-index-janitor: 목록에 뜨지만 실체 비정상이거나 빈 Probe 잔해 정리.

        dangling = (a) list 에는 있으나 load 가 404 (이론상 드묾) (b) 이름에 Probe 포함 + 노드 0.
        delete_empty_probes=True 이면 빈 Probe 트리를 cascade 삭제(파괴적 — 호출자 책임).
        """
        listed = self.list_trees()
        dangling: list[dict] = []
        empty_probes: list[str] = []
        for row in listed:
            n = row.get("name") or ""
            try:
                td = self.tree_data(n)
            except HTTPException as exc:
                if exc.status_code == 404:
                    dangling.append({"name": n, "reason": "list_present_load_404"})
                continue
            nodes = td.get("nodes") or []
            if not nodes and ("Probe" in n or "probe" in n or "RoleLayout" in n):
                empty_probes.append(n)
                dangling.append({"name": n, "reason": "empty_probe", "nodes": 0})
        deleted: list[str] = []
        if delete_empty_probes:
            for n in empty_probes:
                try:
                    td = self.tree_data(n)
                    incarnation = str(
                        td.get("tree_incarnation_id") or "legacy-unassigned"
                    )
                    key_material = json.dumps(
                        {"tree": n, "incarnation": incarnation},
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    janitor_key = "janitor-empty-probe-" + hashlib.sha256(
                        key_material.encode("utf-8")
                    ).hexdigest()
                    self.delete_tree(
                        n,
                        cascade=True,
                        idempotency_key=janitor_key,
                        require_empty=True,
                        require_incarnation_match=True,
                        expected_incarnation_id=td.get("tree_incarnation_id"),
                    )
                    deleted.append(n)
                except HTTPException:
                    pass
        return {
            "listed": len(listed),
            "dangling": dangling,
            "dangling_count": len(dangling),
            "empty_probes": empty_probes,
            "deleted": deleted,
        }

    def delete_tree(
        self,
        name: str,
        cascade: bool = False,
        *,
        idempotency_key: str | None = None,
        require_empty: bool = False,
        require_incarnation_match: bool = False,
        expected_incarnation_id: str | None = None,
    ) -> dict:
        """Delete only from the writer's lock-held authoritative decision."""
        if idempotency_key is None or not (
            1 <= len(idempotency_key) <= 256
            and idempotency_key.isascii()
            and idempotency_key.isprintable()
        ):
            raise HTTPException(
                422,
                "DELETE requires Idempotency-Key with 1..256 printable ASCII characters",
            )
        result = self._mutations().delete_tree(
            name,
            cascade=cascade,
            idempotency_key=idempotency_key,
            require_empty=require_empty,
            require_incarnation_match=require_incarnation_match,
            expected_incarnation_id=expected_incarnation_id,
        )
        response = {
            "ok": True,
            "tree": name,
            "deleted_nodes": result["deleted_nodes"],
            "cascade": cascade,
            "idempotent": result.get("idempotent") is True,
        }
        if result.get("superseded") is True:
            response["superseded"] = True
        return response

    def open_question(self, name: str, question: QuestionIn) -> dict:
        # 2026-07-23 트리-스코프 수리: MERGE 키를 (tree, name) 복합으로 — 종전 {name} 전역 MERGE 는
        # 두 트리가 같은 qname 을 쓰면 *하나의* OpenQuestion 을 공유해 body last-write-wins 덮어씀·
        # close/n_visits 오염이 트리를 걸쳐 새는 결함이었다(실충돌 관측: judgment-ledger-repair-20260723).
        rows = self.kg(
            """MATCH (t:LakatosTree {name:$tree})
          SET t._tree_write_cas=coalesce(t._tree_write_cas,0)+0
          WITH t
          MERGE (qn:OpenQuestion {name:$qn, tree:$tree})
          ON CREATE SET qn.status=$open_state, qn.created_at=$ts, qn.n_visits=0
          WITH t, qn, coalesce(qn.status, $open_state) AS before_state
          FOREACH (_ IN CASE WHEN before_state=$open_state THEN [1] ELSE [] END |
            SET qn.body=$body, qn.status=$open_state,
                qn.expected_gain=$expected_gain, qn.cost=$cost,
                qn.n_visits=coalesce(qn.n_visits, 0))
          MERGE (t)-[:HAS_FRONTIER]->(qn)
          RETURN qn.name AS name, before_state""",
            tree=name,
            qn=question.qname,
            body=question.body,
            expected_gain=question.expected_gain,
            cost=question.cost,
            ts=datetime.now(timezone.utc).isoformat(),
            open_state=QuestionState.OPEN.value,
        )
        if not rows:   # MATCH 0행 = 나무 미존재 — 종전엔 침묵 no-op ok:true (close_question 과 비대칭)
            raise HTTPException(404, f"나무 없음: {name} (질문 열기 실패 — 침묵 no-op 금지)")
        before = rows[0].get("before_state") or QuestionState.OPEN.value
        try:
            transition = step_question(QuestionState(before), QuestionEvent.OPEN)
        except (ValueError, InvalidQuestionTransition) as exc:
            raise HTTPException(409, f"질문 상태 전이 거부: {before} + OPEN") from exc
        if QuestionEffect.UPDATE_METADATA in transition.effects:
            self.hist(name, "question_open", None, question.model_dump())
        return {"ok": True, "state": transition.state.value,
                "changed": transition.changed, "transition": transition.transition_id}

    def close_question(self, name: str, qname: str, closed_by: str = "") -> dict:
        ts = datetime.now(timezone.utc).isoformat()
        closure_id = f'{name}/{qname}/closure'
        rows = self.kg(
            """MATCH (t:LakatosTree {name:$tree})
              SET t._tree_write_cas=coalesce(t._tree_write_cas,0)+0
              WITH t
              MATCH (t)-[:HAS_FRONTIER]->(q {name:$qn})
              SET q._cas=coalesce(q._cas, 0) + 0
              WITH q, coalesce(q.status, $open_state) AS before_state
              WITH q, before_state, before_state=$open_state AS transitioned
              FOREACH (_ IN CASE WHEN transitioned THEN [1] ELSE [] END |
                SET q.status=$closed_state,
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
                MERGE (q)-[:HAS_CLOSURE]->(c))
              RETURN q.name AS name, before_state,
                     CASE WHEN transitioned THEN $closed_state ELSE before_state END AS after_state,
                     transitioned""",
            tree=name,
            qn=qname,
            by=closed_by,
            closure_id=closure_id,
            ts=ts,
            open_state=QuestionState.OPEN.value,
            closed_state=QuestionState.CLOSED.value,
        )
        if not rows:
            raise HTTPException(404, f"질문 없음: {qname}")
        before = rows[0].get("before_state") or QuestionState.OPEN.value
        try:
            transition = step_question(QuestionState(before), QuestionEvent.CLOSE)
        except (ValueError, InvalidQuestionTransition) as exc:
            raise HTTPException(409, f"질문 상태 전이 거부: {before} + CLOSE") from exc
        if QuestionEffect.RECORD_CLOSURE in transition.effects:
            self.hist(name, "question_close", closed_by, {"question": qname})
        return {"ok": True, "state": transition.state.value,
                "changed": transition.changed, "transition": transition.transition_id}

    def reattribute_question(self, name: str, qname: str, closed_by: str) -> dict:
        """Append a receipt-backed closer to an already-CLOSED question (Sprint A P0-2).

        Does **not** reopen. Rejects self-report / force_of_row≠COUNTS closers.
        Pure FSM: CLOSED + REATTRIBUTE + receipt_backed_conclusive → AppendQuestionCloser.
        """
        from lakatos.frontier_state import (
            InvalidQuestionTransition,
            QuestionEffect,
            QuestionEvent,
            QuestionState,
            step as step_question,
        )
        from lakatos.verdicts import force_of_row, verdict_assurance

        if not closed_by or not str(closed_by).strip():
            raise HTTPException(422, "reattribute requires closed_by (node tag)")

        # Load closer node + question state in one read (tree scope).
        rows = self.kg(
            """MATCH (t:LakatosTree {name:$tree})
               MATCH (t)-[:HAS_FRONTIER]->(q {name:$qn})
               OPTIONAL MATCH (t)-[:HAS_NODE]->(n {tag:$by})
               RETURN coalesce(q.status, 'OPEN') AS q_status,
                      q.closed_by AS closed_by,
                      q.closed_events AS closed_events,
                      n.tag AS tag,
                      n.verdict AS verdict,
                      n.verdict_source AS verdict_source,
                      n.current_receipt_sha AS current_receipt_sha,
                      n.measurement_grade AS measurement_grade,
                      n.replay_status AS replay_status,
                      n.measurement_lock_sha AS measurement_lock_sha,
                      n.qualitative_self_report AS qualitative_self_report,
                      COUNT { MATCH (n)-[:HAS_RECEIPT]->
                        (:VerdictReceipt {receipt_sha:n.current_receipt_sha}) }
                        AS receipt_bindings,
                      COUNT { MATCH (n)-[:HAS_LOCK]->
                        (:MeasurementLock {lock_sha:n.measurement_lock_sha}) }
                        AS lock_bindings,
                      n.node_state AS node_state""",
            tree=name, qn=qname, by=closed_by,
        )
        if not rows:
            raise HTTPException(404, f"질문 없음: {qname}")
        row = rows[0]
        if not row.get("tag"):
            raise HTTPException(404, f"closer 노드 없음: {closed_by}")

        closer = {
            "tag": row["tag"],
            "verdict": row.get("verdict"),
            "verdict_source": row.get("verdict_source"),
            "current_receipt_sha": row.get("current_receipt_sha"),
            "measurement_grade": row.get("measurement_grade"),
            "replay_status": row.get("replay_status"),
            "measurement_lock_bound": row.get("lock_bindings") == 1,
            "qualitative_self_report": bool(
                row.get("qualitative_self_report")
            ),
            "node_state": row.get("node_state"),
        }
        # Always present the receipt key so force_of_row applies the ledger gate
        # (API rows always carry the key; OPTIONAL MATCH may yield None).
        if "current_receipt_sha" not in closer:
            closer["current_receipt_sha"] = None

        if force_of_row(closer) != "COUNTS" or row.get("receipt_bindings") != 1:
            raise HTTPException(
                409,
                f"reattribute 거부: closer {closed_by!r} force_of_row≠COUNTS "
                f"(vs={closer.get('verdict_source')!r}, "
                f"receipt={bool(closer.get('current_receipt_sha'))}, "
                f"mg={closer.get('measurement_grade')!r}, "
                f"replay={closer.get('replay_status')!r})",
            )

        receipt_sha = closer.get("current_receipt_sha") or ""
        verdict = closer.get("verdict") or ""
        closer_assurance = verdict_assurance(closer)
        before = row.get("q_status") or QuestionState.OPEN.value
        try:
            transition = step_question(
                QuestionState(before),
                QuestionEvent.REATTRIBUTE,
                verdict=verdict,
                receipt_sha=receipt_sha,
                assurance_level=closer_assurance["val"],
                qualitative_self_report=closer[
                    "qualitative_self_report"
                ],
            )
        except (ValueError, InvalidQuestionTransition) as exc:
            raise HTTPException(
                409, f"질문 상태 전이 거부: {before} + REATTRIBUTE ({exc})"
            ) from exc

        if QuestionEffect.APPEND_CLOSER not in transition.effects:
            return {
                "ok": True,
                "state": transition.state.value,
                "changed": False,
                "transition": transition.transition_id,
                "appended": False,
            }

        ts = datetime.now(timezone.utc).isoformat()
        # Unique closure id per closer+time so reattribute does not overwrite the
        # original close MERGE (id was previously tree/qname/closure only).
        closure_id = f"{name}/{qname}/closure/{closed_by}@{ts}"

        written = self.kg(
            """MATCH (t:LakatosTree {name:$tree})
               SET t._tree_write_cas=coalesce(t._tree_write_cas,0)+0
               WITH t
               MATCH (t)-[:HAS_FRONTIER]->(q {name:$qn})
               MATCH (t)-[:HAS_NODE]->(n {tag:$by})
               WHERE coalesce(q.status, $open_state) = $closed_state
                 AND coalesce(n.verdict,'')=coalesce($exp_verdict,'')
                 AND coalesce(n.verdict_source,'')=coalesce($exp_verdict_source,'')
                 AND coalesce(n.current_receipt_sha,'')=coalesce($exp_receipt_sha,'')
                 AND coalesce(n.measurement_grade,'')=coalesce($exp_measurement_grade,'')
                 AND coalesce(n.replay_status,'')=coalesce($exp_replay_status,'')
                 AND coalesce(n.node_state,'')=coalesce($exp_node_state,'')
               WITH q,
                 CASE
                   WHEN q.closed_by IS NULL THEN []
                   WHEN valueType(q.closed_by) STARTS WITH 'LIST' THEN q.closed_by
                   ELSE [toString(q.closed_by)]
                 END AS current_closed_by,
                 CASE
                   WHEN q.closed_events IS NULL THEN []
                   WHEN valueType(q.closed_events) STARTS WITH 'LIST' THEN q.closed_events
                   ELSE [toString(q.closed_events)]
                 END AS current_closed_events
               SET q._cas = coalesce(q._cas, 0) + 0,
                   q.closed_by = CASE WHEN $by IN current_closed_by
                                      THEN current_closed_by
                                      ELSE current_closed_by + [$by] END,
                   q.closed_events = CASE WHEN $closure_id IN current_closed_events
                                          THEN current_closed_events
                                          ELSE current_closed_events + [$closure_id] END
               MERGE (c:QuestionClosure {id:$closure_id})
               SET c.closed_by=$by, c.at=$ts, c.tree=$tree, c.question=$qn,
                   c.kind='reattribute', c.receipt_sha=$receipt_sha
               MERGE (q)-[:HAS_CLOSURE]->(c)
               RETURN q.name AS name, q.closed_by AS closed_by""",
            tree=name,
            qn=qname,
            by=closed_by,
            closure_id=closure_id,
            ts=ts,
            receipt_sha=receipt_sha,
            exp_verdict=row.get("verdict"),
            exp_verdict_source=row.get("verdict_source"),
            exp_receipt_sha=row.get("current_receipt_sha"),
            exp_measurement_grade=row.get("measurement_grade"),
            exp_replay_status=row.get("replay_status"),
            exp_node_state=row.get("node_state"),
            open_state=QuestionState.OPEN.value,
            closed_state=QuestionState.CLOSED.value,
        )
        if not written:
            raise HTTPException(
                409,
                f"reattribute write 0행 — 질문이 CLOSED가 아니거나 동시 변경: {qname}",
            )
        self.hist(
            name,
            "question_reattribute",
            closed_by,
            {"question": qname, "closure_id": closure_id, "receipt_sha": receipt_sha},
        )
        return {
            "ok": True,
            "state": transition.state.value,
            "changed": True,
            "transition": transition.transition_id,
            "appended": True,
            "closed_by": written[0].get("closed_by"),
            "closure_id": closure_id,
        }
