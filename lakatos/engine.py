"""라카토트리 엔진 결합부.

기존 순수층은 이미 분리되어 있다:
trust.py = 인터넷 신뢰, judge.py = 판결, lineage.py = 데이터 계보,
argue.py = 인간/agent 비판, harness.py = 실제 포트 연결.

이 모듈은 그 층들이 조용히 서로를 우회하지 못하게 묶는 순수 게이트다.
인터넷 관측은 신뢰 승격 게이트를 통과해야 하고, bash 실행은 하계의
기록 가능한 세계 행위로 남아야 하며, 데이터 가지는 lineage 재생 가능성으로
검증된다.
# KG: span_lakatotree_engine
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from typing import Iterable

from .lineage import (
    Derivation,
    by_output,
    rebuild_plan,
    reproducibility_gaps,
    roots,
    stale_inputs,
)
from .trust import evidence_weight


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
        if self.trust >= 0.70 and (
            self.primary_source_bonus >= 0.80 or self.provenance_score >= 0.95
        ):
            return CredibilityTier.EXTRACTED
        if self.trust >= 0.35:
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
    """인터넷 재수집 append-only 원장."""

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

        missing: list[str] = []
        if not evidence.theory_laden_anomaly:
            missing.append("theory_laden_anomaly")
        if not evidence.independent_testable_consequence:
            missing.append("independent_testable_consequence")
        if not evidence.excess_empirical_content:
            missing.append("excess_empirical_content")
        if not evidence.hard_core_preserved:
            missing.append("hard_core_preserved")
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
    """하계 bash 실행. 실패도 기록 가능한 evidence 이지만, 성공 claim 은 별도 요구한다."""

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


class LineageReplayGate:
    """데이터 가지가 source root 에서 다시 만들어질 수 있는지 판정한다."""

    @staticmethod
    def evaluate(
        final_artifact: str,
        derivations: Iterable[Derivation],
        *,
        sources: set[str] | None = None,
        current_shas: dict[str, str] | None = None,
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

        reasons: list[str] = []
        if gaps:
            reasons.append("reproducibility_gaps")
        if changed:
            reasons.append("stale_inputs")
        return LineageReplayResult(
            passed=not reasons,
            reasons=tuple(reasons),
            roots=tuple(sorted(root_set)),
            gaps=tuple(sorted(gaps)),
            rebuild_plan=plan,
            stale=bool(changed),
            changed=tuple(changed),
        )
