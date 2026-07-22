#!/usr/bin/env python3
"""EXTAUDIT S6 novel 채점기 — 라이브에서 layout 이 역할 밖 서명자를 실제로 거부하는가 (e2e).

독립 결과: 라이브 서버(:55170)에 role layout 선언 트리를 만든다 —
  · attestor_dids=[predict_did, submit_did], research_layout 에 submit step pubkeys=[submit_did]만.
  · submit step 밖 키(predict_did)로 서명한 write_cert 로 submit → 403(역할 밖).
  · submit step 키(submit_did)로 서명하면 통과(양성 통제).
metric = 1 ⇔ 역할 밖 403 ∧ 역할 내 통과 / 0 ⇔ 좁힘 실패 / -1 ⇔ 프로브 실패(fail-closed).

hermetic 키생성: lakatos.write_cert(로컬). 트리명에 timestamp 로 충돌 회피.
stdout `metric=<int>` + exit 0.
"""
import json
import sys
import time
import urllib.request

sys.path.insert(0, __import__("pathlib").Path(__file__).resolve().parents[1].as_posix())
from lakatos.layout import canonical_layout_blob                       # noqa: E402
from lakatos.write_cert import (build_write_cert, did_key_encode,      # noqa: E402
                                ed25519_public_key, ed25519_sign)

BASE = "http://127.0.0.1:55170"
_S = {n: bytes([100 + n]) * 32 for n in (1, 2, 3)}   # owner/predict/submit
DID = {n: did_key_encode(ed25519_public_key(_S[n])) for n in _S}


def _req(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, None


def probe() -> int:
    tree = f"LakatosTree_RoleLayoutProbe_{int(time.time())}"
    predict_did, submit_did = DID[2], DID[3]
    layout = {"layout_version": 1, "steps": [
        {"verb": "submit_test_result", "pubkeys": [submit_did], "threshold": 1}]}
    owner_sig = ed25519_sign(_S[1], canonical_layout_blob(layout)).hex()
    try:
        st, _ = _req("POST", f"/api/tree/{tree}", {
            "title": "S6 role layout 프로브", "hard_core": "역할=다른 열쇠",
            "frontier_rule": "프로브 — 역할 밖 서명자 거부 측정", "assurance_tier": "anchored",
            "attestor_dids": [predict_did, submit_did],
            "research_layout": json.dumps(layout, ensure_ascii=False),
            "layout_owner_did": DID[1], "layout_sig": owner_sig})
        if st != 200:
            return -1

        def _one(tag, signer_secret, signer_did):
            _req("POST", f"/api/tree/{tree}/node", {"tag": tag, "comment": "role probe"})
            _req("POST", f"/api/tree/{tree}/node/{tag}/prediction", {
                "metric_name": "m", "direction": "lower", "baseline_value": 1.0, "noise_band": 0.0})
            cmd = {"tree": tree, "tag": tag, "prev_receipt_sha": None,
                   "metric_value": 0.5, "script_sha": None, "verb": "submit_test_result"}
            cert = build_write_cert(signer_secret, cmd)
            cert["signer_did"] = signer_did
            code, _ = _req("POST", f"/api/tree/{tree}/node/{tag}/test_result", {
                "metric_value": 0.5, "script": "judges/extaudit_probe_scorer.py",
                "result_path": "judges/extaudit_probe_scorer.py", "write_cert": cert})
            return code

        wrong = _one("wrong-role", _S[2], predict_did)     # predict 키로 submit 시도 → 403
        right = _one("right-role", _S[3], submit_did)       # submit 키 → 200
        return 1 if (wrong == 403 and right == 200) else 0
    except Exception:
        return -1


if __name__ == '__main__':
    print(f"metric={probe()}")
    sys.exit(0)
