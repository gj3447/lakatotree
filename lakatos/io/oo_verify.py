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
from contextlib import contextmanager

from lakatos.io.oo_sink import (
    _cfg,
    _endpoint,
    _open_default,
    enabled,
    ship,
    test_outcome_records,
)


def verify_trace(cid: str, *, stream: str = 'tests', expect_total: int | None = None,
                 retries: int = 6, delay: float = 2.0, minutes_back: int = 60,
                 opener=None, timeout: float = 15.0) -> dict:
    """cid 의 test_session trace 가 oo `stream` 에 실재하는지 retries×delay 폴링(ingestion latency 흡수).

    logs = ground truth — ship 의 '예외 없음' 보고와 달리 *실제 도착*을 positive 단언.
    반환 {ok, attempts, records, outcomes, session{...}, reasons[]}. opener 주입 = 네트워크 없이 테스트.
    """
    # RESOLVED(prom-honesty/3, 적대감사 2026-06-20 → M9 2026-06-25): write→독립read→compare 의
    #   positive 왕복을 `assert_positive_roundtrip`(아래)이 *항상 ON* 으로 고정한다 — opener 가
    #   crafted hits 를 echo 하던 영수증 연극 대신, producer 가 *실제로 쓴 store* 를 *분리된*
    #   reader 가 읽어 대조(Pact actor 분리: writer opener ≠ reader opener, store 통해서만 정보 흐름).
    #   drop(silent ingest loss, 2026-06-09 그 실패모드)면 reader 가 못 읽어 RED(이빨 있음).
    #   실외부 백엔드 positive 왕복은 test_oo_roundtrip.py(OOPTDD_E2E_BACKEND gated)가 보완.
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
    except Exception as exc:   # 관측은 판결을 바꾸지 않는다 — warn 은 경고만, strict 는 도착보증이라 실패
        return {'shipped': 0, 'fail_build': mode == 'strict',
                'messages': [f'trace ship skipped ({type(exc).__name__}: {exc})'
                             + ('; strict — 도착 미확인으로 빌드 실패' if mode == 'strict' else '; 빌드 영향 없음')]}
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
    except Exception as exc:   # strict 는 도착보증 게이트 — verify 예외도 fail-open 금지(나생문 #23)
        msgs.append(f'verify skipped ({type(exc).__name__}: {exc})'
                    + ('; strict — 도착 미확인으로 빌드 실패' if mode == 'strict' else ''))
        return {'shipped': len(reports), 'messages': msgs, 'fail_build': mode == 'strict'}


# ── M9: write→독립 read→compare positive 왕복 (항상 ON, actor 분리) ─────────────────
#  영수증 연극(같은 프로세스가 만든 crafted hits 를 자기가 대조)을 닫는다. producer(ship 의
#  writer opener)가 *실제로 쓴* store 를 *분리된* reader(verify_trace 의 reader opener)가 읽어
#  대조한다 — Pact 식 consumer-driven contract 의 actor 분리. store 를 통해서만 정보가 흐르므로
#  자기응답이 구조적으로 불가능. memory backend conformance(ooptdd) 패턴을 oo HTTP 경로로 차용.

class OoRoundtripStore:
    """ship/_json 으로 들어온 레코드를 보관하고 _search 로 되읽는 *in-process* oo 에뮬레이터.

    핵심은 **분리된 두 opener**: `writer_opener` 는 oo_sink.ship 의 `/{stream}/_json` POST 를
    받아 store 에 *쓰기*만 하고, `reader_opener` 는 verify_trace 의 `/_search` POST 를 받아
    store 에서 *읽기*만 한다. 두 opener 는 서로 다른 callable(actor 분리)이고 오직 store 를
    통해서만 정보가 흐른다 → producer 가 만든 응답을 그 producer 가 대조하는 일이 불가능.

    네트워크 없이 ship→독립read→compare 의 진짜 왕복을 CI 에서 hermetic 하게 돈다(opener 가
    crafted hits 를 echo 하지 않는다). `assert_positive_roundtrip` 의 기반.
    """

    def __init__(self):
        self._rows: list[dict] = []   # ship 으로 적재된 oo 레코드(공유 store)

    # — writer 측: oo_sink.ship 의 `/{stream}/_json` POST 를 받아 store 에 쓴다 —
    def writer_opener(self):
        def _writer(request, timeout=None):
            payload = json.loads(request.data.decode())
            now_us = int(time.time() * 1_000_000)
            for rec in payload:
                self._rows.append({**rec, '_timestamp': now_us})
            return _CannedResp({'status': [{'successful': len(payload)}]})
        return _writer

    # — reader 측: verify_trace 의 `/_search` POST 를 받아 store 에서 *읽기*만 한다 —
    def reader_opener(self):
        def _reader(request, timeout=None):
            body = json.loads(request.data.decode())
            sql = body.get('query', {}).get('sql', '')
            cid = _cid_from_sql(sql)
            hits = [dict(r) for r in self._rows
                    if (r.get('cid') or r.get('correlation_id') or r.get('cycle_id')) == cid]
            return _CannedResp({'hits': hits})
        return _reader

    def opener(self):
        """단일 opener — *자기응답 안티패턴*(writer==reader)을 테스트가 만들기 위한 헬퍼.
        실사용은 writer_opener()/reader_opener() 를 따로 받아 actor 분리를 지킨다."""
        def _both(request, timeout=None):   # noqa: ARG001
            raise AssertionError('writer==reader opener 는 영수증 연극 — 분리하라')
        return _both


class _CannedResp:
    """urllib 응답 모양(컨텍스트 매니저 + read())을 흉내내는 in-process 응답."""

    def __init__(self, obj):
        self._b = json.dumps(obj).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._b


def _cid_from_sql(sql: str) -> str:
    """verify_trace 가 만든 `... WHERE cycle_id = '<cid>'` 에서 cid 추출(in-process reader 용)."""
    marker = "cycle_id = '"
    i = sql.find(marker)
    if i < 0:
        return ''
    j = sql.find("'", i + len(marker))
    return sql[i + len(marker):j] if j > i else ''


def _roundtrip(*, cid: str, expect_total: int, writer, reader,
               records: list | None = None) -> dict:
    """ship(writer opener)→ verify_trace(reader opener)→ compare 의 *분리된* 왕복.

    actor 분리를 구조적으로 강제: writer 와 reader 가 *같은 객체*면 ValueError(영수증 연극 차단).
    반환은 verify_trace 결과 dict. ship/verify 게이트(CONSUMER_LOGS_E2E∧OO_PASS, OO_URL)는 *in-process
    더미*로 채운다 — opener 가 모든 HTTP 를 가로채므로 네트워크/실자격증명 없이 hermetic 하게 돈다.
    원래 env 는 함수 종료 시 *그대로 복원*(전역 오염 금지).
    """
    if writer is reader:
        raise ValueError('roundtrip writer 와 reader 가 동일(same opener) — actor 분리 위반(영수증 연극)')
    recs = records if records is not None else _default_roundtrip_records(cid, expect_total)
    with _hermetic_oo_gate():
        # producer: 실 oo_sink.ship 경로로 *쓴다*(writer opener). 게이트 ON 이라 실제 ship 경로를 탄다.
        ship(recs, stream='tests', opener=writer)
        # 독립 reader: verify_trace 가 _search 로 store 를 *읽어* 대조(crafted echo 아님).
        return verify_trace(cid, expect_total=expect_total, retries=1, delay=0, opener=reader)


@contextmanager
def _hermetic_oo_gate():
    """ship/verify 게이트 env 를 in-process 더미로 켜고, 끝나면 원상복구(전역 오염 방지).

    CONSUMER_LOGS_E2E=1·OO_PASS·OO_URL 만 채우면 enabled()/_endpoint()/verify_trace 가 실 경로를
    타되, opener 주입이 실제 HTTP 를 전부 가로채므로 네트워크는 일어나지 않는다."""
    import os
    keys = {'CONSUMER_LOGS_E2E': '1', 'OO_PASS': 'roundtrip-dummy',
            'OO_URL': 'http://oo.roundtrip.local:5080'}
    prev = {k: os.environ.get(k) for k in keys}
    os.environ.update(keys)
    try:
        yield
    finally:
        for k, old in prev.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old


def assert_positive_roundtrip(*, cid: str = 'oo-positive-roundtrip',
                              expect_total: int = 3, drop_event: str | None = None) -> dict:
    """oo write→*독립* read→compare 의 positive 왕복을 단언(항상 ON, env 불필요).

    정상 ship 이면 독립 reader 가 session+outcomes 를 읽어 GREEN(반환 dict, ok=True).
    `drop_event` 로 그 종류 이벤트를 ship 전 누락시키면(silent ingest loss, 2026-06-09 그
    실패모드) 독립 reader 가 못 읽어 AssertionError('round-trip lost…') — 왕복의 *이빨*.

    M9 해소: 이 함수가 lakatos oo 경로에 write→독립read→compare 의 진짜 왕복을 *항상* 둔다.
    opener 가 crafted hits 를 echo 하던 영수증 연극이 아니라, producer 가 쓴 store 를 분리된
    reader 가 읽는다(ooptdd assert_backend_conforms 패턴을 oo HTTP 경로로 차용).
    """
    store = OoRoundtripStore()
    records = None
    if drop_event is not None:
        records = [r for r in _default_roundtrip_records(cid, expect_total)
                   if r.get('event') != drop_event]
    v = _roundtrip(cid=cid, expect_total=expect_total,
                   writer=store.writer_opener(), reader=store.reader_opener(),
                   records=records)
    if not v.get('ok'):
        raise AssertionError(
            f"round-trip lost: write→독립read→compare 의 positive 왕복이 미도착/불일치 — "
            f"reasons={v.get('reasons')} (drop_event={drop_event!r}). "
            f"독립 reader 가 producer 가 쓴 trace 를 읽지 못함 = silent ingest loss.")
    return v


def _default_roundtrip_records(cid: str, expect_total: int) -> list:
    """positive 왕복 기본 레코드(outcome×N + session 1) — drop 케이스가 일부를 빼기 위한 정본."""
    return [
        {'cid': cid, 'correlation_id': cid, 'cycle_id': cid, 'service': 'lakatotree.tests',
         'event': 'test_outcome', 'test': f't::{i}', 'outcome': 'passed'}
        for i in range(expect_total)
    ] + [{'cid': cid, 'correlation_id': cid, 'cycle_id': cid, 'service': 'lakatotree.tests',
          'event': 'test_session', 'passed': expect_total, 'failed': 0,
          'total': expect_total, 'skipped': 0}]
