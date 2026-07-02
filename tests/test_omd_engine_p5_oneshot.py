"""test_omd_engine_p5_oneshot.py — PROM guard for OMD P5 (complete_task 원샷 wrapper).

LakatoTree research-programme guard. Two independent oracles, two sources of truth.

PROBLEM (omd/docs/FEEDBACK_problems_20260630.md §P5 "verb 마찰")
  happy-path 가 7~8 verb 시퀀스(declare→next→claim→start→commit→finish→connect)라
  망각-스트랜드가 구조적으로 발생한다: `finish` 를 빼먹으면 task 가 영원히 IN_ORBIT
  (궤도 미해제 → 뒤 대기자 기아), `connect` 를 빼먹으면 worktree 에 묶여 영영 미통합.
  채택(P1)을 갉아먹는 마찰 — 안 지켜지는 프로토콜은 없는 프로토콜.

PRINCIPLE (problemshift)
  `complete_task() = finish+connect(+push)` 원샷 wrapper: happy-path 를 1 verb 로 접고,
  INV: ok:True ⟺ 최종 MERGED, 중간 단계 거부는 fail-loud 로 stage 이름과 함께 전파.

OMD artifact corroborated (real substrate, read-only):
  - omd_server/core.py complete_task  : finish+connect 합성 (MCP verb 로도 노출, 44b6187).
  - tests/test_p5_complete_task.py    : 원샷 머지·빈커밋·단계거부 stage 전파.

ORACLES
  guard_defect (test_forgotten_finish_strands_task_oneshot_merges_and_frees_orbit):
      Self-contained, revert-proof in-test model. NAIVE 수동 시퀀스에서 finish 망각 →
      task 영구 IN_ORBIT + 대기자 기아(the anomaly). complete_task 원샷은 같은 지점에서
      MERGED + 궤도 해제 + 대기자 진행. Revert: wrapper 대신 망각 드라이버 → 기아 복귀.

  guard_mechanism (test_omd_p5_complete_task_dimension_test_passes_in_real_substrate):
      BEHAVIORAL — 실 OMD venv 에서 tests/test_p5_complete_task.py 를 subprocess 로 돌려
      rc==0 (실 Coordinator + 실 git worktree/merge 구동). 부재 시 정직 FAIL.
"""

import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(
    not os.path.isdir("<WORKSPACE>/PROJECT/PI/omd"),
    reason="OMD 자매 repo 미체크아웃(hermetic CI) — 크로스레포 도그푸드 가드는 로컬에서만 실측")

# ---------------------------------------------------------------------------
# Self-contained model for guard_defect (task/orbit FSM + verb sequence driver).
# ---------------------------------------------------------------------------


class _Coord:
    """toy 코디네이터: task FSM(IN_ORBIT→DONE→MERGED) + 궤도 1개(해제는 finish 에서만)."""

    def __init__(self):
        self.tasks = {}          # tid -> state
        self.orbit_holder = None

    def start(self, tid):
        assert self.orbit_holder is None, "궤도 점유중 — 대기자는 기다린다"
        self.orbit_holder = tid
        self.tasks[tid] = "IN_ORBIT"
        return {"ok": True}

    def commit(self, tid):
        assert self.tasks[tid] == "IN_ORBIT"
        return {"ok": True}

    def finish(self, tid):
        if self.tasks.get(tid) != "IN_ORBIT":
            return {"ok": False, "stage": "finish"}
        self.tasks[tid] = "DONE"
        self.orbit_holder = None                   # 궤도 해제는 여기서만
        return {"ok": True}

    def connect(self, tid):
        if self.tasks.get(tid) != "DONE":          # finish 안 했으면 응결 불가
            return {"ok": False, "stage": "connect", "reason": "not_done"}
        self.tasks[tid] = "MERGED"
        return {"ok": True, "state": "MERGED"}

    def complete_task(self, tid):
        """원샷 wrapper: finish+connect 합성. INV: ok:True ⟺ MERGED; 단계 거부 stage 전파."""
        for step in (self.finish, self.connect):
            r = step(tid)
            if not r.get("ok"):
                return {"ok": False, "stage": r.get("stage", "?")}
        return {"ok": True, "state": "MERGED"}


def _forgetful_manual_driver(omd, tid):
    """NAIVE 드라이버: 7-verb 수동 시퀀스에서 finish 를 망각(가장 흔한 스트랜드)."""
    omd.start(tid)
    omd.commit(tid)
    # ... finish 망각 ...
    return omd.connect(tid)


# ---------------------------------------------------------------------------
# guard_defect  (negative / improvement oracle) — LOAD-BEARING
# ---------------------------------------------------------------------------


def test_forgotten_finish_strands_task_oneshot_merges_and_frees_orbit():
    """NAIVE: finish 망각 → connect 거부·task 영구 IN_ORBIT·궤도 미해제 → 대기자 기아
    (the anomaly). 원샷 complete_task 는 MERGED + 궤도 해제 + 대기자 진행."""

    naive = _Coord()
    r = _forgetful_manual_driver(naive, "A")
    assert r["ok"] is False and r["reason"] == "not_done"
    assert naive.tasks["A"] == "IN_ORBIT", "naive: task 영구 스트랜드"
    assert naive.orbit_holder == "A", "naive: 궤도 미해제"
    with pytest.raises(AssertionError):
        naive.start("B")                           # 대기자 B 기아

    fixed = _Coord()
    fixed.start("A")
    fixed.commit("A")
    r = fixed.complete_task("A")                   # 원샷: finish+connect
    assert r == {"ok": True, "state": "MERGED"}, "INV: ok:True ⟺ MERGED"
    assert fixed.tasks["A"] == "MERGED" and fixed.orbit_holder is None
    assert fixed.start("B")["ok"] is True, "궤도 해제 → 대기자 진행(기아 해소)"

    # The property genuinely depends on the mechanism: stranded vs merged.
    assert naive.tasks["A"] != fixed.tasks["A"]


def test_revert_proof_manual_sequence_reintroduces_strand_and_stage_failloud():
    """Negative control / revert-proof: wrapper 를 버리고 수동 시퀀스로 돌아가면 같은
    망각이 다시 스트랜드를 만든다. 그리고 wrapper 는 단계 거부를 침묵이 아니라
    stage 이름으로 fail-loud 전파(반쪽성공을 ok:True 로 위장하지 않음)."""
    reverted = _Coord()
    _forgetful_manual_driver(reverted, "A")
    assert reverted.tasks["A"] == "IN_ORBIT" and reverted.orbit_holder == "A"

    # 시작도 안 한 task 에 complete_task → finish 단계에서 fail-loud (MERGED 위장 금지).
    omd = _Coord()
    r = omd.complete_task("ghost")
    assert r["ok"] is False and r["stage"] == "finish"
    assert omd.tasks.get("ghost") != "MERGED"


# ---------------------------------------------------------------------------
# guard_mechanism  (positive / novel oracle) — LOAD-BEARING
# ---------------------------------------------------------------------------

_OMD_ROOT = "<WORKSPACE>/PROJECT/PI/omd"
_OMD_PY = os.path.join(_OMD_ROOT, ".venv", "bin", "python")
_OMD_TEST = "tests/test_p5_complete_task.py"


def test_omd_p5_complete_task_dimension_test_passes_in_real_substrate():
    """Independent corroboration: 실 OMD venv 에서 P5 complete_task 차원테스트 통과
    (실 git repo 원샷 머지 + INV ok⟺MERGED + 단계거부 stage 전파)."""
    assert os.path.isfile(_OMD_PY), f"OMD venv python missing: {_OMD_PY}"
    assert os.path.isfile(os.path.join(_OMD_ROOT, _OMD_TEST)), f"missing: {_OMD_TEST}"

    proc = subprocess.run(
        [_OMD_PY, "-m", "pytest", _OMD_TEST, "-q", "-p", "no:cacheprovider"],
        cwd=_OMD_ROOT, capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, (
        f"real OMD P5 complete_task dimension test failed.\nrc={proc.returncode}\n"
        f"STDOUT:\n{proc.stdout[-4000:]}\nSTDERR:\n{proc.stderr[-2000:]}")
    assert "passed" in proc.stdout, proc.stdout[-2000:]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
