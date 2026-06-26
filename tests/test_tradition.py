"""연구전통층 TDD — Laudan research tradition (diagnostic-only). gap: research_tradition.
설계: THEORY/lakatotree-open-gaps/research_tradition_design.md 의 Future OOPTDD Contracts.
# KG: span_lakatotree_tradition
"""
import pytest

from lakatos.programme.tradition import (
    DIAGNOSTIC_ONLY_AUTHORITY,
    ResearchTradition,
    TraditionAppraisal,
    TraditionCommitment,
    TraditionRevision,
    appraise_tradition_revision,
)


def _commit(kind='methodology', revisability='routine'):
    return TraditionCommitment(commitment_id='c1', kind=kind, statement='CAD prior',
                               revisability=revisability, source_refs=())


def _rev(operation='modify', receipts=(), compat=''):
    return TraditionRevision('c1', operation, reason='r', receipt_refs=receipts, compatibility_claim=compat)


def test_routine_revision_is_same_tradition():
    ap = appraise_tradition_revision(_commit(revisability='routine'), _rev())
    assert ap.outcome == 'same_tradition_revision'
    assert ap.authority == DIAGNOSTIC_ONLY_AUTHORITY


def test_costly_revision_drifts_without_receipts():
    ap = appraise_tradition_revision(_commit(revisability='costly'), _rev())
    assert ap.outcome == 'tradition_drift' and ap.methodology_pressure > 0


def test_costly_revision_with_receipts_is_same_tradition():
    ap = appraise_tradition_revision(_commit(revisability='costly'),
                                     _rev(receipts=('r1',), compat='same metric, validated'))
    assert ap.outcome == 'same_tradition_revision' and ap.methodology_pressure == 0.0


def test_identity_boundary_is_different_programme_candidate_not_hardcore():
    ap = appraise_tradition_revision(_commit(kind='ontology', revisability='identity_boundary'),
                                     _rev(operation='retire'))
    assert ap.outcome == 'different_programme_candidate'   # 직접 hard-core 위반 아님(LakatosGate 경유)
    assert ap.ontology_pressure > 0 and ap.authority == DIAGNOSTIC_ONLY_AUTHORITY


def test_appraisal_never_carries_promotion_authority():
    for rev in ('routine', 'costly', 'identity_boundary'):
        ap = appraise_tradition_revision(_commit(revisability=rev), _rev())
        assert ap.authority == DIAGNOSTIC_ONLY_AUTHORITY   # invariant 4: 승격 권위 0


def test_revision_target_must_match_commitment():
    with pytest.raises(ValueError):
        appraise_tradition_revision(_commit(), TraditionRevision('other', 'modify'))


def test_invalid_enums_refused():
    with pytest.raises(ValueError):
        TraditionCommitment('c', 'bogus_kind', 's')
    with pytest.raises(ValueError):
        TraditionCommitment('c', 'ontology', 's', revisability='bogus')
    with pytest.raises(ValueError):
        TraditionRevision('c', 'bogus_op')


def test_research_tradition_container_validates_and_holds_exemplars():
    t = ResearchTradition(tradition_id='t1', name='CAD 3D inspection',
                          ontology_commitments=('CAD prior',), methodology_rules=('surface match',),
                          exemplars=('euler_polyhedron',), accepted_problem_types=('pose',),
                          background_theories=('rigid body',), revision_policy='receipt-gated')
    assert t.tradition_id == 't1' and 'euler_polyhedron' in t.exemplars
    with pytest.raises(ValueError):
        ResearchTradition(tradition_id='', name='x')
