"""Cluster ③ — 대시보드가 신규 P2/P3 층을 실제로 표시하는지 (나생문 DASH-1/2/3).

전엔 진보율/기각률/퇴행/frontier/node tree 만 보였다. 이제 stack/lifecycle/bayes/fertility/
multiplicity + per-node 분석 링크 + 리더보드(>=2 트리)를 실 ASGI 렌더링으로 검증.
"""
import importlib
import os

from fastapi.testclient import TestClient


def load_app():
    os.environ.setdefault('NEO4J_URI', 'bolt://localhost:7687')
    os.environ.setdefault('NEO4J_USER', 'neo4j')
    os.environ.setdefault('NEO4J_PASSWORD', 'test')
    return importlib.import_module('server.app')


def _node(tag, verdict, parent=None, **kw):
    return dict(tag=tag, verdict=verdict, parent=parent, parents=[parent] if parent else [],
                parent_edges=[], algorithm='a', comment='c', limitation='l',
                metric_name=kw.get('mn'), metric_value=kw.get('mv'), metric_scope=kw.get('scope', 's'),
                pred_baseline=kw.get('pb'), pred_noise_band=kw.get('nb'), pred_direction=kw.get('pd'),
                novel_registered=kw.get('nr'), novel_confirmed=kw.get('nc'), questions=kw.get('qs', []))


HEALTHY = dict(
    name='T', title='T tree', hard_core=[], frontier_rule='', doc='',
    coverage_backlog=[], coverage_statement='',
    nodes=[
        _node('root', 'progressive', mn='p95', mv=0.4, pb=0.5, nb=0.05, nr=True, nc=True),
        _node('mid', 'progressive', parent='root', mn='p95', mv=0.3, pb=0.4, nb=0.05, nr=True, nc=True),
        _node('best', 'CANONICAL', parent='mid', mn='p95', mv=0.28),
    ],
    frontier=[dict(name='q1', status='OPEN', body='b', closed_by=None,
                   expected_gain=0.5, cost=1.0, n_visits=1)])


def test_dashboard_surfaces_new_layers(monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, 'trees', lambda: [{'name': 'T', 'title': 'T tree'}])
    monkeypatch.setattr(app, 'tree_data', lambda n: HEALTHY)
    r = TestClient(app.app).get('/')
    assert r.status_code == 200
    t = r.text
    assert '3층 스택' in t and 'lifecycle' in t            # stack + lifecycle 패널 (DASH-2)
    assert '베이즈 신뢰도' in t and '발전성' in t            # bayes + fertility (DASH-1)
    assert '/node/best/certificate' in t                   # per-node 분석 링크 (dead-end 해소)
    assert 'directions' in t                                # 다음-방향 흐름 링크


def test_dashboard_leaderboard_with_two_trees(monkeypatch):
    app = load_app()
    t2 = dict(HEALTHY, name='U', title='U tree')
    monkeypatch.setattr(app, 'trees', lambda: [{'name': 'T', 'title': 'T'}, {'name': 'U', 'title': 'U'}])
    monkeypatch.setattr(app, 'tree_data', lambda n: HEALTHY if n == 'T' else t2)
    r = TestClient(app.app).get('/')
    assert r.status_code == 200 and '리더보드' in r.text     # 경쟁 프로그램 비교(DASH)
