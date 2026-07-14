"""A1: eureka 배선 — 판결 seam(submit_test_result)에서 measurement-grade eureka 산출·영속.

전엔 eureka.classify 가 metrics._eureka_layer(트리집계)에만 먹였고 *노드별* 판정은 미배선이었다
(__init__ 미export + 제출 seam 미연결). 이 테스트는 ① 패키지 export ② 제출 seam 의 노드별
felt/true/hallucinated 를 동일 kg_tx op-list 안에서 산출·영속(원자적, 2차 비원자 쓰기 금지)을 핀.
"""
import importlib
import os


def load_app():
    os.environ.setdefault('NEO4J_URI', 'bolt://localhost:7687')
    os.environ.setdefault('NEO4J_USER', 'neo4j')
    os.environ.setdefault('NEO4J_PASSWORD', 'test')
    return importlib.import_module('server.app')


def test_eureka_classify_importable_from_package():
    from lakatos import classify, EurekaVerdict, eureka_over_tree, eureka_rate   # noqa: F401


def _pred_eureka(q, **kw):
    # novel target 등록 + 닫는 질문 존재(closes) — measurement-grade true 가 가능한 사전등록 상태.
    if 'RETURN e.pred_metric' in q:
        return [dict(m='p95', d='lower', b=0.5, nb=0.02, novel='x', vsrc=None,
                     nmet='nm', ndir='higher', nthr=0.5, psha=None,
                     closes='q1', n_opened=0)]
    return []


def _pred_eureka_without_noise(q, **kw):
    if 'RETURN e.pred_metric' in q:
        return [dict(m='p95', d='lower', b=0.5, nb=None, novel='x', vsrc=None,
                     nmet='nm', ndir='higher', nthr=0.5, psha=None,
                     closes='q1', n_opened=0)]
    return []


def test_submit_emits_true_eureka_in_same_tx(monkeypatch):
    app = load_app()
    txs = []
    monkeypatch.setattr(app, 'kg', _pred_eureka)
    monkeypatch.setattr(app, 'kg_tx', lambda ops: txs.append(ops) or [[]])
    monkeypatch.setattr(app, 'hist', lambda *a, **k: None)
    out = app.submit_test_result('T', 'v', app.TestResultIn(
        metric_value=0.1, script='j.py', novel_measured=0.9))   # 큰 개선(delta=0.4) + novel 적중
    assert out['verdict'] == 'progressive_unverified'
    assert out['eureka']['felt'] is True
    assert out['eureka']['true'] is True
    assert out['eureka']['hallucinated'] is False
    # 같은 단일 tx 안에서 영속 (판결 SET 과 원자적, 2차 비원자 쓰기 금지)
    assert len(txs) == 1
    cyphers = [c for c, _ in txs[0]]
    assert any('eureka_true' in c for c in cyphers)


def test_submit_unconfirmed_novel_is_hallucinated(monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, 'kg', _pred_eureka)
    monkeypatch.setattr(app, 'kg_tx', lambda ops: [[]])
    monkeypatch.setattr(app, 'hist', lambda *a, **k: None)
    # novel_measured 가 threshold(0.5, higher) 미달 → novel 미확증 → felt 이나 not true = hallucinated
    out = app.submit_test_result('T', 'v', app.TestResultIn(
        metric_value=0.1, script='j.py', novel_measured=0.1))
    assert out['eureka']['felt'] is True
    assert out['eureka']['true'] is False
    assert out['eureka']['hallucinated'] is True


def test_submit_eureka_preserves_absent_noise_as_weak_evidence(monkeypatch):
    """NB1: submit seam이 pred_noise_band=None을 선언-0으로 강등하지 않는다."""
    from lakatos.quant.bayes import BF_BASE, bayes_factor

    app = load_app()
    monkeypatch.setattr(app, 'kg', _pred_eureka_without_noise)
    monkeypatch.setattr(app, 'kg_tx', lambda ops: [[]])
    monkeypatch.setattr(app, 'hist', lambda *a, **k: None)
    out = app.submit_test_result('T', 'v', app.TestResultIn(
        metric_value=0.1, script='j.py', novel_measured=0.9))
    expected = bayes_factor('progressive', delta=-0.4, noise_band=None)
    assert out['eureka']['bf'] == round(expected, 3)
    assert expected < BF_BASE['progressive']


# ── A1-surface: GET /node/{tag}/eureka read surface ──────────────────────────
def test_node_eureka_reads_persisted_fields():
    from server.contexts.tree.judgement_service import JudgementService

    def kg(q, **kw):
        return [dict(tag='v', verdict='progressive', felt=True, true=True,
                     hallucinated=False, reasons=['x'], bf=6.0)]
    svc = JudgementService(kg=kg, kg_tx=lambda ops: None, hist=lambda *a, **k: None,
                           foundation=lambda n: None, reproducible_for_node=lambda n, t: None)
    out = svc.node_eureka('T', 'v')
    assert out['judged'] is True and out['felt'] is True and out['true'] is True
    assert out['hallucinated'] is False and out['reasons'] == ['x']


def test_node_eureka_unjudged_node_is_not_felt():
    from server.contexts.tree.judgement_service import JudgementService

    def kg(q, **kw):
        return [dict(tag='v', verdict=None, felt=None, true=None,
                     hallucinated=None, reasons=None, bf=None)]
    svc = JudgementService(kg=kg, kg_tx=lambda ops: None, hist=lambda *a, **k: None,
                           foundation=lambda n: None, reproducible_for_node=lambda n, t: None)
    out = svc.node_eureka('T', 'v')
    assert out['judged'] is False and out['felt'] is False


# ── A3: standing echoes the defeated-doubt list (Dung 가시성) ─────────────────
def test_standing_exposes_defeated_doubt(monkeypatch):
    app = load_app()

    def kg(q, **kw):
        # 막지 못한 의문(doubt1)이 verdict 를 직접 공격 → verdict 패퇴, doubt1 만 grounded
        return [dict(verdict='progressive',
                     args=[dict(id='crit/doubt1', attacks='v', kind='rebuttal', by='x')])]
    monkeypatch.setattr(app, 'kg', kg)
    out = app.standing('T', 'v')
    assert out['stands'] is False
    assert 'verdict:v' in out['defeated']           # 패퇴한 논증 명시
    assert 'doubt1' in out['grounded_extension']
