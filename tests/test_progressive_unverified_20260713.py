"""Recovered finding-A contract: metric progress without qualitative scrutiny is not full progress.

The original 2026-07-12 audit settled three orthogonal policies: series-neutral,
promotion-excluded, and Eureka-discovery-preserving.  This file restores that
interrupted contract without resolving the separate fertility-policy dispute.
"""
from lakatos.verdict.pnr import Response, appraise_response
from lakatos.verdict.spine import dialectical_verdict, reconcile_verdict
from lakatos.verdicts import (
    CONFIRMED_NOVEL_PROGRESS,
    ENGINE_VERDICTS,
    NONPROGRESSIVE_VERDICTS,
    PROGRESS_VERDICTS,
    SCRIPTED_VERDICTS,
    VERDICT_REGISTRY,
    is_engine_verdict,
    is_progress_verdict,
    is_self_report_blocked_verdict,
)
from lakatos.quant.bayes import BF_BASE, bayes_factor
from lakatos.eureka import eureka_verdict
from lakatos.verdict.promote import PROMOTABLE, promotion_gate

PU = "progressive_unverified"


def test_metric_progressive_without_lakatos_emits_unverified():
    result = reconcile_verdict("progressive", None)
    assert result["verdict"] == PU
    assert result["lakatos"] == "unverified"
    assert result["status"] == "qualitative_unverified"
    assert "lakatos_evidence_missing" in result["reasons"]


def test_metric_nonprogressive_is_never_unverified():
    assert reconcile_verdict("partial", None)["verdict"] == "partial"
    assert reconcile_verdict("rejected", None)["verdict"] == "rejected"


def test_zero_scrutiny_dialectic_emits_unverified():
    assert dialectical_verdict("progressive")["verdict"] == PU


def test_pnr_progressive_lifts_unverified_to_full_progressive():
    appraisal = appraise_response(
        Response.LEMMA_INCORPORATION,
        excess_content=True,
        novel_corroborated=True,
        in_heuristic_spirit=True,
    )
    assert appraisal.verdict == "progressive"
    assert dialectical_verdict(
        "progressive", pnr_appraisal=appraisal
    )["verdict"] == "progressive"


def test_pnr_conditional_lifts_unverified_to_conditional():
    appraisal = appraise_response(
        Response.LEMMA_INCORPORATION,
        excess_content=True,
        novel_corroborated=False,
        in_heuristic_spirit=True,
    )
    assert appraisal.verdict == "conditional"
    assert dialectical_verdict(
        "progressive", pnr_appraisal=appraisal
    )["verdict"] == "progressive_conditional"


def test_pnr_degenerating_overrides_unverified():
    appraisal = appraise_response(
        Response.LEMMA_INCORPORATION, excess_content=False
    )
    assert appraisal.verdict == "degenerating"
    assert dialectical_verdict(
        "progressive", pnr_appraisal=appraisal
    )["verdict"] == "degenerating"


def test_registered_and_engine_and_self_report_blocked():
    assert PU in VERDICT_REGISTRY
    assert PU in ENGINE_VERDICTS and is_engine_verdict(PU)
    assert is_self_report_blocked_verdict(PU)


def test_out_of_every_progress_and_scripted_set():
    assert PU not in SCRIPTED_VERDICTS
    assert PU not in PROGRESS_VERDICTS and not is_progress_verdict(PU)
    assert PU not in NONPROGRESSIVE_VERDICTS
    assert PU not in CONFIRMED_NOVEL_PROGRESS
    assert PROGRESS_VERDICTS.isdisjoint(NONPROGRESSIVE_VERDICTS)


def test_bayes_factor_is_neutral_for_unverified():
    assert BF_BASE[PU] == 1.0
    assert bayes_factor(PU, delta=5.0, noise_band=0.1) == 1.0


def test_eureka_verdict_maps_unverified_to_progressive():
    assert eureka_verdict(PU) == "progressive"
    assert bayes_factor(eureka_verdict(PU), delta=5.0, noise_band=0.1) > 3.162
    assert eureka_verdict("progressive") == "progressive"
    assert eureka_verdict("degenerating") == "degenerating"


def test_eureka_write_mapping_and_tree_recompute_are_symmetric():
    from lakatos.eureka import classify, eureka_over_tree

    mapped = classify({
        "novel_registered": True,
        "novel_confirmed": True,
        "verdict": eureka_verdict(PU),
        "delta": -0.4,
        "noise_band": 0.02,
        "source_trust": 1.0,
        "closed": 1,
        "opened": 0,
    }, require_promotion=False)
    recomputed = eureka_over_tree([{
        "tag": "n",
        "novel_registered": True,
        "novel_confirmed": True,
        "verdict": PU,
        "metric_value": 0.1,
        "pred_baseline": 0.5,
        "pred_noise_band": 0.02,
        "source_trust": 1.0,
        "pred_closes": "q1",
        "questions": [],
    }])
    assert mapped.true is True
    assert recomputed["true"] == 1 and recomputed["hallucinated"] == 0


def test_unverified_is_not_promotable():
    assert PU not in PROMOTABLE
    ok, reasons = promotion_gate(scripted_verdict=PU, stands=True)
    assert not ok and any("verdict_not_promotable" in reason for reason in reasons)


def test_series_treats_unverified_as_neutral_not_progress_not_degeneration():
    from lakatos.programme.series import (
        KNOWN_VERDICTS,
        NEUTRAL_VERDICTS,
        ProgrammeSeriesRecord,
        programme_series_appraisal,
    )

    assert PU in KNOWN_VERDICTS and PU in NEUTRAL_VERDICTS
    rows = [
        ProgrammeSeriesRecord(tag="n1", verdict=PU),
        ProgrammeSeriesRecord(tag="n2", verdict=PU),
    ]
    appraisal = programme_series_appraisal(rows)
    assert appraisal.progressive_count == 0
    assert appraisal.nonprogressive_count == 0
    assert appraisal.trend not in {"progressive", "degenerating"}


def test_hard_core_violation_still_overrides_unverified():
    from server.contexts.tree.judgement_policy import apply_verdict_demotes

    violated = apply_verdict_demotes(
        PU,
        "unverified",
        hc_derived=False,
        require_novel_anchor=False,
        novel=False,
        cross_metric_novel=False,
        novel_server_anchored=False,
    )
    assert violated.verdict == "different_programme"

    preserved = apply_verdict_demotes(
        PU,
        "unverified",
        hc_derived=True,
        require_novel_anchor=False,
        novel=False,
        cross_metric_novel=False,
        novel_server_anchored=False,
    )
    assert preserved.verdict == PU


def test_unverified_is_a_consecutive_nonprogressive_streak_boundary():
    from lakatos.quant.metrics import branch_inputs

    result = branch_inputs([
        {"tag": "old", "verdict": "rejected"},
        {"tag": "pending", "parent": "old", "verdict": PU},
        {"tag": "leaf", "parent": "pending", "verdict": "partial"},
    ], [], leaf="leaf")
    # boundary=1; transparent skip=2; treating PU as nonprogressive=3.
    assert result["consecutive_nonprogressive"] == 1


def test_unverified_does_not_reset_lifecycle_regret():
    from lakatos.programme.lifecycle import regret_nodes

    assert regret_nodes([{"verdict": "progressive"}, {"verdict": PU}]) == 1


def test_fertility_remains_verdict_blind_and_confirmation_driven():
    from lakatos.quant.fertility import predictive_fertility

    assert predictive_fertility([
        {"verdict": PU, "novel_registered": True, "novel_confirmed": True},
    ], scope="unit") == {
        "registered": 1,
        "confirmed": 1,
        "fertility": 1.0,
        "scope": "unit",
    }


def test_unverified_node_is_judged_but_not_a_canonical_candidate():
    from lakatos.node_state import NodeState, derive_node_state

    state = derive_node_state({
        "verdict": PU,
        "verdict_source": "scripted",
        "novel_confirmed": True,
    })
    assert state is NodeState.JUDGED_SCRIPTED


def test_fsck_keeps_scripted_structure_guards_for_unverified_verdict():
    from server.contexts.audit.fsck import fsck_node

    corrupt = {
        "verdict": PU,
        "verdict_source": "scripted",
    }
    finding_ids = {finding.check_id for finding in fsck_node(corrupt)}
    assert "VERDICT_WITHOUT_PREREG" in finding_ids
    assert "VERDICT_WRITE_WITHOUT_TIER_RESOLVE" in finding_ids

    wrong_source = {
        "verdict": PU,
        "verdict_source": "conjecture",
        "pred_registered_at": "2026-07-14T00:00:00Z",
        "assurance_tier_resolved": "anchored",
    }
    wrong_ids = {finding.check_id for finding in fsck_node(wrong_source)}
    assert "SCRIPTED_WITHOUT_SOURCE" in wrong_ids
