"""c1verify preregistered gate — clean venv (no engine). Verdict re-derived from the sealed spec."""
from __future__ import annotations

import c1verify
from c1verify.jcs import jcs
from c1verify.judge import judge
from c1verify.receipts import prediction_content_sha, receipt_content_sha

# distinct primary/novel metrics (same-metric novel would be demoted by the independence gate)
SPEC = {"metric_name": "reject_rate", "direction": "higher", "baseline_value": 0.0,
        "noise_band": 0.0, "scale_type": "ratio"}
NOVEL = {"metric_name": "other_axis", "direction": "higher", "threshold": 1.0}


def _receipt(verdict, source="scripted"):
    fields = {"tree": "T", "tag": "n", "target_id": "n", "verdict": verdict, "verdict_source": source,
              "metric_name": "reject_rate", "metric_value": 1.0, "novel_confirmed": True,
              "lakatos_status": "canonical", "judged_at": "2026-07-09T00:00:00+00:00",
              "judge_script_sha": "deadbeef", "prev_receipt_sha": None,
              "measurement_grade": "server_regenerated"}
    fields["receipt_sha"] = receipt_content_sha(fields)
    return fields


def _bundle(spec, measured, novel, novel_measured, sealed_verdict, source="scripted"):
    r = _receipt(sealed_verdict, source)
    payload = {"spec": spec, "novel_target": novel, "measured": measured,
               "novel_measured": novel_measured, "chain": [r], "head": r["receipt_sha"]}
    return jcs({"c1_bundle_version": 1, "gates": {"preregistered": payload}})


def _dec(bundle):
    return next(g for g in c1verify.verify(bundle)["per_gate"] if g["gate"] == "preregistered")


def test_verdict_consistent_with_spec_accepts_with_residual():
    v = judge(SPEC, 1.0, NOVEL, 1.0)["verdict"]        # progressive
    assert v == "progressive"
    d = _dec(_bundle(SPEC, 1.0, NOVEL, 1.0, v))
    assert d["decision"] == c1verify.ACCEPT
    assert d["residual_trust_surface"] and "back-fit" in d["residual_trust_surface"]


def test_hand_typed_verdict_source_rejects():
    v = judge(SPEC, 1.0, NOVEL, 1.0)["verdict"]
    d = _dec(_bundle(SPEC, 1.0, NOVEL, 1.0, v, source="engine"))
    assert d["decision"] == c1verify.REJECT and "scripted" in d["reason"]


def test_verdict_inconsistent_with_spec_rejects():
    # spec+measured actually judge to 'rejected'; sealing 'progressive' is a forged verdict
    assert judge(SPEC, -5.0, NOVEL, 0.0)["verdict"] == "rejected"
    d = _dec(_bundle(SPEC, -5.0, NOVEL, 0.0, "progressive"))
    assert d["decision"] == c1verify.REJECT and "judge-recomputed" in d["reason"]


def test_invalid_spec_rejects():
    bad = {**SPEC, "direction": "sideways"}
    d = _dec(_bundle(bad, 1.0, NOVEL, 1.0, "progressive"))
    assert d["decision"] == c1verify.REJECT


def test_tampered_receipt_rejects_before_judge():
    v = judge(SPEC, 1.0, NOVEL, 1.0)["verdict"]
    r = _receipt(v)
    tampered = {**r, "metric_value": 999.0}          # break the content-sha
    payload = {"spec": SPEC, "novel_target": NOVEL, "measured": 1.0, "novel_measured": 1.0,
               "chain": [tampered], "head": r["receipt_sha"]}
    d = _dec(jcs({"c1_bundle_version": 1, "gates": {"preregistered": payload}}))
    assert d["decision"] == c1verify.REJECT and "content-sha mismatch" in d["reason"]


# ── S3-engine keystone: PredictionReceipt in the chain — spec sealed AT REGISTRATION ─────────────
# The engine now mints a prediction receipt (full spec, own type header) at register_prediction and
# the verdict receipt seals its sha via prev linkage. With one in the ancestry, this gate must
# (a) REJECT a shown spec that differs from the sealed one (back-fit dies), (b) narrow the residual
# to hash-causal ordering (wholesale chain fabrication / wall-clock remain out-of-band).

def _pred_receipt(spec=SPEC, novel=NOVEL, **over):
    fields = {"receipt_kind": "prediction", "tree": "T", "tag": "n",
              "metric_name": spec["metric_name"], "direction": spec["direction"],
              "baseline_value": spec["baseline_value"], "noise_band": spec["noise_band"],
              "scale_type": spec["scale_type"], "novel_prediction": "novel claim",
              "novel_metric": novel["metric_name"] if novel else None,
              "novel_direction": novel["direction"] if novel else None,
              "novel_threshold": novel["threshold"] if novel else None,
              "judge_script_sha": "deadbeef", "closes_question": "q-x", "credence": 0.7,
              "baseline_lineage": "no_prior", "registered_at": "2026-07-10T00:00:00+00:00",
              "prev_receipt_sha": None}
    fields.update(over)
    fields["receipt_sha"] = prediction_content_sha(fields)
    return fields


def _sealed_bundle(shown_spec, measured, shown_novel, novel_measured, sealed_verdict,
                   pred=None, extra_preds=()):
    pred = pred or _pred_receipt()
    vfields = {"tree": "T", "tag": "n", "target_id": "n", "verdict": sealed_verdict,
               "verdict_source": "scripted", "metric_name": "reject_rate", "metric_value": 1.0,
               "novel_confirmed": True, "lakatos_status": "canonical",
               "judged_at": "2026-07-10T01:00:00+00:00", "judge_script_sha": "deadbeef",
               "prev_receipt_sha": pred["receipt_sha"], "measurement_grade": "server_regenerated"}
    vfields["receipt_sha"] = receipt_content_sha(vfields)
    chain = [pred, *extra_preds, vfields]
    payload = {"spec": shown_spec, "novel_target": shown_novel, "measured": measured,
               "novel_measured": novel_measured, "chain": chain, "head": vfields["receipt_sha"]}
    return jcs({"c1_bundle_version": 1, "gates": {"preregistered": payload}})


def test_sealed_spec_matching_shown_spec_accepts_with_narrowed_residual():
    v = judge(SPEC, 1.0, NOVEL, 1.0)["verdict"]      # progressive
    d = _dec(_sealed_bundle(SPEC, 1.0, NOVEL, 1.0, v))
    assert d["decision"] == c1verify.ACCEPT, d
    assert "sealed at registration" in d["reason"]
    # residual narrows: no longer "needs a PredictionReceipt" — now hash-causal vs wall-clock/authenticity
    assert "hash-causal" in d["residual_trust_surface"]


def test_backfit_shown_spec_differs_from_sealed_rejects():
    # attacker re-shows a friendlier baseline than the one sealed at registration
    shown = {**SPEC, "baseline_value": -100.0}
    v = judge(shown, 1.0, NOVEL, 1.0)["verdict"]
    d = _dec(_sealed_bundle(shown, 1.0, NOVEL, 1.0, v))
    assert d["decision"] == c1verify.REJECT and "sealed" in d["reason"]


def test_backfit_shown_novel_target_differs_from_sealed_rejects():
    shown_novel = {**NOVEL, "threshold": 0.0}        # loosened novel bar after seeing the result
    v = judge(SPEC, 1.0, shown_novel, 1.0)["verdict"]
    d = _dec(_sealed_bundle(SPEC, 1.0, shown_novel, 1.0, v))
    assert d["decision"] == c1verify.REJECT and "sealed" in d["reason"]


def test_two_prediction_receipts_in_ancestry_rejects_ambiguous():
    pred1 = _pred_receipt()
    pred2 = _pred_receipt(registered_at="2026-07-10T00:30:00+00:00",
                          prev_receipt_sha=pred1["receipt_sha"])
    vfields = {"tree": "T", "tag": "n", "target_id": "n", "verdict": "progressive",
               "verdict_source": "scripted", "metric_name": "reject_rate", "metric_value": 1.0,
               "novel_confirmed": True, "lakatos_status": "canonical",
               "judged_at": "2026-07-10T01:00:00+00:00", "judge_script_sha": "deadbeef",
               "prev_receipt_sha": pred2["receipt_sha"], "measurement_grade": "server_regenerated"}
    vfields["receipt_sha"] = receipt_content_sha(vfields)
    payload = {"spec": SPEC, "novel_target": NOVEL, "measured": 1.0, "novel_measured": 1.0,
               "chain": [pred1, pred2, vfields], "head": vfields["receipt_sha"]}
    d = _dec(jcs({"c1_bundle_version": 1, "gates": {"preregistered": payload}}))
    assert d["decision"] == c1verify.REJECT and "ambiguous" in d["reason"]


def test_tampered_prediction_receipt_rejects_by_kind_aware_recompute():
    pred = _pred_receipt()
    pred_tampered = {**pred, "baseline_value": -100.0}   # sealed field edited, sha kept
    d = _dec(_sealed_bundle(SPEC, 1.0, NOVEL, 1.0, "progressive", pred=pred_tampered))
    assert d["decision"] == c1verify.REJECT and "content-sha mismatch" in d["reason"]


def test_kind_stripped_prediction_receipt_rejects():
    # stripping the sealed discriminator makes the integrity check recompute it as a verdict
    # receipt -> sha mismatch (kind-smuggling dies because receipt_kind is inside the sha)
    pred = _pred_receipt()
    stripped = {k: v for k, v in pred.items() if k != "receipt_kind"}
    d = _dec(_sealed_bundle(SPEC, 1.0, NOVEL, 1.0, "progressive", pred=stripped))
    assert d["decision"] == c1verify.REJECT and "content-sha mismatch" in d["reason"]


def test_junk_sealed_spec_rejects_total_not_crash():
    # sha-consistent junk (attacker controls both bytes and sha): must REJECT, never raise
    junk = _pred_receipt(baseline_value="not-a-number", direction="sideways")
    d = _dec(_sealed_bundle(SPEC, 1.0, NOVEL, 1.0, "progressive", pred=junk))
    assert d["decision"] == c1verify.REJECT


def test_chain_without_prediction_receipt_keeps_v1_backfit_residual():
    # regression: pred-less chains (pre-keystone nodes) keep the honest v1 ACCEPT whose residual
    # still names back-fit as UNdischarged
    v = judge(SPEC, 1.0, NOVEL, 1.0)["verdict"]
    d = _dec(_bundle(SPEC, 1.0, NOVEL, 1.0, v))
    assert d["decision"] == c1verify.ACCEPT
    assert "back-fit" in d["residual_trust_surface"] and "hash-causal" not in d["residual_trust_surface"]
