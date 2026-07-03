"""test_omd_engine_p4_idemgc.py — PROM guard for OMD P4 (idempotency 테이블 GC).

LakatoTree research-programme guard. Two independent oracles, two sources of truth.

PROBLEM (omd/docs/FEEDBACK_problems_20260630.md §P4 / CONCURRENCY.md §D9)
  "request_id 행 무한 누적" — exactly-once 를 주는 idempotency 테이블에 GC 가 없으면
  변이 동사 호출마다 행이 하나씩 영구히 쌓인다(설계 문서가 스스로 인정한 design-only 부채).
  장수 코디네이터에서 무한 성장 = 자원 고갈로 가는 침묵 퇴행.

PRINCIPLE (problemshift)
  변환-불변식 3종을 지키는 TTL GC: ① idem_ttl 지난 DONE 행은 sweep 이 삭제(누적 차단),
  ② INFLIGHT(completed_at 없음)는 나이 무관 절대 보존(진행중 멱등 윈도우), ③ ttl 이내
  DONE 은 보존되어 같은 request_id replay 가 캐시 적중(exactly-once 의미 유지).

OMD artifact corroborated (real substrate, read-only):
  - omd_server/core.py _sweep_inline : idem_ttl 지난 DONE 행 정리(무한누적 차단).
  - tests/test_p4_idem_gc.py         : 만료삭제·INFLIGHT 보존·replay 유지·ttl=None GC off.

ORACLES
  guard_defect (test_gcless_idem_table_grows_unbounded_ttl_gc_bounds_it):
      Self-contained, revert-proof in-test model. NAIVE 테이블(GC 없음)은 만료 DONE 이
      쌓여 단조 무한성장(the anomaly). TTL GC 는 만료 DONE 만 지우고 INFLIGHT/최근
      DONE/replay 의미를 보존. Revert: ttl=None → 무한성장 복귀.

  guard_mechanism (test_omd_p4_idem_gc_dimension_test_passes_in_real_substrate):
      BEHAVIORAL — 실 OMD venv 에서 tests/test_p4_idem_gc.py 를 subprocess 로 돌려 rc==0.
      in-test 모델과 독립(실 Coordinator(idem_ttl=..)+sweep()+SQLite store 구동). 부재 시 정직 FAIL.
"""

import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(
    not os.path.isdir("<WORKSPACE>/PROJECT/PI/omd"),
    reason="OMD 자매 repo 미체크아웃(hermetic CI) — 크로스레포 도그푸드 가드는 로컬에서만 실측")

# ---------------------------------------------------------------------------
# Self-contained model for guard_defect (mirrors store idempotency + _sweep_inline GC).
# 결정적 fake clock — time.time() 미사용.
# ---------------------------------------------------------------------------


class _IdemTable:
    """request_id → (state, completed_at). ttl=None 이 NAIVE(GC 없음 — the revert),
    숫자 ttl 이 원리 GC."""

    def __init__(self, ttl=None):
        self.ttl = ttl
        self.rows = {}     # rid -> dict(state, completed_at, result)

    def begin(self, rid, now):
        self.rows[rid] = {"state": "INFLIGHT", "completed_at": None,
                          "created_at": now, "result": None}

    def done(self, rid, result, now):
        self.rows[rid].update(state="DONE", completed_at=now, result=result)

    def lookup(self, rid):
        row = self.rows.get(rid)
        return None if row is None or row["state"] != "DONE" else row["result"]

    def sweep(self, now):
        if self.ttl is None:                       # NAIVE: GC off → 무한누적
            return
        expired = [rid for rid, r in self.rows.items()
                   if r["state"] == "DONE" and now - r["completed_at"] > self.ttl]
        for rid in expired:
            del self.rows[rid]


def _churn(table, n, *, t0=0.0):
    """n 개의 변이 요청을 처리하고 전부 DONE 으로 완료(각 1초 간격)."""
    for i in range(n):
        rid = f"r{i}"
        table.begin(rid, now=t0 + i)
        table.done(rid, result={"ok": True, "i": i}, now=t0 + i)


# ---------------------------------------------------------------------------
# guard_defect  (negative / improvement oracle) — LOAD-BEARING
# ---------------------------------------------------------------------------


def test_gcless_idem_table_grows_unbounded_ttl_gc_bounds_it():
    """NAIVE(GC 없음)는 만료 DONE 100행이 sweep 후에도 100행(단조 무한성장 — the anomaly).
    TTL GC 는 만료만 삭제해 성장을 상한하되, INFLIGHT·최근 DONE·replay 의미는 보존."""

    naive = _IdemTable(ttl=None)
    _churn(naive, 100)
    naive.sweep(now=999_999.0)                     # 아득한 미래에도
    assert len(naive.rows) == 100, "naive: 만료 행이 영원히 남는다(무한누적)"

    gc = _IdemTable(ttl=3600.0)
    _churn(gc, 100)                                # 전부 t≈0~99 에 DONE
    gc.begin("inflight-1", now=0.0)                # 아주 오래된 INFLIGHT
    gc.begin("recent-1", now=999_000.0)
    gc.done("recent-1", result={"ok": True}, now=999_000.0)   # ttl 이내 DONE
    gc.sweep(now=999_999.0)

    assert all(f"r{i}" not in gc.rows for i in range(100)), "만료 DONE 은 전부 수거"
    assert "inflight-1" in gc.rows, "INFLIGHT 는 나이 무관 절대 보존(진행중 멱등 윈도우)"
    assert gc.lookup("recent-1") == {"ok": True}, "ttl 이내 DONE replay 는 캐시 적중 유지"
    assert len(gc.rows) == 2, "성장이 live 행 수로 상한된다"

    # The property genuinely depends on the mechanism: naive 100 vs gc 2.
    assert len(naive.rows) != len(gc.rows)


def test_revert_proof_ttl_none_reintroduces_unbounded_growth():
    """Negative control / revert-proof: 같은 churn 을 ttl=None 으로 돌리면 다시 무한성장 —
    상한 단언이 GC 기제에 load-bearing 임을 증명. 그리고 GC 는 미래 행을 오삭제하지 않는다."""
    reverted = _IdemTable(ttl=None)
    _churn(reverted, 50)
    reverted.sweep(now=10**9)
    assert len(reverted.rows) == 50

    fresh = _IdemTable(ttl=3600.0)
    _churn(fresh, 10, t0=1000.0)
    fresh.sweep(now=1010.0)                        # 아무것도 안 만료
    assert len(fresh.rows) == 10, "ttl 이내 행은 하나도 안 지움(오삭제 0)"


# ---------------------------------------------------------------------------
# guard_mechanism  (positive / novel oracle) — LOAD-BEARING
# ---------------------------------------------------------------------------

_OMD_ROOT = "<WORKSPACE>/PROJECT/PI/omd"
_OMD_PY = os.path.join(_OMD_ROOT, ".venv", "bin", "python")
_OMD_TEST = "tests/test_p4_idem_gc.py"


def test_omd_p4_idem_gc_dimension_test_passes_in_real_substrate():
    """Independent corroboration: 실 OMD venv 에서 P4 idem-GC 차원테스트 통과
    (실 Coordinator idem_ttl + sweep() + SQLite idempotency 테이블 구동)."""
    assert os.path.isfile(_OMD_PY), f"OMD venv python missing: {_OMD_PY}"
    assert os.path.isfile(os.path.join(_OMD_ROOT, _OMD_TEST)), f"missing: {_OMD_TEST}"

    proc = subprocess.run(
        [_OMD_PY, "-m", "pytest", _OMD_TEST, "-q", "-p", "no:cacheprovider"],
        cwd=_OMD_ROOT, capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, (
        f"real OMD P4 idem-GC dimension test failed.\nrc={proc.returncode}\n"
        f"STDOUT:\n{proc.stdout[-4000:]}\nSTDERR:\n{proc.stderr[-2000:]}")
    assert "passed" in proc.stdout, proc.stdout[-2000:]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
