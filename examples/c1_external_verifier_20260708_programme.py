"""C1 — External Certificate Verifier: LakatoTree research programme (slice S0).

Dogfood discipline (like every examples/*_programme.py): nodes do NOT hand-type a verdict. Each
node's measured/novel_measured are DERIVED from a real, independent measurement — here the executed
c1verify skeleton via its ooptdd emit-adapter — and `judge()` turns them into the verdict. No fake
green: the same numbers are the ooptdd receipt's shipped events (LTDD trace) and this judge's inputs.

S0 lands two pre-registered predictions (registered in the KG BEFORE this ran):
  P0  (s0-skeleton-failclosed): garbage_bundle_reject_rate == 1.0        — fail-closed by construction
  P0b (s0-engine-independence): engine_symbols_in_sys_modules_after_verify == 0 — zero engine import

Hard core: SEAL don't POINT; FAIL-CLOSED TOTALITY; ZERO ENGINE IMPORT (proven three ways). certified
is True only when every gate ACCEPTs — impossible in the skeleton, which is the honest behaviour.

# KG: LakatosTree_C1ExternalVerifier_20260708
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_RECEIPTS = _REPO / "ooptdd_receipts"
for _p in (_REPO.as_posix(),
           (_RECEIPTS / "c1_skeleton_failclosed").as_posix(),
           (_RECEIPTS / "c1_grounded_shapin").as_posix()):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lakatos.verdict.judge import NovelTarget, Prediction, judge  # noqa: E402

import c1_skeleton_receipt as receipt  # noqa: E402 — the real S0 measurement (drive, don't reimplement)
import c1_grounded_receipt as grounded  # noqa: E402 — the real S1 grounded measurement


# Two GENUINELY DISTINCT axes per node (independence, not the same number twice): an improvement
# metric (primary) + an independent structural novel target. Same-metric novel would be demoted by
# the engine's independence gate (judge.py:134) — and rightly so.
def _p0_skeleton_failclosed():
    """P0 — fail-closed by construction.
    primary (structure): reachable_accept_on_garbage 0 < 1  (no gate reaches ACCEPT on the corpus).
    novel  (behaviour):  garbage_bundle_reject_rate  >= 1.0 (every bundle REJECTs every gate)."""
    reachable_accept = float(receipt.reachable_accept_on_garbage())   # 0
    reject_rate = receipt.garbage_bundle_reject_rate()                # 1.0
    pred = Prediction(metric_name="reachable_accept_on_garbage", direction="lower",
                      baseline_value=1.0, noise_band=0.0, novel_prediction=True,
                      closes_question="q_failclosed_by_construction")
    novel = NovelTarget(metric_name="garbage_bundle_reject_rate", direction="higher", threshold=1.0)
    verdict = judge(pred, reachable_accept, novel_target=novel, novel_measured=reject_rate)
    return dict(tag="s0-skeleton-failclosed", measured=reachable_accept, novel_measured=reject_rate,
                verdict=verdict)


def _p0b_engine_independence():
    """P0b — zero engine import.
    primary (static):  engine_import_statements_in_source 0 < 1 (no engine import in source).
    novel  (runtime):  engine_symbols_in_sys_modules_after_verify <= 0 (none loaded by verify())."""
    static_imports = float(receipt.engine_import_statements_in_source())   # 0
    runtime_symbols = float(receipt.engine_symbols_after_verify())         # 0
    pred = Prediction(metric_name="engine_import_statements_in_source", direction="lower",
                      baseline_value=1.0, noise_band=0.0, novel_prediction=True,
                      closes_question="q_verifier_secretly_trusts_engine")
    novel = NovelTarget(metric_name="engine_symbols_in_sys_modules_after_verify",
                        direction="lower", threshold=0.0)
    verdict = judge(pred, static_imports, novel_target=novel, novel_measured=runtime_symbols)
    return dict(tag="s0-engine-independence", measured=static_imports, novel_measured=runtime_symbols,
                verdict=verdict)


def _p1_grounded_sha_pin():
    """P1 — grounded gate is re-derived from the sealed registry, not a pointer.
    primary (swap tamper):  snapshot_substitution_reject_rate >= 1.0 (registry swap caught by sha-pin).
    novel  (tier tamper):   bogus_tier_reject_rate           >= 1.0 (off-allowlist tier caught).
    Two genuinely distinct tamper classes — one defeats content-substitution, the other tier-forgery."""
    snapshot_reject = grounded.snapshot_substitution_reject_rate()   # 1.0
    bogus_tier_reject = grounded.bogus_tier_reject_rate()            # 1.0
    pred = Prediction(metric_name="snapshot_substitution_reject_rate", direction="higher",
                      baseline_value=0.0, noise_band=0.0, novel_prediction=True,
                      closes_question="q_grounded_f2_snapshot")
    novel = NovelTarget(metric_name="bogus_tier_reject_rate", direction="higher", threshold=1.0)
    verdict = judge(pred, snapshot_reject, novel_target=novel, novel_measured=bogus_tier_reject)
    return dict(tag="s1-grounded-sha-pin", measured=snapshot_reject, novel_measured=bogus_tier_reject,
                verdict=verdict)


def results() -> list:
    return [_p0_skeleton_failclosed(), _p0b_engine_independence(), _p1_grounded_sha_pin()]


def main() -> int:
    ok = True
    for r in results():
        v = r["verdict"]
        status = getattr(v, "verdict", v)
        novel = getattr(v, "novel_confirmed", getattr(v, "novel", None))
        print(f"[{r['tag']}] measured={r['measured']} novel_measured={r['novel_measured']} "
              f"-> verdict={status} novel_confirmed={novel}")
        ok = ok and str(status) == "progressive"
    print("ALL PROGRESSIVE" if ok else "NOT ALL PROGRESSIVE")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
