"""EXTAUDIT S8 — MeasurementLock: 측정 입력 봉인 + run-cache (DVC lock 흡수).

급소 #3 잔여: receipt v3 조차 judge_script_sha 하나만 현실 앵커 — 입력 데이터/환경/출력이 봉인 밖.
DVC dvc.lock 이식: (cmd, deps 서버해시, params, env_sha) → outs 함수적 봉인. lock_key run-cache 로
재검증 1회 상각. 사이드카(receipt 불변). # KG: q-extaudit-replay-default-on-20260722 잔여
"""
from lakatos.measurement_lock import (RunCache, build_measurement_lock, lock_dirty, lock_key,
                                      lock_sha)


def _lock(**kw):
    base = dict(cmd="python judge.py out.json",
                deps=[{"path": "judge.py", "sha256": "aa"}, {"path": "in.json", "sha256": "bb"}],
                params={"metric_name": "m", "tolerance": 1e-9}, env_sha="env1",
                outs=[{"name": "m", "value": 0.5}],
                measurement_grade="server_regenerated", replay_status="verified")
    base.update(kw)
    return build_measurement_lock(**base)


# ── 봉인 결정론 + deps 정렬 ──────────────────────────────────────────────────────────────
def test_lock_sha_deterministic_and_dep_order_invariant():
    a = _lock()
    b = _lock(deps=[{"path": "in.json", "sha256": "bb"}, {"path": "judge.py", "sha256": "aa"}])
    assert lock_sha(a) == lock_sha(b)                      # deps 정렬 정규화
    assert lock_sha(a) == lock_sha(_lock())               # 결정론


def test_dep_sha_change_moves_lock_sha():
    assert lock_sha(_lock()) != lock_sha(_lock(deps=[{"path": "judge.py", "sha256": "aa"},
                                                     {"path": "in.json", "sha256": "CHANGED"}]))
    assert lock_sha(_lock()) != lock_sha(_lock(env_sha="env2"))   # env 변화도 봉인 이동


# ── run-cache 키: outs 값·grade·status 제외, 나머지 동일이면 같은 키 ─────────────────────────
def test_lock_key_excludes_outs_value_and_grade():
    base = _lock()
    diff_out = _lock(outs=[{"name": "m", "value": 999.0}])          # 값만 다름
    diff_grade = _lock(measurement_grade="client_asserted", replay_status="not_attempted")
    assert lock_key(base) == lock_key(diff_out) == lock_key(diff_grade)   # 키는 입력 지문
    # 입력(deps)이 다르면 키도 다르다.
    assert lock_key(base) != lock_key(_lock(deps=[{"path": "judge.py", "sha256": "aa"},
                                                  {"path": "in.json", "sha256": "X"}]))


# ── dirty-check: stale_inputs / env_drift ─────────────────────────────────────────────────
def test_lock_dirty_detects_stale_and_env_drift():
    lock = _lock()
    clean = lock_dirty(lock, current_deps=[{"path": "judge.py", "sha256": "aa"},
                                           {"path": "in.json", "sha256": "bb"}],
                       current_env_sha="env1")
    assert clean == ()                                             # 재사용 가능
    stale = lock_dirty(lock, current_deps=[{"path": "in.json", "sha256": "MUTATED"}],
                       current_env_sha="env1")
    assert "stale_inputs" in stale
    drift = lock_dirty(lock, current_deps=[{"path": "judge.py", "sha256": "aa"},
                                           {"path": "in.json", "sha256": "bb"}],
                       current_env_sha="env2")
    assert "env_drift" in drift
    # 재계산 불가(sha=None)는 보수적으로 stale (불확실=재실행).
    assert "stale_inputs" in lock_dirty(lock, current_deps=[{"path": "in.json", "sha256": None}],
                                        current_env_sha="env1")


# ── RunCache: 검증 결과 재사용 (값이 아니라 결과) ─────────────────────────────────────────
def test_run_cache_reuse_by_lock_key():
    rc = RunCache()
    k = lock_key(_lock())
    assert rc.get(k) is None
    rc.put(k, {"verified": True, "regenerated": 0.5})
    assert rc.get(k) == {"verified": True, "regenerated": 0.5}
    # 값만 다른 lock 은 같은 키 → 같은 캐시 히트(입력 지문 재사용).
    assert rc.get(lock_key(_lock(outs=[{"name": "m", "value": 999.0}]))) is not None
