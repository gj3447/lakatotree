"""Reusable declarative fact-query evaluator (Kythe Souffle goal-verifier / Glean ``where``).

A judge expresses its expected facts as DATA — a list of :class:`FactQuery` rows — evaluated
by ONE :func:`evaluate` runner, instead of growing a bespoke per-rule conditional grader.
The test IS a query over the emitted facts; adding a new structural assertion is a new row,
not new imperative code. Mirrors ``tpa_engine.fitness``'s predicate registry, scoped to a
dict of keyed JSON fact-rows.
"""
from __future__ import annotations

import operator
from collections.abc import Callable
from dataclasses import dataclass

_OPS = {
    "==": operator.eq, "!=": operator.ne,
    ">=": operator.ge, ">": operator.gt, "<=": operator.le, "<": operator.lt,
    "in": lambda a, b: a in b,
    "contains": lambda a, b: b in (a or ""),
}

FACT_PREDICATE_REGISTRY: dict[str, Callable] = {}


def fact_predicate(name: str) -> Callable:
    """Register a named fact predicate ``fn(rows, args) -> bool`` (duplicate-name guard)."""
    def deco(fn: Callable) -> Callable:
        if name in FACT_PREDICATE_REGISTRY:
            raise ValueError(f"duplicate fact predicate {name!r}")
        FACT_PREDICATE_REGISTRY[name] = fn
        return fn
    return deco


@dataclass(frozen=True)
class FactQuery:
    """One declarative assertion. ``predicate`` is checked over the keyed fact-rows;
    ``label`` is emitted when the assertion does NOT hold. ``args`` are predicate params."""

    predicate: str
    label: str
    args: tuple = ()


@fact_predicate("present")
def _present(rows: dict, args) -> bool:
    (key,) = args
    return key in rows


@fact_predicate("field")
def _field(rows: dict, args) -> bool:
    # absent key vacuously passes here (a separate `present` query reports the absence) —
    # so a missing fact yields exactly one label, not one per field.
    key, field, op, expected = args
    item = rows.get(key)
    return item is None or _OPS[op](item.get(field), expected)


def evaluate(rows: dict, queries: list[FactQuery]) -> list[str]:
    """Labels of every :class:`FactQuery` whose assertion does NOT hold over ``rows`` (a
    dict of keyed fact-rows). Empty = all satisfied. Deterministic (query order preserved)."""
    failed: list[str] = []
    for q in queries:
        fn = FACT_PREDICATE_REGISTRY[q.predicate]
        if not fn(rows, q.args):
            failed.append(q.label)
    return failed
