"""oo positive verification — LTDD 의 *read 절반* (ship 은 oo_sink, write).

LTDD 파이프라인(positive TDD):
    reports ─build─▶ records ─ship─▶ oo ─verify─▶ presence ─policy─▶ verdict
            (pure)          (write,oo_sink)   (read,여기)        (pure,여기)

oo_sink.ship 은 '예외 없음'으로 적재를 *보고*만 한다. 이 모듈이 *실제 oo 도착*을 positive 단언하고
(silent ingest loss 감지 — 2026-06-09 401 사건 22h 미감지 그 실패모드), 정책(경고 vs strict 실패)을
결정하며, conftest 가 부를 단일 오케스트레이터(session_finish)를 제공한다.
# KG: span_lakatotree_oo_sink / lesson-agent-log-tdd-methodology-20260610
"""
import json
import time
import urllib.request

from lakatos.io.oo_sink import _cfg, _endpoint, _open_default, enabled, ship, test_outcome_records


def verify_trace(cid: str, *, stream: str = 'tests', expect_total: int | None = None,
                 retries: int = 6, delay: float = 2.0, minutes_back: int = 60,
                 opener=None, timeout: float = 15.0) -> dict:
    """cid 의 test_session trace 가 oo `stream` 에 실재하는지 retries×delay 폴링(ingestion latency 흡수).

    logs = ground truth — ship 의 '예외 없음' 보고와 달리 *실제 도착*을 positive 단언.
    반환 {ok, attempts, records, outcomes, session{...}, reasons[]}. opener 주입 = 네트워크 없이 테스트.
    """
    # TODO(prom-honesty/3, 적대감사 2026-06-20): CI 에 write→독립read→compare 왕복 테스트가 없음.
    #   모든 oo/marquez 테스트가 opener 를 주입해 *같은 프로세스가 만든 응답*을 대조(영수증 연극).
    #   실네트워크 테스트(test_oo_verify.py:173)는 기본 OFF + 부정경로만. 외부 백엔드 1개로 positive 왕복 고정할 것.
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
    """verify_trace 결과 + 모드 → 빌드 판정 (순수). conftest/CI 정책 단일 정본.

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
                          else '. 재확인: python scripts/oo_positive_verify.py')}


def _default_poll(mode: str) -> tuple:
    return (8, 2.0) if mode == 'strict' else (4, 1.5)   # strict 는 더 길게 폴링(false-fail 줄임)


def session_finish(reports: list, cid: str, *, mode: str = '1', retries: int | None = None,
                   delay: float | None = None, meta: dict | None = None,
                   shipper=None, verifier=None) -> dict:
    """LTDD 세션 종료 오케스트레이터 (build→ship→verify→policy). conftest 가 이것만 부른다.

    게이트 OFF(enabled() False)/리포트 0 → no-op. ship 실패는 경고만(판결 불변). mode='0' → verify 생략.
    반환 {shipped, messages[], fail_build}. conftest = messages 출력 + fail_build 시 exitstatus=1.
    shipper(records)/verifier()=네트워크 없이 오케스트레이션 테스트(주입).
    """
    if not enabled() or not reports:
        return {'shipped': 0, 'messages': [], 'fail_build': False}
    rp, dl = _default_poll(mode)
    retries = rp if retries is None else retries
    delay = dl if delay is None else delay
    _ship = shipper or ship
    try:
        recs = test_outcome_records(reports, cid=cid, meta=meta or {})
        _ship(recs)
    except Exception as exc:   # 관측은 판결을 바꾸지 않는다 — ship 실패는 경고만
        return {'shipped': 0, 'fail_build': False,
                'messages': [f'trace ship skipped ({type(exc).__name__}: {exc}); 빌드 영향 없음']}
    msgs = [f'{len(reports)} test traces shipped → oo tests stream '
            f'(cid={cid}; RCA: trace_cycle("{cid}"))']
    if mode == '0':
        return {'shipped': len(reports), 'messages': msgs, 'fail_build': False}
    n_total = len({r['nodeid'] for r in reports})
    _verify = verifier or (lambda: verify_trace(cid, expect_total=n_total, retries=retries, delay=delay))
    try:
        v = _verify()
        verdict = verify_policy(v, mode)
        msgs.append(verdict['message'] + ('' if v.get('ok') else f' (cid={cid})'))
        return {'shipped': len(reports), 'messages': msgs, 'fail_build': verdict['fail_build']}
    except Exception as exc:
        msgs.append(f'verify skipped ({type(exc).__name__}: {exc})')
        return {'shipped': len(reports), 'messages': msgs, 'fail_build': False}
