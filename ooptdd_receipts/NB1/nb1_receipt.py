"""NB1 emit-adapter — noise_band 부재와 선언-0을 실제 Bayes/metrics 코드로 구분한다."""
from __future__ import annotations

import math
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lakatos.quant.bayes import BF_BASE, bayes_factor, branch_credence  # noqa: E402
from lakatos.quant.metrics import _verdict_seq  # noqa: E402
from lakatos.programme.consilience import project_tree_rows  # noqa: E402


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.NB1", "event": name, **attrs}


def verify(backend, cid):
    """실 엔진을 구동해 fail-safe·호환 메커니즘·결함 주입 오라클을 함께 봉인한다."""
    absent_small = bayes_factor("progressive", 0.001, noise_band=None)
    absent_huge = bayes_factor("progressive", 999.0, noise_band=None)
    declared_zero = bayes_factor("progressive", 999.0, noise_band=0.0)
    assert absent_small == absent_huge
    assert 1.0 < absent_small < declared_zero == BF_BASE["progressive"]
    absent_rejected = bayes_factor("rejected", 0.001, noise_band=None)
    absent_rejected_huge = bayes_factor("rejected", 999.0, noise_band=None)
    declared_zero_rejected = bayes_factor("rejected", 999.0, noise_band=0.0)
    assert absent_rejected == absent_rejected_huge
    assert math.isclose(BF_BASE["rejected"], declared_zero_rejected)
    assert declared_zero_rejected < absent_rejected < 1.0
    assert bayes_factor("progressive", 0.5) == bayes_factor(
        "progressive", 0.5, noise_band=0.0)
    backend.ship([_ev(cid, "absent_noise_is_weak", absent_bf=absent_small,
                      declared_zero_bf=declared_zero,
                      absent_rejected_bf=absent_rejected)])

    marginal = bayes_factor("progressive", 0.001, noise_band=1.0)
    large = bayes_factor("progressive", 4.0, noise_band=1.0)
    assert 1.0 < marginal < large == BF_BASE["progressive"]
    assert declared_zero == BF_BASE["progressive"]
    backend.ship([_ev(cid, "declared_noise_mechanism_preserved",
                      marginal_bf=marginal, large_bf=large)])

    declared = branch_credence([
        {"verdict": "progressive", "delta": 2.0, "noise_band": 5.0, "target": "A"}])
    omitted = branch_credence([
        {"verdict": "progressive", "delta": 2.0, "target": "A"}])
    assert omitted <= declared
    backend.ship([_ev(cid, "branch_omission_fails_safe",
                      omitted_credence=omitted, declared_credence=declared)])

    by = {"n": {"tag": "n", "verdict": "progressive", "metric_value": 2.0,
                  "pred_baseline": 0.0, "pred_noise_band": None}}
    seq = _verdict_seq(["n"], by)
    assert seq[0]["noise_band"] is None
    projected = project_tree_rows([{
        "tag": "n", "parents": [], "verdict": "progressive", "pred_closes": "q1",
        "metric_value": 2.0, "pred_baseline": 0.0, "pred_noise_band": None,
    }])[2]
    assert projected[0]["noise_band"] is None
    safe = branch_credence(seq)
    collapsed = branch_credence([{**seq[0], "noise_band": 0.0}])
    assert collapsed > safe, "부재를 선언-0으로 강등해도 오라클이 감지하지 못함"
    backend.ship([_ev(cid, "feeder_collapse_negative_oracle",
                      safe_credence=safe, collapsed_credence=collapsed)])
