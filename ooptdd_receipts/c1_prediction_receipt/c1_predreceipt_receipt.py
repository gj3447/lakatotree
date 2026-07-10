"""OOPTDD emit-adapter — C1 S3-engine (PredictionReceipt keystone) as a receipt.

Discipline (ooptdd): event literals live ONLY here. `verify(backend,cid)` drives the REAL engine
registration/submit paths (JudgementService over a stateful KG double — the double models storage,
never re-implements engine logic) and the REAL c1verify preregistered gate v2, and proves:

  MINT       — register_prediction seals the FULL prediction spec as a content-addressed receipt
               (genesis) and advances the node pointer; the sha is REDERIVABLE from stored fields.
  HASH-CAUSAL— submit's verdict receipt seals the prediction sha via prev linkage (spec ≺ verdict in
               chain order): editing the spec after the verdict is unrepresentable (chain breaks).
  GOLDEN     — c1verify's re-implemented prediction_content_sha agrees with the engine byte-for-byte.
  BACK-FIT   — every forgery class dies at the gate (shown-spec swap / moved novel bar / sealed-field
               tamper / kind-strip smuggle / double-registration ambiguity) while the honest sealed
               bundle ACCEPTs with the narrowed hash-causal residual.
  NEGATIVE   — dropping the sealed-vs-shown comparison (v1 semantics) or the kind-aware sha recompute
               makes the above vacuous => the new checks are load-bearing (no fake green).

# KG: LakatosTree_C1ExternalVerifier_20260708 / s3-engine-prediction-receipt
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if _REPO.as_posix() not in sys.path:
    sys.path.insert(0, _REPO.as_posix())

import c1verify  # noqa: E402
import c1verify.receipts as CR  # noqa: E402 — re-implemented kernel (under test)
from c1verify.jcs import jcs  # noqa: E402

import lakatos.verdicts as LV  # noqa: E402 — engine kernel (golden reference)
from lakatos.verdicts import ReceiptChainBroken, fold_receipt_chain  # noqa: E402
from server.contexts.tree.judgement_service import JudgementService  # noqa: E402
from server.contexts.tree.schemas import PredictionIn  # noqa: E402
from server.contexts.tree.schemas import TestResultIn as Result  # noqa: E402


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "c1verify.S3.prediction_receipt", "event": name, **attrs}


# ── stateful KG double (storage model only — register/submit run REAL service code) ────────────
class _Kg:
    def __init__(self):
        self.node = {"tag": "seam", "verdict": None, "verdict_source": None, "node_state": None,
                     "pred_registered_at": None, "current_receipt_sha": None}
        self.receipts: list[dict] = []

    def __call__(self, query, **p):
        if "t.ontology AS ontology" in query:
            return [{"ontology": None}]
        if "parent_measured" in query:
            return []
        if "AS prev_rsha" in query:
            return [{"prev_rsha": self.node["current_receipt_sha"]}]
        if "SET e.pred_metric" in query:
            n = self.node
            ok = (n.get("verdict_source") != "scripted" and n.get("pred_registered_at") is None
                  and (n.get("node_state") or "DRAFT") in p["allowed_from"]
                  and (n.get("current_receipt_sha") or "") == (p.get("prev_rsha") or ""))
            if not ok:
                return []
            n.update(pred_metric=p["metric_name"], pred_direction=p["direction"],
                     pred_baseline=p["baseline_value"], pred_noise_band=p["noise_band"],
                     pred_scale_type=p["scale_type"], pred_novel=p["novel_prediction"],
                     pred_closes=p["closes_question"], pred_novel_metric=p["novel_metric"],
                     pred_novel_direction=p["novel_direction"],
                     pred_novel_threshold=p["novel_threshold"],
                     pred_script_sha=p["judge_script_sha"], pred_credence=p["credence"],
                     pred_registered_at=p["ts"], node_state=p["node_state"],
                     baseline_lineage=p["baseline_lineage"])
            if "MERGE (rec:VerdictReceipt" in query and p.get("rsha"):
                rec = {"receipt_sha": p["rsha"], "receipt_kind": "prediction",
                       "tree": p["tree"], "tag": p["tag"], "metric_name": p["metric_name"],
                       "direction": p["direction"], "baseline_value": p["baseline_value"],
                       "noise_band": p["noise_band"], "scale_type": p["scale_type"],
                       "novel_prediction": p["novel_prediction"], "novel_metric": p["novel_metric"],
                       "novel_direction": p["novel_direction"],
                       "novel_threshold": p["novel_threshold"],
                       "judge_script_sha": p["judge_script_sha"],
                       "closes_question": p["closes_question"], "credence": p["credence"],
                       "baseline_lineage": p["baseline_lineage"], "registered_at": p["ts"],
                       "prev_receipt_sha": p.get("prev_rsha"),
                       "verdict": None, "verdict_source": None}
                self.receipts.append(rec)
                n["current_receipt_sha"] = p["rsha"]
            return [{"tag": n["tag"]}]
        if "n_visits" in query:
            return []
        if "pred_metric AS m" in query:
            n = self.node
            return [{"m": n.get("pred_metric"), "d": n.get("pred_direction"),
                     "b": n.get("pred_baseline"), "nb": n.get("pred_noise_band"),
                     "scale": n.get("pred_scale_type"), "novel": n.get("pred_novel"),
                     "vsrc": n.get("verdict_source"), "nmet": n.get("pred_novel_metric"),
                     "ndir": n.get("pred_novel_direction"), "nthr": n.get("pred_novel_threshold"),
                     "psha": n.get("pred_script_sha"),
                     "pred_registered_at": n.get("pred_registered_at"),
                     "node_state": n.get("node_state"), "judged_at": None,
                     "existing_metric_value": None, "existing_verdict": n.get("verdict"),
                     "existing_lstat": None, "prev_receipt_sha": n.get("current_receipt_sha"),
                     "closes": n.get("pred_closes"), "n_opened": 0, "hard_core": "",
                     "require_novel_anchor": False, "assurance_tier": None, "attestor_dids": None}]
        if "current_receipt_sha AS head" in query:
            return [{"head": self.node["current_receipt_sha"],
                     "cache_verdict": self.node["verdict"],
                     "cache_source": self.node["verdict_source"]}]
        if "HAS_RECEIPT" in query:
            return [dict(r) for r in self.receipts]
        return []

    def tx(self, ops):
        q0, params = ops[0]
        if "MERGE (rec:VerdictReceipt" in q0:
            self.node["verdict"] = params["v"]
            self.node["verdict_source"] = "scripted"
            self.node["current_receipt_sha"] = params["rsha"]
            self.receipts.append({"receipt_sha": params["rsha"],
                                  "prev_receipt_sha": params["prev_rsha"],
                                  "tree": params["tree"], "tag": params["tag"],
                                  "target_id": params["target_id"], "verdict": params["v"],
                                  "verdict_source": "scripted", "metric_name": params["mn"],
                                  "metric_value": params["mv"], "novel_confirmed": params["novel"],
                                  "lakatos_status": params["lstat"], "judged_at": params["ts"],
                                  "judge_script_sha": params["sha"],
                                  "measurement_grade": params["mg"]})
        return [[{"claimed": params.get("tag")}] for _ in ops]


def _registered_and_judged():
    """Run the REAL register->submit cycle; return (kg, pred_receipt, verdict_receipt)."""
    kg = _Kg()
    svc = JudgementService(kg=kg, kg_tx=kg.tx, hist=lambda *a, **k: None,
                           foundation=lambda n: None, reproducible_for_node=lambda n, t: None)
    svc.register_prediction("T", "seam", PredictionIn(
        metric_name="seam", direction="lower", baseline_value=10.0, noise_band=0.0,
        scale_type="ratio", novel_prediction="novel claim", novel_metric="novelaxis",
        novel_direction="higher", novel_threshold=1.0, closes_question="q-x", credence=0.7))
    pred = next(r for r in kg.receipts if r.get("receipt_kind") == "prediction")
    out = svc.submit_test_result("T", "seam",
                                 Result(metric_value=1.0, script="inline", novel_measured=1.0))
    assert out["verdict"] == "progressive", out
    verdict = next(r for r in kg.receipts if r.get("verdict_source") == "scripted")
    return kg, pred, verdict


def _shown_spec(pred):
    return {"metric_name": pred["metric_name"], "direction": pred["direction"],
            "baseline_value": pred["baseline_value"], "noise_band": pred["noise_band"],
            "scale_type": pred["scale_type"]}


def _shown_novel(pred):
    return {"metric_name": pred["novel_metric"], "direction": pred["novel_direction"],
            "threshold": pred["novel_threshold"]}


def _gate(chain, head, spec, novel, measured=1.0, novel_measured=1.0):
    payload = {"spec": spec, "novel_target": novel, "measured": measured,
               "novel_measured": novel_measured, "chain": chain, "head": head}
    bundle = jcs({"c1_bundle_version": 1, "gates": {"preregistered": payload}})
    return next(g for g in c1verify.verify(bundle)["per_gate"] if g["gate"] == "preregistered")


def backfit_reject_rate() -> float:
    """Honest sealed bundle ACCEPTs (narrowed residual); every back-fit forgery class REJECTs."""
    kg, pred, verdict = _registered_and_judged()
    chain, head = kg.receipts, verdict["receipt_sha"]
    honest = _gate(chain, head, _shown_spec(pred), _shown_novel(pred))
    assert honest["decision"] == c1verify.ACCEPT, honest
    assert "hash-causal" in honest["residual_trust_surface"], honest

    swapped_spec = {**_shown_spec(pred), "baseline_value": -100.0}
    moved_novel = {**_shown_novel(pred), "threshold": 0.0}
    tampered_pred = [{**r, "baseline_value": -100.0} if r is pred else r for r in chain]
    stripped_pred = [{k: v for k, v in r.items() if k != "receipt_kind"} if r is pred else r
                     for r in chain]
    second = dict(pred, registered_at="2026-07-10T09:00:00+00:00",
                  prev_receipt_sha=pred["receipt_sha"])
    second["receipt_sha"] = CR.prediction_content_sha(second)
    double_v = dict(verdict)
    double_v.pop("receipt_sha")
    double_v["prev_receipt_sha"] = second["receipt_sha"]
    double_v["receipt_sha"] = CR.receipt_content_sha(double_v)
    forgeries = [
        _gate(chain, head, swapped_spec, _shown_novel(pred)),          # shown-spec swap
        _gate(chain, head, _shown_spec(pred), moved_novel),            # moved novel bar
        _gate(tampered_pred, head, _shown_spec(pred), _shown_novel(pred)),   # sealed-field tamper
        _gate(stripped_pred, head, _shown_spec(pred), _shown_novel(pred)),   # kind-strip smuggle
        _gate([pred, second, double_v], double_v["receipt_sha"],
              _shown_spec(pred), _shown_novel(pred)),                  # double-registration ambiguity
    ]
    return sum(d["decision"] == c1verify.REJECT for d in forgeries) / len(forgeries)


def negative_oracle_load_bearing() -> bool:
    """(a) The back-fit shown spec judge-recomputes CLEAN (fold verdict == judge(shown)) — so without
    the sealed-vs-shown comparison (v1 semantics) it would ACCEPT; only the comparison kills it.
    (b) Recomputing the honest prediction receipt with the VERDICT canonicalization mismatches — so
    without the kind-aware branch, honest sealed chains would never verify (the branch is load-bearing,
    and it is tamper-safe because receipt_kind is inside the sha)."""
    kg, pred, verdict = _registered_and_judged()
    chain, head = kg.receipts, verdict["receipt_sha"]

    # (a) craft a shown spec that yields the SAME verdict as sealed (progressive) but differs from
    #     the sealed spec: judge-recompute alone cannot tell them apart.
    backfit = {**_shown_spec(pred), "baseline_value": 9.0}   # still improved at measured=1.0
    from c1verify.judge import judge as cj
    assert cj(backfit, 1.0, _shown_novel(pred), 1.0)["verdict"] == verdict["verdict"], \
        "back-fit spec no longer judge-consistent — negative oracle vacuous"
    d = _gate(chain, head, backfit, _shown_novel(pred))
    assert d["decision"] == c1verify.REJECT and "sealed" in d["reason"], \
        f"sealed-vs-shown comparison did not catch the judge-consistent back-fit: {d}"

    # (b) kind-aware recompute is load-bearing for the honest ACCEPT.
    assert CR.prediction_content_sha(pred) == pred["receipt_sha"]
    assert CR.receipt_content_sha(pred) != pred["receipt_sha"], \
        "verdict-canonicalization matched a prediction receipt — domain separation broken"
    return True


def verify(backend, cid):
    """Drive the real engine paths + gate v2 and ship the S3-engine oracles. Failures raise (RED)."""
    # ① MINT — real register_prediction seals the spec; sha rederivable from stored fields.
    kg, pred, verdict = _registered_and_judged()
    assert pred["prev_receipt_sha"] is None, "prediction receipt is not genesis"
    assert LV.prediction_content_sha(pred) == pred["receipt_sha"], "mint not rederivable"
    backend.ship([_ev(cid, "c1_predreceipt_minted", rederivable=True, genesis=True)])

    # ② HASH-CAUSAL — verdict receipt seals the prediction sha as prev; chain folds; spec-swap breaks.
    assert verdict["prev_receipt_sha"] == pred["receipt_sha"], "verdict does not commit to the seal"
    fold = fold_receipt_chain(kg.receipts, kg.node["current_receipt_sha"])
    assert fold["from_receipt"] and fold["verdict"] == "progressive"
    swapped = dict(pred, baseline_value=-100.0)
    swapped["receipt_sha"] = LV.prediction_content_sha(swapped)   # self-consistent re-mint
    broke = False
    try:
        fold_receipt_chain([swapped if r is pred else r for r in kg.receipts],
                           kg.node["current_receipt_sha"])
    except ReceiptChainBroken:
        broke = True
    assert broke, "spec swap did not break the chain — back-fit alive"
    backend.ship([_ev(cid, "c1_predreceipt_hashcausal", prev_sealed=True, swap_breaks_chain=True)])

    # ③ GOLDEN — engine <-> c1verify prediction sha byte-parity over a coercion corpus.
    base = {k: None for k in LV.PREDICTION_RECEIPT_FIELDS}
    corpus = [
        dict(pred),
        dict(base, receipt_kind="prediction", tree="T", tag="n", baseline_value=3),
        dict(base, receipt_kind="prediction", tree="T", tag="n", baseline_value=3.0),
        dict(base, receipt_kind="prediction", tree="유니코드", novel_metric="재현율_δ",
             credence=0.7, prev_receipt_sha="a" * 64, registered_at=1720483200),
    ]
    agree = sum(1 for f in corpus
                if LV.prediction_content_sha(f) == CR.prediction_content_sha(f))
    assert agree == len(corpus), f"golden byte-parity {agree}/{len(corpus)} (kernel fidelity drift)"
    backend.ship([_ev(cid, "c1_predreceipt_golden", agreement=1.0, corpus=len(corpus))])

    # ④ BACK-FIT — honest sealed bundle ACCEPTs narrowed; all forgery classes die.
    brr = backfit_reject_rate()
    assert brr == 1.0, f"backfit_reject_rate={brr} != 1.0 (a back-fit slipped)"
    backend.ship([_ev(cid, "c1_predreceipt_backfit_killed", backfit_reject_rate=brr, classes=5)])

    # ⑤ NEGATIVE ORACLE — comparison + kind-aware recompute are load-bearing.
    assert negative_oracle_load_bearing()
    backend.ship([_ev(cid, "c1_predreceipt_negative_oracle", checks_load_bearing=True)])
