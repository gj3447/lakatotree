#!/usr/bin/env python3
"""EXTAUDIT S2 novel 채점기 — 라이브 서버 replay *발효* e2e 프로브.

독립 결과(주 메트릭=테스트 가드와 별개 실측): 재시작된 라이브 서버(:55170)에서 프로브 노드를
사전등록→submit 하면 서버가 judges/extaudit_probe_scorer.py 를 실제 재실행해 값을 재유도하는가.

metric = 1  ⇔  프로브 노드의 measurement_grade=='server_regenerated' ∧ replay_status=='verified'
metric = 0  ⇔  여전히 client_asserted (GO1 미발효)
metric = -1 ⇔  프로브 자체 실패(서버 다운/HTTP 오류) — fail-closed 최악값

stdout `metric=<int>` + exit 0. 프로브 트리 = LakatosTree_ReplayDefaultProbe_20260722 (NovelAnchorProbe 장르).
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
    tag = f"probe-{int(time.time())}"
    try:
        _req("POST", f"/api/tree/{TREE}", {
            "title": "S2 replay 기본 ON 발효 프로브 (NovelAnchorProbe 장르)",
            "hard_core": "라이브 서버는 sandbox 선언 시 client 제출값을 재실행으로 재유도한다",
            "frontier_rule": "프로브 노드 1개 — replay 발효 여부만 측정, 확장 없음"})
        _req("POST", f"/api/tree/{TREE}/node", {
            "tag": tag, "author": "claude-fable-5/extaudit-s2",
            "comment": "replay 발효 e2e 프로브 노드"})
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
                ok = (n.get("measurement_grade") == "server_regenerated"
                      and n.get("replay_status") == "verified")
                return 1 if ok else 0
        return -1
    except Exception:
        return -1


if __name__ == '__main__':
    print(f"metric={probe()}")
    sys.exit(0)
