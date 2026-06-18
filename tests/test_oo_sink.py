"""oo 전송 sink TDD(LTDD) — env-gate(CONSUMER_LOGS_E2E∧OO_PASS) + opener 주입 + 트레이스 빌더.

전송층은 자격증명(env) 없으면 no-op. 있으면 cid 구조화 trace 를 oo stream 으로 POST.
marquez_sink 와 동형 패턴 — 네트워크 없이 opener 주입으로 검증.
# KG: span_lakatotree_oo_sink / lesson-agent-log-tdd-methodology-20260610
"""
import base64
import json

from lakatos.io import oo_sink


RECS = [{'cid': 'c1', 'service': 'lakatotree.tests', 'event': 'test_outcome',
         'test': 't::a', 'outcome': 'passed'}]


def _enable(monkeypatch, pw='secret'):
    monkeypatch.setenv('CONSUMER_LOGS_E2E', '1')
    monkeypatch.setenv('OO_PASS', pw)


def test_disabled_when_gate_off(monkeypatch):
    monkeypatch.delenv('CONSUMER_LOGS_E2E', raising=False)
    monkeypatch.setenv('OO_PASS', 'secret')
    assert oo_sink.enabled() is False


def test_requires_both_flags(monkeypatch):
    monkeypatch.setenv('CONSUMER_LOGS_E2E', '1')
    monkeypatch.delenv('OO_PASS', raising=False)
    assert oo_sink.enabled() is False
    _enable(monkeypatch)
    assert oo_sink.enabled() is True


def test_ship_noop_when_disabled(monkeypatch):
    monkeypatch.delenv('CONSUMER_LOGS_E2E', raising=False)
    called = []
    assert oo_sink.ship(RECS, opener=lambda *a, **k: called.append(1)) is None
    assert called == []


def test_ship_noop_on_empty_records_even_if_enabled(monkeypatch):
    _enable(monkeypatch)
    called = []
    assert oo_sink.ship([], opener=lambda *a, **k: called.append(1)) is None
    assert called == []


def test_ship_posts_json_to_oo_stream_with_basic_auth(monkeypatch):
    _enable(monkeypatch, pw='hunter2')
    monkeypatch.setenv('OO_URL', 'http://oo:5080')
    monkeypatch.setenv('OO_USER', 'root@consumer.local')
    monkeypatch.setenv('OO_ORG', 'default')
    captured = {}

    class _Resp:
        def read(self): return b'{"status":[{"successful":1}]}'
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def opener(request, timeout):
        captured['url'] = request.full_url
        captured['body'] = json.loads(request.data.decode())
        captured['headers'] = {k.lower(): v for k, v in request.header_items()}
        captured['method'] = request.get_method()
        return _Resp()

    out = oo_sink.ship(RECS, stream='tests', opener=opener, timeout=3.0)
    assert captured['url'] == 'http://oo:5080/api/default/tests/_json'
    assert captured['method'] == 'POST'
    assert captured['body'] == RECS
    # Basic auth = base64(user:pass), 시크릿은 env 로만
    raw = base64.b64decode(captured['headers']['authorization'].split()[1]).decode()
    assert raw == 'root@consumer.local:hunter2'
    assert out['status'][0]['successful'] == 1


def test_outcome_records_builds_per_test_plus_session_summary():
    reports = [
        {'nodeid': 'tests/t.py::a', 'outcome': 'passed', 'duration': 0.012, 'when': 'call'},
        {'nodeid': 'tests/t.py::b', 'outcome': 'failed', 'duration': 0.5, 'when': 'call',
         'longrepr': 'AssertionError: boom'},
        {'nodeid': 'tests/t.py::c', 'outcome': 'skipped', 'duration': 0.0, 'when': 'setup'},
    ]
    recs = oo_sink.test_outcome_records(reports, cid='sess-1', meta={'exit_status': 1})
    # per-test (3) + 세션요약 (1)
    assert len(recs) == 4
    assert all(r['cid'] == 'sess-1' for r in recs)          # correlation_id 전파
    per = recs[:3]
    assert [r['event'] for r in per] == ['test_outcome'] * 3
    assert per[0]['outcome'] == 'passed' and per[0]['level'] == 'INFO'
    assert per[1]['outcome'] == 'failed' and per[1]['level'] == 'ERROR'
    assert 'boom' in per[1]['error']                        # 실패 longrepr 동봉
    summary = recs[-1]
    assert summary['event'] == 'test_session'
    assert (summary['total'], summary['passed'], summary['failed'], summary['skipped']) == (3, 1, 1, 1)
    assert summary['level'] == 'ERROR'                      # 실패 있으면 세션 ERROR
    assert summary['exit_status'] == 1                      # meta 병합


def test_outcome_records_all_pass_session_is_info():
    reports = [{'nodeid': 'x', 'outcome': 'passed', 'duration': 0.1, 'when': 'call'}]
    recs = oo_sink.test_outcome_records(reports, cid='s')
    assert recs[-1]['level'] == 'INFO' and recs[-1]['failed'] == 0


def test_outcome_records_carry_correlation_keys_for_trace_cycle():
    # oo trace_cycle 은 correlation_id/cycle_id 컬럼만 병합 → 그 컬럼명으로 동봉돼야 한 콜 RCA 가 묶인다
    recs = oo_sink.test_outcome_records(
        [{'nodeid': 'x', 'outcome': 'passed', 'duration': 0.1, 'when': 'call'}], cid='zzz')
    assert all(r['correlation_id'] == 'zzz' and r['cycle_id'] == 'zzz' for r in recs)


def test_outcome_records_session_counts_are_per_test_not_per_phase():
    # teardown 실패 = call/passed + teardown/failed 두 phase 레코드지만 test 는 1개(=failed)
    reports = [
        {'nodeid': 't::a', 'outcome': 'passed', 'duration': 0.1, 'when': 'call'},
        {'nodeid': 't::a', 'outcome': 'failed', 'duration': 0.0, 'when': 'teardown',
         'longrepr': 'teardown boom'},
    ]
    recs = oo_sink.test_outcome_records(reports, cid='s')
    per = [r for r in recs if r['event'] == 'test_outcome']
    summary = next(r for r in recs if r['event'] == 'test_session')
    assert len(per) == 2                       # phase별 event 보존(RCA 용 teardown traceback)
    assert (summary['total'], summary['failed'], summary['passed']) == (1, 1, 0)
