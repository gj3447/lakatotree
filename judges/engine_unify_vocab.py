#!/usr/bin/env python3
"""engine-unify 채점기 — verdicts.py 정본 밖 verdict 어휘 리터럴 집합 정의 수 (baseline 9 → 목표 0).

측정: lakatos/ + server/ 프로덕션 코드를 AST 로 걸어, 원소 ≥2개이고 *모든* 문자열 원소가
VERDICT_REGISTRY 어휘인 set/frozenset/tuple 리터럴 정의 지점을 센다(정본 verdicts.py 자신,
tests/examples/docs/build 산출물 제외). 레지스트리 docstring 의 '재유도 금지' 규칙의 구조적 위반 수.
구현 전 9(validation 3 + series 2 + node_state 1 + fsck 1 + metrics 1 + spine 1), 흡수 후 0 이어야 한다.
stdout `metric=<int>` + exit 0 (harness 계약, ag1 장르). 결정론 — LLM 무관, import 불필요(자기완비).
사전등록 후 이 파일 동결 (script_sha 서버 앵커 — 완화 = sha 변경 = 409).
# KG 거울: LakatosTree_LakatoTree_SelfDev_20260612 / q-lkt-engine-unify
"""
from __future__ import annotations   # 서버 replay 가 구형 python 으로 돌려도 annotation 평가 충돌 없게

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# lakatos/verdicts.py VERDICT_REGISTRY 와 동일 어휘 (자기완비 — 정본 변경 시 이 스크립트는 sha 로 잠김)
VOCAB = frozenset({
    'progressive', 'partial', 'equivalent', 'rejected',
    'CANONICAL', 'canonical_stage', 'former_canonical', 'proof', 'superseded',
    'CANONICAL_KNOWLEDGE', 'repurposed_measurement',
    'progressive_conditional', 'progressive_unverified', 'degenerating', 'withdrawn',
    'different_programme', 'ambiguous',
    'rebuildable', 'rebuildable_static', 'metric_mismatch', 'env_drift', 'step_failed',
})

SCAN_ROOTS = ('lakatos', 'server')
SKIP_PARTS = {'tests', 'examples', 'docs', 'build', '__pycache__', '.venv'}
CANON = 'verdicts.py'   # 정본 자신은 제외 (거기서 정의하는 것이 정상)


def _literal_strs(node: ast.AST) -> list[str] | None:
    """set/tuple 리터럴(및 frozenset(...) 래핑)의 문자열 원소 — 전원 str 상수일 때만."""
    inner = node
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'frozenset':
        if len(node.args) != 1 or node.keywords:
            return None
        inner = node.args[0]
    if not isinstance(inner, (ast.Set, ast.Tuple)):
        return None
    strs = []
    for el in inner.elts:
        if isinstance(el, ast.Constant) and isinstance(el.value, str):
            strs.append(el.value)
        else:
            return None   # 비문자열 원소 혼재 = 어휘 집합 아님
    return strs


def count_sites() -> tuple[int, list[str]]:
    seen: set[tuple[str, int, tuple[str, ...]]] = set()
    sites: list[str] = []
    for root_name in SCAN_ROOTS:
        for path in sorted((ROOT / root_name).rglob('*.py')):
            if path.name == CANON or SKIP_PARTS & set(path.parts):
                continue
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
            for node in ast.walk(tree):
                strs = _literal_strs(node)
                if strs and len(strs) >= 2 and all(s in VOCAB for s in strs):
                    # frozenset({...}) 는 Call 과 남는 Set 이 이중 매칭 — (파일,행,원소)로 dedupe
                    key = (str(path), node.lineno, tuple(sorted(strs)))
                    if key in seen:
                        continue
                    seen.add(key)
                    sites.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    return len(sites), sites


if __name__ == '__main__':
    n, details = count_sites()
    for d in details:
        print(f"# site {d}", file=sys.stderr)
    print(f"metric={n}")
    sys.exit(0)
