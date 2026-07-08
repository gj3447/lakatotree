"""c1verify preregistered gate — clean venv (no engine). Verdict re-derived from the sealed spec."""
from __future__ import annotations

import c1verify
from c1verify.jcs import jcs
from c1verify.judge import judge
from c1verify.receipts import receipt_content_sha

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
