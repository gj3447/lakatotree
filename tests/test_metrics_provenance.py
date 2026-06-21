"""prom-honesty (R2→정본 결정 2026-06-21): metrics 읽기경로의 verdict_source 미채점 진보 = inconclusive.

쓰기게이트(9b85cf8)는 *앞으로*의 self-report 진보 주입을 막았지만, 읽기/집계 경로·기존 KG 데이터는
NULL-source 진보를 그대로 진보로 셌다(영수증 없는 green — 쓰기게이트의 대칭 누락, R2 fresh-eyes 발견).
이론(ooptdd 3치 LTL3): verdict_source 없는 진보 = *inconclusive*(pass도 fail도 아님) → DEFAULT 로 positive
진보 집계서 제외(비파괴·가역), 재검증으로 해소. cfg.provenance_lenient 로 옛 동작 opt-out.
# KG: span_lakatotree_S1_laudan_layer
"""
from lakatos.quant.metrics import tree_metrics

_ROOT = {"tag": "root", "verdict": "proof", "metric_value": 10.0, "metric_scope": "s", "pred_baseline": 10.0}


def _self_report_canonical():
    """verdict_source 키가 *있고* None = 실 KG self-report(노드 경로 주입/구데이터) = inconclusive."""
    return {"tag": "c", "parent": "root", "verdict": "CANONICAL", "verdict_source": None,
            "metric_value": 1.0, "metric_scope": "s", "pred_baseline": 10.0, "pred_direction": "lower"}


def test_inconclusive_progress_excluded_from_positive_by_default():
    """DEFAULT(3치): verdict_source 없는 진보는 inconclusive → canonical anchor 못 되고 진보 집계서 제외,
    provenance + alert 로 surface. (영수증 없는 green 을 *조용히* 도 *명시적으로*도 진보로 안 센다.)"""
    m = tree_metrics([_ROOT, _self_report_canonical()], [])
    assert m["canonical"] is None                                  # inconclusive ≠ verified canonical
    assert m["provenance"]["mode"] == "inconclusive-excluded"
    assert m["provenance"]["count"] == 1 and "c" in m["provenance"]["inconclusive_progress"]
    assert any("inconclusive" in a for a in m["alerts"])


def test_lenient_mode_opts_out_to_legacy_counting():
    """cfg.provenance_lenient=True = append-only 존중 opt-out: 옛 동작(집계 포함)으로 — 단 alert 로 경고."""
    m = tree_metrics([_ROOT, _self_report_canonical()], [], cfg={"provenance_lenient": True})
    assert m["canonical"] == "c"                                   # 옛 동작 보존(가역)
    assert m["provenance"]["mode"] == "lenient-counted"
    assert any("부풀림" in a for a in m["alerts"])


def test_legacy_nodes_without_verdict_source_key_unaffected():
    """verdict_source *키 부재*(레거시/테스트 픽스처)는 신뢰 — inconclusive 아님, 집계 정상(타 트리 비트동일)."""
    legit = {"tag": "c", "parent": "root", "verdict": "CANONICAL",
             "metric_value": 1.0, "metric_scope": "s", "pred_baseline": 10.0}
    m = tree_metrics([_ROOT, legit], [])
    assert m["provenance"]["count"] == 0
    assert m["canonical"] == "c"
