"""Longinus — KG ReferenceSite ↔ 소스코드 바인딩 drift 감사 (자족, 서버 불필요).

라카토트리의 코드↔KG 관통(貫通) 위상. docs/longinus_bindings.json 매니페스트의 각 바인딩
{sourceId, file, symbol, sha256} 을 *현재* 소스에서 심볼 재해석(re-resolve)해 판정한다:
  - L4 drift : 심볼 소멸/리네임 (sourceId 가 가리키던 def/class/assignment 가 사라짐)
  - L6 drift : def-line 시그니처 변경 (sha256[:16] 불일치 — 의도된 변경이면 재베이스라인)
  - line_hint 는 *캐시* — stale 허용(심볼이 정본, 줄은 밀려도 무드리프트).

tests/test_longinus_bindings.py 와 동일 규칙을 재사용 가능한 함수로 추출.
# KG: span_lakatotree_world_gates, rs-longinus-cli-audit
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "longinus_bindings.json"


def _load(manifest: Path | None = None) -> dict:
    return json.loads((manifest or MANIFEST).read_text(encoding="utf-8"))


def _resolve(file: str, symbol: str, root: Path = ROOT):
    """심볼의 def/class/assignment 줄을 *현재* 소스에서 찾는다 (줄번호=재유도, 캐시 무시)."""
    path = root / file
    if not path.exists():
        return None, None
    s = re.escape(symbol)
    # ★H3 트랩(1) 수정: `=(?!=)` 로 `==` 비교를 정의(assignment)로 오인하지 않음(`:` annotation 은 유지).
    pats = [rf"^\s*def\s+{s}\s*\(", rf"^\s*async\s+def\s+{s}\s*\(",
            rf"^\s*class\s+{s}\b", rf"^\s*{s}\s*(?::|=(?!=))"]
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if any(re.search(p, line) for p in pats):
            return i, line
    return None, None


# ── H3 척추: ast 스코프-인식 resolver + 본문 전체 contents-hash ─────────────────────────────
#   정규식 _resolve 의 두 트랩((2) 동명 첫매칭, (3) def-한줄 sha)을 ast 로 닫는다. judge_script↔소스심볼
#   바인딩이 소비: 서버가 r.script 의 심볼을 *재해석*해 본문 전체를 해시(client 제출 sha 신뢰 금지).
#   무영수증 정직성: 없는 심볼=found False, 모호=sha None(거짓 영수증 날조 금지 — ⊥ 아니라 ?).

def _collect_defs(tree: ast.AST) -> list[tuple[str, ast.AST]]:
    """(qualname, node) — 모듈/클래스 스코프의 def/class/assignment. 함수 본문(=지역변수)은 제외."""
    out: list[tuple[str, ast.AST]] = []

    def walk(body: list, stack: list[str]) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.append((".".join(stack + [node.name]), node))   # 본문엔 안 내려감(locals)
            elif isinstance(node, ast.ClassDef):
                out.append((".".join(stack + [node.name]), node))
                walk(node.body, stack + [node.name])
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        out.append((".".join(stack + [t.id]), node))
            elif isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name):
                    out.append((".".join(stack + [node.target.id]), node))

    walk(getattr(tree, "body", []), [])
    return out


def resolve_symbol(file: str, symbol: str, root: Path = ROOT) -> dict:
    """심볼을 ast 로 스코프-인식 재해석. dotted=정확 qualname, bare=마지막 세그먼트 매칭(중복이면 ambiguous).

    반환: {found, ambiguous, qualname, lineno, end_lineno, def_line, candidates}. 첫매칭 침묵 금지 —
    bare 이름이 여러 정의에 걸리면 ambiguous=True 로 *명시 거부*(qualified name 을 요구).
    """
    none = {"found": False, "ambiguous": False, "qualname": None,
            "lineno": None, "end_lineno": None, "def_line": None, "candidates": []}
    path = root / file
    if not path.exists():
        return none
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError:
        return {**none, "error": "syntax"}
    defs = _collect_defs(tree)
    if "." in symbol:
        cands = [(q, n) for q, n in defs if q == symbol]
    else:
        cands = [(q, n) for q, n in defs if q.rsplit(".", 1)[-1] == symbol]
    if not cands:
        return none
    if len(cands) > 1:
        return {"found": True, "ambiguous": True, "qualname": None, "lineno": None,
                "end_lineno": None, "def_line": None, "candidates": [q for q, _ in cands]}
    q, node = cands[0]
    lines = src.splitlines()
    return {"found": True, "ambiguous": False, "qualname": q, "lineno": node.lineno,
            "end_lineno": getattr(node, "end_lineno", node.lineno),
            "def_line": lines[node.lineno - 1] if 0 < node.lineno <= len(lines) else None,
            "candidates": [q]}


def symbol_body_sha(file: str, symbol: str, root: Path = ROOT) -> tuple[str | None, dict]:
    """심볼 *본문 전체*(시그니처+바디)의 sha256 hex — CPG contents-hash. def-한줄 sha 의 본문-변경 무드리프트 봉쇄.

    found False(부재) 또는 ambiguous(모호)면 sha=None(거짓 영수증 금지). judge_script 바인딩의 서버측 재유도용.
    """
    r = resolve_symbol(file, symbol, root)
    if not r["found"]:
        return None, {"found": False, "reason": "absent_l4"}
    if r["ambiguous"]:
        return None, {"found": True, "ambiguous": True, "candidates": r["candidates"], "reason": "ambiguous"}
    src = (root / file).read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(root / file))
    node = next((n for q, n in _collect_defs(tree) if q == r["qualname"]), None)
    seg = ast.get_source_segment(src, node) if node is not None else None
    if seg is None:
        return None, {"found": True, "reason": "no_source_segment"}
    return (hashlib.sha256(seg.encode("utf-8")).hexdigest(),
            {"found": True, "ambiguous": False, "qualname": r["qualname"],
             "lineno": r["lineno"], "end_lineno": r["end_lineno"]})


def audit(root: Path = ROOT, manifest: Path | None = None) -> dict:
    """전 바인딩 drift 감사. 순수 — 같은 입력 같은 출력."""
    bindings = _load(manifest).get("bindings", [])
    l4, l6, ok = [], [], []
    for b in bindings:
        ln, line = _resolve(b["file"], b["symbol"], root)
        if ln is None:
            l4.append({"sourceId": b["sourceId"], "file": b["file"], "symbol": b["symbol"]})
            continue
        cur = hashlib.sha256(line.encode()).hexdigest()[:16]
        if cur != b.get("sha256"):
            l6.append({"sourceId": b["sourceId"], "file": b["file"], "symbol": b["symbol"],
                       "baseline": b.get("sha256"), "current": cur,
                       "line": ln, "line_hint": b.get("line_hint")})
        else:
            ok.append({"sourceId": b["sourceId"], "line": ln,
                       "line_hint": b.get("line_hint"), "line_drift": ln != b.get("line_hint")})
    return {"ok": not (l4 or l6), "total": len(bindings),
            "passed": len(ok), "l4_drift": l4, "l6_drift": l6, "bindings_ok": ok}


def report(result: dict | None = None) -> str:
    """사람용 한 화면 요약."""
    r = result or audit()
    lines = [f"Longinus 바인딩 감사 — {r['passed']}/{r['total']} OK"
             + ("  ✅" if r["ok"] else "  ❌ DRIFT")]
    for d in r["l4_drift"]:
        lines.append(f"  L4(심볼 소멸/리네임): {d['sourceId']}  [{d['file']}::{d['symbol']}]")
    for d in r["l6_drift"]:
        lines.append(f"  L6(시그니처 변경): {d['sourceId']}  {d['baseline']}→{d['current']}  "
                     f"(재베이스라인: docs/longinus_bindings.json + KG ReferenceSite)")
    drifted = sum(1 for b in r["bindings_ok"] if b["line_drift"])
    if drifted:
        lines.append(f"  ℹ {drifted} 바인딩 line_hint stale(캐시) — 심볼 정본 유효, 무드리프트")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    res = audit()
    print(report(res))
    sys.exit(0 if res["ok"] else 1)
