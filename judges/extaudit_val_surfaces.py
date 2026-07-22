#!/usr/bin/env python3
"""EXTAUDIT S3b 채점기 — VAL 표면 확장 가드 실패 수 (baseline: 부재 → 목표 0).

측정: tests/test_extaudit_val_surfaces.py 를 pytest 로 실행해 failed(+수집붕괴=99) 수를 센다.
read-model 부착 3 + 비파괴 계약 1 + submit 헬퍼/배선 앵커 2 = 6.
stdout `metric=<int>` + exit 0. 결정론 — LLM 무관. 사전등록 후 동결 (script_sha 서버 앵커).
# KG 거울: LakatosTree_LakatoTree_SelfDev_20260612 / v22_extaudit_val_surfaces
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def count_failures() -> int:
    p = subprocess.run(
        [sys.executable, '-m', 'pytest', 'tests/test_extaudit_val_surfaces.py', '-q', '--tb=no'],
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
