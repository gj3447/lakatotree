"""test_omd_engine_p4_barrier.py — PROM guard for OMD P4 잔여 (§3.D 배리어 재기동 단위복구 + CONSUMED).

LakatoTree research-programme guard. Two independent oracles, two sources of truth.

PROBLEM (CONCURRENCY 증분8 deviation 3·4 — 문서가 자백한 부채; FEEDBACK §P4)
  ① TRIPPING 중 코디네이터 크래시 시 _recover() 는 task 를 *개별*로만 git 진실과 조정 —
    배리어 잔해는 방치되어 "BROKEN 신호 없이 반쪽 MERGED"(§3.D 함정)가 가능했다.
  ② TRIPPED→CONSUMED 는 FSM 정의만 있고 수거 동사 미구현(TRIPPED 가 사실상 종단).

PRINCIPLE (problemshift — omd 증분11, 커밋 5f5db33)
  _barrier_recover(): task-단위 조정 *후* TRIPPING 잔해를 단위로 조정 — 전 멤버 MERGED →
  TRIPPED 전진수정 / 일부만 → BROKEN(coordinator_crash_partial_trip) fail-loud. MERGED 는
  단조 사실 유지. + barrier_consume: TRIPPED→CONSUMED + 멤버별 merge_sha 수거, 멱등 noop,
  비-TRIPPED 거부. 적합성 barrier_restart_recovery must=True 승격(회귀가드).

OMD artifact corroborated (real substrate, read-only):
  - omd_server/core.py _barrier_recover/_recover 말미 호출 + barrier_consume(MCP 노출).
  - tests/test_p4_barrier_restart.py : 전진수정/부분트립 BROKEN/ARMED 무해/수거+멱등/거부 5종.

ORACLES
  guard_defect (test_task_only_recovery_leaves_half_trip_silent_unit_recovery_fails_loud):
      Self-contained, revert-proof in-test model. NAIVE(task-개별 복구만)는 반쪽 트립을
      TRIPPING 침묵 방치(관측자는 반쪽 MERGED 를 모른다 — the anomaly). 단위복구는
      all-MERGED→TRIPPED / partial→BROKEN(fail-loud). Revert: 단위복구 off → 침묵 복귀.

  guard_mechanism (test_omd_p4_barrier_restart_dimension_test_passes_in_real_substrate):
      BEHAVIORAL — 실 OMD venv 에서 tests/test_p4_barrier_restart.py 를 subprocess 로
      돌려 rc==0 (실 Coordinator 재기동 + 실 git 응결 + 크래시 주입). 부재 시 정직 FAIL.
"""

import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(
    not os.path.isdir("<WORKSPACE>/PROJECT/PI/omd"),
    reason="OMD 자매 repo 미체크아웃(hermetic CI) — 크로스레포 도그푸드 가드는 로컬에서만 실측")

# ---------------------------------------------------------------------------
# Self-contained model for guard_defect (task-individual vs barrier-unit recovery).
# ---------------------------------------------------------------------------


def _recover(tasks: dict, barrier: dict, *, unit_recovery: bool):
    """재기동 복구 모델. tasks: id→state(크래시 잔해). barrier: TRIPPING 잔해.
    task-단위 조정(공통): CONNECTING 은 git 진실대로 MERGED(트레일러 있음) 또는 DONE 롤백 —
    여기선 잔해가 이미 그 결과라고 본다. unit_recovery=False 가 NAIVE(배리어 방치 — the revert)."""
    if not unit_recovery:
        return dict(barrier)                       # NAIVE: 배리어 잔해 그대로(침묵)
    b = dict(barrier)
    if all(s == "MERGED" for s in tasks.values()):
        b["state"] = "TRIPPED"                     # 전진수정
    else:
        b["state"] = "BROKEN"                      # 반쪽 트립 fail-loud
        b["break_reason"] = "coordinator_crash_partial_trip"
    return b


def _consume(barrier: dict, tasks: dict):
    """수거 동사 모델: TRIPPED 에서만 결과(merge_sha) 수거 + CONSUMED 종단, 재호출 멱등 noop."""
    if barrier["state"] == "CONSUMED":
        return {"ok": True, "noop": True, "state": "CONSUMED"}
    if barrier["state"] != "TRIPPED":
        return {"ok": False, "reason": f"not TRIPPED: {barrier['state']}"}
    barrier["state"] = "CONSUMED"
    return {"ok": True, "state": "CONSUMED",
            "results": [{"task_id": t, "merge_sha": f"sha-{t}"} for t in tasks]}


# ---------------------------------------------------------------------------
# guard_defect  (negative / improvement oracle) — LOAD-BEARING
# ---------------------------------------------------------------------------


def test_task_only_recovery_leaves_half_trip_silent_unit_recovery_fails_loud():
    """NAIVE(task-개별만): A=MERGED/B=DONE 반쪽 잔해에서 배리어가 TRIPPING 으로 침묵 방치 —
    관측자는 반쪽 적용을 모른다(the anomaly). 단위복구: partial→BROKEN fail-loud,
    all-MERGED→TRIPPED 전진수정. 그리고 CONSUMED 수거가 TRIPPED 에서만 동작."""

    half = {"A": "MERGED", "B": "DONE"}
    naive = _recover(half, {"state": "TRIPPING"}, unit_recovery=False)
    assert naive["state"] == "TRIPPING", "naive: 반쪽 트립이 침묵으로 남는다(§3.D 함정)"
    assert "break_reason" not in naive, "naive: BROKEN 신호 없음"

    fixed = _recover(half, {"state": "TRIPPING"}, unit_recovery=True)
    assert fixed["state"] == "BROKEN"
    assert fixed["break_reason"] == "coordinator_crash_partial_trip"

    full = {"A": "MERGED", "B": "MERGED"}
    fwd = _recover(full, {"state": "TRIPPING"}, unit_recovery=True)
    assert fwd["state"] == "TRIPPED", "전 멤버 MERGED = 전진수정(반쪽 신호 아님)"

    # 수거: TRIPPED→CONSUMED(+merge_sha), 재호출 noop, BROKEN 거부.
    c = _consume(fwd, full)
    assert c["ok"] and c["state"] == "CONSUMED" and len(c["results"]) == 2
    assert _consume(fwd, full)["noop"] is True
    assert _consume(fixed, half)["ok"] is False

    # The property genuinely depends on the mechanism: silent TRIPPING vs BROKEN.
    assert naive["state"] != fixed["state"]


def test_revert_proof_disabling_unit_recovery_reintroduces_silence():
    """Negative control / revert-proof: 단위복구를 끄면 all-MERGED 잔해조차 TRIPPING 으로
    남는다(전진수정도 없음) — 두 단언 모두 기제에 load-bearing."""
    full = {"A": "MERGED", "B": "MERGED"}
    reverted = _recover(full, {"state": "TRIPPING"}, unit_recovery=False)
    assert reverted["state"] == "TRIPPING"
    # 그리고 수거는 방치된 TRIPPING 에서 불가 — 파이프라인이 결과를 영영 못 받는다.
    assert _consume(reverted, full)["ok"] is False


# ---------------------------------------------------------------------------
# guard_mechanism  (positive / novel oracle) — LOAD-BEARING
# ---------------------------------------------------------------------------

_OMD_ROOT = "<WORKSPACE>/PROJECT/PI/omd"
_OMD_PY = os.path.join(_OMD_ROOT, ".venv", "bin", "python")
_OMD_TEST = "tests/test_p4_barrier_restart.py"


def test_omd_p4_barrier_restart_dimension_test_passes_in_real_substrate():
    """Independent corroboration: 실 OMD venv 에서 증분11 차원테스트 5종 통과
    (실 재기동 Coordinator + 실 git 응결 + 크래시 주입 — 전진수정/BROKEN/무해/수거/거부)."""
    assert os.path.isfile(_OMD_PY), f"OMD venv python missing: {_OMD_PY}"
    assert os.path.isfile(os.path.join(_OMD_ROOT, _OMD_TEST)), f"missing: {_OMD_TEST}"

    proc = subprocess.run(
        [_OMD_PY, "-m", "pytest", _OMD_TEST, "-q", "-p", "no:cacheprovider"],
        cwd=_OMD_ROOT, capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, (
        f"real OMD P4 barrier-restart dimension test failed.\nrc={proc.returncode}\n"
        f"STDOUT:\n{proc.stdout[-4000:]}\nSTDERR:\n{proc.stderr[-2000:]}")
    assert "passed" in proc.stdout, proc.stdout[-2000:]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
