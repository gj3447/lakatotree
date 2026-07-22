#!/usr/bin/env python3
"""EXTAUDIT S4 novel 채점기 — 라이브에서 comment 봉인 미러가 실제로 mint 되는가 (e2e).

독립 결과: 재배포된 라이브 서버(:55170)에서 comment 있는 프로브 노드를 submit 하면
GET tree 의 해당 노드에 comment_sha_at_verdict 가 non-null 로 실리고, 그 값이
sha256(제출 시점 comment)과 일치하는가.

metric = 1 ⇔ 미러 실재 ∧ 해시 일치 / 0 ⇔ 미러 부재·불일치 / -1 ⇔ 프로브 실패(fail-closed)
stdout `metric=<int>` + exit 0. 프로브 트리 = LakatosTree_ReplayDefaultProbe_20260722.
"""
import hashlib
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:55170"
TREE = "LakatosTree_ReplayDefaultProbe_20260722"
COMMENT = "S4 프로브 — 판정 시점 코멘트(봉인 대상)"


def _req(method: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=60) as resp:
        return json.loads(resp.read().decode())


def probe() -> int:
    tag = f"csprobe-{int(time.time())}"
    try:
        _req("POST", f"/api/tree/{TREE}", {
            "title": "S2 replay 기본 ON 발효 프로브 (NovelAnchorProbe 장르)",
            "hard_core": "라이브 서버는 sandbox 선언 시 client 제출값을 재실행으로 재유도한다",
            "frontier_rule": "프로브 노드 — S4 comment 봉인 측정"})
        _req("POST", f"/api/tree/{TREE}/node", {
            "tag": tag, "author": "claude-fable-5/extaudit-s4", "comment": COMMENT})
        _req("POST", f"/api/tree/{TREE}/node/{tag}/prediction", {
            "metric_name": "probe_metric", "direction": "lower",
            "baseline_value": 1.0, "noise_band": 0.0})
        _req("POST", f"/api/tree/{TREE}/node/{tag}/test_result", {
            "metric_value": 0.5, "script": "judges/extaudit_probe_scorer.py",
            "result_path": "judges/extaudit_probe_scorer.py"})
        tree = _req("GET", f"/api/tree/{TREE}")
        nodes = tree.get("nodes", tree if isinstance(tree, list) else [])
        for n in nodes:
            if n.get("tag") == tag:
                seal = n.get("comment_sha_at_verdict")
                want = hashlib.sha256((n.get("comment") or "").encode()).hexdigest()
                return 1 if (seal and seal == want) else 0
        return -1
    except Exception:
        return -1


if __name__ == '__main__':
    print(f"metric={probe()}")
    sys.exit(0)
