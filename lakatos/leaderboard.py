"""경쟁 가지/프로그램 리더보드 — P2: 라우든의 'rival 보다 생산적인가'를 표로.

단일 합성점수 하나로 뭉개지 않는다 (가짜 정밀 금지). 3 기준을 따로 보이고:
  laudan_score : 문제해결력 (branch_score — metric% + 문제수지 가중)
  credence     : 베이즈 사후 신뢰도 (자산가중 생존력)
  fertility_lb : novel 적중률 Wilson 95% 하한 (이론 발전성 — Lakatos-Zahar 의 대체 기준)

집계는 두 겹:
  ① Pareto 지배: A 가 전 기준 ≥ ∧ 한 기준 > 이면 A dominates B — 논쟁 불가 서열.
  ② Borda count: 기준별 순위 합산 (Borda 1781) — Pareto 비교불능쌍의 *참고용* 전순서.
     Borda 는 정책 집계임을 정직 표기 (기준 가중이 동일하다는 선택).
# KG: span_lakatotree_leaderboard / P2
"""
from dataclasses import dataclass

from .bayes import branch_credence
from .fertility import predictive_fertility
from .grounding import wilson_lower_bound
from .laudan import branch_score

CRITERIA = ('laudan_score', 'credence', 'fertility_lb')


@dataclass(frozen=True)
class Competitor:
    """경쟁 단위 — 같은 트리의 가지일 수도, 트리(프로그램) 자체일 수도 있다."""
    name: str
    verdicts: list               # 시간순 판결 dict 리스트 (bayes 입력)
    nodes: list                  # novel_registered/confirmed 포함 노드 리스트 (fertility 입력)
    metric_improvement_pct: float
    closed: int
    opened: int


def score_competitor(c: Competitor) -> dict:
    fert = predictive_fertility(c.nodes)
    return {
        'name': c.name,
        'laudan_score': round(branch_score(c.metric_improvement_pct, c.closed, c.opened), 3),
        'credence': round(branch_credence(c.verdicts), 3),
        'fertility_lb': round(wilson_lower_bound(fert['confirmed'], fert['registered']), 3),
        'fertility_raw': fert,
    }


def dominates(a: dict, b: dict) -> bool:
    """Pareto 지배 — 전 기준 ≥ ∧ 한 기준이라도 >."""
    ge = all(a[k] >= b[k] for k in CRITERIA)
    gt = any(a[k] > b[k] for k in CRITERIA)
    return ge and gt


def leaderboard(competitors: list) -> dict:
    """리더보드 — 기준별 점수 + Pareto 지배관계 + Borda 집계.

    반환: {'rows': [...점수+borda+dominated_by...], 'pareto_front': [...],
           'note': 집계 정직성 문구}. rows 는 borda 내림차순.
    """
    scored = [score_competitor(c) for c in competitors]
    n = len(scored)
    # Borda: 기준별 순위(높을수록 좋음) → 점수 n-1..0 합산. 동점은 평균 순위 점수.
    borda = {s['name']: 0.0 for s in scored}
    for k in CRITERIA:
        ordered = sorted(scored, key=lambda s: s[k], reverse=True)
        i = 0
        while i < n:
            j = i
            while j + 1 < n and ordered[j + 1][k] == ordered[i][k]:
                j += 1
            pts = sum(n - 1 - r for r in range(i, j + 1)) / (j - i + 1)
            for r in range(i, j + 1):
                borda[ordered[r]['name']] += pts
            i = j + 1
    for s in scored:
        s['borda'] = round(borda[s['name']], 2)
        s['dominated_by'] = sorted(o['name'] for o in scored
                                   if o['name'] != s['name'] and dominates(o, s))
    front = sorted(s['name'] for s in scored if not s['dominated_by'])
    rows = sorted(scored, key=lambda s: s['borda'], reverse=True)
    return {
        'rows': rows,
        'pareto_front': front,
        'criteria': list(CRITERIA),
        'note': 'Pareto=논쟁불가 서열 / Borda=동일가중 정책 집계(참고용) — 단일점수 환원 금지',
    }
