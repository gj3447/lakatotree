"""엔진이 *선언된* 도메인 온톨로지를 노드 등록 시점에 강제(opt-in, fail-closed 422).
미선언 트리 = 무영향(backward-compat). entity_type = node.algorithm, attrs = 노드 필드.
# KG: span_lakatotree_ontology_gate
"""
from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import NodeIn, PredictionIn
from server.contexts.tree.service import TreeService

_ONTO = json.dumps({
    "entities": {
        "icp": {"required": ["metric_name"],
                "constraints": {"metric_value": {"type": "number", "min": 0.0}}},
    },
    "closed_world": True,
})


def _svc(*, ontology: str, captured: list):
    def kg(query, **p):
        if "RETURN t.title AS title" in query:
            return [{"title": "T", "hard_core": [], "frontier_rule": "", "doc": "",
                     "coverage_backlog": [], "coverage_statement": "", "ontology": ontology}]
        if "ORDER BY tag" in query:
            return []
        return []

    def kg_tx(ops):
        captured.append(ops)
        return [[{"t": 1}] for _ in ops]

    return TreeService(kg=kg, kg_tx=kg_tx, hist=lambda *a: None, pg=lambda: None)


def test_conforming_node_passes():
    cap: list = []
    out = _svc(ontology=_ONTO, captured=cap).add_node(
        "T", NodeIn(tag="n", algorithm="icp", metric_name="seam", metric_value=0.9))
    assert out["ok"] is True and cap


def test_undeclared_entity_is_422_closed_world():
    with pytest.raises(HTTPException) as e:
        _svc(ontology=_ONTO, captured=[]).add_node(
            "T", NodeIn(tag="n", algorithm="fabricated_method", metric_name="x"))
    assert e.value.status_code == 422 and "온톨로지" in str(e.value.detail)


def test_missing_required_attr_is_422():
    with pytest.raises(HTTPException) as e:
        _svc(ontology=_ONTO, captured=[]).add_node(
            "T", NodeIn(tag="n", algorithm="icp"))   # metric_name 누락
    assert e.value.status_code == 422


def test_bad_value_min_is_422():
    with pytest.raises(HTTPException) as e:
        _svc(ontology=_ONTO, captured=[]).add_node(
            "T", NodeIn(tag="n", algorithm="icp", metric_name="x", metric_value=-5.0))
    assert e.value.status_code == 422


def test_structural_node_no_algorithm_exempt():
    cap: list = []
    out = _svc(ontology=_ONTO, captured=cap).add_node("T", NodeIn(tag="root", algorithm=""))
    assert out["ok"] is True   # algorithm 없는 구조노드는 엔티티-온톨로지 면제


def test_no_ontology_no_enforcement_backward_compat():
    cap: list = []
    out = _svc(ontology="", captured=cap).add_node(
        "T", NodeIn(tag="n", algorithm="anything_goes", metric_name="x"))
    assert out["ok"] is True   # 미선언 트리 = 강제 없음(기존 트리 무영향)


# ── 확장 B: require_entity strict — 구조노드도 entity 필수 ─────────────────────
def test_require_entity_rejects_structural_node():
    onto = json.dumps({"entities": {"icp": {}}, "require_entity": True})
    with pytest.raises(HTTPException) as e:
        _svc(ontology=onto, captured=[]).add_node("T", NodeIn(tag="root", algorithm=""))
    assert e.value.status_code == 422 and "require_entity" in str(e.value.detail)


# ── 확장 A: prediction(metric) 어휘 강제 — register_prediction 시점 ────────────
_MONTO = json.dumps({"metrics": {"seam_mm": {"direction": "lower"}}, "closed_world_metrics": True})


def _judge(ontology: str):
    def kg(query, **k):
        if "RETURN t.ontology AS ontology" in query:
            return [{"ontology": ontology}]
        if "SET e.pred_metric" in query:
            return [{"tag": "n"}]
        return []
    return JudgementService(kg=kg, kg_tx=lambda ops: [[{"ok": 1}] for _ in ops],
                            hist=lambda *a: None,
                            foundation=lambda *a, **k: None,
                            reproducible_for_node=lambda *a, **k: None)


def test_prediction_undeclared_metric_is_422():
    with pytest.raises(HTTPException) as e:
        _judge(_MONTO).register_prediction("T", "n", PredictionIn(metric_name="fabricated_metric", baseline_value=1.0))
    assert e.value.status_code == 422 and "metric 온톨로지" in str(e.value.detail)


def test_prediction_wrong_direction_is_422():
    with pytest.raises(HTTPException) as e:
        _judge(_MONTO).register_prediction("T", "n", PredictionIn(metric_name="seam_mm", direction="higher", baseline_value=1.0))
    assert e.value.status_code == 422


def test_prediction_conforming_metric_passes():
    out = _judge(_MONTO).register_prediction("T", "n", PredictionIn(metric_name="seam_mm", direction="lower", baseline_value=1.0))
    assert out["ok"] is True


def test_prediction_no_ontology_no_enforcement():
    out = _judge("").register_prediction("T", "n", PredictionIn(metric_name="anything", baseline_value=1.0))
    assert out["ok"] is True   # 미선언 트리 = 강제 없음
