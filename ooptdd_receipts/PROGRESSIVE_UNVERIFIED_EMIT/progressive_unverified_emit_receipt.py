"""OOPTDD adapter for the progressive-unverified judgement contract.

The adapter drives the real spine, PnR, Bayes, and Eureka code. Its assertions are
negative oracles: the receipt cannot go green if the old full-progress emission,
the PnR rescue, or the orthogonal Eureka mapping regresses.
"""
import sys

_LKT = __import__("pathlib").Path(__file__).resolve().parents[2].as_posix()
if _LKT not in sys.path:
    sys.path.insert(0, _LKT)

from lakatos.eureka import classify, eureka_verdict  # noqa: E402
from lakatos.quant.bayes import bayes_factor  # noqa: E402
from lakatos.quant.metrics import _multiplicity_screen  # noqa: E402
from lakatos.verdict.pnr import Response, appraise_response  # noqa: E402
from lakatos.verdict.spine import dialectical_verdict, reconcile_verdict  # noqa: E402
from server.contexts.audit.fsck import fsck_node  # noqa: E402

PU = "progressive_unverified"


def _event(cid, name, **attrs):
    return {
        "cid": cid,
        "correlation_id": cid,
        "cycle_id": cid,
        "service": "lakatos.spine.progressive_unverified",
        "event": name,
        **attrs,
    }


def verify(backend, cid):
    base = reconcile_verdict("progressive", None)
    zero = dialectical_verdict("progressive")
    assert base["verdict"] == PU
    assert base["status"] == "qualitative_unverified"
    assert zero["verdict"] == PU
    backend.ship([_event(cid, "unverified_emitted", verdict=zero["verdict"],
                         status=base["status"], reasons=list(base["reasons"]))])

    progressive = appraise_response(
        Response.LEMMA_INCORPORATION,
        excess_content=True,
        novel_corroborated=True,
        in_heuristic_spirit=True,
    )
    conditional = appraise_response(
        Response.LEMMA_INCORPORATION,
        excess_content=True,
        novel_corroborated=False,
        in_heuristic_spirit=True,
    )
    lifted_progressive = dialectical_verdict(
        "progressive", pnr_appraisal=progressive)["verdict"]
    lifted_conditional = dialectical_verdict(
        "progressive", pnr_appraisal=conditional)["verdict"]
    assert lifted_progressive == "progressive"
    assert lifted_conditional == "progressive_conditional"
    backend.ship([_event(cid, "pnr_rescue_lifts", pnr_progressive=lifted_progressive,
                         pnr_conditional=lifted_conditional)])

    abandon_bf = bayes_factor(PU, delta=5.0, noise_band=0.1)
    discovery_bf = bayes_factor(eureka_verdict(PU), delta=5.0, noise_band=0.1)
    assert abandon_bf == 1.0
    assert discovery_bf > 3.162
    assert eureka_verdict("progressive") == "progressive"
    direct = classify({
        "novel_registered": True, "novel_confirmed": True, "verdict": PU,
        "delta": 5.0, "noise_band": 0.1, "source_trust": 1.0,
        "closed": 1, "opened": 0,
    }, require_promotion=False)
    assert direct.true and direct.bf > 3.162
    backend.ship([_event(cid, "eureka_orthogonal", abandon_bf=abandon_bf,
                         discovery_bf=discovery_bf, public_classify_true=direct.true)])

    corrupt = {"verdict": PU, "verdict_source": "scripted", "replay_status": "mismatch"}
    finding_ids = {finding.check_id for finding in fsck_node(corrupt)}
    assert "VERDICT_WITHOUT_PREREG" in finding_ids
    assert "VERDICT_WRITE_WITHOUT_TIER_RESOLVE" in finding_ids
    assert "MEASUREMENT_REFUTED_BUT_STANDING" in finding_ids
    candidates = [
        {"tag": "a", "verdict": PU, "metric_name": "p95", "metric_scope": "api",
         "metric_value": 0.39, "pred_baseline": 0.5, "pred_noise_band": 0.1,
         "pred_direction": "lower"},
        {"tag": "b", "verdict": PU, "metric_name": "p95", "metric_scope": "api",
         "metric_value": 0.1, "pred_baseline": 0.5, "pred_noise_band": 0.1,
         "pred_direction": "lower"},
    ]
    family_size = _multiplicity_screen(candidates)["p95/api"]["family_size"]
    assert family_size == 2
    backend.ship([_event(cid, "downstream_guards_hold", fsck=sorted(finding_ids),
                         multiplicity_family_size=family_size)])
