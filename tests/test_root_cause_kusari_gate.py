"""rerunnable acceptance check — BPC.RootCauseKusariChecklist (Longinus 바인딩 PIERCE).

준거: docs/LONGINUS_ROOT_CAUSE_KUSARI_20260624.md.
claim: root-cause critique 는 공격하는 정확한 coordinate_frame/datum/algorithm/feature/threshold 를 명명해야 한다.
acceptance: 모든 critique 항목은 target_artifact / failure_mode / expected_observable / blocking_verdict 를 포함.
이 테스트가 그 체크리스트를 fail-closed 로 강제한다(vague critique = LabelRot 차단).
# KG: CT_LakatoTree_3D_PROM_LonginusReview_20260624 / BPC.RootCauseKusariChecklist
"""
from __future__ import annotations

import pytest

from lakatos.verdict.kusari import (
    REQUIRED_FIELDS,
    TARGET_AXES,
    KusariVerdict,
    lint_checklist,
    lint_critique,
)


def _critique(**over) -> dict:
    """doc Root-Cause Stack 'Registration geometry' 행을 구조화한 잘 형성된 critique 항목."""
    base = {
        "target_artifact": "examples/bpc_icp_programme.py::free_multiview_icp",
        "failure_mode": "flat/repetitive/symmetric parts create null spaces and local minima (rank-deficiency)",
        "expected_observable": "seam/ICP residual collapses into a false minimum; yaw eigenvalue ~1.4e-4",
        "blocking_verdict": "degenerating",
        # claim: 공격 대상의 정확한 명명(이 critique 는 algorithm/feature/threshold 축을 짚는다)
        "algorithm": "free global ICP (small_gicp VGICP)",
        "feature": "planar panel + periodic 18mm pockets",
        "threshold": "seam <= 1.0mm",
    }
    base.update(over)
    return base


# ── 잘 형성된 항목: 통과 ──────────────────────────────────────────────────────
def test_well_formed_critique_passes():
    v = lint_critique(_critique())
    assert isinstance(v, KusariVerdict)
    assert v.valid is True
    assert v.problems == ()


# ── 4대 필수 필드 누락 → fail-closed ──────────────────────────────────────────
@pytest.mark.parametrize("field", REQUIRED_FIELDS)
def test_missing_required_field_fails(field):
    item = _critique()
    del item[field]
    v = lint_critique(item)
    assert v.valid is False
    assert field in v.problems


def test_empty_or_none_required_field_fails():
    assert lint_critique(_critique(failure_mode="")).valid is False
    assert lint_critique(_critique(expected_observable=None)).valid is False
    assert lint_critique(_critique(target_artifact="   ")).valid is False


# ── claim: 정확한 공격 대상 명명(5축 중 최소 1개) ─────────────────────────────
def test_no_target_axis_named_fails():
    """frame/datum/algorithm/feature/threshold 를 하나도 명명 안 하면 vague critique → fail."""
    item = _critique()
    for axis in TARGET_AXES:
        item.pop(axis, None)
    v = lint_critique(item)
    assert v.valid is False
    assert "target_specificity" in v.problems
    assert any(a in v.reason for a in TARGET_AXES)   # reason 이 어떤 축을 요구하는지 안내


@pytest.mark.parametrize("axis", TARGET_AXES)
def test_any_single_target_axis_satisfies_specificity(axis):
    item = _critique()
    for a in TARGET_AXES:
        item.pop(a, None)
    item[axis] = "the exact thing under attack"
    v = lint_critique(item)
    assert v.valid is True, v
    assert "target_specificity" not in v.problems


# ── blocking_verdict 는 blocking-class 여야(critique 가 통과판결을 달 수 없음) ──
def test_non_blocking_verdict_fails():
    for passing in ("pass", "PASS-PRODUCTION-CANDIDATE", "progressive", "CANONICAL", "adopted"):
        v = lint_critique(_critique(blocking_verdict=passing))
        assert v.valid is False, passing
        assert any("blocking_verdict" in p for p in v.problems)


@pytest.mark.parametrize("blocking", ["NO-GO", "BLOCKED", "REFUTED", "rejected", "indeterminate", "CONDITIONAL"])
def test_blocking_class_verdicts_accepted(blocking):
    assert lint_critique(_critique(blocking_verdict=blocking)).valid is True


# ── 입력 위생 + 체크리스트(전 항목) ───────────────────────────────────────────
def test_non_dict_is_invalid_not_crash():
    assert lint_critique(None).valid is False
    assert lint_critique("not a critique").valid is False


def test_checklist_fails_if_any_item_fails():
    good = _critique()
    bad = _critique(failure_mode="")           # 한 항목 결함
    v = lint_checklist([good, bad, good])
    assert v.valid is False
    assert any("1" in p for p in v.problems)   # 결함 항목 인덱스(1) 식별
    # 전부 양호하면 통과
    assert lint_checklist([good, good]).valid is True


def test_empty_checklist_is_invalid():
    """빈 체크리스트는 '검증함'이 아니다 — 항목 0개는 fail-closed."""
    assert lint_checklist([]).valid is False
