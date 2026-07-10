"""preregistered gate reverifier (C1 S3, sub-claim A + S3-engine sub-claim B) — re-derive the verdict
from the sealed spec, and (when the chain carries a PredictionReceipt) re-derive the SPEC itself from
the registration-time seal.

The engine's cert proves this gate with a POINTER ('<judge_script>:<sha12>') and a presence check on
node properties. C1 re-derives instead: the bundle carries the frozen prediction spec + measurement +
the content-addressed receipt chain, and this gate:
  1. re-checks receipt integrity + folds the chain (shared with substrate; kind-aware recompute);
  2. REJECTs unless the folded verdict_source == 'scripted' (a hand-typed/engine verdict dies here);
  3. S3-engine: if the head's ancestry carries a PredictionReceipt (spec sealed at registration,
     genesis-chained; the verdict receipt commits to its sha via the sealed prev linkage), REJECT
     unless the SHOWN spec/novel_target equal the SEALED ones — a spec back-fit to the result died
     at registration time, by hash-causal order (changing the spec changes the prediction sha,
     which dangles the verdict's sealed prev);
  4. re-runs judge() over the spec and REJECTs unless it reproduces the sealed verdict.

Residual (enumerated, never silently discharged):
  - chains WITHOUT a prediction receipt (pre-keystone nodes): spec-fixed-before-result stays
    out-of-band — the v1 residual, verbatim;
  - chains WITH one: the spec≺verdict ordering proven here is HASH-CAUSAL, not wall-clock —
    fabricating an entire fresh chain (prediction + verdict) after seeing results remains possible
    without authenticity (substrate-B Ed25519 write-cert) + witnessed temporal ordering; and the
    judge-script identity across registration→submit is carried in both receipts, not compared here.
"""
from __future__ import annotations

from .._decision import ACCEPT, REJECT, gate_decision
from ..judge import JudgeError, judge
from ..receipts import check_chain_integrity, is_prediction_receipt

GATE = "preregistered"

_RESIDUAL = ("spec-fixed-BEFORE-result is out-of-band: this proves the sealed verdict is what judge() "
             "produces from the SHOWN spec (a hand-typed / spec-inconsistent verdict is rejected), NOT "
             "that the spec was fixed before the result rather than back-fit to it. Closing that needs "
             "a content-sealed PredictionReceipt at registration + witnessed temporal ordering.")

_RESIDUAL_SEALED = (
    "spec-fixed-before-result is discharged in hash-causal order only: the verdict receipt seals the "
    "prediction receipt's sha via prev linkage, so editing the spec after the verdict is "
    "unrepresentable — but WALL-CLOCK ordering and chain authenticity are not proven here. "
    "Fabricating an entire fresh chain (prediction + verdict) after seeing results needs "
    "substrate-B (Ed25519 write-cert) + witnessed temporal ordering to die. judge_script_sha is "
    "carried in both receipts but registration==submit identity is not compared here.")


def _f(v):
    """Float-normalise a sealed/shown numeric for equality (mirrors the blob coercion); junk -> None."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f


def _shown_spec_norm(spec) -> dict | None:
    if not isinstance(spec, dict):
        return None
    return {"metric_name": spec.get("metric_name"), "direction": spec.get("direction"),
            "baseline_value": _f(spec.get("baseline_value")),
            "noise_band": _f(spec.get("noise_band", 0.0)),
            "scale_type": spec.get("scale_type", "ratio")}


def _sealed_spec_norm(pred: dict) -> dict:
    return {"metric_name": pred.get("metric_name"), "direction": pred.get("direction"),
            "baseline_value": _f(pred.get("baseline_value")),
            "noise_band": _f(pred.get("noise_band")) if pred.get("noise_band") is not None else 0.0,
            "scale_type": pred.get("scale_type") or "ratio"}


def _shown_novel_norm(novel) -> dict | None:
    if not isinstance(novel, dict):
        return None
    return {"metric_name": novel.get("metric_name"), "direction": novel.get("direction"),
            "threshold": _f(novel.get("threshold"))}


def _sealed_novel_norm(pred: dict) -> dict | None:
    if pred.get("novel_metric") is None:
        return None
    return {"metric_name": pred.get("novel_metric"), "direction": pred.get("novel_direction"),
            "threshold": _f(pred.get("novel_threshold"))}


def _ancestry_predictions(chain: list, head) -> list:
    """Prediction receipts on the head->genesis walk (integrity already checked; walk terminates)."""
    by_sha = {r.get("receipt_sha"): r for r in chain}
    preds, cur = [], head
    while cur is not None:
        r = by_sha[cur]
        if is_prediction_receipt(r):
            preds.append(r)
        cur = r.get("prev_receipt_sha")
    return preds


def verify_preregistered(payload, ctx) -> dict:
    """payload = {spec, novel_target|None, measured, novel_measured|None, chain, head[, measured_sha,
    novel_sha]}. Total, fail-closed."""
    if not isinstance(payload, dict):
        return gate_decision(GATE, REJECT, "preregistered payload absent or not an object")
    fold, reason = check_chain_integrity(payload.get("chain"), payload.get("head"))
    if reason:
        return gate_decision(GATE, REJECT, reason)
    if fold["verdict_source"] != "scripted":
        return gate_decision(GATE, REJECT,
                             f"verdict_source is {fold['verdict_source']!r}, not 'scripted' — "
                             f"hand-typed / engine verdict, not a scripted judgement")
    # S3-engine sub-claim B: spec sealed at registration (PredictionReceipt in the head's ancestry).
    preds = _ancestry_predictions(payload["chain"], payload["head"])
    sealed = None
    if len(preds) > 1:
        return gate_decision(GATE, REJECT,
                             f"{len(preds)} prediction receipts in the head's ancestry — ambiguous "
                             f"spec seal (the engine registers exactly once; forged chain)")
    if preds:
        sealed = preds[0]
        if _shown_spec_norm(payload.get("spec")) != _sealed_spec_norm(sealed):
            return gate_decision(GATE, REJECT,
                                 "shown spec != spec sealed at registration (PredictionReceipt) — "
                                 "back-fit: the spec was changed after the seal")
        if _shown_novel_norm(payload.get("novel_target")) != _sealed_novel_norm(sealed):
            return gate_decision(GATE, REJECT,
                                 "shown novel_target != novel target sealed at registration "
                                 "(PredictionReceipt) — back-fit: the novel bar was moved")
    try:
        recomputed = judge(payload.get("spec"), payload.get("measured"),
                           novel_target=payload.get("novel_target"),
                           novel_measured=payload.get("novel_measured"),
                           measured_sha=payload.get("measured_sha", ""),
                           novel_sha=payload.get("novel_sha", ""))
    except JudgeError as exc:
        return gate_decision(GATE, REJECT, f"spec invalid or judge failed (fail-closed): {exc}")
    if recomputed["verdict"] != fold["verdict"]:
        return gate_decision(GATE, REJECT,
                             f"sealed verdict {fold['verdict']!r} != judge-recomputed "
                             f"{recomputed['verdict']!r} from the shown spec — hand-typed or forged")
    if sealed is not None:
        return gate_decision(GATE, ACCEPT,
                             f"sealed verdict {fold['verdict']!r} re-derived by judge() from the spec "
                             f"sealed at registration (PredictionReceipt, hash-causally committed by "
                             f"the verdict receipt's prev linkage); chain content-addressed + folded",
                             residual_trust_surface=_RESIDUAL_SEALED)
    return gate_decision(GATE, ACCEPT,
                         f"sealed verdict {fold['verdict']!r} re-derived by judge() from the shown "
                         f"spec; receipt chain content-addressed + folded",
                         residual_trust_surface=_RESIDUAL)
