#!/usr/bin/env python3
"""EXTAUDIT S3 novel 채점기 — 라이브 standing 표면에 VAL 등급이 실제로 동봉되는가 (e2e).

독립 결과: 재배포된 라이브 서버(:55170)에서 프로브 노드(server_regenerated 로 재유도됨)를 만들고
GET standing 하면 verdict 문자열이 '@L2(replay_verified' 를 포함하는가.

metric = 1  ⇔  라이브 standing verdict 에 '@L2(replay_verified' 동봉
metric = 0  ⇔  bare verdict 그대로 (급소 #5 잔존)
metric = -1 ⇔  프로브 자체 실패 (fail-closed)

stdout `metric=<int>` + exit 0. 프로브 트리 = LakatosTree_ReplayDefaultProbe_20260722 (S2 프로브 재사용).
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
    tag = f"valprobe-{int(time.time())}"
    try:
        _req("POST", f"/api/tree/{TREE}", {
            "title": "S2 replay 기본 ON 발효 프로브 (NovelAnchorProbe 장르)",
            "hard_core": "라이브 서버는 sandbox 선언 시 client 제출값을 재실행으로 재유도한다",
            "frontier_rule": "프로브 노드 — S3 VAL 표면 동봉 측정"})
        _req("POST", f"/api/tree/{TREE}/node", {
            "tag": tag, "author": "claude-fable-5/extaudit-s3",
            "comment": "VAL 표면 동봉 e2e 프로브 노드"})
        _req("POST", f"/api/tree/{TREE}/node/{tag}/prediction", {
            "metric_name": "probe_metric", "direction": "lower",
            "baseline_value": 1.0, "noise_band": 0.0})
        _req("POST", f"/api/tree/{TREE}/node/{tag}/test_result", {
            "metric_value": 0.5, "script": "judges/extaudit_probe_scorer.py",
            "result_path": "judges/extaudit_probe_scorer.py"})
        st = _req("GET", f"/api/tree/{TREE}/node/{tag}/standing")
        v = st.get("verdict") or ""
        return 1 if "@L2(replay_verified" in v else 0
    except Exception:
        return -1


if __name__ == '__main__':
    print(f"metric={probe()}")
    sys.exit(0)
