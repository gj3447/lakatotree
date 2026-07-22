#!/usr/bin/env python3
"""EXTAUDIT S5 채점기 — Laudan 폐기신호 배선 가드 실패 수 (baseline → 목표 0).

측정: tests/test_extaudit_abandon_wire.py 전체를 pytest 로 실행해 failed 수를 센다.
발화+영속기록 1 + 무발화 이중가드 1 + fail-open 1 = 3.
구현 전 RED, 구현 후 0. stdout `metric=<int>` + exit 0 (harness 계약). 결정론 — LLM 무관.
사전등록 후 이 파일 동결 (script_sha 서버 앵커).
# KG 거울: LakatosTree_LakatoTree_SelfDev_20260612 / v24_extaudit_abandon_wire
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def count_failures() -> int:
    p = subprocess.run(
        [sys.executable, '-m', 'pytest', 'tests/test_extaudit_abandon_wire.py', '-q', '--tb=no'],
        cwd=ROOT, capture_output=True, text=True, timeout=300)
    out = p.stdout + p.stderr
    m = re.search(r'(\d+) failed', out)
    if m:
        return int(m.group(1))
    if re.search(r'(\d+) passed', out) and p.returncode == 0:
        return 0
    return 99   # 수집 붕괴 = 최악값 (fail-closed)


if __name__ == '__main__':
    print(f"metric={count_failures()}")
    sys.exit(0)
