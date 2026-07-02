"""test_omd_engine_p6_ha.py — PROM guard for OMD P6 (D14 멀티프로세스 HA 실측).

LakatoTree research-programme guard. Two independent oracles, two sources of truth.

PROBLEM (FEEDBACK §P6)
  단일 coordinator+leader·SQLite = SPOF 이고, D14(단일리더/epoch fence)는 **단일 프로세스
  안** 두 Coordinator 객체로만 검증돼 있었다 — 실제 프로세스 크래시/정지(GC-pause)를
  가로지르는 integration 실측 부재. 미검증 보장 = production 신뢰 불가.

PRINCIPLE (problemshift — omd 증분12, 커밋 aa6d6d9; 코드 무변경 측정 증분)
  실 OS 프로세스 드라이버(stdin/stdout 1줄-응답)로 3종 실증: ① 살아있는 리더 옆 2호 프로세스
  기동 = CoordinatorConflict 거부, ② SIGKILL 크래시 → TTL 후 takeover(epoch 단조 +1),
  ③ SIGSTOP(GC-pause 아날로그) → takeover → SIGCONT 로 깨어난 좀비 리더의 변이 전부 FENCED.
  SPOF 잔여는 §7 의도된 설계(단일 인스턴스 강제)로 처분, transitions 유지공백은 정직 미해소.

OMD artifact corroborated (real substrate, read-only):
  - omd_server/core.py _acquire_leadership/_assert_leader/coordinator_heartbeat (기존 D14 기제).
  - tests/test_p6_multiproc_ha.py : 실 subprocess 3종 (admission/SIGKILL takeover/SIGSTOP fence).

ORACLES
  guard_defect (test_epochless_lease_splits_brain_epoch_fence_blocks_zombie):
      Self-contained, revert-proof in-test model. NAIVE(순수 TTL lease, epoch fence 없음)는
      GC-pause 후 깨어난 옛 리더와 새 리더가 **둘 다** 쓴다(split-brain 이중쓰기 — the
      anomaly). epoch fence 는 변이마다 lease 의 (id,epoch) 재검증 → 좀비 쓰기 0.
      Revert: fence off → 이중쓰기 복귀.

  guard_mechanism (test_omd_p6_multiproc_ha_dimension_test_passes_in_real_substrate):
      BEHAVIORAL — 실 OMD venv 에서 tests/test_p6_multiproc_ha.py 를 subprocess 로 돌려
      rc==0 (실 OS 프로세스 SIGKILL/SIGSTOP 시나리오). 부재 시 정직 FAIL.
"""

import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(
    not os.path.isdir("<WORKSPACE>/PROJECT/PI/omd"),
    reason="OMD 자매 repo 미체크아웃(hermetic CI) — 크로스레포 도그푸드 가드는 로컬에서만 실측")

# ---------------------------------------------------------------------------
# Self-contained model for guard_defect (pure-TTL lease vs epoch-fenced lease).
# 결정적 fake clock — time.time() 미사용.
# ---------------------------------------------------------------------------


class _Db:
    """공유 저장소 모델: leader lease + 쓰기 로그. epoch_fence=False 가 NAIVE(the revert)."""

    def __init__(self, epoch_fence: bool):
        self.epoch_fence = epoch_fence
        self.lease = None            # {id, epoch, hb}
        self.writes = []             # (writer_id, epoch)

    def acquire(self, cid, now, ttl):
        if self.lease and (now - self.lease["hb"]) <= ttl and self.lease["id"] != cid:
            return None                                   # 살아있는 리더 — 거부
        epoch = (self.lease["epoch"] + 1) if self.lease else 1
        self.lease = {"id": cid, "epoch": epoch, "hb": now}
        return epoch

    def mutate(self, cid, epoch, payload):
        if self.epoch_fence:
            if self.lease is None or self.lease["id"] != cid or self.lease["epoch"] != epoch:
                return "FENCED"                            # 좀비 리더 차단(§D14)
        self.writes.append((cid, epoch, payload))
        return "OK"


def _gc_pause_scenario(db: _Db):
    """A 가 리더 → GC-pause(hb 중단) → TTL 경과 → B takeover → A 가 깨어나 쓴다."""
    ea = db.acquire("A", now=0.0, ttl=1.0)
    assert ea == 1
    # A 정지(GC-pause). t=2.0: lease 만료 관측 → B takeover.
    eb = db.acquire("B", now=2.0, ttl=1.0)
    assert eb == 2
    ra = db.mutate("A", ea, "zombie-write")                # A 가 깨어나 자기가 리더인 줄 앎
    rb = db.mutate("B", eb, "leader-write")
    return ra, rb


# ---------------------------------------------------------------------------
# guard_defect  (negative / improvement oracle) — LOAD-BEARING
# ---------------------------------------------------------------------------


def test_epochless_lease_splits_brain_epoch_fence_blocks_zombie():
    """NAIVE(epoch fence 없음): GC-pause 후 좀비 A 와 새 리더 B 가 둘 다 쓴다(split-brain —
    the anomaly). epoch fence: 좀비 쓰기 FENCED, 새 리더만 쓴다."""

    naive = _Db(epoch_fence=False)
    ra, rb = _gc_pause_scenario(naive)
    assert ra == "OK" and rb == "OK", "naive: 둘 다 성공(이중쓰기)"
    writers = {w for w, _, _ in naive.writes}
    assert writers == {"A", "B"}, f"split-brain: 두 writer 가 한 DB 를 변이: {writers}"

    fenced = _Db(epoch_fence=True)
    ra, rb = _gc_pause_scenario(fenced)
    assert ra == "FENCED", "좀비 리더의 쓰기는 fence-out 돼야(§D14)"
    assert rb == "OK"
    assert {w for w, _, _ in fenced.writes} == {"B"}, "epoch-현재 writer 는 최대 1"

    # The property genuinely depends on the mechanism: 2 writers vs 1 writer.
    assert len(naive.writes) != len(fenced.writes)


def test_revert_proof_disabling_fence_readmits_zombie_write():
    """Negative control / revert-proof: fence 를 끄면 같은 시나리오가 다시 이중쓰기.
    그리고 admission(살아있는 리더 옆 2호 기동 거부)은 fence 와 독립으로 동작."""
    reverted = _Db(epoch_fence=False)
    ra, _ = _gc_pause_scenario(reverted)
    assert ra == "OK" and len(reverted.writes) == 2

    live = _Db(epoch_fence=True)
    assert live.acquire("A", now=0.0, ttl=30.0) == 1
    assert live.acquire("B", now=1.0, ttl=30.0) is None, "살아있는 리더 옆 admission 거부"


# ---------------------------------------------------------------------------
# guard_mechanism  (positive / novel oracle) — LOAD-BEARING
# ---------------------------------------------------------------------------

_OMD_ROOT = "<WORKSPACE>/PROJECT/PI/omd"
_OMD_PY = os.path.join(_OMD_ROOT, ".venv", "bin", "python")
_OMD_TEST = "tests/test_p6_multiproc_ha.py"


def test_omd_p6_multiproc_ha_dimension_test_passes_in_real_substrate():
    """Independent corroboration: 실 OMD venv 에서 증분12 차원테스트 3종 통과 —
    실 OS 프로세스(SIGKILL/SIGSTOP)로 admission/takeover/좀비 fence-out 실증."""
    assert os.path.isfile(_OMD_PY), f"OMD venv python missing: {_OMD_PY}"
    assert os.path.isfile(os.path.join(_OMD_ROOT, _OMD_TEST)), f"missing: {_OMD_TEST}"

    proc = subprocess.run(
        [_OMD_PY, "-m", "pytest", _OMD_TEST, "-q", "-p", "no:cacheprovider"],
        cwd=_OMD_ROOT, capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, (
        f"real OMD P6 multiproc HA dimension test failed.\nrc={proc.returncode}\n"
        f"STDOUT:\n{proc.stdout[-4000:]}\nSTDERR:\n{proc.stderr[-2000:]}")
    assert "passed" in proc.stdout, proc.stdout[-2000:]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
