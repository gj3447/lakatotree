"""Longinus consumer_b Z-height/CAD-surface 게이트 — registration green 이 wrong-z 를 숨기지 못하게 fail-closed.

준거: docs/BPC_Z_HEIGHT_CAD_SURFACE_PROM_20260624.md "Required consumer_b Z Guards".
실패양식: good CAD registration 이 (global/rigid residual) + (CAD layer membership) + (measured contact) 를
한 숫자로 뭉개면, feature 의 Z 가 several-mm 틀려도 "정합 OK"로 보인다. 이 게이트는 세 surface 를 *분리*
강제한다:
  · rigid residual            = registration_residual_mm
  · per-feature z residual     = z_signed_error_mm
  · frame/sign audit           = candidate_layers(경쟁 후보 ≥2, z_frame_state/chirality 감사) + selected_layer
하나라도 결여/뭉갬 → BLOCKED. 그리고 핵심(LGN-consumer_b-Z-003): registration 이 green(작은 residual)이어도
|z_signed_error| 가 rigid residual + 확장불확도(U_k2) 를 넘으면 **Z-NOT-CERTIFIED** — 정합 metric 이 z-차원을
보증하지 못한다(repeatable wrong-layer 도 wrong).

acceptance check(rerunnable): tests/test_z_height_gate.py (실 consumer_b feature_z_offset_per_hole.json 으로 검증,
부재 시 hermetic skip).
※ frontier(후속): wrong-layer/wrong-axis/free-ICP/panel-only/nearest-triangle/shuffled-ID 음성대조 실행 강제
   배선(별도 바인딩 consumer_b.ZLayerNegativeControlsExecuted = CANDIDATE).
# KG: CT_LakatoTree_3D_PROM_LonginusReview_20260624 / consumer_b.ZHeightCadSurfaceFailureMode
"""
from __future__ import annotations

from dataclasses import dataclass

# Required consumer_b Z Guards 스키마(doc 라인 179-198)의 load-bearing 필드. 하나라도 결여 → 뭉갬 = BLOCKED.
REQUIRED_FIELDS: tuple[str, ...] = (
    "measurand",
    "datum_frame",
    "intended_cad_layer",
    "candidate_layers",          # frame/sign audit: 경쟁 후보 ≥2 (단일=뭉갬)
    "selected_layer",
    "layer_selection_rule",
    "z_signed_error_mm",         # per-feature z residual (rigid 와 분리)
    "registration_residual_mm",  # rigid residual (z 와 분리)
    "uncertainty",               # U_k2_mm 필요
    "decision_rule",
    "conformity_state",
)


@dataclass(frozen=True)
class ZHeightVerdict:
    verdict: str                         # BLOCKED | Z-NOT-CERTIFIED | Z-INDETERMINATE | Z-PASS-CANDIDATE
    missing: tuple[str, ...]
    z_certified_by_registration: bool
    reason: str


def _absent(result: dict, field: str) -> bool:
    if field not in result:
        return True
    v = result[field]
    if v is None:
        return True
    if field == "candidate_layers":
        # frame/sign audit 는 경쟁 후보(≥2)를 *보여야* 한다 — 단일 후보 = 감사 뭉갬.
        return not (isinstance(v, (list, tuple)) and len(v) >= 2)
    if field == "uncertainty":
        return not (isinstance(v, dict) and v.get("U_k2_mm") is not None)
    if field in ("z_signed_error_mm", "registration_residual_mm"):
        return not isinstance(v, (int, float))
    if isinstance(v, str):
        return v.strip() == ""
    return False


def judge_z_height(result) -> ZHeightVerdict:
    """consumer_b Z 결과 판정. 세 surface 뭉개짐 → BLOCKED; registration green 이 z 오차 숨기면 Z-NOT-CERTIFIED."""
    if not isinstance(result, dict):
        return ZHeightVerdict("BLOCKED", ("<result>",), False,
                              "결과가 dict 아님 — 입력 계약 위반(fail-closed)")

    missing = tuple(f for f in REQUIRED_FIELDS if _absent(result, f))
    if missing:
        return ZHeightVerdict(
            "BLOCKED", missing, False,
            f"세 surface 뭉갬/결여: {', '.join(missing)} — rigid residual·per-feature z·frame/sign audit 를 "
            "분리해야 production-adopted (fail-closed).")

    zerr = abs(float(result["z_signed_error_mm"]))
    reg = abs(float(result["registration_residual_mm"]))
    u_k2 = float(result["uncertainty"]["U_k2_mm"])

    if zerr > reg + u_k2:
        return ZHeightVerdict(
            "Z-NOT-CERTIFIED", (), False,
            f"registration residual {reg:.3f}mm 이 green 이어도 per-feature z {zerr:.3f}mm 가 "
            f"reg+U_k2({reg + u_k2:.3f}mm) 초과 — 정합 metric 이 z-차원을 보증 못함(LGN-consumer_b-Z-003).")
    if zerr <= u_k2:
        return ZHeightVerdict(
            "Z-PASS-CANDIDATE", (), True,
            f"z {zerr:.3f}mm ≤ U_k2 {u_k2:.3f}mm, registration {reg:.3f}mm 와 정합 — guard-band 후 PPAP/MSA 검토 대상.")
    return ZHeightVerdict(
        "Z-INDETERMINATE", (), False,
        f"z {zerr:.3f}mm 가 U_k2({u_k2:.3f}) 밖이나 reg+U_k2({reg + u_k2:.3f}) 안 — guard-band 결정 필요(indeterminate).")
