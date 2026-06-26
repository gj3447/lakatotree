"""native 도메인 온톨로지 게이트 순수 로직 — required / enum / type / min-max / closed-world drift.
# KG: span_lakatotree_ontology_gate
"""
from __future__ import annotations

from lakatos.ontology import DomainOntology, EntityType


def test_from_spec_optin_none_when_no_ontology():
    assert DomainOntology.from_spec(None) is None
    assert DomainOntology.from_spec({}) is None
    assert DomainOntology.from_spec({"closed_world": True}) is None   # entities 없으면 강제 없음


_SPEC = {
    "entities": {
        "icp": {"required": ["metric_name", "metric_value"],
                "constraints": {"metric_value": {"type": "number", "min": 0.0},
                                "metric_scope": {"enum": ["registration", "measurement"]}}},
        "problem": {},
    },
    "closed_world": True,
}


def test_conforming_entity_has_no_violations():
    o = DomainOntology.from_spec(_SPEC)
    assert o.violations("icp", {"metric_name": "seam", "metric_value": 0.9, "metric_scope": "registration"}) == []
    assert o.violations("problem", {}) == []


def test_missing_required_is_violation():
    o = DomainOntology.from_spec(_SPEC)
    v = o.violations("icp", {"metric_name": "seam"})   # metric_value 누락
    assert any("metric_value" in x for x in v)


def test_bad_value_enum_type_range():
    o = DomainOntology.from_spec(_SPEC)
    assert any("enum" in x for x in o.violations("icp", {"metric_name": "s", "metric_value": 1, "metric_scope": "bogus"}))
    assert any("min" in x for x in o.violations("icp", {"metric_name": "s", "metric_value": -3}))
    assert any("타입" in x for x in o.violations("icp", {"metric_name": "s", "metric_value": "lots"}))


def test_closed_world_unknown_entity_is_drift():
    o = DomainOntology.from_spec(_SPEC)
    assert any("drift" in x for x in o.violations("fabricated_method", {}))


def test_open_world_unknown_entity_allowed():
    o = DomainOntology.from_spec({**_SPEC, "closed_world": False})
    assert o.violations("anything_goes", {}) == []


def test_constraint_only_binds_when_present():
    o = DomainOntology.from_spec({"entities": {"x": {"constraints": {"k": {"type": "number"}}}}})
    assert o.violations("x", {}) == []   # k 없음 → 제약 미적용(required 아님)


# ── 확장 A: metric(측정) 어휘 강제 — prediction 시점 ──────────────────────────
_MSPEC = {"metrics": {"seam_mm": {"direction": "lower"}}, "closed_world_metrics": True}


def test_metrics_only_ontology_is_valid():
    assert DomainOntology.from_spec({"metrics": {"m": {}}}) is not None


def test_metric_drift_closed_world():
    o = DomainOntology.from_spec(_MSPEC)
    assert any("drift" in x for x in o.metric_violations("fabricated_metric", "lower"))


def test_metric_direction_mismatch():
    o = DomainOntology.from_spec(_MSPEC)
    assert any("direction" in x for x in o.metric_violations("seam_mm", "higher"))
    assert o.metric_violations("seam_mm", "lower") == []


def test_metric_open_world_allows_undeclared():
    o = DomainOntology.from_spec({"metrics": {"x": {}}})   # closed_world_metrics=false
    assert o.metric_violations("anything_metric", "lower") == []


def test_empty_metric_name_no_violation():
    assert DomainOntology.from_spec(_MSPEC).metric_violations("", None) == []


# ── 확장 B: require_entity strict — 미선언 entity 는 open-world 라도 drift ─────
def test_require_entity_rejects_undeclared_even_open_world():
    o = DomainOntology.from_spec({"entities": {"icp": {}}, "require_entity": True})  # closed_world=false
    assert any("drift" in x for x in o.violations("undeclared", {}))


# ── from_json 파서(opt-in) ────────────────────────────────────────────────────
def test_from_json_string_dict_none():
    assert DomainOntology.from_json("") is None
    assert DomainOntology.from_json("not json{") is None
    assert DomainOntology.from_json(None) is None
    o = DomainOntology.from_json('{"metrics":{"seam_mm":{"direction":"lower"}}}')
    assert o is not None and o.metric_violations("seam_mm", "lower") == []
