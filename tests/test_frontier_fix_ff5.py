"""FF5 guard (frontier-fix 2026-06-26): eigentrust 출처신뢰 가중이 *서빙 /metrics 경로에서 살아있다*(D1 이 닫음).

deep-dive FF5: README 의 'eigentrust 가중 credence'가 서빙 경로에서 死였다 — load_tree_data 가 observations 를
안 만들고, 채우는 read_models 사본은 orphan(비테스트 호출자 0)이라 A2 통합테스트만 green, 실 /metrics 는 inert.
D1(2026-06-26)이 프로덕션 TreeKgRepository.load_tree_data 로 통합: observations 방출 + 노드 source 부착 →
compute_tree_metrics 가 trust.global_source_trust 로 맵 구성·주입 → branch_credence 가 노드 source 가중.

verify-only(D1 코드 편집 아님): 서빙 경로가 (1) observations 방출(死 아님), (2) eigentrust 맵 구성·주입·매칭
함을 검증. 관측 없으면 맵 미구성(레거시·failsafe: 주장 없는 경로에 trust fabricate 안 함, 조용한 1.0-snap 금지).
두 가드 green 착륙 시 examples/frontier_fix_20260626_programme.py 가 FF5 를 progressive 로 자동 채점.
# KG: LakatosTree_FrontierFix_20260626 / FF5_eigentrust_dead_failopen_trust
"""
from __future__ import annotations

import json

from server.contexts.tree.repository import TreeKgRepository
from server.read_models import compute_tree_metrics


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


def test_tree_service_loads_observations_and_defaults_failsafe():
    """서빙 로더(TreeKgRepository.load_tree_data)가 observations 를 방출 + 노드 source 부착(D1) — 死 아님.
    관측 없으면 맵 미구성(레거시·failsafe: 주장 없는 경로에 trust 를 조용히 1.0 으로 fabricate 안 함)."""
    nodes = [dict(tag='root', verdict='canonical_stage', parent=None),
             dict(tag='p1', verdict='progressive', parent='root')]
    obs = [dict(node='p1', payload=json.dumps(
        {'url': 'http://blog.x/a', 'source_type': 'blog', 'corroboration_score': 0.4}))]
    td = TreeKgRepository(_kg(nodes, obs)).load_tree_data('T')
    assert td.get('observations'), '서빙 로더가 observations 미방출 = eigentrust 死(FF5 미수정)'
    assert {r['tag']: r for r in td['nodes']}['p1'].get('source') == 'http://blog.x/a'
    # 관측 없음 → 맵 미구성(레거시) — fail-open 1.0-snap 이 아니라 정직한 미가중
    m0 = compute_tree_metrics(dict(name='T', frontier=[], nodes=[
        dict(tag='root', verdict='canonical_stage', parent=None, metric_value=1.0, metric_scope='s'),
        dict(tag='top', verdict='CANONICAL', parent='root', metric_value=0.4, metric_scope='s')]))
    assert m0['bayes']['trust_coverage']['map_supplied'] is False


def test_served_metrics_path_downweights_low_trust_source():
    """서빙 compute_tree_metrics 가 관측에서 eigentrust 글로벌 신뢰 맵을 *구성·주입*해 경로 source 를 가중한다
    (deep-dive 가 지적한 '서빙 경로 死' 의 반증) — 경로 source 가 신뢰맵에 매칭(조용한 1.0-snap 아님)."""
    nodes = [
        dict(tag='root', verdict='canonical_stage', parent=None, metric_value=1.0, metric_scope='s'),
        dict(tag='p1', verdict='progressive', parent='root', metric_value=0.5, metric_scope='s',
             pred_baseline=1.0, pred_noise_band=0.02, pred_closes='q1', source='peer://a'),
        dict(tag='top', verdict='CANONICAL', parent='p1', metric_value=0.4, metric_scope='s'),
    ]
    obs = [dict(source='peer://a', source_type='peer_reviewed', node='p1', corroboration_score=0.9)]
    m = compute_tree_metrics(dict(name='T', nodes=nodes, frontier=[], observations=obs))
    tc = m['bayes']['trust_coverage']
    assert tc['map_supplied'] is True                    # 관측→맵 구성·주입(서빙 경로 死 아님)
    assert tc['path_sources_matched'] >= 1               # 경로 source 가 신뢰맵에 매칭(가중 적용, 1.0-snap 아님)
