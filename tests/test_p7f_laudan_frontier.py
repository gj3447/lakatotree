"""P7-F: Laudan frontier 의미론 — closed_by 귀속 정확성 (TDD).

ENG-DU-5-branch-problem-balance: closed_by 는 '닫은 노드 tag' 여야 규칙③ per-branch 귀속이 산다.
비-노드 문자열로 닫으면 closed 미집계 → 가지 문제수지 과소계상(조용한 false-abandon).
unattributed_closures 로 이 미귀속을 가시화(정직 신호) + metrics 에 노출.
"""
from lakatos.quant.laudan import unattributed_closures, branch_problem_balance_windowed
from lakatos.quant.metrics import tree_metrics


def test_unattributed_closure_detected():
    node_tags = ['root', 'v22']
    frontier = [
        dict(name='qA', status='CLOSED', closed_by=['v22']),     # 노드 귀속 → OK
        dict(name='qB', status='CLOSED', closed_by=['alice']),   # 비-노드 → 미귀속
        dict(name='qC', status='CLOSED'),                        # closed_by 없음 → 미귀속
        dict(name='qD', status='OPEN', closed_by=['v22']),       # OPEN → 무시
    ]
    assert set(unattributed_closures(node_tags, frontier)) == {'qB', 'qC'}


def test_windowed_balance_counts_only_node_attributed():
    chain = [dict(tag='v22', questions=['qX'])]                   # opened 1
    node_close = [dict(name='qX', status='CLOSED', closed_by=['v22'])]
    assert branch_problem_balance_windowed(chain, node_close) == 0    # closed1 − opened1

    nonnode_close = [dict(name='qX', status='CLOSED', closed_by=['alice'])]
    assert branch_problem_balance_windowed(chain, nonnode_close) == -1   # 미집계 → 과소계상


def test_metrics_surfaces_unattributed_closed():
    nodes = [dict(tag='root', verdict='CANONICAL', parent=None, metric_value=1.0, metric_scope='s')]
    frontier = [dict(name='q2', status='CLOSED', body='')]       # closed_by 없음 = 미귀속
    m = tree_metrics(nodes, frontier)
    assert 'unattributed_closed' in m['laudan']
    assert 'q2' in m['laudan']['unattributed_closed']


def test_node_attributed_closure_not_flagged():
    nodes = [dict(tag='root', verdict='CANONICAL', parent=None, metric_value=1.0, metric_scope='s')]
    frontier = [dict(name='q2', status='CLOSED', closed_by=['root'])]
    m = tree_metrics(nodes, frontier)
    assert m['laudan']['unattributed_closed'] == []
