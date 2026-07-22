#!/usr/bin/env python3
"""EXTAUDIT S3b novel 채점기 — 라이브 submit 응답 + tree read 양쪽 표면에 VAL 동봉 (e2e).

독립 결과: 재배포된 라이브 서버(:55170)에서 프로브 노드를 submit 하면
  ① submit 응답에 verdict_display='...@L2(replay_verified)' 가 동봉되고
  ② GET /api/tree/{name} 의 해당 노드에도 verdict_display 가 실리는가.

metric = 1 ⇔ 양쪽 다 '@L2(replay_verified' 동봉 / 0 ⇔ 한쪽이라도 bare / -1 ⇔ 프로브 실패(fail-closed)
stdout `metric=<int>` + exit 0. 프로브 트리 = LakatosTree_ReplayDefaultProbe_20260722.
"""
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:55170"
TREE = "LakatosTree_ReplayDefaultProbe_20260722"


def _req(method: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=60) as resp:
        return json.loads(resp.read().decode())


def probe() -> int:
    tag = f"sfprobe-{int(time.time())}"
    try:
        _req("POST", f"/api/tree/{TREE}", {
            "title": "S2 replay 기본 ON 발효 프로브 (NovelAnchorProbe 장르)",
            "hard_core": "라이브 서버는 sandbox 선언 시 client 제출값을 재실행으로 재유도한다",
            "frontier_rule": "프로브 노드 — S3b VAL 표면 확장 측정"})
        _req("POST", f"/api/tree/{TREE}/node", {
            "tag": tag, "author": "claude-fable-5/extaudit-s3b",
            "comment": "VAL 표면 확장 e2e 프로브 노드"})
        _req("POST", f"/api/tree/{TREE}/node/{tag}/prediction", {
            "metric_name": "probe_metric", "direction": "lower",
            "baseline_value": 1.0, "noise_band": 0.0})
        sub = _req("POST", f"/api/tree/{TREE}/node/{tag}/test_result", {
            "metric_value": 0.5, "script": "judges/extaudit_probe_scorer.py",
            "result_path": "judges/extaudit_probe_scorer.py"})
        ok_sub = "@L2(replay_verified" in (sub.get("verdict_display") or "")
        tree = _req("GET", f"/api/tree/{TREE}")
        nodes = tree.get("nodes", tree if isinstance(tree, list) else [])
        ok_read = any(n.get("tag") == tag and "@L2(replay_verified" in (n.get("verdict_display") or "")
                      for n in nodes)
        return 1 if (ok_sub and ok_read) else 0
    except Exception:
        return -1


if __name__ == '__main__':
    print(f"metric={probe()}")
    sys.exit(0)
