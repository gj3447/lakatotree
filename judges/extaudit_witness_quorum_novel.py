#!/usr/bin/env python3
"""심화 D1 novel 채점기 — 라이브에서 2-of-2 증인 정족수가 실제로 강제되는가 (e2e).

witness_threshold=2 트리에서:
  · 증인 1명 앵커로 register → 422(정족수 미달).
  · 증인 2명(distinct) 앵커로 register → 200 + pred_anchor_verified=true, quorum=2.
metric = 1 ⇔ 단일 거부 ∧ 2명 통과 / 0 ⇔ 정족수 무효 / -1 ⇔ 프로브 실패(fail-closed).
stdout `metric=<int>` + exit 0.
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
_S = {n: bytes([235 + n]) * 32 for n in (1, 2, 3, 4)}   # owner / predict / witnessA / witnessB
DID = {n: did_key_encode(ed25519_public_key(_S[n])) for n in _S}


def _req(m, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=m,
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=60) as z:
            return z.status, json.loads(z.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def probe() -> int:
    stamp = int(time.time())
    lo = {"layout_version": 1, "steps": [
        {"verb": "register_prediction", "pubkeys": [DID[2]], "threshold": 1}]}
    sig = ed25519_sign(_S[1], canonical_layout_blob(lo)).hex()
    spec = {"metric_name": "m", "direction": "lower", "baseline_value": 1.0, "noise_band": 0.0,
            "scale_type": "ratio", "novel_prediction": "", "novel_metric": None,
            "novel_direction": None, "novel_threshold": None, "judge_script_sha": None,
            "closes_question": "", "credence": None}
    sdg = spec_digest(spec)
    t1 = "2026-07-22T00:00:00+00:00"     # past T1 (before now)
    ancA = build_temporal_anchor(_S[3], sdg, t1, DID[3])
    ancB = build_temporal_anchor(_S[4], sdg, t1, DID[4])
    rcert = lambda: dict(build_write_cert(_S[2], {"tree": None, "tag": None, "prev_receipt_sha": None,
                                                  "metric_value": None, "script_sha": None,
                                                  "verb": "register_prediction"}))
    try:
        # threshold=2 트리, 증인 allowlist=[A,B].
        t = f"LakatoTree_QuorumProbe_{stamp}"
        st, _ = _req("POST", f"/api/tree/{t}", {
            "title": "D1 2-of-2 정족수", "hard_core": "담합 저항", "frontier_rule": "정족수",
            "assurance_tier": "notebook", "research_layout": json.dumps(lo, ensure_ascii=False),
            "layout_owner_did": DID[1], "layout_sig": sig,
            "witness_dids": [DID[3], DID[4]], "witness_threshold": 2})
        if st != 200:
            return -1

        def _reg(tag, anchors):
            _req("POST", f"/api/tree/{t}/node", {"tag": tag, "comment": "quorum probe"})
            cmd = {"tree": t, "tag": tag, "prev_receipt_sha": None, "metric_value": None,
                   "script_sha": None, "verb": "register_prediction"}
            cert = build_write_cert(_S[2], cmd); cert["signer_did"] = DID[2]
            return _req("POST", f"/api/tree/{t}/node/{tag}/prediction",
                        {**spec, "write_cert": cert, "temporal_anchors": anchors})

        code_single, _ = _reg("single", [ancA])            # 1명 → 미달 422
        code_two, two = _reg("two", [ancA, ancB])          # 2명 → 통과
        single_rejected = (code_single == 422)
        two_ok = (code_two == 200 and isinstance(two, dict) and two.get("pred_anchor_verified") is True)
        return 1 if (single_rejected and two_ok) else 0
    except Exception:
        return -1


if __name__ == '__main__':
    print(f"metric={probe()}")
    sys.exit(0)
