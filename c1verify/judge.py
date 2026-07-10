"""Scoring kernel — byte-exact RE-IMPLEMENTATION of lakatos.verdict.judge (NOT an import).

The engine's verdict is a deterministic function of a pre-registered prediction and the measurement:
judge(spec, measured, novel_target, novel_measured) -> {progressive|partial|equivalent|rejected}. C1
re-derives it here (over plain dicts, since the verifier reads JSON, not dataclasses) so an outsider
re-checks that a receipt's sealed verdict is what judge() actually produces from the shown spec —
catching a HAND-TYPED verdict inconsistent with its spec. Copy-fidelity to the engine is pinned by an
out-of-band golden cross-check (c1verify.judge agrees with lakatos.judge over a fuzz corpus).

Residual it does NOT close: that the shown spec was FIXED BEFORE the result (not back-fit to make
judge() emit the desired verdict). That needs a content-sealed PredictionReceipt at registration +
witnessed temporal ordering — enumerated, never discharged here.
"""
from __future__ import annotations

import math

SCALE_TYPES = ("ratio", "interval", "ordinal", "nominal")


class JudgeError(ValueError):
    """Invalid spec / non-finite input — fail-closed: the caller REJECTs (never a silent verdict)."""


def _finite_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _validate_spec(spec: dict) -> None:
    """Mirror Prediction.__post_init__ (lakatos.verdict.judge:39-55)."""
    if not isinstance(spec, dict):
        raise JudgeError("spec is not an object")
    scale = spec.get("scale_type", "ratio")
    if scale not in SCALE_TYPES:
        raise JudgeError(f"scale_type must be one of {SCALE_TYPES}")
    if scale == "nominal":
        raise JudgeError("nominal metric has no order — no progress direction (Stevens)")
    noise_band = spec.get("noise_band", 0.0)
    if not _finite_number(noise_band):
        raise JudgeError("noise_band must be a finite number")
    if scale == "ordinal" and noise_band != 0:
        raise JudgeError("ordinal metric forbids a magnitude noise_band (Stevens)")
    if noise_band < 0:
        raise JudgeError("noise_band must be >= 0 (blocks worse-is-progressive gaming)")
    if not _finite_number(spec.get("baseline_value")):
        raise JudgeError("baseline_value must be finite")
    if spec.get("direction") not in ("lower", "higher"):
        raise JudgeError("direction must be 'lower' | 'higher'")


def _corroborated(direction: str, threshold: float, measured: float) -> bool:
    if direction == "lower":
        return measured <= threshold
    return measured >= threshold


def judge(spec: dict, measured, novel_target: dict | None = None,
          novel_measured=None, measured_sha: str = "", novel_sha: str = "") -> dict:
    """Return {verdict, delta, improved, novel}. Mirrors lakatos.verdict.judge exactly, incl. the
    same-metric independence gate (judge.py:134): a same-metric novel with no distinct measurement
    source is demoted (not independent excess content)."""
    _validate_spec(spec)
    if not _finite_number(measured):
        raise JudgeError("measured must be finite (NaN-is-rejected silence forbidden)")
    baseline = spec["baseline_value"]
    noise_band = spec.get("noise_band", 0.0)
    delta = measured - baseline
    if spec["direction"] == "lower":
        improved = delta < -noise_band
    else:
        improved = delta > noise_band
    within_noise = abs(delta) <= noise_band

    if novel_target is not None:
        if not isinstance(novel_target, dict):
            raise JudgeError("novel_target is not an object")
        nt_dir = novel_target.get("direction")
        nt_threshold = novel_target.get("threshold")
        if nt_dir not in ("lower", "higher"):
            raise JudgeError("novel_target.direction must be 'lower' | 'higher'")
        if not _finite_number(nt_threshold):
            raise JudgeError("novel_target.threshold must be finite")
        if novel_measured is None:
            raise JudgeError("novel_target present but novel_measured missing (independent excess content)")
        if not _finite_number(novel_measured):
            raise JudgeError("novel_measured must be finite")
        novel = _corroborated(nt_dir, nt_threshold, novel_measured)
        noindep = (novel and novel_target.get("metric_name") == spec.get("metric_name")
                   and not (measured_sha and novel_sha and novel_sha != measured_sha))
        if noindep:
            novel = False
    else:
        novel = False

    if improved and novel:
        verdict = "progressive"
    elif improved:
        verdict = "partial"
    elif within_noise:
        verdict = "equivalent"
    else:
        verdict = "rejected"
    return {"verdict": verdict, "delta": delta, "improved": improved, "novel": novel}
