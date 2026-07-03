#!/usr/bin/env python3
"""AG6/R-SOV V4 채점기 — 값무결 fsck 차원 미착륙 gap 수 (측정주권 2026-07-03).

측정(self-report 아님 — 실 fsck 구동): 두 gap 을 실제로 두드린다.
  gap① 관측 부재: 반증(replay_status='mismatch')+standing verdict 노드를 fsck_node 가 플래그 안 하면
       반증된 측정이 서있어도 조용하다.
  gap② WARN/dead-σ 위반: check-id 가 WARN(비차단) 아니거나 not_attempted(exec OFF)에도 발화하면
       (검증 불가를 반증으로 오분류) 값무결이 거부/오경보가 된다.
metric = 열린 gap 수(봉합 후 0). 체크/severity/dead-σ 를 떼면 값이 오른다(revert-민감). exit 0.
# KG 거울: LakatosTree_MeasurementSovereignty_20260703 / ag6_value_integrity_fsck
"""
import os
import sys

os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

_ID = "MEASUREMENT_REFUTED_BUT_STANDING"


def value_integrity_gaps() -> int:
    gaps = 0
    from server.contexts.audit import fsck as F
    # gap①: 반증-서있음 노드 플래그.
    flagged = _ID in {f.check_id for f in F.fsck_node({"replay_status": "mismatch", "verdict": "progressive"})}
    if not flagged:
        gaps += 1
    # gap②: WARN(비차단) ∧ dead-σ(not_attempted 무발화).
    warn_ok = F._SEVERITY.get(_ID) == F.WARN
    dead_sigma = _ID not in {f.check_id for f in F.fsck_node({"replay_status": "not_attempted", "verdict": "progressive"})}
    if not (warn_ok and dead_sigma):
        gaps += 1
    return gaps


if __name__ == "__main__":
    print(f"metric={value_integrity_gaps()}")
    sys.exit(0)
