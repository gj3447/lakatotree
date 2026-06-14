"""Longinus 코드 바인딩 drift-guard — KG ReferenceSite 의 in-repo 정본 미러 검사.

★설계(자가모순 해소): anchor 는 *심볼*(sourceId)이지 *줄번호*가 아니다. drift 판정은 심볼을
재해석(re-resolve)해 한다 — 줄이 밀려도(주석 추가 등) 심볼이 그 자리면 무드리프트.
sha256 은 def-line *내용* 해시라 시그니처가 바뀔 때만 변한다. 따라서:
  - 줄 이동(line_hint stale) = 무드리프트(심볼이 정본, 줄은 캐시) → 통과
  - 심볼 소멸/리네임(L4) = drift → 실패
  - def-line 시그니처 변경(L6, sha 불일치) = drift → 실패(검토 필요)
이로써 `# KG:` 주석을 코드에 박아 줄이 밀려도 이 가드가 깨지지 않는다(symbol-resolved).
# KG: span_lakatotree_world_gates
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "longinus_bindings.json"


def _load() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _resolve(file: str, symbol: str):
    """심볼의 def/class/assignment 줄을 *현재* 소스에서 찾는다. (줄번호=재유도, 캐시 무시)."""
    lines = (ROOT / file).read_text(encoding="utf-8").splitlines()
    s = re.escape(symbol)
    pats = [rf"^\s*def\s+{s}\s*\(", rf"^\s*class\s+{s}\b", rf"^\s*{s}\s*[:=]"]
    for i, line in enumerate(lines, 1):
        if any(re.search(p, line) for p in pats):
            return i, line
    return None, None


def test_all_bindings_symbol_resolves():
    """모든 바인딩의 sourceId 심볼이 해당 파일에 실재한다 (소멸/리네임 = L4 drift)."""
    broken = []
    for b in _load()["bindings"]:
        ln, _ = _resolve(b["file"], b["symbol"])
        if ln is None:
            broken.append(b["sourceId"])
    assert not broken, f"Longinus L4 drift — 심볼 소멸/리네임: {broken}"


def test_all_bindings_def_line_sha_unchanged():
    """def-line sha256 이 baseline 과 일치 (시그니처 변경 = L6 drift, 검토 필요)."""
    drift = []
    for b in _load()["bindings"]:
        _, line = _resolve(b["file"], b["symbol"])
        if line is None:
            continue  # L4 는 위 테스트가 잡는다
        cur = hashlib.sha256(line.encode()).hexdigest()[:16]
        if cur != b["sha256"]:
            drift.append({"sourceId": b["sourceId"], "baseline": b["sha256"], "current": cur})
    assert not drift, (
        "Longinus L6 drift — def-line 시그니처 변경. 의도된 변경이면 docs/longinus_bindings.json "
        f"의 sha256 + KG ReferenceSite 를 재베이스라인하라:\n{drift}")


def test_line_hint_is_cache_not_anchor():
    """line_hint 는 *캐시* — 정확하면 좋으나 stale 도 허용(심볼이 정본). 단 모두 소멸은 sanity 실패."""
    bindings = _load()["bindings"]
    resolved = sum(1 for b in bindings if _resolve(b["file"], b["symbol"])[0] is not None)
    assert resolved == len(bindings), "모든 심볼이 resolve 되어야(=anchor 유효)"
