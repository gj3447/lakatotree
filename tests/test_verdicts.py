"""verdict registry TDD — 문서/서버/엔진의 판결 어휘를 한 곳에서 관리."""
from lakatos.verdicts import (
    ADMIN_VERDICTS,
    SCRIPTED_VERDICTS,
    VERDICT_REGISTRY,
    is_admin_verdict,
    is_registered_verdict,
)


def test_verdict_registry_contains_v11_operational_vocabulary():
    assert 'superseded' in VERDICT_REGISTRY
    assert 'CANONICAL_KNOWLEDGE' in VERDICT_REGISTRY
    assert 'CANONICAL' in ADMIN_VERDICTS
    assert 'progressive' in SCRIPTED_VERDICTS


def test_unknown_verdict_is_not_silently_registered():
    assert is_admin_verdict('CANONICAL')
    assert not is_admin_verdict('progressive')
    assert is_registered_verdict('partial')
    assert not is_registered_verdict('maybe-good')
