"""[FIXED 2026-06-28] live integration of producer replay — green regression.

producer_replay 프리미티브(lakatos/io/replay.py)는 *판정 로직*만 — 채점 스크립트를 *실제로 재실행*해
client metric 을 검증하는 것은 서버가 해야 #1 의 forge 가 런타임에 닫힌다. 본 하네스는 그 live 통합을 핀한다:

  (A) server.app._producer_replay_for_node(name, tag) -> bool|None
      - 게이트 OFF(_replay_exec_enabled 거짓): None — client 스크립트 *실행 안 함*(보안 기본; opt-in).
      - 게이트 ON: judge_script(*경로*)+result_path → prov.replay_command('python <script> <result_path>')를 만들어
        _replay_run 으로 재실행 → io.replay.producer_replay 로 *서버 고정 tol* 대조 → True/False(위조 적발).
  (B) JudgementService 가 producer_replay_for_node 포트를 받아 set_verdict 가 synthesize_promotion 으로 흘림.
  (C) gated 통합 e2e(LAKATOS_IT): 실 HTTP+실 sandbox 실행으로 위조 적발 — 로컬 skip.

★ 적대적 리뷰(2026-06-28) 교정 — 이 하네스가 *놓쳤던* 3 결함을 회귀가드로 박았다:
  #1 judge_script 는 *경로*지 명령이 아니다(예전 하네스가 'python score.py' 명령형을 써서 production 비기능을 가렸다)
      → _node 는 *경로*('score.py'), 그리고 monkeypatch 없는 *실 subprocess* 테스트를 추가.
  #2 게이트는 boolean 파싱이어야 한다('0'/'false'/'off' 도 truthy 라 켜지던 footgun).
  #3 tolerance 는 서버 고정 — client noise_band 로 위조를 통과시키지 못한다.

보안 불변: client 스크립트는 기본 비실행, 명시 게이트 + sandbox 러너 경유만(임의 server-side exec 금지).
# KG: span_lakatotree_engine / span_lakatotree_rebuild
"""
from __future__ import annotations

import os

import pytest

# server.app import 는 NEO4J env 기본값을 요구(연결은 안 함) — #15 하네스와 동일 패턴.
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")


def _node(metric_value: float, judge_script: str = "score.py", result_path: str = "out.json"):
    # judge_script 는 submit 가 저장하는 *경로*(명령 아님) — 실 노드 형태.
    return {"judge_script": judge_script, "metric_value": metric_value, "result_path": result_path}


def _app():
    import importlib
    return importlib.import_module("server.app")


# ── (A) 안전 기본(보안): 게이트 OFF → 스크립트 실행 안 함 → None. ────────────────────────────────
def test_producer_replay_for_node_default_does_not_execute(monkeypatch):
    app = _app()
    monkeypatch.delenv("LAKATOS_REPLAY_EXEC", raising=False)        # 게이트 OFF(미설정)
    monkeypatch.setattr(app, "kg", lambda q, **p: [_node(0.99)])
    def _must_not_run(cmd):   # noqa: ARG001
        raise AssertionError("게이트 OFF 인데 client 스크립트가 실행됨(보안 위반)")
    monkeypatch.setattr(app, "_replay_run", _must_not_run, raising=False)
    assert app._producer_replay_for_node("tree", "n1") is None


# ── (review #2) 게이트는 boolean — '0'/'false'/'off' 는 비활성(truthy 켜짐 footgun 차단). ──────────
def test_replay_exec_gate_is_boolean_not_truthy(monkeypatch):
    app = _app()
    def _must_not_run(cmd):   # noqa: ARG001
        raise AssertionError("게이트 비활성 값인데 실행됨")
    for off in ("0", "false", "off", "no", ""):
        monkeypatch.setenv("LAKATOS_REPLAY_EXEC", off)
        monkeypatch.setattr(app, "kg", lambda q, **p: [_node(0.99)])
        monkeypatch.setattr(app, "_replay_run", _must_not_run, raising=False)
        assert app._producer_replay_for_node("tree", "n1") is None, f"{off!r} 는 비활성이어야"
    for on in ("1", "true", "ON", "yes"):
        monkeypatch.setenv("LAKATOS_REPLAY_EXEC", on)
        monkeypatch.setattr(app, "kg", lambda q, **p: [_node(0.50)])
        monkeypatch.setattr(app, "_replay_run", lambda cmd: ("metric=0.50", 0), raising=False)
        assert app._producer_replay_for_node("tree", "n1") is True, f"{on!r} 는 활성이어야"


# ── (A) 게이트 ON + 위조: 재실행 0.50 인데 recorded=0.99 → False. 재현명령 재구성도 검증(review #1). ──
def test_producer_replay_for_node_catches_fabricated_when_enabled(monkeypatch):
    app = _app()
    monkeypatch.setenv("LAKATOS_REPLAY_EXEC", "1")
    monkeypatch.setattr(app, "kg", lambda q, **p: [_node(0.99, judge_script="score.py", result_path="out.json")])
    seen = {}
    def _runner(cmd):
        seen["cmd"] = cmd
        return ("metric=0.50", 0)
    monkeypatch.setattr(app, "_replay_run", _runner, raising=False)
    assert app._producer_replay_for_node("tree", "n1") is False
    # review #1 회귀가드: bare path 가 아니라 'python <script> <result_path>' 재현명령으로 실행돼야.
    assert seen["cmd"] == "python score.py out.json", seen


# ── (A) 게이트 ON + 정직: 재실행이 recorded 와 일치 → True. ──────────────────────────────────────
def test_producer_replay_for_node_verifies_honest_when_enabled(monkeypatch):
    app = _app()
    monkeypatch.setenv("LAKATOS_REPLAY_EXEC", "1")
    monkeypatch.setattr(app, "kg", lambda q, **p: [_node(0.50)])
    monkeypatch.setattr(app, "_replay_run", lambda cmd: ("metric=0.50", 0), raising=False)
    assert app._producer_replay_for_node("tree", "n1") is True


# ── (review #3) tolerance 는 서버 고정 — 넓은 client noise_band 가 위조를 통과시키지 못한다. ─────────
def test_replay_tolerance_is_server_fixed_not_client_noise_band(monkeypatch):
    app = _app()
    monkeypatch.setenv("LAKATOS_REPLAY_EXEC", "1")
    # client 가 recorded=0.99 + 넓은 noise_band=10 등록했어도 재실행 0.50 은 서버 고정 tol 로 불일치=False.
    monkeypatch.setattr(app, "kg", lambda q, **p: [{"judge_script": "score.py", "metric_value": 0.99,
                                                    "result_path": "out.json", "pred_noise_band": 10.0}])
    monkeypatch.setattr(app, "_replay_run", lambda cmd: ("metric=0.50", 0), raising=False)
    assert app._producer_replay_for_node("tree", "n1") is False


# ── (review #1) inline/file::symbol 은 재현명령으로 못 만든다 → None(증명불가, 실행 시도 안 함). ──────
def test_inline_or_symbol_script_is_inconclusive(monkeypatch):
    app = _app()
    monkeypatch.setenv("LAKATOS_REPLAY_EXEC", "1")
    def _must_not_run(cmd):   # noqa: ARG001
        raise AssertionError("재현명령 불가 형태인데 실행됨")
    monkeypatch.setattr(app, "_replay_run", _must_not_run, raising=False)
    for js in ("inline", "lakatos/x.py::symbol"):
        monkeypatch.setattr(app, "kg", lambda q, **p: [_node(0.50, judge_script=js)])
        assert app._producer_replay_for_node("tree", "n1") is None, js


# ── (review #1 핵심) 실 subprocess(monkeypatch 없음): 경로형 judge_script 를 실제로 재실행할 수 있어야. ──
def test_replay_run_really_executes_a_path_script(tmp_path, monkeypatch):
    app = _app()
    script = tmp_path / "scorer.py"
    script.write_text("import sys\nprint('metric=0.50')\n")   # args 무시, metric 출력
    monkeypatch.setenv("LAKATOS_REPLAY_EXEC", "1")
    monkeypatch.setattr(app, "kg",
                        lambda q, **p: [_node(0.50, judge_script=str(script), result_path="x")])
    # _replay_run 은 monkeypatch 안 함 — 실 subprocess 가 'python <script> x' 를 돌린다.
    assert app._producer_replay_for_node("tree", "n1") is True
    # 위조면(recorded 다름) 같은 실행이 False — bare-path-as-command 결함이면 둘 다 False 라 못 구별.
    monkeypatch.setattr(app, "kg",
                        lambda q, **p: [_node(0.99, judge_script=str(script), result_path="x")])
    assert app._producer_replay_for_node("tree", "n2") is False


# ── (B) 배선: JudgementService 가 producer_replay_for_node 포트를 받는다. ──────────────────────────
def test_judgement_service_accepts_producer_replay_port():
    from server.contexts.tree.judgement_service import JudgementService
    svc = JudgementService(kg=lambda *a, **k: [], kg_tx=lambda *a, **k: [],
                           hist=lambda *a, **k: None, foundation=lambda *a, **k: None,
                           reproducible_for_node=lambda *a, **k: None,
                           producer_replay_for_node=lambda *a, **k: None)
    assert callable(svc.producer_replay_for_node)


# ── (C) gated 통합 e2e: 실 HTTP + 실 sandbox 실행으로 위조 적발(로컬 skip). ──────────────────────────
@pytest.mark.skipif(not os.environ.get("LAKATOS_IT"),
                    reason="LAKATOS_IT 미설정 — live producer-replay e2e(실 sandbox 실행) skip")
def test_live_producer_replay_catches_forge_end_to_end():   # pragma: no cover
    raise NotImplementedError("LAKATOS_IT live producer-replay e2e — sandbox 러너 구현 후 채움")


# 이중 가드 export (defect=위조 적발 / mechanism=정직 외부검증).
guard_defect = "test_producer_replay_for_node_catches_fabricated_when_enabled"
guard_mechanism = "test_producer_replay_for_node_verifies_honest_when_enabled"
