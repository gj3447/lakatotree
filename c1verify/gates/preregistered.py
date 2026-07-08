"""preregistered gate reverifier (C1 S3, sub-claim A) — re-derive the verdict from the sealed spec.

The engine's cert proves this gate with a POINTER ('<judge_script>:<sha12>') and a presence check on
node properties. C1 re-derives instead: the bundle carries the frozen prediction spec + measurement +
the content-addressed receipt chain, and this gate:
  1. re-checks receipt integrity + folds the chain (shared with substrate);
  2. REJECTs unless the folded verdict_source == 'scripted' (a hand-typed/engine verdict dies here);
  3. re-runs judge() over the SHOWN spec and REJECTs unless it reproduces the sealed verdict
     (a verdict inconsistent with its spec — hand-typed or forged — dies here).

Enumerated residual (never discharged): that the shown spec was FIXED BEFORE the result (not back-fit
to make judge() emit the desired verdict). Catching that needs a content-sealed PredictionReceipt at
registration + witnessed temporal ordering (the S3-engine keystone + the transparency log) — so this
ACCEPT means 'the verdict is judge()-consistent with the shown spec', never 'the prediction predates
the result'.
"""
from __future__ import annotations

from .._decision import ACCEPT, REJECT, gate_decision
from ..judge import JudgeError, judge
from ..receipts import check_chain_integrity

GATE = "preregistered"

_RESIDUAL = ("spec-fixed-BEFORE-result is out-of-band: this proves the sealed verdict is what judge() "
             "produces from the SHOWN spec (a hand-typed / spec-inconsistent verdict is rejected), NOT "
             "that the spec was fixed before the result rather than back-fit to it. Closing that needs "
             "a content-sealed PredictionReceipt at registration + witnessed temporal ordering.")


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
    return gate_decision(GATE, ACCEPT,
                         f"sealed verdict {fold['verdict']!r} re-derived by judge() from the shown "
                         f"spec; receipt chain content-addressed + folded",
                         residual_trust_surface=_RESIDUAL)
