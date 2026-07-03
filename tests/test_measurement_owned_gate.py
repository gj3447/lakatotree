"""G6 measurement_owned — measurement_grade 사다리(AG3~5)에 *이빨*을 준다.

측정주권의 잔여 구멍: AG3 가 값소유 기계(replay 재유도 → server_regenerated grade)를 지었고
AG5 가 신원(attested)을 사다리에 얹었지만, **인증서(certify.py)는 measurement_grade 를 아예 안 봤다**
— 5게이트만 통과하면 무replay·무서명 client_asserted float 도 certified=true 였다(grade=장식).

이 스위트가 그 구멍을 못 박는다(RED-first 이중가드):
  · 결함 오라클 : client_asserted(무replay·무서명) 측정근거 claim 은 미소유 = 인증 불가여야.
  · 메커니즘 오라클 : server_regenerated(값소유)·attested(서명)·측정값없음(질적) 은 소유 = 인증 가능.
  · revert-민감 : measurement_owned 를 GATES 에서 빼면 client_asserted 가 다시 인증됨 → 구조 가드가 RED.
"""
import pytest

from lakatos.verdict.certify import (
    GATES, OWNED_GRADES, is_measurement_owned, gate_check, certify_claim,
)

_FULL_WINDOW = {'as_of': '2026-07-03T00:00:00+00:00'}


def _pass(gate):
    return gate_check(gate, True, evidence_ref=f'ev:{gate}')


# ── 술어: is_measurement_owned (순수 honesty 규칙) ────────────────────────────
@pytest.mark.parametrize('grade,has_metric,expected', [
    ('client_asserted', True, False),   # ★결함: 무replay·무서명 float 을 근거로 든 claim = 미소유
    (None, True, False),                #   grade 미기록 + 측정근거 = 미소유
    ('server_regenerated', True, True), # 서버 replay 재유도 = 값소유
    ('attested', True, True),           # allow-list 신원 서명 = 소유(익명 아님·비부인)
    ('client_asserted', False, True),   # SCOPED: 측정값 없는 노드(질적/problem) = 자동 소유(무회귀)
    (None, False, True),                # 문제진술 노드 등 = 측정소유 무의미
])
def test_owned_predicate(grade, has_metric, expected):
    assert is_measurement_owned(grade, has_metric) is expected


def test_owned_grades_are_the_ladder_top():
    """소유 등급 = server_regenerated·attested 뿐. client_asserted 는 절대 소유 아님."""
    assert set(OWNED_GRADES) == {'server_regenerated', 'attested'}
    assert 'client_asserted' not in OWNED_GRADES


# ── 게이트가 load-bearing: certificate 가 실제로 캡되나 ────────────────────────
def test_measurement_owned_is_a_required_gate():
    """revert-민감: G6 가 GATES 에 있어야 인증이 grade 를 강제한다(빼면 구멍 부활)."""
    assert 'measurement_owned' in GATES


def test_client_asserted_metric_claim_is_not_certified():
    """★핵심(구멍 봉합): 다른 5게이트 다 통과해도 measurement_owned 미통과면 인증 거부."""
    five = [_pass(g) for g in GATES if g != 'measurement_owned']
    unowned = gate_check('measurement_owned', False, '', 'client_asserted — 무replay·무서명')
    cert = certify_claim('t/n', five + [unowned], _FULL_WINDOW)
    assert cert.certified is False
    assert 'measurement_owned' in cert.missing


def test_owned_metric_claim_certifies():
    """메커니즘: 값소유(또는 attested)면 6게이트 전수 통과 → 인증."""
    checks = [_pass(g) for g in GATES]
    cert = certify_claim('t/n', checks, _FULL_WINDOW)
    assert cert.certified is True
    assert cert.missing == ()


def test_missing_g6_entirely_blocks_certification():
    """G6 을 아예 제출 안 하면(구버전 5게이트 호출부) 미통과로 집계 → 인증 거부(silent-pass 아님)."""
    five = [_pass(g) for g in GATES if g != 'measurement_owned']
    cert = certify_claim('t/n', five, _FULL_WINDOW)
    assert cert.certified is False
    assert 'measurement_owned' in cert.missing
