"""연구전통층 — Laudan research tradition (diagnostic-only).

Laudan 의 research tradition 은 Lakatos hard core 와 *다른* 객체다(설계:
THEORY/lakatotree-open-gaps/research_tradition_design.md). hard core 위반은 여전히 프로그램 *정체성*
사건(engine.LakatosGate / HardCoreProtected)이고, 이 층은 *진단 전용* — 가변 ontology/methodology 표류를
서술하되 정본 승격·폐기·hard-core 정체성을 침묵 변경하지 않는다(authority=diagnostic_only, invariant 1~5).

판정(appraise_tradition_revision):
  routine commitment 수정          → same_tradition_revision (일상 보호대 수정)
  costly commitment 수정           → tradition_drift (단 receipt+compatibility_claim 이면 same_tradition_revision)
  identity_boundary commitment 수정 → different_programme_candidate (직접 hard-core 위반 *아님* —
                                     engine.LakatosGate/HardCoreProtected 경유해야 확정)
# KG: span_lakatotree_tradition
라이선스(THEORY §8): laudan1977
"""
from __future__ import annotations

from dataclasses import dataclass

DIAGNOSTIC_ONLY_AUTHORITY = "diagnostic_only"

COMMITMENT_KINDS = ("ontology", "methodology", "exemplar", "problem_type", "background_theory")
REVISABILITY = ("routine", "costly", "identity_boundary")
REVISION_OPERATIONS = ("add", "modify", "retire", "reclassify")
TRADITION_OUTCOMES = ("same_tradition_revision", "tradition_drift", "different_programme_candidate")

# 가변성 → 진단 압력(diagnostic): routine 무압, costly 중압, identity_boundary 최대. 정책값(영감 laudan1977).
_REVISABILITY_PRESSURE = {"routine": 0.0, "costly": 0.5, "identity_boundary": 1.0}
# 개념(conceptual) commitment 류 — 개념 압력은 여기서 산다(empirical 문제수지에 섞기 *전*, invariant 5).
_CONCEPTUAL_KINDS = ("ontology", "background_theory", "problem_type", "exemplar")


@dataclass(frozen=True)
class TraditionCommitment:
    """전통의 한 약속(commitment). revisability 가 정체성 경계를 가른다."""

    commitment_id: str
    kind: str                     # COMMITMENT_KINDS
    statement: str
    revisability: str = "routine"  # REVISABILITY: routine | costly | identity_boundary
    source_refs: tuple = ()

    def __post_init__(self) -> None:
        if not self.commitment_id.strip():
            raise ValueError("commitment_id 비어있을 수 없음")
        if self.kind not in COMMITMENT_KINDS:
            raise ValueError(f"kind 는 {COMMITMENT_KINDS} 중 (받음: {self.kind})")
        if self.revisability not in REVISABILITY:
            raise ValueError(f"revisability 는 {REVISABILITY} 중 (받음: {self.revisability})")


@dataclass(frozen=True)
class TraditionRevision:
    """한 commitment 에 대한 수정 제안 + 양립 영수증(있으면 costly 표류를 막는다)."""

    target_commitment_id: str
    operation: str                # REVISION_OPERATIONS
    reason: str = ""
    receipt_refs: tuple = ()
    compatibility_claim: str = ""

    def __post_init__(self) -> None:
        if not self.target_commitment_id.strip():
            raise ValueError("target_commitment_id 비어있을 수 없음")
        if self.operation not in REVISION_OPERATIONS:
            raise ValueError(f"operation 은 {REVISION_OPERATIONS} 중 (받음: {self.operation})")


@dataclass(frozen=True)
class ResearchTradition:
    """프로그램 가족의 가변 ontology/methodology/exemplar 컨테이너 (hard core 보다 넓고 가변)."""

    tradition_id: str
    name: str
    ontology_commitments: tuple = ()
    methodology_rules: tuple = ()
    exemplars: tuple = ()
    accepted_problem_types: tuple = ()
    background_theories: tuple = ()
    revision_policy: str = ""
    compatibility_notes: str = ""

    def __post_init__(self) -> None:
        if not self.tradition_id.strip():
            raise ValueError("tradition_id 비어있을 수 없음")
        if not self.name.strip():
            raise ValueError("name 비어있을 수 없음")


@dataclass(frozen=True)
class TraditionAppraisal:
    """전통 수정 진단 결과 — authority 는 항상 diagnostic_only(승격/폐기 권위 0)."""

    outcome: str                  # TRADITION_OUTCOMES
    conceptual_pressure: float
    methodology_pressure: float
    ontology_pressure: float
    reasons: tuple
    authority: str = DIAGNOSTIC_ONLY_AUTHORITY


def appraise_tradition_revision(commitment: TraditionCommitment,
                                revision: TraditionRevision) -> TraditionAppraisal:
    """전통 commitment 수정 → 진단 판정. authority=diagnostic_only — verdict/승격 권위 0(invariant 4).

    identity_boundary 는 *different_programme 후보*일 뿐 직접 hard-core 위반이 아니다(invariant 1/3):
    실제 hard-core 정체성은 engine.LakatosGate / HardCoreProtected 가 결정한다.
    """
    if revision.target_commitment_id != commitment.commitment_id:
        raise ValueError(
            f"revision.target({revision.target_commitment_id}) ≠ commitment.id({commitment.commitment_id})")
    rev = commitment.revisability
    receipts_ok = bool(revision.receipt_refs) and bool(revision.compatibility_claim.strip())
    reasons: list[str] = []
    if rev == "routine":
        outcome = "same_tradition_revision"
        reasons.append("routine commitment — 일상 보호대 수정")
    elif rev == "costly":
        if receipts_ok:
            outcome = "same_tradition_revision"
            reasons.append("costly commitment 이나 receipt+compatibility_claim 으로 양립 정당화")
        else:
            outcome = "tradition_drift"
            reasons.append("costly commitment 수정 — 양립 영수증 부재 → 전통 표류")
    else:   # identity_boundary (생성자가 enum 보증)
        outcome = "different_programme_candidate"
        reasons.append("identity_boundary commitment 수정 — 다른 프로그램 *후보*(직접 hard-core 위반 아님; "
                       "engine.LakatosGate/HardCoreProtected 경유 확정)")
    pressure = 0.0 if outcome == "same_tradition_revision" else _REVISABILITY_PRESSURE[rev]
    return TraditionAppraisal(
        outcome=outcome,
        conceptual_pressure=pressure if commitment.kind in _CONCEPTUAL_KINDS else 0.0,
        methodology_pressure=pressure if commitment.kind == "methodology" else 0.0,
        ontology_pressure=pressure if commitment.kind == "ontology" else 0.0,
        reasons=tuple(reasons),
        authority=DIAGNOSTIC_ONLY_AUTHORITY,
    )
