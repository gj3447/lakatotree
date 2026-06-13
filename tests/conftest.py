"""LTDD 백본 — 테스트 판정을 oo `tests` 스트림에 cid 로 묶어 적재(영수증).

라카토트리는 "로그가 ground truth"를 설파한다 (rebuild.py LTDD). 이 conftest 는 그
원칙을 *자기 테스트 스위트*에 적용한다: 매 세션을 correlation_id(cid) 로 묶어
각 테스트 outcome 을 oo 로 ship → 실패 RCA 는 trace_cycle(cid) 한 콜로 전 타임라인 확보.

게이트: oo_sink.enabled() (CONSUMER_LOGS_E2E=1 ∧ OO_PASS) — OFF 면 완전 no-op(로컬 = 조용).
관측은 *판결을 바꾸지 않는다*: ship 실패가 빌드를 깨선 안 된다 → try/except 로 흡수.
cid 는 LAKATOS_TEST_CID env 로 부모 dev-loop 와 공유 가능(없으면 세션 자동 생성).
# KG: span_lakatotree_oo_conftest / lesson-agent-log-tdd-methodology-20260610
"""
import os
import uuid

from lakatos import oo_sink

_REPORTS: list = []
_CID = os.getenv('LAKATOS_TEST_CID') or ('pytest-' + uuid.uuid4().hex[:12])


def pytest_runtest_logreport(report):
    """판정이 정해지는 phase 만 1건 기록 (정상 통과=call 1건, setup 실패/skip=setup 1건)."""
    when = getattr(report, 'when', 'call')
    outcome = getattr(report, 'outcome', 'passed')
    record = (when == 'call'
              or (when == 'setup' and outcome in ('failed', 'skipped'))
              or (when == 'teardown' and outcome == 'failed'))
    if not record:
        return
    _REPORTS.append({
        'nodeid': getattr(report, 'nodeid', '?'),
        'outcome': outcome,
        'duration': getattr(report, 'duration', 0.0),
        'when': when,
        'longrepr': str(getattr(report, 'longrepr', '') or '') if outcome == 'failed' else '',
    })


def pytest_sessionfinish(session, exitstatus):
    """세션 종료 → oo 적재 (게이트 OFF 면 no-op). 실패가 빌드를 깨지 않도록 흡수."""
    if not oo_sink.enabled() or not _REPORTS:
        return
    try:
        recs = oo_sink.test_outcome_records(
            _REPORTS, cid=_CID,
            meta={'exit_status': int(exitstatus), 'suite': 'lakatotree'})
        oo_sink.ship(recs, stream='tests')
        print(f'\n[oo LTDD] {len(_REPORTS)} test traces shipped → oo tests stream '
              f'(cid={_CID}; RCA: trace_cycle("{_CID}"))')
    except Exception as exc:   # 관측은 판결을 바꾸지 않는다 — ship 실패는 경고만
        print(f'\n[oo LTDD] trace ship skipped ({type(exc).__name__}: {exc}); 빌드 영향 없음')
