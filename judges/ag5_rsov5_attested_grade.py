#!/usr/bin/env python3
"""AG5/R-SOV V3 채점기 — attested 측정등급 사다리 미봉합 gap 수 (측정주권 2026-07-03).

측정(self-report 아님 — 실코드 구동): 두 gap 을 실제로 두드린다.
  gap① attested 미생성: 서명(attested=True)인데 resolve_measurement 이 grade='attested' 를 안 내면
       신원이 measurement_grade 로 안 올라온다(익명 client float 와 뭉갬).
  gap② 사다리 역전: server_regenerated(값소유)가 attested 를 안 이기면 provenance 순서가 깨진다
       (재유도값이 서명보다 강한 값 주장이어야).
metric = 열린 gap 수(봉합 후 0). attested 분기/사다리를 떼면 값이 오른다(revert-민감). exit 0.
# KG 거울: LakatosTree_MeasurementSovereignty_20260703 / ag5_attested_grade
"""
import os
import sys

os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)


def attested_grade_gaps() -> int:
    gaps = 0
    try:
        from server.contexts.tree.judgement_policy import resolve_measurement
        from lakatos.io.replay import ProducerReplayVerdict
        # gap①: 서명 → attested (무서명 → client_asserted).
        _v, g_signed, _s = resolve_measurement(None, 0.5, attested=True)
        _v, g_unsigned, _s = resolve_measurement(None, 0.5, attested=False)
        if not (g_signed == "attested" and g_unsigned == "client_asserted"):
            gaps += 1
        # gap②: server_regenerated 가 attested 를 이긴다(재유도 서명값도 소유로 치환·grade).
        ok = ProducerReplayVerdict(verified=True, regenerated=0.7, recorded=0.7, reason="x")
        val, g_top, _s = resolve_measurement(ok, 0.5, attested=True)
        if not (g_top == "server_regenerated" and val == 0.7):
            gaps += 1
    except (ImportError, TypeError):
        gaps += 2   # seam 미착륙(attested 파라미터 부재 등)
    return gaps


if __name__ == "__main__":
    print(f"metric={attested_grade_gaps()}")
    sys.exit(0)
