#!/usr/bin/env python3
"""EXTAUDIT S6b/S7b/S8b novel 채점기 — 세 라이브 배선이 실제 서버에서 발효하는가 (e2e).

라이브 서버(:55170)에서:
  · S6b: layout 이 register_prediction step 선언한 트리에서 무서명 예측 → 403(역할서명 강제).
  · S7b: witness_dids 선언 트리에서 유효 spec 앵커로 register → GET 노드에 pred_anchor_verified=true.
  · S8b: 평범한 submit 후 GET 노드에 measurement_lock_sha 실림(측정락 mint).
metric = 1 ⇔ 셋 다 / 0 ⇔ 하나라도 실패 / -1 ⇔ 프로브 예외(fail-closed).

hermetic 키생성: lakatos.write_cert/layout/temporal(로컬). stdout `metric=<int>` + exit 0.
"""
import json
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, __import__("pathlib").Path(__file__).resolve().parents[1].as_posix())
from lakatos.layout import canonical_layout_blob                                  # noqa: E402
from lakatos.temporal import build_temporal_anchor, spec_digest                   # noqa: E402
from lakatos.write_cert import (build_write_cert, did_key_encode,                 # noqa: E402
                                ed25519_public_key, ed25519_sign)

BASE = "http://127.0.0.1:55170"
_S = {n: bytes([170 + n]) * 32 for n in (1, 2, 3)}       # owner / predict-signer / witness
DID = {n: did_key_encode(ed25519_public_key(_S[n])) for n in _S}


def _req(m, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=m,
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=60) as z:
            return z.status, json.loads(z.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def _node(tree, tag):
    _, td = _req("GET", f"/api/tree/{tree}")
    if not isinstance(td, dict):
        return {}
    for n in td.get("nodes", []):
        if n.get("tag") == tag:
            return n
    return {}


def probe() -> int:
    stamp = int(time.time())
    lo = {"layout_version": 1, "steps": [
        {"verb": "register_prediction", "pubkeys": [DID[2]], "threshold": 1}]}
    owner_sig = ed25519_sign(_S[1], canonical_layout_blob(lo)).hex()
    try:
        # (S6b) layout+witness 트리 — 무서명 예측 403.
        t = f"LakatoTree_LiveWireProbe_{stamp}"
        st, _ = _req("POST", f"/api/tree/{t}", {
            "title": "S6b/S7b/S8b live 배선 프로브", "hard_core": "역할서명+증인+측정락",
            "frontier_rule": "라이브 배선 발효 측정", "assurance_tier": "notebook",
            "research_layout": json.dumps(lo, ensure_ascii=False),
            "layout_owner_did": DID[1], "layout_sig": owner_sig, "witness_dids": [DID[3]]})
        if st != 200:
            return -1
        _req("POST", f"/api/tree/{t}/node", {"tag": "unsigned", "comment": "무서명 예측 시도"})
        code_unsigned, _ = _req("POST", f"/api/tree/{t}/node/unsigned/prediction", {
            "metric_name": "m", "direction": "lower", "baseline_value": 1.0, "noise_band": 0.0})
        s6b = (code_unsigned == 403)

        # (S7b) 역할서명 + 외부 증인 앵커 → register → pred_anchor_verified.
        _req("POST", f"/api/tree/{t}/node", {"tag": "anchored", "comment": "증인 앵커 예측"})
        spec = {"metric_name": "m", "direction": "lower", "baseline_value": 1.0, "noise_band": 0.0,
                "scale_type": "ratio", "novel_prediction": "", "novel_metric": None,
                "novel_direction": None, "novel_threshold": None, "judge_script_sha": None,
                "closes_question": "", "credence": None}
        sdg = spec_digest(spec)
        anchor = build_temporal_anchor(_S[3], sdg, "2026-07-23T06:00:00+00:00", DID[3])
        cmd = {"tree": t, "tag": "anchored", "prev_receipt_sha": None, "metric_value": None,
               "script_sha": None, "verb": "register_prediction"}
        cert = build_write_cert(_S[2], cmd); cert["signer_did"] = DID[2]
        code_reg, reg = _req("POST", f"/api/tree/{t}/node/anchored/prediction",
                             {**spec, "write_cert": cert, "temporal_anchor": anchor})
        s7b = (code_reg == 200 and isinstance(reg, dict) and reg.get("pred_anchor_verified") is True
               and _node(t, "anchored").get("pred_anchor_verified") is True)

        # (S8b) 평범한 트리에서 submit → measurement_lock_sha mint (락은 tier 무관).
        t2 = f"LakatoTree_LiveLockProbe_{stamp}"
        _req("POST", f"/api/tree/{t2}", {"title": "S8b lock", "hard_core": "x",
                                         "frontier_rule": "측정락", "assurance_tier": "notebook"})
        _req("POST", f"/api/tree/{t2}/node", {"tag": "lk", "comment": "락 프로브"})
        _req("POST", f"/api/tree/{t2}/node/lk/prediction", {
            "metric_name": "m", "direction": "lower", "baseline_value": 1.0, "noise_band": 0.0})
        _req("POST", f"/api/tree/{t2}/node/lk/test_result", {
            "metric_value": 0.5, "script": "judges/extaudit_probe_scorer.py",
            "result_path": "judges/extaudit_probe_scorer.py"})
        s8b = bool(_node(t2, "lk").get("measurement_lock_sha"))

        return 1 if (s6b and s7b and s8b) else 0
    except Exception:
        return -1


if __name__ == '__main__':
    print(f"metric={probe()}")
    sys.exit(0)
