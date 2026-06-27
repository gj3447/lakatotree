"""다중비교 보정 — gap8: 가지가 많으면 우연히 '진보'가 나온다 (false-progressive 율).

문제(THEORY §4 gap8): 판결은 점추정 비교(delta vs noise_band)다. 가지 1개면 괜찮지만
가지 20개를 같은 noise 에서 비교하면 보정 없이는 우연 통과가 기대상 1개꼴(α=0.05 기준).
"여러 가지 중 하나가 improved" 는 "그 가지가 진짜 improved" 보다 훨씬 약한 증거다.

해법: 같은 family(동일 metric/scope 의 improved 후보들)에 대해
  - Bonferroni (Dunn 1961): FWER 통제 — 하나라도 거짓양성일 확률 ≤ α. 보수적.
  - Benjamini-Hochberg (1995): FDR 통제 — 발견 중 거짓 비율 ≤ q. 탐색 연구 기본값.

정직 표기 3건:
  ① p 값은 noise_band 를 1σ 로 보는 *근사*다 — noise_band 는 분산 추정이 아니라
     판결 무차별 밴드(정책)라서, 이 매핑은 보수적 가정이지 도출이 아니다 (tier=policy).
  ② noise_band=0 인 판결은 검정 불가(p 정의 안 됨) → None 반환, 침묵 통과 금지.
  ③ 보정은 판결(judge)을 바꾸지 않는다 — 판결은 사전등록 단일비교 규약대로 서고,
     보정은 *나무 수준 경보*(이 중 몇 개가 우연인가)다. 권위 분리: judge=노드, 여기=family.
# KG: span_lakatotree_multiplicity / THEORY gap8
"""
import math
from dataclasses import dataclass

from lakatos.grounding import GROUNDED

FDR_Q = GROUNDED['fdr_q']['value']


def _phi(z: float) -> float:
    """표준정규 CDF (math.erf — 외부의존 0)."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def judgment_pvalue(delta: float, noise_band: float, direction: str) -> float | None:
    """단측 p — H0 '개선 없음' 하에서 이만한 delta 가 나올 확률. noise_band=1σ 근사(정직①).

    direction='lower' 면 delta<0 이 개선. noise_band=0 → None (검정 불가, 정직②).
    """
    if noise_band is None or noise_band <= 0 or not math.isfinite(delta):
        return None   # #3: 부재(None)·선언≤0 = 검정 척도 부재 → untestable(정직②)
    if direction not in ('lower', 'higher'):
        raise ValueError("direction 은 'lower'|'higher'")
    z = (-delta if direction == 'lower' else delta) / noise_band
    return 1.0 - _phi(z)


def bonferroni(pvals: list, alpha: float = FDR_Q) -> list:
    """FWER 통제 (Dunn 1961) — reject 플래그 리스트. None p 는 reject 불가."""
    m = sum(1 for p in pvals if p is not None)
    if m == 0:
        return [False] * len(pvals)
    return [(p is not None and p <= alpha / m) for p in pvals]


def benjamini_hochberg(pvals: list, q: float = FDR_Q) -> list:
    """FDR 통제 (BH 1995 step-up) — reject 플래그 리스트. None p 는 검정 불가=False."""
    indexed = [(p, i) for i, p in enumerate(pvals) if p is not None]
    m = len(indexed)
    out = [False] * len(pvals)
    if m == 0:
        return out
    indexed.sort()
    k_star = 0
    for rank, (p, _) in enumerate(indexed, start=1):
        if p <= q * rank / m:
            k_star = rank
    for rank, (_, i) in enumerate(indexed, start=1):
        if rank <= k_star:
            out[i] = True
    return out


@dataclass(frozen=True)
class MultiplicityReport:
    family_size: int             # 검정 가능했던 improved 후보 수
    untestable: tuple            # noise_band=0 등 검정 불가 tag 들 (침묵 금지)
    survivors_bh: tuple          # BH(FDR) 생존 tag
    survivors_bonferroni: tuple  # Bonferroni(FWER) 생존 tag
    q: float
    note: str = ('보정은 판결을 바꾸지 않는다 — family 수준 false-progressive 경보. '
                 'p 는 noise_band=1σ 근사(정책 가정)')


def false_progressive_screen(candidates: list, q: float = FDR_Q) -> MultiplicityReport:
    """improved 후보 family → 보정 후 생존자. candidates=[{tag, delta, noise_band, direction}].

    같은 family 로 묶는 책임은 호출자에 있다 (같은 metric/scope 끼리만 — 다른 측정을
    한 family 로 묶으면 보정이 과도/과소해진다).
    """
    pvals, untestable = [], []
    for c in candidates:
        p = judgment_pvalue(c['delta'], c.get('noise_band', 0.0), c.get('direction', 'lower'))
        pvals.append(p)
        if p is None:
            untestable.append(c['tag'])
    bh = benjamini_hochberg(pvals, q)
    bonf = bonferroni(pvals, q)
    return MultiplicityReport(
        family_size=sum(1 for p in pvals if p is not None),
        untestable=tuple(untestable),
        survivors_bh=tuple(c['tag'] for c, r in zip(candidates, bh) if r),
        survivors_bonferroni=tuple(c['tag'] for c, r in zip(candidates, bonf) if r),
        q=q)
