#!/usr/bin/env python3
"""judge — GO1 dogfood: 채점시점 producer-replay 가 라이브인가 (측정주권 dead-σ 3단의 flip 실증).

metric: go1_scoring_replay_enabled
  = :55170 포트를 소유한 *서빙 프로세스*의 /proc/<pid>/environ 에서 LAKATOS_REPLAY_EXEC 가
    명시적 truthy('1'/'true'/'yes'/'on')면 1.0, 아니면 0.0.

상수/손입력이 아니라 라이브 프로세스 상태의 실측이다. 클라이언트가 미리 돌려도, 서버가
submit 시 replay 로 재실행해도 *같은 실측점*(서빙 프로세스의 env)을 보므로 값이 수렴한다 —
이 스크립트가 server_regenerated 로 값소유되는 것 자체가 GO1 폐루프(env 플립→재기동→
채점시점 재실행→값 치환)의 실증이다. 영수증: results/go1_replay_dogfood_result.json
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_TRUTHY = ("1", "true", "yes", "on")


def _serving_pid_55170() -> int | None:
    """cmdline 에 uvicorn 과 55170 이 함께 있는 프로세스 — ss/psutil 없이 /proc 만으로(샌드박스 내구)."""
    for p in Path("/proc").iterdir():
        if not p.name.isdigit():
            continue
        try:
            cmd = (p / "cmdline").read_bytes().replace(b"\0", b" ")
        except OSError:
            continue
        if b"uvicorn" in cmd and b"55170" in cmd:
            return int(p.name)
    return None


def main() -> None:
    pid = _serving_pid_55170()
    flag = None
    if pid is not None:
        try:
            env = (Path(f"/proc/{pid}/environ").read_bytes()).split(b"\0")
            for kv in env:
                if kv.startswith(b"LAKATOS_REPLAY_EXEC="):
                    flag = kv.split(b"=", 1)[1].decode().strip().lower()
        except OSError:
            pid = None
    value = 1.0 if (flag in _TRUTHY) else 0.0
    receipt = {
        "tree": "LakatosTree_MeasurementSovereignty_20260703",
        "node": "go1_replay_flip_dogfood",
        "metric": "go1_scoring_replay_enabled",
        "value": value,
        "serving_pid": pid,
        "replay_exec_env": flag,
    }
    out = REPO / "results" / "go1_replay_dogfood_result.json"
    out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False))
    print(f"metric = {value}")


if __name__ == "__main__":
    main()
