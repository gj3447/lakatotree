"""설계감사 H9(완성-후 로드맵 2026-06-26) — verdict-write CAS *클래스* 봉인 (TOCTOU+self-report 동시 잠금).

H5(set_verdict 승격)·H7(add_critique 강등)·M5(submit scripted)·M12 가 verdict-mutating write 를 인스턴스별로
원자 CAS 화했다. 그러나 *미래에 누군가* 가드 없는 verdict-전이 write 를 추가하면 TOCTOU/self-report 가 부활한다
(클래스 재발). 이 테스트는 인스턴스가 아니라 *클래스 전체* 를 덮는다: server/·lakatos/ 의 모든 Cypher 문자열에서
verdict 를 CANONICAL/former_canonical 로 전이하거나 verdict_source 를 'scripted' 로 박는 SET 은 *같은 쿼리* 안에
스냅샷 재검증 가드(WHERE)를 동반해야 한다. 무가드 전이가 하나라도 생기면 RED — commit 시점에 자동 차단.

"완벽 = 클래스를 by-construction 불가능 + 재발 자동 RED" 의 verdict-write 판(板). verdict_source 가 client 에서
오지 않음(server-set-only)도 함께 단언.
# KG: span_lakatotree_design_audit_20260625
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SCAN_DIRS = ["server", "lakatos"]

# verdict 권위를 바꾸는 *전이* SET (가드 필수): CANONICAL/former_canonical 승강 + scripted 채점.
_TRANSITION = re.compile(
    r"SET\b[\s\S]*?\b[\w.]*verdict\s*=\s*'(CANONICAL|former_canonical)'"
    r"|SET\b[\s\S]*?\bverdict_source\s*=\s*'scripted'")

# 같은 쿼리 안에 있어야 하는 스냅샷 재검증 가드 토큰(낙관적 CAS / 조건부 매치) 중 최소 하나.
_GUARD_TOKENS = (
    "coalesce(cur.verdict",            # H5 set_verdict 승격 스냅샷 CAS
    "coalesce(e.verdict",              # H7 add_critique 강등 스냅샷 CAS
    "arg_fp",                          # 논증집합 지문 재검증(H5/H7)
    "verdict_source <> 'scripted'",    # M5 submit 원자 claim CAS
    "verdict_source IS NULL",          # M5 claim CAS(첫 채점 허용)
    "e.verdict='CANONICAL'",           # app.py AGM 강등: WHERE 로 현 CANONICAL 재검증
    "{verdict:'CANONICAL'}",           # 매치 패턴으로 현 CANONICAL 노드만 강등
)


def _cypher_strings(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and "SET" in node.value:
            yield node.value


def test_every_verdict_transition_write_has_cas_guard():
    """클래스 봉인: verdict 를 CANONICAL/former_canonical 로 전이하거나 scripted 채점하는 모든 SET 은
    같은 쿼리 안에 스냅샷 재검증 가드를 동반한다(무가드 전이=TOCTOU/self-report 부활 → RED)."""
    violations: list[str] = []
    n_transitions = 0
    for rel in _SCAN_DIRS:
        for py in (_ROOT / rel).rglob("*.py"):
            relpath = str(py.relative_to(_ROOT))
            for cy in _cypher_strings(ast.parse(py.read_text(), filename=relpath)):
                if not _TRANSITION.search(cy):
                    continue
                n_transitions += 1
                # 가드는 *첫 (실)SET 이전*(MATCH/WHERE/WITH 영역)에 있어야 인정 — SET 절 안의 verdict='CANONICAL'
                # 리터럴이 자기 자신을 가드로 위장하는 false-pass 차단(Cypher 는 WHERE 가 SET 보다 앞).
                # 단 eager-lock 무전이 SET(`SET x._cas=coalesce(x._cas,0)+0` — 술어 평가 전 노드 쓰기락 선점,
                # #16/#17 원자화)은 verdict 전이가 아니므로 제거한 뒤 '첫 SET' 을 찾는다(락 SET 이 가드를 가리지 않게).
                cas_stripped = re.sub(r"SET\s+\w+\._cas\s*=\s*coalesce\([^)]*\)\s*\+\s*0", "", cy)
                pre_set = cas_stripped.split("SET", 1)[0]
                if not any(tok in pre_set for tok in _GUARD_TOKENS):
                    snippet = " ".join(cy.split())[:120]
                    violations.append(f"{relpath}: 무가드 verdict-전이 SET → …{snippet}…")
    # 비-vacuity: 실 전이 사이트(H5 승격·H7/app 강등·M5 scripted)를 잡았는지
    assert n_transitions >= 4, f"verdict-전이 SET 스캔 실패({n_transitions}<4) — 클래스 테스트가 vacuous"
    assert not violations, (
        "verdict-write CAS 클래스 위반 — 스냅샷 재검증 없는 verdict-전이 write(TOCTOU/self-report 부활):\n  "
        + "\n  ".join(violations))


def test_verdict_source_is_never_client_set():
    """동반 불변식: verdict_source 는 server-set-only — client 스키마(_SERVER_SET_ONLY extra='forbid')가
    verdict_source 필드를 받지 않는다(self-report verdict 출처 위조 차단)."""
    schemas = (_ROOT / "server/contexts/tree/schemas.py").read_text()
    assert "_SERVER_SET_ONLY" in schemas and 'extra="forbid"' in schemas
    # client 입력 스키마 어디에도 verdict_source 필드가 선언돼선 안 된다(서버만 SET)
    assert "verdict_source:" not in schemas, "client 스키마가 verdict_source 필드 노출 → server-set-only 위반"
