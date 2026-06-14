"""P8/ENG-DU-2: LakatosGate data_branch/data_replay/human_verdict 배선 (TDD).

engine.LakatosGate 는 data_branch/data_replay_passed/human_verdict_required 를 *평가*하나,
submit_test_result 가 LakatosEvidence 에 *주입* 안 해 프로덕션에서 dead 였다(test-vs-prod drift).
TestResultIn → LakatosEvidence 배선으로 활성화.
"""
import importlib
import os


def load_app():
    os.environ.setdefault('NEO4J_URI', 'bolt://localhost:7687')
    os.environ.setdefault('NEO4J_USER', 'neo4j')
    os.environ.setdefault('NEO4J_PASSWORD', 'test')
    return importlib.import_module('server.app')


def _pred_novel(q, **kw):   # novel 적중 → metric_verdict=progressive
    if 'RETURN e.pred_metric' in q:
        return [dict(m='p95', d='lower', b=0.5, nb=0.05, novel='x', vsrc=None,
                     nmet='nm', ndir='higher', nthr=0.5, psha=None)]
    return []


def _wire(app, monkeypatch):
    monkeypatch.setattr(app, 'kg', _pred_novel)
    monkeypatch.setattr(app, 'kg_tx', lambda ops: [[]])
    monkeypatch.setattr(app, 'hist', lambda *a, **k: None)


_QUAL = dict(lakatos_anomaly=True, lakatos_consequence=True,
             lakatos_excess=True, lakatos_hardcore=True)


def test_human_verdict_required_forces_ambiguous(monkeypatch):
    app = load_app(); _wire(app, monkeypatch)
    out = app.submit_test_result('T', 'v', app.TestResultIn(
        metric_value=0.4, script='j.py', novel_measured=0.9, human_verdict_required=True))
    assert out['verdict'] == 'ambiguous'        # 질적기준 없이도 인간보류 강제
    assert out['requires_human'] is True


def test_data_branch_replay_not_proven_is_conditional(monkeypatch):
    app = load_app(); _wire(app, monkeypatch)
    out = app.submit_test_result('T', 'v', app.TestResultIn(
        metric_value=0.4, script='j.py', novel_measured=0.9, **_QUAL,
        data_branch=True, data_replay_passed=False))
    assert out['verdict'] == 'progressive_conditional'   # data replay 미증명 → 조건부


def test_data_branch_replay_passed_is_progressive(monkeypatch):
    app = load_app(); _wire(app, monkeypatch)
    out = app.submit_test_result('T', 'v', app.TestResultIn(
        metric_value=0.4, script='j.py', novel_measured=0.9, **_QUAL,
        data_branch=True, data_replay_passed=True))
    assert out['verdict'] == 'progressive'


def test_default_no_data_branch_unchanged(monkeypatch):
    app = load_app(); _wire(app, monkeypatch)
    out = app.submit_test_result('T', 'v', app.TestResultIn(
        metric_value=0.4, script='j.py', novel_measured=0.9, **_QUAL))
    assert out['verdict'] == 'progressive'
    assert out.get('requires_human') is False
