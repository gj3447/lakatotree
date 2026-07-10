"""OOPTDD emit-adapter — C1 S3 (receipt kernel + judge re-implementation) as a receipt.

Discipline (ooptdd): event literals live ONLY here. `verify(backend,cid)` drives the REAL c1verify
substrate + preregistered gates over receipt chains MINTED with the REAL engine primitives
(lakatos.verdicts.receipt_content_sha, lakatos.verdict.judge), and proves two things at once:

  GOLDEN cross-check (copy-fidelity) — c1verify's re-implemented receipt_content_sha and judge() agree
    byte-for-byte / verdict-for-verdict with the engine over a corpus. This is the load-bearing proof
    that the engine-forbidden verifier re-derives the SAME crypto/scoring, not a look-alike.
  FORGERY rejection — a single-field-tampered receipt (substrate) and a hand-typed / spec-inconsistent
    verdict (preregistered) are REJECTed; the honest chain ACCEPTs. Negative oracle: dropping the
    content-sha recompute / the judge-recompute lets the forgery slip => the checks are load-bearing.

# KG: LakatosTree_C1ExternalVerifier_20260708 / s3-substrate-integrity + s3-preregistered-recompute
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if _REPO.as_posix() not in sys.path:
    sys.path.insert(0, _REPO.as_posix())

import c1verify  # noqa: E402
import c1verify.judge as CJ  # noqa: E402 — re-implemented scoring kernel (under test)
import c1verify.receipts as CR  # noqa: E402 — re-implemented receipt kernel (under test)
from c1verify.jcs import jcs  # noqa: E402

import lakatos.verdicts as LV  # noqa: E402 — engine receipt kernel (golden reference)
from lakatos.verdict.judge import NovelTarget, Prediction  # noqa: E402
from lakatos.verdict.judge import judge as engine_judge  # noqa: E402


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "c1verify.S3.kernel", "event": name, **attrs}


_BASE = {"tree": "T", "tag": "n", "target_id": "n", "verdict": "progressive",
         "verdict_source": "scripted", "metric_name": "reject_rate", "metric_value": 1.0,
         "novel_confirmed": True, "lakatos_status": "canonical",
         "judged_at": "2026-07-09T00:00:00+00:00", "judge_script_sha": "deadbeef",
         "prev_receipt_sha": None, "measurement_grade": "server_regenerated"}


def _fields_corpus() -> list:
    """Varied receipt field dicts exercising the coercions (int vs float metric_value, None/str
    judged_at, unicode, None fields, prev link)."""
    return [
        _BASE,
        {**_BASE, "metric_value": 3},                       # int -> float coercion
        {**_BASE, "metric_value": 3.0},                     # equals the int case after coercion
        {**_BASE, "metric_value": None},
        {**_BASE, "metric_value": float("nan")},            # non-finite -> None
        {**_BASE, "judged_at": None},
        {**_BASE, "judged_at": 1720483200},                 # non-str -> str coercion
        {**_BASE, "verdict": "rejected", "novel_confirmed": False},
        {**_BASE, "metric_name": "재현율_δ", "prev_receipt_sha": "a" * 64},
        {**_BASE, "measurement_grade": "client_asserted"},
    ]


def golden_content_sha_agreement_rate() -> float:
    """c1verify.receipt_content_sha == lakatos.verdicts.receipt_content_sha over the corpus."""
    corpus = _fields_corpus()
    agree = sum(1 for f in corpus if CR.receipt_content_sha(f) == LV.receipt_content_sha(f))
    return agree / len(corpus)


def _judge_corpus() -> list:
    """(spec_dict, measured, novel_dict|None, novel_measured|None) — exercises improved/within_noise,
    novel corroboration both directions, the same-metric independence gate, noise_band, scale_type."""
    p = {"metric_name": "m", "direction": "higher", "baseline_value": 0.0, "noise_band": 0.0,
         "scale_type": "ratio"}
    pl = {"metric_name": "m", "direction": "lower", "baseline_value": 1.0, "noise_band": 0.1,
          "scale_type": "ratio"}
    nv = {"metric_name": "novel", "direction": "higher", "threshold": 1.0}
    nvl = {"metric_name": "novel", "direction": "lower", "threshold": 0.0}
    same = {"metric_name": "m", "direction": "higher", "threshold": 1.0}   # same-metric (independence)
    return [
        (p, 1.0, nv, 1.0),        # improved + novel -> progressive
        (p, 1.0, nv, 0.5),        # improved, novel not corroborated -> partial
        (p, 0.0, nv, 1.0),        # not improved (delta 0), within_noise -> equivalent
        (p, -1.0, nv, 1.0),       # worse -> rejected
        (pl, 0.5, nvl, 0.0),      # lower-direction improved + novel -> progressive
        (pl, 1.05, nvl, 0.0),     # within noise_band 0.1 -> equivalent
        (p, 1.0, same, 1.0),      # same-metric novel -> demoted (independence) -> partial
        (p, 1.0, None, None),     # no novel target -> partial at best
    ]


def golden_judge_agreement_rate() -> float:
    """c1verify.judge verdict == lakatos.verdict.judge verdict over the corpus (copy-fidelity)."""
    corpus = _judge_corpus()
    agree = 0
    for spec, measured, novel, novel_measured in corpus:
        mine = CJ.judge(spec, measured, novel, novel_measured)["verdict"]
        pred = Prediction(metric_name=spec["metric_name"], direction=spec["direction"],
                          baseline_value=spec["baseline_value"], noise_band=spec["noise_band"],
                          scale_type=spec["scale_type"])
        nt = (NovelTarget(metric_name=novel["metric_name"], direction=novel["direction"],
                          threshold=novel["threshold"]) if novel else None)
        theirs = engine_judge(pred, measured, nt, novel_measured).verdict
        agree += (mine == theirs)
    return agree / len(corpus)


# ── mint real receipts with the ENGINE primitive, then drive the c1verify gates ────────────────
def _mint(prev=None, **over) -> dict:
    fields = {**_BASE, "prev_receipt_sha": prev, **over}
    fields["receipt_sha"] = LV.receipt_content_sha(fields)   # real engine mint
    return fields


def _substrate_dec(chain, head) -> dict:
    bundle = jcs({"c1_bundle_version": 1, "gates": {"substrate": {"chain": chain, "head": head}}})
    return next(g for g in c1verify.verify(bundle)["per_gate"] if g["gate"] == "substrate")


def receipt_tamper_reject_rate() -> float:
    """Honest chain ACCEPTs; each single-field tamper (old sha kept) REJECTs."""
    genesis = _mint()
    head = _mint(prev=genesis["receipt_sha"])
    assert _substrate_dec([genesis, head], head["receipt_sha"])["decision"] == c1verify.ACCEPT
    rejects = []
    for field, val in (("verdict", "rejected"), ("metric_value", 0.123),
                       ("verdict_source", "engine"), ("judge_script_sha", "0" * 8),
                       ("measurement_grade", "client_asserted")):
        tampered = {**head, field: val}   # keeps head['receipt_sha'] -> content-sha now mismatches
        rejects.append(_substrate_dec([genesis, tampered], head["receipt_sha"])["decision"]
                       == c1verify.REJECT)
    return sum(rejects) / len(rejects)


def _prereg_dec(spec, measured, novel, novel_measured, sealed_verdict, source="scripted") -> dict:
    r = _mint(verdict=sealed_verdict, verdict_source=source)
    payload = {"spec": spec, "novel_target": novel, "measured": measured,
               "novel_measured": novel_measured, "chain": [r], "head": r["receipt_sha"]}
    bundle = jcs({"c1_bundle_version": 1, "gates": {"preregistered": payload}})
    return next(g for g in c1verify.verify(bundle)["per_gate"] if g["gate"] == "preregistered")


def forged_verdict_reject_rate() -> float:
    """Honest scripted verdict (== engine judge) ACCEPTs; hand-typed source and spec-inconsistent
    verdict REJECT."""
    spec = {"metric_name": "m", "direction": "higher", "baseline_value": 0.0, "noise_band": 0.0,
            "scale_type": "ratio"}
    novel = {"metric_name": "novel", "direction": "higher", "threshold": 1.0}
    honest_v = engine_judge(Prediction(metric_name="m", direction="higher", baseline_value=0.0,
                                       noise_band=0.0, scale_type="ratio"), 1.0,
                            NovelTarget(metric_name="novel", direction="higher", threshold=1.0),
                            1.0).verdict
    assert _prereg_dec(spec, 1.0, novel, 1.0, honest_v)["decision"] == c1verify.ACCEPT
    other = "rejected" if honest_v != "rejected" else "progressive"
    forgeries = [
        _prereg_dec(spec, 1.0, novel, 1.0, honest_v, source="engine"),   # hand-typed source
        _prereg_dec(spec, 1.0, novel, 1.0, other),                       # verdict inconsistent w/ spec
        _prereg_dec(spec, -5.0, novel, 0.0, "progressive"),              # spec+measured -> rejected
    ]
    return sum(d["decision"] == c1verify.REJECT for d in forgeries) / len(forgeries)


def negative_oracle_checks_are_load_bearing() -> bool:
    """Dropping the content-sha recompute (substrate) or the judge-recompute (preregistered) lets the
    forgery slip => the real checks are what catch it (revert-proof intuition, in-process)."""
    genesis = _mint()
    head = _mint(prev=genesis["receipt_sha"])
    tampered = {**head, "verdict": "rejected"}     # old sha, changed verdict

    # real substrate REJECTs the tamper; a fold-only variant (no sha recompute) would ACCEPT it.
    assert _substrate_dec([genesis, tampered], head["receipt_sha"])["decision"] == c1verify.REJECT
    fold_only = CR.fold_receipt_chain([genesis, tampered], head["receipt_sha"])  # no integrity check
    substrate_slip = fold_only["from_receipt"] is True   # the broken receipt still folds -> would pass
    assert substrate_slip, "fold-only did not accept the tamper — substrate negative oracle vacuous"

    # real preregistered REJECTs an inconsistent verdict; without the judge-recompute it would pass
    spec = {"metric_name": "m", "direction": "higher", "baseline_value": 0.0, "noise_band": 0.0,
            "scale_type": "ratio"}
    d = _prereg_dec(spec, -5.0, None, None, "progressive")   # judge -> rejected, sealed progressive
    assert d["decision"] == c1verify.REJECT and "judge-recomputed" in d["reason"], \
        "preregistered did not reject an inconsistent verdict"
    return True


def verify(backend, cid):
    """Drive the real kernels + gates and ship the S3 oracles. Failures raise (RED)."""
    # ① GOLDEN — receipt content-sha re-implementation matches the engine byte-for-byte.
    g1 = golden_content_sha_agreement_rate()
    assert g1 == 1.0, f"golden_content_sha_agreement_rate={g1} != 1.0 (kernel fidelity drift)"
    backend.ship([_ev(cid, "c1_kernel_golden_content_sha", agreement=g1, corpus=len(_fields_corpus()))])

    # ② GOLDEN — judge() re-implementation matches the engine verdict-for-verdict.
    g2 = golden_judge_agreement_rate()
    assert g2 == 1.0, f"golden_judge_agreement_rate={g2} != 1.0 (scoring fidelity drift)"
    backend.ship([_ev(cid, "c1_kernel_golden_judge", agreement=g2, corpus=len(_judge_corpus()))])

    # ③ substrate — honest chain ACCEPTs; every single-field tamper REJECTs.
    ttr = receipt_tamper_reject_rate()
    assert ttr == 1.0, f"receipt_tamper_reject_rate={ttr} != 1.0 (a tampered receipt slipped)"
    backend.ship([_ev(cid, "c1_kernel_substrate", tamper_reject_rate=ttr)])

    # ④ preregistered — honest scripted verdict ACCEPTs; hand-typed / inconsistent verdict REJECTs.
    fvr = forged_verdict_reject_rate()
    assert fvr == 1.0, f"forged_verdict_reject_rate={fvr} != 1.0 (a forged verdict slipped)"
    backend.ship([_ev(cid, "c1_kernel_preregistered", forged_reject_rate=fvr)])

    # ⑤ negative oracle — the integrity + judge-recompute checks are load-bearing.
    assert negative_oracle_checks_are_load_bearing()
    backend.ship([_ev(cid, "c1_kernel_negative_oracle", checks_load_bearing=True)])
