#!/usr/bin/env python3
"""AG3/R-SOV V1 채점기 — 값소유(value-ownership) 미봉합 gap 수 (측정주권 2026-07-03).

측정(self-report 아님 — 실코드 구동): 두 gap 을 실제로 두드린다.
  gap① 등급 미봉인: measurement_grade 가 receipt_sha 를 *안 가르면* 서버-재유도값과 client-운반값이
       같은 영수증을 든다(테제의 '운반만' 구멍). receipt_content_sha 를 grade 만 바꿔 두 번 계산해 확인.
  gap② 값 미소유: 서버 replay 가 verified 인데 resolve_measurement 이 v.regenerated 를 SSOT 로
       치환하지 않으면(client 값 유지) 값을 소유하지 못한 것.
metric = 열린 gap 수(봉합 후 0). 등급 봉인/치환 코드를 떼면 값이 오른다(revert-민감). exit 0.
# KG 거울: LakatosTree_MeasurementSovereignty_20260703 / ag3_value_ownership
"""
import os
import sys

os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)


def value_ownership_gaps() -> int:
    gaps = 0
    # gap①: 등급이 봉인 sha 를 가르나(진짜검증≠위조).
    from lakatos.verdicts import receipt_content_sha
    base = dict(tree="T", tag="n", target_id=None, verdict="progressive", verdict_source="scripted",
                metric_name="m", metric_value=0.5, novel_confirmed=True, lakatos_status="ok",
                judged_at="2026-07-03T00:00:00Z", judge_script_sha="x", prev_receipt_sha=None)
    a = receipt_content_sha(dict(base, measurement_grade="server_regenerated"))
    b = receipt_content_sha(dict(base, measurement_grade="client_asserted"))
    if a == b:
        gaps += 1   # 등급이 receipt_sha 에 안 들어감 — 위조=진짜검증 동일 영수증
    # gap②: verified replay 가 값을 소유(치환)하나.
    try:
        from server.contexts.tree.judgement_policy import resolve_measurement
        from lakatos.io.replay import ProducerReplayVerdict
        vv = ProducerReplayVerdict(verified=True, regenerated=0.777, recorded=0.123, reason="x")
        eff, grade, _status = resolve_measurement(vv, 0.123)
        if not (eff == 0.777 and grade == "server_regenerated"):
            gaps += 1   # 서버가 재유도해도 client 값 유지 — 소유 실패
    except ImportError:
        gaps += 1       # 치환 seam 미착륙 — 소유 불가
    return gaps


if __name__ == "__main__":
    print(f"metric={value_ownership_gaps()}")
    sys.exit(0)
