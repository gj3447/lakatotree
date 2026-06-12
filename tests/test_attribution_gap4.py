"""gap4 per-branch 질문귀속 — 라우든 규칙③ 부활 검증 (엔진 레벨)."""
from lakatos.laudan import branch_problem_balance_windowed
from lakatos.metrics import tree_metrics


def _node(tag, verdict='partial', questions=(), **kw):
    return dict(tag=tag, verdict=verdict, questions=list(questions),
                algorithm='a', comment='c', limitation='l',
                metric_value=kw.get('metric_value'), metric_scope=kw.get('scope'),
                parent=kw.get('parent'), parents=[kw['parent']] if kw.get('parent') else [],
                **{k: v for k, v in kw.items() if k.startswith('pred_') or k in ('metric_name', 'novel_registered', 'novel_confirmed')})


def test_branch_balance_counts_window_only():
    chain = [_node('leaf', questions=['q3', 'q4']),       # leaf 쪽
             _node('mid', questions=['q2']),
             _node('old', questions=['q0', 'q1'])]         # 윈도우 밖이어야 함 (window=2)
    frontier = [
        {'name': 'q2', 'status': 'CLOSED', 'closed_by': ['leaf']},   # 윈도우 안 닫음 → closed 1
        {'name': 'q3', 'status': 'OPEN', 'closed_by': None},
        {'name': 'q9', 'status': 'CLOSED', 'closed_by': ['old']},    # 윈도우 밖 닫음 → 미집계
    ]
    # window=2: opened = leaf 2 + mid 1 = 3, closed = 1 → 수지 -2
    assert branch_problem_balance_windowed(chain, frontier, window=2) == -2


def test_branch_balance_missing_attribution_is_zero_not_crash():
    chain = [_node('leaf')]
    frontier = [{'name': 'q', 'status': 'CLOSED'}]   # closed_by 미귀속 → 미집계 (정직)
    assert branch_problem_balance_windowed(chain, frontier) == 0


def test_rule3_fires_in_tree_metrics():
    """변명이 문제를 낳는 가지: 질문만 2개 열고 못 닫음 → 규칙③ 폐기 후보."""
    nodes = [
        _node('root', verdict='CANONICAL'),
        _node('excuse1', parent='root', questions=['qa']),
        _node('excuse2', parent='excuse1', questions=['qb']),
    ]
    frontier = [{'name': 'qa', 'status': 'OPEN', 'closed_by': None},
                {'name': 'qb', 'status': 'OPEN', 'closed_by': None}]
    m = tree_metrics(nodes, frontier)
    cands = {c['leaf']: c['reason'] for c in m['laudan']['abandon_candidates']}
    assert 'excuse2' in cands
    assert '문제 수지' in cands['excuse2']   # 규칙③이 발동 이유여야 (이전엔 항상 0이라 불가능)


def test_multiplicity_screen_in_tree_metrics():
    """같은 metric family 의 improved 2건 — 마진 개선은 BH 에서 떨어지고 경보가 뜬다."""
    nodes = [
        _node('root', verdict='CANONICAL'),
        _node('big', parent='root', verdict='partial', metric_name='p95', scope='s',
              metric_value=0.10, pred_baseline=0.50, pred_noise_band=0.1, pred_direction='lower'),
        _node('lucky', parent='root', verdict='partial', metric_name='p95', scope='s',
              metric_value=0.39, pred_baseline=0.50, pred_noise_band=0.1, pred_direction='lower'),
    ]
    m = tree_metrics(nodes, [])
    fam = m['multiplicity']['p95/s']
    assert fam['family_size'] == 2
    assert 'big' in fam['survivors_bh']
    assert 'lucky' not in fam['survivors_bh']
    assert any('다중비교 경보' in a for a in m['alerts'])


def test_multiplicity_absent_without_pred_fields():
    nodes = [_node('root', verdict='CANONICAL'), _node('a', parent='root')]
    m = tree_metrics(nodes, [])
    assert m['multiplicity'] == {}   # 구식 데이터 → 침묵 경보 없음 (하위호환)
