#!/usr/bin/env python3
"""q-extaudit-temporal-witness-20260722 라이브 프로브 러너 — k-of-N 외부 시간증인 실배선 실측.

질문: "외부 시간 증인(k-of-N witness quorum)을 어떻게 배선해서 run-first-register-second 를
물리적으로 차단하나?" — S7b(양끝 앵커)+D1(k-of-N 정족수) 착지 후 라이브 서버에 대해:

  happy          : 2-of-2 정족수 앵커 등록→판정 — pred_anchor_verified ∧ quorum=2 ∧ temporal_witness_verified
  sybil          : 같은 증인 2회 서명 — distinct 1 < threshold 2 → 422 기대
  outsider       : allow-list 밖 증인 — 422 기대 (solo box 무증인 fail-closed)
  digest_mismatch: 다른 spec 을 커버한 앵커 밀반입 — 422 기대
  future         : 유효서명이되 미래 gen_time(시각을 거짓말하는 증인) — 등록은 통과하나
                   판정에서 ordering(T1≤judged_at) 실패로 temporal_witness 미성립 기대
  noanchor       : 앵커 부재 — 판정은 나되 temporal_witness 미성립(침묵 잠금 아닌 가시적 강등)

정직 경계(temporal.py docstring 준수): 증인 키 2개는 이 프로브가 생성 — solo box 에서는 *메커니즘*
(배선·정족수·ordering·fail-closed)의 실증이지 시각의 진짜 외부성 실증이 아니다. 외부성은 키 소유
구조가 결정하며, 본 프로브의 증명 범위는 "k 명 담합 없이는 백데이트 불가"의 구조적 강제다.

사적키는 evidence 에 남기지 않는다(공개 DID 만). 산출: ooptdd_receipts/temporal_witness_probe_20260723/
probe_evidence.json — judges/extaudit_temporal_witness_live{,_novel}.py 가 채점하는 커밋 대상.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lakatos.temporal import build_temporal_anchor, spec_digest          # noqa: E402
from lakatos.write_cert import keygen                                     # noqa: E402

BASE = os.environ.get("LAKATOTREE_URL", "http://localhost:55170").rstrip("/")
TREE = "LakatoTree_TemporalWitnessProbe_20260723"
RUN = os.environ.get("PROBE_RUN", "")   # 재실행 시 태그 suffix (예: PROBE_RUN=r3)
OUT = ROOT / "ooptdd_receipts" / "temporal_witness_probe_20260723" / "probe_evidence.json"
JUDGE_SCRIPT = "judges/engine_unify_vocab.py"   # 서버 체크아웃에 존재·결정론 0 — 시나리오 노드 채점용

_ENVELOPE_KEYS = ("write_cert", "temporal_anchor", "temporal_anchors")   # 서버 spec_digest 제외 키와 동일


def _post(path: str, payload: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"{BASE}{path}", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"raw": body[:400]}


def _get(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE}{path}", timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _pred_payload(tag: str) -> dict:
    # pydantic 이 float 으로 강제하는 필드는 float 로 — 서버 model_dump() 와 바이트 동일해야 digest 일치
    return {
        "metric_name": "probe_roundtrip", "direction": "lower", "baseline_value": 1.0,
        "noise_band": 0.0, "scale_type": "ratio", "novel_prediction": "",
        "novel_metric": None, "novel_direction": None, "novel_threshold": None,
        "judge_script_sha": None, "closes_question": "", "credence": None,
        "write_cert": None, "temporal_anchor": None, "temporal_anchors": None,
    }


def _anchors(secret_dids: list[tuple[str, str]], payload: dict, gen_time: str) -> list[dict]:
    sdg = spec_digest({k: v for k, v in payload.items() if k not in _ENVELOPE_KEYS})
    return [build_temporal_anchor(bytes.fromhex(sec), sdg, gen_time, did)
            for sec, did in secret_dids]


def _node_fields(tree_data: dict, tag: str) -> dict:
    for n in tree_data.get("nodes", []):
        if n.get("tag") == tag:
            return n
    return {}


def main() -> int:
    w1_sec, w1_did = keygen()
    w2_sec, w2_did = keygen()
    wo_sec, wo_did = keygen()   # allow-list 밖 증인
    W1, W2, W_OUT = (w1_sec, w1_did), (w2_sec, w2_did), (wo_sec, wo_did)
    now = datetime.now(timezone.utc).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()

    evidence: dict = {
        "probe": "q-extaudit-temporal-witness-20260722 live quorum probe",
        "tree": TREE, "server": BASE, "generated_at": now,
        "witness_dids": [w1_did, w2_did], "outsider_did": wo_did,
        "witness_threshold": 2,
        "honesty_boundary": "solo box 메커니즘 실증 — 시각의 진짜 외부성은 키 소유 구조 몫",
        "scenarios": [],
    }

    # ── probe 트리 생성 (witness 2, threshold 2, notebook tier) ──
    st, body = _post(f"/api/tree/{TREE}", {
        "title": "temporal witness k-of-N 라이브 프로브 (q-extaudit-temporal-witness-20260722)",
        "hard_core": "LakatosGate + critique + replayability",
        "frontier_rule": "probe 종료 시 archive",
        "assurance_tier": "notebook",
        "witness_dids": [w1_did, w2_did], "witness_threshold": 2,
    })
    evidence["tree_create"] = {"status": st, "ok": st in (200, 201)}
    if st not in (200, 201):
        evidence["scenarios"].append({"name": "tree_create", "ok": False, "body": body})
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"tree create failed: {st} {body}")
        return 1

    def scenario(name: str, tag_base: str, anchors: list[dict] | None,
                 expect_pred: int, submit: bool, node_checks: dict) -> None:
        # 실패 재시도 대비 run suffix — 앵커 422 도 등록 SET 을 소비하는 서버 동작(비원자 seam) 때문에
        # 같은 태그 재등록은 409 라, 재실행은 새 태그로 (증거의 시나리오명은 불변, judge 는 이름만 본다).
        tag = f"{tag_base}_{RUN}" if RUN else tag_base
        guards: list[dict] = []
        _post(f"/api/tree/{TREE}/node", {"tag": tag, "author": "temporal-probe",
                                         "comment": f"temporal witness probe — {name}"})
        payload = _pred_payload(tag)
        if anchors is not None:
            payload["temporal_anchors"] = anchors
        st, body = _post(f"/api/tree/{TREE}/node/{tag}/prediction", payload)
        guards.append({"guard": "prediction_status", "expected": expect_pred,
                       "actual": st, "ok": st == expect_pred})
        if st == 200:
            guards.append({"guard": "pred_anchor_verified",
                           "expected": bool(anchors), "actual": bool(body.get("pred_anchor_verified")),
                           "ok": bool(body.get("pred_anchor_verified")) == bool(anchors)})
        else:
            guards.append({"guard": "rejection_reason", "expected": "4xx body",
                           "actual": str(body)[:200], "ok": True})
        if submit and st == 200:
            st2, body2 = _post(f"/api/tree/{TREE}/node/{tag}/test_result",
                               {"metric_value": 0, "script": JUDGE_SCRIPT})
            guards.append({"guard": "submit_status", "expected": 200, "actual": st2, "ok": st2 == 200})
        if node_checks:
            td = _get(f"/api/tree/{TREE}")
            nf = _node_fields(td, tag)
            for key, expected in node_checks.items():
                actual = nf.get(key)
                guards.append({"guard": f"node.{key}", "expected": expected,
                               "actual": actual, "ok": actual == expected})
        evidence["scenarios"].append({
            "name": name, "tag": tag,
            "ok": all(g["ok"] for g in guards), "guards": guards})

    scenario("happy_2of2", "n_happy", _anchors([W1, W2], _pred_payload("n_happy"), now),
             200, True,
             {"pred_anchor_verified": True, "pred_anchor_quorum": 2, "pred_anchor_threshold": 2,
              "temporal_witness_verified": True})
    scenario("sybil_same_witness", "n_sybil", _anchors([W1, W1], _pred_payload("n_sybil"), now),
             422, False, {})
    scenario("outsider_witness", "n_outsider", _anchors([W_OUT, W_OUT], _pred_payload("n_outsider"), now),
             422, False, {})
    wrong = _pred_payload("n_digest")
    wrong["baseline_value"] = 999.0   # 다른 spec 을 커버한 앵커 밀반입
    scenario("digest_mismatch", "n_digest", _anchors([W1, W2], wrong, now),
             422, False, {})
    scenario("future_gen_time", "n_future", _anchors([W1, W2], _pred_payload("n_future"), future),
             200, True,
             {"pred_anchor_verified": True, "temporal_witness_verified": False})
    scenario("no_anchor", "n_noanchor", None,
             200, True,
             {"pred_anchor_verified": None, "temporal_witness_verified": False})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
    failed = [s["name"] for s in evidence["scenarios"] if not s["ok"]]
    print(f"evidence → {OUT}")
    print(f"scenarios ok={len(evidence['scenarios']) - len(failed)}/{len(evidence['scenarios'])}"
          + (f" FAILED: {failed}" if failed else ""))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
