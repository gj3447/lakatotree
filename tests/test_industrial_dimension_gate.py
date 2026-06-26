"""rerunnable acceptance check — BPC.IndustrialDimensionJudgementGate (Longinus 바인딩 PIERCE).

준거: docs/LONGINUS_INDUSTRIAL_DIMENSION_JUDGEMENT_20260624.md "Required Promotion Gate Patch".
claim: 산업 차원판정은 measurement 수용 전에 accuracy/precision/uncertainty/repeatability/CAD residual
       /traceability 를 분리해 갖춰야 한다. 어느 한 축이라도 없으면 progressive 일 수는 있어도
       industrial-production-adopted 는 불가(fail-closed) — 그리고 near-limit 은 강제 indeterminate.
이 테스트가 게이트의 그 규율을 실측으로 강제한다(= 바인딩 acceptance_check, rerunnable).
# KG: CT_LakatoTree_3D_PROM_LonginusReview_20260624 / BPC.IndustrialDimensionJudgementGate
"""
from __future__ import annotations

import pytest

from lakatos.verdict.industrial import (
    REQUIRED_FIELDS,
    DimensionVerdict,
    judge_dimension,
)


def _complete(**over) -> dict:
    """스키마 완비된 production 차원결과(기본=공차 내·게이지 acceptable)."""
    base = {
        "measurand": "FRT_pair_distance",
        "cad_nominal": {"value": 1093.3, "unit": "mm"},
        "measured": {"value": 1093.1, "unit": "mm"},
        "deviation": {"value": -0.2, "unit": "mm"},
        "tolerance": {"lower": -1.0, "upper": 1.0, "unit": "mm"},
        "uncertainty": {"u_c": 0.15, "U_k2": 0.30, "method": "GUM"},
        "decision_rule": "guard_band",
        "conformity_state": "pass",
        "gauge": {"rr_percent_tolerance": 18.0, "status": "acceptable"},
        "independent_truth": "CMM",
        "negative_controls": ["wrong_axis", "free_icp"],
    }
    base.update(over)
    return base


# ── 완비 결과: 정상 판정 ──────────────────────────────────────────────────────
def test_complete_in_tolerance_is_production_candidate():
    v = judge_dimension(_complete())
    assert isinstance(v, DimensionVerdict)
    assert v.verdict == "PASS-PRODUCTION-CANDIDATE"
    assert v.conformity == "pass"
    assert v.missing == ()


# ── 핵심: 4대 명시축(uncertainty/repeatability/CAD residual/traceability) 누락 → BLOCKED ──
@pytest.mark.parametrize("field, axis", [
    ("uncertainty", "uncertainty"),
    ("gauge", "repeatability"),          # gauge R&R = 반복성/게이지능력
    ("deviation", "cad_residual"),       # measured−cad_nominal = CAD residual
    ("independent_truth", "traceability"),
])
def test_missing_named_axis_is_blocked(field, axis):
    r = _complete()
    del r[field]
    v = judge_dimension(r)
    assert v.verdict == "BLOCKED", v
    assert field in v.missing
    assert axis in v.reason          # reason 이 빠진 축을 사람이 읽을 이름으로 명시


def test_every_required_field_missing_blocks():
    """REQUIRED_FIELDS 의 어느 하나라도 빠지면 전부 BLOCKED (fail-closed 전수)."""
    for field in REQUIRED_FIELDS:
        r = _complete()
        del r[field]
        v = judge_dimension(r)
        assert v.verdict == "BLOCKED", f"{field} 누락인데 BLOCKED 아님: {v}"
        assert field in v.missing


def test_present_but_empty_or_none_counts_as_missing():
    assert judge_dimension(_complete(uncertainty=None)).verdict == "BLOCKED"
    assert judge_dimension(_complete(negative_controls=[])).verdict == "BLOCKED"
    assert judge_dimension(_complete(independent_truth="")).verdict == "BLOCKED"
    # 하위 필드 부재(확장불확도 U_k2 없음)도 불완전 → BLOCKED
    assert judge_dimension(_complete(uncertainty={"u_c": 0.1, "method": "GUM"})).verdict == "BLOCKED"


# ── near-limit 강제 indeterminate (doc: "industrial release needs indeterminate") ──
def test_near_limit_forces_indeterminate_conditional():
    # |tol_upper − |dev|| = |1.0 − 0.85| = 0.15 < U_k2(0.30) → 가드밴드 내 = indeterminate
    v = judge_dimension(_complete(deviation={"value": 0.85, "unit": "mm"}))
    assert v.conformity == "indeterminate"
    assert v.verdict == "CONDITIONAL"


def test_claimed_pass_near_limit_is_not_trusted():
    """자기보고 conformity='pass' 라도 near-limit 이면 게이트가 indeterminate 로 재계산(자기채점 금지)."""
    r = _complete(deviation={"value": 0.95, "unit": "mm"}, conformity_state="pass")
    v = judge_dimension(r)
    assert v.conformity == "indeterminate"
    assert v.verdict == "CONDITIONAL"


# ── 공차 초과(불확도 밖) → NO-GO ──────────────────────────────────────────────
def test_out_of_tolerance_beyond_uncertainty_is_no_go():
    # dev 1.5 > tol 1.0, |1.0−1.5|=0.5 > U(0.30) → near-limit 아님 → fail
    v = judge_dimension(_complete(deviation={"value": 1.5, "unit": "mm"}))
    assert v.conformity == "fail"
    assert v.verdict == "NO-GO"


# ── 게이지(MSA repeatability) unacceptable → PASS 불가, CONDITIONAL 상한 (BPC 케이스) ──
def test_unacceptable_gauge_caps_at_conditional():
    v = judge_dimension(_complete(gauge={"rr_percent_tolerance": 80.0, "status": "unacceptable"}))
    assert v.conformity == "pass"          # 편차는 공차 내
    assert v.verdict == "CONDITIONAL"      # 그러나 게이지 약함 → production-candidate 아님


def test_borderline_gauge_caps_at_conditional():
    v = judge_dimension(_complete(gauge={"rr_percent_tolerance": 28.0, "status": "borderline"}))
    assert v.verdict == "CONDITIONAL"


# ── 입력 위생 ────────────────────────────────────────────────────────────────
def test_non_dict_input_is_blocked_not_crash():
    assert judge_dimension(None).verdict == "BLOCKED"
    assert judge_dimension("not a result").verdict == "BLOCKED"
