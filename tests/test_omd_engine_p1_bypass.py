"""test_omd_engine_p1_bypass.py — PROM guard for OMD P1 (우회 fail-loud 감사).

LakatoTree research-programme guard. Two independent oracles, two sources of truth.

PROBLEM (omd/docs/FEEDBACK_problems_20260630.md §P1)
  OMD 의 "분열=0 사전보장"은 advisory — 에이전트가 opt-in 해야만 성립한다. 실측: consumer_b 세션들이
  OMD 를 우회해 공유 통합브랜치에 직접커밋 → +17 divergence. 우회 감지·차단 0건이면
  *코드는 옳은데 아무도 안 쓴다* — 보장이 사실상 무의미.

PRINCIPLE (problemshift)
  보호 통합브랜치의 first-parent 히스토리에서 커밋을 (parent 수 × OMD-Connect trailer × 작성자)
  로 분류: OMD_CONNECT(정상 응결) vs DIRECT_COMMIT/FOREIGN_MERGE/FORGED_TRAILER/FORGED_MERGE
  (우회 4종). 우회 ≥1 → fail-loud NO_GO; adoption_ratio = 경유/(경유+우회) 를 노출.

OMD artifact corroborated (real substrate, read-only):
  - omd_server/bypass_audit.py : classify()/AuditReport.adoption_ratio/gate() (fail-loud).
  - omd_server/harness.py      : CI/pre-push 하네스 진입점 (Makefile verify · warn-only hook).
  - tests/test_p1_bypass.py    : 분류 5종 + 위조 trailer/머지 + adoption 임계 게이트.

ORACLES
  guard_defect (test_trailer_blind_audit_admits_bypass_classify_fails_loud):
      Self-contained, revert-proof in-test model. trailer-blind NAIVE 감사(우회 개념 없음)는
      직접커밋·수동머지·위조 trailer 전부에 GO 를 준다(consumer_b 사고의 재현). 원리 분류기는
      우회 4종을 전부 잡고 NO_GO. Revert: trailer_blind=True 토글 → 검출 0 으로 붕괴.

  guard_mechanism (test_omd_p1_bypass_dimension_test_passes_in_real_substrate):
      BEHAVIORAL — 실 OMD venv 에서 tests/test_p1_bypass.py 를 subprocess 로 돌려 rc==0.
      in-test 모델과 독립(실 bypass_audit.classify/gate 를 구동). venv 부재 시 정직 FAIL.
"""

import os
import subprocess
import sys
from dataclasses import dataclass

import pytest

pytestmark = pytest.mark.skipif(
    not os.path.isdir("<WORKSPACE>/PROJECT/PI/omd"),
    reason="OMD 자매 repo 미체크아웃(hermetic CI) — 크로스레포 도그푸드 가드는 로컬에서만 실측")

# ---------------------------------------------------------------------------
# Self-contained model for guard_defect (mirrors bypass_audit.classify semantics).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Commit:
    sha: str
    n_parents: int
    trailer: bool          # line-exact 'OMD-Connect: <task>' 보유 여부
    author: str = "human"


def _classify(c: _Commit, omd_author: str = "omd") -> str:
    """원리 분류기 — parent 수 × trailer × 작성자 (bypass_audit.classify 미러)."""
    if c.n_parents == 0:
        return "root"
    if c.trailer:
        if c.n_parents < 2:
            return "forged_trailer"        # non-merge + trailer = 위조
        if c.author != omd_author:
            return "forged_merge"          # merge + trailer 지만 작성자≠OMD
        return "omd_connect"
    return "foreign_merge" if c.n_parents >= 2 else "direct_commit"


_BYPASS = {"direct_commit", "foreign_merge", "forged_trailer", "forged_merge"}


def _audit(history, *, trailer_blind: bool):
    """trailer_blind=True 가 NAIVE(우회 개념 없음 — 전 커밋을 정상 취급 = 감사 부재)이고,
    False 가 원리 감사다. 토글 하나가 revert-proof 스위치."""
    bypass, adopted = [], []
    for c in history:
        kind = "omd_connect" if trailer_blind else _classify(c)
        if kind == "root":
            continue
        (bypass if kind in _BYPASS else adopted).append((c.sha, kind))
    denom = len(bypass) + len(adopted)
    ratio = 1.0 if denom == 0 else len(adopted) / denom
    return {"bypass": bypass, "adoption_ratio": ratio,
            "verdict": "NO_GO" if bypass else "GO"}


_HISTORY = (
    _Commit("c0", 0, False),                      # root — 분류 제외
    _Commit("c1", 2, True, author="omd"),         # 정상 CLOUD CONNECT 응결
    _Commit("c2", 1, False),                      # 직접커밋 우회 (consumer_b 사고 유형)
    _Commit("c3", 2, False),                      # git pull/수동머지 우회
    _Commit("c4", 1, True),                       # trailer 위조 (non-merge)
    _Commit("c5", 2, True, author="human"),       # 수동 위조 머지 (작성자≠OMD)
)


# ---------------------------------------------------------------------------
# guard_defect  (negative / improvement oracle) — LOAD-BEARING
# ---------------------------------------------------------------------------


def test_trailer_blind_audit_admits_bypass_classify_fails_loud():
    """NAIVE(감사 부재)는 우회 4종 전부에 GO — 분열이 침묵으로 진행(the anomaly).
    원리 분류기는 4종 전부 검출 + adoption_ratio 노출 + fail-loud NO_GO."""

    naive = _audit(_HISTORY, trailer_blind=True)
    assert naive["verdict"] == "GO", "naive: 우회를 못 보므로 GO 를 준다(사고의 재현)"
    assert len(naive["bypass"]) == 0
    assert naive["adoption_ratio"] == 1.0, "naive 는 채택률조차 1.0 으로 오보"

    fixed = _audit(_HISTORY, trailer_blind=False)
    assert fixed["verdict"] == "NO_GO", "우회 ≥1 이면 fail-loud"
    kinds = {k for _, k in fixed["bypass"]}
    assert kinds == _BYPASS, f"우회 4종 전부 검출해야: {kinds}"
    assert fixed["adoption_ratio"] == pytest.approx(1.0 / 5.0), "경유1/(경유1+우회4)"

    # The property genuinely depends on the mechanism: naive GO vs principled NO_GO.
    assert naive["verdict"] != fixed["verdict"]


def test_revert_proof_disabling_classifier_reintroduces_silent_bypass():
    """Negative control / revert-proof: 분류기를 끄면(trailer_blind) 같은 히스토리가
    다시 clean 으로 보인다 — fixed-path 단언이 분류기에 load-bearing 임을 증명."""
    reverted = _audit(_HISTORY, trailer_blind=True)
    assert reverted["verdict"] == "GO" and not reverted["bypass"]

    # 그리고 clean 히스토리(전부 정상 응결)에선 원리 감사도 GO — 오탐 아님.
    clean = (_Commit("c0", 0, False), _Commit("c1", 2, True, author="omd"))
    ok = _audit(clean, trailer_blind=False)
    assert ok["verdict"] == "GO" and ok["adoption_ratio"] == 1.0


# ---------------------------------------------------------------------------
# guard_mechanism  (positive / novel oracle) — LOAD-BEARING
# ---------------------------------------------------------------------------

_OMD_ROOT = "<WORKSPACE>/PROJECT/PI/omd"
_OMD_PY = os.path.join(_OMD_ROOT, ".venv", "bin", "python")
_OMD_TEST = "tests/test_p1_bypass.py"


def test_omd_p1_bypass_dimension_test_passes_in_real_substrate():
    """Independent corroboration: 실 OMD venv 에서 P1 우회감사 차원테스트가 통과
    (classify 5종 + 위조 + adoption 게이트 — 실 bypass_audit/gate 구동)."""
    assert os.path.isfile(_OMD_PY), f"OMD venv python missing: {_OMD_PY}"
    assert os.path.isfile(os.path.join(_OMD_ROOT, _OMD_TEST)), f"missing: {_OMD_TEST}"

    proc = subprocess.run(
        [_OMD_PY, "-m", "pytest", _OMD_TEST, "-q", "-p", "no:cacheprovider"],
        cwd=_OMD_ROOT, capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, (
        f"real OMD P1 bypass dimension test failed.\nrc={proc.returncode}\n"
        f"STDOUT:\n{proc.stdout[-4000:]}\nSTDERR:\n{proc.stderr[-2000:]}")
    assert "passed" in proc.stdout, proc.stdout[-2000:]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
