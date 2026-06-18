"""트리 지표 TDD — 합성 나무로 진보율/기각률/퇴행깊이/라우든 alert.
# KG: span_lakatotree_S1_laudan_layer
"""
from lakatos.quant.metrics import tree_metrics

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


def test_zero_first_metric_no_crash():
    """나생문 F-FG-8: 시작 metric=0(예: tests 0개)이어도 ZeroDivision 안 남."""
    nodes = [
        dict(tag='a', verdict='canonical_stage', parent=None, metric_value=0.0, metric_scope='s',
             algorithm='x', comment='x', limitation='x'),
        dict(tag='b', verdict='CANONICAL', parent='a', metric_value=26.0, metric_scope='s',
             algorithm='x', comment='x', limitation='x'),
    ]
    m = tree_metrics(nodes, [])
    assert m['progress']['improvement_pct'] is None
    assert m['progress']['abs_gain'] == 26.0


def test_metrics_accept_multi_parent_nodes_by_using_primary_parent_for_path():
    nodes = [
        dict(tag='root', verdict='canonical_stage', parents=[], metric_value=1.0, metric_scope='s',
             algorithm='x', comment='x', limitation='x'),
        dict(tag='side', verdict='proof', parents=[], metric_value=1.1, metric_scope='s',
             algorithm='x', comment='x', limitation='x'),
        dict(tag='best', verdict='CANONICAL', parents=['root', 'side'], metric_value=0.7,
             metric_scope='s', algorithm='x', comment='x', limitation='x'),
    ]
    m = tree_metrics(nodes, [])
    assert m['canonical_path'] == ['root', 'best']
    assert m['progress']['improvement_pct'] == 30.0


def test_coverage_backlog_is_reported_and_alerted():
    m = tree_metrics(NODES, FRONTIER, cfg={
        'coverage_backlog': ['unread/spec-a.md', 'unread/spec-b.md'],
        'coverage_statement': 'partial import, not exhaustive',
    })
    assert m['coverage']['backlog_count'] == 2
    assert m['coverage']['statement'] == 'partial import, not exhaustive'
    assert any('커버리지 backlog' in a for a in m['alerts'])


def test_improvement_pct_higher_is_better_direction():
    # ENG-HON-1: pred_direction='higher' 면 last>first 가 진보 (전엔 음수로 오보 + 가짜 정체경보)
    nodes = [
        dict(tag='root', verdict='progressive', parent=None, metric_value=0.60, metric_scope='m',
             pred_direction='higher', algorithm='a', comment='c', limitation='l'),
        dict(tag='best', verdict='CANONICAL', parent='root', metric_value=0.90, metric_scope='m',
             pred_direction='higher', algorithm='a', comment='c', limitation='l'),
    ]
    m = tree_metrics(nodes, [])
    assert m['progress']['improvement_pct'] == 50.0
    assert m['progress']['direction'] == 'higher'
    assert not any('정체' in a for a in m['alerts'])


def test_improvement_pct_lower_default_unchanged():
    m = tree_metrics(NODES, FRONTIER)
    assert m['progress']['improvement_pct'] == 50.0          # 기존 lower-is-better 회귀 0


def test_canonical_credence_dedups_repeated_same_question_LIVE():
    """use-novelty 상관보정 live 배선 실증: 정본 경로에서 같은 질문(pred_closes)을 반복 확증해도
    canonical_credence 가 부풀지 않는다(content-dedup). 전엔 같은 progressive 반복이 ~1.0 인위확신."""
    def chain(closes_pair):
        c1, c2 = closes_pair
        return [
            dict(tag='root', verdict='canonical_stage', parent=None, metric_value=1.0,
                 metric_scope='s', algorithm='a', comment='c', limitation='l'),
            dict(tag='p1', verdict='progressive', parent='root', metric_value=0.5, metric_scope='s',
                 pred_baseline=1.0, pred_noise_band=0.02, pred_closes=c1,
                 algorithm='a', comment='c', limitation='l'),
            dict(tag='p2', verdict='progressive', parent='p1', metric_value=0.4, metric_scope='s',
                 pred_baseline=1.0, pred_noise_band=0.02, pred_closes=c2,
                 algorithm='a', comment='c', limitation='l'),
            dict(tag='top', verdict='CANONICAL', parent='p2', metric_value=0.35, metric_scope='s',
                 algorithm='a', comment='c', limitation='l'),
        ]
    same = tree_metrics(chain(('q1', 'q1')), [])['bayes']['canonical_credence']    # 같은 질문 재확증
    diff = tree_metrics(chain(('q1', 'q2')), [])['bayes']['canonical_credence']    # 서로 다른 질문
    assert diff > same          # 새 예측 2개 = 독립증거 → 더 높은 신뢰 (use-novelty)
    assert 0.0 < same < 1.0     # 재확증은 인위확신 안 만듦


# ── SOLID 분해의 payoff: 각 지표 개념을 *독립*으로 테스트 (전엔 트리 통째로만 가능했음) ──────
from lakatos.quant.metrics import (
    _canonical_path, _progress_metric, _degeneration_depth, _multiplicity_screen, _coverage,
)


def _r(tag, verdict, parent=None, **kw):
    return dict(tag=tag, verdict=verdict, parent=parent, metric_scope='s', **kw)


def test_canonical_path_isolated():
    nodes = [_r('root', 'canonical_stage'), _r('a', 'progressive', 'root'), _r('c', 'CANONICAL', 'a')]
    by = {r['tag']: r for r in nodes}
    assert _canonical_path(nodes, by) == ['root', 'a', 'c']        # root→leaf


def test_progress_metric_isolated_direction_and_zero_guard():
    by = {'root': _r('root', 'canonical_stage', metric_value=2.0),
          'c': _r('c', 'CANONICAL', 'root', metric_value=1.0)}
    p = _progress_metric(['root', 'c'], by)
    assert p['improvement_pct'] == 50.0 and p['scope'] == 's'       # lower-is-better 2→1 = 50%
    byz = {'root': _r('root', 'canonical_stage', metric_value=0.0),
           'c': _r('c', 'CANONICAL', 'root', metric_value=3.0)}
    pz = _progress_metric(['root', 'c'], byz)
    assert pz['improvement_pct'] is None and pz['abs_gain'] == 3.0  # first=0 → 절대증가(ZeroDiv 가드)


def test_degeneration_depth_isolated():
    children = {'canon': [_r('d1', 'degenerating', 'canon')],
                'd1': [_r('d2', 'rejected', 'd1')]}
    assert _degeneration_depth(['canon'], children) == 2           # 2연속 비진보 자식 체인


def test_multiplicity_screen_isolated_only_families_of_2plus():
    one = [_r('a', 'progressive', metric_name='iou', metric_value=0.5, pred_baseline=1.0)]
    assert _multiplicity_screen(one) == {}                         # family 1개 = 다중비교 아님
    two = [_r('a', 'progressive', metric_name='iou', metric_value=0.5, pred_baseline=1.0),
           _r('b', 'progressive', metric_name='iou', metric_value=0.4, pred_baseline=1.0)]
    assert 'iou/s' in _multiplicity_screen(two)                    # family 2개 → 스크린


def test_coverage_isolated_backlog_blocks_exhaustive():
    assert _coverage({})['exhaustive'] is True
    assert _coverage({'coverage_backlog': ['x']})['exhaustive'] is False


# ── 바인딩이 드러낸 테스트 공백 메움: bound owner 8개 독립 테스트 (owner+test chain) ──────
from lakatos.quant.metrics import (
    _children_index, _verdict_seq, _branch_chain, _laudan_layer, _bayes_layer,
    _fertility_layer, _eureka_layer, _assemble_alerts,
)


def _mn(tag, verdict, parent=None, **kw):
    return dict(tag=tag, verdict=verdict, parent=parent, **kw)


def test_children_index_isolated():
    ci = _children_index([_mn('r', 'canonical_stage'), _mn('a', 'progressive', 'r'), _mn('b', 'rejected', 'r')])
    assert {c['tag'] for c in ci['r']} == {'a', 'b'}


def test_verdict_seq_isolated_delta_and_target():
    by = {'a': _mn('a', 'progressive', metric_value=0.5, pred_baseline=1.0, pred_noise_band=0.02, pred_closes='q1')}
    s = _verdict_seq(['a'], by)
    assert s[0]['delta'] == -0.5 and s[0]['target'] == 'q1'


def test_branch_chain_isolated_stops_at_path():
    by = {'leaf': _mn('leaf', 'rejected', 'mid'), 'mid': _mn('mid', 'rejected', 'canon'), 'canon': _mn('canon', 'CANONICAL')}
    assert [r['tag'] for r in _branch_chain('leaf', ['canon'], by)] == ['leaf', 'mid']


def test_laudan_layer_isolated_balance():
    lay = _laudan_layer([_mn('canon', 'CANONICAL')], [], ['canon'], {'canon': _mn('canon', 'CANONICAL')}, [], 2, 5)
    assert lay['frontier_balance'] == 3 and 'abandon_candidates' in lay and 'psr' in lay


def test_bayes_layer_isolated_credence_bounded():
    by = {'canon': _mn('canon', 'progressive', metric_value=0.5, pred_baseline=1.0, pred_noise_band=0.02)}
    b = _bayes_layer(['canon'], by, [])
    assert 0 < b['canonical_credence'] < 1 and b['low_credence_branches'] == []


def test_fertility_layer_isolated_has_nobel_grade():
    by = {'c': _mn('c', 'progressive', novel_registered=True, novel_confirmed=True)}
    f = _fertility_layer(['c'], by, list(by.values()))
    assert 'nobel_grade' in f and 'note' in f


def test_eureka_layer_isolated_returns_dict():
    by = {'c': _mn('c', 'progressive', novel_registered=True, novel_confirmed=True)}
    assert isinstance(_eureka_layer(['c'], by, list(by.values())), dict)


def test_assemble_alerts_isolated_degeneration_then_clean():
    al = _assemble_alerts(stalled=3, prog=None, annotated=1, n=1, coverage_backlog=[], abandon=[], multiplicity={})
    assert any('퇴행' in a for a in al)
    assert _assemble_alerts(stalled=0, prog=None, annotated=1, n=1, coverage_backlog=[], abandon=[], multiplicity={}) == []
