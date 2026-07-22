#!/usr/bin/env python3
"""EXTAUDIT S5 novel 채점기 — 라이브에서 red 가지 확장 시 abandon_signal 이 실제로 기록되는가 (e2e).

독립 결과: 라이브 서버(:55170)에 rejected 연쇄 3개(사전등록→고의 반증 submit ×3)를 만든 뒤
그 leaf 에 자식 노드를 add 하면 응답에 abandon_signal(fired=True, 연속 비진보 사유)과
policy_warnings ABANDON_SIGNAL_IGNORED 가 실리는가.

metric = 1 ⇔ 신호+경고 동봉 / 0 ⇔ 침묵 진격(급소 #7 잔존) / -1 ⇔ 프로브 실패(fail-closed)
stdout `metric=<int>` + exit 0. 프로브 트리 = LakatosTree_ReplayDefaultProbe_20260722.
고의 반증: direction=lower, baseline=1.0 에 metric_value=5.0 제출 → rejected (probe_scorer 미사용,
값 불일치 replay 는 rejected 판정에 무해 — grade 는 이 프로브의 측정 대상이 아님).
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
    with urllib.request.urlopen(r, timeout=120) as resp:
        return json.loads(resp.read().decode())


def probe() -> int:
    stamp = int(time.time())
    try:
        _req("POST", f"/api/tree/{TREE}", {
            "title": "S2 replay 기본 ON 발효 프로브 (NovelAnchorProbe 장르)",
            "hard_core": "라이브 서버는 sandbox 선언 시 client 제출값을 재실행으로 재유도한다",
            "frontier_rule": "프로브 노드 — S5 abandon 신호 측정"})
        parent = ""
        for i in range(3):
            tag = f"abprobe-{stamp}-{i}"
            body = {"tag": tag, "author": "claude-fable-5/extaudit-s5",
                    "comment": "S5 red 가지 프로브(고의 반증)"}
            if parent:
                body["parent"] = parent
            _req("POST", f"/api/tree/{TREE}/node", body)
            _req("POST", f"/api/tree/{TREE}/node/{tag}/prediction", {
                "metric_name": "probe_metric", "direction": "lower",
                "baseline_value": 1.0, "noise_band": 0.0})
            _req("POST", f"/api/tree/{TREE}/node/{tag}/test_result", {
                "metric_value": 5.0, "script": "judges/extaudit_probe_scorer.py",
                "result_path": "judges/extaudit_probe_scorer.py"})
            parent = tag
        child = _req("POST", f"/api/tree/{TREE}/node", {
            "tag": f"abprobe-{stamp}-child", "parent": parent,
            "author": "claude-fable-5/extaudit-s5", "comment": "red light 위 확장"})
        sig = child.get("abandon_signal") or {}
        warned = "ABANDON_SIGNAL_IGNORED" in (child.get("policy_warnings") or [])
        return 1 if (sig.get("fired") is True and warned) else 0
    except Exception:
        return -1


if __name__ == '__main__':
    print(f"metric={probe()}")
    sys.exit(0)
