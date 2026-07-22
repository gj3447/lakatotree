#!/usr/bin/env python3
"""EXTAUDIT S1 novel 채점기 — 전체 회귀 실패 수 (독립 결과: 게이트 도입이 기존 1,700+ 계약을 깨지 않는다).

주 메트릭(신규 가드 실패 수)과 독립인 별도 실측 — 전체 스위트의 failed+error 수.
novel_threshold < 1 (즉 0): grade-gate 가 키-부재 신뢰 계약(_SOURCE_ABSENT)을 지켰다면
기존 골든(비트동일 계약 포함)은 전부 생존해야 한다는 사전 예측.
stdout `metric=<int>` + exit 0. 결정론 — LLM 무관.
"""
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
