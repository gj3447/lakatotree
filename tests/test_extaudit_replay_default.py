"""EXTAUDIT S2 — replay 기본 ON 2단 설계 (GO1 flip, sandbox 선언 조건부).

적대감사 2026-07-22 급소 #3 후반: producer replay 로직은 완성돼 있는데 LAKATOS_REPLAY_EXEC 기본
OFF 라 라이브에서 구조적으로 죽은 경로였다(재실행된 유일 표본 67건 중 51건 불일치 — 검증이 안 도는
동안 쌓인 실측). 완전 무조건 ON 은 AG2 보안계약(sandbox 는 운영자 몫) 위반이라 2단으로 뒤집는다:

  LAKATOS_REPLAY_EXEC 명시값        → 그 값이 항상 이긴다 (기존 계약 그대로: ''/'0'/'off' = OFF)
  unset ∧ LAKATOS_REPLAY_SANDBOXED=1 → ON  (운영자가 sandbox 보장을 선언하면 기본 ON — GO1 발효)
  unset ∧ SANDBOXED 미선언/off       → OFF (선언 없는 배포는 기존 거동 불변 — 소급 무회귀)

S1(grade-gate)과 합쳐 인센티브가 완성된다: 선언 없는 배포는 replay 가 안 돌아 client_asserted 가
INCONCLUSIVE 로 남고, 선언한 배포만 server_regenerated 로 진보 credit 을 산다.
# KG: q-extaudit-replay-default-on-20260722 (a)안 / crit-extaudit-20260722-replay-76pct-mismatch
"""
import importlib
import os

os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")


def _app():
    return importlib.import_module("server.app")


# ── guard_defect (음성 오라클): sandbox 선언 시 unset 이 ON 이어야 한다 ──────────────────────
def test_sandboxed_declared_unset_exec_defaults_on(monkeypatch):
    app = _app()
    monkeypatch.delenv("LAKATOS_REPLAY_EXEC", raising=False)
    monkeypatch.setenv("LAKATOS_REPLAY_SANDBOXED", "1")
    assert app._replay_exec_enabled() is True, "sandbox 선언 배포에서 unset=ON 이어야 (GO1 발효)"


def test_sandboxed_truthy_variants_default_on(monkeypatch):
    app = _app()
    monkeypatch.delenv("LAKATOS_REPLAY_EXEC", raising=False)
    for on in ("1", "true", "YES", "on"):
        monkeypatch.setenv("LAKATOS_REPLAY_SANDBOXED", on)
        assert app._replay_exec_enabled() is True, f"SANDBOXED={on!r} 는 기본 ON 이어야"


# ── guard_mechanism (양성 오라클): 선언 없으면 기존 거동 불변, 명시값은 항상 이긴다 ─────────────
def test_undeclared_unset_stays_off(monkeypatch):
    app = _app()
    monkeypatch.delenv("LAKATOS_REPLAY_EXEC", raising=False)
    monkeypatch.delenv("LAKATOS_REPLAY_SANDBOXED", raising=False)
    assert app._replay_exec_enabled() is False, "선언 없는 배포는 기존 OFF 불변(소급 무회귀)"


def test_sandboxed_falsy_stays_off(monkeypatch):
    app = _app()
    monkeypatch.delenv("LAKATOS_REPLAY_EXEC", raising=False)
    for off in ("0", "false", "off", ""):
        monkeypatch.setenv("LAKATOS_REPLAY_SANDBOXED", off)
        assert app._replay_exec_enabled() is False, f"SANDBOXED={off!r} 는 OFF 여야 (boolean 파싱)"


def test_explicit_exec_off_wins_over_sandboxed(monkeypatch):
    # 명시 OFF > 선언 — 운영자가 일시적으로 replay 를 끌 자유 보존 (기존 boolean footgun 계약 유지).
    app = _app()
    monkeypatch.setenv("LAKATOS_REPLAY_SANDBOXED", "1")
    for off in ("0", "false", "off", ""):
        monkeypatch.setenv("LAKATOS_REPLAY_EXEC", off)
        assert app._replay_exec_enabled() is False, f"명시 EXEC={off!r} 가 선언을 이겨야"


def test_explicit_exec_on_without_sandboxed_still_on(monkeypatch):
    # 기존 opt-in 경로 무회귀: SANDBOXED 없이도 명시 ON 은 ON.
    app = _app()
    monkeypatch.delenv("LAKATOS_REPLAY_SANDBOXED", raising=False)
    monkeypatch.setenv("LAKATOS_REPLAY_EXEC", "1")
    assert app._replay_exec_enabled() is True
