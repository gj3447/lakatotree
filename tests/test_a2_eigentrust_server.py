"""A2 server-feed: 프로덕션 read-model 이 eigentrust 글로벌 신뢰 맵을 *관측에서 구성*해 credence 로 주입.

per-node source_trust float 은 prom A 에서 live. 이건 그 위 글로벌 그래프 신뢰: TreeKgRepository.load_tree_data
(프로덕션 경로·유일 정본, D1 감사 2026-06-26)가 노드의 internet 관측 source(url|source_type)를 노드에 부착 +
관측 리스트 방출 → compute_tree_metrics 가 trust.global_source_trust 로 맵 구성 → tree_metrics cfg →
branch_credence 가 노드 source 를 글로벌 신뢰로 가중(노드 source 부재면 trust_coverage 로 정직 노출, 조용히
1.0 스냅 금지). 실DB 영수증은 통합티어 참조.
"""
import json

from server.contexts.tree.repository import TreeKgRepository
from server.read_models import compute_tree_metrics


def load_tree_data(name, *, kg):
    """프로덕션 경로 그대로: 서비스가 쓰는 TreeKgRepository 를 통해 읽는다(죽은 read_models 사본 제거 후)."""
    return TreeKgRepository(kg).load_tree_data(name)


def _kg(nodes_rows, obs_rows):
    def kg(q, **kw):
        if 'RETURN t.title' in q:
            return [dict(title='T', hard_core='', frontier_rule='', doc='',
                         coverage_backlog=[], coverage_statement='')]
        if 'HAS_RESEARCH_EVENT' in q:
            return obs_rows
        if 'HAS_FRONTIER' in q:
            return []
        if 'HAS_NODE' in q:
            return nodes_rows
        return []
    return kg


def test_load_tree_data_attaches_node_source_and_emits_observations():
    nodes = [dict(tag='root', verdict='canonical_stage', parent=None),
             dict(tag='p1', verdict='progressive', parent='root')]
    obs = [dict(node='p1', payload=json.dumps(
        {'url': 'http://blog.x/a', 'source_type': 'blog', 'corroboration_score': 0.4}))]
    td = load_tree_data('T', kg=_kg(nodes, obs))
    by = {r['tag']: r for r in td['nodes']}
    assert by['p1']['source'] == 'http://blog.x/a'           # 노드에 source(url|source_type) 부착
    assert td['observations'] and td['observations'][0]['source'] == 'http://blog.x/a'


def test_compute_tree_metrics_builds_and_feeds_eigentrust_map():
    nodes = [
        dict(tag='root', verdict='canonical_stage', parent=None, metric_value=1.0, metric_scope='s'),
        dict(tag='p1', verdict='progressive', parent='root', metric_value=0.5, metric_scope='s',
             pred_baseline=1.0, pred_noise_band=0.02, pred_closes='q1', source='peer://a'),
        dict(tag='top', verdict='CANONICAL', parent='p1', metric_value=0.4, metric_scope='s'),
    ]
    obs = [dict(source='peer://a', source_type='peer_reviewed', node='p1', corroboration_score=0.9)]
    m = compute_tree_metrics(dict(name='T', nodes=nodes, frontier=[], observations=obs))
    tc = m['bayes']['trust_coverage']
    assert tc['map_supplied'] is True                        # 관측→맵 구성·주입됨
    assert tc['path_sources_matched'] >= 1                   # 노드 source 가 맵에 매칭(조용히 1.0 아님)
    assert tc['mode'] in ('graph_propagated', 'seed_dominated', 'uniform_unlearned')


def test_compute_tree_metrics_without_observations_is_legacy():
    nodes = [dict(tag='root', verdict='canonical_stage', parent=None, metric_value=1.0, metric_scope='s'),
             dict(tag='top', verdict='CANONICAL', parent='root', metric_value=0.4, metric_scope='s')]
    m = compute_tree_metrics(dict(name='T', nodes=nodes, frontier=[]))
    assert m['bayes']['trust_coverage']['map_supplied'] is False   # 맵 없음 = 레거시 동작
