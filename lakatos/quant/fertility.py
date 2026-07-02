"""이론 발전성(predictive fertility) — 라카토스/과학의 핵심 판정 기준.

"과학은 이론적 기반으로 얼마나 예측을 잘 하는가"(novel fact prediction)로 판단된다.
땜빵(사후 설명)과 달리 진보는 **새 사실을 미리 맞힌다**. 이게 노벨상의 본질.
라카토트리는 사전등록 novel 예측의 적중 track record 를 정량화한다.

발전성 = 적중한 novel 예측 / 등록한 novel 예측 (사전등록이므로 사후 HARKing 불가).
노벨급 = 충분한 예측 수 AND 높은 적중률 (운 좋은 1방 배제).
# KG: span_lakatotree_fertility
라이선스(THEORY §8): mayo1996
"""

from lakatos.grounding import GROUNDED, wilson_lower_bound as _wilson_lower

NOBEL_MIN_PREDICTIONS = GROUNDED['nobel_min_predictions']['value']  # 표본 하한 (Wilson 유의 최소 n)
NOBEL_MIN_HITRATE_LB = GROUNDED['nobel_min_hitrate_lb']['value']    # Wilson 95% 하한 ≥0.7 (실효 통과선 ≈9/9, LB=0.701; T-H-2)


def predictive_fertility(nodes: list, *, scope: str = 'unscoped') -> dict:
    """가지/트리의 novel 예측 발전성. nodes = 노드 dict 리스트.

    G5(git-흡수 2026-07-02, read-model drift 봉합): fertility 는 표면마다 *다른 스코프*로 계산됐다 —
    tree_metrics 는 canonical-path, leaderboard 는 all-nodes — 같은 'fertility' 이름이 다른 의미를 나르는
    silent divergence(아키텍처 감사 유일 HIGH). git 의 '파생값은 동결 어휘로 한 곳에서 계산'(merge-ort
    conflict 어휘) 이식: scope 를 *명시 echo* 해 이름이 의미를 표류시키지 못하게 한다(다른 스코프=다른 라벨).
    표면 호출자는 반드시 scope 를 선언한다(test_git_absorption_g5 가 소스 스캔으로 강제).
    """
    registered = sum(1 for r in nodes if r.get('novel_registered'))
    confirmed = sum(1 for r in nodes if r.get('novel_registered') and r.get('novel_confirmed'))
    fert = round(confirmed / registered, 3) if registered else 0.0
    return dict(registered=registered, confirmed=confirmed, fertility=fert, scope=scope)


def nobel_grade(fert: dict) -> bool:
    """노벨급 = 예측 수 충분 ∧ Wilson 적중률 하한 ≥0.7 (운 좋은 소표본 배제, F-MATH-6)."""
    lb = _wilson_lower(fert['confirmed'], fert['registered'])
    return fert['registered'] >= NOBEL_MIN_PREDICTIONS and lb >= NOBEL_MIN_HITRATE_LB
