#!/usr/bin/env python3
"""EXTAUDIT S2 채점기 — replay 기본 ON 2단 설계 가드 실패 수 (baseline 2 → 목표 0).

측정: tests/test_extaudit_c1verify_temporal.py 전체를 pytest 로 실행해 failed 수를 센다.
결함가드 2(sandbox 선언 시 unset=ON) + 양성통제 4(선언 없음 OFF 불변·명시값 우선·boolean 파싱) = 6.
구현 전 2 실패(가드 RED), 구현 후 0. stdout `metric=<int>` + exit 0 (harness 계약). 결정론 — LLM 무관.
사전등록 후 이 파일 동결 (script_sha 서버 앵커).
# KG 거울: LakatosTree_LakatoTree_SelfDev_20260612 / d2_extaudit_c1verify_temporal
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def count_failures() -> int:
    p = subprocess.run(
        [sys.executable, '-m', 'pytest', 'tests/test_extaudit_c1verify_temporal.py', '-q', '--tb=no'],
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
