"""MeasurementLock — 측정의 입력을 봉인하는 재현 레코드 (EXTAUDIT S8, DVC lock 흡수 2026-07-23).

급소 #3 잔여: S1 grade-gate/S2 replay 는 *값의 검증*을 강제했지만, receipt(v3)조차 봉인하는 것은
judge_script_sha 하나뿐 — 입력 데이터/환경/출력 해시가 봉인 밖이라 "이 값은 이 입력에서 재생산된다"가
증명 불가였다(감사: 영수증은 실험이 아니라 주장을 봉인).

DVC dvc.lock 이식(구조만, 통째 의존 0): stage 하나 = (cmd, deps 해시, params 값) → outs 해시의 함수적
봉인. DVC 에는 클라이언트가 outs 를 주장하는 경로 자체가 없다(outs 는 실행 후 관측만) — 그 원칙을
LakatoTree 로 옮긴다:

  MeasurementLock = {cmd, deps:[{path,sha256}], params:{k:v}, env_sha, outs:[{name,value}],
                     measurement_grade, replay_status}
  · deps sha 는 *서버가 디스크에서 재계산*(client 선언 금지) — S1 의 값소유 원칙을 입력으로 확장.
  · lock_sha = sha256(도메인헤더 + JCS(전체)) — receipt sha-space 와 도메인 분리.
  · lock_key = sha256(outs/grade/status 제외 부분집합) — DVC run-cache 키(_get_cache_hash key=True)
    동형. 같은 (cmd,deps,params,env)면 재실행 결과도 같다(결정론 replay _REPLAY_TOL) → 재검증 1회.
  · dirty-check: deps sha 재계산 ≠ lock → stale_inputs, env_sha ≠ 현재 → env_drift (io.replay reason 어휘).

전부 순수함수. receipt v3 필드셋은 불변(lock 은 사이드카 — verdict receipt 를 건드리지 않는다, S4 처럼
소급 강등 0). 라이브 :MeasurementLock 노드 mint 는 S8b(submit 배선).
# KG: q-extaudit-replay-default-on-20260722 잔여 / crit-extaudit-receipt-seals-claims-not-experiments
"""
from __future__ import annotations

import hashlib
import json

_LOCK_DOMAIN = "measurement-lock\x00v1\n"       # receipt/anchor 와 sha-space 도메인 분리


def _jcs(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def build_measurement_lock(*, cmd: str, deps: list[dict], params: dict, env_sha: str | None,
                           outs: list[dict], measurement_grade: str, replay_status: str) -> dict:
    """MeasurementLock 레코드 조립. deps 는 [{path, sha256}] (서버 재계산 sha; 재계산 불가는 sha256=None
    으로 정직 기록 — 날조·은닉 금지, S1 값소유 규율). outs 는 실행 관측값 [{name, value}]."""
    norm_deps = sorted(
        [{"path": str(d.get("path") or ""), "sha256": d.get("sha256")} for d in (deps or [])],
        key=lambda d: d["path"])
    norm_outs = [{"name": str(o.get("name") or ""), "value": o.get("value")} for o in (outs or [])]
    return {"cmd": cmd or "", "deps": norm_deps, "params": dict(params or {}),
            "env_sha": env_sha, "outs": norm_outs,
            "measurement_grade": measurement_grade, "replay_status": replay_status}


def lock_sha(lock: dict) -> str:
    """전체 봉인 sha256 — outs/grade/status 까지 포함(이 측정 결과의 완전한 지문)."""
    return hashlib.sha256((_LOCK_DOMAIN + _jcs(lock)).encode("utf-8")).hexdigest()


def lock_key(lock: dict) -> str:
    """run-cache 키 — DVC _get_cache_hash(key=True) 동형: outs *값*·grade·status 제외, out *이름*은 포함.

    같은 (cmd, deps, params, env, out-이름)이면 재실행 결과가 결정론적으로 같다 → 재검증 재사용 키.
    outs 값 제외가 핵심: 값은 재실행이 낳는 것이지 키의 일부가 아니다(주장을 키에 넣으면 캐시가 거짓말)."""
    keyed = {"cmd": lock.get("cmd", ""), "deps": lock.get("deps", []),
             "params": lock.get("params", {}), "env_sha": lock.get("env_sha"),
             "out_names": sorted(o.get("name", "") for o in lock.get("outs", []))}
    return hashlib.sha256((_LOCK_DOMAIN + "key\n" + _jcs(keyed)).encode("utf-8")).hexdigest()


def lock_dirty(lock: dict, *, current_deps: list[dict], current_env_sha: str | None) -> tuple[str, ...]:
    """dirty-check — 봉인 이후 입력이 바뀐 축의 reason 튜플. 빈 튜플=재사용 가능(clean).

    stale_inputs: 어떤 dep 의 현재 sha 가 lock 과 다름(재계산 대조). env_drift: env_sha 불일치.
    현재 dep 이 lock 에 없거나 sha=None(재계산 불가)은 stale 로 보수적 판정(불확실=재실행)."""
    reasons = []
    locked = {d["path"]: d.get("sha256") for d in lock.get("deps", [])}
    cur = {str(d.get("path") or ""): d.get("sha256") for d in (current_deps or [])}
    for path, sha in cur.items():
        if sha is None or locked.get(path) != sha:
            reasons.append("stale_inputs")
            break
    lock_env = lock.get("env_sha")
    if lock_env is not None and current_env_sha is not None and lock_env != current_env_sha:
        reasons.append("env_drift")
    return tuple(reasons)


class RunCache:
    """(lock_key → 검증 결과) 재사용 테이블 — 순수 in-memory(라이브는 KG 미러가 S8b). DVC run-cache 축소판.

    put/get 만 — 같은 입력 지문의 replay 검증 결과를 노드당 1회로 상각. 값(outs)이 아니라 *검증 결과*를
    캐시한다(재현확인의 재사용이지 값소유 우회가 아니다)."""

    def __init__(self):
        self._t: dict[str, dict] = {}

    def get(self, key: str) -> dict | None:
        return self._t.get(key)

    def put(self, key: str, result: dict) -> None:
        self._t[key] = dict(result)
