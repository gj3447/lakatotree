"""Marquez 전송 sink TDD — env-gate(MARQUEZ_URL) + opener 주입 검증.

전송층은 자격증명(env) 없으면 no-op. 있으면 OpenLineage event 를 Marquez 로 POST.
oo_sink 와 동형 패턴. 네트워크 없이 opener 주입으로 검증.
# KG: span_lakatotree_marquez_sink / q-lkt-dead-adapters
"""
import json

import pytest

from lakatos import marquez_sink


EVENTS = [{"eventType": "COMPLETE", "job": {"name": "solve.py"}}]


def test_disabled_when_no_marquez_url(monkeypatch):
    monkeypatch.delenv("MARQUEZ_URL", raising=False)
    assert marquez_sink.enabled() is False


def test_enabled_when_marquez_url_set(monkeypatch):
    monkeypatch.setenv("MARQUEZ_URL", "http://marquez:5000")
    assert marquez_sink.enabled() is True


def test_ship_noop_when_disabled(monkeypatch):
    monkeypatch.delenv("MARQUEZ_URL", raising=False)
    # opener 가 불려선 안 됨 (no-op)
    called = []
    assert marquez_sink.ship(EVENTS, opener=lambda *a, **k: called.append(1)) is None
    assert called == []


def test_ship_noop_on_empty_events_even_if_enabled(monkeypatch):
    monkeypatch.setenv("MARQUEZ_URL", "http://marquez:5000")
    called = []
    assert marquez_sink.ship([], opener=lambda *a, **k: called.append(1)) is None
    assert called == []


def test_ship_posts_to_marquez_lineage_endpoint(monkeypatch):
    monkeypatch.setenv("MARQUEZ_URL", "http://marquez:5000/")
    monkeypatch.delenv("MARQUEZ_TOKEN", raising=False)
    captured = {}

    class _Resp:
        status = 200
        def read(self): return b'{"ok": true}'
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def opener(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode())
        captured["headers"] = {k.lower(): v for k, v in request.header_items()}
        return _Resp()

    out = marquez_sink.ship(EVENTS, opener=opener, timeout=3.0)
    assert captured["url"] == "http://marquez:5000/api/v1/lineage"
    assert captured["body"] == EVENTS[0]
    assert "authorization" not in captured["headers"]  # 토큰 없으면 무 Authorization
    assert out and out[0]["status"] == 200


def test_ship_includes_bearer_when_token_set(monkeypatch):
    monkeypatch.setenv("MARQUEZ_URL", "http://marquez:5000")
    monkeypatch.setenv("MARQUEZ_TOKEN", "secret-tok")
    captured = {}

    class _Resp:
        status = 201
        def read(self): return b'{}'
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def opener(request, timeout):
        captured["headers"] = {k.lower(): v for k, v in request.header_items()}
        return _Resp()

    marquez_sink.ship(EVENTS, opener=opener)
    assert captured["headers"].get("authorization") == "Bearer secret-tok"
