#!/usr/bin/env python3
"""등록 원자성 채점기 — validate-then-write 가드 실패 수 (baseline 1 → 목표 0).

측정: tests/test_registration_anchor_atomicity.py 전체를 pytest 로 실행해 failed 수를 센다.
결함가드 1(앵커 422 가 등록을 소비 → 노드 stuck) + 양성통제 1(유효 앵커 등록 정상) = 2.
구현 전 1 실패(가드 RED), 구현 후 0. stdout `metric=<int>` + exit 0 (harness 계약, ag1 장르).
사전등록 후 이 파일 동결 (script_sha 서버 앵커).
# KG 거울: LakatosTree_LakatoTree_SelfDev_20260612 / q-lkt-nonatomic-registration-anchor-20260723
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def count_failures() -> int:
    p = subprocess.run(
        [sys.executable, '-m', 'pytest', 'tests/test_registration_anchor_atomicity.py',
         '-q', '--tb=no', '-p', 'no:cacheprovider'],
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
