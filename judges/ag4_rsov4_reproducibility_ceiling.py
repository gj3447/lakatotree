#!/usr/bin/env python3
"""AG4/R-SOV V2 채점기 — 재현성 천장 미봉합 gap 수 (측정주권 2026-07-03).

측정(self-report 아님 — 실코드 구동): 두 gap 을 실제로 두드린다.
  gap① 게이트 부재: GATE_REPRODUCIBILITY_CEILING 이 submit_test_result×anchored 에 무장 안 됐으면
       재현성 구조반증 노드를 천장할 정책 훅이 없다(assurance.gates_for 로 확인).
  gap② 강등 미발화: apply_verdict_demotes 가 (anchored 게이트 ∧ reproducible is False ∧ progressive)를
       partial(reproducibility_refuted)로 천장하지 않으면, 재현불가 측정이 progressive 로 남는다.
       ★불가 None 은 여전히 progressive 여야(부재≠반증) — 이 dead-σ 규율도 함께 검사.
metric = 열린 gap 수(봉합 후 0). 게이트/강등을 떼면 값이 오른다(revert-민감). exit 0.
# KG 거울: LakatosTree_MeasurementSovereignty_20260703 / ag4_reproducibility_ceiling
"""
import os
import sys

os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)


def reproducibility_ceiling_gaps() -> int:
    gaps = 0
    from lakatos import assurance
    g = getattr(assurance, "GATE_REPRODUCIBILITY_CEILING", None)
    # gap①: anchored 게이트에 재현성 천장 비트가 무장됐나(receipted/notebook 엔 없어야 = 단조).
    if not (g and g in assurance.gates_for("submit_test_result", "anchored")
            and g not in assurance.gates_for("submit_test_result", "receipted")):
        gaps += 1
    # gap②: 강등이 False 만 천장하고 None 은 통과(dead-σ)하나.
    try:
        from server.contexts.tree.judgement_policy import apply_verdict_demotes

        def _v(reproducible):
            return apply_verdict_demotes("progressive", "ok", hc_derived=None, require_novel_anchor=False,
                                         novel=False, cross_metric_novel=False, novel_server_anchored=False,
                                         reproducible=reproducible, reproducibility_ceiling=True).verdict
        refuted_capped = _v(False) == "partial"
        none_preserved = _v(None) == "progressive"        # 불가≠반증
        true_preserved = _v(True) == "progressive"
        if not (refuted_capped and none_preserved and true_preserved):
            gaps += 1
    except ImportError:
        gaps += 1
    return gaps


if __name__ == "__main__":
    print(f"metric={reproducibility_ceiling_gaps()}")
    sys.exit(0)
