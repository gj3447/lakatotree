"""Judge/gate composition as a free monoid (Joern ``Semantics`` monoid / jQAssistant
``VerificationStrategy``).

A :class:`GateOutcome` carries the reasons a gate blocked (empty tuple = passed). Gates
compose by concatenating their reasons; the identity is the empty outcome (a pass-through
gate), and a hard-fail's reasons survive every composition (absorbing). So a multi-gate
verdict is a *fold* over GateOutcomes — order-explicit, total, and a missing gate is a
*provable identity* (no silent gap), instead of a hand-rolled ``block.extend`` accumulation.

Laws (property-tested in tests/test_compose.py):
    compose_gates(IDENTITY, g) ≡ g          (left identity)
    compose_gates(g, IDENTITY) ≡ g          (right identity)
    compose_gates(hard_fail(...), x).passed is False for any x   (absorbing)
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GateOutcome:
    """The outcome of one gate: the reasons it blocked (empty = it passed)."""

    name: str
    reasons: tuple = ()

    @property
    def passed(self) -> bool:
        return not self.reasons


IDENTITY = GateOutcome("identity", ())


def hard_fail(name: str, *reasons: str) -> GateOutcome:
    """An absorbing gate: it blocks, and its reason(s) survive every composition."""
    return GateOutcome(name, tuple(reasons) or (name,))


def combine(a: GateOutcome, b: GateOutcome) -> GateOutcome:
    """Associative reason-concatenation with IDENTITY as the unit."""
    name = b.name if a is IDENTITY else a.name
    return GateOutcome(name, tuple(a.reasons) + tuple(b.reasons))


def compose_gates(*gates: GateOutcome | None) -> GateOutcome:
    """Fold gates (a ``None`` gate is the identity = an unsupplied gate) into one outcome.

    Passes iff every gate passed — i.e. no reason was accumulated by any of them."""
    out = IDENTITY
    for g in gates:
        if g is not None:
            out = combine(out, g)
    return out
