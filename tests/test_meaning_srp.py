"""Meaning-SRP gate — SOLID SRP applied to the SEMANTIC layer (docs/meaning_units.json).

매 고수준 의미 단위는 *정확히 하나*의 owner sourceId + 테스트 ≥1 + 문서 ref 를 가져야 한다,
아니면 *정직하게 gap 선언*(owner=null + reason). "의미를 LOC 로 부풀리기"가 아니라
"어떤 개념도 단일 책임자(owner)·영수증(test)·문서 없이 주장 못 한다"의 강제.
decorative/thin 개념을 gap 으로 표면화한다(조용한 의미-과잉주장 차단).

owner 해석은 파일시스템 module→path 맵으로(서브패키지 reorg 에 drift-proof, test_readme_longinus 와 동형).
# KG: span_lakatotree_engine
"""
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REG = ROOT / "docs" / "meaning_units.json"
_MODMAP = {p.stem: p for p in ROOT.glob("lakatos/**/*.py") if p.stem != "__init__"}


def _units() -> list:
    return json.loads(REG.read_text(encoding="utf-8"))["meaning_units"]


def _owner_resolves(owner: str) -> bool:
    """owner = 'module.Symbol' → 그 모듈 파일에서 Symbol 의 def/class/assignment 가 실재하는가."""
    mod, _, sym = owner.partition(".")
    path = _MODMAP.get(mod)
    if path is None or not sym:
        return False
    src = path.read_text(encoding="utf-8")
    s = re.escape(sym)
    pats = [rf"^\s*def\s+{s}\s*\(", rf"^\s*async\s+def\s+{s}\s*\(",
            rf"^\s*class\s+{s}\b", rf"^\s*{s}\s*[:=]"]
    return any(re.search(p, src, re.M) for p in pats)


def test_every_covered_unit_has_a_single_resolvable_owner():
    """SRP-의미층: covered 단위는 owner sourceId(module.symbol) 정확히 1개 + 실재 심볼."""
    bad = []
    for u in _units():
        if u["status"] != "covered":
            continue
        owner = u.get("owner")
        if not isinstance(owner, str) or not owner:
            bad.append((u["unit"], "no single owner"))
        elif not _owner_resolves(owner):
            bad.append((u["unit"], f"owner unresolved: {owner}"))
    assert not bad, f"meaning-SRP owner 위반: {bad}"


def test_every_covered_unit_has_test_and_doc():
    """covered 단위는 영수증(존재하는 test 파일 ≥1) + 문서 ref 를 가져야."""
    bad = []
    for u in _units():
        if u["status"] != "covered":
            continue
        tests = u.get("tests") or []
        if not tests:
            bad.append((u["unit"], "no test"))
        for t in tests:
            if not (ROOT / t).exists():
                bad.append((u["unit"], f"missing test file: {t}"))
        if not (u.get("doc") or "").strip():
            bad.append((u["unit"], "no doc ref"))
    assert not bad, f"meaning-SRP test/doc 위반: {bad}"


def test_owner_is_unique_per_concept_srp():
    """SRP: 한 owner 심볼이 2+ 의미단위를 소유 = 책임 분산 → 분리하거나 단위 병합."""
    owners = Counter(u["owner"] for u in _units()
                     if u["status"] == "covered" and u.get("owner"))
    dupes = {o: c for o, c in owners.items() if c > 1}
    assert not dupes, f"SRP 위반(한 owner 가 복수 의미): {dupes}"


def test_gaps_are_honestly_declared_not_silent():
    """gap 단위는 owner=null + reason 필수 — decorative 개념의 조용한 주장 금지(정직)."""
    bad = []
    for u in _units():
        if u["status"] == "gap":
            if u.get("owner"):
                bad.append((u["unit"], "gap must have owner=null"))
            if not (u.get("reason") or "").strip():
                bad.append((u["unit"], "gap needs a reason"))
    assert not bad, f"미정직 gap: {bad}"


def test_status_is_known_and_unit_named():
    for u in _units():
        assert u.get("status") in ("covered", "gap"), f"unknown status: {u}"
        assert (u.get("unit") or "").strip(), f"unnamed unit: {u}"


def test_coverage_is_reported():
    """진단(어설션 없음 핵심): 의미 커버리지 = covered / total. gap 은 곧 로드맵."""
    units = _units()
    covered = [u for u in units if u["status"] == "covered"]
    gaps = [u for u in units if u["status"] == "gap"]
    assert len(covered) + len(gaps) == len(units)
    assert len(covered) >= 1
    # gap 은 0 이어야 하는 게 아님 — 정직하게 선언된 한 OK (로드맵 신호)
