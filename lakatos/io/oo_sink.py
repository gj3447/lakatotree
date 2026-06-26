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


def test_outcome_records(reports: list, cid: str, *, service: str = 'lakatotree.tests',
                         meta: dict | None = None) -> list:
    """pytest 결과 → oo 구조화 trace 레코드 — 벤더 ooptdd 의 정본 빌더에 위임 (단일 정본).

    예전엔 lakatotree 가 같은 봉투(_corr/_RANK/distinct-nodeid 세션요약)를 자체 구현했다.
    이제 `ooptdd.domain.model.build_outcome_records` (`_vendor/ooptdd`) 를 그대로 부른다 —
    출력은 종전과 byte-identical(correlation_keys=cid/correlation_id/cycle_id, per-phase event,
    실패 traceback[:2000], distinct nodeid 집계, meta 병합). `service` 기본값은 lakatotree 값을
    유지(서명키는 안 넘김 → sig 없음, 종전과 동일). LTDD '로그=ground truth' 정본을 실제로 소비.
    reports: [{nodeid, outcome('passed'|'failed'|'skipped'), duration, when(,longrepr)}].
    """
    from ooptdd.domain.model import build_outcome_records  # vendored canonical builder
    return build_outcome_records(reports, cid=cid, service=service, meta=meta or {})
