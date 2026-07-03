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

import json
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
            # fail-closed: min/max 가 선언됐는데 값이 (존재하나) 비-숫자면 범위검증 불가 → 위반.
            #   (type:number 가 함께 선언됐으면 그쪽이 이미 잡으므로 중복 방출 회피.)
            if ("min" in rule or "max" in rule) and "type" not in rule and n is None:
                out.append(f"'{attr}'={v!r} 비-숫자 — 수치 범위(min/max) 검증 불가")
            if "min" in rule and n is not None and n < rule["min"]:
                out.append(f"'{attr}'={v} < min {rule['min']}")
            if "max" in rule and n is not None and n > rule["max"]:
                out.append(f"'{attr}'={v} > max {rule['max']}")
        return out


@dataclass(frozen=True)
class DomainOntology:
    entities: dict                                  # name -> EntityType (노드 entity 어휘)
    closed_world: bool = False                      # 미선언 entity = drift
    metrics: dict = field(default_factory=dict)     # metric_name -> {direction?}  (측정 어휘)
    closed_world_metrics: bool = False              # 미선언 metric = drift (prediction 강제)
    require_entity: bool = False                    # strict: 모든 노드가 선언 entity 필수(구조노드 면제 X)

    @classmethod
    def from_spec(cls, spec) -> "DomainOntology | None":
        """선언 dict → DomainOntology. entities/metrics 둘 다 없으면 None(=강제 없음, opt-in)."""
        if not isinstance(spec, dict) or not (spec.get("entities") or spec.get("metrics")):
            return None
        ents: dict = {}
        for name, e in (spec.get("entities") or {}).items():
            e = e or {}
            ents[name] = EntityType(
                name=name,
                required=tuple(e.get("required", [])),
                constraints=dict(e.get("constraints", {})),
            )
        return cls(
            entities=ents,
            closed_world=bool(spec.get("closed_world", False)),
            metrics=dict(spec.get("metrics", {})),
            closed_world_metrics=bool(spec.get("closed_world_metrics", False)),
            require_entity=bool(spec.get("require_entity", False)),
        )

    @classmethod
    def from_json(cls, raw) -> "DomainOntology | None":
        """JSON 문자열(또는 dict/None) → DomainOntology. 무효/빈 → None(opt-in)."""
        if not raw:
            return None
        try:
            spec = json.loads(raw) if isinstance(raw, str) else raw
        except (ValueError, TypeError):
            return None
        return cls.from_spec(spec)

    def violations(self, entity_type: str, attrs: dict) -> list[str]:
        """엔티티 1개를 온톨로지에 대조. 미선언+(closed_world|require_entity)=drift; 선언됐으면 필수/값 검사."""
        et = self.entities.get(entity_type)
        if et is None:
            return [f"미선언 엔티티 '{entity_type}' (closed-world drift)"] if (self.closed_world or self.require_entity) else []
        return et.violations(attrs)

    def metric_violations(self, metric_name, direction=None) -> list[str]:
        """metric 1개를 측정 어휘에 대조. 미선언+closed_world_metrics=drift; 선언됐으면 direction 일치 검사."""
        if not metric_name:
            return []
        spec = self.metrics.get(metric_name)
        if spec is None:
            return [f"미선언 metric '{metric_name}' (closed-world drift)"] if self.closed_world_metrics else []
        want = (spec or {}).get("direction")
        if want and direction and direction != want:
            return [f"metric '{metric_name}' direction={direction!r} ≠ 선언 {want!r}"]
        return []
