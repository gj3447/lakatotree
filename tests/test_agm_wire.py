"""Cluster ② — AGM 신념개정(P1)이 server 로 노출돼 실제 호출 가능한지 (나생문 WIRE-3).

AGM 모듈은 95% 테스트됐으나 어떤 surface 에서도 호출 불가였다. /api/agm/revise 로 reachable.
hard core PROTECTED + programme_shift_candidate(Kuhn 연동)이 HTTP 경계에서 보존되는지 검증.
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


def _belt(bid, **kw):
    return dict(belief_id=bid, statement=bid, kind='protective_belt', **kw)


def test_agm_expansion_adds(monkeypatch):
    app = load_app()
    out = app.agm_revise(app.AgmReviseIn(op='expansion', base=[],
                                         new=app.BeliefIn(**_belt('b1'))))
    assert out['op'] == 'expansion'
    assert [b['belief_id'] for b in out['base']] == ['b1']
    assert out['added'] == ['b1']


def test_agm_contraction_protects_hard_core(monkeypatch):
    app = load_app()
    base = [app.BeliefIn(belief_id='hc', kind='hard_core')]
    with pytest.raises(HTTPException) as e:                  # allow_hard_core 없이 409
        app.agm_revise(app.AgmReviseIn(op='contraction', base=base, target_id='hc'))
    assert e.value.status_code == 409


def test_agm_contraction_hard_core_with_consent_flags_shift(monkeypatch):
    app = load_app()
    base = [app.BeliefIn(belief_id='hc', kind='hard_core')]
    out = app.agm_revise(app.AgmReviseIn(op='contraction', base=base,
                                         target_id='hc', allow_hard_core=True))
    assert out['removed'] == ['hc']
    assert out['programme_shift_candidate'] is True          # Kuhn 연동 신호 보존
    assert 'lexicographic' in out['entrenchment_policy']


def test_agm_revision_levi_identity(monkeypatch):
    app = load_app()
    base = [app.BeliefIn(**_belt('old')), app.BeliefIn(**_belt('keep'))]
    out = app.agm_revise(app.AgmReviseIn(op='revision', base=base,
                                         new=app.BeliefIn(**_belt('new')), contradicts=['old']))
    ids = {b['belief_id'] for b in out['base']}
    assert ids == {'keep', 'new'} and out['removed'] == ['old']


def test_agm_demote_canonical(monkeypatch):
    app = load_app()
    base = [app.BeliefIn(belief_id='oldcan', credence=0.9)]
    out = app.agm_revise(app.AgmReviseIn(op='demote_canonical', base=base,
                                         old_canonical_id='oldcan',
                                         new=app.BeliefIn(belief_id='newcan', credence=0.8)))
    by = {b['belief_id']: b for b in out['base']}
    assert 'newcan' in by
    assert by['oldcan']['credence'] < 0.9                    # 강등(credence 내려감)


def test_agm_bad_op_422(monkeypatch):
    app = load_app()
    with pytest.raises(HTTPException) as e:
        app.agm_revise(app.AgmReviseIn(op='nonsense', base=[]))
    assert e.value.status_code == 422
