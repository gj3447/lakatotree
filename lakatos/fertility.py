"""이론 발전성(predictive fertility) — 라카토스/과학의 핵심 판정 기준.

"과학은 이론적 기반으로 얼마나 예측을 잘 하는가"(novel fact prediction)로 판단된다.
땜빵(사후 설명)과 달리 진보는 **새 사실을 미리 맞힌다**. 이게 노벨상의 본질.
라카토트리는 사전등록 novel 예측의 적중 track record 를 정량화한다.

발전성 = 적중한 novel 예측 / 등록한 novel 예측 (사전등록이므로 사후 HARKing 불가).
노벨급 = 충분한 예측 수 AND 높은 적중률 (운 좋은 1방 배제).
# KG: span_lakatotree_fertility
"""

NOBEL_MIN_PREDICTIONS = 3   # 표본 하한 (1방 행운 배제)
NOBEL_MIN_HITRATE = 0.7     # 적중률 하한


def predictive_fertility(nodes: list) -> dict:
    """가지/트리의 novel 예측 발전성. nodes = 노드 dict 리스트."""
    registered = sum(1 for r in nodes if r.get('novel_registered'))
    confirmed = sum(1 for r in nodes if r.get('novel_registered') and r.get('novel_confirmed'))
    fert = round(confirmed / registered, 3) if registered else 0.0
    return dict(registered=registered, confirmed=confirmed, fertility=fert)


def nobel_grade(fert: dict) -> bool:
    """노벨급 = 예측 수 충분 ∧ 적중률 높음 (이론 발전성의 강한 증거)."""
    return fert['registered'] >= NOBEL_MIN_PREDICTIONS and fert['fertility'] >= NOBEL_MIN_HITRATE
