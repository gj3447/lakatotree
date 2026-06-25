"""도메인 온톨로지 게이트 — 엔진이 *선언된* 온톨로지를 강제(fail-closed).

지금까지 FoundationMap 의 domain-ontology 요건은 '선언'만 받았다(자유텍스트 체크리스트, engine.py).
이 모듈은 트리가 선언한 온톨로지(엔티티 타입 + 필수 속성 + 값 제약 + closed-world)에 노드가 conform
하는지 검사해 세 가지 환각을 RED 로 만든다:
  ① 미선언 엔티티(closed-world drift)  ② 필수 속성 누락  ③ 값 위반(enum/type/min/max).

의미론은 JSON Schema(Draft 2020-12) subset — ooptdd/domain/ontology.py 와 *동일 어휘*(required /
constraints{enum|type|min|max} / additional_properties / closed_world). ooptdd 가 stdlib-only 로
재구현한 철학을 따라 여기서도 cross-repo 의존 없이 native 재구현(엔진 self-contained 유지).

opt-in: 트리가 온톨로지를 선언하지 않으면 강제 없음(기존 트리 무영향). from_spec(None)→None.
# KG: span_lakatotree_ontology_gate
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


def _num(v):
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _type_ok(v, t: str) -> bool:
    if t == "number":
        return _num(v) is not None
    if t == "string":
        return isinstance(v, str)
    if t == "boolean":
        return isinstance(v, bool)
    return True   # 미지 타입은 통과(과잉형식화 금지)


@dataclass(frozen=True)
class EntityType:
    """온톨로지의 엔티티 1종 — 필수 속성 + 값 제약. (ooptdd EventType 와 동일 모델)"""
    name: str
    required: tuple[str, ...] = ()
    constraints: dict = field(default_factory=dict)   # attr -> {enum|type|min|max}

    def violations(self, attrs: dict) -> list[str]:
        out: list[str] = []
        for key in self.required:
            if attrs.get(key) in (None, ""):
                out.append(f"필수 속성 누락 '{key}'")
        for attr, rule in self.constraints.items():
            if attr not in attrs or attrs[attr] in (None, ""):
                continue   # presence 는 required 가 관장 — 제약은 존재할 때만 bind
            v = attrs[attr]
            if "enum" in rule and v not in rule["enum"]:
                out.append(f"'{attr}'={v!r} ∉ enum {rule['enum']}")
            if "type" in rule and not _type_ok(v, rule["type"]):
                out.append(f"'{attr}'={v!r} 타입≠{rule['type']}")
            n = _num(v)
            if "min" in rule and n is not None and n < rule["min"]:
                out.append(f"'{attr}'={v} < min {rule['min']}")
            if "max" in rule and n is not None and n > rule["max"]:
                out.append(f"'{attr}'={v} > max {rule['max']}")
        return out


@dataclass(frozen=True)
class DomainOntology:
    entities: dict           # name -> EntityType
    closed_world: bool = False

    @classmethod
    def from_spec(cls, spec) -> "DomainOntology | None":
        """선언 dict → DomainOntology. 미선언/빈/무효 → None(=강제 없음, opt-in)."""
        if not isinstance(spec, dict) or not spec.get("entities"):
            return None
        ents: dict = {}
        for name, e in spec["entities"].items():
            e = e or {}
            ents[name] = EntityType(
                name=name,
                required=tuple(e.get("required", [])),
                constraints=dict(e.get("constraints", {})),
            )
        return cls(entities=ents, closed_world=bool(spec.get("closed_world", False)))

    def violations(self, entity_type: str, attrs: dict) -> list[str]:
        """엔티티 1개를 온톨로지에 대조. 미선언+closed_world=drift; 선언됐으면 필수/값 검사."""
        et = self.entities.get(entity_type)
        if et is None:
            return [f"미선언 엔티티 '{entity_type}' (closed-world drift)"] if self.closed_world else []
        return et.violations(attrs)
