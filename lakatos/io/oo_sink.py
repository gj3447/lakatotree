"""oo(OpenObserve) write 절반 — LTDD: cid 구조화 trace 를 외부 정본에 ship (out-of-band).

LTDD 파이프라인: reports ─build(test_outcome_records)─▶ records ─ship─▶ oo. read/verify 절반은
oo_verify.py (verify_trace/verify_policy/session_finish). 공용 config/auth(_endpoint)는 여기 정본.

게이트: CONSUMER_LOGS_E2E=1 ∧ OO_PASS env. 없으면 no-op(로컬 = opener 주입으로 검증, 네트워크 없이).
시크릿은 env 로만(코드/문서 baked default 금지). marquez_sink 와 동형(opener 주입 패턴).
# KG: lesson-agent-log-tdd-methodology-20260610 / span_lakatotree_oo_sink
"""
import base64
import json
import os
import urllib.request


def _cfg(key, default):
    return os.getenv(key, default)


def enabled() -> bool:
    return os.getenv('CONSUMER_LOGS_E2E') == '1' and bool(os.getenv('OO_PASS'))


def _endpoint():
    """oo (base, org, auth) — ship/verify 공용(DRY). OO_URL 미설정 시 ValueError(baked default 금지)."""
    base = _cfg('OO_URL', '')
    if not base:   # OPS-INIT-1: 내부 IP baked default 금지(외부배포 깨짐) — env 명시 강제
        raise ValueError('OO_URL 필수 — CONSUMER_LOGS_E2E=1 이면 oo 엔드포인트를 .env 의 OO_URL 로 명시 '
                         '(예: OO_URL=http://<oo-host>:5080). 코드/문서 baked default 금지.')
    auth = 'Basic ' + base64.b64encode(
        f"{_cfg('OO_USER', 'root@consumer.local')}:{os.environ['OO_PASS']}".encode()).decode()
    return base.rstrip('/'), _cfg('OO_ORG', 'default'), auth


def _open_default(request, timeout):
    return urllib.request.urlopen(request, timeout=timeout)


def ship(records: list, stream: str = 'tests', *, opener=None, timeout: float = 10.0):
    """구조화 로그 리스트를 oo stream 으로 POST (게이트 OFF 면 no-op=None).

    opener(request, timeout) 주입 시 네트워크 없이 테스트 (marquez_sink 동형 패턴).
    시크릿(OO_PASS)은 env 로만 읽고 baked default 금지.
    """
    if not enabled() or not records:
        return None
    base, org, auth = _endpoint()
    req = urllib.request.Request(
        f'{base}/api/{org}/{stream}/_json', data=json.dumps(records).encode(),
        method='POST', headers={'Authorization': auth, 'Content-Type': 'application/json'})
    with (opener or _open_default)(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _corr(cid: str) -> dict:
    """correlation 키 — oo `trace_cycle` 은 cycle_id/correlation_id 컬럼만 병합하므로
    `cid` 외에 표준 컬럼명을 동봉해야 'trace_cycle(cid) 한 콜 RCA'가 실제로 동작한다 (나생문 F1-cid)."""
    return {'cid': cid, 'correlation_id': cid, 'cycle_id': cid}


_RANK = {'failed': 2, 'skipped': 1, 'passed': 0}   # 한 test 의 여러 phase 중 가장 심각한 결과


def test_outcome_records(reports: list, cid: str, *, service: str = 'lakatotree.tests',
                         meta: dict | None = None) -> list:
    """pytest 결과 → oo 구조화 trace 레코드 (순수 함수, pytest 비의존).

    LTDD: 로그가 ground truth — 각 테스트 판정을 cid(=correlation_id=cycle_id)로 묶어
    외부 정본에 영수증으로 남긴다. trace_cycle(cid) 한 콜로 전 타임라인 RCA.
    reports: [{nodeid, outcome('passed'|'failed'|'skipped'), duration, when(,longrepr)}].
    반환: per-test event 레코드 N (phase 별, RCA 용 traceback 보존) + 세션요약 1.
    세션요약 집계는 distinct nodeid 기준 (teardown-fail 등 다중 phase 이중계상 방지, 나생문 F2).
    """
    meta = meta or {}
    recs = []
    for r in reports:
        outcome = r['outcome']
        rec = {
            **_corr(cid), 'service': service,
            'level': 'ERROR' if outcome == 'failed' else 'INFO',
            'event': 'test_outcome', 'test': r['nodeid'], 'outcome': outcome,
            'when': r.get('when', 'call'),
            'duration_s': round(float(r.get('duration', 0.0)), 4),
        }
        if outcome == 'failed' and r.get('longrepr'):
            rec['error'] = str(r['longrepr'])[:2000]
        recs.append(rec)
    by_test = {}                                  # nodeid → 가장 심각한 outcome
    for r in reports:
        prev = by_test.get(r['nodeid'])
        if prev is None or _RANK.get(r['outcome'], 0) > _RANK.get(prev, 0):
            by_test[r['nodeid']] = r['outcome']
    passed = sum(1 for o in by_test.values() if o == 'passed')
    failed = sum(1 for o in by_test.values() if o == 'failed')
    skipped = sum(1 for o in by_test.values() if o == 'skipped')
    recs.append({
        **_corr(cid), 'service': service,
        'level': 'ERROR' if failed else 'INFO',
        'event': 'test_session', 'total': len(by_test),
        'passed': passed, 'failed': failed, 'skipped': skipped,
        **meta,
    })
    return recs
