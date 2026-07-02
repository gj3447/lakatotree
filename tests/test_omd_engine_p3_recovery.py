"""test_omd_engine_p3_recovery.py — PROM guard for OMD P3 (충돌 복구 UX: 진단 동봉 + rerere).

LakatoTree research-programme guard. Two independent oracles, two sources of truth.

PROBLEM (FEEDBACK §P3 잔여 — 논의 노드 p3_conflict_recovery_ux 의 관측 3건이 근거)
  배타(write) 충돌의 유일 발생경로는 out-of-band 우회(P1)라 '충돌=경보'는 옳으나, 경보
  *이후*가 비어 있었다: rollback+retryable 뿐 — 원인 진단 0(누가 통합을 갈랐나), 복구
  레시피 0, 동일충돌이 재시도마다 반복(기억 0).

PRINCIPLE (problemshift — omd 증분13, 커밋 72128b5; 문헌: Zuul reporter/git rerere/jj)
  O1 진단 동봉: GitMergeConflict(충돌 경로) + _diagnose_conflict — 응답에 conflict_files/
  culprits(통합측 first-parent 원인커밋을 bypass_audit 분류·작성자와 함께 지목)/rebase hint.
  O2 rerere 레인: rerere.enabled+autoUpdate(rr-cache 전 worktree 공유), 기록된 해소가 충돌을
  전부 재해소하면 merge_into 가 머지를 완성(OMD-Connect trailer 보존). O3(resolve-태스크
  승격)는 정직 잔여.

OMD artifact corroborated (real substrate, read-only):
  - omd_server/gitio.py GitMergeConflict/enable_rerere/merge_into 완성경로/commits_touching.
  - omd_server/core.py _diagnose_conflict + Phase C 진단 동봉.
  - tests/test_p3_conflict_ux.py : 우회충돌 진단/shared 진단/rerere 활성/동일충돌 자동재해소 4종.

ORACLES
  guard_defect (test_bare_alarm_gives_no_recovery_enriched_response_and_rerere_do):
      Self-contained, revert-proof in-test model. NAIVE(맨 경보)는 진단 0 + 동일충돌 무한
      반복(the anomaly). 원리 응답은 파일/범인/레시피 동봉 + 해소 1회 기록 후 동일충돌
      자동 재해소. Revert: 진단·기억 off → 막막함 복귀.

  guard_mechanism (test_omd_p3_conflict_ux_dimension_test_passes_in_real_substrate):
      BEHAVIORAL — 실 OMD venv 에서 tests/test_p3_conflict_ux.py 를 subprocess 로 돌려
      rc==0 (실 git 우회커밋·실 rerere rr-cache 구동). 부재 시 정직 FAIL.
"""

import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(
    not os.path.isdir("<WORKSPACE>/PROJECT/PI/omd"),
    reason="OMD 자매 repo 미체크아웃(hermetic CI) — 크로스레포 도그푸드 가드는 로컬에서만 실측")

# ---------------------------------------------------------------------------
# Self-contained model for guard_defect (bare alarm vs enriched diagnosis + rerere memory).
# ---------------------------------------------------------------------------


class _Connect:
    """충돌 응답 모델. enriched=False 가 NAIVE(맨 경보 — the revert)."""

    def __init__(self, enriched: bool):
        self.enriched = enriched
        self.rr_cache = {}           # preimage -> resolution (rerere 기억)

    def attempt(self, conflict, integration_log):
        """conflict = {file, preimage, integration_culprit}. 기록된 해소가 있으면 자동 완성."""
        if self.enriched and conflict["preimage"] in self.rr_cache:
            return {"ok": True, "state": "MERGED",
                    "resolved_by": "rerere", "content": self.rr_cache[conflict["preimage"]]}
        out = {"ok": False, "reason": "merge conflict", "retryable": True}
        if self.enriched:
            out["conflict_files"] = [conflict["file"]]
            out["culprits"] = [c for c in integration_log
                               if conflict["file"] in c["files"]]
            out["hint"] = "rebase onto integration tip; 해소는 rerere 가 기록·재사용"
        return out

    def record_resolution(self, conflict, resolution):
        if self.enriched:
            self.rr_cache[conflict["preimage"]] = resolution


_LOG = [{"sha": "byp123", "kind": "direct_commit", "author": "human",
         "files": ["constants/env.py"]}]
_CONFLICT = {"file": "constants/env.py", "preimage": "X:1|222|999",
             "integration_culprit": "byp123"}


# ---------------------------------------------------------------------------
# guard_defect  (negative / improvement oracle) — LOAD-BEARING
# ---------------------------------------------------------------------------


def test_bare_alarm_gives_no_recovery_enriched_response_and_rerere_do():
    """NAIVE(맨 경보): 진단 0 + 해소를 기록해도 동일충돌이 영원히 반복(the anomaly).
    원리: 파일/범인(kind·author)/레시피 동봉 + 해소 1회 기록 후 동일충돌 자동 MERGED."""

    naive = _Connect(enriched=False)
    r = naive.attempt(_CONFLICT, _LOG)
    assert r["ok"] is False and "conflict_files" not in r and "culprits" not in r, (
        "naive: 물방울은 뭘 고쳐야 할지 알 수 없다")
    naive.record_resolution(_CONFLICT, "X = 999222")         # 기록해도(기억 없음)
    r2 = naive.attempt(_CONFLICT, _LOG)
    assert r2["ok"] is False, "naive: 동일충돌 무한 반복"

    fixed = _Connect(enriched=True)
    r = fixed.attempt(_CONFLICT, _LOG)
    assert r["conflict_files"] == ["constants/env.py"]
    assert r["culprits"][0]["sha"] == "byp123" and r["culprits"][0]["kind"] == "direct_commit"
    assert "rebase" in r["hint"]
    fixed.record_resolution(_CONFLICT, "X = 999222")
    r2 = fixed.attempt(_CONFLICT, _LOG)
    assert r2["ok"] is True and r2["resolved_by"] == "rerere", "동일충돌 자동 재해소"
    assert r2["content"] == "X = 999222"

    # The property genuinely depends on the mechanism: 반복 실패 vs 자동 성공.
    assert naive.attempt(_CONFLICT, _LOG)["ok"] != fixed.attempt(_CONFLICT, _LOG)["ok"]


def test_revert_proof_disabling_enrichment_reintroduces_helplessness():
    """Negative control / revert-proof: enriched 를 끄면 같은 시나리오가 다시 진단 0·반복
    실패로 돌아간다. 그리고 기억이 있어도 *다른* preimage(새 충돌)는 자동 해소하지 않는다
    (오적용 0 — rerere 의 preimage-일치 의미론)."""
    reverted = _Connect(enriched=False)
    reverted.record_resolution(_CONFLICT, "X = 999222")
    assert reverted.attempt(_CONFLICT, _LOG)["ok"] is False

    fixed = _Connect(enriched=True)
    fixed.record_resolution(_CONFLICT, "X = 999222")
    other = dict(_CONFLICT, preimage="X:1|333|999")          # 다른 충돌
    r = fixed.attempt(other, _LOG)
    assert r["ok"] is False and "hint" in r, "새 충돌은 자동 해소 금지(진단만)"


# ---------------------------------------------------------------------------
# guard_mechanism  (positive / novel oracle) — LOAD-BEARING
# ---------------------------------------------------------------------------

_OMD_ROOT = "<WORKSPACE>/PROJECT/PI/omd"
_OMD_PY = os.path.join(_OMD_ROOT, ".venv", "bin", "python")
_OMD_TEST = "tests/test_p3_conflict_ux.py"


def test_omd_p3_conflict_ux_dimension_test_passes_in_real_substrate():
    """Independent corroboration: 실 OMD venv 에서 증분13 차원테스트 4종 통과 —
    실 git 우회커밋 진단(first-parent bypass 분류) + 실 rerere 동일충돌 자동재해소."""
    assert os.path.isfile(_OMD_PY), f"OMD venv python missing: {_OMD_PY}"
    assert os.path.isfile(os.path.join(_OMD_ROOT, _OMD_TEST)), f"missing: {_OMD_TEST}"

    proc = subprocess.run(
        [_OMD_PY, "-m", "pytest", _OMD_TEST, "-q", "-p", "no:cacheprovider"],
        cwd=_OMD_ROOT, capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, (
        f"real OMD P3 conflict-UX dimension test failed.\nrc={proc.returncode}\n"
        f"STDOUT:\n{proc.stdout[-4000:]}\nSTDERR:\n{proc.stderr[-2000:]}")
    assert "passed" in proc.stdout, proc.stdout[-2000:]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
