"""신규 층 서버 계약 — stack/lifecycle/leaderboard/paradigm/certificate 엔드포인트.

DB는 monkeypatch 한 tree_data/kg/MONGO 포트로 대체 (test_server_contracts 동형).
"""
import importlib
import os

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient


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


def test_series_view_diagnostic_only_over_canonical_path(monkeypatch):
    # #5: 고아였던 programme.series 에 런타임 read surface — 정본경로 verdict 시퀀스 진단(diagnostic_only)
    app = load_app()
    patch_tree(monkeypatch, app, {'T': HEALTHY_TD})
    out = app.series_view('T')
    assert out['leaf'] == 'best'
    assert out['authority'] == 'diagnostic_only' and out['promotion_authority'] is False
    assert out['trend'] == 'progressive' and out['progressive_count'] == 2  # CANONICAL leaf 는 진단축 밖 제외
    assert out['coverage']['conceptual_problem'] == 'not_projected_from_kg'  # overclaim 금지(정직 표기)


def test_directions_crisis_widens_on_degenerating_tree(monkeypatch):
    # #9 crisis→explore: 퇴행깊이 ≥ k(Kuhn 위기) → crisis_exploration True (UCB 탐색 폭 확대)
    app = load_app()
    patch_tree(monkeypatch, app, {'D': DYING_TD, 'T': HEALTHY_TD})
    assert app.directions('D')['crisis_exploration'] is True     # root→e1/e2/e3 rejected = 퇴행깊이 3
    assert app.directions('T')['crisis_exploration'] is False    # 건강한 정본경로


def test_prediction_in_carries_scale_type():
    # C(Stevens): PredictionIn 이 scale_type 을 운반해 judge.Prediction 가드를 reachable 하게(orphan 아님).
    from server.contexts.tree.schemas import PredictionIn
    p = PredictionIn(metric_name='rank', baseline_value=3.0, scale_type='ordinal', noise_band=0.0)
    assert p.scale_type == 'ordinal'
    assert PredictionIn(metric_name='m', baseline_value=1.0).scale_type == 'ratio'   # 기본 하위호환
    assert 'scale_type' in p.model_dump()   # register_prediction 가 **model_dump 로 KG(pred_scale_type)에 씀


# ── #① Laudan 연구전통 authoring + appraise + series bridge (diagnostic-only) ──

class _FakeTraditionKG:
    """전통 authoring 라운드트립용 stateful fake kg (Cypher 키워드 매칭)."""
    def __init__(self):
        self.tradition = None
        self.revisions = []

    def __call__(self, q, **kw):
        if 'MERGE (rt:ResearchTradition' in q:                 # set_tradition
            self.tradition = kw
            return [{'id': kw['tid']}]
        if 'RETURN rt.tradition_id AS tid' in q:               # get_tradition
            t = self.tradition
            return [] if not t else [{'tid': t['tid'], 'tname': t['tname'], 'commitments': t['commitments'],
                                      'onto': t['onto'], 'meth': t['meth'], 'exemplars': t['exemplars'],
                                      'probs': t['probs'], 'bg': t['bg'], 'rpol': t['rpol'], 'cnotes': t['cnotes']}]
        if 'RETURN rt.commitments AS commitments' in q:        # appraise read
            return [{'commitments': self.tradition['commitments']}] if self.tradition else []
        if 'HAS_TRADITION_REVISION]->(:TraditionRevision' in q:  # appraise write
            self.revisions.append(kw['cp'])
            return []
        if 'sum(rv.conceptual_pressure)' in q:                 # series bridge
            return [{'cp': sum(self.revisions)}]
        return []


def test_tradition_authoring_appraise_roundtrip(monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, 'kg', _FakeTraditionKG())
    monkeypatch.setattr(app, 'hist', lambda *a, **k: None)
    c = TestClient(app.app)
    r = c.post('/api/tree/T/tradition', json={'tradition_id': 't1', 'name': 'CAD 3D inspection',
               'exemplars': ['euler'], 'commitments': [
                   {'commitment_id': 'm1', 'kind': 'methodology', 'statement': 'CAD prior', 'revisability': 'costly'},
                   {'commitment_id': 'o1', 'kind': 'ontology', 'statement': '결정성', 'revisability': 'identity_boundary'}]})
    assert r.status_code == 200 and r.json()['commitments'] == 2 and r.json()['authority'] == 'diagnostic_only'
    g = c.get('/api/tree/T/tradition')
    assert g.status_code == 200 and g.json()['tradition_id'] == 't1' and 'euler' in g.json()['exemplars']
    # costly methodology, 영수증 없음 → tradition_drift (직접 hard-core 위반 아님)
    a = c.post('/api/tree/T/tradition/appraise', json={'commitment_id': 'm1', 'operation': 'modify'})
    assert a.status_code == 200 and a.json()['outcome'] == 'tradition_drift'
    assert a.json()['authority'] == 'diagnostic_only'
    # identity_boundary ontology → different_programme_candidate (개념압력 1.0 누적)
    a2 = c.post('/api/tree/T/tradition/appraise', json={'commitment_id': 'o1', 'operation': 'retire'})
    assert a2.json()['outcome'] == 'different_programme_candidate' and a2.json()['conceptual_pressure'] == 1.0


def test_set_tradition_bad_enum_422(monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, 'kg', _FakeTraditionKG())
    r = TestClient(app.app).post('/api/tree/T/tradition', json={'tradition_id': 't', 'name': 'x',
                                 'commitments': [{'commitment_id': 'c', 'kind': 'bogus', 'statement': 's'}]})
    assert r.status_code == 422   # tradition.py 도메인 불변식(kind enum) 위반


def test_series_view_surfaces_tradition_conceptual_pressure(monkeypatch):
    # #① bridge: 기록된 전통 개념압력이 series 진단에 반영(diagnostic_only, verdict 권위 불변)
    app = load_app()
    patch_tree(monkeypatch, app, {'T': HEALTHY_TD})
    monkeypatch.setattr(app, 'kg', lambda *a, **k: [{'cp': 0.5}])   # 누적 전통 개념압력 합
    out = app.series_view('T')
    assert out['tradition_conceptual_pressure'] == 0.5
    assert out['coverage']['conceptual_problem'] == 'tradition_wired'   # bridge 활성
    assert out['authority'] == 'diagnostic_only'                        # 권위 불변


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


def test_certificate_assembles_six_gates(monkeypatch):
    app = load_app()
    # mg=server_regenerated(값소유)+mv 존재 → G6 measurement_owned 통과 → 6게이트 전수 인증
    monkeypatch.setattr(app, 'kg', lambda q, **kw: [dict(
        verdict='progressive', vsrc='scripted', pm='p95',
        script='judges/x.py', sha='a' * 64, rp='out/final.json',
        mg='server_regenerated', mv=0.9)])
    monkeypatch.setattr(app, '_reproducible_for_node', lambda n, t: True)
    monkeypatch.setattr(app, 'standing', lambda n, t: dict(
        stands=True, grounded_extension=['verdict:v22'], verdict='progressive'))
    monkeypatch.setattr(app, 'calibration', lambda n: dict(n=4, calibration_error=0.03))   # well-calibrated
    out = app.node_certificate('T', 'v22')
    assert out['certified'] is True
    assert [c['gate'] for c in out['checks']] == \
        ['preregistered', 'reproducible', 'stands', 'calibrated', 'grounded', 'measurement_owned']


# ── G4 'calibrated' 게이트가 ECE 를 강제 (verifier-rigor 연구 P0-#2, 2026-07-21) ──────────────
#    옛 게이트는 판관이 이미 계산한 ECE 를 버리고 존재(n≥1)만 확인 → ECE=0.57 과신도 'calibrated' 인증.
def _six_gate_app(monkeypatch, cal):
    app = load_app()
    monkeypatch.setattr(app, 'kg', lambda q, **kw: [dict(
        verdict='progressive', vsrc='scripted', pm='p95',
        script='judges/x.py', sha='a' * 64, rp='out/final.json',
        mg='server_regenerated', mv=0.9)])
    monkeypatch.setattr(app, '_reproducible_for_node', lambda n, t: True)
    monkeypatch.setattr(app, 'standing', lambda n, t: dict(
        stands=True, grounded_extension=['verdict:v22'], verdict='progressive'))
    monkeypatch.setattr(app, 'calibration', lambda n: cal)
    return app


def _cal_gate(out):
    return next(c for c in out['checks'] if c['gate'] == 'calibrated')


def test_calibrated_gate_blocks_high_ece(monkeypatch):
    # 음성 오라클: ECE=0.57 과신(BhgmanCeilingPierce) → calibrated 차단, 인증 실패.
    out = _six_gate_app(monkeypatch, dict(n=20, calibration_error=0.57)).node_certificate('T', 'v22')
    assert _cal_gate(out)['passed'] is False
    assert out['certified'] is False


def test_calibrated_gate_passes_low_ece(monkeypatch):
    # 양성 통제: ECE=0.03 well-calibrated → 통과 (게이트를 전부에 대해 깨지 않음).
    out = _six_gate_app(monkeypatch, dict(n=20, calibration_error=0.03)).node_certificate('T', 'v22')
    assert _cal_gate(out)['passed'] is True
    assert out['certified'] is True


def test_calibrated_gate_abstains_on_small_n(monkeypatch):
    # N-abstain: 완벽 ECE라도 n<min_n(=3) → 인증 불가(존재 스탬프 회귀 금지).
    out = _six_gate_app(monkeypatch, dict(n=1, calibration_error=0.0)).node_certificate('T', 'v22')
    assert _cal_gate(out)['passed'] is False


def test_grounded_ece_gate_registered():
    from lakatos.grounding import GROUNDED
    assert GROUNDED['ece_gate_max']['tier'] == 'policy_in_scale'
    assert GROUNDED['ece_gate_max']['source'] == 'guo2017'
    assert GROUNDED['ece_gate_min_n']['tier'] == 'policy_in_scale'


def test_certificate_blocks_without_lineage(monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, 'kg', lambda q, **kw: [dict(
        verdict='progressive', vsrc='scripted', pm='p95',
        script='judges/x.py', sha='a' * 64, rp='',
        mg='server_regenerated', mv=0.9)])
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
        verdict='progressive', vsrc='scripted', pm='p95', script='', sha=None, rp='out/x.json',
        mg='server_regenerated', mv=0.9)])
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
