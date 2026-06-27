"""FIX-HARNESS (live integration of producer replay) — RED-first 계약.

producer_replay 프리미티브(lakatos/io/replay.py)는 *판정 로직*만 — 채점 스크립트를 *실제로 재실행*해
client metric 을 검증하는 것은 서버가 해야 #1 의 forge 가 런타임에 닫힌다. 이 하네스는 그 *live 통합*을
구현 전에 고정한다(RED-first). 두 축:

  (A) 서버 함수 server.app._producer_replay_for_node(name, tag) -> bool|None
      - 기본(게이트 OFF): None — 스크립트를 *실행하지 않는다*(보안 기본; client 스크립트 server-side 실행은
        위험하므로 opt-in). _reproducible_for_node 동형(None=증명불가, 비차단).
      - 게이트 ON(LAKATOS_REPLAY_EXEC) + sandbox 러너(_replay_run): 노드의 judge_script 를 재실행해 재생성
        metric 이 recorded metric_value 와 일치하는지 io.replay.producer_replay 로 대조 → True/False(위조 적발).
  (B) server.contexts.tree.judgement_service.JudgementService 가 producer_replay_for_node 포트를 받아
      set_verdict 가 synthesize_promotion(producer_replay_verified=...) 로 흘린다(reproducible_for_node 동형).
  (C) gated 통합 e2e(LAKATOS_IT): 실 HTTP + 실 sandbox 실행으로 위조 metric 이 measurement_externally_anchored
      =False 로 잡히는지 — 로컬 skip(실행 환경 필요).

보안 불변: client 스크립트는 *기본적으로 실행되지 않는다*. 실행은 명시 게이트 + sandbox 러너 경유로만 —
임의 server-side exec 금지(#12/#15 의 경로격리 교훈과 정합).

xfail(strict)/skipif: 구현되면 green → strict 가 마커 제거 신호.
# KG: span_lakatotree_engine / span_lakatotree_rebuild
"""
from __future__ import annotations

import os

import pytest

# server.app import 는 NEO4J env 기본값을 요구(연결은 안 함) — #15 하네스와 동일 패턴.
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")


def _node(metric_value: float, judge_script: str = "python score.py", noise_band: float = 0.0):
    return {"judge_script": judge_script, "metric_value": metric_value, "pred_noise_band": noise_band}


# ── (A) 안전 기본(보안): 게이트 OFF → 스크립트 실행 안 함 → None(증명불가, 비차단). ──────────────
@pytest.mark.xfail(reason="LIVE producer-replay: server.app._producer_replay_for_node 미구현 — 기본 비실행(None) 계약; RED until 구현; strict trips when fixed",
                   strict=True)
def test_producer_replay_for_node_default_does_not_execute(monkeypatch):
    import importlib
    app = importlib.import_module("server.app")
    monkeypatch.delenv("LAKATOS_REPLAY_EXEC", raising=False)        # 게이트 OFF
    monkeypatch.setattr(app, "kg", lambda q, **p: [_node(0.99)])
    # 러너가 *불려선 안 된다*(기본 비실행) — 불리면 AssertionError 로 즉시 실패.
    def _must_not_run(cmd):   # noqa: ARG001
        raise AssertionError("게이트 OFF 인데 client 스크립트가 실행됨(보안 위반)")
    monkeypatch.setattr(app, "_replay_run", _must_not_run, raising=False)
    assert app._producer_replay_for_node("tree", "n1") is None


# ── (A) 게이트 ON + 위조: 재실행이 0.50 인데 recorded=0.99 → False(forge 적발). ───────────────────
@pytest.mark.xfail(reason="LIVE producer-replay: 게이트 ON 이면 judge_script 재실행으로 위조 metric 적발(False) 계약; RED until 구현; strict trips when fixed",
                   strict=True)
def test_producer_replay_for_node_catches_fabricated_when_enabled(monkeypatch):
    import importlib
    app = importlib.import_module("server.app")
    monkeypatch.setenv("LAKATOS_REPLAY_EXEC", "1")                  # 게이트 ON
    monkeypatch.setattr(app, "kg", lambda q, **p: [_node(0.99)])    # client 가 0.99 로 보고(위조)
    monkeypatch.setattr(app, "_replay_run", lambda cmd: ("metric=0.50", 0), raising=False)  # 실제 재실행=0.50
    assert app._producer_replay_for_node("tree", "n1") is False


# ── (A) 게이트 ON + 정직: 재실행이 recorded 와 일치 → True(외부검증). ─────────────────────────────
@pytest.mark.xfail(reason="LIVE producer-replay: 게이트 ON + 정직 측정 재실행 일치 → True(외부검증) 계약; RED until 구현; strict trips when fixed",
                   strict=True)
def test_producer_replay_for_node_verifies_honest_when_enabled(monkeypatch):
    import importlib
    app = importlib.import_module("server.app")
    monkeypatch.setenv("LAKATOS_REPLAY_EXEC", "1")
    monkeypatch.setattr(app, "kg", lambda q, **p: [_node(0.50)])
    monkeypatch.setattr(app, "_replay_run", lambda cmd: ("metric=0.50", 0), raising=False)
    assert app._producer_replay_for_node("tree", "n1") is True


# ── (B) 배선: JudgementService 가 producer_replay_for_node 포트를 받는다(set_verdict 가 floor 로 흘림). ──
@pytest.mark.xfail(reason="LIVE producer-replay: JudgementService 가 producer_replay_for_node 포트 미수용 — RED until __init__+set_verdict 배선; strict trips when fixed",
                   strict=True)
def test_judgement_service_accepts_producer_replay_port():
    from server.contexts.tree.judgement_service import JudgementService
    # 포트가 존재해야 함(현재는 TypeError: unexpected kwarg). set_verdict 가 synthesize_promotion 으로 흘린다.
    svc = JudgementService(kg=lambda *a, **k: [], kg_tx=lambda *a, **k: [],
                           hist=lambda *a, **k: None, foundation=lambda *a, **k: None,
                           reproducible_for_node=lambda *a, **k: None,
                           producer_replay_for_node=lambda *a, **k: None)
    assert callable(svc.producer_replay_for_node)


# ── (C) gated 통합 e2e: 실 HTTP + 실 sandbox 실행으로 위조 metric 이 잡히는지(로컬 skip). ───────────
@pytest.mark.skipif(not os.environ.get("LAKATOS_IT"),
                    reason="LAKATOS_IT 미설정 — live producer-replay e2e(실 sandbox 실행) skip")
def test_live_producer_replay_catches_forge_end_to_end():   # pragma: no cover
    # 통합티어: 트리/노드 생성 → 위조 metric_value 로 progressive → set_verdict(CANONICAL) 시 서버가
    # judge_script 를 sandbox 재실행해 불일치 적발 → measurement_externally_anchored=False(또는 승격 플래그).
    # 실 실행 환경(sandbox 러너)·실 Neo4j 필요 → 안정화 후 구현(현재는 계약 자리표시).
    raise NotImplementedError("LAKATOS_IT live producer-replay e2e — sandbox 러너 구현 후 채움")


# 이중 가드 export (defect=위조 적발 / mechanism=정직 외부검증).
guard_defect = "test_producer_replay_for_node_catches_fabricated_when_enabled"
guard_mechanism = "test_producer_replay_for_node_verifies_honest_when_enabled"
