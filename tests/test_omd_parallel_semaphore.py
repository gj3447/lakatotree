"""LakatoTree PROM guard — D4 crash-safe counting semaphore (permit=lease).

literature : Dijkstra counting semaphore (P/V), up to K holders. A NAIVE semaphore
             that only decrements on acquire and increments on explicit release LEAKS a
             permit when a holder crashes without releasing — available capacity erodes
             monotonically toward 0 (permanent capacity loss / deadlock).
principle  : crash-safe fix = permit-as-lease — availability is DERIVED as
             avail = max − count(ACTIVE non-expired leases). A dead holder's permit is
             EXPIRED and its slot is recovered STRUCTURALLY (no leak, no manual cleanup).
OMD dim    : D4 (크래시 안전 세마포어, 빌드 슬롯 max=N).
OMD artifact corroborated:
             <WORKSPACE>/PROJECT/PI/omd/CONCURRENCY.md L131 ("가용 = N − count(ACTIVE permit)
             이 구조적으로 복구된다 — 누수 0") & L541 ("증분 7 — D4 ... permit=lease,
             가용 = max − count(ACTIVE) — DONE"); behavioral oracle =
             <WORKSPACE>/PROJECT/PI/omd/tests/test_d4_semaphore.py (run in OMD venv;
             test_bail_holder_recovers_slot / TTL-expiry show sem_status['available']
             recovers after holder death).
KG lit node: OMD-finding-fencing-required
KG prom    : OMD framed as Lakatosian research programme (semaphore_crash_safe node).

판정 계약 / judge() contract:
  - guard_defect (test_naive_semaphore_leaks_permit_lease_derived_avail_recovers):
      self-contained, revert-proof in-test demo — NAIVE integer counter LEAKS a permit on
      crash (avail stuck at 0 forever, 3rd waiter never proceeds), while the LEASE-derived
      model (avail = max − count(ACTIVE)) recovers the slot on EXPIRE. Toggling availability
      back to the manual counter brings the leak back ⇒ assertion flips RED by construction.
  - guard_mechanism (test_omd_d4_semaphore_dimension_test_passes_in_real_substrate):
      INDEPENDENT corroboration — subprocess-run the REAL OMD D4 dimension test in OMD's OWN
      venv; rc==0 proves the real substrate recovers permits structurally. Does NOT re-derive
      from the in-test model.
"""

import os
import subprocess
import sys

import pytest

# ── 실 OMD 아티팩트 좌표 (read-only; 절대 편집/생성 금지) ───────────────────────
OMD_ROOT = "<WORKSPACE>/PROJECT/PI/omd"
OMD_VENV_PY = os.path.join(OMD_ROOT, ".venv", "bin", "python")
OMD_D4_TEST = os.path.join("tests", "test_d4_semaphore.py")  # OMD_ROOT 기준 상대


# ─────────────────────────────────────────────────────────────────────────────
# 자기완결 모델: 고전 정수-카운터 세마포어 vs permit=lease 세마포어
#   - "crash" / "GC pause" 는 실시간이 아니라 명시적 재배열 스텝으로 모델링(결정적).
#   - derive_from_leases=False → 고전 정수 카운터(누수). True → 가용 = max − count(ACTIVE).
# ─────────────────────────────────────────────────────────────────────────────
class _ModelSemaphore:
    """max=K 카운팅 세마포어의 두 구현을 한 클래스로 — 가용 계산만 갈라진다.

    derive_from_leases=False : 고전 — 정수 카운터 avail; acquire 시 avail--, release 시 avail++.
                               보유자가 release 없이 crash 하면 avail 은 영영 복구 안 됨(누수).
    derive_from_leases=True  : permit=lease — 가용을 *파생* avail = max − count(ACTIVE).
                               crash 한 보유자의 lease 를 EXPIRED 로 표시하면 슬롯이 구조적 복구.
    """

    def __init__(self, max_permits, derive_from_leases):
        self.max = max_permits
        self.derive = derive_from_leases
        self._counter = max_permits          # 고전 모드의 정수 카운터
        self._leases = {}                    # lease 모드: holder -> "ACTIVE" | "EXPIRED"

    # --- 가용: 두 진실의 원천이 갈라지는 유일 지점 ---
    def available(self):
        if self.derive:
            active = sum(1 for st in self._leases.values() if st == "ACTIVE")
            return self.max - active
        return self._counter

    # --- P / acquire ---
    def acquire(self, holder):
        if self.available() <= 0:
            return False
        if self.derive:
            self._leases[holder] = "ACTIVE"
        else:
            self._counter -= 1
        return True

    # --- V / release (정상 경로) ---
    def release(self, holder):
        if self.derive:
            # 정상 해제 = lease 종료(여기선 EXPIRED 로 수렴 표현).
            if self._leases.get(holder) == "ACTIVE":
                self._leases[holder] = "EXPIRED"
        else:
            self._counter += 1

    # --- 보유자 crash: release 를 호출하지 않은 채 사라짐 ---
    #   고전: 아무 일도 안 일어남 → 카운터가 영구 누수.
    #   lease: 외부 reclaim(bail/zombie/TTL-sweep)이 lease 를 EXPIRE → 슬롯 복구.
    def crash(self, holder):
        # 두 모드 공통: 보유자는 release 를 못 부르고 죽는다 (그래서 아무것도 안 함).
        return None

    def reclaim_expired(self, holder):
        """단일 reclaim 루틴(§1.1) 모사 — lease 모드에서만 의미. 죽은 보유자 permit 회수."""
        if self.derive and self._leases.get(holder) == "ACTIVE":
            self._leases[holder] = "EXPIRED"


import os as _os
import pytest as _pytest
_OMD_ROOT = _os.environ.get("OMD_ROOT", "<WORKSPACE>/PROJECT/PI/omd")
_OMD_ABSENT = not _os.path.isdir(_OMD_ROOT)
# audit un-gate: 자기완결 defect 오라클(naive-vs-fixed in-test 모델, OMD 불요)은 게이트 없이 CI 서 실행.
# OMD-의존 mechanism 오라클(disjoint import / TLA 파싱 / OMD venv subprocess)만 부재 시 skip(아래 @_skip_omd).
_skip_omd = _pytest.mark.skipif(
    _OMD_ABSENT, reason="OMD 자매 repo 미체크아웃/OMD_ROOT 미설정 — 크로스레포 mechanism 오라클(로컬/CI-checkout 시만)")

def _run_crash_schedule(derive_from_leases):
    """max=2. 적대적 스케줄: 두 acquire → 하나 crash(release 없음) → reclaim 시도 → 3번째 waiter.

    반환: (avail_after_crash, avail_after_reclaim, third_waiter_proceeded)
    """
    sem = _ModelSemaphore(max_permits=2, derive_from_leases=derive_from_leases)
    assert sem.available() == 2

    assert sem.acquire("agA") is True
    assert sem.acquire("agB") is True
    assert sem.available() == 0          # 두 슬롯 다 점유

    # agA 가 release 없이 crash.
    sem.crash("agA")
    avail_after_crash = sem.available()

    # 단일 reclaim 루틴이 죽은 보유자 permit 회수 시도(고전 모드엔 효과 없음).
    sem.reclaim_expired("agA")
    avail_after_reclaim = sem.available()

    # 3번째 대기자가 진행 가능한가?
    third_waiter_proceeded = sem.acquire("agC")
    return avail_after_crash, avail_after_reclaim, third_waiter_proceeded


# ─────────────────────────────────────────────────────────────────────────────
# guard_defect — 부정/개선 오라클 (self-contained, revert-proof)
# ─────────────────────────────────────────────────────────────────────────────
def test_naive_semaphore_leaks_permit_lease_derived_avail_recovers():
    """고전 정수 카운터는 crash 시 permit 을 영구 누수(avail 0 고착, 3번째 waiter 영원히 막힘);
    permit=lease(가용 = max − count(ACTIVE))는 reclaim 으로 슬롯을 구조적 복구해 waiter 진행.

    revert-proof: 가용 계산을 lease 파생→정수 카운터로 되돌리면(derive=False) 누수가 되살아나
    복구 단언이 RED 가 된다. 상수/항진명제 없음 — property 가 메커니즘에 실제 의존."""

    # --- 고전 정수 카운터: 누수 ---
    naive_crash, naive_reclaim, naive_third = _run_crash_schedule(derive_from_leases=False)
    assert naive_crash == 0, "고전: crash 직후 가용 0"
    # reclaim 루틴이 돌아도 정수 카운터엔 아무 효과 없음 → 영구 0 (영구 capacity loss).
    assert naive_reclaim == 0, "고전: reclaim 후에도 가용 0 — permit 영구 누수"
    assert naive_third is False, "고전: 3번째 waiter 는 죽은 보유자가 사라진 뒤에도 영원히 진행 불가"

    # --- permit=lease: 구조적 복구 ---
    lease_crash, lease_reclaim, lease_third = _run_crash_schedule(derive_from_leases=True)
    assert lease_crash == 0, "lease: crash 직후엔 아직 ACTIVE 2개라 가용 0"
    # reclaim 이 죽은 보유자 lease 를 EXPIRE → 가용 = 2 − count(ACTIVE=1) = 1.
    assert lease_reclaim == 1, "lease: reclaim 후 가용 1 로 구조적 복구 (누수 0)"
    assert lease_third is True, "lease: 복구된 슬롯을 3번째 waiter 가 받아 진행"

    # --- 두 모드의 분기 자체가 메커니즘 의존성의 증거 (동일 스케줄, 다른 결과) ---
    assert naive_reclaim != lease_reclaim
    assert naive_third != lease_third


# ─────────────────────────────────────────────────────────────────────────────
# 추가 negative-control 회귀: 부정논리(naive)가 정말 누수 모드인지 직접 못박음
# ─────────────────────────────────────────────────────────────────────────────
def test_lease_derivation_is_what_recovers_the_slot():
    """메커니즘 sensitivity: 같은 crash+reclaim 스케줄에서 derive 플래그만 뒤집어도
    가용 복구가 1→0 으로 사라진다. lease 파생이 *유일* 복구 원인임을 분리 입증."""
    _, lease_reclaim, _ = _run_crash_schedule(derive_from_leases=True)
    _, naive_reclaim, _ = _run_crash_schedule(derive_from_leases=False)
    assert lease_reclaim == 1 and naive_reclaim == 0


# ─────────────────────────────────────────────────────────────────────────────
# guard_mechanism — 긍정/신규 오라클 (실 OMD substrate, 독립 출처)
# ─────────────────────────────────────────────────────────────────────────────
@_skip_omd
def test_omd_d4_semaphore_dimension_test_passes_in_real_substrate():
    """독립 corroboration: 실 OMD D4 차원 테스트를 OMD 자체 venv 에서 subprocess 실행, rc==0.

    in-test 모델과 무관하게, 실제 substrate 가 permit=lease 로 슬롯을 구조적 복구함을 입증
    (bail/zombie-reclaim/TTL-sweep 가 sem_status['available'] 를 복구; no-overtaking; heartbeat
    renews). OMD venv 가 정말로 없으면 정직하게 FAIL(거짓 green skip 금지)."""
    assert os.path.isfile(OMD_VENV_PY), f"OMD venv python 없음: {OMD_VENV_PY}"
    assert os.path.isfile(os.path.join(OMD_ROOT, OMD_D4_TEST)), "OMD D4 테스트 파일 없음"

    proc = subprocess.run(
        [OMD_VENV_PY, "-m", "pytest", OMD_D4_TEST, "-q"],
        cwd=OMD_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=300,
    )
    out = proc.stdout.decode("utf-8", "replace")
    assert proc.returncode == 0, (
        "실 OMD D4 세마포어 차원 테스트 실패 (rc=%s)\n%s" % (proc.returncode, out[-4000:])
    )
    # 신호 강화: 실제로 무언가가 통과했고 실패/에러가 없음을 본문에서 확인.
    assert "passed" in out, out[-2000:]
    assert "failed" not in out and " error" not in out, out[-2000:]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
