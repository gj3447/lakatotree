"""OOPTDD emit-adapter — EXTAUDIT S2(2026-07-22) replay 기본 ON 2단을 구조화 이벤트 trace 로 영수증화.

규율(ooptdd): 이벤트 리터럴은 엔진이 아니라 이 adapter 에만(server/app.py 불변).
verify 가 실제 server.app._replay_exec_enabled 를 env 조합별로 *구동*해:
  ① unset + SANDBOXED 선언 → True (GO1 발효)
  ② 둘 다 unset → False (무선언 소급 무회귀) / 명시 EXEC off 값이 선언을 이김
을 구조화 이벤트로 ship. env 는 save/restore 로 원상복구(허메틱).

음성 오라클(no-fake-green): 옛 거동(unset=무조건 OFF)이 살아있으면 ①의 assert 가 False 를 보고 깨진다.
참고 테스트: lakatotree/tests/test_extaudit_replay_default.py
# KG: LakatosTree_LakatoTree_SelfDev_20260612 / v20_extaudit_replay_default
"""
import os
import sys

_LKT = __import__("pathlib").Path(__file__).resolve().parents[2].as_posix()
if _LKT not in sys.path:
    sys.path.insert(0, _LKT)

os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")

_KEYS = ("LAKATOS_REPLAY_EXEC", "LAKATOS_REPLAY_SANDBOXED")


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.extaudit.replay_default", "event": name, **attrs}


def _with_env(exec_val, sandboxed_val, fn):
    saved = {k: os.environ.get(k) for k in _KEYS}
    try:
        for k, v in (("LAKATOS_REPLAY_EXEC", exec_val), ("LAKATOS_REPLAY_SANDBOXED", sandboxed_val)):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return fn()
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def verify(backend, cid):
    """2단 게이트 구동 — 실제 _replay_exec_enabled 로 발효·무회귀·우선순위 증언."""
    from server.app import _replay_exec_enabled

    # (1) 음성 오라클: 선언 배포에서 unset=ON. 옛 unset=무조건 OFF 가 살아있으면 여기서 깨진다.
    on = _with_env(None, "1", _replay_exec_enabled)
    assert on is True, f"SANDBOXED 선언인데 unset 이 OFF(옛 거동 잔존): {on}"
    backend.ship([_ev(cid, "sandboxed_unset_defaults_on", enabled=on)])

    # (2) 무선언 무회귀 + 명시값 우선(과잉 발효 방지 이중가드 — vacuous-on 아님).
    off_undeclared = _with_env(None, None, _replay_exec_enabled)
    off_explicit = _with_env("0", "1", _replay_exec_enabled)
    off_empty = _with_env("", "1", _replay_exec_enabled)
    assert off_undeclared is False, f"무선언 배포가 켜짐(소급 발효 — 과잉): {off_undeclared}"
    assert off_explicit is False, f"명시 EXEC=0 이 선언에 짐: {off_explicit}"
    assert off_empty is False, f"명시 EXEC='' 이 선언에 짐(boolean footgun 재발): {off_empty}"
    backend.ship([_ev(cid, "undeclared_off_and_explicit_wins",
                      undeclared=off_undeclared, explicit_zero=off_explicit, explicit_empty=off_empty)])
