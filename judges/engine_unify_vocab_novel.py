#!/usr/bin/env python3
"""engine-unify novel 채점기 — spine.py 의 무호출 promotion composer 수 (baseline 1 → 목표 0).

주 메트릭(어휘 리터럴 지점 수)과 독립인 별도 실측 — '단일 승격 판결 권위'의 구조적 위반:
lakatos/verdict/spine.py 에 정의된 promotion_* 공개 함수 중 프로덕션(lakatos/+server/, tests 제외)
호출부가 0인 composer 수. 2026-06-27 fix-harness 가 floor drift 를 잡았던 promotion_decision 이 1.
삭제(또는 재배선) 후 0 이어야 '권위 단일' 예측이 적중.
stdout `metric=<int>` + exit 0. 결정론 — LLM 무관, import 불필요(자기완비).
# KG 거울: LakatosTree_LakatoTree_SelfDev_20260612 / q-lkt-engine-unify
"""
from __future__ import annotations   # 서버 replay 가 구형 python 으로 돌려도 annotation 평가 충돌 없게

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPINE = ROOT / 'lakatos' / 'verdict' / 'spine.py'
SCAN_ROOTS = ('lakatos', 'server')
SKIP_PARTS = {'tests', 'examples', 'docs', 'build', '__pycache__', '.venv'}


def count_dead_composers() -> tuple[int, list[str]]:
    tree = ast.parse(SPINE.read_text(encoding='utf-8'), filename=str(SPINE))
    composers = [n.name for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.name.startswith('promotion')]
    corpus = []
    for root_name in SCAN_ROOTS:
        for path in sorted((ROOT / root_name).rglob('*.py')):
            if SKIP_PARTS & set(path.parts):
                continue
            corpus.append(path.read_text(encoding='utf-8'))
    blob = '\n'.join(corpus)
    dead = []
    for name in composers:
        # 정의 지점(def name() 1회) 외 프로덕션 호출/참조가 없으면 사장 composer
        uses = len(re.findall(rf'(?<!def )\b{re.escape(name)}\b', blob))
        if uses <= 1:   # docstring 언급 1회까지 관용 (spine 모듈 docstring 의 roster 행)
            dead.append(name)
    return len(dead), dead


if __name__ == '__main__':
    n, dead = count_dead_composers()
    for d in dead:
        print(f"# dead {d}", file=sys.stderr)
    print(f"metric={n}")
    sys.exit(0)
