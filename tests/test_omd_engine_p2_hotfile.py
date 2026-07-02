"""test_omd_engine_p2_hotfile.py — PROM guard for OMD P2 (hot 공유파일 경합 진단).

LakatoTree research-programme guard. Two independent oracles, two sources of truth.

PROBLEM (omd/docs/FEEDBACK_problems_20260630.md §P2)
  disjoint write-set + 위반강제(connect_rejected reason=writeset_violation) 아래에서
  `constants/env.py`·`business_logic.py` 같은 **여러 task 가 동시에 건드려야 하는 중앙파일**은
  ① 한 궤도만 잡아 직렬화(병렬도 ≈1) 또는 ② 안 claim 하고 건드리면 connect 거부.
  실측: 2026-06-30 divergence 충돌 파일이 정확히 env.py/modbus.py — OMD 최약 케이스인데
  disjoint-only 세계관은 이 마찰을 *진단조차 못 한다*(침묵 직렬화).

PRINCIPLE (problemshift)
  최근 히스토리에서 파일별 touch 빈도(distinct 커밋수·저자수)를 세어 threshold 이상을
  hot 파일로 식별 → shared glob 등급 후보로 권고(fail-loud 진단; disjoint 불변식은 유지).

OMD artifact corroborated (real substrate, read-only):
  - omd_server/hot_files.py       : hot_file_audit()/HotReport.recommend_shared_globs/gate().
  - tests/test_p2_p4_harness.py   : hot 검출·정렬·threshold·max_hot NO_GO 게이트.

ORACLES
  guard_defect (test_disjoint_only_worldview_silent_on_hot_contention_audit_diagnoses):
      Self-contained, revert-proof in-test model. NAIVE(disjoint-only) 진단기는 hot 파일
      경합을 0건으로 오보(권고 0) — 직렬화 마찰이 침묵 진행. 원리 감사는 touch-빈도로
      env.py/modbus.py 를 hot 으로 검출·빈도순 정렬·권고. Revert: 검출 끔 → 다시 침묵.

  guard_mechanism (test_omd_p2_hotfile_dimension_test_passes_in_real_substrate):
      BEHAVIORAL — 실 OMD venv 에서 tests/test_p2_p4_harness.py 를 subprocess 로 돌려 rc==0.
      in-test 모델과 독립(실 hot_file_audit/gate 를 실 git repo 위에서 구동). 부재 시 정직 FAIL.
"""

import os
import subprocess
import sys
from collections import Counter, defaultdict

import pytest

pytestmark = pytest.mark.skipif(
    not os.path.isdir("<WORKSPACE>/PROJECT/PI/omd"),
    reason="OMD 자매 repo 미체크아웃(hermetic CI) — 크로스레포 도그푸드 가드는 로컬에서만 실측")

# ---------------------------------------------------------------------------
# Self-contained model for guard_defect (mirrors hot_files.hot_file_audit semantics).
# ---------------------------------------------------------------------------

# (author, touched_files) 비-merge 커밋 히스토리 — env.py 5touch/3저자, modbus.py 4/2, x.py 1/1.
_HISTORY = (
    ("alice", ("constants/env.py", "a/x.py")),
    ("bob",   ("constants/env.py",)),
    ("carol", ("constants/env.py", "constants/modbus.py")),
    ("alice", ("constants/env.py", "constants/modbus.py")),
    ("bob",   ("constants/env.py", "constants/modbus.py")),
    ("alice", ("constants/modbus.py",)),
)


def _audit(history, *, detect_hot: bool, threshold: int = 3):
    """detect_hot=False 가 NAIVE(disjoint-only 세계관 — hot 개념 없음 = 진단 부재),
    True 가 원리 감사. 토글 하나가 revert-proof 스위치."""
    if not detect_hot:
        return {"hot": [], "recommend": []}
    commits, authors = Counter(), defaultdict(set)
    for author, files in history:
        for f in files:
            commits[f] += 1
            authors[f].add(author)
    hot = [(p, n, len(authors[p])) for p, n in commits.items() if n >= threshold]
    hot.sort(key=lambda h: (-h[1], -h[2], h[0]))
    return {"hot": hot, "recommend": [p for p, _, _ in hot]}


# ---------------------------------------------------------------------------
# guard_defect  (negative / improvement oracle) — LOAD-BEARING
# ---------------------------------------------------------------------------


def test_disjoint_only_worldview_silent_on_hot_contention_audit_diagnoses():
    """NAIVE(disjoint-only)는 중앙파일 경합을 0건 오보 — 직렬화/거부 마찰이 침묵 진행
    (the anomaly). 원리 감사는 hot 2파일을 빈도순으로 검출하고 shared glob 을 권고."""

    naive = _audit(_HISTORY, detect_hot=False)
    assert naive["hot"] == [] and naive["recommend"] == [], (
        "naive: hot 개념이 없어 경합을 진단하지 못한다(침묵)")

    fixed = _audit(_HISTORY, detect_hot=True, threshold=3)
    paths = [p for p, _, _ in fixed["hot"]]
    assert paths == ["constants/env.py", "constants/modbus.py"], (
        f"hot 파일을 touch-빈도 내림차순으로 검출해야: {paths}")
    env = fixed["hot"][0]
    assert env[1] == 5 and env[2] == 3, "env.py = 커밋 5·저자 3 (실사고 프로파일)"
    assert "a/x.py" not in paths, "1-touch 파일은 hot 아님(오탐 0)"
    assert fixed["recommend"], "hot 존재 시 shared glob 권고가 나와야(fail-loud 진단)"

    # The property genuinely depends on the mechanism: naive 0건 vs principled 2건.
    assert len(naive["hot"]) != len(fixed["hot"])


def test_revert_proof_disabling_detection_reintroduces_silence():
    """Negative control / revert-proof: 검출을 끄면 같은 히스토리가 다시 무경합으로 보인다.
    그리고 threshold 를 높이면(=사실상 revert) hot 이 소멸 — 단언이 기제에 load-bearing."""
    reverted = _audit(_HISTORY, detect_hot=False)
    assert reverted["recommend"] == []
    tightened = _audit(_HISTORY, detect_hot=True, threshold=99)
    assert tightened["hot"] == [], "threshold=99 → hot 0 (기제 의존 확인)"
    # cold 히스토리(각 파일 1touch)에선 원리 감사도 0건 — 오탐 아님.
    cold = (("a", ("p.py",)), ("b", ("q.py",)))
    assert _audit(cold, detect_hot=True)["hot"] == []


# ---------------------------------------------------------------------------
# guard_mechanism  (positive / novel oracle) — LOAD-BEARING
# ---------------------------------------------------------------------------

_OMD_ROOT = "<WORKSPACE>/PROJECT/PI/omd"
_OMD_PY = os.path.join(_OMD_ROOT, ".venv", "bin", "python")
_OMD_TEST = "tests/test_p2_p4_harness.py"


def test_omd_p2_hotfile_dimension_test_passes_in_real_substrate():
    """Independent corroboration: 실 OMD venv 에서 P2 hot-file 하네스 차원테스트 통과
    (실 git repo 위 hot_file_audit/gate — 검출·정렬·max_hot NO_GO)."""
    assert os.path.isfile(_OMD_PY), f"OMD venv python missing: {_OMD_PY}"
    assert os.path.isfile(os.path.join(_OMD_ROOT, _OMD_TEST)), f"missing: {_OMD_TEST}"

    proc = subprocess.run(
        [_OMD_PY, "-m", "pytest", _OMD_TEST, "-q", "-p", "no:cacheprovider"],
        cwd=_OMD_ROOT, capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, (
        f"real OMD P2 hot-file dimension test failed.\nrc={proc.returncode}\n"
        f"STDOUT:\n{proc.stdout[-4000:]}\nSTDERR:\n{proc.stderr[-2000:]}")
    assert "passed" in proc.stdout, proc.stdout[-2000:]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
