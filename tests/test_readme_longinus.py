"""README ↔ 코드/설정/Lean Longinus 바인딩 — README 의 구조 주장을 실재에 *꼽는다*(드리프트 가드).

README 가 스스로 설파하는 "receipts, not claims" 를 README 자신에 적용: module map·계층·정리수 주장이
파일시스템/`.importlinter`/`formal/Pidna.lean` 과 어긋나면 RED. = README 는 조용히 거짓말 못 한다.
(엔진 reorg·split 때 module map 이 stale 났던 사고 회귀 가드.)
# KG: span_lakatotree_engine
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"

# 헤더 텍스트 → 계층 (Foundation 먼저: 헤더에 `lakatos/` 도 들었으나 root 로 귀속)
_HEADER_LAYER = [("Foundation", "root"), ("`verdict/`", "verdict"),
                 ("`quant/`", "quant"), ("`programme/`", "programme"), ("`io/`", "io")]
_ROSTER = re.compile(r"^(?:`[A-Za-z_]\w*`\s*)+$")   # 백틱 모듈명만으로 이뤄진 roster 줄


def _module_map_section() -> str:
    text = README.read_text(encoding="utf-8")
    start = text.index("## Module map")
    rest = text[start + 3:]
    return text[start: start + 3 + rest.index("\n## ")]


def _readme_layer_map() -> dict[str, set[str]]:
    lines = _module_map_section().splitlines()
    out: dict[str, set[str]] = {}
    for i, line in enumerate(lines):
        if not line.startswith("### "):
            continue
        layer = next((lyr for key, lyr in _HEADER_LAYER if key in line), None)
        if not layer:
            continue
        for j in range(i + 1, len(lines)):
            if lines[j].startswith("### "):
                break
            if _ROSTER.match(lines[j].strip()):
                out[layer] = set(re.findall(r"`([A-Za-z_]\w*)`", lines[j]))
                break
    return out


def _fs_layer_map() -> dict[str, set[str]]:
    out = {"root": {p.stem for p in (ROOT / "lakatos").glob("*.py") if p.stem != "__init__"}}
    for layer in ("verdict", "quant", "programme", "io"):
        out[layer] = {p.stem for p in (ROOT / "lakatos" / layer).glob("*.py") if p.stem != "__init__"}
    return out


def test_readme_module_map_is_a_bijection_with_filesystem():
    """README module map ↔ 실제 모듈 1:1 — 계층 오귀속·유령·누락 모두 차단(Longinus pierce)."""
    readme, fs = _readme_layer_map(), _fs_layer_map()
    assert set(readme) == set(fs), f"README 계층 {set(readme)} != fs {set(fs)}"
    for layer in fs:
        missing = fs[layer] - readme[layer]      # 코드엔 있는데 README 누락
        phantom = readme[layer] - fs[layer]      # README 엔 있는데 실재 없음(오귀속 포함)
        assert not missing and not phantom, (
            f"layer '{layer}' drift — README누락={sorted(missing)} README유령/오귀속={sorted(phantom)}")


def test_readme_layers_match_importlinter_contract():
    """README 가 주장하는 계층집합 == `.importlinter` strict layers 집합."""
    il = (ROOT / ".importlinter").read_text(encoding="utf-8")
    declared = set(re.findall(r"lakatos\.(\w+)", il))
    expected = {"programme", "verdict", "quant", "io"}
    assert expected <= declared, f".importlinter layers {declared} 가 {expected} 미포함"
    assert expected <= set(_readme_layer_map()), "README 계층이 importlinter 계층과 불일치"


def test_readme_theorem_count_matches_lean():
    """README 의 'N theorems' 주장 == formal/Pidna.lean 실제 theorem/lemma 수."""
    lean = ROOT / "formal" / "Pidna.lean"
    if not lean.exists():
        return   # Lean 없는 checkout 은 skip(정직)
    n = len(re.findall(r"^\s*(?:theorem|lemma)\b", lean.read_text(encoding="utf-8"), re.M))
    claimed = int(re.search(r"(\d+)\s+theorems", README.read_text(encoding="utf-8")).group(1))
    assert claimed == n, f"README {claimed} theorems 주장, Pidna.lean 은 {n}"


def test_readme_primary_kg_anchor_is_registered():
    """README 의 주 span 앵커가 KG 레지스트리(kg_anchors)에 실재 — 유령 참조 차단."""
    declared = set(json.loads((ROOT / "docs/longinus_bindings.json").read_text())["kg_anchors"])
    assert "span_lakatotree_engine" in README.read_text(encoding="utf-8")
    assert "span_lakatotree_engine" in declared
