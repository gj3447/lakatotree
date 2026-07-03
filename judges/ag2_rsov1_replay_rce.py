#!/usr/bin/env python3
"""AG2/R-SOV-1 채점기 — replay exec 경로에 열린 RCE 벡터 수 (측정주권 2026-07-03).

측정: server/app.py `_replay_run` 을 4개 RCE 벡터(-c argv 인젝션·result_path flag 위장·허용루트 밖
절대경로·비-python 실행파일)로 두드려, 무해 sentinel side-effect 를 내거나 거부되지 않은 벡터 수를 센다.
payload 는 무해(허용루트 tmp 에 sentinel 쓰기 시도) — 봉합 후 0. metric=<열린 벡터 수>. exit 0.

self-report 아님: 실제 `_replay_run` 을 호출해 실측(격리/rlimit 떼면 값이 오른다).
# KG 거울: LakatosTree_MeasurementSovereignty_20260703 / ag2_rsov1_replay_rce
"""
import os
import sys
import tempfile

os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)


def open_rce_vectors() -> int:
    import server.app as app
    tmp = tempfile.mkdtemp(prefix="ag2judge_")
    sentinel = os.path.join(tmp, "PWNED")
    real = os.path.join(tempfile.gettempdir(), "ag2judge_scorer.py")
    with open(real, "w") as f:
        f.write("print('metric=1.0')\n")
    vectors = [
        f"python -c import os;open('{sentinel}','w').write('1')",   # -c argv 인젝션
        f"python {real} -cimport os;open('{sentinel}','w').write('2')",  # result_path flag 위장
        "python /etc/passwd",                                       # 허용루트 밖 절대경로
        f"/bin/sh -c touch\\ {sentinel}",                           # 비-python 실행파일
    ]
    opened = 0
    for cmd in vectors:
        out, code = app._replay_run(cmd)
        executed = os.path.exists(sentinel) or not (
            code != 0 and str(out).startswith("replay_error:unsafe_command"))
        if executed:
            opened += 1
        if os.path.exists(sentinel):
            os.remove(sentinel)
    return opened


if __name__ == "__main__":
    print(f"metric={open_rce_vectors()}")
    sys.exit(0)
