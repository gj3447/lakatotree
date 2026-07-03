#!/usr/bin/env python3
"""FE5 채점기 — auth 자세 미관측 gap 수 (측정주권 2026-07-03).

측정(self-report 아님 — 실코드 구동): 두 gap 을 실제로 두드린다.
  gap① 자세 미분류: classify 가 3값 사다리(token_required>irreversible_attested>open)를 안 내면
       무인증 open-write 가 여전히 관측 불가.
  gap② open 무음: open 자세인데 open_posture_warning 이 None 이면 무인증 부팅이 조용히 지나간다
       (경고=관측화의 실이빨). token_required 는 None 이어야(과잉경보 아님).
metric = 열린 gap 수(봉합 후 0). 분류/경고를 떼면 값이 오른다(revert-민감). exit 0.
# KG 거울: LakatosTree_MeasurementSovereignty_20260703 / fe5_auth_posture
"""
import os
import sys

os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)


def auth_posture_gaps() -> int:
    gaps = 0
    try:
        from server.auth_posture import classify, open_posture_warning
        # gap①: 3값 사다리 분류.
        ladder = (classify(True) == "token_required"
                  and classify(False, irreversible_attested=True) == "irreversible_attested"
                  and classify(False) == "open")
        if not ladder:
            gaps += 1
        # gap②: open 은 loud WARN, 그 외는 무경보.
        warns = (open_posture_warning("open") is not None
                 and open_posture_warning("token_required") is None
                 and open_posture_warning("irreversible_attested") is None)
        if not warns:
            gaps += 1
    except ImportError:
        gaps += 2   # 관측화 seam 미착륙
    return gaps


if __name__ == "__main__":
    print(f"metric={auth_posture_gaps()}")
    sys.exit(0)
