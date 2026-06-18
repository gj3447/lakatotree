"""Novelty-sense policy OOPTDD receipts.

The object under test is a policy boundary: temporal/Worrall novelty are
audit tags, not separate scoring oracles.
"""

from lakatos.verdict.judge import (
    NOVELTY_SENSE_SCORING_POLICY,
    NovelTarget,
    Prediction,
    judge,
)


def _verdict_for(sense: str):
    return judge(
        Prediction(
            metric_name="loo_p95",
            direction="lower",
            baseline_value=0.384,
            noise_band=0.01,
            novel_prediction="structural target only",
        ),
        measured=0.279,
        novel_target=NovelTarget("psr", "higher", 0.5, novelty_sense=sense),
        novel_measured=0.7,
    )


def test_novelty_sense_policy_is_tag_only_not_score_oracle():
    assert NOVELTY_SENSE_SCORING_POLICY == "tag_only"


def test_temporal_and_worrall_tags_do_not_change_verdict_outcome():
    baseline = _verdict_for("zahar_use_novelty")

    for sense in ("temporal_novelty", "worrall_use_novelty"):
        candidate = _verdict_for(sense)
        assert (
            candidate.verdict,
            candidate.delta,
            candidate.improved,
            candidate.novel,
        ) == (
            baseline.verdict,
            baseline.delta,
            baseline.improved,
            baseline.novel,
        )
        assert f"novelty_sense={sense}" in candidate.reason
