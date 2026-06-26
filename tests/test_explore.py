"""탐색배분 TDD — bandit UCB + VoI 로 frontier 질문 우선순위.
# KG: span_lakatotree_explore
"""
from lakatos.programme.explore import ucb_score, voi, rank_questions

def test_ucb_unexplored_bonus():
    # 같은 신뢰도면 덜 탐색된 질문이 높다 (탐색 보너스)
    a = ucb_score(credence=0.5, n_visits=1, total_visits=100)
    b = ucb_score(credence=0.5, n_visits=50, total_visits=100)
    assert a > b

def test_voi_gain_over_cost():
    assert voi(expected_gain=0.2, cost=1.0) > voi(expected_gain=0.2, cost=4.0)
    assert voi(expected_gain=0.0, cost=1.0) == 0.0

def test_rank_orders_by_priority():
    qs = [dict(name='cheap_high', expected_gain=0.3, cost=1.0, credence=0.6, n_visits=1),
          dict(name='expensive_low', expected_gain=0.05, cost=5.0, credence=0.3, n_visits=10)]
    ranked = rank_questions(qs, total_visits=20)
    assert ranked[0]['name'] == 'cheap_high'
    assert 'voi' in ranked[0] and 'ucb' in ranked[0] and 'priority' in ranked[0]

def test_crisis_widens_exploration():
    # Kuhn 위기(incumbent 퇴행) = 가설공간 확장 신호 → UCB 탐색항을 넓혀 덜 본 질문 정찰 강화(라이선스 kuhn1962)
    qs = [dict(name='q', expected_gain=0.2, cost=1.0, credence=0.5, n_visits=1)]
    normal = rank_questions(qs, total_visits=50, crisis=False)[0]['ucb']
    crisis = rank_questions(qs, total_visits=50, crisis=True)[0]['ucb']
    assert crisis > normal   # 위기 시 탐색항 확대(가설공간 확장)
