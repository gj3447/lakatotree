"""Longinus ast-기반 심볼 resolver — 설계감사 H3(judge_script↔소스심볼 바인딩) 척추.

RED-first(trap_if_skipped = 음성 명세):
  (1) 정규식 `{s}[:=]` 가 `==` 비교를 *정의*로 오인 → 거짓 바인딩.
  (2) `re.search` 첫매칭만 → 동명 심볼/스코프 구분 못 함(엉뚱한 def 에 바인딩).
  (3) sha 가 def *한 줄*만 → 본문 변경 무드리프트(CPG contents-hash = 본문 전체여야).
이 테스트들이 RED 였다가, longinus 의 ast resolver + 본문 contents-hash 로 GREEN 이 된다.
# KG: span_lakatotree_longinus_ast_resolver
"""
from __future__ import annotations

import hashlib

from lakatos import longinus


# ── 트랩(1): `==` 비교를 정의로 오인하지 않는다 ─────────────────────────────────
def test_comparison_not_misread_as_definition(tmp_path):
    """`ready == expected` 는 정의가 아니다 — _resolve 가 이걸 assignment 로 잡으면 거짓 바인딩."""
    (tmp_path / "cmp.py").write_text("ready == expected\n", encoding="utf-8")
    ln, _ = longinus._resolve("cmp.py", "ready", root=tmp_path)
    assert ln is None, "`==` 비교가 정의(assignment)로 오인됨 — 거짓 심볼 바인딩"


def test_real_assignment_and_annotation_still_resolve(tmp_path):
    """회귀 가드: 진짜 assignment/annotation 은 여전히 잡아야(=, : 정상)."""
    (tmp_path / "ok.py").write_text("flag = True\nlimit: int = 5\n", encoding="utf-8")
    assert longinus._resolve("ok.py", "flag", root=tmp_path)[0] == 1
    assert longinus._resolve("ok.py", "limit", root=tmp_path)[0] == 2


# ── 트랩(2): 스코프-인식 — 동명 심볼을 qualified name 으로 구분 ──────────────────
_MOD = (
    "class A:\n"
    "    def run(self):\n"
    "        return 'A'\n"
    "\n"
    "class B:\n"
    "    def run(self):\n"
    "        return 'B'\n"
    "\n"
    "def run():\n"
    "    return 'top'\n"
)


def test_resolve_symbol_scope_disambiguation(tmp_path):
    """B.run 은 B 의 메서드(line 6)여야 — 첫매칭(A.run, line 2)이 아니라."""
    (tmp_path / "m.py").write_text(_MOD, encoding="utf-8")
    r = longinus.resolve_symbol("m.py", "B.run", root=tmp_path)
    assert r["found"] and not r["ambiguous"]
    assert r["qualname"] == "B.run"
    assert r["lineno"] == 6, f"스코프 무시 — B.run 이 {r['lineno']}행으로 잘못 바인딩"


def test_resolve_symbol_bare_duplicate_is_ambiguous(tmp_path):
    """bare 'run' 은 3개(A.run/B.run/run) → ambiguous 로 *명시 거부*(첫매칭 침묵 금지)."""
    (tmp_path / "m.py").write_text(_MOD, encoding="utf-8")
    r = longinus.resolve_symbol("run", "run", root=tmp_path) if False else \
        longinus.resolve_symbol("m.py", "run", root=tmp_path)
    assert r["ambiguous"] is True
    assert set(r["candidates"]) == {"A.run", "B.run", "run"}


# ── 트랩(3): 본문 전체 contents-hash — def 한 줄이 아니라 ────────────────────────
def test_symbol_body_sha_detects_body_change(tmp_path):
    """def-line 이 똑같아도 *본문*이 바뀌면 sha 가 바뀌어야(CPG contents-hash)."""
    p = tmp_path / "b.py"
    p.write_text("def f():\n    return 1\n", encoding="utf-8")
    sha1, info1 = longinus.symbol_body_sha("b.py", "f", root=tmp_path)
    assert sha1 and info1["found"]
    # def-line 은 동일, 본문만 변경
    p.write_text("def f():\n    return 2\n", encoding="utf-8")
    sha2, _ = longinus.symbol_body_sha("b.py", "f", root=tmp_path)
    # 옛 def-line sha(한 줄)는 동일했을 것 — 대조용
    defline_sha = hashlib.sha256("def f():".encode()).hexdigest()[:16]
    assert sha1 != sha2, "본문 변경을 contents-hash 가 못 잡음(def-line 만 해시하는 트랩)"
    assert defline_sha == hashlib.sha256("def f():".encode()).hexdigest()[:16]  # def-line 불변 명시


def test_symbol_body_sha_absent_and_ambiguous_refuse(tmp_path):
    """없는 심볼=found False, 모호=sha None(거짓 영수증 금지 — 무영수증은 ⊥ 아니라 ?)."""
    (tmp_path / "m.py").write_text(_MOD, encoding="utf-8")
    sha_absent, info_absent = longinus.symbol_body_sha("m.py", "ghost", root=tmp_path)
    assert sha_absent is None and not info_absent["found"]
    sha_amb, info_amb = longinus.symbol_body_sha("m.py", "run", root=tmp_path)
    assert sha_amb is None and info_amb.get("ambiguous") is True
