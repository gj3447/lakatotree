"""Cluster ① — '초록인데 안 돌던' 기능을 실제로 작동시키는 write-path 검증.

T3-1: pred_credence write → certify G4(calibration) 가 더 이상 영구 n=0 아님.
WIRE-1: question 의 expected_gain/cost write → directions VoI 가 default 가 아닌 실값으로 차등.
GAP-T2-04: route-contract + TestClient 스모크 — CLI/MCP↔서버 route/serialization drift 차단.
# KG: span_lakatotree_make_it_real
"""
import importlib
import os

from fastapi.testclient import TestClient


def load_app():
    os.environ.setdefault('NEO4J_URI', 'bolt://localhost:7687')
    os.environ.setdefault('NEO4J_USER', 'neo4j')
    os.environ.setdefault('NEO4J_PASSWORD', 'test')
    return importlib.import_module('server.app')


def _capture_kg(monkeypatch, app, ret=None):
    calls = []

    def fake_kg(q, **kw):
        calls.append((q, kw))
        return ret if ret is not None else [{'tag': 'v'}]

    monkeypatch.setattr(app, 'kg', fake_kg)
    monkeypatch.setattr(app, 'hist', lambda *a, **k: None)
    return calls


# ── T3-1: pred_credence write-path (certify G4 부활) ──

def test_register_prediction_writes_pred_credence(monkeypatch):
    app = load_app()
    calls = _capture_kg(monkeypatch, app)
    app.register_prediction('T', 'v', app.PredictionIn(
        metric_name='p95', baseline_value=0.5, credence=0.8))
    q, kw = next(c for c in calls if 'e.pred_metric=' in c[0])   # ontology read 가 calls[0] 라 내용으로 찾음
    assert 'e.pred_credence=$credence' in q
    assert kw['credence'] == 0.8


def test_register_prediction_credence_optional(monkeypatch):
    app = load_app()
    calls = _capture_kg(monkeypatch, app)
    app.register_prediction('T', 'v', app.PredictionIn(metric_name='p95', baseline_value=0.5))
    pred = next(c for c in calls if 'e.pred_metric=' in c[0])   # ontology read 가 calls[0] 라 내용으로 찾음
    assert pred[1]['credence'] is None        # 안 줘도 OK


def test_calibration_has_data_once_pred_credence_present(monkeypatch):
    # write-path 생겨 calibration 이 더 이상 구조적 n=0 영구가 아님 (certify G4 통과 가능)
    app = load_app()
    monkeypatch.setattr(app, 'kg', lambda q, **kw: [dict(p=0.8, o=True), dict(p=0.3, o=False)])
    out = app.calibration('T')
    assert out['n'] == 2


# ── WIRE-1: VoI write-path (directions 차등 부활) ──

def test_open_question_writes_voi_meta(monkeypatch):
    app = load_app()
    calls = _capture_kg(monkeypatch, app)
    app.open_question('T', app.QuestionIn(qname='q1', body='b', expected_gain=0.4, cost=2.0))
    q, kw = calls[0]
    assert 'qn.expected_gain=$expected_gain' in q and 'qn.cost=$cost' in q
    assert (kw['expected_gain'], kw['cost']) == (0.4, 2.0)


def test_directions_ranks_by_real_voi_and_survives_none(monkeypatch):
    app = load_app()
    td = dict(name='T', title='T', hard_core=[], frontier_rule='', doc='',
              coverage_backlog=[], coverage_statement='',
              nodes=[dict(tag='c', verdict='CANONICAL', metric_value=None)],
              frontier=[
                  dict(name='q-old', status='OPEN', body='', expected_gain=None, cost=None, n_visits=None),
                  dict(name='q-hi', status='OPEN', body='', expected_gain=0.9, cost=1.0, n_visits=1),
                  dict(name='q-lo', status='OPEN', body='', expected_gain=0.05, cost=5.0, n_visits=1)])
    monkeypatch.setattr(app, 'tree_data', lambda n: td)
    monkeypatch.setattr(app, 'compute_metrics', lambda t: {'bayes': {'canonical_credence': 0.5}})
    out = app.directions('T')
    names = [d['name'] for d in out['ranked_directions']]
    assert names[0] == 'q-hi'                     # 실 VoI 반영 → 차등 생김 (전엔 전부 동률)
    assert 'q-old' in names                       # None(옛 질문)이어도 crash 없이 포함


# ── GAP-T2-04: route-contract (CLI/MCP 가 부르는 경로가 전부 실재하는가) ──

def test_cli_mcp_endpoints_are_registered_routes():
    app = load_app()
    registered = set()

    def _leaves(router):
        # FastAPI >=0.137 wraps included routers as _IncludedRouter (sub-routes
        # under original_router.routes) instead of flattening inline — walk both.
        for r in router.routes:
            sub = getattr(r, 'original_router', None)
            if sub is not None and hasattr(sub, 'routes'):
                yield from _leaves(sub)
            else:
                yield r

    for r in _leaves(app.app):
        for m in (getattr(r, 'methods', None) or []):
            registered.add((m, r.path))
    required = {
        ('GET', '/api/trees'), ('GET', '/api/tree/{name}'),
        ('GET', '/api/tree/{name}/metrics'), ('GET', '/api/tree/{name}/directions'),
        ('GET', '/api/tree/{name}/stack'), ('GET', '/api/tree/{name}/lifecycle'),
        ('GET', '/api/leaderboard'), ('GET', '/api/paradigm'),
        ('GET', '/api/tree/{name}/node/{tag}/certificate'),
        ('GET', '/api/tree/{name}/calibration'),
        ('POST', '/api/tree/{name}/question'),
        ('POST', '/api/tree/{name}/question/{qname}/close'),
        ('POST', '/api/tree/{name}/node/{tag}/prediction'),
        ('POST', '/api/tree/{name}/node/{tag}/test_result'),
        ('GET', '/api/tree/{name}/node/{tag}/standing'),
        ('GET', '/api/tree/{name}/node/{tag}/claim-standing'),
        ('POST', '/api/tree/{name}/node/{tag}/critique'),
    }
    missing = required - registered
    assert not missing, f'CLI/MCP 가 부르는데 미등록 라우트: {missing}'


# ── GAP-T2-04: TestClient 스모크 — 실 ASGI/직렬화 스택 관통 (read 경로) ──

def test_testclient_trees_and_dashboard_serialize(monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, 'kg', lambda q, **kw: [])     # 빈 KG
    client = TestClient(app.app)
    r = client.get('/api/trees')
    assert r.status_code == 200 and r.json() == []
    d = client.get('/')
    assert d.status_code == 200 and '라카토스 서버' in d.text


def test_calibration_query_restricts_to_novel_registered(monkeypatch):
    # CREDENCE-CALIBRATION-MISMATCH 수정: novel 없는 예측 오염 차단(novel_registered=true)
    app = load_app()
    calls = _capture_kg(monkeypatch, app, ret=[])
    app.calibration('T')
    assert 'novel_registered = true' in calls[0][0]


def test_register_prediction_bumps_closed_question_visits(monkeypatch):
    # WIRE1-UCB 수정: closes_question 예측이 그 질문 n_visits++ → UCB 탐색항 차등
    app = load_app()
    calls = _capture_kg(monkeypatch, app)
    app.register_prediction('T', 'v', app.PredictionIn(
        metric_name='p95', baseline_value=0.5, closes_question='q1'))
    assert any('n_visits=coalesce(q.n_visits, 0) + 1' in q for q, _ in calls)
    assert any(kw.get('cq') == 'q1' for _, kw in calls)


# ── prom16 engine-axis: CounterexampleType end-to-end 배선 (server) ──
import pytest
from fastapi import HTTPException


def _pred_row(q, **kw):
    if 'RETURN e.pred_metric' in q:
        return [dict(m='p95', d='lower', b=0.5, nb=0.05, novel=None, vsrc=None,
                     nmet=None, ndir=None, nthr=None, psha=None)]
    return []


def test_test_result_invalid_counterexample_type_422(monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, 'kg', _pred_row)
    monkeypatch.setattr(app, 'hist', lambda *a, **k: None)
    with pytest.raises(HTTPException) as e:
        app.submit_test_result('T', 'v', app.TestResultIn(
            metric_value=0.4, script='j.py', counterexample_response='lemma_incorporation',
            counterexample_type='bogus'))
    assert e.value.status_code == 422


def test_test_result_accepts_valid_counterexample_type(monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, 'kg', _pred_row)
    monkeypatch.setattr(app, 'kg_tx', lambda ops: [[]])
    monkeypatch.setattr(app, 'hist', lambda *a, **k: None)
    out = app.submit_test_result('T', 'v', app.TestResultIn(
        metric_value=0.4, script='j.py', counterexample_response='lemma_incorporation',
        ce_excess_content=True, ce_novel_corroborated=True, ce_in_heuristic_spirit=True,
        counterexample_type='local_not_global'))
    assert 'verdict' in out            # CounterexampleType 파싱+전달 배선 — 422 없이 판결 산출


def test_test_result_writes_verdict_and_prov_in_single_tx(monkeypatch):
    # P6-1b OPS-HON-2: 판결 SET + PROV-O 가 단일 kg_tx (부분쓰기 분기 차단)
    app = load_app()
    monkeypatch.setattr(app, 'kg', _pred_row)
    monkeypatch.setattr(app, 'hist', lambda *a, **k: None)
    txs = []
    monkeypatch.setattr(app, 'kg_tx', lambda ops: txs.append(ops) or [[]])
    app.submit_test_result('T', 'v', app.TestResultIn(metric_value=0.4, script='j.py'))
    assert len(txs) == 1                                   # 단일 tx
    cyphers = [c for c, _ in txs[0]]
    assert any('e.verdict=$v' in c for c in cyphers)       # 판결 SET 포함
    assert any('HAS_PROV' in c or 'PROV_REL' in c for c in cyphers)   # PROV 도 같은 tx


# ── P6-2b: ENG-DU-1 ProofGeneratedConcept reachable + F2 /cycle PnR 배선 ──

def _pred_novel(q, **kw):   # novel target 등록된 pred → 적중 시 metric_verdict=progressive
    if 'RETURN e.pred_metric' in q:
        return [dict(m='p95', d='lower', b=0.5, nb=0.05, novel='x', vsrc=None,
                     nmet='nm', ndir='higher', nthr=0.5, psha=None)]
    return []


def test_proof_generated_concept_reaches_appraisal(monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, 'kg', _pred_novel)
    monkeypatch.setattr(app, 'kg_tx', lambda ops: [[]])
    monkeypatch.setattr(app, 'hist', lambda *a, **k: None)
    base = dict(metric_value=0.4, script='j.py', novel_measured=0.9,   # 0.9>0.5 → novel 적중
                counterexample_response='proofs_and_refutations',
                ce_excess_content=True, ce_novel_corroborated=True, ce_in_heuristic_spirit=True)
    with_pgc = app.submit_test_result('T', 'v', app.TestResultIn(
        **base, ce_proof_concept_name='단순연결', ce_proof_born_from='속빈정육면체',
        ce_proof_incorporated_lemma='convexity'))
    without = app.submit_test_result('T', 'v', app.TestResultIn(**base))
    assert with_pgc['verdict'] == 'progressive'                # 증명-생성 개념 → 성숙 진보 확정
    assert without['verdict'] == 'progressive_conditional'     # 없으면 조건부(PnR 성숙 미완)


def test_run_cycle_carries_pnr_fields(monkeypatch):
    # F2: 전엔 /cycle 이 dialectic 우회 — 이제 PnR/lakatos 필드를 test_result 로 전달
    app = load_app()
    captured = {}
    monkeypatch.setattr(app, 'add_node', lambda n, x: {'ok': True})
    monkeypatch.setattr(app, 'register_prediction', lambda n, t, x: {'ok': True})
    monkeypatch.setattr(app, 'submit_test_result',
                        lambda n, t, r: (captured.__setitem__('r', r), {'verdict': 'progressive', 'novel': None, 'delta': -0.2})[1])
    monkeypatch.setattr(app, 'standing', lambda n, t: {'stands': True})
    app.run_cycle('T', app.CycleIn(tag='e1', metric_name='p95', baseline=0.5, measured=0.4,
                                   counterexample_response='monster_barring', lakatos_hardcore=False))
    assert captured['r'].counterexample_response == 'monster_barring'
    assert captured['r'].lakatos_hardcore is False


# ── P6-5 ENG-DU-3: /api/prov ?format=prov-json → 표준 W3C PROV-JSON (직렬기 배선) ──

def test_artifact_prov_format_prov_json(monkeypatch):
    app = load_app()
    from lakatos.io.lineage import Derivation
    src = Derivation('raw', 'rs', '', '', [], kind='source')
    fin = Derivation('out', 'os', 'build.py', 'bs', [('raw', 'rs')], kind='final')
    monkeypatch.setattr(app, '_load_lineage', lambda: [src, fin])
    plain = app.artifact_prov('out')
    pj = app.artifact_prov('out', format='prov-json')
    assert 'prov' in plain                          # format 없으면 내부 dict
    assert 'prefix' in pj and 'entity' in pj and 'activity' in pj   # 표준 W3C PROV-JSON 키


def test_rebuild_verify_static_surface_uses_distinct_token(monkeypatch):
    """#7 정직: /rebuild-verify 는 *정적* DAG 체크(재실행 아님)다 → executor 재실행 영수증과 같은
    'rebuildable' 을 뱉으면 영수증급 과장. 정적 surface 는 rebuildable_static + verified='static' 을 뱉어야."""
    from server.contexts.lineage import service as svc
    s = svc.LineageService(kg=None, pg=None, path_sha=lambda p: None,
                           load_lineage=lambda: [], safe_rebuild_plan=lambda a, bo: [])
    monkeypatch.setattr(s, '_lineage_for', lambda a: ([], {}))
    monkeypatch.setattr(s, '_current_input_shas', lambda ds: {})
    monkeypatch.setattr(s, '_safe_rebuild_plan', lambda a, bo: [])
    monkeypatch.setattr(svc, 'reproducibility_gaps', lambda *a, **k: set())

    class _M:
        final = 'out.json'; roots = []; env_sha = '0' * 64; recipe = []
    monkeypatch.setattr(svc, 'build_manifest', lambda *a, **k: _M)

    out = s.rebuild_verify('out.json')
    assert out['verdict'] == 'rebuildable_static'   # 'rebuildable'(executor 영수증) 아님
    assert out['verified'] == 'static'
