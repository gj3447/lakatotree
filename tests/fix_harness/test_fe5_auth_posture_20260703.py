"""FE5 auth_posture 관측화 — 무인증 open-write 를 보이게 한다 (측정주권 PROM 2026-07-03).

테제(선행 [[measurement-sovereignty-prom-20260703]] 비평 #1): 무인증 DEFAULT(LAKATOS_API_TOKEN
미설정 → _bearer_auth no-op → 모든 mutating 요청 무인증)는 blast-radius=전 연구그래프인데 *보이지
않았다* — 신원(open-write)이 co-fundamental A-blocker인데 관측 불가였다. FE5 는 이 자세(auth posture)를
관측화한다(확정결정: 무토큰 부팅거부 NO, **open-but-observable**):

  3값 사다리(강→약): token_required > irreversible_attested > open
  · /version 이 현재 posture 공시  · open 부팅은 loud WARN(부팅은 안 막음)

★irreversible_attested 는 AG5-IDENT(비가역 verb 서명강제) 착륙 시 live — 현재는 taxonomy 슬롯만(dead).

  guard_defect    = test_open_boot_warns          (음성: open 인데 WARN 안 하면 RED — 무음 open 재발)
  guard_mechanism = test_posture_taxonomy          (양성: 3값 사다리 분류 실재)

novel_script = 이 파일. # KG 거울: LakatosTree_MeasurementSovereignty_20260703 / fe5_auth_posture
"""
from __future__ import annotations

import os
from pathlib import Path

from server.auth_posture import POSTURES, classify, open_posture_warning

ROOT = Path(__file__).resolve().parents[2]


# ── (A) 순수 사다리 ────────────────────────────────────────────────────────────────
def test_posture_taxonomy():
    """guard_mechanism: 3값 사다리 — 토큰 최강, 비가역서명 중간, 무인증 open."""
    assert classify(True) == "token_required"
    assert classify(True, irreversible_attested=True) == "token_required"   # 토큰이 이긴다
    assert classify(False, irreversible_attested=True) == "irreversible_attested"
    assert classify(False, irreversible_attested=False) == "open"
    assert set(POSTURES) == {"token_required", "irreversible_attested", "open"}


def test_open_boot_warns():
    """guard_defect: open 자세 → loud WARN 메시지(부팅 안 막음), 그 외 → None(과잉경보 아님).

    open_posture_warning 을 무력화(항상 None)하면 무음 open 부팅이 재발 → 이 가드 RED(revert-민감)."""
    w = open_posture_warning("open")
    assert w and "LAKATOS_API_TOKEN" in w and "blast-radius" in w, w
    assert open_posture_warning("token_required") is None
    assert open_posture_warning("irreversible_attested") is None


# ── (B) 배선: /version 공시 + env 반영 + lifespan WARN ────────────────────────────────
def _load_app():
    os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
    os.environ.setdefault("NEO4J_USER", "neo4j")
    os.environ.setdefault("NEO4J_PASSWORD", "test")
    import importlib
    return importlib.import_module("server.app")


def test_current_posture_reads_env(monkeypatch):
    app = _load_app()
    monkeypatch.setenv("LAKATOS_API_TOKEN", "s3cr3t")
    assert app._current_auth_posture() == "token_required"
    monkeypatch.delenv("LAKATOS_API_TOKEN", raising=False)
    assert app._current_auth_posture() == "open"   # 무토큰 = open(현 기본)


def test_version_exposes_auth_posture():
    """/version 이 auth_posture 를 공시 → 배포 프로브가 무인증 자세를 관측(G2 stale 공시와 동일 표면)."""
    from fastapi.testclient import TestClient

    app = _load_app()
    body = TestClient(app.app).get("/version").json()
    assert body.get("auth_posture") in POSTURES, body


def test_lifespan_wires_open_warning():
    """소스 계약: lifespan startup 이 open_posture_warning 을 logger.warning 으로 흘린다(무음 open 봉쇄)."""
    src = (ROOT / "server" / "app.py").read_text(encoding="utf-8")
    assert "open_posture_warning" in src and "logger.warning" in src
    assert "'auth_posture'" in src or '"auth_posture"' in src   # /version 배선


guard_defect = "test_open_boot_warns"
guard_mechanism = "test_posture_taxonomy"
