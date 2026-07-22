#!/usr/bin/env python3
"""EXTAUDIT S6 novel 채점기 — 라이브에서 layout 이 역할 밖 서명자를 실제로 거부하는가 (e2e).

독립 결과(role-narrowing 인과 격리): 같은 서명자(predict_did, attestor_dids 안에 있음)를 두 트리에서 시험 —
  · layout 트리(submit step pubkeys=[submit_did]만): predict_did 로 submit → 403 "allow-list 밖"
    (layout 이 이 verb 를 좁혀 attestor 이지만 역할 밖이라 거부).
  · no-layout 트리(attestor_dids=[predict_did]): 같은 predict_did → allow-list 통과, 명령바인딩
    단계(422)까지 도달 = allow-list 는 그를 막지 않는다(폴백 불변).
차이의 유일 원인 = layout 역할 좁히기. metric = 1 ⇔ layout 트리서 allow-list 거부 ∧ no-layout 트리서
allow-list 통과 / 0 ⇔ 좁힘 무효 / -1 ⇔ 프로브 실패(fail-closed).

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
        return e.code, e.read().decode("utf-8", "replace")


def _submit_with_cert(tree, tag, signer_secret, signer_did):
    """노드 생성→사전등록→cert submit. 반환 (status, detail). allow-list 거부(403)는 명령바인딩 이전
    단계라 cert 의 prev/script sha 미상과 무관하게 확정적."""
    _req("POST", f"/api/tree/{tree}/node", {"tag": tag, "comment": "role probe"})
    _req("POST", f"/api/tree/{tree}/node/{tag}/prediction", {
        "metric_name": "m", "direction": "lower", "baseline_value": 1.0, "noise_band": 0.0})
    cmd = {"tree": tree, "tag": tag, "prev_receipt_sha": None,
           "metric_value": 0.5, "script_sha": None, "verb": "submit_test_result"}
    cert = build_write_cert(signer_secret, cmd)
    cert["signer_did"] = signer_did
    return _req("POST", f"/api/tree/{tree}/node/{tag}/test_result", {
        "metric_value": 0.5, "script": "judges/extaudit_probe_scorer.py",
        "result_path": "judges/extaudit_probe_scorer.py", "write_cert": cert})


def probe() -> int:
    stamp = int(time.time())
    predict_did, submit_did = DID[2], DID[3]
    layout = {"layout_version": 1, "steps": [
        {"verb": "submit_test_result", "pubkeys": [submit_did], "threshold": 1}]}
    owner_sig = ed25519_sign(_S[1], canonical_layout_blob(layout)).hex()
    try:
        # (A) layout 트리 — predict_did 는 attestor 이나 submit 역할 밖 → allow-list 거부(403).
        t_lo = f"LakatoTree_RoleLayoutProbe_{stamp}_lo"
        st, _ = _req("POST", f"/api/tree/{t_lo}", {
            "title": "S6 role layout 프로브", "hard_core": "역할=다른 열쇠",
            "frontier_rule": "역할 밖 서명자 거부 측정", "assurance_tier": "anchored",
            "attestor_dids": [predict_did, submit_did],
            "research_layout": json.dumps(layout, ensure_ascii=False),
            "layout_owner_did": DID[1], "layout_sig": owner_sig})
        if st != 200:
            return -1
        code_lo, detail_lo = _submit_with_cert(t_lo, "predict-tries-submit", _S[2], predict_did)

        # (B) no-layout 트리 — 같은 predict_did 가 attestor 전체 → allow-list 통과(명령바인딩까지).
        t_nolo = f"LakatoTree_RoleLayoutProbe_{stamp}_nolo"
        st2, _ = _req("POST", f"/api/tree/{t_nolo}", {
            "title": "S6 no-layout 대조", "hard_core": "x", "frontier_rule": "폴백 대조",
            "assurance_tier": "anchored", "attestor_dids": [predict_did]})
        if st2 != 200:
            return -1
        code_nolo, _ = _submit_with_cert(t_nolo, "predict-submits", _S[2], predict_did)

        rejected_by_role = (code_lo == 403 and "allow-list" in (detail_lo or ""))
        passed_allowlist_no_layout = (code_nolo != 403)   # 422 명령바인딩 등 — allow-list 통과
        return 1 if (rejected_by_role and passed_allowlist_no_layout) else 0
    except Exception:
        return -1


if __name__ == '__main__':
    print(f"metric={probe()}")
    sys.exit(0)
