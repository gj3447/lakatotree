"""트리 지표 TDD — 합성 나무로 진보율/기각률/퇴행깊이/라우든 alert.
# KG: span_lakatotree_S1_laudan_layer
"""
from lakatos.metrics import tree_metrics

NODES = [
 dict(tag='root', verdict='canonical_stage', parent=None, metric_value=1.0, metric_scope='s',
      algorithm='a', comment='c', limitation='l'),
 dict(tag='good', verdict='CANONICAL', parent='root', metric_value=0.5, metric_scope='s',
      algorithm='a', comment='c', limitation='l'),
 dict(tag='bad1', verdict='rejected', parent='good', metric_value=0.9, metric_scope='s',
      algorithm='a', comment='c', limitation='l'),
 dict(tag='bad2', verdict='rejected', parent='bad1', metric_value=0.95, metric_scope='s',
      algorithm='a', comment='c', limitation='l'),
 dict(tag='bad3', verdict='rejected', parent='bad2', metric_value=0.99, metric_scope='s',
      algorithm='a', comment='c', limitation='l'),
]
FRONTIER = [dict(name='q1', status='OPEN', body=''), dict(name='q2', status='CLOSED', body='')]

def test_basic_metrics():
    m = tree_metrics(NODES, FRONTIER)
    assert m['canonical'] == 'good'
    assert m['progress']['improvement_pct'] == 50.0
    assert m['rejection_ratio'] == 0.6
    assert m['annotation_coverage'] == 1.0

def test_degeneration_alert_fires_at_3():
    m = tree_metrics(NODES, FRONTIER)
    assert m['max_degeneration_depth'] == 3
    assert any('퇴행' in a for a in m['alerts'])

def test_laudan_section():
    m = tree_metrics(NODES, FRONTIER)
    assert m['laudan']['frontier_balance'] == 0   # closed 1 − open 1 ... 정의: closed−opened(OPEN)
    assert 'abandon_candidates' in m['laudan']
    # bad 가지: 연속 비진보 3 → 폐기 후보
    assert any(c['leaf'] == 'bad3' for c in m['laudan']['abandon_candidates'])


# === 적대 검증 BLOCKER 회귀 — F-FG-3 사이클 가드 ===
def test_parent_cycle_does_not_hang():
    cyc = [
        dict(tag='c1', verdict='CANONICAL', parent='c2', metric_value=0.5, metric_scope='s',
             algorithm='a', comment='c', limitation='l'),
        dict(tag='c2', verdict='canonical_stage', parent='c1', metric_value=1.0, metric_scope='s',
             algorithm='a', comment='c', limitation='l'),
    ]
    m = tree_metrics(cyc, [])   # 무한루프면 여기서 hang — 가드 있으면 즉시 반환
    assert m['canonical'] == 'c1'
