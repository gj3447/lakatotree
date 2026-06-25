"""Longinus 산업 차원판정 게이트 — production 차원결과가 불완전/약하면 fail-closed.

준거: docs/LONGINUS_INDUSTRIAL_DIMENSION_JUDGEMENT_20260624.md "Required Promotion Gate Patch".
연구진보(progressive)와 산업채택(industrial-production-adopted)을 *분리*한다:

  · 스키마(measurand/cad_nominal/measured/deviation/tolerance/uncertainty/decision_rule/
    conformity_state/gauge/independent_truth/negative_controls)의 어느 한 필드라도 없거나
    불완전하면 → **BLOCKED** (progressive 일 수는 있어도 production-adopted 불가).
  · near-limit(|tolerance − |deviation|| < 확장불확도 U_k2)은 강제 **indeterminate** —
    binary pass/fail 금지("industrial release needs indeterminate").
  · conformity 는 자기보고를 신뢰하지 않고 게이트가 *재계산*한다(자기채점 금지, 엔진 정신).
  · gauge(MSA R&R) 가 acceptable 이 아니면 편차가 공차 내여도 PASS-PRODUCTION-CANDIDATE 아님(=CONDITIONAL).

이 게이트의 acceptance check 는 tests/test_industrial_dimension_gate.py (rerunnable).
※ frontier(후속): 이 게이트를 promotion 경로(promote.promotion_gate)에 박아 'adopted' 승격을
   강제하는 배선은 공개 API 변경이라 별도 작업으로 남긴다 — 현재는 호출가능한 판정면을 제공한다.
# KG: CT_LakatoTree_3D_PROM_LonginusReview_20260624 / consumer_b.IndustrialDimensionJudgementGate
"""
from __future__ import annotations

from dataclasses import dataclass

# Required Promotion Gate Patch 스키마(doc 라인 297-313). 하나라도 빠지면 production-adopted 불가.
REQUIRED_FIELDS: tuple[str, ...] = (
    "measurand",
    "cad_nominal",
    "measured",
    "deviation",
    "tolerance",
    "uncertainty",
    "decision_rule",
    "conformity_state",
    "gauge",
    "independent_truth",
    "negative_controls",
)

# dict 필드가 실질을 가지려면 있어야 하는 하위 키(계산·판정에 load-bearing 한 것).
_SUBKEYS: dict[str, tuple[str, ...]] = {
    "cad_nominal": ("value",),
    "measured": ("value",),
    "deviation": ("value",),
    "tolerance": ("upper",),
    "uncertainty": ("U_k2",),   # 확장불확도(k=2) — 가드밴드 판정에 필수
    "gauge": ("status",),
}

# 바인딩 acceptance_check 가 명시한 4대 축 → 사람이 읽을 이름(BLOCKED reason 에 노출).
AXIS_LABEL: dict[str, str] = {
    "uncertainty": "uncertainty",
    "gauge": "repeatability",        # gauge R&R = 반복성/게이지 능력(MSA)
    "deviation": "cad_residual",     # measured − cad_nominal = CAD 잔차
    "independent_truth": "traceability",
}

VERDICTS: tuple[str, ...] = (
    "PASS-PRODUCTION-CANDIDATE",
    "CONDITIONAL",
    "RESEARCH-ONLY",
    "NO-GO",
    "BLOCKED",
)


@dataclass(frozen=True)
class DimensionVerdict:
    verdict: str                  # VERDICTS 중 하나
    missing: tuple[str, ...]      # 누락/불완전 필드(없으면 빈 튜플)
    conformity: str               # pass | fail | indeterminate (게이트 재계산값)
    reason: str


def _absent(result: dict, field: str) -> bool:
    """필드가 없거나 None 이거나, dict/리스트/문자열로서 실질이 비면 True(불완전=누락)."""
    if field not in result:
        return True
    v = result[field]
    if v is None:
        return True
    if field in _SUBKEYS:
        if not isinstance(v, dict):
            return True
        return any(v.get(sk) is None for sk in _SUBKEYS[field])
    if field == "negative_controls":
        return not (isinstance(v, (list, tuple)) and len(v) > 0)
    if isinstance(v, str):
        return v.strip() == ""
    return False


def judge_dimension(result) -> DimensionVerdict:
    """산업 차원판정. 불완전 → BLOCKED, near-limit → indeterminate, 게이지 약함 → 상한 CONDITIONAL."""
    if not isinstance(result, dict):
        return DimensionVerdict("BLOCKED", ("<result>",), "indeterminate",
                                "결과가 dict 아님 — 입력 계약 위반(fail-closed)")

    missing = tuple(f for f in REQUIRED_FIELDS if _absent(result, f))
    if missing:
        labels = ", ".join(f"{f}({AXIS_LABEL[f]})" if f in AXIS_LABEL else f for f in missing)
        return DimensionVerdict(
            "BLOCKED", missing, "indeterminate",
            f"누락/불완전 필드: {labels} — 산업채택(production-adopted) 불가, fail-closed "
            "(연구상 progressive 일 수는 있음).")

    dev = abs(float(result["deviation"]["value"]))
    tol_upper = float(result["tolerance"]["upper"])
    u_k2 = float(result["uncertainty"]["U_k2"])
    margin = tol_upper - dev

    if abs(margin) < u_k2:                      # 확장불확도 가드밴드 안 = 결정 불가
        conformity = "indeterminate"
    elif dev <= tol_upper:
        conformity = "pass"
    else:
        conformity = "fail"

    gauge_status = result["gauge"].get("status")

    if conformity == "fail":
        verdict = "NO-GO"
    elif conformity == "indeterminate":
        verdict = "CONDITIONAL"                 # near-limit = guard-band 판단 필요
    elif gauge_status == "acceptable":
        verdict = "PASS-PRODUCTION-CANDIDATE"
    else:
        verdict = "CONDITIONAL"                 # 편차는 공차 내지만 게이지(MSA) 약함

    reason = (f"conformity={conformity} (|dev|={dev:.3f} vs tol={tol_upper:.3f}, U_k2={u_k2:.3f}, "
              f"margin={margin:.3f}); gauge={gauge_status}; decision_rule={result['decision_rule']}.")
    return DimensionVerdict(verdict, (), conformity, reason)
