"""라카토트리 sparse engine.

기존 순수층은 이미 분리되어 있다:
trust.py = 인터넷 신뢰, judge.py = 판결, lineage.py = 데이터 계보,
argue.py = 인간/agent 비판, harness.py = 실제 포트 연결.

이 모듈은 특정 프로젝트의 해법이 아니라 연구 프레임워크의 얇은 뼈대다.
가능성은 단칼에 사라지지 않고, 인간/agent/인터넷/bash/DB/git
행위는 append-only event 로 남으며, 데이터 가지는 source root 에서
언제든 재현 가능한지 lineage 로 검증된다.
# KG: span_lakatotree_engine
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from typing import Iterable

from lakatos.grounding import GROUNDED   # P6-3: credibility tier 문턱 단일 정본(spine 과 공유)

from lakatos.io.lineage import (
    Derivation,
    by_output,
    rebuild_plan,
    reproducibility_gaps,
    roots,
    stale_inputs,
)
from lakatos.quant.trust import evidence_weight


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


class CredibilityTier(str, Enum):
    """KG claim 승격 등급."""

    EXTRACTED = "EXTRACTED"
    INFERRED = "INFERRED"
    AMBIGUOUS = "AMBIGUOUS"


class LakatosVerdict(str, Enum):
    """라카토트리 엔진 게이트 판결."""

    PROGRESSIVE = "progressive"
    PROGRESSIVE_CONDITIONAL = "progressive_conditional"
    DEGENERATING = "degenerating"
    DIFFERENT_PROGRAMME = "different_programme"   # AXIS-CORR: hard core 위반 = 정체성 사건(다른 프로그램)
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class GateResult:
    passed: bool
    reasons: tuple[str, ...] = ()

    @classmethod
    def pass_(cls) -> "GateResult":
        return cls(True, ())

    @classmethod
    def fail(cls, reasons: Iterable[str]) -> "GateResult":
        return cls(False, tuple(reasons))


class Realm(str, Enum):
    """연구 이벤트가 속한 세계/행위 채널."""

    INTERNET = "internet"
    HUMAN = "human"
    AGENT = "agent"
    BASH = "bash"
    DATA = "data"
    KG = "kg"
    GIT = "git"


class KnowledgeKind(str, Enum):
    """연구 시작 전에 필요한 기반지식 범주."""

    THEORY = "theory"
    DOMAIN = "domain"
    DATA = "data"
    METRIC = "metric"
    METHOD = "method"
    TOOL = "tool"
    TRUST = "trust"
    REPRODUCIBILITY = "reproducibility"
    HUMAN_PROTOCOL = "human_protocol"


@dataclass(frozen=True)
class ResearchProject:
    """LakatoTree 틀 안의 구체 프로젝트 인스턴스."""

    name: str
    goal: str
    root_artifacts: tuple[str, ...] = ()


@dataclass(frozen=True)
class FoundationRequirement:
    """연구가 시작되기 전 명시돼야 할 기반지식 requirement."""

    name: str
    kind: KnowledgeKind
    question: str
    why_needed: str
    acceptance_criteria: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    status: str = "needed"       # needed | satisfied | waived
    optional: bool = False
    owner: str = ""
    risk_if_missing: str = ""

    @property
    def satisfied(self) -> bool:
        if self.optional and self.status == "waived":
            return True
        return self.status == "satisfied" and bool(self.evidence_refs)

    def db_record(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind.value,
            "question": self.question,
            "why_needed": self.why_needed,
            "acceptance_criteria": list(self.acceptance_criteria),
            "evidence_refs": list(self.evidence_refs),
            "status": self.status,
            "optional": self.optional,
            "owner": self.owner,
            "risk_if_missing": self.risk_if_missing,
            "satisfied": self.satisfied,
        }


@dataclass
class FoundationMap:
    """프로젝트 기반지식을 sparse requirement 목록으로 관리한다."""

    _requirements: dict[str, FoundationRequirement] = field(default_factory=dict)

    def add(self, requirement: FoundationRequirement) -> FoundationRequirement:
        if requirement.name in self._requirements:
            raise ValueError(f"foundation requirement already exists: {requirement.name}")
        self._requirements[requirement.name] = requirement
        return requirement

    def requirements(self) -> tuple[FoundationRequirement, ...]:
        return tuple(self._requirements.values())

    def gaps(self) -> tuple[FoundationRequirement, ...]:
        return tuple(r for r in self._requirements.values() if not r.satisfied)

    def summary(self) -> dict:
        reqs = self.requirements()
        gaps = self.gaps()
        by_kind: dict[str, int] = {}
        for req in reqs:
            by_kind[req.kind.value] = by_kind.get(req.kind.value, 0) + 1
        return {
            "required": len(reqs),
            "satisfied": len(reqs) - len(gaps),
            "gaps": [g.name for g in gaps],
            "by_kind": by_kind,
        }

    @classmethod
    def default_for_project(cls, project: ResearchProject) -> "FoundationMap":
        fmap = cls()
        defaults = [
            FoundationRequirement(
                name="research-program-theory",
                kind=KnowledgeKind.THEORY,
                question="what counts as progressive, degenerating, or merely partial?",
                why_needed="prevents the tree from becoming an absolute narrative",
                acceptance_criteria=("verdict vocabulary", "revision rule", "non-absolute current best"),
            ),
            FoundationRequirement(
                name="domain-ontology",
                kind=KnowledgeKind.DOMAIN,
                question="what entities, observations, and interventions exist in this project?",
                why_needed="prevents project-specific facts from leaking into the framework",
                acceptance_criteria=("entity vocabulary", "scope boundary", "unknown list"),
            ),
            FoundationRequirement(
                name="root-data-contract",
                kind=KnowledgeKind.DATA,
                question="what raw/root artifacts anchor the research?",
                why_needed="makes all derived results replayable from roots",
                acceptance_criteria=("root artifact ids", "content hashes", "stale policy"),
            ),
            FoundationRequirement(
                name="metric-contract",
                kind=KnowledgeKind.METRIC,
                question="which metrics judge branches and where do metric relabels break continuity?",
                why_needed="prevents relabel events from masquerading as progress",
                acceptance_criteria=("metric_name", "direction", "noise_band", "relabel rule"),
            ),
            FoundationRequirement(
                name="trust-and-provenance-contract",
                kind=KnowledgeKind.TRUST,
                question="which sources and observations are trusted enough for each claim tier?",
                why_needed="prevents internet observations from silently becoming extracted claims",
                acceptance_criteria=("credibility tier", "source refs", "corroboration rule"),
            ),
            FoundationRequirement(
                name="reproducibility-contract",
                kind=KnowledgeKind.REPRODUCIBILITY,
                question="how can final artifacts be regenerated from root artifacts?",
                why_needed="keeps buffers temporary and final claims replayable",
                acceptance_criteria=("lineage DAG", "producer sha", "rebuild plan"),
            ),
            FoundationRequirement(
                name="human-agent-protocol",
                kind=KnowledgeKind.HUMAN_PROTOCOL,
                question="what can humans decide, what can agents build, and how are doubts recorded?",
                why_needed="keeps critique, construction, and sigma judgement separate",
                acceptance_criteria=("critique channel", "closure events", "conflict rule"),
            ),
        ]
        for req in defaults:
            fmap.add(req)
        if project.root_artifacts:
            existing = fmap._requirements["root-data-contract"]
            fmap._requirements["root-data-contract"] = replace(
                existing,
                evidence_refs=tuple(project.root_artifacts),
                status="satisfied",
            )
        return fmap


class FoundationGate:
    """기반지식 gap 이 남아 있으면 연구 판결을 보수적으로 막는다."""

    @staticmethod
    def evaluate(foundation: FoundationMap) -> GateResult:
        gaps = foundation.gaps()
        return GateResult.pass_() if not gaps else GateResult.fail(g.name for g in gaps)


@dataclass(frozen=True)
class Possibility:
    """아직 닫히지 않은 연구 가능성.

    state 는 DB/KG 에서 해석할 문자열로 둔다. 엔진은 가능성을 강제 폐기하지
    않고 이벤트와 evidence 를 축적한다.
    """

    name: str
    question: str
    parent: str | None = None
    state: str = "open"
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResearchEvent:
    """인간/agent/인터넷/bash/git/DB 행위의 최소 이력 단위."""

    name: str
    realm: Realm
    actor: str
    action: str
    target: str
    evidence_refs: tuple[str, ...] = ()
    payload: tuple[tuple[str, str], ...] = ()
    created_at: datetime | None = None

    def db_record(self) -> dict:
        return {
            "name": self.name,
            "realm": self.realm.value,
            "actor": self.actor,
            "action": self.action,
            "target": self.target,
            "evidence_refs": list(self.evidence_refs),
            "payload": dict(self.payload),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


@dataclass
class ResearchFrame:
    """프로젝트의 가능성들과 모든 행위 이력을 sparse 하게 보존한다."""

    project: ResearchProject
    _possibilities: dict[str, Possibility] = field(default_factory=dict)
    _events: list[ResearchEvent] = field(default_factory=list)

    def open_possibility(self, possibility: Possibility) -> Possibility:
        if possibility.name in self._possibilities:
            raise ValueError(f"possibility already exists: {possibility.name}")
        if possibility.parent and possibility.parent not in self._possibilities:
            raise KeyError(f"unknown parent possibility: {possibility.parent}")
        self._possibilities[possibility.name] = possibility
        return possibility

    def record_event(self, event: ResearchEvent) -> ResearchEvent:
        if event.target not in self._possibilities:
            raise KeyError(f"unknown event target: {event.target}")
        self._events.append(event)
        return event

    def possibilities(self) -> tuple[Possibility, ...]:
        return tuple(self._possibilities.values())

    def events(self) -> tuple[ResearchEvent, ...]:
        return tuple(self._events)

    def events_for(self, possibility: str) -> tuple[ResearchEvent, ...]:
        return tuple(e for e in self._events if e.target == possibility)

    def standing(self, possibility: str) -> dict:
        p = self._possibilities[possibility]
        evs = self.events_for(possibility)
        refs = sorted({ref for e in evs for ref in e.evidence_refs} | set(p.evidence_refs))
        return {
            "name": p.name,
            "state": p.state,
            "event_count": len(evs),
            "realms": sorted({e.realm.value for e in evs}),
            "evidence_refs": refs,
        }


@dataclass(frozen=True)
class SourceCredibilityScore:
    """인터넷 출처 신뢰의 설명 가능한 구성요소.

    score 자체는 opaque label 이 아니라 source class, link authority,
    provenance, corroboration, supply-chain 등을 보존한다. 최종 가중치는
    기존 trust.evidence_weight 와 연결해 베이즈층으로 흘릴 수 있다.
    """

    source_class_weight: float = 0.0
    link_authority: float = 0.0
    primary_source_bonus: float = 0.0
    provenance_score: float = 0.0
    corroboration_score: float = 0.0
    recency_score: float = 0.0
    supply_chain_score: float = 0.0
    injection_penalty: float = 0.0
    conflict_penalty: float = 0.0
    explicit_tier: CredibilityTier | None = None

    @property
    def trust(self) -> float:
        raw = (
            0.18 * self.source_class_weight
            + 0.12 * self.link_authority
            + 0.15 * self.primary_source_bonus
            + 0.15 * self.provenance_score
            + 0.15 * self.corroboration_score
            + 0.10 * self.recency_score
            + 0.10 * self.supply_chain_score
            - 0.15 * self.injection_penalty
            - 0.10 * self.conflict_penalty
        )
        return _clamp01(raw)

    @property
    def tier(self) -> CredibilityTier:
        if self.explicit_tier is not None:
            return self.explicit_tier
        if self.trust >= GROUNDED['credibility_extracted_trust']['value'] and (
            self.primary_source_bonus >= 0.80 or self.provenance_score >= 0.95
        ):
            return CredibilityTier.EXTRACTED
        if self.trust >= GROUNDED['credibility_inferred_trust']['value']:
            return CredibilityTier.INFERRED
        return CredibilityTier.AMBIGUOUS

    @property
    def evidence_weight(self) -> float:
        return evidence_weight(self.trust)

    def as_components(self) -> dict[str, float]:
        return {
            "source_class_weight": _clamp01(self.source_class_weight),
            "link_authority": _clamp01(self.link_authority),
            "primary_source_bonus": _clamp01(self.primary_source_bonus),
            "provenance_score": _clamp01(self.provenance_score),
            "corroboration_score": _clamp01(self.corroboration_score),
            "recency_score": _clamp01(self.recency_score),
            "supply_chain_score": _clamp01(self.supply_chain_score),
            "injection_penalty": _clamp01(self.injection_penalty),
            "conflict_penalty": _clamp01(self.conflict_penalty),
        }


class CredibilityPromotionGate:
    """인터넷 관측이 KG claim 으로 조용히 승격되는 것을 막는다."""

    _rank = {
        CredibilityTier.AMBIGUOUS: 0,
        CredibilityTier.INFERRED: 1,
        CredibilityTier.EXTRACTED: 2,
    }

    @classmethod
    def evaluate(
        cls,
        *,
        current: CredibilityTier,
        target: CredibilityTier,
        has_direct_source: bool,
        has_independent_corroboration: bool,
        has_human_verdict: bool,
    ) -> GateResult:
        if cls._rank[target] <= cls._rank[current]:
            return GateResult.pass_()

        reasons: list[str] = []
        if target is CredibilityTier.INFERRED:
            if not (has_independent_corroboration or has_human_verdict):
                reasons.append("corroboration_or_human_verdict")
        elif target is CredibilityTier.EXTRACTED:
            if not (has_direct_source or has_human_verdict):
                reasons.append("direct_source_or_human_verdict")
            if current is CredibilityTier.AMBIGUOUS and not has_human_verdict:
                reasons.append("ambiguous_to_extracted_requires_human_verdict")
        return GateResult.fail(reasons) if reasons else GateResult.pass_()


@dataclass(frozen=True)
class InternetObservation:
    """상계 인터넷 관측 1회분. 재수집은 수정이 아니라 새 observation 이다."""

    name: str
    url: str
    query: str
    retrieved_at: datetime
    content_hash: str
    fetch_tool: str
    source_type: str
    credibility: SourceCredibilityScore
    raw_snapshot_path: str | None = None
    revision_of: str | None = None

    def kg_properties(self) -> dict:
        return {
            "name": self.name,
            "url": self.url,
            "query": self.query,
            "retrieved_at": self.retrieved_at.isoformat(),
            "content_hash": self.content_hash,
            "fetch_tool": self.fetch_tool,
            "source_type": self.source_type,
            "raw_snapshot_path": self.raw_snapshot_path,
            "revision_of": self.revision_of,
            "trust": self.credibility.trust,
            "evidence_weight": self.credibility.evidence_weight,
            "tier": self.credibility.tier.value,
        }


@dataclass
class ObservationLedger:
    """인터넷 재수집 append-only 원장. (순수 in-memory 참조 모델 — 프로덕션 계보는 KG/adapters.)"""

    _items: dict[str, InternetObservation] = field(default_factory=dict)

    def add(self, observation: InternetObservation) -> InternetObservation:
        if observation.name in self._items:
            raise ValueError(f"observation already exists: {observation.name}")
        self._items[observation.name] = observation
        return observation

    def get(self, name: str) -> InternetObservation:
        try:
            return self._items[name]
        except KeyError as exc:
            raise KeyError(f"unknown observation: {name}") from exc

    def by_url(self, url: str) -> tuple[InternetObservation, ...]:
        return tuple(x for x in self._items.values() if x.url == url)

    def refetch(
        self,
        *,
        previous_name: str,
        name: str,
        retrieved_at: datetime,
        content_hash: str,
        fetch_tool: str,
        raw_snapshot_path: str | None = None,
        credibility: SourceCredibilityScore | None = None,
    ) -> InternetObservation:
        previous = self.get(previous_name)
        observation = replace(
            previous,
            name=name,
            retrieved_at=retrieved_at,
            content_hash=content_hash,
            fetch_tool=fetch_tool,
            raw_snapshot_path=raw_snapshot_path,
            credibility=credibility or previous.credibility,
            revision_of=previous.name,
        )
        return self.add(observation)


@dataclass(frozen=True)
class LakatosEvidence:
    """진보적 문제전환 판별에 필요한 최소 증거."""

    theory_laden_anomaly: bool
    independent_testable_consequence: bool
    excess_empirical_content: bool
    hard_core_preserved: bool
    implementation_complete: bool
    data_branch: bool = False
    data_replay_passed: bool = True
    human_verdict_required: bool = False


@dataclass(frozen=True)
class LakatosGateResult:
    verdict: LakatosVerdict
    reasons: tuple[str, ...]
    requires_human_verdict: bool = False


class LakatosGate:
    """라카토스 진보/퇴행 판별 게이트."""

    @staticmethod
    def evaluate(evidence: LakatosEvidence) -> LakatosGateResult:
        if evidence.human_verdict_required:
            return LakatosGateResult(
                LakatosVerdict.AMBIGUOUS,
                ("human_verdict_required",),
                requires_human_verdict=True,
            )

        # AXIS-CORR (audit qual-fidelity 2026-06-18): hard core 위반은 진보/퇴행 판정이 아니라
        # 정체성 사건 — 음의 휴리스틱을 떠나 *다른 프로그램*으로 간 것. degenerating(belt 내용-비진보,
        # 진보 축)으로 뭉뚱그리면 정체성 축과 진보 축이 섞인다(MSRP 곡해). 별 verdict 로 분리.
        if not evidence.hard_core_preserved:
            return LakatosGateResult(LakatosVerdict.DIFFERENT_PROGRAMME, ("hard_core_violated",))

        missing: list[str] = []
        if not evidence.theory_laden_anomaly:
            missing.append("theory_laden_anomaly")
        if not evidence.independent_testable_consequence:
            missing.append("independent_testable_consequence")
        if not evidence.excess_empirical_content:
            missing.append("excess_empirical_content")
        if missing:
            return LakatosGateResult(LakatosVerdict.DEGENERATING, tuple(missing))

        conditional: list[str] = []
        if not evidence.implementation_complete:
            conditional.append("implementation_incomplete")
        if evidence.data_branch and not evidence.data_replay_passed:
            conditional.append("data_replay_not_proven")
        if conditional:
            return LakatosGateResult(
                LakatosVerdict.PROGRESSIVE_CONDITIONAL,
                tuple(conditional),
            )
        return LakatosGateResult(LakatosVerdict.PROGRESSIVE, ())


@dataclass(frozen=True)
class LakatosNode:
    """라카토트리의 보존되는 가지. 기각 가지도 감사 이력으로 남는다."""

    name: str
    verdict: LakatosVerdict
    branch_from: str | None = None
    comment: str = ""
    metric_name: str | None = None
    metric_value: float | None = None
    open_questions: tuple[str, ...] = ()
    closed_questions: tuple[str, ...] = ()

    @property
    def is_canonical_candidate(self) -> bool:
        return self.verdict in {
            LakatosVerdict.PROGRESSIVE,
            LakatosVerdict.PROGRESSIVE_CONDITIONAL,
        }


@dataclass
class LakatosTree:
    """순수 in-memory 트리. 서버/KG 없이 엔진 판정을 테스트할 때 쓴다."""

    name: str
    hard_core: tuple[str, ...]
    _nodes: dict[str, LakatosNode] = field(default_factory=dict)

    def add_node(self, node: LakatosNode) -> LakatosNode:
        if node.name in self._nodes:
            raise ValueError(f"node already exists: {node.name}")
        if node.branch_from is not None and node.branch_from not in self._nodes:
            raise KeyError(f"unknown parent: {node.branch_from}")
        self._nodes[node.name] = node
        return node

    def branch(self, *, parent: str, node: LakatosNode) -> LakatosNode:
        if parent not in self._nodes:
            raise KeyError(f"unknown parent: {parent}")
        return self.add_node(replace(node, branch_from=parent))

    def get(self, name: str) -> LakatosNode:
        try:
            return self._nodes[name]
        except KeyError as exc:
            raise KeyError(f"unknown Lakatos node: {name}") from exc

    def nodes(self) -> tuple[LakatosNode, ...]:
        return tuple(self._nodes.values())

    def canonical_nodes(self) -> tuple[LakatosNode, ...]:
        return tuple(x for x in self._nodes.values() if x.is_canonical_candidate)

    def frontier_nodes(self) -> tuple[LakatosNode, ...]:
        return tuple(x for x in self.canonical_nodes() if x.open_questions)


@dataclass(frozen=True)
class BashAct:
    """하계 bash 실행. 실패도 기록 가능한 evidence 이지만, 성공 claim 은 별도 요구한다.
    (순수 in-memory 참조 모델 — 프로덕션 실행은 harness_run/_bash, 계보는 PROV/adapters.)"""

    name: str
    command: str
    cwd: str
    exit_code: int | None
    stdout_summary: str = ""
    stderr_summary: str = ""
    stdout_hash: str | None = None
    stderr_hash: str | None = None
    touched_files: tuple[str, ...] = ()
    git_sha: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None

    def evidence_ready(
        self,
        *,
        require_success: bool = False,
        require_git_sha: bool = False,
    ) -> GateResult:
        reasons: list[str] = []
        if not self.command.strip():
            reasons.append("command")
        if not self.cwd.strip():
            reasons.append("cwd")
        if self.exit_code is None:
            reasons.append("exit_code")
        if not (
            self.stdout_summary
            or self.stderr_summary
            or self.stdout_hash
            or self.stderr_hash
        ):
            reasons.append("stdout_or_stderr_evidence")
        if require_success and self.exit_code != 0:
            reasons.append("exit_code_zero")
        if require_git_sha and not self.git_sha:
            reasons.append("git_sha")
        return GateResult.fail(reasons) if reasons else GateResult.pass_()


@dataclass(frozen=True)
class LineageReplayResult(GateResult):
    roots: tuple[str, ...] = ()
    gaps: tuple[str, ...] = ()
    rebuild_plan: tuple[Derivation, ...] = ()
    stale: bool = False
    changed: tuple[tuple[str, tuple[tuple[str, str, str], ...]], ...] = ()
    env_drift: bool = False
    env_changed: tuple[str, ...] = ()   # 환경 지문 바뀐 산출물


class LineageReplayGate:
    """데이터 가지가 source root 에서 다시 만들어질 수 있는지 판정한다."""

    @staticmethod
    def evaluate(
        final_artifact: str,
        derivations: Iterable[Derivation],
        *,
        sources: set[str] | None = None,
        current_shas: dict[str, str] | None = None,
        current_env: str | None = None,
    ) -> LineageReplayResult:
        derivs = list(derivations)
        bo = by_output(derivs)
        if final_artifact not in bo:
            return LineageReplayResult(
                passed=False,
                reasons=("artifact_unrecorded",),
            )

        source_set = sources or {d.output for d in derivs if d.kind == "source"}
        try:
            root_set = roots(final_artifact, bo)
            gaps = reproducibility_gaps(final_artifact, bo, source_set)
            plan = tuple(rebuild_plan(final_artifact, bo))
        except ValueError as exc:
            return LineageReplayResult(
                passed=False,
                reasons=("lineage_cycle", str(exc)),
            )

        changed: list[tuple[str, tuple[tuple[str, str, str], ...]]] = []
        if current_shas is not None:
            for deriv in plan:
                bad = tuple(stale_inputs(deriv, current_shas))
                if bad:
                    changed.append((deriv.output, bad))

        env_changed: list[str] = []
        if current_env is not None:
            for deriv in plan:
                if deriv.env and deriv.env != current_env:
                    env_changed.append(deriv.output)   # 환경 바뀜 → float 결과 달라질 수 있음

        reasons: list[str] = []
        if gaps:
            reasons.append("reproducibility_gaps")
        if changed:
            reasons.append("stale_inputs")
        if env_changed:
            reasons.append("env_drift")
        return LineageReplayResult(
            passed=not reasons,
            reasons=tuple(reasons),
            roots=tuple(sorted(root_set)),
            gaps=tuple(sorted(gaps)),
            rebuild_plan=plan,
            stale=bool(changed),
            changed=tuple(changed),
            env_drift=bool(env_changed),
            env_changed=tuple(env_changed),
        )


@dataclass(frozen=True)
class ReproducibilityContract:
    """프로젝트별 root 데이터에서 final artifact 를 다시 만들 수 있어야 한다."""

    final_artifact: str
    root_artifacts: tuple[str, ...]
    tolerance: str | None = None

    def evaluate(
        self,
        derivations: Iterable[Derivation],
        *,
        current_shas: dict[str, str] | None = None,
        current_env: str | None = None,   # 나생문 F-ARCH-3: env 전달 (계약이 env-blind 였음)
    ) -> LineageReplayResult:
        return LineageReplayGate.evaluate(
            self.final_artifact,
            derivations,
            sources=set(self.root_artifacts),
            current_shas=current_shas,
            current_env=current_env,
        )
