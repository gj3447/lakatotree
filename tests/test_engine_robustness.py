"""엔진 하드닝 — 순수모듈 엣지케이스 + 층간 자기일관성.
# KG: span_lakatotree_engine_hardening
"""
import pytest
from lakatos.verdict.judge import Prediction, NovelTarget, judge
from lakatos.quant.bayes import branch_credence, bayes_factor
from lakatos.quant.metrics import tree_metrics
from lakatos.quant.fertility import predictive_fertility
from lakatos.programme.explore import rank_questions

# --- judge 엣지 ---
def test_judge_inf_baseline_refused():
    with pytest.raises(ValueError):
        Prediction(metric_name='m', direction='lower', baseline_value=float('inf'))

def test_judge_bad_direction_refused():
    with pytest.raises(ValueError):
        Prediction(metric_name='m', direction='sideways', baseline_value=1.0)

def test_novel_target_boundary_inclusive():
    # threshold 정확히 같으면 적중(≥/≤ inclusive)
    assert NovelTarget('m', 'higher', 0.5).corroborated(0.5)
    assert NovelTarget('m', 'lower', 0.5).corroborated(0.5)

# --- bayes 단조/경계 ---
def test_bayes_factor_equivalent_is_one():
    assert bayes_factor('equivalent', 5.0, 0.01) == 1.0

def test_bayes_unknown_verdict_neutral():
    assert bayes_factor('weird', 1.0, 0.01) == 1.0   # 미지 판결 = 무정보

def test_credence_bounded_0_1():
    seq = [{'verdict': 'progressive', 'delta': -10, 'noise_band': 0.001}] * 20
    c = branch_credence(seq)
    assert 0.0 < c < 1.0   # 폭주해도 확률 경계 유지

# --- metrics 엣지 ---
def test_empty_tree_no_crash():
    m = tree_metrics([], [])
    assert m['nodes'] == 0 and m['canonical'] is None and m['fertility']['fertility'] == 0.0

def test_no_canonical_no_crash():
    nodes = [dict(tag='a', verdict='proof', parent=None, algorithm='x', comment='x', limitation='x')]
    m = tree_metrics(nodes, [])
    assert m['canonical'] is None and m['canonical_path'] == []

def test_multi_parent_node_no_crash():
    # 한 노드가 dict 중복(같은 tag) → by 맵이 하나로 수렴, 크래시 없음
    nodes = [dict(tag='a', verdict='CANONICAL', parent=None, algorithm='x', comment='x', limitation='x'),
             dict(tag='a', verdict='CANONICAL', parent=None, algorithm='x', comment='x', limitation='x')]
    m = tree_metrics(nodes, [])
    assert m['canonical'] == 'a'

# --- explore 엣지 ---
def test_rank_empty_questions():
    assert rank_questions([], total_visits=0) == []

def test_rank_zero_visits_no_div_error():
    r = rank_questions([dict(name='q', expected_gain=0.1, cost=1.0, credence=0.5, n_visits=0)], total_visits=0)
    assert r[0]['ucb'] > 0   # n_visits=0, total=0 가드

# --- 층간 자기일관성 ---
def test_layers_consistent_on_strong_branch():
    """강한 가지: 베이즈 신뢰도 높음 ∧ 발전성 높음 ∧ 퇴행깊이 0."""
    nodes = [dict(tag=f'n{i}', verdict='CANONICAL' if i == 2 else 'progressive',
                  parent=(f'n{i-1}' if i else None), metric_value=10 - i, metric_scope='s',
                  algorithm='x', comment='x', limitation='x',
                  novel_registered=True, novel_confirmed=True) for i in range(3)]
    m = tree_metrics(nodes, [])
    assert m['bayes']['canonical_credence'] > 0.5
    assert m['fertility']['fertility'] == 1.0
    assert m['max_degeneration_depth'] == 0
