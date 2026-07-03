"""설계감사 M13(완성-후 로드맵 2026-06-26) — actor-독립성 *클래스* 봉인 (인스턴스가 아니라 클래스).

H8 은 인라인 AF 조립(by 무시) 3 호출부를 assemble_af 정본으로 수렴했다. 그러나 *미래에 누군가* 또 인라인
AF 를 조립해 grounded_extension 을 호출하면 self-vouch 가 부활한다(클래스 재발). 이 테스트는 인스턴스가
아니라 *클래스 전체* 를 덮는다: server/·lakatos/ 의 어떤 함수든 grounded_extension 을 호출하면 반드시
같은 함수에서 actor-aware assemble_af 도 호출해야 한다(인라인 AF 조립 금지). 위반이 하나라도 생기면 RED —
self-vouch 회귀를 commit 시점에 자동으로 잡는다.

"완벽 = 클래스를 by-construction 으로 불가능하게 + 재발을 자동 RED" 의 구현. argue.py(정의처)는 화이트리스트.
# KG: span_lakatotree_argue / span_lakatotree_design_audit_20260625
"""
from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SCAN_DIRS = ["server", "lakatos"]
# 정의처/교차검증 모듈 — grounded_extension 과 assemble_af 가 여기 살고 단위테스트가 직접 부른다.
_WHITELIST = {"lakatos/verdict/argue.py"}


def _calls_named(node: ast.AST, name: str) -> bool:
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if (isinstance(f, ast.Name) and f.id == name) or (isinstance(f, ast.Attribute) and f.attr == name):
                return True
    return False


def _functions_calling(tree: ast.AST, name: str):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _calls_named(node, name):
            yield node


def test_no_inline_af_assembly_actor_independence():
    """클래스 봉인: grounded_extension 을 호출하는 모든 함수는 actor-aware assemble_af 도 호출한다.

    인라인 AF 조립(arguments/attacks 를 손으로 만들어 grounded_extension 에 직접 넘김)은 by(actor)를
    누락해 self-vouch 를 부활시키므로 by-construction 금지 — 위반 함수가 하나라도 있으면 fail.
    """
    violations: list[str] = []
    n_callers = 0
    for rel in _SCAN_DIRS:
        for py in (_ROOT / rel).rglob("*.py"):
            relpath = str(py.relative_to(_ROOT))
            if relpath in _WHITELIST:
                continue
            tree = ast.parse(py.read_text(), filename=relpath)
            for fn in _functions_calling(tree, "grounded_extension"):
                n_callers += 1
                if not _calls_named(fn, "assemble_af"):
                    violations.append(f"{relpath}::{fn.name} (grounded_extension 호출하나 assemble_af 미사용 — 인라인 AF)")
    # 비-vacuity: 실제 standing 결정 호출부(set_verdict/add_critique/standing)를 스캔이 잡았는지 — 0이면 테스트 헛돎
    assert n_callers >= 3, f"grounded_extension 호출부 스캔 실패({n_callers}<3) — 클래스 테스트가 vacuous"
    assert not violations, (
        "actor-독립성 클래스 위반 — grounded_extension 을 인라인 AF 로 호출(by 무시 → self-vouch 부활):\n  "
        + "\n  ".join(violations))


def test_assemble_af_is_the_sole_af_builder_present():
    """정의처(argue.py)에 actor-aware assemble_af 가 실재하고 by 를 실제로 본다(테스트가 헛돌지 않음)."""
    src = (_ROOT / "lakatos/verdict/argue.py").read_text()
    assert "def assemble_af(" in src
    assert "by_of" in src and "self-defense" in src, "assemble_af 가 actor(by) 기반 self-defense 제거를 안 함"
