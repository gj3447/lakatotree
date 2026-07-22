#!/usr/bin/env python3
"""EXTAUDIT S1 채점기 — grade-gate 결함가드 실패 수 (baseline 3 → 목표 0).

측정: tests/test_extaudit_grade_gate.py 전체를 pytest 로 실행해 failed 수를 센다.
결함가드 3(client_asserted 무검증 강등 ×2 + fertility 파급) + 양성통제 4(무회귀) = 7.
구현 전 3 실패(가드 RED), 구현 후 0 이어야 한다 — 0 은 "강등이 작동하고 무회귀"의 동시 증명.
stdout `metric=<int>` + exit 0 (harness 계약, ag1 장르). 결정론 — LLM 무관.
사전등록 후 이 파일 동결 (script_sha 서버 앵커 — 완화 = sha 변경 = 409).
# KG 거울: LakatosTree_LakatoTree_SelfDev_20260612 / v19_extaudit_grade_gate
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def count_failures() -> int:
    p = subprocess.run(
        [sys.executable, '-m', 'pytest', 'tests/test_extaudit_grade_gate.py', '-q', '--tb=no'],
        cwd=ROOT, capture_output=True, text=True, timeout=300)
    out = p.stdout + p.stderr
    m = re.search(r'(\d+) failed', out)
    if m:
        return int(m.group(1))
    if re.search(r'(\d+) passed', out) and p.returncode == 0:
        return 0
    return 99   # 수집 자체가 깨짐 = 최악값 (fail-closed)


if __name__ == '__main__':
    print(f"metric={count_failures()}")
    sys.exit(0)
