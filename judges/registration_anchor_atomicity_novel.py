#!/usr/bin/env python3
"""등록 원자성 novel 채점기 — 전체 회귀 실패 수 (독립 결과: 순서 변경이 기존 계약을 깨지 않는다).

주 메트릭(원자성 가드)과 독립인 별도 실측 — 전체 스위트의 failed+error 수.
novel_threshold < 1 (즉 0): validate-then-write 재배치가 S6b/S7b/S8b 배선·정족수·budget 등
기존 골든을 전부 생존시켰다는 사전 예측. stdout `metric=<int>` + exit 0. 결정론 — LLM 무관.
# KG 거울: LakatosTree_LakatoTree_SelfDev_20260612 / q-lkt-nonatomic-registration-anchor-20260723
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def count_suite_failures() -> int:
    p = subprocess.run(
        [sys.executable, '-m', 'pytest', 'tests/', '-q', '--tb=no', '-p', 'no:cacheprovider'],
        cwd=ROOT, capture_output=True, text=True, timeout=3600)
    out = p.stdout + p.stderr
    failed = sum(int(n) for n in re.findall(r'(\d+) failed', out))
    errors = sum(int(n) for n in re.findall(r'(\d+) error', out))
    if failed == 0 and errors == 0 and not re.search(r'\d+ passed', out):
        return 99   # 수집 붕괴 = 최악값 (fail-closed)
    return failed + errors


if __name__ == '__main__':
    print(f"metric={count_suite_failures()}")
    sys.exit(0)
