"""AG6/R-SOV V4 값무결 fsck 차원 — 반증된 측정이 서있으면 관측화 (측정주권 PROM 2026-07-03).

테제 후속(선행 [[measurement-sovereignty-prom-20260703]]): AG3 이 submit-ordering 을 흡수(incoming
replay)하고 replay_status(not_attempted/verified/mismatch)를 노드에 persist 했다. 그러나 producer
replay 가 *실행되어 측정을 반증*(mismatch)한 노드가 progressive/partial 로 서있어도 조용했다 — 승격
floor(G6)는 CANONICAL 만 막는다. AG6 는 fsck 에 **값무결 차원**을 더해 이를 관측화한다:

  MEASUREMENT_REFUTED_BUT_STANDING (WARN) : replay_status='mismatch' ∧ verdict 가 standing.

★WARN(비차단, 확정결정): boundary_fsck(min ERROR)를 안 건드려 write 를 막지 않는다 — 값무결은
*관측*이지 거부가 아니다. ★dead-σ: not_attempted(exec OFF)/verified(일치)/비-standing verdict 은
무발화(검증 불가·일치·이미 부정 ≠ 반증).

  guard_defect    = test_refuted_standing_node_is_flagged (음성: 체크 제거 시 반증-서있음 무음 → RED)
  guard_mechanism = test_warn_nonblocking_and_dead_sigma  (양성: WARN 비차단 + not_attempted/verified 무발화)

novel_script = 이 파일. # KG 거울: LakatosTree_MeasurementSovereignty_20260703 / ag6_value_integrity_fsck
"""
from __future__ import annotations

from server.contexts.audit import fsck as F

_ID = "MEASUREMENT_REFUTED_BUT_STANDING"
_SCRIPTED_SOURCE_ID = "SCRIPTED_WITHOUT_SOURCE"


def _ids(rec):
    return {f.check_id for f in F.fsck_node(rec)}


def test_progressive_unverified_mismatch_keeps_value_integrity_warning():
    """PU is programme-neutral, but its metric result is still a standing measurement claim."""
    assert _ID in _ids({"verdict": "progressive_unverified", "replay_status": "mismatch"})


def test_offline_progressive_unverified_without_source_or_receipt_fails_closed():
    """An offline-corrupted PU row cannot evade scripted-source integrity checks."""
    rec = {
        "verdict": "progressive_unverified",
        "pred_registered_at": "2026-07-14T00:00:00Z",
        "assurance_tier_resolved": "T0",
    }

    findings = F.fsck_node(rec)

    assert _SCRIPTED_SOURCE_ID in {finding.check_id for finding in findings}
    assert next(f for f in findings if f.check_id == _SCRIPTED_SOURCE_ID).severity == F.ERROR

    managed = {
        **rec,
        "verdict_source": "scripted",
        "current_receipt_sha": "0" * 64,
    }
    assert _SCRIPTED_SOURCE_ID not in _ids(managed)

    # Scope guard: historical scripted verdicts retain their pre-source-stamping semantics.
    legacy = {**rec, "verdict": "progressive"}
    assert _SCRIPTED_SOURCE_ID not in _ids(legacy)


# ── guard_defect ──────────────────────────────────────────────────────────────────
def test_refuted_standing_node_is_flagged():
    """replay 가 값을 반증(mismatch)했는데 standing verdict 를 든 노드 → 값무결 WARN 표면화."""
    assert _ID in _ids({"replay_status": "mismatch", "verdict": "progressive"})
    assert _ID in _ids({"replay_status": "mismatch", "verdict": "CANONICAL"})
    assert _ID in _ids({"replay_status": "mismatch", "verdict": "partial"})
    assert _ID in _ids({"replay_status": "mismatch", "verdict": "progressive_conditional"})


# ── guard_mechanism ───────────────────────────────────────────────────────────────
def test_warn_nonblocking_and_dead_sigma():
    """WARN(비차단) + dead-σ 무발화(검증 불가·일치·이미 부정 ≠ 반증)."""
    rec = {"replay_status": "mismatch", "verdict": "progressive"}
    finding = next(f for f in F.fsck_node(rec) if f.check_id == _ID)
    assert finding.severity == F.WARN, finding.severity
    # WARN → 쓰기 경계(min ERROR)를 안 막는다(값무결=관측이지 거부 아님).
    assert _ID not in {f.check_id for f in F.boundary_fsck(rec)}
    # dead-σ: not_attempted(exec OFF)/verified(일치)/None → 무발화.
    for st in ("not_attempted", "verified", None):
        assert _ID not in _ids({"replay_status": st, "verdict": "progressive"})
    # 비-standing verdict(이미 부정) → 무발화(반증-서있음의 '서있음'이 조건).
    for v in ("rejected", "different_programme", "former_canonical", None):
        assert _ID not in _ids({"replay_status": "mismatch", "verdict": v})


def test_severity_registered_in_ssot():
    """check-id 가 _SEVERITY SSOT 에 WARN 으로 등재(열거되지 않은 부패는 존재하지 않는 것처럼 다루지 않는다)."""
    assert F._SEVERITY.get(_ID) == F.WARN


guard_defect = "test_refuted_standing_node_is_flagged"
guard_mechanism = "test_warn_nonblocking_and_dead_sigma"
