"""정본 prom (Occam 통합 2026-06-21): force_of — "영수증 vs 자기보고"의 단일 3치 술어.

6라운드 동안 metrics·CANONICAL floor·credibility 가 이 술어를 각자 재유도하다 drift 했다. 이 테스트는
(1) force_of 진리표를 고정하고 (2) force_of_row 가 옛 metrics inconclusive 술어와 *비트동일*임을 증명한다
(behavior-preserving 머지의 golden test).
# KG: span_lakatotree_verdict_registry
"""
from lakatos.verdicts import PROGRESS_VERDICTS, force_of, force_of_row, normalize_source


def test_force_of_truth_table():
    for src in ("scripted", "engine", "reproducible", "human"):
        assert force_of("progressive", src) == "COUNTS"
        assert force_of("proof", src) == "COUNTS"            # forceful source → COUNTS (verdict 무관)
    assert force_of("progressive", None) == "INCONCLUSIVE"   # 진보 + 키 있고 빈 source = 영수증 미도래
    assert force_of("CANONICAL", "") == "INCONCLUSIVE"
    assert force_of("progressive") == "SELF_REPORT"          # 키 부재(레거시/픽스처) → 신뢰(집계 보존)
    assert force_of("proof", None) == "SELF_REPORT"          # 비진보 + 빈 source = inconclusive 아님
    assert force_of("CANONICAL", "admin") == "SELF_REPORT"   # admin = 구조, forceful 아님


def test_normalize_source_absorbs_aliases_and_prose():
    """Occam step 6: normalize_source 가 별칭/prose 를 정본 토큰으로 흡수(force_of 단일 정규화 chokepoint)."""
    assert normalize_source("dogfood") == "scripted"                 # dogfood judge() = 실 pytest 영수증
    assert normalize_source("cloc-measured + adversarial 6-agent") == "reproducible"   # 결정론 실행 측정
    assert normalize_source("MEASURED: pytest 168 passed; grep dispatch=0") == "reproducible"   # 라이브 실행 영수증
    assert normalize_source("engine judge() over bhgman pytest receipt 93/93 PASSED") == "engine"  # prose 선두토큰
    assert normalize_source("scripted") == "scripted"                # 정확 일치
    assert normalize_source("kg_bootstrap") == "kg_bootstrap"        # 구조(forceful 아님)
    assert normalize_source("admin root (conjecture established)") == "admin"


def test_force_of_over_live_vocabulary_golden():
    """통제 어휘 lock — 실 KG 에서 관측된 모든 verdict_source 형태가 sane 하게 분류되는지(유령/오분류 차단).
    실 영수증(dogfood/engine-prose/cloc)은 COUNTS, 무영수증 마커는 INCONCLUSIVE, 구조/conjecture 는 SELF_REPORT."""
    counts = ["scripted", "engine", "reproducible", "human", "dogfood",
              "engine judge() over bhgman pytest receipt 93/93 PASSED (executed-not-asserted)",
              "cloc-measured + adversarial 6-agent dissection workflow w3r9m5kny (deterministic LOC)",
              "MEASURED: len(PREDICATE_REGISTRY)==4; pytest 38 passed; ruff clean; executed-not-asserted"]
    for s in counts:
        assert force_of("progressive", s) == "COUNTS", s
    for s in ("pre_receipt", "prehistory"):
        assert force_of("CANONICAL", s) == "INCONCLUSIVE", s
    for s in ("admin", "kg_bootstrap", "conjecture", "admin root (conjecture established, not scored)"):
        assert force_of("CANONICAL", s) == "SELF_REPORT", s


def test_explicit_pre_receipt_marker_is_inconclusive_not_self_report():
    """Occam step 5: 명시적 무영수증 마커(pre_receipt/prehistory)는 INCONCLUSIVE — NULL 진보어휘와 동일.
    fabrication 아님(영수증 부재를 단언). force 아니므로 COUNTS 절대 아님."""
    for src in ("pre_receipt", "prehistory"):
        assert force_of("progressive", src) == "INCONCLUSIVE"
        assert force_of("CANONICAL", src) == "INCONCLUSIVE"
        assert force_of("proof", src) == "INCONCLUSIVE"      # 비진보 구조어휘라도 명시 마커는 inconclusive
    assert force_of_row({"verdict": "CANONICAL", "verdict_source": "pre_receipt"}) == "INCONCLUSIVE"


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
