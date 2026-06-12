"""라우든 문제해결력 정량층 — 라카토스의 "판정 기준 애매" 한계 보완.

라우든: 과학의 목적 = 문제를 더 많이/잘/적은 부작용으로 해결.
여기서 문제 = OpenQuestion. 해결력 = 닫은 질문 − 새로 연 질문 + metric 개선.
폐기 타이밍 = 명문 규칙 3개 (라카토스가 못 준 시간표를 코드로 강제).
# KG: span_lakatotree_S1_laudan_layer
"""

ABANDON_K = 3        # 규칙①: 연속 비진보 노드 수
ABANDON_BUDGET = 5   # 규칙②: 예측 적중 0 인 채 소진 가능한 노드 예산
ABANDON_B = 2        # 규칙③: 허용 가능한 문제 수지 적자 (windowed)


def problem_balance(closed: int, opened: int) -> int:
    """문제 수지 = 닫은 질문 − 연 질문. 음수 = 변명이 문제를 낳는 중."""
    return closed - opened


def psr(closed: int, path_nodes: int) -> float:
    """problem-solving rate = 닫은 질문 / 정본경로 노드 수."""
    return closed / path_nodes if path_nodes else 0.0


def branch_score(metric_improvement_pct: float, closed: int, opened: int,
                 w_metric: float = 1.0, w_problem: float = 5.0) -> float:
    """비교 문제해결력 — 경쟁 가지 서열화 (라우든의 'rival 보다 생산적인가')."""
    return w_metric * metric_improvement_pct + w_problem * problem_balance(closed, opened)


def should_abandon(consecutive_nonprogressive: int, nodes_spent: int, prediction_hits: int,
                   problem_balance_windowed: int,
                   k: int = ABANDON_K, budget: int = ABANDON_BUDGET, b: int = ABANDON_B):
    """폐기 타이밍 명문 규칙 — '언제부터 퇴행인가'를 코드로 닫는다.

    ① 연속 비진보 ≥ k                  (땜빵의 연쇄)
    ② 노드 예산 소진 ∧ 예측 적중 0      (관용은 유한 — 적중 1이면 살린다)
    ③ 문제 수지 ≤ −b (window)          (변명이 문제를 낳는 속도가 해결을 추월)
    """
    if consecutive_nonprogressive >= k:
        return True, f'연속 비진보 {consecutive_nonprogressive} ≥ {k}'
    if nodes_spent >= budget and prediction_hits == 0:
        return True, f'예산 {budget}노드 소진, 예측 적중 0'
    if problem_balance_windowed <= -b:
        return True, f'문제 수지 {problem_balance_windowed} ≤ −{b}'
    return False, None
