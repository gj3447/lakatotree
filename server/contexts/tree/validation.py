"""Executable Lakatos tree write semantics.

# KG: seed-lkt-engine-semantic-validator-20260616
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException

from lakatos.ontology import DomainOntology
from lakatos.verdicts import is_registered_verdict, is_self_report_blocked_verdict
from server.contexts.tree.schemas import NodeIn, ParentEdgeIn


def _enforce_ontology(tree_data: dict, node: NodeIn) -> None:
    """트리가 선언한 도메인 온톨로지를 노드에 강제(opt-in, fail-closed). 미선언/무효/algorithm없음 → 면제.

    entity_type = node.algorithm(노드의 방법/종류), attrs = 노드 필드. 위반 시 422 (미선언 엔티티
    drift / 필수 속성 누락 / 값 위반). '선언만 받던' domain-ontology foundation 에 teeth 를 준다."""
    onto = DomainOntology.from_json(tree_data.get("ontology"))
    if onto is None:
        return
    entity = (node.algorithm or "").strip()
    if not entity:
        if onto.require_entity:
            raise HTTPException(422, "온톨로지 strict(require_entity): 노드가 entity(algorithm) 미선언")
        return   # algorithm 없는 구조/루트 노드는 면제(require_entity 아닐 때)
    viols = onto.violations(entity, node.model_dump())
    if viols:
        raise HTTPException(422, f"온톨로지 위반(entity={entity}): {viols}")


CANONICAL_VERDICTS = frozenset({"CANONICAL", "canonical_stage"})
PROGRESS_VERDICTS = frozenset({"progressive", "progressive_conditional"})
FRONTIER_EXPLANATION_VERDICTS = frozenset({
    "partial",
    "rejected",
    "degenerating",
    "ambiguous",
    "metric_mismatch",
    "env_drift",
    "step_failed",
})


@dataclass(frozen=True)
class PolicyFinding:
    code: str
    message: str
    severity: Literal["error", "warn"] = "error"


@dataclass(frozen=True)
class PolicyDecision:
    findings: tuple[PolicyFinding, ...] = ()

    @property
    def errors(self) -> tuple[PolicyFinding, ...]:
        return tuple(finding for finding in self.findings if finding.severity == "error")

    @property
    def warnings(self) -> tuple[PolicyFinding, ...]:
        return tuple(finding for finding in self.findings if finding.severity == "warn")

    def enforce(self) -> None:
        if self.errors:
            codes = ", ".join(finding.code for finding in self.errors)
            raise HTTPException(422, f"Lakatos policy violation: {codes}")


@dataclass(frozen=True)
class NodeValidationResult:
    parent_edges: list[ParentEdgeIn]
    policy_findings: tuple[PolicyFinding, ...] = ()


@dataclass(frozen=True)
class LakatosPolicy:
    """Executable Lakatos policy for tree mutations."""

    # KG: seed-lkt-engine-policy-canonical-frontier-20260616

    mode: Literal["strict", "legacy_warn"] = "strict"

    @classmethod
    def strict(cls) -> "LakatosPolicy":
        return cls(mode="strict")

    @classmethod
    def legacy_warn(cls) -> "LakatosPolicy":
        return cls(mode="legacy_warn")

    def evaluate_tree_meta(self, *, hard_core: str, frontier_rule: str) -> PolicyDecision:
        findings: list[PolicyFinding] = []
        if not _text(hard_core):
            findings.append(self._finding("hard_core_required", "LakatosTree.hard_core is required"))
        if not _text(frontier_rule):
            findings.append(self._finding("frontier_rule_required", "LakatosTree.frontier_rule is required"))
        return PolicyDecision(tuple(findings))

    def evaluate_node(self, node: NodeIn, parent_edges: list[ParentEdgeIn]) -> PolicyDecision:
        findings: list[PolicyFinding] = []
        has_metric = _has_metric_triplet(node)
        has_provenance = _has_node_provenance(node)

        if node.verdict in CANONICAL_VERDICTS:
            if not has_metric:
                findings.append(self._finding("canonical_metric_required", "canonical nodes require metric_name/value/scope"))
            if not has_provenance:
                findings.append(self._finding("canonical_provenance_required", "canonical nodes require script or result_path"))
            if _text(node.open_question) or _text(node.limitation):
                findings.append(self._finding("canonical_frontier_open", "canonical nodes cannot carry open frontier markers"))

        if node.verdict in PROGRESS_VERDICTS:
            if not has_metric:
                findings.append(self._finding("progressive_metric_required", "progressive nodes require metric_name/value/scope"))
            if not has_provenance:
                findings.append(self._finding("progressive_provenance_required", "progressive nodes require script or result_path"))

        if node.verdict in FRONTIER_EXPLANATION_VERDICTS and not (_text(node.open_question) or _text(node.limitation)):
            findings.append(self._finding("frontier_explanation_required", "non-progressive frontier nodes require limitation or open_question"))

        for edge in parent_edges:
            if (edge.inferred or edge.relation_kind != "knowledge_inheritance") and not _text(edge.evidence_ref):
                findings.append(self._finding(
                    "parent_edge_provenance_required",
                    f"parent edge to {edge.tag} requires evidence_ref",
                ))

        return PolicyDecision(tuple(findings))

    def _finding(self, code: str, message: str) -> PolicyFinding:
        severity: Literal["error", "warn"] = "warn" if self.mode == "legacy_warn" else "error"
        return PolicyFinding(code=code, message=message, severity=severity)


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "\n".join(str(item) for item in value if str(item).strip()).strip()
    return str(value).strip()


def _has_metric_triplet(node: NodeIn) -> bool:
    return bool(_text(node.metric_name) and node.metric_value is not None and _text(node.metric_scope))


def _has_node_provenance(node: NodeIn) -> bool:
    return bool(_text(node.script) or _text(node.result_path))


class LakatosSemanticValidator:
    """Fail-closed checks before a tree mutation reaches KG."""

    # KG: rf-lkt-engine-lakatos-semantic-validator-20260616

    def __init__(self, policy: LakatosPolicy | None = None):
        self.policy = policy or LakatosPolicy.strict()

    def normalized_parent_edges(self, node: NodeIn) -> list[ParentEdgeIn]:
        edges: dict[str, ParentEdgeIn] = {}
        if node.parent:
            edges[node.parent] = ParentEdgeIn(tag=node.parent)
        for parent in node.parents:
            edges.setdefault(parent, ParentEdgeIn(tag=parent))
        for edge in node.parent_edges:
            edges[edge.tag] = edge
        if node.tag in edges:
            raise HTTPException(400, "자기 자신을 parent 로 둘 수 없음")
        return list(edges.values())

    def validate_node_create(self, tree_name: str, tree_data: dict, node: NodeIn) -> list[ParentEdgeIn]:
        return self.validate_node_create_result(tree_name, tree_data, node).parent_edges

    def validate_node_create_result(self, tree_name: str, tree_data: dict, node: NodeIn) -> NodeValidationResult:
        if not is_registered_verdict(node.verdict):
            raise HTTPException(422, f"등록되지 않은 라카토스 verdict: {node.verdict}")
        # prom-honesty/1 (적대감사 2026-06-20, 재검증 강화 2026-06-21): *스코어링·진보* 판결은 노드 수동
        #   생성/업서트로 self-report 금지. = scripted ∪ engine ∪ PROGRESS_VERDICTS(CANONICAL/former_canonical
        #   포함). scripted/engine 만 막던 1차 게이트는 CANONICAL/former_canonical 누수가 남아 metrics 진보를
        #   부풀렸다(적대 재검증 발견) → 정본급 진보어휘까지 차단. 이 어휘는 judge/engine 채점 또는 set_verdict
        #   의 promotion gate 전용. ("neither subsystem scores its own output" 의 런타임 강제.)
        #   노드엔 구조/행정 어휘(proof·canonical_stage·superseded·CANONICAL_KNOWLEDGE …)만.
        if is_self_report_blocked_verdict(node.verdict):
            raise HTTPException(422, f"스코어링/진보 판결({node.verdict})은 노드 수동 작성 금지 — 채점은 "
                                     f"judge/engine 전용, 정본승격(CANONICAL)은 set_verdict gate 전용. 구조/행정 어휘만.")
        existing = {r["tag"] for r in tree_data.get("nodes", []) if r.get("tag")}
        parent_edges = self.normalized_parent_edges(node)
        missing = [edge.tag for edge in parent_edges if edge.tag not in existing]
        if missing:
            raise HTTPException(400, f"부모 노드 없음: {missing}")
        decision = self.policy.evaluate_node(node, parent_edges)
        decision.enforce()
        _enforce_ontology(tree_data, node)   # 선언된 도메인 온톨로지 강제(opt-in, fail-closed)
        return NodeValidationResult(parent_edges=parent_edges, policy_findings=decision.findings)

    def validate_tree_meta(self, *, hard_core: str, frontier_rule: str) -> tuple[PolicyFinding, ...]:
        decision = self.policy.evaluate_tree_meta(hard_core=hard_core, frontier_rule=frontier_rule)
        decision.enforce()
        return decision.findings
