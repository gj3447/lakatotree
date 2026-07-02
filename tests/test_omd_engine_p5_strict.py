"""test_omd_engine_p5_strict.py — PROM guard for OMD P5 (strict-writeset commit 게이트).

LakatoTree research-programme guard. Two independent oracles, two sources of truth.

PROBLEM (omd/docs/FEEDBACK_problems_20260630.md §P5 "안전하지 않은 기본값")
  write-set 위반이 commit 때는 경고만(advisory, commit_writeset_warning) 나가고 권위
  거부는 connect 에서야 온다. 에이전트가 경고를 무시하면 **일을 다 끝낸 뒤 늦게 깨진다**
  (late failure) — 낭비된 커밋 + connect_rejected(writeset_violation) 롤백.

PRINCIPLE (problemshift)
  `strict_writeset` commit-time 게이트: 궤도-밖 경로를 commit 에서 자동 제외(히스토리
  진입 차단·working tree 는 보존) — 위반이 조기에, 커밋 경계에서 드러난다. connect 는
  이제 깨끗한 커밋만 받아 성공(late failure 0).

OMD artifact corroborated (real substrate, read-only):
  - omd_server/core.py commit(strict_writeset) : 궤도-밖 자동 제외 + excluded 명시 회신.
  - tests/test_p5_strict_writeset.py           : 제외·working tree 보존·in-orbit 만 커밋.

ORACLES
  guard_defect (test_advisory_commit_fails_late_at_connect_strict_fails_early):
      Self-contained, revert-proof in-test model. NAIVE advisory 는 경고만 내고 전부
      커밋 → connect 에서 늦은 거부(the anomaly: 일 다 한 뒤 rollback). strict 는
      commit-time 에 궤도-밖을 제외해 connect 성공(늦은 실패 0, working tree 보존).
      Revert: strict=False → 늦은 거부 복귀.

  guard_mechanism (test_omd_p5_strict_writeset_dimension_test_passes_in_real_substrate):
      BEHAVIORAL — 실 OMD venv 에서 tests/test_p5_strict_writeset.py 를 subprocess 로
      돌려 rc==0 (실 git worktree 에서 실 commit 게이트 구동). 부재 시 정직 FAIL.
"""

import os
import subprocess
import sys
from fnmatch import fnmatch

import pytest

pytestmark = pytest.mark.skipif(
    not os.path.isdir("<WORKSPACE>/PROJECT/PI/omd"),
    reason="OMD 자매 repo 미체크아웃(hermetic CI) — 크로스레포 도그푸드 가드는 로컬에서만 실측")

# ---------------------------------------------------------------------------
# Self-contained model for guard_defect (advisory vs strict commit gate).
# ---------------------------------------------------------------------------


def _in_orbit(path, globs):
    return any(fnmatch(path, g) or fnmatch(path, g.replace("**", "*")) for g in globs)


class _Task:
    def __init__(self, orbit_globs, worktree_paths):
        self.orbit = tuple(orbit_globs)
        self.worktree = set(worktree_paths)        # 편집된 경로들
        self.committed = set()

    def commit(self, *, strict: bool):
        """strict=False 가 NAIVE(advisory — 전부 커밋 + 경고만), True 가 원리 게이트."""
        offending = sorted(p for p in self.worktree if not _in_orbit(p, self.orbit))
        if strict:
            self.committed = {p for p in self.worktree if _in_orbit(p, self.orbit)}
            return {"ok": True, "excluded_out_of_orbit": offending}
        self.committed = set(self.worktree)        # advisory: 위반 경로도 커밋됨
        return {"ok": True, "commit_writeset_warning": offending}

    def connect(self):
        """권위 강제 지점: 커밋에 궤도-밖 경로가 있으면 거부(늦은 실패)."""
        violation = sorted(p for p in self.committed if not _in_orbit(p, self.orbit))
        if violation:
            return {"ok": False, "reason": "writeset_violation", "offending": violation}
        return {"ok": True, "state": "MERGED"}


_ORBIT = ("a/**",)
_EDITS = ("a/x.py", "b/foo.py")                    # b/foo.py = 궤도-밖


# ---------------------------------------------------------------------------
# guard_defect  (negative / improvement oracle) — LOAD-BEARING
# ---------------------------------------------------------------------------


def test_advisory_commit_fails_late_at_connect_strict_fails_early():
    """NAIVE advisory: 경고를 무시하면 위반 경로가 커밋되고 connect 에서야 거부 —
    일 다 끝낸 뒤 늦은 실패(the anomaly). strict: commit-time 제외 → connect 성공."""

    naive = _Task(_ORBIT, _EDITS)
    rc = naive.commit(strict=False)
    assert rc["ok"] is True and rc["commit_writeset_warning"] == ["b/foo.py"], (
        "advisory: 경고만 — 커밋은 통과")
    assert "b/foo.py" in naive.committed, "위반 경로가 히스토리에 들어간다"
    rn = naive.connect()
    assert rn == {"ok": False, "reason": "writeset_violation", "offending": ["b/foo.py"]}, (
        "늦은 실패: connect 에서야 깨진다")

    strict = _Task(_ORBIT, _EDITS)
    rc = strict.commit(strict=True)
    assert rc["ok"] is True and rc["excluded_out_of_orbit"] == ["b/foo.py"]
    assert strict.committed == {"a/x.py"}, "in-orbit 만 커밋"
    assert "b/foo.py" in strict.worktree, "궤도-밖 편집은 working tree 에 보존(작업 소실 0)"
    assert strict.connect() == {"ok": True, "state": "MERGED"}, "늦은 실패 0"

    # The property genuinely depends on the mechanism: late-reject vs merged.
    assert naive.connect()["ok"] != strict.connect()["ok"]


def test_revert_proof_strict_off_reintroduces_late_rejection():
    """Negative control / revert-proof: strict 를 끄면 같은 편집이 다시 늦은 거부로
    끝난다 — 조기-실패 단언이 게이트에 load-bearing. 그리고 전-경로 in-orbit 이면
    strict 도 아무것도 제외하지 않는다(오차단 0)."""
    reverted = _Task(_ORBIT, _EDITS)
    reverted.commit(strict=False)
    assert reverted.connect()["ok"] is False

    clean = _Task(_ORBIT, ("a/x.py", "a/y.py"))
    rc = clean.commit(strict=True)
    assert rc["excluded_out_of_orbit"] == [] and clean.committed == {"a/x.py", "a/y.py"}
    assert clean.connect()["ok"] is True


# ---------------------------------------------------------------------------
# guard_mechanism  (positive / novel oracle) — LOAD-BEARING
# ---------------------------------------------------------------------------

_OMD_ROOT = "<WORKSPACE>/PROJECT/PI/omd"
_OMD_PY = os.path.join(_OMD_ROOT, ".venv", "bin", "python")
_OMD_TEST = "tests/test_p5_strict_writeset.py"


def test_omd_p5_strict_writeset_dimension_test_passes_in_real_substrate():
    """Independent corroboration: 실 OMD venv 에서 P5 strict-writeset 차원테스트 통과
    (실 git worktree 에서 궤도-밖 commit-time 제외 + working tree 보존)."""
    assert os.path.isfile(_OMD_PY), f"OMD venv python missing: {_OMD_PY}"
    assert os.path.isfile(os.path.join(_OMD_ROOT, _OMD_TEST)), f"missing: {_OMD_TEST}"

    proc = subprocess.run(
        [_OMD_PY, "-m", "pytest", _OMD_TEST, "-q", "-p", "no:cacheprovider"],
        cwd=_OMD_ROOT, capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, (
        f"real OMD P5 strict-writeset dimension test failed.\nrc={proc.returncode}\n"
        f"STDOUT:\n{proc.stdout[-4000:]}\nSTDERR:\n{proc.stderr[-2000:]}")
    assert "passed" in proc.stdout, proc.stdout[-2000:]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
