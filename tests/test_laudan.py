"""라우든 정량층 TDD — 문제해결력 수지 + 폐기 타이밍 명문규칙 (라카토스 한계 보완).
# KG: span_lakatotree_S1_laudan_layer
"""
from lakatos.laudan import problem_balance, psr, branch_score, should_abandon

def test_problem_balance():
    assert problem_balance(closed=3, opened=1) == 2
    assert problem_balance(closed=0, opened=4) == -4

def test_psr():
    assert psr(closed=2, path_nodes=4) == 0.5
    assert psr(closed=0, path_nodes=0) == 0.0

def test_branch_score_comparative():
    # 비교 문제해결력: metric 개선 + 문제 수지 — 경쟁 가지 서열화
    a = branch_score(metric_improvement_pct=27.3, closed=1, opened=2)
    b = branch_score(metric_improvement_pct=0.0, closed=0, opened=3)
    assert a > b

def test_abandon_rule1_consecutive_nonprogressive():
    ok, reason = should_abandon(consecutive_nonprogressive=3, nodes_spent=1,
                                prediction_hits=1, problem_balance_windowed=0)
    assert ok and '연속 비진보' in reason
    ok, _ = should_abandon(consecutive_nonprogressive=2, nodes_spent=1,
                           prediction_hits=1, problem_balance_windowed=0)
    assert not ok

def test_abandon_rule2_budget_without_hit():
    ok, reason = should_abandon(consecutive_nonprogressive=0, nodes_spent=5,
                                prediction_hits=0, problem_balance_windowed=0)
    assert ok and '예산' in reason
    ok, _ = should_abandon(consecutive_nonprogressive=0, nodes_spent=5,
                           prediction_hits=1, problem_balance_windowed=0)
    assert not ok   # 적중이 하나라도 있으면 살린다 (라카토스의 관용, 단 유한)

def test_abandon_rule3_problem_balance():
    ok, reason = should_abandon(consecutive_nonprogressive=0, nodes_spent=1,
                                prediction_hits=1, problem_balance_windowed=-2)
    assert ok and '수지' in reason
