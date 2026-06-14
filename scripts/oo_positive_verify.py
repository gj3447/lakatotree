#!/usr/bin/env python3
"""oo positive verification — LTDD 의 *빠진 절반*.

conftest 의 oo_sink.ship 은 "예외 없음"으로 적재를 *보고*할 뿐, oo 에 *실제로 도착했는지*는
확인 안 한다(silent ingest loss = 2026-06-09 401 사건이 22h 미감지된 그 실패모드). 이 스크립트가
positive 단언을 한다: 주어진 cycle_id 의 test_session trace 가 oo `tests` 스트림에 *실재*하고
세션 합계(passed/total)가 일치하는지. logs = ground truth.

사용:
  AIRO_LOGS_E2E=1 LAKATOS_TEST_CID=<cid> python -m pytest ...   # ship
  python scripts/oo_positive_verify.py <cid> [--expect-passed N] [--expect-total N]
  → oo 에 trace 실재 + 합계 일치면 exit 0(GREEN), 없으면 exit 1(RED).

env: OO_URL, OO_USER, OO_PASS, (선택) OO_ORG=default. 시크릿은 env 로만.
# KG: span_lakatotree_oo_positive_verify
"""
import argparse
import base64
import json
import os
import sys
import urllib.request


def _search(sql: str, *, minutes_back: int = 60, size: int = 200) -> list:
    base = os.environ['OO_URL'].rstrip('/')
    org = os.getenv('OO_ORG', 'default')
    user, pw = os.environ['OO_USER'], os.environ['OO_PASS']
    now_us = int(__import__('time').time() * 1_000_000)
    body = json.dumps({'query': {
        'sql': sql,
        'start_time': now_us - minutes_back * 60 * 1_000_000,
        'end_time': now_us,
        'size': size,
    }}).encode()
    auth = 'Basic ' + base64.b64encode(f'{user}:{pw}'.encode()).decode()
    req = urllib.request.Request(f'{base}/api/{org}/_search', data=body, method='POST',
                                 headers={'Authorization': auth, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode()).get('hits', [])


def verify(cid: str, *, expect_passed=None, expect_total=None, minutes_back=60) -> dict:
    sql = ("SELECT event, passed, failed, total, skipped, service FROM tests "
           f"WHERE cycle_id = '{cid}'")
    hits = _search(sql, minutes_back=minutes_back)
    sessions = [h for h in hits if h.get('event') == 'test_session']
    outcomes = [h for h in hits if h.get('event') == 'test_outcome']
    ok = bool(sessions)                                       # positive: trace 실재
    reasons = []
    if not sessions:
        reasons.append('no_test_session_trace_in_oo')        # RED: 적재 안 됨(silent loss)
    s = sessions[0] if sessions else {}
    if expect_passed is not None and s.get('passed') != expect_passed:
        ok = False; reasons.append(f"passed={s.get('passed')}!=expect{expect_passed}")
    if expect_total is not None and s.get('total') != expect_total:
        ok = False; reasons.append(f"total={s.get('total')}!=expect{expect_total}")
    return {'ok': ok, 'cid': cid, 'records': len(hits), 'outcomes': len(outcomes),
            'session': {k: s.get(k) for k in ('service', 'passed', 'failed', 'total', 'skipped')},
            'reasons': reasons}


def main(argv=None):
    p = argparse.ArgumentParser(prog='oo_positive_verify')
    p.add_argument('cycle_id')
    p.add_argument('--expect-passed', type=int)
    p.add_argument('--expect-total', type=int)
    p.add_argument('--minutes-back', type=int, default=60)
    a = p.parse_args(argv)
    res = verify(a.cycle_id, expect_passed=a.expect_passed, expect_total=a.expect_total,
                 minutes_back=a.minutes_back)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    if res['ok']:
        print(f"GREEN — oo 에 trace 실재 (session passed={res['session'].get('passed')}/"
              f"{res['session'].get('total')}, outcomes={res['outcomes']})", file=sys.stderr)
        return 0
    print(f"RED — positive 단언 실패: {res['reasons']}", file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
