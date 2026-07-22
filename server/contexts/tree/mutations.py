"""Application-level tree mutation API.

# KG: seed-lkt-engine-mutation-service-20260616
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import HTTPException

from lakatos import assurance
from lakatos.coverage import validate_coverage_declaration
from server.contexts.tree.materialization import TreeMaterializationPlanner
from server.contexts.tree.schemas import NodeIn, ParentEdgeIn, QuestionIn
from server.contexts.tree.validation import LakatosSemanticValidator, PolicyFinding
from server.contexts.tree.writer import TierDowngrade, TreeKgWriter, TreeNotFound, WriteSummary
from server.ports import HistoryAppend


@dataclass(frozen=True)
class TreeSpec:
    name: str
    title: str = ""
    hard_core: str = ""
    frontier_rule: str = ""
    doc: str = ""
    coverage_backlog: tuple[str, ...] = ()
    coverage_statement: str = ""
    coverage_status: str = "unknown"
    ontology: str = ""   # 도메인 온톨로지 JSON(선언 시 엔진이 노드 강제)
    require_novel_anchor: bool = False   # FF1: cross-metric novel 서버앵커 강제(opt-in, 기본 off)
    require_certified_evidence: bool = False   # cert-consumer(2026-07-08): 근거 노드 인증서 강제(opt-in, 기본 off)
    # G6: 보증 tier 선언(notebook/receipted/anchored). None=미선언 — 신규 트리는 writer 의 ON CREATE 가
    #   기본 anchored 스탬프, 기존 트리는 tier 무변경(legacy 소급 스탬프 금지). 선언은 단조 ratchet(하향 409).
    assurance_tier: str | None = None
    attestor_dids: tuple[str, ...] | None = None   # G10: None=불변, 선언=교체
    cycle_budget: int | None = None   # PROM16: 루프 경계 사이클 상한. None=불변/미선언(무제한)
    nodes: tuple[NodeIn, ...] = field(default_factory=tuple)
    questions: tuple[QuestionIn, ...] = field(default_factory=tuple)


class TreeMutationService:
    """Validated tree write API above the raw KG writer."""

    # KG: seed-lkt-engine-mutation-service-20260616

    def __init__(
        self,
        *,
        writer: TreeKgWriter,
        validator: LakatosSemanticValidator,
        hist: HistoryAppend,
        planner: TreeMaterializationPlanner | None = None,
    ):
        self.writer = writer
        self.validator = validator
        self.hist = hist
        self.planner = planner or TreeMaterializationPlanner(chunk_size=writer.chunk_size)

    def add_node(self, name: str, node: NodeIn, tree_data: dict) -> dict:
        result = self.validator.validate_node_create_result(name, tree_data, node)
        # EXTAUDIT S5 (2026-07-23): Laudan 폐기신호 배선 — 부모 가지에 should_abandon 이 발화하면
        # 응답+영속 이력에 기록한다. 차단 아님(라카토스 철학상 자동 폐기는 인간 안건) — 확장은
        # 자유이되 red light 를 지나갔다는 사실이 지워지지 않는다(전엔 server/ 호출 0건의 죽은 신호).
        abandon = self._branch_abandon_signal(node, tree_data)
        try:
            self.writer.add_node(name, node, result.parent_edges)
        except TreeNotFound:
            raise HTTPException(404, f"나무 없음: {name}")
        warnings = _finding_codes(result.policy_findings)
        if abandon:
            warnings = [*warnings, "ABANDON_SIGNAL_IGNORED"]
        self.hist(name, "node_create", node.tag, {
            **node.model_dump(),
            "policy_warnings": warnings,
        })
        out = {"ok": True, "tag": node.tag}
        if abandon:
            out["abandon_signal"] = abandon
            self.hist(name, "abandon_override", node.tag, abandon)   # 영속 override 기록
        if warnings:
            out["policy_warnings"] = warnings
        return out

    @staticmethod
    def _branch_abandon_signal(node: NodeIn, tree_data: dict) -> dict | None:
        """부모 가지의 Laudan 폐기 3규칙 판정 — branch_inputs(규칙①②③ 실입력) 재사용.

        fail-open: 부모 없음/미지/계산 불가 = None (이건 차단 도구가 아니라 기록 도구다)."""
        parent = node.parent or (node.parents[0] if node.parents else None)
        if not parent:
            return None
        from lakatos.quant.laudan import should_abandon
        from lakatos.quant.metrics import branch_inputs
        try:
            bi = branch_inputs(tree_data.get("nodes") or [], tree_data.get("frontier") or [],
                               leaf=parent)
        except (KeyError, TypeError):
            return None
        fired, reason = should_abandon(bi["consecutive_nonprogressive"], bi["nodes_spent"],
                                       bi["prediction_hits"], bi["problem_balance_windowed"])
        if not fired:
            return None
        return {"fired": True, "reason": reason, "branch_leaf": parent,
                "consecutive_nonprogressive": bi["consecutive_nonprogressive"],
                "nodes_spent": bi["nodes_spent"], "prediction_hits": bi["prediction_hits"],
                "problem_balance_windowed": bi["problem_balance_windowed"]}

    def delete_tree(self, name: str) -> None:
        try:
            self.writer.delete_tree(name)
        except TreeNotFound:
            raise HTTPException(404, f"나무 없음: {name}")
        self.hist(name, "tree_delete", None, {})

    def upsert_tree(self, spec: TreeSpec) -> dict:
        # G6: 선언 tier 어휘는 닫힌 집합 — 오타(예: 'precious')를 무음 저장하면 게이트 0 인 유령 tier 가 생긴다.
        if spec.assurance_tier is not None and spec.assurance_tier not in assurance.TIERS:
            raise HTTPException(422, f"assurance_tier 미정의 어휘: '{spec.assurance_tier}' — "
                                     f"{list(assurance.TIERS)} 중 하나(생략=신규 anchored/기존 유지)")
        try:
            coverage_status = validate_coverage_declaration(
                spec.coverage_status,
                statement=spec.coverage_statement,
                backlog=spec.coverage_backlog,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        bulk = self._validate_bulk_nodes(spec)
        meta_findings = self.validator.validate_tree_meta(
            hard_core=spec.hard_core,
            frontier_rule=spec.frontier_rule,
        )
        summary = WriteSummary()
        try:
            summary = summary.plus(
                self.writer.upsert_tree_meta(
                    name=spec.name,
                    title=spec.title,
                    hard_core=spec.hard_core,
                    frontier_rule=spec.frontier_rule,
                    doc=spec.doc,
                    coverage_backlog=spec.coverage_backlog,
                    coverage_statement=spec.coverage_statement,
                    coverage_status=coverage_status,
                    ontology=spec.ontology,
                    require_novel_anchor=spec.require_novel_anchor,
                    require_certified_evidence=spec.require_certified_evidence,
                    assurance_tier=spec.assurance_tier,
                    attestor_dids=spec.attestor_dids,
                    cycle_budget=spec.cycle_budget,
                )
            )
        except TierDowngrade as e:
            raise HTTPException(409, f"G6 단조 ratchet: {e}")
        summary = summary.plus(self.writer.upsert_nodes(spec.name, spec.nodes))
        summary = summary.plus(self.writer.link_branch_edges(spec.name, bulk.parent_edges_by_tag))
        summary = summary.plus(self.writer.upsert_questions(spec.name, spec.questions))
        warnings = _finding_codes((*meta_findings, *bulk.policy_findings))
        self.hist(
            spec.name,
            "tree_upsert",
            None,
            {
                "nodes": len(spec.nodes),
                "questions": len(spec.questions),
                "tx_count": summary.tx_count,
                "policy_warnings": warnings,
            },
        )
        out = {
            "ok": True,
            "tree": spec.name,
            "nodes": len(spec.nodes),
            "questions": len(spec.questions),
            "tx_count": summary.tx_count,
            "op_count": summary.op_count,
        }
        if warnings:
            out["policy_warnings"] = warnings
        return out

    def plan_upsert_tree(self, spec: TreeSpec) -> dict:
        bulk = self._validate_bulk_nodes(spec)
        meta_findings = self.validator.validate_tree_meta(
            hard_core=spec.hard_core,
            frontier_rule=spec.frontier_rule,
        )
        plan = self.planner.plan(spec, parent_edges_by_tag=bulk.parent_edges_by_tag).to_dict()
        warnings = _finding_codes((*meta_findings, *bulk.policy_findings))
        if warnings:
            plan["policy_warnings"] = warnings
        return plan

    def _validate_bulk_nodes(self, spec: TreeSpec) -> "_BulkValidation":
        tags = [node.tag for node in spec.nodes]
        duplicates = sorted({tag for tag in tags if tags.count(tag) > 1})
        if duplicates:
            raise HTTPException(400, f"중복 노드 tag: {duplicates}")
        tree_data = {"nodes": [{"tag": tag} for tag in tags]}
        parent_edges_by_tag: dict[str, list[ParentEdgeIn]] = {}
        findings: list[PolicyFinding] = []
        for node in spec.nodes:
            result = self.validator.validate_node_create_result(spec.name, tree_data, node)
            parent_edges_by_tag[node.tag] = result.parent_edges
            findings.extend(result.policy_findings)
        return _BulkValidation(parent_edges_by_tag=parent_edges_by_tag, policy_findings=tuple(findings))


@dataclass(frozen=True)
class _BulkValidation:
    parent_edges_by_tag: dict[str, list[ParentEdgeIn]]
    policy_findings: tuple[PolicyFinding, ...] = ()


def _finding_codes(findings: tuple[PolicyFinding, ...]) -> list[str]:
    return [finding.code for finding in findings if finding.severity == "warn"]
