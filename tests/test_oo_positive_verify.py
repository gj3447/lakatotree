"""oo positive verifier 단위 테스트 — LTDD positive 단언 로직(오프라인, _search 모킹).

실 oo 없이 verify() 의 판정(session 실재=GREEN / 부재=RED / 합계불일치=RED)을 핀.
실 oo 왕복은 scripts/oo_positive_verify.py 가 CI/수동으로 수행(이 테스트는 로직만).
"""
import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    'oo_positive_verify', Path(__file__).resolve().parents[1] / 'scripts' / 'oo_positive_verify.py')
ov = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ov)


def _patch(monkeypatch, hits):
    monkeypatch.setattr(ov, '_search', lambda sql, **k: hits)


def test_verify_green_when_session_present(monkeypatch):
    _patch(monkeypatch, [
        {'event': 'test_session', 'passed': 25, 'failed': 0, 'total': 25, 'skipped': 0,
         'service': 'lakatotree.tests'},
        *[{'event': 'test_outcome'} for _ in range(25)],
    ])
    r = ov.verify('cid', expect_passed=25, expect_total=25)
    assert r['ok'] is True and r['outcomes'] == 25 and r['reasons'] == []


def test_verify_red_when_no_session(monkeypatch):
    _patch(monkeypatch, [{'event': 'test_outcome'}])      # outcomes 만, session 없음 = ingest 일부유실/미적재
    r = ov.verify('cid')
    assert r['ok'] is False and 'no_test_session_trace_in_oo' in r['reasons']


def test_verify_red_on_count_mismatch(monkeypatch):
    _patch(monkeypatch, [{'event': 'test_session', 'passed': 20, 'total': 25,
                          'service': 'lakatotree.tests'}])
    r = ov.verify('cid', expect_passed=25)
    assert r['ok'] is False and any('passed=20' in x for x in r['reasons'])


def test_main_exit_codes(monkeypatch, capsys):
    _patch(monkeypatch, [{'event': 'test_session', 'passed': 3, 'total': 3,
                          'service': 'lakatotree.tests'}])
    assert ov.main(['cid', '--expect-total', '3']) == 0          # GREEN
    _patch(monkeypatch, [])
    assert ov.main(['cid']) == 1                                 # RED (빈 oo)
