"""엔진이 *선언된* 도메인 온톨로지를 노드 등록 시점에 강제(opt-in, fail-closed 422).
미선언 트리 = 무영향(backward-compat). entity_type = node.algorithm, attrs = 노드 필드.
# KG: span_lakatotree_ontology_gate
"""
from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from server.contexts.tree.schemas import NodeIn
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
