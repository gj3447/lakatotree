"""정본 prom (Occam 통합 2026-06-21): force_of — "영수증 vs 자기보고"의 단일 3치 술어.

6라운드 동안 metrics·CANONICAL floor·credibility 가 이 술어를 각자 재유도하다 drift 했다. 이 테스트는
(1) force_of 진리표를 고정하고 (2) force_of_row 가 옛 metrics inconclusive 술어와 *비트동일*임을 증명한다
(behavior-preserving 머지의 golden test).
# KG: span_lakatotree_verdict_registry
"""
from lakatos.verdicts import PROGRESS_VERDICTS, force_of, force_of_row


def test_force_of_truth_table():
    for src in ("scripted", "engine", "reproducible", "human"):
        assert force_of("progressive", src) == "COUNTS"
        assert force_of("proof", src) == "COUNTS"            # forceful source → COUNTS (verdict 무관)
    assert force_of("progressive", None) == "INCONCLUSIVE"   # 진보 + 키 있고 빈 source = 영수증 미도래
    assert force_of("CANONICAL", "") == "INCONCLUSIVE"
    assert force_of("progressive") == "SELF_REPORT"          # 키 부재(레거시/픽스처) → 신뢰(집계 보존)
    assert force_of("proof", None) == "SELF_REPORT"          # 비진보 + 빈 source = inconclusive 아님
    assert force_of("CANONICAL", "admin") == "SELF_REPORT"   # admin = 구조, forceful 아님


def test_force_of_row_distinguishes_absent_from_none():
    assert force_of_row({"verdict": "CANONICAL"}) == "SELF_REPORT"                       # 키 부재
    assert force_of_row({"verdict": "CANONICAL", "verdict_source": None}) == "INCONCLUSIVE"   # 키 None
    assert force_of_row({"verdict": "CANONICAL", "verdict_source": "scripted"}) == "COUNTS"


def test_force_of_row_is_bit_identical_to_old_metrics_predicate():
    """golden: force_of_row==INCONCLUSIVE  iff  (진보어휘 AND verdict_source 키 존재 AND falsy) = 옛 술어."""
    for verdict in list(PROGRESS_VERDICTS) + ["proof", "rejected", "equivalent"]:
        for has_key, src in [(False, None), (True, None), (True, ""), (True, "scripted"),
                             (True, "engine"), (True, "admin")]:
            row = {"verdict": verdict}
            if has_key:
                row["verdict_source"] = src
            old = (verdict in PROGRESS_VERDICTS and has_key and not src)
            assert (force_of_row(row) == "INCONCLUSIVE") == old, (verdict, has_key, src)
