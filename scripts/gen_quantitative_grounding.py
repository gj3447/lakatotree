"""docs/QUANTITATIVE_GROUNDING.md 생성기 — 정본 lakatos/grounding.py 에서 자동 도출.

전엔 문서가 "자동생성"이라 주장했지만 생성기가 없어 grounding.py 의 tier 정정
(eigentrust_alpha / ece_bins → policy_in_scale, ucb_c → literature)이 문서에 반영 안 됨
= doc↔code drift (audit quant-fidelity finding 2026-06-18). 이 스크립트가 그 주장을 참으로 만든다.

  python scripts/gen_quantitative_grounding.py        # 재생성 (덮어쓰기)
  python scripts/gen_quantitative_grounding.py --check # drift 시 exit 1 (CI 가드)

데이터 섹션(tier 요약/척도 표/상수 표/인용)은 grounding.py 에서 도출, 산문 섹션(헤더/검증/
나생문 이력)은 이 생성기의 템플릿. # KG: span_lakatotree_grounding
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lakatos.grounding import (  # noqa: E402
    GROUNDED, SOURCES, JEFFREYS_BANDS, KASS_RAFTERY_BANDS_2LN, COHEN_D_BANDS,
    grounding_tiers,
)

DOC = ROOT / "docs" / "QUANTITATIVE_GROUNDING.md"


def _fmt_val(v) -> str:
    if isinstance(v, dict):
        return "(realm/action dict — 본문 grounding.py 참조)"
    if isinstance(v, float):
        return f"{v:.4g}"
    return str(v)


def _tier_summary() -> str:
    tiers = grounding_tiers()
    order = ["literature", "policy_in_scale", "policy"]
    lines = []
    for t in order:
        ks = sorted(tiers.get(t, []))
        lines.append(f"- **{t}** ({len(ks)}): " + ", ".join(f"`{k}`" for k in ks))
    return "\n".join(lines)


def _band_table(bands, col: str) -> str:
    rows = [f"| {col} 하한 | 등급 |", "|---|---|"]
    for lo, lbl in sorted(bands, key=lambda x: x[0]):
        rows.append(f"| {lo:.3f} | {lbl} |")
    return "\n".join(rows)


def _constants_table() -> str:
    rows = ["| 상수 | 값 | tier | 출처 | 밴드 | 근거(요약) |", "|---|---|---|---|---|---|"]
    for k, g in GROUNDED.items():
        rationale = g.get("rationale", "").replace("\n", " ")
        if len(rationale) > 90:
            rationale = rationale[:90]
        band = g.get("band", "").replace("\n", " ")
        rows.append(f"| `{k}` | {_fmt_val(g['value'])} | {g['tier']} | {g['source']} | {band} | {rationale} |")
    return "\n".join(rows)


def _citations() -> str:
    used = sorted({g["source"] for g in GROUNDED.values()} | {"policy"})
    return "\n".join(f"- **{s}**: {SOURCES.get(s, s)}" for s in used)


def render() -> str:
    return f"""# 라카토트리 정량 점수 기반 지식 (Quantitative Grounding)

> 사용자(2026-06-12): **"야매로 점수주는 게 아니라 기반 지식이 풍부하게 있는 기반으로 정확하게 점수를 매겨야"**.
> 정본 = `lakatos/grounding.py` (이 문서는 거기서 `scripts/gen_quantitative_grounding.py` 로 자동생성, 직접 편집 금지).

> ★**정직성(tier)**: 척도/방법이 문헌 근거인 것과 특정 *값*이 정책 선택인 것을 구분한다 — 가짜 정밀(역산값을 derivation 인 척) 금지.
> - `literature` = 값이 문헌서 직접 · `policy_in_scale` = 값은 정책이나 문헌 척도 위 해석 · `policy` = 순수 엔지니어링(영감만 문헌)

## tier 별 정직성 요약

{_tier_summary()}

## 해석 척도 (raw 점수 → 문헌 등급)

### Bayes factor — Jeffreys (1961), 밴드=10^(k/2)
{_band_table(JEFFREYS_BANDS, "BF")}

### Bayes factor — Kass & Raftery (1995), 2·ln(BF) — ★원전 최상=very_strong (decisive 없음=Jeffreys 전용)
{_band_table(KASS_RAFTERY_BANDS_2LN, "2·ln(BF)")}

### 효과크기 — Cohen (1988)
{_band_table(COHEN_D_BANDS, "d")}

## Grounded 상수 정본

{_constants_table()}

## 문헌 정본 (citations)

{_citations()}

## 검증 (상계 WebSearch + 계산, 2026-06-12 / 재확증 2026-06-14)

- Jeffreys 밴드 = 10^(k/2): 3.162/10/31.623/100 ✓ | KR 2ln(BF){{2,6,10}}→BF{{2.72,20.1,148}} ✓
- Wald SPRT α=β=0.05 → ln경계 ±2.944 (α+β<1 필수, 아니면 역전) ✓
- Wilson 95% 하한: 10/10=0.722, 9/9=0.701(NOBEL 실효 통과선), 8/8=0.676(탈락), 3/3=0.438 ✓
- ★2026-06-14 정정: eigentrust_alpha(=1−0.85 teleport)·ece_bins(Guo 원전 M=15) → `policy_in_scale` 강등
  (방법은 문헌, 값은 정책). 이 생성기가 grounding.py 정본을 그대로 반영하므로 doc↔code drift 불가.

## 나생문 적대검증 이력 (정직성)

- grounding-fidelity 3렌즈(문헌충실/수학/정직성) 13 confirmed → 전부 수정: tier 도입(정책값 정직표시), _band_label 순서무관, SPRT α+β 검증, NOBEL 실효최소 9 명시, 고아 인용 제거(laudan1977/guo2017/policy 등록).
- 역산 가짜정밀 철회: abandon_k '0.98 nat'(실제 BF rejected=−1.79), weight_floor '0.3=Jeffreys'(실제 정책), bf=6.0 'geom center'(실제 정책).

> 엄격도 스택: Popper(judge 이산) > Bayes(연속신뢰도) > Laudan(문제수지). 점수는 이 척도로만 해석.
"""


def main() -> int:
    new = render()
    if "--check" in sys.argv:
        cur = DOC.read_text(encoding="utf-8") if DOC.exists() else ""
        if cur != new:
            print("DRIFT: docs/QUANTITATIVE_GROUNDING.md != grounding.py — 재생성 필요")
            return 1
        print("OK: 문서가 grounding.py 와 동기")
        return 0
    DOC.write_text(new, encoding="utf-8")
    print(f"WROTE {DOC.relative_to(ROOT)} ({len(new)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
