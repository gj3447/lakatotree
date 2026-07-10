#!/usr/bin/env python3
"""C1 S3-engine PredictionReceipt 채점 스크립트 (LakatosTree_C1ExternalVerifier_20260708 / s3-engine-prediction-receipt).

측정 2축 (사전등록 예측 대비):
  primary  backfit_reject_classes      — 실 c1verify preregistered 게이트가 죽이는 back-fit 위조 클래스 수.
             pre-keystone(체인에 PredictionReceipt 없음/게이트 v1): 전 클래스가 judge-recompute 를 통과해
             ACCEPT(slip) => baseline 0. keystone 후: 5 클래스 전부 REJECT.
  novel    prediction_seal_rederivable — 등록-시점 봉인이 mint 의식이 아니라 재유도 가능한 내용주소인가:
             (엔진 sha 재유도 == 저장 sha) ∧ (c1verify 미러 byte-parity) ∧ (verdict prev == pred sha)
             ∧ (spec-swap 시 체인 붕괴) 전부 참일 때 1.0.

실코드 구동(재구현 금지): JudgementService.register_prediction/submit_test_result + c1verify.verify.
출력: JSON (stdout + 인자로 준 result_path).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if _REPO.as_posix() not in sys.path:
    sys.path.insert(0, _REPO.as_posix())

import c1verify  # noqa: E402
import c1verify.receipts as CR  # noqa: E402

import lakatos.verdicts as LV  # noqa: E402
from lakatos.verdicts import ReceiptChainBroken, fold_receipt_chain  # noqa: E402

sys.path.insert(0, (_REPO / "ooptdd_receipts" / "c1_prediction_receipt").as_posix())
from c1_predreceipt_receipt import (  # noqa: E402 — 영수증 어댑터의 실-구동 하네스 재사용(단일정본)
    _gate,
    _registered_and_judged,
    _shown_novel,
    _shown_spec,
)


def measure() -> dict:
    kg, pred, verdict = _registered_and_judged()   # 실 register→submit 사이클
    chain, head = kg.receipts, verdict["receipt_sha"]
    shown_spec, shown_novel = _shown_spec(pred), _shown_novel(pred)

    # ── primary: back-fit 위조 5클래스 중 게이트가 REJECT 하는 수 ───────────────────────────
    #   클래스 1·2 는 *judge-일관*(재채점만으론 sealed verdict 와 같은 답 = v1 semantics 로는 식별
    #   불가) — REJECT 는 오직 등록-시점 봉인 대조에서만 나온다. 3·4·5 는 봉인 자체를 겨냥한 공격
    #   (변조·kind-밀수·이중등록) — pre-keystone 엔 봉인이 없어 방어 자체가 부재였던 표면.
    swapped_spec = {**shown_spec, "baseline_value": 9.0}   # lower·measured 1.0 → 여전히 progressive
    moved_novel = {**shown_novel, "threshold": 0.0}        # novel 여전히 corroborated → 동일 verdict
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
        _gate(chain, head, swapped_spec, shown_novel),
        _gate(chain, head, shown_spec, moved_novel),
        _gate(tampered_pred, head, shown_spec, shown_novel),
        _gate(stripped_pred, head, shown_spec, shown_novel),
        _gate([pred, second, double_v], double_v["receipt_sha"], shown_spec, shown_novel),
    ]
    backfit_reject_classes = sum(d["decision"] == c1verify.REJECT for d in forgeries)

    # 정직 대조(baseline 0 의 실증): pre-keystone 형상(verdict 가 genesis, 봉인 없음)에선 같은
    # judge-일관 back-fit(클래스 1·2)이 ACCEPT 로 slip — v1 semantics 의 실측 재현.
    v0 = {k: verdict[k] for k in verdict if k != "receipt_sha"}
    v0["prev_receipt_sha"] = None
    v0["receipt_sha"] = CR.receipt_content_sha(v0)
    baseline_slip = (_gate([v0], v0["receipt_sha"], swapped_spec, shown_novel)["decision"]
                     == c1verify.ACCEPT
                     and _gate([v0], v0["receipt_sha"], shown_spec, moved_novel)["decision"]
                     == c1verify.ACCEPT)

    # ── novel: 봉인 재유도 가능성(내용주소 실재) ──────────────────────────────────────────
    honest = _gate(chain, head, shown_spec, shown_novel)
    swap_breaks = False
    swapped = dict(pred, baseline_value=-100.0)
    swapped["receipt_sha"] = LV.prediction_content_sha(swapped)
    try:
        fold_receipt_chain([swapped if r is pred else r for r in chain],
                           kg.node["current_receipt_sha"])
    except ReceiptChainBroken:
        swap_breaks = True
    rederivable = (LV.prediction_content_sha(pred) == pred["receipt_sha"]
                   and CR.prediction_content_sha(pred) == pred["receipt_sha"]
                   and verdict["prev_receipt_sha"] == pred["receipt_sha"]
                   and honest["decision"] == c1verify.ACCEPT
                   and "hash-causal" in honest["residual_trust_surface"]
                   and swap_breaks)

    return {
        "metric_name": "backfit_reject_classes",
        "metric_value": float(backfit_reject_classes),
        "baseline_slip_reproduced": baseline_slip,
        "novel_metric": "prediction_seal_rederivable",
        "novel_measured": 1.0 if rederivable else 0.0,
        "forgery_classes": ["shown_spec_swap", "moved_novel_bar", "sealed_field_tamper",
                            "kind_strip_smuggle", "double_registration_ambiguity"],
        "engine_commit": "1b04bfb",
    }


if __name__ == "__main__":
    out = measure()
    blob = json.dumps(out, ensure_ascii=False, indent=2)
    print(blob)
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(blob + "\n", encoding="utf-8")
