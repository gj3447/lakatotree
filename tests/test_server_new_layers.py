"""신규 층 서버 계약 — stack/lifecycle/leaderboard/paradigm/certificate 엔드포인트.

DB는 monkeypatch 한 tree_data/kg/MONGO 포트로 대체 (test_server_contracts 동형).
"""
import importlib
import os

import pytest
from fastapi import HTTPException


def load_app():
    os.environ.setdefault('NEO4J_URI', 'bolt://localhost:7687')
    os.environ.setdefault('NEO4J_USER', 'neo4j')
    os.environ.setdefault('NEO4J_PASSWORD', 'test')
    return importlib.import_module('server.app')


def _node(tag, verdict, parent=None, **kw):
    return dict(tag=tag, verdict=verdict, parent=parent,
                parents=[parent] if parent else [], parent_edges=[],
                algorithm='a', comment='c', limitation='l',
                metric_name=kw.get('metric_name'), metric_value=kw.get('metric_value'),
                metric_scope=kw.get('scope', 's'),
                pred_baseline=kw.get('pred_baseline'), pred_noise_band=kw.get('pred_noise_band'),
                pred_direction=kw.get('pred_direction'),
                novel_registered=kw.get('novel_registered'),
                novel_confirmed=kw.get('novel_confirmed'),
                questions=kw.get('questions', []))


HEALTHY_TD = dict(
    name='T', title='T', hard_core=[], frontier_rule='', doc='',
    coverage_backlog=[], coverage_statement='',
    nodes=[
        _node('root', 'progressive', metric_name='p95', metric_value=0.4,
              pred_baseline=0.5, pred_noise_band=0.05, novel_registered=True, novel_confirmed=True),
        _node('mid', 'progressive', parent='root', metric_name='p95', metric_value=0.3,
              pred_baseline=0.4, pred_noise_band=0.05, novel_registered=True, novel_confirmed=True),
        _node('best', 'CANONICAL', parent='mid', metric_name='p95', metric_value=0.28),
    ],
    frontier=[dict(name='q1', status='CLOSED', body='', closed_by=['mid'])],
)

DYING_TD = dict(
    name='D', title='D', hard_core=[], frontier_rule='', doc='',
    coverage_backlog=[], coverage_statement='',
    nodes=[
        _node('root', 'CANONICAL'),
        _node('e1', 'rejected', parent='root', questions=['qa']),
        _node('e2', 'rejected', parent='e1', questions=['qb']),
        _node('e3', 'rejected', parent='e2', questions=['qc']),
    ],
    frontier=[dict(name=q, status='OPEN', body='', closed_by=None) for q in ('qa', 'qb', 'qc')],
)


def patch_tree(monkeypatch, app, mapping):
    monkeypatch.setattr(app, 'tree_data', lambda n: mapping[n])


def test_stack_view_healthy_branch_retains(monkeypatch):
    app = load_app()
    patch_tree(monkeypatch, app, {'T': HEALTHY_TD})
    out = app.stack_view('T')
    assert out['leaf'] == 'best'
    assert out['decision'] == 'retain'
    assert {v['layer'] for v in out['votes']} == {'popper', 'bayes', 'laudan'}


def test_stack_view_dying_branch_abandons_with_quorum(monkeypatch):
    app = load_app()
    patch_tree(monkeypatch, app, {'D': DYING_TD})
    out = app.stack_view('D', leaf='e3')
    assert out['decision'] == 'abandon'
    assert sum(1 for v in out['votes'] if v['vote'] == 'abandon') >= 2
    assert out['inputs']['problem_balance_windowed'] < 0   # gap4 귀속이 살아있음


def test_stack_view_unknown_leaf_404(monkeypatch):
    app = load_app()
    patch_tree(monkeypatch, app, {'T': HEALTHY_TD})
    with pytest.raises(HTTPException) as e:
        app.stack_view('T', leaf='ghost')
    assert e.value.status_code == 404


def test_lifecycle_view_extinct_only_via_stack(monkeypatch):
    app = load_app()
    patch_tree(monkeypatch, app, {'D': DYING_TD})
    out = app.lifecycle_view('D', leaf='e3')
    assert out['state'] == 'extinct'
    assert out['stack']['decision'] == 'abandon'


def test_leaderboard_view_ranks_and_requires_two(monkeypatch):
    app = load_app()
    patch_tree(monkeypatch, app, {'T': HEALTHY_TD, 'D': DYING_TD})
    out = app.leaderboard_view('T,D')
    assert out['rows'][0]['name'] == 'T'
    assert 'D' not in out['pareto_front']
    with pytest.raises(HTTPException):
        app.leaderboard_view('T')


class FakeCollection:
    def __init__(self):
        self.docs = []
    def insert_one(self, d):
        self.docs.append(d)
    def find(self, q):
        docs = [d for d in self.docs if d['key'] == q['key']]
        class _C:   # chainable cursor — sort(asc<0=desc)→limit→iterable (OPS-ROB-2 bounded find)
            def __init__(self, ds): self.ds = ds
            def sort(self, k, asc): self.ds = sorted(self.ds, key=lambda d: d[k], reverse=(asc < 0)); return self
            def limit(self, n): self.ds = self.ds[:n]; return self
            def __iter__(self): return iter(self.ds)
        return _C(docs)


class FakeMongo(dict):
    def __getitem__(self, k):
        if k not in self:
            super().__setitem__(k, FakeCollection())
        return super().get(k)


def test_paradigm_insufficient_snapshots_is_honest(monkeypatch):
    app = load_app()
    patch_tree(monkeypatch, app, {'T': HEALTHY_TD, 'D': DYING_TD})
    monkeypatch.setattr(app, 'MONGO', FakeMongo())
    out = app.paradigm_view(incumbent='D', rivals='T')
    assert out['snapshots'] == 0
    assert '축적 필요' in out['note']
    assert out['state'] in ('crisis', 'normal_science')   # 우세 증거 없으면 shift 금지


def test_paradigm_shift_after_sustained_snapshots(monkeypatch):
    app = load_app()
    patch_tree(monkeypatch, app, {'T': HEALTHY_TD, 'D': DYING_TD})
    mongo = FakeMongo()
    monkeypatch.setattr(app, 'MONGO', mongo)
    for i in range(3):                       # 윈도우 3 연속 우세 축적
        app.leaderboard_view('T,D', snapshot=True)
    out = app.paradigm_view(incumbent='D', rivals='T')
    assert out['state'] == 'shift_candidate'
    assert out['rival'] == 'T'
    assert out['requires_human_oracle'] is True


def test_certificate_assembles_five_gates(monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, 'kg', lambda q, **kw: [dict(
        verdict='progressive', vsrc='scripted', pm='p95',
        script='judges/x.py', sha='a' * 64, rp='out/final.json')])
    monkeypatch.setattr(app, '_reproducible_for_node', lambda n, t: True)
    monkeypatch.setattr(app, 'standing', lambda n, t: dict(
        stands=True, grounded_extension=['verdict:v22'], verdict='progressive'))
    monkeypatch.setattr(app, 'calibration', lambda n: dict(n=4))
    out = app.node_certificate('T', 'v22')
    assert out['certified'] is True
    assert [c['gate'] for c in out['checks']] == \
        ['preregistered', 'reproducible', 'stands', 'calibrated', 'grounded']


def test_certificate_blocks_without_lineage(monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, 'kg', lambda q, **kw: [dict(
        verdict='progressive', vsrc='scripted', pm='p95',
        script='judges/x.py', sha='a' * 64, rp='')])
    monkeypatch.setattr(app, '_reproducible_for_node', lambda n, t: None)   # 계보 미기록
    monkeypatch.setattr(app, 'standing', lambda n, t: dict(
        stands=True, grounded_extension=['verdict:v22'], verdict='progressive'))
    monkeypatch.setattr(app, 'calibration', lambda n: dict(n=4))
    out = app.node_certificate('T', 'v22')
    assert out['certified'] is False
    assert 'reproducible' in out['missing']
    assert any(a['gate'] == 'reproducible' for a in out['next_actions'])


def test_certificate_empty_script_does_not_thinly_pass_prereg(monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, 'kg', lambda q, **kw: [dict(
        verdict='progressive', vsrc='scripted', pm='p95', script='', sha=None, rp='out/x.json')])
    monkeypatch.setattr(app, '_reproducible_for_node', lambda n, t: True)
    monkeypatch.setattr(app, 'standing', lambda n, t: dict(
        stands=True, grounded_extension=['verdict:v22'], verdict='progressive'))
    monkeypatch.setattr(app, 'calibration', lambda n: dict(n=4))
    out = app.node_certificate('T', 'v22')
    prereg = next(c for c in out['checks'] if c['gate'] == 'preregistered')
    assert prereg['passed'] is False           # bare ':' 고무도장 우회 차단
    assert prereg['evidence_ref'] == ''
    assert 'preregistered' in out['missing']


def test_paradigm_bounds_mongo_find_to_50(monkeypatch):
    # 나생문 B5: paradigm 의 leaderboard_snapshots find 가 무제한이면 안 됨 — .limit(50) 고정
    app = load_app()
    captured = {}

    class _Cur:
        def __init__(self, ds): self.ds = ds
        def sort(self, k, asc): self.ds = sorted(self.ds, key=lambda d: d[k], reverse=(asc < 0)); return self
        def limit(self, n): captured['limit'] = n; self.ds = self.ds[:n]; return self
        def __iter__(self): return iter(self.ds)

    class _Coll:
        def __init__(self): self.docs = []
        def insert_one(self, d): self.docs.append(d)
        def find(self, q): return _Cur([d for d in self.docs if d['key'] == q['key']])

    class _M(dict):
        def __getitem__(self, k):
            if k not in self: super().__setitem__(k, _Coll())
            return super().get(k)

    m = _M()
    for i in range(60):                         # 60 스냅샷 적재 → 최신 50 만 로드돼야
        m['leaderboard_snapshots'].insert_one(dict(
            key='T,U', at=f'2026-06-14T00:00:{i:02d}',
            board={'rows': [{'name': 'T'}, {'name': 'U'}], 'pareto_front': []}))
    monkeypatch.setattr(app, 'MONGO', m)
    patch_tree(monkeypatch, app, {'T': HEALTHY_TD, 'U': HEALTHY_TD})
    app.paradigm_view(incumbent='T', rivals='U')
    assert captured['limit'] == 50              # 무제한 아님(전수 메모리 로드 차단)
