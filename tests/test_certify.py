"""P2 인증층 — 5게이트 AND + 근거 없는 PASS 차단 + 시점 한계 명시 검증."""
import pytest

from lakatos.verdict.certify import GATES, Certificate, certify_claim, gate_check, next_actions

WINDOW = {'as_of': '2026-06-12T19:00:00+09:00', 'shas': {'VFEZ0060.zdf': 'abc123'}}


def _all_pass():
    return [gate_check(g, True, f'ref:{g}') for g in GATES]


def test_full_pass_certifies():
    cert = certify_claim('claim-v22-interior-0.9mm', _all_pass(), WINDOW)
    assert cert.certified is True and cert.missing == ()


def test_one_missing_gate_blocks():
    checks = [gate_check(g, True, f'ref:{g}') for g in GATES if g != 'reproducible']
    cert = certify_claim('c', checks, WINDOW)
    assert cert.certified is False
    assert cert.missing == ('reproducible',)
    acts = next_actions(cert)
    assert acts[0]['gate'] == 'reproducible' and 'manifest' in acts[0]['action']


def test_failed_gate_blocks_and_is_visible():
    checks = _all_pass()
    checks[2] = gate_check('stands', False, '', '의문 q-3 미해소')
    cert = certify_claim('c', checks, WINDOW)
    assert cert.certified is False and 'stands' in cert.missing
    by_gate = {c.gate: c for c in cert.checks}
    assert by_gate['stands'].note == '의문 q-3 미해소'   # 부분 통과 은폐 금지


def test_pass_without_evidence_ref_rejected():
    with pytest.raises(ValueError, match='고무도장'):
        gate_check('preregistered', True, '')


def test_duplicate_gate_submission_rejected():
    checks = _all_pass() + [gate_check('grounded', True, 'ref:dup')]
    with pytest.raises(ValueError, match='중복'):
        certify_claim('c', checks, WINDOW)


def test_unknown_gate_rejected():
    with pytest.raises(ValueError, match='미등록'):
        gate_check('vibes', True, 'ref')


def test_evidence_window_as_of_required():
    with pytest.raises(ValueError, match='as_of'):
        certify_claim('c', _all_pass(), {'shas': {}})


def test_limits_disclosed():
    cert = certify_claim('c', _all_pass(), WINDOW)
    assert '절대 보증 아님' in cert.limits
