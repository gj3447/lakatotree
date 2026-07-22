"""OOPTDD emit-adapter — EXTAUDIT S8(2026-07-23) MeasurementLock 를 구조화 이벤트로 영수증화.

규율(ooptdd): 이벤트 리터럴은 이 adapter 에만. verify 가 실제 lakatos.measurement_lock 을 *구동*해:
  ① 입력 봉인(lock_sha deps/env 이동) + lock_key 가 outs 값/grade 제외(입력 지문)
  ② dirty-check(stale_inputs/env_drift/None 보수) + RunCache 재사용
을 구조화 이벤트로 ship.

음성 오라클(no-fake-green): lock_key 가 outs 값을 포함(주장을 키에)하거나 dirty 가 stale 을 놓치면 깨진다.
참고 테스트: lakatotree/tests/test_extaudit_measurement_lock.py
# KG: LakatosTree_LakatoTree_SelfDev_20260612 / v27_extaudit_measurement_lock
"""
import sys

_LKT = __import__("pathlib").Path(__file__).resolve().parents[2].as_posix()
if _LKT not in sys.path:
    sys.path.insert(0, _LKT)

from lakatos.measurement_lock import (RunCache, build_measurement_lock, lock_dirty,   # noqa: E402
                                      lock_key, lock_sha)


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.extaudit.measurement_lock", "event": name, **attrs}


def _lock(**kw):
    base = dict(cmd="python judge.py out.json",
                deps=[{"path": "judge.py", "sha256": "aa"}, {"path": "in.json", "sha256": "bb"}],
                params={"metric_name": "m", "tolerance": 1e-9}, env_sha="env1",
                outs=[{"name": "m", "value": 0.5}],
                measurement_grade="server_regenerated", replay_status="verified")
    base.update(kw)
    return build_measurement_lock(**base)


def verify(backend, cid):
    """MeasurementLock 구동 — 봉인·키·dirty·캐시 증언."""
    # (1) 입력 봉인 + 키가 outs 값 제외.
    base = _lock()
    assert lock_sha(base) == lock_sha(_lock(deps=[{"path": "in.json", "sha256": "bb"},
                                                  {"path": "judge.py", "sha256": "aa"}]))   # 정렬 정규화
    assert lock_sha(base) != lock_sha(_lock(env_sha="env2"))                                # env 이동
    assert lock_key(base) == lock_key(_lock(outs=[{"name": "m", "value": 999.0}])), \
        "lock_key 가 outs 값을 포함(주장을 키에 — 캐시가 거짓말)"
    assert lock_key(base) != lock_key(_lock(deps=[{"path": "judge.py", "sha256": "aa"},
                                                  {"path": "in.json", "sha256": "X"}]))
    backend.ship([_ev(cid, "lock_seals_inputs_key_excludes_outs", lock_sha=lock_sha(base)[:12],
                      lock_key=lock_key(base)[:12])])

    # (2) dirty-check + run-cache.
    stale = lock_dirty(base, current_deps=[{"path": "in.json", "sha256": "MUT"}], current_env_sha="env1")
    drift = lock_dirty(base, current_deps=[{"path": "judge.py", "sha256": "aa"},
                                           {"path": "in.json", "sha256": "bb"}], current_env_sha="env2")
    none_stale = lock_dirty(base, current_deps=[{"path": "in.json", "sha256": None}], current_env_sha="env1")
    assert "stale_inputs" in stale and "env_drift" in drift and "stale_inputs" in none_stale, \
        (stale, drift, none_stale)
    rc = RunCache()
    k = lock_key(base)
    rc.put(k, {"verified": True, "regenerated": 0.5})
    assert rc.get(lock_key(_lock(outs=[{"name": "m", "value": 999.0}]))) == {"verified": True,
                                                                            "regenerated": 0.5}
    backend.ship([_ev(cid, "dirty_check_and_run_cache", stale=stale, drift=drift)])
