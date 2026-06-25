"""Longinus 근본원인(鎖, kusari) critique 게이트 — vague critique 를 fail-closed 로 차단.

준거: docs/LONGINUS_ROOT_CAUSE_KUSARI_20260624.md.
claim: root-cause critique 는 공격하는 정확한 coordinate_frame / datum / algorithm / feature /
       threshold 를 명명해야 한다(막연한 비판 금지 = LabelRot 차단).
acceptance: 모든 critique 항목은 target_artifact / failure_mode / expected_observable /
       blocking_verdict 를 포함해야 한다.

게이트:
  · 4대 필수 필드 중 하나라도 결여/공백 → invalid.
  · blocking_verdict 는 *blocking-class* 여야 한다(통과판결로 critique 라 우길 수 없음).
  · 공격 대상 명명: coordinate_frame/datum/algorithm/feature/threshold 중 *최소 1개* 를 짚어야 한다
    (모든 critique 가 5축 전부를 공격하진 않지만, 정확히 무엇을 치는지는 반드시 명명).
  · lint_checklist: 항목이 0개거나 한 항목이라도 실패하면 전체 invalid("Every critique item").

acceptance check(rerunnable): tests/test_root_cause_kusari_gate.py
※ frontier(후속): critique 를 생성하는 surface(mcp critique 툴/리뷰 파이프라인)에 이 게이트를
   강제 배선하는 것은 별도 작업으로 남긴다 — 현재는 호출가능한 린트 면을 제공한다.
# KG: CT_LakatoTree_3D_PROM_LonginusReview_20260624 / consumer_b.RootCauseKusariChecklist
"""
from __future__ import annotations

from dataclasses import dataclass

# acceptance_check 가 명시한 4대 필수 필드.
REQUIRED_FIELDS: tuple[str, ...] = (
    "target_artifact",       # 공격 대상(파일/노드/리포트 등 구체 산출물)
    "failure_mode",          # 실패 양식
    "expected_observable",   # 기대 관측치(닫힘/반증 조건)
    "blocking_verdict",      # 막는 판결(blocking verdict)
)

# claim 의 "정확한 명명" 5축 — 최소 1개를 짚어야 한다.
TARGET_AXES: tuple[str, ...] = (
    "coordinate_frame",
    "datum",
    "algorithm",
    "feature",
    "threshold",
)

# blocking-class 판결(통과판결은 critique 의 blocking_verdict 가 될 수 없음).
BLOCKING_VERDICTS = frozenset({
    "no-go", "blocked", "refuted", "rejected", "degenerating",
    "conditional", "research-only", "indeterminate",
})


@dataclass(frozen=True)
class KusariVerdict:
    valid: bool
    problems: tuple[str, ...]
    reason: str


def _empty(v) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def lint_critique(item) -> KusariVerdict:
    """단일 root-cause critique 항목을 린트. 막연/불완전하면 valid=False(fail-closed)."""
    if not isinstance(item, dict):
        return KusariVerdict(False, ("<item>",), "critique 가 dict 아님 — 입력 계약 위반(fail-closed)")

    problems: list[str] = [f for f in REQUIRED_FIELDS if _empty(item.get(f))]

    bv = item.get("blocking_verdict")
    if not _empty(bv) and str(bv).strip().lower() not in BLOCKING_VERDICTS:
        problems.append("blocking_verdict:non-blocking")

    if not any(not _empty(item.get(a)) for a in TARGET_AXES):
        problems.append("target_specificity")

    if not problems:
        return KusariVerdict(True, (), "critique well-formed: 4 필수 + blocking-class + 공격대상 명명.")

    bits: list[str] = []
    missing_req = [p for p in problems if p in REQUIRED_FIELDS]
    if missing_req:
        bits.append("필수 필드 누락/공백=" + ",".join(missing_req))
    if "blocking_verdict:non-blocking" in problems:
        bits.append(f"blocking_verdict({bv}) 가 blocking-class 아님 — 통과판결로 critique 불가")
    if "target_specificity" in problems:
        bits.append("공격 대상 미명명 — " + "/".join(TARGET_AXES) + " 중 최소 1개 필요")
    return KusariVerdict(False, tuple(problems), "; ".join(bits))


def lint_checklist(items) -> KusariVerdict:
    """critique 체크리스트 전체. 항목 0개거나 하나라도 실패하면 invalid('Every critique item')."""
    if not isinstance(items, (list, tuple)) or len(items) == 0:
        return KusariVerdict(False, ("<empty>",),
                             "체크리스트가 비었거나 리스트 아님 — 항목 0개는 검증이 아니다(fail-closed)")
    problems = [
        f"item[{i}]: {','.join(v.problems)}"
        for i, it in enumerate(items)
        if not (v := lint_critique(it)).valid
    ]
    if not problems:
        return KusariVerdict(True, (), "모든 critique 항목 well-formed.")
    return KusariVerdict(False, tuple(problems), " | ".join(problems))
