#!/usr/bin/env python3
"""AG5-IDENT 채점기 — 비가역 verb 서명강제·verb 봉인 미착륙 gap 수 (측정주권 2026-07-03).

측정(self-report 아님 — 실코드 구동): 두 gap 을 실제로 두드린다.
  gap① 서명강제 부재: set_verdict_canonical 이 anchored tier 에서 GATE_WRITE_CERT 로 무장 안 됐으면
       비가역 승격에 서명 강제가 없다(무-attestor 트리는 여전히 open — 이건 정상 dead-σ).
  gap② verb 미봉인: write_cert.COMMAND_FIELDS 에 verb 가 없으면 submit 용 cert 를 canonical 에 재생
       (sign-X-execute-Y)할 수 있다 — cert 가 verb 에 안 묶임.
metric = 열린 gap 수(봉합 후 0). 게이트/verb 를 떼면 값이 오른다(revert-민감). exit 0.
# KG 거울: LakatosTree_MeasurementSovereignty_20260703 / ag5b_verb_signed_irreversible
"""
import os
import sys

os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)


def unsigned_irreversible_gaps() -> int:
    gaps = 0
    from lakatos import assurance
    from lakatos import write_cert as W
    # gap①: 비가역 승격(set_verdict_canonical)이 anchored 에서 서명강제.
    if assurance.GATE_WRITE_CERT not in assurance.gates_for("set_verdict_canonical", "anchored"):
        gaps += 1
    # gap②: cert 가 verb 에 묶인다(sign-X-execute-Y 봉인).
    if "verb" not in W.COMMAND_FIELDS:
        gaps += 1
    return gaps


if __name__ == "__main__":
    print(f"metric={unsigned_irreversible_gaps()}")
    sys.exit(0)
