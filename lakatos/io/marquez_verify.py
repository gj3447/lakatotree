"""Marquez positive verification — write→독립 read→compare 왕복 (M11, 항상 ON, actor 분리).

marquez_sink.ship 은 `POST /api/v1/lineage` 의 '예외 없음/200' 으로 적재를 *보고*만 한다(fire-and-forget).
이 모듈이 *실제 Marquez 도착* 을 positive 단언한다 — producer(ship 의 writer opener)가 쓴 run 을 *분리된*
reader(readback GET opener)가 읽어 대조. drop(silent ingest loss)이면 reader 가 못 읽어 RED(이빨 있음).

M9 는 oo 백엔드에만 이 왕복을 뒀고 Marquez 는 fire-and-forget 으로 남겼다(M11). oo_verify 의
OoRoundtripStore/assert_positive_roundtrip 패턴을 Marquez HTTP 경로로 동형 차용한다 — store 를 통해서만
정보가 흐르므로 같은 프로세스가 만든 응답을 그 프로세스가 대조하는 '영수증 연극' 이 구조적으로 불가능.
# KG: span_lakatotree_marquez_sink / span_lakatotree_design_audit_20260625
"""
from __future__ import annotations

import json
import urllib.request
from contextlib import contextmanager

from lakatos.io import marquez_sink

_RUNS_PATH = "/api/v1/jobs/runs/"   # 독립 readback: GET {base}/api/v1/jobs/runs/{runId}


class _CannedResp:
    """urllib 응답 모양(컨텍스트 매니저 + read() + status)을 흉내내는 in-process 응답."""

    def __init__(self, obj, status: int = 200):
        self._b = json.dumps(obj).encode()
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._b


def _run_id_of(event: dict) -> str:
    return ((event.get("run") or {}).get("runId")) or ""


def _run_id_from_url(url: str) -> str:
    i = url.find(_RUNS_PATH)
    return url[i + len(_RUNS_PATH):].split("?")[0] if i >= 0 else ""


class MarquezRoundtripStore:
    """ship 의 `POST /api/v1/lineage` 를 받아 run 별 event 를 보관하고, readback `GET /jobs/runs/{id}` 로
    되읽는 *in-process* Marquez 에뮬레이터.

    핵심은 **분리된 두 opener**: `writer_opener` 는 POST 를 받아 store 에 *쓰기*만, `reader_opener` 는
    readback GET 을 받아 store 에서 *읽기*만 한다. 오직 store 를 통해서만 정보가 흐른다 → producer 가
    만든 응답을 그 producer 가 대조하는 일이 불가능(Pact 식 consumer-driven contract actor 분리).
    """

    def __init__(self) -> None:
        self._by_run: dict[str, list[dict]] = {}   # runId → [event...] (공유 store)

    def writer_opener(self):
        def _writer(request, timeout=None):   # noqa: ARG001
            event = json.loads(request.data.decode())
            self._by_run.setdefault(_run_id_of(event), []).append(event)
            return _CannedResp({"status": "ok"}, status=200)
        return _writer

    def reader_opener(self):
        def _reader(request, timeout=None):   # noqa: ARG001
            run_id = _run_id_from_url(request.get_full_url())
            events = self._by_run.get(run_id, [])
            if not events:   # 미도착(silent loss) → Marquez 가 404 내듯
                return _CannedResp({"present": False, "runId": run_id, "count": 0}, status=404)
            return _CannedResp({"present": True, "runId": run_id, "count": len(events)}, status=200)
        return _reader

    def opener(self):
        """단일 opener — *자기응답 안티패턴*(writer==reader)을 테스트가 만들기 위한 헬퍼(실사용 금지)."""
        def _both(request, timeout=None):   # noqa: ARG001
            raise AssertionError("writer==reader opener 는 영수증 연극 — 분리하라")
        return _both


def marquez_readback(run_id: str, *, base_url: str, opener, timeout: float = 10.0) -> dict:
    """독립 GET readback — run 이 Marquez 에 실재(queryable)한지 확인. ship 과 *다른* opener 로 호출.

    반환 {ok, runId, read_back, reasons}. 404/예외면 ok=False(미도착=silent ingest loss)."""
    url = f"{base_url.rstrip('/')}{_RUNS_PATH}{run_id}"
    req = urllib.request.Request(url, method="GET")
    try:
        with opener(req, timeout=timeout) as r:
            present = json.loads(r.read().decode())
    except Exception as exc:   # noqa: BLE001
        return {"ok": False, "runId": run_id, "read_back": 0, "reasons": [f"readback_error:{type(exc).__name__}"]}
    if not present.get("present"):
        return {"ok": False, "runId": run_id, "read_back": 0, "reasons": ["run_not_found_in_marquez"]}
    return {"ok": True, "runId": run_id, "read_back": int(present.get("count") or 0), "reasons": []}


@contextmanager
def _hermetic_marquez_gate():
    """ship 게이트 env(MARQUEZ_URL)를 in-process 더미로 켜고 끝나면 원상복구(전역 오염 방지).
    opener 주입이 실제 HTTP 를 전부 가로채므로 네트워크/실자격증명 없이 hermetic."""
    import os
    keys = {"MARQUEZ_URL": "http://marquez.roundtrip.local:5000"}
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


def _events(run_id: str, n_events: int) -> list[dict]:
    """positive 왕복 기본 OpenLineage event(run.runId 공유) — drop 케이스가 전부를 뺀다."""
    return [{"eventType": "COMPLETE", "eventTime": f"2026-06-26T00:00:0{i}Z",
             "run": {"runId": run_id}, "job": {"namespace": "lakatotree", "name": f"derivation::{i}"}}
            for i in range(n_events)]


def _roundtrip(*, run_id: str, n_events: int, writer, reader, drop: bool = False) -> dict:
    """ship(writer opener)→ marquez_readback(reader opener)→ compare 의 *분리된* 왕복.

    writer 와 reader 가 *같은 객체*면 ValueError(영수증 연극 차단). drop=True 면 ship 을 건너뛰어
    silent ingest loss 를 시뮬(독립 reader 가 못 읽어 ok=False).
    """
    if writer is reader:
        raise ValueError("roundtrip writer 와 reader 가 동일(same opener) — actor 분리 위반(영수증 연극)")
    with _hermetic_marquez_gate():
        import os
        base = os.environ["MARQUEZ_URL"]
        if not drop:
            marquez_sink.ship(_events(run_id, n_events), opener=writer)   # producer: 실 ship 경로로 쓴다
        return marquez_readback(run_id, base_url=base, opener=reader)     # 독립 reader: GET 으로 대조


def assert_positive_roundtrip(*, run_id: str = "marquez-positive-roundtrip",
                              n_events: int = 3, drop: bool = False) -> dict:
    """Marquez write→*독립* read→compare 의 positive 왕복을 단언(항상 ON, env 불요).

    정상 ship 이면 독립 reader 가 run 을 GET readback 으로 읽어 GREEN. drop=True 면 ship 누락(silent
    ingest loss, M9 가 닫으려던 그 실패모드)을 시뮬 → reader 가 못 읽어 AssertionError(왕복의 *이빨*).
    M11 해소: Marquez 경로에도 write→독립read→compare 왕복을 둬 fire-and-forget 비대칭 제거.
    """
    store = MarquezRoundtripStore()
    v = _roundtrip(run_id=run_id, n_events=n_events,
                   writer=store.writer_opener(), reader=store.reader_opener(), drop=drop)
    if not v.get("ok"):
        raise AssertionError(
            f"Marquez round-trip lost: ship→독립read→compare 가 미도착/불일치 — reasons={v.get('reasons')} "
            f"(drop={drop}). 독립 reader 가 producer 가 쓴 run({run_id})을 GET 으로 읽지 못함 = silent ingest loss.")
    # 나생문 #10: presence(ok) 만으론 *부분* 적재유실(3 중 1 남음)을 못 잡는다 → read_back 을 ship 한 n_events 와
    #   대조(oo_verify outcomes<expect_total 동형). M11 비대칭의 나머지 절반(부분 drop=RED) 봉합.
    if not drop and v.get("read_back") != n_events:
        raise AssertionError(
            f"Marquez round-trip partial loss: ship {n_events} → 독립 readback {v.get('read_back')} "
            f"(부분 ingest 유실; run {run_id}). presence 만으론 못 잡던 비대칭 — oo outcomes<expect_total 동형.")
    return v
