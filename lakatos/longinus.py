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
    pats = [rf"^\s*def\s+{s}\s*\(", rf"^\s*async\s+def\s+{s}\s*\(",
            rf"^\s*class\s+{s}\b", rf"^\s*{s}\s*[:=]"]
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if any(re.search(p, line) for p in pats):
            return i, line
    return None, None


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
