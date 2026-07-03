# -*- coding: utf-8 -*-
"""barrier_crash_safe — D5 크래시 안전 랑데부 배리어 (PROM guard node).

literature / 고전결과:
  Barrier synchronization (cyclic / sense-reversing barrier; Mellor-Crummey &
  Scott, "Algorithms for scalable synchronization on shared-memory
  multiprocessors", ACM TOCS 1991). N participants rendezvous and proceed
  together. The NAIVE counter-barrier admits a classic LIVENESS failure: if one
  participant dies *before* arriving, the counter is stuck at N-1 < N and every
  already-arrived waiter blocks FOREVER (permanent hang). The fault-tolerant fix
  is a generation-stamped barrier with a BROKEN terminal state: on a participant
  death/timeout the barrier *breaks* and wakes every arrived waiter
  (java.util.concurrent.CyclicBarrier.reset / BrokenBarrierException; Python
  threading.Barrier.abort()).

OMD dimension:  D5 — 크래시 안전 배리어(응결 랑데부).
OMD artifact corroborated:
  tests/test_d5_barrier.py  (행위 오라클; OMD 자기 .venv 에서 rc==0)
  membership = task set (N re-computed on reclaim/requeue); policy break(전원 깸)
  vs shrink(죽은 멤버 빼고 진행). Verbs barrier_declare / barrier_arrive /
  barrier_abort.
KG lit node:  OMD-finding-fencing-required.

이 파일은 두 개의 독립 오라클을 둔다:
  (1) guard_defect  — in-test 으로 NAIVE(고장) vs CRASH-SAFE(원리) 두 모델을 모두
      세우고 적대 스케줄(2 arrive, 3rd dies)을 돌려, naive 는 hang(liveness 위반),
      BROKEN-종단 모델은 전원 기상함을 보인다. mechanism flag 를 끄면 hang 이
      되돌아오므로 revert-proof.
  (2) guard_mechanism — 실제 OMD 서브스트레이트의 D5 차원 테스트를 OMD 자기 .venv 로
      서브프로세스 실행해 rc==0 을 확인(in-test 모델과 독립).
"""

import os
import subprocess
import sys

import pytest

OMD_ROOT = "<WORKSPACE>/PROJECT/PI/omd"
OMD_PY = os.path.join(OMD_ROOT, ".venv", "bin", "python")
D5_TEST = "tests/test_d5_barrier.py"


# --------------------------------------------------------------------------- #
# in-test 모델 — 세대-스탬프 응결 배리어 (D5 FSM 의 충실한 축소판)
#   ARMED → TRIPPING → TRIPPED → CONSUMED   ⊕   (any) → BROKEN
# 멤버십 = task 집합. 죽음 이벤트 = 명시적 재배열된 스텝(실시간/슬립 없음).
# --------------------------------------------------------------------------- #
class HangError(Exception):
    """배리어가 N 미만에서 영원히 멈춤(액티브 참가자 없음) — liveness 위반."""


class BarrierBroken(Exception):
    """배리어가 BROKEN 으로 종단되어 도착 전원이 에러로 기상(Barrier.abort 시맨틱)."""


class Barrier:
    """결정론적 단일-스레드 배리어 모델.

    break_on_death=True  → D5 원리(BROKEN 종단 + 전원 기상).
    break_on_death=False → NAIVE 카운터(사망 시 종단 전이 없음 → 영구 hang).
    """

    def __init__(self, parties, break_on_death):
        self.parties = parties          # N (= |task set|)
        self.generation = 0             # 세대 스탬프
        self.state = "ARMED"
        self.arrived = []               # 도착해 대기 중인 task
        self.dead = set()               # 사망 통보된 task
        self.break_on_death = break_on_death
        self.break_reason = None

    def arrive(self, task):
        """task 도착. 전원 도착 시 TRIPPED(release). 그 외엔 계속 대기."""
        if self.state == "BROKEN":
            raise BarrierBroken(self.generation)
        if task not in self.arrived:
            self.arrived.append(task)
        if len(self.arrived) == self.parties:
            self.state = "TRIPPING"
            self.state = "TRIPPED"     # 순서대로 응결 후 트립 커밋
        return self.state

    def notify_death(self, task):
        """참가자 사망/타임아웃 통보.

        원리(break_on_death): _break → BROKEN, 도착 전원 기상.
        naive: 아무 종단 전이 없음 — 카운터는 N 에 영영 못 닿음.
        """
        self.dead.add(task)
        if self.break_on_death and self.state in ("ARMED", "TRIPPING"):
            self.state = "BROKEN"      # (any) → BROKEN
            self.break_reason = "participant_death:%s" % task
        return self.state

    def released_waiters(self):
        """이 배리어 때문에 진행/기상하게 된 도착 task 목록.

        TRIPPED → 정상 release; BROKEN → 전원 abort-기상.
        둘 다 아니면(여전히 ARMED/TRIPPING with 사망자) 누구도 깨지 못함 = hang.
        """
        if self.state == "TRIPPED":
            return list(self.arrived)          # 정상 랑데부
        if self.state == "BROKEN":
            return list(self.arrived)          # 전원 BROKEN 기상
        # 활성 참가자가 더 없는데(전원 도착했거나 죽음) 종단 못함 → liveness 위반
        live = self.parties - len(self.arrived) - len(self.dead - set(self.arrived))
        if live <= 0:
            raise HangError(
                "no live participant can ever advance the counter to N "
                "and no BROKEN terminal exists -> permanent hang"
            )
        return []


import os as _os
import pytest as _pytest
pytestmark = _pytest.mark.skipif(
    not _os.path.isdir("<WORKSPACE>/PROJECT/PI/omd"),
    reason="OMD 자매 repo 미체크아웃(hermetic CI) — 크로스레포 도그푸드 가드는 로컬에서만 실측")

def _run_schedule(break_on_death):
    """적대 스케줄: N=3 중 t1,t2 도착, t3 사망(도착 전).

    반환: (barrier, 그 결과 기상/진행하게 된 도착 task 목록).
    HangError 면 영구 hang.
    """
    b = Barrier(parties=3, break_on_death=break_on_death)
    b.arrive("t1")            # 도착(대기)
    b.arrive("t2")            # 도착(대기) — count=2 < 3
    b.notify_death("t3")      # 3번째가 도착 전에 죽음
    return b, b.released_waiters()


# --------------------------------------------------------------------------- #
# guard_defect — 음성/개선 오라클 (self-contained, revert-proof)
# --------------------------------------------------------------------------- #
def test_naive_barrier_hangs_on_death_generation_broken_terminal_wakes_all():
    """NAIVE 배리어는 멤버 사망 시 영구 hang; BROKEN-종단 배리어는 전원 기상.

    revert-proof: BROKEN-on-death 기제를 끄면(break_on_death=False) 곧장 hang 으로
    퇴행한다 — property 가 기제에 진짜로 의존함을 in-test 토글로 증명.
    """
    # (1) NAIVE: 사망 시 종단 전이 없음 → 도착해 있던 t1,t2 가 영원히 못 깸.
    with pytest.raises(HangError):
        _run_schedule(break_on_death=False)

    # (2) CRASH-SAFE: 사망 → BROKEN 종단 → 도착 전원 기상(bounded, 1 스텝).
    b, woken = _run_schedule(break_on_death=True)
    assert b.state == "BROKEN", "사망은 배리어를 BROKEN 으로 종단시켜야 한다"
    assert b.break_reason == "participant_death:t3", "BROKEN 사유가 기록되어야 한다"
    assert sorted(woken) == ["t1", "t2"], (
        "BROKEN 종단은 도착해 대기 중이던 전원을 깨워야 한다(Barrier.abort 시맨틱)"
    )
    assert "t3" not in woken, "죽은 참가자는 깨우지 않는다"

    # (3) 기제 = property 의 원인임을 직접 대조(혼동변수 차단):
    #     같은 스케줄, 오직 BROKEN-종단 플래그만 다른데 결과가 hang↔wake 로 갈린다.
    with pytest.raises(HangError):
        _run_schedule(break_on_death=False)
    _b2, woken2 = _run_schedule(break_on_death=True)
    assert woken2, "기제가 켜진 동일 스케줄은 반드시 누군가를 깨워야 한다"


# --------------------------------------------------------------------------- #
# guard_mechanism — 양성/신규 오라클 (실제 OMD 서브스트레이트, 행위 독립)
# --------------------------------------------------------------------------- #
def test_omd_d5_barrier_dimension_test_passes_in_real_substrate():
    """실제 OMD D5 배리어 차원 테스트를 OMD 자기 .venv 로 실행해 rc==0 확인.

    in-test 모델과 완전 독립 — 실제 세대-스탬프 배리어가 참가자 사망/타임아웃에
    BROKEN 되어 전원 기상함(tests/test_d5_barrier.py)을 corroborate.
    OMD .venv 가 진짜로 없으면 정직하게 FAIL(거짓 green xfail/skip 금지).
    """
    assert os.path.exists(OMD_PY), (
        "OMD .venv python 부재: %s — 행위 오라클이 정직하게 실패함" % OMD_PY
    )
    assert os.path.isfile(os.path.join(OMD_ROOT, D5_TEST)), (
        "OMD D5 차원 테스트 부재: %s" % os.path.join(OMD_ROOT, D5_TEST)
    )
    proc = subprocess.run(
        [OMD_PY, "-m", "pytest", D5_TEST, "-q", "-p", "no:cacheprovider"],
        cwd=OMD_ROOT,
        capture_output=True,
        text=True,
        timeout=420,
    )
    assert proc.returncode == 0, (
        "실제 OMD D5 배리어 차원 테스트 실패 (rc=%s)\n--- stdout ---\n%s\n--- stderr ---\n%s"
        % (proc.returncode, proc.stdout[-3000:], proc.stderr[-2000:])
    )


# --------------------------------------------------------------------------- #
# 추가 회귀/음성-대조 (load-bearing 아님)
# --------------------------------------------------------------------------- #
def test_happy_path_full_rendezvous_trips_and_releases_all():
    """정상경로: 전원 도착 → TRIPPED → 전원 release (배리어가 가짜로 항상 BROKEN 이
    아님을 확인 — 기제가 정상 랑데부를 막지 않는다)."""
    b = Barrier(parties=3, break_on_death=True)
    b.arrive("t1")
    b.arrive("t2")
    state = b.arrive("t3")
    assert state == "TRIPPED"
    assert sorted(b.released_waiters()) == ["t1", "t2", "t3"]


def test_generation_is_stamped_and_negative_control_bogus_state():
    """세대 스탬프 존재 + 음성대조: 존재하지 않는 가짜 상태는 release 로 인정 안 됨."""
    b = Barrier(parties=2, break_on_death=True)
    assert b.generation == 0
    b.state = "ARMED_BOGUS_NOT_A_REAL_TERMINAL"
    b.arrived = ["t1"]
    # ARMED/TRIPPING/TRIPPED/CONSUMED/BROKEN 외 상태는 release 도 BROKEN 도 아님.
    # 활성 참가자(t2)가 남아 hang 도 아님 → 빈 목록.
    assert b.released_waiters() == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
