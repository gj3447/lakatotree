"""oo(OpenObserve) 적재 — LTDD: cid 구조화 trace 를 외부 정본에 ship (변조 불가).

게이트: CONSUMER_LOGS_E2E=1 ∧ OO_PASS env. 없으면 no-op(로컬 테스트는 emit 캡처로 검증).
시크릿은 env 로만(코드/문서 baked default 금지).
# KG: lesson-agent-log-tdd-methodology-20260610
"""
import base64
import json
import os
import urllib.request

OO_URL = os.getenv('OO_URL', 'http://localhost:5080')
OO_USER = os.getenv('OO_USER', 'root@consumer.local')
OO_ORG = os.getenv('OO_ORG', 'default')


def enabled() -> bool:
    return os.getenv('CONSUMER_LOGS_E2E') == '1' and bool(os.getenv('OO_PASS'))


def ship(records: list, stream: str = 'tests'):
    """구조화 로그 리스트를 oo stream 으로 (게이트 OFF 면 no-op)."""
    if not enabled() or not records:
        return None
    auth = 'Basic ' + base64.b64encode(f"{OO_USER}:{os.environ['OO_PASS']}".encode()).decode()
    req = urllib.request.Request(
        f'{OO_URL}/api/{OO_ORG}/{stream}/_json', data=json.dumps(records).encode(),
        method='POST', headers={'Authorization': auth, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())
