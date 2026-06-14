"""oo(OpenObserve) 적재 — LTDD: cid 구조화 trace 를 외부 정본에 ship (out-of-band, 개발머신 밖).

게이트: CONSUMER_LOGS_E2E=1 ∧ OO_PASS env. 없으면 no-op(로컬 테스트는 emit 캡처/opener 주입으로 검증).
시크릿은 env 로만(코드/문서 baked default 금지). marquez_sink 와 동형(opener 주입 = 네트워크 없이 검증).
# KG: lesson-agent-log-tdd-methodology-20260610 / span_lakatotree_oo_sink
"""
import base64
import json
import os
import time
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


def verify_trace(cid: str, *, stream: str = 'tests', expect_total: int | None = None,
                 retries: int = 6, delay: float = 2.0, minutes_back: int = 60,
                 opener=None, timeout: float = 15.0) -> dict:
    """★LTDD 의 빠진 절반 — ship 의 '예외 없음' 보고가 아니라 *실제 oo 도착*을 positive 단언.

    cid 의 test_session trace 가 oo `stream` 에 실재하는지 retries×delay 폴링(ingestion latency 흡수).
    logs = ground truth. silent ingest loss(적재 보고됐으나 실제 미도착)를 감지한다.
    반환 {ok, attempts, records, outcomes, session{...}, reasons[]}. opener 주입 = 네트워크 없이 테스트.
    """
    if not _cfg('OO_URL', ''):
        return {'ok': False, 'attempts': 0, 'records': 0, 'outcomes': 0, 'session': {},
                'reasons': ['OO_URL_unset']}
    base, org, auth = _endpoint()
    sql = ("SELECT event, passed, failed, total, skipped, service FROM " + stream +
           f" WHERE cycle_id = '{cid}'")
    _open = opener or _open_default
    for attempt in range(1, max(retries, 1) + 1):
        # ★창은 매 폴링마다 갱신 + 미래 버퍼(+5min). 방금 적재된 레코드의 oo _timestamp 가 verify
        #  시작시각보다 *뒤*(수신시각/클럭 스큐)면 고정창에서 영영 누락되던 race 버그 수정.
        now_us = int(time.time() * 1_000_000)
        body = json.dumps({'query': {'sql': sql, 'start_time': now_us - minutes_back * 60_000_000,
                                     'end_time': now_us + 300_000_000, 'size': 1000}}).encode()
        req = urllib.request.Request(f'{base}/api/{org}/_search', data=body, method='POST',
                                     headers={'Authorization': auth, 'Content-Type': 'application/json'})
        try:
            with _open(req, timeout=timeout) as r:
                hits = json.loads(r.read().decode()).get('hits', [])
        except Exception:
            hits = []
        sessions = [h for h in hits if h.get('event') == 'test_session']
        if sessions:
            s = sessions[0]
            outcomes = sum(1 for h in hits if h.get('event') == 'test_outcome')
            reasons = []
            if expect_total is not None and s.get('total') != expect_total:
                reasons.append(f"total={s.get('total')}!=expect{expect_total}")
            if expect_total is not None and outcomes < expect_total:   # 부분 적재 유실 감지
                reasons.append(f"outcomes={outcomes}<total{expect_total}_partial_loss")
            return {'ok': not reasons, 'attempts': attempt, 'records': len(hits), 'outcomes': outcomes,
                    'session': {k: s.get(k) for k in ('service', 'passed', 'failed', 'total', 'skipped')},
                    'reasons': reasons}
        if attempt < retries:
            time.sleep(delay)
    return {'ok': False, 'attempts': max(retries, 1), 'records': 0, 'outcomes': 0, 'session': {},
            'reasons': ['no_test_session_trace_in_oo_after_poll']}


def verify_policy(v: dict, mode: str) -> dict:
    """verify_trace 결과 + 모드 → 빌드 판정 (순수, 테스트 가능). conftest/CI 정책 단일 정본.

    mode: '1'(기본=경고, '관측은 판결을 바꾸지 않는다' 보존) | 'strict'(미도착=세션 실패) | '0'(off, 호출 전 처리).
    반환 {level, fail_build, message}. strict 에서만 fail_build=True → conftest 가 exitstatus=1.
    """
    if v.get('ok'):
        s = v.get('session', {})
        return {'level': 'ok', 'fail_build': False,
                'message': f"✅ oo 도착 확인 (session {s.get('passed')}/{s.get('total')}, "
                           f"outcomes={v.get('outcomes')}, {v.get('attempts')} attempt)"}
    fail = (mode == 'strict')
    return {'level': 'error' if fail else 'warn', 'fail_build': fail,
            'message': f"{'❌' if fail else '⚠️'} oo 도착 *미확인* ({v.get('reasons')}) — silent ingest loss 의심"
                       + (' — ★strict: 세션 실패(exit 1)' if fail
                          else f". 재확인: python scripts/oo_positive_verify.py")}


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
