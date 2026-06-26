"""Tree context request contracts.

# KG: seed-lkt-engine-schema-context-split-20260616
"""

from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

# ★server-set-only 경계(적대 재검증 2026-06-21): verdict_source 등 server 전용 필드는 client 가 절대 못 쓴다.
#   pydantic 기본 extra='ignore' 는 client 가 보낸 verdict_source 를 *조용히 drop* 할 뿐 — 미래에 누군가
#   필드를 추가하거나 SET e += row 로 바꾸면 'no receipt=green' 이 재개방된다. extra='forbid' 로 *명시 거부*(422).
_SERVER_SET_ONLY = ConfigDict(extra="forbid")

from lakatos.engine import FoundationRequirement, KnowledgeKind, Realm, ResearchEvent


class ParentEdgeIn(BaseModel):
    tag: str
    inferred: bool = False
    relation_kind: str = "knowledge_inheritance"
    evidence_ref: str = ""


class NodeIn(BaseModel):
    model_config = _SERVER_SET_ONLY   # client 가 verdict_source 등 server 전용 필드 못 실음(422)
    tag: str = Field(min_length=1)
    parent: str | None = None
    parents: list[str] = Field(default_factory=list)
    parent_edges: list[ParentEdgeIn] = Field(default_factory=list)
    verdict: str = "proof"
    script: str = ""
    result_path: str = ""
    algorithm: str = ""
    comment: str = ""
    limitation: str = ""
    open_question: str = ""
    metric_name: str | None = None
    metric_value: float | None = None
    metric_scope: str | None = None


class VerdictIn(BaseModel):
    model_config = _SERVER_SET_ONLY   # verdict_source 는 server 가 set — client 입력이면 422
    verdict: str
    note: str = ""
    scope: str = ""
    assumptions: list[str] = Field(default_factory=list)
    evidence_window: str = ""
    valid_until_rebutted: bool = True
    human_verdict: bool = False


class QuestionIn(BaseModel):
    qname: str = Field(min_length=1)
    body: str = ""
    expected_gain: float = Field(0.1, ge=0)
    cost: float = Field(1.0, gt=0)


class CreateTreeIn(BaseModel):
    model_config = _SERVER_SET_ONLY   # client 가 server 전용 필드 못 실음(422). name 은 URL path 가 소유.
    # 메타 전용 create/upsert. 멱등이되 last-write-wins: 같은 name 재호출은 보낸 값으로 덮어씀
    # (생략 필드 = 빈값). 노드/질문은 각자 /node /question 라우트로.
    title: str = ""
    hard_core: str = ""
    frontier_rule: str = ""
    doc: str = ""
    coverage_statement: str = ""
    coverage_backlog: list[str] = Field(default_factory=list)
    # 도메인 온톨로지(JSON): {"entities":{name:{required:[...],constraints:{attr:{enum|type|min|max}}}},
    # "closed_world":bool}. 선언하면 엔진이 노드 등록 시 강제(opt-in). 빈 문자열=강제 없음.
    ontology: str = ""


class PredictionIn(BaseModel):
    """Preregistered prediction. Judgement must happen after this contract exists."""

    model_config = _SERVER_SET_ONLY
    metric_name: str
    direction: str = "lower"
    baseline_value: float
    noise_band: float = Field(0.0, ge=0)
    scale_type: str = "ratio"   # Stevens 측정척도 — judge.Prediction 가 검증(ordinal=순서만, nominal=거부)
    novel_prediction: str = ""
    novel_metric: str | None = None
    novel_direction: str | None = None
    novel_threshold: float | None = None
    judge_script_sha: str | None = None
    closes_question: str = ""
    credence: float | None = Field(None, ge=0, le=1)


class TestResultIn(BaseModel):
    """Judge-script result. The server derives the verdict from this payload."""

    model_config = _SERVER_SET_ONLY
    metric_value: float
    script: str = Field(min_length=1)
    script_sha: str | None = None
    novel_measured: float | None = None
    novel_sha: str | None = None   # prom-honesty/sha: novel 측정의 출처(예측 측정 sha 와 다르면 독립 인정)
    novel_script: str | None = None   # #H6: novel 측정의 *소스*(서버 재계산 대상). 있으면 서버가 이 본문에서
                                      #   novel sha 를 재유도해 독립성을 client 문자열(novel_sha)이 아닌 현실에 묶는다.
    source_trust: float = 1.0
    result_path: str = ""
    log: str = ""
    lakatos_anomaly: bool | None = None
    lakatos_consequence: bool | None = None
    lakatos_excess: bool | None = None
    lakatos_hardcore: bool | None = None
    implementation_complete: bool = True
    data_branch: bool = False
    data_replay_passed: bool = True
    human_verdict_required: bool = False
    counterexample_response: str | None = None
    counterexample_type: str | None = None
    ce_excess_content: bool = False
    ce_novel_corroborated: bool = False
    ce_in_heuristic_spirit: bool | None = None
    ce_proof_concept_name: str | None = None
    ce_proof_born_from: str | None = None
    ce_proof_incorporated_lemma: str | None = None


class CritiqueIn(BaseModel):
    """Human/agent doubt, comment, rebuttal, or evaluation."""

    arg_id: str
    attacks: str
    by: str = ""
    kind: str = "doubt"
    body: str = ""


class ResearchEventIn(BaseModel):
    """Append-only evidence event consumed by ClaimStanding."""

    event_id: str
    realm: str
    actor: str = ""
    action: str
    evidence_refs: list[str] = Field(default_factory=list)
    payload: dict[str, str] = Field(default_factory=dict)
    created_at: str | None = None

    def to_engine(self, target: str) -> ResearchEvent:
        try:
            realm = Realm(self.realm)
        except ValueError as exc:
            raise HTTPException(422, f"unknown research event realm: {self.realm}") from exc
        return ResearchEvent(
            name=self.event_id,
            realm=realm,
            actor=self.actor,
            action=self.action,
            target=target,
            evidence_refs=tuple(self.evidence_refs),
            payload=tuple((str(k), str(v)) for k, v in self.payload.items()),
        )


class LonginusRefIn(BaseModel):
    sourceId: str
    sourcePath: str
    layer: str = ""
    note: str = ""


class ObservationIn(BaseModel):
    """G-Web internet observation evidence."""

    event_id: str
    url: str = ""
    retrieved_at: str = ""
    content_hash: str = ""
    raw_snapshot_path: str = ""
    source_type: str = ""
    query: str = ""
    fetch_tool: str = ""
    trust: float | None = None
    link_authority: float | None = None
    source_class_weight: float | None = None
    primary_source_bonus: float | None = None
    provenance_score: float | None = None
    corroboration_score: float | None = None
    recency_score: float | None = None
    supply_chain_score: float | None = None
    lakatos_location: str = ""
    content: str = ""
    actor: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    theory_basis: str = ""
    foundation_refs: list[str] = Field(default_factory=list)
    rival_name: str = ""
    rival_relation: str = ""
    rival_node: str = ""
    comparison_axes: list[str] = Field(default_factory=list)
    longinus_refs: list[LonginusRefIn] = Field(default_factory=list)


class WorldActionIn(BaseModel):
    """G-WorldAction bash execution evidence."""

    event_id: str
    command: str = ""
    cwd: str = ""
    exit_code: int | None = None
    stdout_summary: str = ""
    stderr_summary: str = ""
    touched_files: list[str] = Field(default_factory=list)
    git_diff_hash: str = ""
    require_git_diff: bool = False
    actor: str = ""
    evidence_refs: list[str] = Field(default_factory=list)


class CycleIn(BaseModel):
    """Single-cycle orchestration input. Server does graph work, not bash execution."""

    tag: str = Field(min_length=1)
    parent: str = ""
    metric_name: str
    baseline: float
    direction: str = "lower"
    noise_band: float = Field(0.0, ge=0)
    measured: float
    script: str = "inline"
    script_sha: str | None = None
    novel_metric: str | None = None
    novel_direction: str | None = None
    novel_threshold: float | None = None
    novel_measured: float | None = None
    credence: float | None = Field(None, ge=0, le=1)
    source_trust: float = 1.0
    algorithm: str = ""
    comment: str = ""
    closes_question: str = ""
    critiques: list[CritiqueIn] = Field(default_factory=list)
    counterexample_response: str | None = None
    counterexample_type: str | None = None
    ce_excess_content: bool = False
    ce_novel_corroborated: bool = False
    ce_in_heuristic_spirit: bool | None = None
    lakatos_anomaly: bool | None = None
    lakatos_consequence: bool | None = None
    lakatos_excess: bool | None = None
    lakatos_hardcore: bool | None = None


class ArtifactIn(BaseModel):
    node_tag: str
    kind: str
    data: dict


class ElementIn(BaseModel):
    name: str
    definition: str = ""
    implication: str = ""
    lifecycle: str = ""
    scope: str = "domain-agnostic"


class ElementUseIn(BaseModel):
    note: str = ""
    evidence_ref: str = ""


class FoundationRequirementIn(BaseModel):
    name: str
    kind: str
    question: str = ""
    why_needed: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    status: str = "needed"
    optional: bool = False
    owner: str = ""
    risk_if_missing: str = ""

    def to_engine(self) -> FoundationRequirement:
        try:
            kind = KnowledgeKind(self.kind)
        except ValueError as exc:
            raise HTTPException(422, f"unknown foundation kind: {self.kind}") from exc
        return FoundationRequirement(
            name=self.name,
            kind=kind,
            question=self.question,
            why_needed=self.why_needed,
            acceptance_criteria=tuple(self.acceptance_criteria),
            evidence_refs=tuple(self.evidence_refs),
            status=self.status,
            optional=self.optional,
            owner=self.owner,
            risk_if_missing=self.risk_if_missing,
        )


# ── #① Laudan 연구전통 authoring (diagnostic-only) — programme/tradition.py 도메인 객체로 검증 ──
class TraditionCommitmentIn(BaseModel):
    model_config = _SERVER_SET_ONLY
    commitment_id: str
    kind: str                       # ontology|methodology|exemplar|problem_type|background_theory
    statement: str
    revisability: str = "routine"   # routine|costly|identity_boundary
    source_refs: list[str] = Field(default_factory=list)


class TraditionIn(BaseModel):
    model_config = _SERVER_SET_ONLY
    tradition_id: str
    name: str
    commitments: list[TraditionCommitmentIn] = Field(default_factory=list)
    ontology_commitments: list[str] = Field(default_factory=list)
    methodology_rules: list[str] = Field(default_factory=list)
    exemplars: list[str] = Field(default_factory=list)
    accepted_problem_types: list[str] = Field(default_factory=list)
    background_theories: list[str] = Field(default_factory=list)
    revision_policy: str = ""
    compatibility_notes: str = ""


class TraditionAppraiseIn(BaseModel):
    model_config = _SERVER_SET_ONLY
    commitment_id: str
    operation: str                  # add|modify|retire|reclassify
    reason: str = ""
    receipt_refs: list[str] = Field(default_factory=list)
    compatibility_claim: str = ""
