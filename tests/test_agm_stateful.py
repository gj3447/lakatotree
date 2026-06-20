"""A4: AGM 신념개정을 *stateful* 로 — belief base 를 트리 KG 에 영속하고, hard_core contraction/
demote 시 의존 CANONICAL 노드를 엔진이 auto-rejudge(→former_canonical, verdict_source='engine').

전엔 /api/agm/revise 가 body 의 base 리스트만 다뤄(stateless) revision 이 트리를 안 건드리고
재판결을 안 트리거했다. 이제 tree 를 주면 영속 base 를 로드/저장하고 auto-demote 까지 한 kg_tx 로.
기존 stateless 계약(body-override)은 보존 — tree 없으면 kg/kg_tx 미접촉(test_agm_wire 불변).
"""
import importlib
import os


def load_app():
    os.environ.setdefault('NEO4J_URI', 'bolt://localhost:7687')
    os.environ.setdefault('NEO4J_USER', 'neo4j')
    os.environ.setdefault('NEO4J_PASSWORD', 'test')
    return importlib.import_module('server.app')


def test_agm_revise_without_tree_stays_stateless(monkeypatch):
    """body-override 보존: tree 없으면 KG 를 전혀 건드리지 않는다(순수, 기존 계약)."""
    app = load_app()
    touched = []
    monkeypatch.setattr(app, 'kg', lambda *a, **k: touched.append('kg') or [])
    monkeypatch.setattr(app, 'kg_tx', lambda ops: touched.append('kg_tx'))
    monkeypatch.setattr(app, 'hist', lambda *a, **k: touched.append('hist'))
    out = app.agm_revise(app.AgmReviseIn(op='expansion', base=[], new=app.BeliefIn(belief_id='b1')))
    assert touched == []                              # 순수 — KG 미접촉
    assert [b['belief_id'] for b in out['base']] == ['b1']
    assert out.get('persisted') in (False, None)     # 영속 안 함


def test_agm_revise_with_tree_loads_persisted_base_and_persists(monkeypatch):
    """tree 주면 영속 belief base 를 로드(body base 없을 때)해 그 위에서 연산하고, 결과를 한 kg_tx 로 영속."""
    app = load_app()

    def kg(q, **kw):
        if 'HAS_BELIEF' in q and 'RETURN' in q:       # 영속 base 로드
            return [dict(belief_id='b1', statement='b1', kind='protective_belt',
                         credence=0.5, problem_balance=0, connectivity=0, depends_on=[])]
        return []
    txs = []
    monkeypatch.setattr(app, 'kg', kg)
    monkeypatch.setattr(app, 'kg_tx', lambda ops: txs.append(ops) or [[]])
    monkeypatch.setattr(app, 'hist', lambda *a, **k: None)
    out = app.agm_revise(app.AgmReviseIn(op='expansion', tree='T', new=app.BeliefIn(belief_id='b2')))
    assert out['persisted'] is True and out['loaded_base'] is True
    assert {b['belief_id'] for b in out['base']} == {'b1', 'b2'}   # 로드된 b1 + 확장 b2
    assert len(txs) == 1                                            # 단일 kg_tx
    cyphers = ' '.join(c for c, _ in txs[0])
    assert 'MERGE (bel:Belief' in cyphers                          # belief 영속


def test_agm_hard_core_contraction_auto_demotes_dependent_canonical(monkeypatch):
    """A4 핵심: hard_core belief contraction(allow_hard_core) → 같은 tag 의 CANONICAL 노드를 엔진이
    former_canonical 로 auto-demote(verdict_source='engine'), 수동 재채점 0회 — 같은 kg_tx 안에서."""
    app = load_app()

    def kg(q, **kw):
        if 'HAS_BELIEF' in q and 'RETURN' in q:
            return [dict(belief_id='hc', statement='hc', kind='hard_core',
                         credence=0.9, problem_balance=0, connectivity=0, depends_on=[])]
        return []
    txs = []
    monkeypatch.setattr(app, 'kg', kg)
    monkeypatch.setattr(app, 'kg_tx', lambda ops: txs.append(ops) or [[]])
    monkeypatch.setattr(app, 'hist', lambda *a, **k: None)
    out = app.agm_revise(app.AgmReviseIn(op='contraction', tree='T', target_id='hc',
                                         allow_hard_core=True))
    assert out['removed'] == ['hc'] and out['programme_shift_candidate'] is True
    assert 'hc' in out['auto_demote_candidates']
    cyphers = ' '.join(c for c, _ in txs[0])
    assert 'former_canonical' in cyphers and "verdict_source='engine'" in cyphers


def test_agm_auto_demote_respects_human_lock_valid_until_rebutted(monkeypatch):
    """A4-richer: 자동 강등이 spine.reconcile_standing 정책 — CANONICAL ∧ valid_until_rebutted=True 만
    강등. 인간이 lock 한(valid_until_rebutted=False) 노드는 belief contraction 으로도 자동강등 금지.
    demote op 가 그 human-lock 가드를 포함해야(전엔 blanket SET 이 lock 무시 = 버그)."""
    app = load_app()

    def kg(q, **kw):
        if 'HAS_BELIEF' in q and 'RETURN' in q:
            return [dict(belief_id='hc', statement='hc', kind='hard_core',
                         credence=0.9, problem_balance=0, connectivity=0, depends_on=[])]
        return []
    txs = []
    monkeypatch.setattr(app, 'kg', kg)
    monkeypatch.setattr(app, 'kg_tx', lambda ops: txs.append(ops) or [[]])
    monkeypatch.setattr(app, 'hist', lambda *a, **k: None)
    app.agm_revise(app.AgmReviseIn(op='contraction', tree='T', target_id='hc', allow_hard_core=True))
    demote = [c for c, _ in txs[0] if 'former_canonical' in c]
    assert demote, '강등 op 없음'
    assert any('valid_until_rebutted' in c for c in demote), 'human-lock 가드 누락(reconcile_standing 정책)'
