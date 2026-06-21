"""prom-honesty (적대 재검증 R2 2026-06-21): metrics 읽기경로의 verdict_source 미채점 진보.

쓰기게이트(9b85cf8)는 *앞으로*의 self-report 진보 주입을 막았지만, 읽기/집계 경로와 기존 KG 데이터는
NULL-source 진보를 그대로 진보로 셌다(영수증 없는 green, 쓰기게이트의 대칭 누락 — R2 fresh-eyes 발견).
tree_metrics 가 이를 *항상 surface*(provenance + alert) 하고, cfg.provenance_strict 로 집계 제외.
# KG: span_lakatotree_S1_laudan_layer
"""
from lakatos.quant.metrics import tree_metrics

_ROOT = {"tag": "root", "verdict": "proof", "metric_value": 10.0, "metric_scope": "s", "pred_baseline": 10.0}


def _self_report_canonical():
    """verdict_source 키가 *있고* None = 실 KG self-report(노드 경로 주입/구데이터)."""
    return {"tag": "c", "parent": "root", "verdict": "CANONICAL", "verdict_source": None,
            "metric_value": 1.0, "metric_scope": "s", "pred_baseline": 10.0, "pred_direction": "lower"}


def test_unprovenanced_progress_is_surfaced_not_silent():
    """기본(비-strict): self-report 진보는 여전히 집계되되(비트동일) provenance + alert 로 *드러난다*."""
    m = tree_metrics([_ROOT, _self_report_canonical()], [])
    assert m["provenance"]["count"] == 1
    assert "c" in m["provenance"]["unprovenanced_progress"]
    assert any("영수증 없는 green" in a for a in m["alerts"])
    assert m["canonical"] == "c"   # 기본 동작 보존 — 단 더는 *조용히* 부풀리지 않는다


def test_strict_mode_excludes_unprovenanced_progress():
    """cfg.provenance_strict=True 면 self-report 진보를 집계에서 제외 — canonical anchor 가 되지 못한다."""
    m = tree_metrics([_ROOT, _self_report_canonical()], [], cfg={"provenance_strict": True})
    assert m["canonical"] is None
    assert m["provenance"]["strict"] is True
    assert any("strict 모드로 집계 제외" in a for a in m["alerts"])


def test_legacy_nodes_without_verdict_source_key_unaffected():
    """verdict_source *키 부재*(레거시/테스트 픽스처)는 신뢰 — 집계·provenance 영향 없음(타 트리 비트동일)."""
    legit = {"tag": "c", "parent": "root", "verdict": "CANONICAL",
             "metric_value": 1.0, "metric_scope": "s", "pred_baseline": 10.0}
    m = tree_metrics([_ROOT, legit], [])
    assert m["provenance"]["count"] == 0
    assert m["canonical"] == "c"
