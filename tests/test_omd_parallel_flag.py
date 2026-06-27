"""OMD-parallel guard — D3 flag crash semantics: EPHEMERAL(=lease) vs LATCH(durable) 두-종류 분리.

원리(D3): producer-소유 신호 하나에 *두 상충 요구*가 산다 —
  (1) 내구 사실(done/merged): producer 가 죽어도 *살아남아야* 한다(consumer 가 done 을 봐야).
  (2) 소유 신호(build_running): producer 가 죽으면 *사라져야* 한다(죽은 producer 의 소유를 consumer 가
      신뢰하면 위험; 영구 hang 도).
단일-종류 플래그는 둘 중 하나를 반드시 어긴다(auto-clear 면 내구사실 분실, persist 면 소유신호 누수).
OMD 해법 = **두 종류 분리**: LATCH(영속·단조 done(1)<merged(2)·downgrade 거부·회수 안 함) +
EPHEMERAL(owned+TTL lease·producer 사망 시 BROKEN/PRODUCER_DEAD 로 대기자 기상).

  guard_defect(음성/개선축): 단일-종류 정책(all_ephemeral|all_latch)이 내구·소유 둘을 동시충족 못 함을,
    테스트 안 split vs 단일 모델 둘 다 돌려 revert-proof 로 증명(split 만 둘 다 만족).
  guard_mechanism(양성/novel축): 실 OMD tests/test_d3_flags.py 를 OMD 자기 venv subprocess 로 돌려 rc==0
    (LATCH 단조/downgrade-거부/producer-death-생존 + EPHEMERAL lease/PRODUCER_DEAD 기상 실증).

문헌: producer-owned ephemeral state(ZooKeeper ephemeral znode = 세션 죽으면 소멸) vs durable latch.
# KG: LakatosTree_OmdParallel_20260627 / flag_crash_safe   근거: omd/CONCURRENCY.md §D3 · tests/test_d3_flags.py
"""
from __future__ import annotations

import os
import subprocess

OMD_ROOT = "<WORKSPACE>/PROJECT/PI/omd"
OMD_PY = os.path.join(OMD_ROOT, ".venv/bin/python")
D3_TEST = "tests/test_d3_flags.py"

_DONE, _MERGED = 1, 2   # LATCH 단조 랭크(done < merged)


# ── 자기완결 모델: 단일-종류 vs 두-종류 플래그 스토어 ───────────────────────────
class FlagStore:
    """policy ∈ {'all_ephemeral','all_latch','split'}.

    - all_ephemeral: 모든 플래그가 lease — producer 사망 시 자동 소멸(소유신호엔 옳지만 내구사실 분실).
    - all_latch    : 모든 플래그가 영속 — 사망 후에도 생존(내구사실엔 옳지만 소유신호 누수).
    - split        : 호출자가 kind 를 고른다(LATCH=내구, EPHEMERAL=소유) — D3 의 정답.
    """

    def __init__(self, policy: str):
        self.policy = policy
        self.flags: dict[str, dict] = {}      # key -> {value, kind, alive}
        self.woken: list[tuple[str, str]] = []  # (key, reason) — 대기자 기상 로그

    def _effective_kind(self, requested: str) -> str:
        if self.policy == "all_ephemeral":
            return "EPHEMERAL"
        if self.policy == "all_latch":
            return "LATCH"
        return requested                      # split: 요청대로

    def set(self, key: str, value, kind: str):
        self.flags[key] = {"value": value, "kind": self._effective_kind(kind), "alive": True}

    def producer_dies(self, key: str):
        """보유 producer 사망. EPHEMERAL(lease)이면 회수(소멸 + PRODUCER_DEAD 기상);
        LATCH(영속)이면 사실 생존(회수 안 함)."""
        f = self.flags.get(key)
        if not f:
            return
        if f["kind"] == "EPHEMERAL":
            f["alive"] = False
            self.woken.append((key, "PRODUCER_DEAD"))   # 대기자 기상 = 영구 hang 0
        # LATCH: no-op (사실은 살아남는다)

    def get(self, key: str):
        f = self.flags.get(key)
        return f["value"] if (f and f["alive"]) else None


import os as _os
import pytest as _pytest
pytestmark = _pytest.mark.skipif(
    not _os.path.isdir("<WORKSPACE>/PROJECT/PI/omd"),
    reason="OMD 자매 repo 미체크아웃(hermetic CI) — 크로스레포 도그푸드 가드는 로컬에서만 실측")

def _durable_fact_preserved(policy: str) -> bool:
    """내구 사실(merged): producer 가 set 후 죽어도 consumer 가 여전히 볼 수 있어야 True."""
    s = FlagStore(policy)
    s.set("task:done", _MERGED, kind="LATCH")
    s.producer_dies("task:done")
    return s.get("task:done") == _MERGED


def _ownership_signal_cleared_and_wakes(policy: str) -> bool:
    """소유 신호(build_running): producer 사망 시 신호가 사라지고 대기자가 PRODUCER_DEAD 로 기상해야 True."""
    s = FlagStore(policy)
    s.set("build:running", "running", kind="EPHEMERAL")
    s.producer_dies("build:running")
    cleared = s.get("build:running") is None
    woke = ("build:running", "PRODUCER_DEAD") in s.woken
    return cleared and woke


# ── GUARD: DEFECT oracle (음성/개선축) — 단일-종류는 둘 동시충족 불가, split 만 가능 ──
def test_single_kind_flag_cannot_serve_both_durable_and_ownership_split_does():
    """revert-proof: 단일 정책은 내구·소유 중 하나를 반드시 어긴다. 두-종류 split 만 둘 다 만족."""
    # all_ephemeral: 소유 OK, 내구 분실
    assert _ownership_signal_cleared_and_wakes("all_ephemeral") is True
    assert _durable_fact_preserved("all_ephemeral") is False, "ephemeral-only 가 내구사실을 분실 안 함 — 결함 재현 실패"

    # all_latch: 내구 OK, 소유 누수(죽은 producer 신호 영속 + 기상 없음 → 영구 hang/오신뢰)
    assert _durable_fact_preserved("all_latch") is True
    assert _ownership_signal_cleared_and_wakes("all_latch") is False, "latch-only 가 소유신호를 누수 안 함 — 결함 재현 실패"

    # split(D3 정답): 둘 다 만족
    assert _durable_fact_preserved("split") is True
    assert _ownership_signal_cleared_and_wakes("split") is True

    # 단일-종류 어느 것도 split 의 '둘 다 만족'을 못 낸다 = 메커니즘(두-종류 분리)에 진짜로 의존
    split_both = _durable_fact_preserved("split") and _ownership_signal_cleared_and_wakes("split")
    eph_both = _durable_fact_preserved("all_ephemeral") and _ownership_signal_cleared_and_wakes("all_ephemeral")
    latch_both = _durable_fact_preserved("all_latch") and _ownership_signal_cleared_and_wakes("all_latch")
    assert split_both is True and eph_both is False and latch_both is False


def test_latch_monotonic_downgrade_would_corrupt_durable_fact():
    """보조(개선축 보강): LATCH 는 단조(done<merged) — downgrade(un-finish)는 내구사실 손상이므로 거부돼야.
    naive(거부 안 함)는 merged→done 으로 사실을 되돌려 입체 전제(§D3-H)를 깬다."""
    def apply(rank_now, rank_new, monotonic: bool):
        if monotonic and rank_new < rank_now:
            return rank_now            # downgrade 거부(불변)
        return rank_new
    assert apply(_MERGED, _DONE, monotonic=False) == _DONE, "naive: merged→done downgrade 통과(손상)"
    assert apply(_MERGED, _DONE, monotonic=True) == _MERGED, "LATCH: downgrade 거부, merged 유지"


# ── GUARD: MECHANISM oracle (양성/novel축) — 실 OMD substrate 독립 조달 ──
def test_omd_d3_flags_dimension_test_passes_in_real_substrate():
    """실 OMD tests/test_d3_flags.py 를 OMD 자기 venv 로 subprocess 실행, rc==0 단언(독립 출처).
    OMD venv 가 진짜로 없으면 정직히 FAIL(xfail/skip 으로 가짜 green 금지)."""
    assert os.path.isfile(OMD_PY), f"OMD venv python 부재: {OMD_PY}"
    assert os.path.isfile(os.path.join(OMD_ROOT, D3_TEST)), f"OMD D3 test 부재: {D3_TEST}"
    proc = subprocess.run(
        [OMD_PY, "-m", "pytest", D3_TEST, "-q", "-p", "no:cacheprovider"],
        cwd=OMD_ROOT, capture_output=True, text=True, timeout=300,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, (
        "실 OMD D3 flag 차원테스트가 green 아님 — 메커니즘 미확증(rc=%s)\n%s" % (proc.returncode, out[-3000:]))
    assert "passed" in out, "expected pytest 'passed' summary:\n" + out[-2000:]


def test_negative_control_bogus_omd_test_path_does_not_pass():
    """음성 대조: 존재하지 않는 OMD 테스트 경로는 rc!=0 (오라클이 공허하지 않음 — 아무거나 green 아님)."""
    proc = subprocess.run(
        [OMD_PY, "-m", "pytest", "tests/test_d3_NOPE_bogus.py", "-q"],
        cwd=OMD_ROOT, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode != 0, "존재하지 않는 테스트 경로가 통과로 잡힘 — 오라클 공허"
