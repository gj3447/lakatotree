"""탐색배분 층 — 다음 어느 가지/질문을 확장할지 (frontier 우선순위).

이론: Multi-armed bandit UCB1 + Value of Information (Howard 1966).
arm = OpenQuestion/가지, reward = progressive 적중. 탐색(미탐색 질문)과
착취(고신뢰 질문)의 트레이드오프를 점수로 정렬 → directions 엔드포인트 승격.
한계(gap6): reward=progressive 적중이 novel 채점(corroboration)에 의존 — 채점 신뢰성 선결.
# KG: span_lakatotree_explore
"""
import math

UCB_C = 1.414   # 탐색계수 √2 (UCB1 표준)


def ucb_score(credence: float, n_visits: int, total_visits: int, c: float = UCB_C) -> float:
    """UCB1: 착취(credence) + 탐색(√(ln N / n)). 덜 본 질문에 보너스."""
    n = max(n_visits, 1)
    total = max(total_visits, 1)
    return credence + c * math.sqrt(math.log(total + 1) / n)


def voi(expected_gain: float, cost: float, floor: float = 1e-6) -> float:
    """Value of Information ≈ 기대 진보이득 / 검증비용 (SKILL.md '가치' 정량화)."""
    return max(expected_gain, 0.0) / max(cost, floor)


def rank_questions(questions: list, total_visits: int) -> list:
    """frontier 질문을 VoI×UCB 합성점수로 정렬. 각 항목에 voi/ucb/priority 부여."""
    out = []
    for q in questions:
        v = voi(q.get('expected_gain', 0.0), q.get('cost', 1.0))
        u = ucb_score(q.get('credence', 0.5), q.get('n_visits', 1), total_visits)
        out.append({**q, 'voi': round(v, 4), 'ucb': round(u, 4),
                    'priority': round(v * u, 4)})
    return sorted(out, key=lambda x: -x['priority'])
