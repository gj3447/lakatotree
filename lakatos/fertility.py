"""이론 발전성(predictive fertility) — 라카토스/과학의 핵심 판정 기준.

"과학은 이론적 기반으로 얼마나 예측을 잘 하는가"(novel fact prediction)로 판단된다.
땜빵(사후 설명)과 달리 진보는 **새 사실을 미리 맞힌다**. 이게 노벨상의 본질.
라카토트리는 사전등록 novel 예측의 적중 track record 를 정량화한다.

발전성 = 적중한 novel 예측 / 등록한 novel 예측 (사전등록이므로 사후 HARKing 불가).
노벨급 = 충분한 예측 수 AND 높은 적중률 (운 좋은 1방 배제).
# KG: span_lakatotree_fertility
"""

import math
NOBEL_MIN_PREDICTIONS = 3       # 표본 하한
NOBEL_MIN_HITRATE_LB = 0.7      # Wilson 95% 하한 (운 배제 — 10/10 이상서야 통과)


def _wilson_lower(k: int, n: int, z: float = 1.96) -> float:
    """Wilson 점수 95% 하한 — 작은 표본의 과신 방지(나생문 F-MATH-6)."""
    if n == 0:
        return 0.0
    phat = k / n
    denom = 1 + z * z / n
    centre = phat + z * z / (2 * n)
    margin = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))
    return max(0.0, (centre - margin) / denom)


def predictive_fertility(nodes: list) -> dict:
    """가지/트리의 novel 예측 발전성. nodes = 노드 dict 리스트."""
    registered = sum(1 for r in nodes if r.get('novel_registered'))
    confirmed = sum(1 for r in nodes if r.get('novel_registered') and r.get('novel_confirmed'))
    fert = round(confirmed / registered, 3) if registered else 0.0
    return dict(registered=registered, confirmed=confirmed, fertility=fert)


def nobel_grade(fert: dict) -> bool:
    """노벨급 = 예측 수 충분 ∧ Wilson 적중률 하한 ≥0.7 (운 좋은 소표본 배제, F-MATH-6)."""
    lb = _wilson_lower(fert['confirmed'], fert['registered'])
    return fert['registered'] >= NOBEL_MIN_PREDICTIONS and lb >= NOBEL_MIN_HITRATE_LB
