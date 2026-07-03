"""test_omd_engine_p2_lane.py — PROM guard for OMD P2 shared 레인 (hot 공유파일 3-way 응결).

LakatoTree research-programme guard. Two independent oracles, two sources of truth.

PROBLEM (FEEDBACK §P2 잔여 + 현장실측 2026-07-02)
  q-omd-p2-threeway-lane: 진단(hot_files 감사)까지는 있었으나 **실행 레인이 없었다** —
  hot 파일은 여전히 ① 한 궤도 직렬화(병렬도 1) 또는 ② connect 거부. 현장실측(consumer_b
  user~200)이 정량 확증: hot 30파일, 실충돌 파일(env.py/modbus.py/business_logic.py)이
  전부 hot 상위.

PRINCIPLE (problemshift — omd 증분10, 커밋 c41356d)
  shared 레인: declare(shared=[...]) + claim(mode="shared") → shared↔shared 동시 HELD 공존,
  배타(write/read)와는 여전히 충돌. 응결은 git 3-way 자동병합; 같은 hunk 진짜 충돌 =
  정상사건(reason=shared_conflict, retryable, rebase 힌트) — 경보 아님(P3 부분 해소).
  disjoint(write) 궤도의 '구조적 불가=경보' 의미론은 불변.

OMD artifact corroborated (real substrate, read-only):
  - omd_server/core.py WRITE_MODES/_conflicts(shared 공존)/declare(shared)/shared_conflict.
  - omd_server/store.py tasks.shared 컬럼(멱등 마이그레이션).
  - tests/test_p2_shared_lane.py : 공존/배타보존/automerge/shared_conflict/경보 음성컨트롤 5종.

ORACLES
  guard_defect (test_disjoint_only_serializes_hot_file_shared_lane_parallelizes):
      Self-contained, revert-proof in-test model. disjoint-only NAIVE 코디네이터는 hot
      파일에서 둘째 task 를 직렬화(대기) — 병렬도 1(the anomaly). shared 레인 모델은 둘 다
      HELD + 다른-hunk 3-way 병합, 같은-hunk 은 retryable 정상사건. Revert: 레인 off →
      직렬화 복귀.

  guard_mechanism (test_omd_p2_shared_lane_dimension_test_passes_in_real_substrate):
      BEHAVIORAL — 실 OMD venv 에서 tests/test_p2_shared_lane.py 를 subprocess 로 돌려
      rc==0 (실 Coordinator + 실 git 3-way 구동). 부재 시 정직 FAIL.
"""

import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(
    not os.path.isdir("<WORKSPACE>/PROJECT/PI/omd"),
    reason="OMD 자매 repo 미체크아웃(hermetic CI) — 크로스레포 도그푸드 가드는 로컬에서만 실측")

# ---------------------------------------------------------------------------
# Self-contained model for guard_defect (disjoint-only vs shared-lane admission+merge).
# ---------------------------------------------------------------------------


class _Coord:
    """toy: 경로별 궤도 테이블 + 3-way 응결 모델. shared_lane=False 가 NAIVE(disjoint-only)."""

    def __init__(self, shared_lane: bool):
        self.shared_lane = shared_lane
        self.held = []               # (task, path, mode)
        self.integration = {}        # path -> {section: value}

    def claim(self, task, path, mode):
        for _, p, m in self.held:
            if p != path:
                continue
            if self.shared_lane and mode == "shared" and m == "shared":
                continue             # shared↔shared 공존
            return "PENDING"         # 배타 충돌(직렬화)
        self.held.append((task, path, mode))
        return "HELD"

    def connect(self, task, path, edits: dict, base: dict):
        """3-way: base 대비 자기 edits 를 integration 에 적용. 같은 section 을 이미 다른
        값으로 바꾼 뒤면 → shared 궤도는 retryable 정상사건, 배타면 경보."""
        cur = self.integration.setdefault(path, dict(base))
        mode = next(m for t, p, m in self.held if t == task and p == path)
        for section, val in edits.items():
            if cur[section] != base[section] and cur[section] != val:
                if mode == "shared":
                    return {"ok": False, "reason": "shared_conflict", "retryable": True,
                            "hint": "rebase onto integration tip and retry"}
                return {"ok": False, "reason": "merge conflict", "alarm": True}
        cur.update(edits)
        self.held = [(t, p, m) for t, p, m in self.held if t != task]
        return {"ok": True, "state": "MERGED"}


_BASE = {"secA": "A=1", "secB": "B=1"}


# ---------------------------------------------------------------------------
# guard_defect  (negative / improvement oracle) — LOAD-BEARING
# ---------------------------------------------------------------------------


def test_disjoint_only_serializes_hot_file_shared_lane_parallelizes():
    """NAIVE(disjoint-only): hot 파일의 둘째 claim 이 PENDING(직렬화, 병렬도 1 — the
    anomaly). shared 레인: 둘 다 HELD, 다른-hunk 편집이 3-way 로 둘 다 MERGED."""

    naive = _Coord(shared_lane=False)
    assert naive.claim("T1", "env.py", "shared") == "HELD"
    assert naive.claim("T2", "env.py", "shared") == "PENDING", (
        "naive: 레인이 없으면 shared 요청도 직렬화된다")

    lane = _Coord(shared_lane=True)
    assert lane.claim("T1", "env.py", "shared") == "HELD"
    assert lane.claim("T2", "env.py", "shared") == "HELD", "shared↔shared 공존"
    # 다른 섹션 편집 → 순차 응결 둘 다 성공, 두 편집 공존.
    assert lane.connect("T1", "env.py", {"secA": "A=2"}, _BASE)["ok"] is True
    assert lane.connect("T2", "env.py", {"secB": "B=2"}, _BASE)["ok"] is True
    assert lane.integration["env.py"] == {"secA": "A=2", "secB": "B=2"}

    # 배타 의미 보존: 레인이 있어도 write↔shared 는 충돌.
    lane2 = _Coord(shared_lane=True)
    assert lane2.claim("T1", "env.py", "write") == "HELD"
    assert lane2.claim("T2", "env.py", "shared") == "PENDING"


def test_revert_proof_lane_off_reserializes_and_conflict_is_normal_event():
    """Negative control / revert-proof: 레인을 끄면 같은 요청이 다시 직렬화된다.
    그리고 같은-hunk 진짜 충돌은 shared 궤도에선 retryable 정상사건(경보 금지),
    배타 궤도에선 경보 — 의미론 분리가 기제에 load-bearing."""
    reverted = _Coord(shared_lane=False)
    reverted.claim("T1", "env.py", "shared")
    assert reverted.claim("T2", "env.py", "shared") == "PENDING"

    lane = _Coord(shared_lane=True)
    lane.claim("T1", "env.py", "shared"); lane.claim("T2", "env.py", "shared")
    assert lane.connect("T1", "env.py", {"secA": "A=111"}, _BASE)["ok"] is True
    r = lane.connect("T2", "env.py", {"secA": "A=222"}, _BASE)   # 같은 섹션!
    assert r["reason"] == "shared_conflict" and r["retryable"] is True
    assert "rebase" in r["hint"] and "alarm" not in r

    alarm = _Coord(shared_lane=True)
    alarm.claim("T3", "env.py", "write")
    alarm.integration["env.py"] = {"secA": "A=999", "secB": "B=1"}   # out-of-band 분기
    ra = alarm.connect("T3", "env.py", {"secA": "A=222"}, _BASE)
    assert ra["reason"] == "merge conflict" and ra.get("alarm") is True


# ---------------------------------------------------------------------------
# guard_mechanism  (positive / novel oracle) — LOAD-BEARING
# ---------------------------------------------------------------------------

_OMD_ROOT = "<WORKSPACE>/PROJECT/PI/omd"
_OMD_PY = os.path.join(_OMD_ROOT, ".venv", "bin", "python")
_OMD_TEST = "tests/test_p2_shared_lane.py"


def test_omd_p2_shared_lane_dimension_test_passes_in_real_substrate():
    """Independent corroboration: 실 OMD venv 에서 P2 shared-lane 차원테스트 5종 통과
    (공존/배타보존/3-way automerge/shared_conflict/경보 음성컨트롤 — 실 git 구동)."""
    assert os.path.isfile(_OMD_PY), f"OMD venv python missing: {_OMD_PY}"
    assert os.path.isfile(os.path.join(_OMD_ROOT, _OMD_TEST)), f"missing: {_OMD_TEST}"

    proc = subprocess.run(
        [_OMD_PY, "-m", "pytest", _OMD_TEST, "-q", "-p", "no:cacheprovider"],
        cwd=_OMD_ROOT, capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, (
        f"real OMD P2 shared-lane dimension test failed.\nrc={proc.returncode}\n"
        f"STDOUT:\n{proc.stdout[-4000:]}\nSTDERR:\n{proc.stderr[-2000:]}")
    assert "passed" in proc.stdout, proc.stdout[-2000:]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
