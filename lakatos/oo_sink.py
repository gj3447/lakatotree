"""oo(OpenObserve) 적재 — LTDD: cid 구조화 trace 를 외부 정본에 ship (out-of-band, 개발머신 밖).

게이트: CONSUMER_LOGS_E2E=1 ∧ OO_PASS env. 없으면 no-op(로컬 테스트는 emit 캡처/opener 주입으로 검증).
시크릿은 env 로만(코드/문서 baked default 금지). marquez_sink 와 동형(opener 주입 = 네트워크 없이 검증).
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


def ship(records: list, stream: str = 'tests', *, opener=None, timeout: float = 10.0):
    """구조화 로그 리스트를 oo stream 으로 POST (게이트 OFF 면 no-op=None).

    opener(request, timeout) 주입 시 네트워크 없이 테스트 (marquez_sink 동형 패턴).
    시크릿(OO_PASS)은 env 로만 읽고 baked default 금지.
    """
    if not enabled() or not records:
        return None
    user = _cfg('OO_USER', 'root@consumer.local')
    org = _cfg('OO_ORG', 'default')
    base = _cfg('OO_URL', 'http://localhost:5080')
    auth = 'Basic ' + base64.b64encode(f"{user}:{os.environ['OO_PASS']}".encode()).decode()
    req = urllib.request.Request(
        f'{base}/api/{org}/{stream}/_json', data=json.dumps(records).encode(),
        method='POST', headers={'Authorization': auth, 'Content-Type': 'application/json'})
    _open = opener or (lambda request, timeout: urllib.request.urlopen(request, timeout=timeout))
    with _open(req, timeout=timeout) as r:
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
