"""나생문 수정 검증 — record_derivation 불변식(CON-2) + Marquez 502(BLOCKER) + 직렬화 일관성.

엔드포인트 함수를 직접 호출(HTTP 프레임 우회) — kg/pg/_load_lineage 포트만 monkeypatch.
# KG: span_lakatotree_server_endpoints_fcon1 / q-lkt-dead-adapters
"""
import importlib
import os

import pytest
from fastapi import HTTPException

from lakatos.lineage import Derivation
from lakatos.adapters import MarquezClientError


def load_app():
    os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
    os.environ.setdefault("NEO4J_USER", "neo4j")
    os.environ.setdefault("NEO4J_PASSWORD", "test")
    return importlib.import_module("server.app")


# === CON-2: 비-source 산출물은 inputs 필수 (write-path 불변식 게이트) ===
def test_record_derivation_rejects_nonsource_empty_inputs(monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, "kg", lambda *a, **k: [])   # 호출되면 안 됨(검증이 먼저)
    d = app.DerivationIn(output="x.json", output_sha="x", kind="final", inputs=[])
    with pytest.raises(HTTPException) as e:
        app.record_derivation(d)
    assert e.value.status_code == 400


def test_record_derivation_allows_source_empty_inputs(monkeypatch):
    app = load_app()
    seen = []
    monkeypatch.setattr(app, "kg", lambda *a, **k: seen.append(1) or [])
    monkeypatch.setattr(app, "pg", lambda: (_ for _ in ()).throw(RuntimeError("pg skipped")))
    d = app.DerivationIn(output="raw.zdf", output_sha="z", kind="source", inputs=[])
    # source 는 검증 통과 → kg 호출까지 진행(pg 에서 막아도 검증은 넘김 확인)
    with pytest.raises(RuntimeError, match="pg skipped"):
        app.record_derivation(d)
    assert seen  # kg 가 불렸다 = 400 안 났다


# === BLOCKER: Marquez 전송 실패 → 502 (500 누수 금지) ===
ART = [Derivation(output="raw.zdf", output_sha="z", producer="", producer_sha="", inputs=[], kind="source"),
       Derivation(output="final.json", output_sha="f", producer="s.py", producer_sha="ps",
                  inputs=[("raw.zdf", "z")], kind="final")]


def test_marquez_endpoint_503_when_disabled(monkeypatch):
    app = load_app()
    monkeypatch.delenv("MARQUEZ_URL", raising=False)
    with pytest.raises(HTTPException) as e:
        app.send_artifact_to_marquez("final.json")
    assert e.value.status_code == 503


def test_marquez_endpoint_502_on_client_error(monkeypatch):
    app = load_app()
    monkeypatch.setenv("MARQUEZ_URL", "http://marquez:5000")
    monkeypatch.setattr(app, "_load_lineage", lambda: ART)
    from lakatos import marquez_sink
    monkeypatch.setattr(marquez_sink, "ship",
                        lambda events, **k: (_ for _ in ()).throw(MarquezClientError("conn refused")))
    with pytest.raises(HTTPException) as e:
        app.send_artifact_to_marquez("final.json")
    assert e.value.status_code == 502


def test_marquez_endpoint_404_unknown_artifact(monkeypatch):
    app = load_app()
    monkeypatch.setenv("MARQUEZ_URL", "http://marquez:5000")
    monkeypatch.setattr(app, "_load_lineage", lambda: ART)
    with pytest.raises(HTTPException) as e:
        app.send_artifact_to_marquez("nope.json")
    assert e.value.status_code == 404


# === CROSS_ENDPOINT: GET /api/openlineage 와 POST .../marquez 가 동일 event 직렬화 ===
def test_marquez_sends_same_events_as_openlineage_endpoint(monkeypatch):
    app = load_app()
    monkeypatch.setenv("MARQUEZ_URL", "http://marquez:5000")
    monkeypatch.setattr(app, "_load_lineage", lambda: ART)
    captured = {}
    from lakatos import marquez_sink
    monkeypatch.setattr(marquez_sink, "ship", lambda events, **k: captured.update(events=events) or [{"status": 200}])
    read_events = app.artifact_openlineage("final.json")["events"]   # GET 직렬화
    app.send_artifact_to_marquez("final.json")                       # POST 전송

    def _strip_time(evs):   # eventTime 은 호출시각이라 불가피하게 다름 — 구조만 비교
        return [{k: v for k, v in e.items() if k != "eventTime"} for e in evs]
    assert _strip_time(captured["events"]) == _strip_time(read_events)   # drift 회귀 방어
