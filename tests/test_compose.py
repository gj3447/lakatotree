"""Judge-composition monoid laws (OQ7) — compose_gates with identity + absorbing element."""
from __future__ import annotations

from lakatos.verdict.compose import IDENTITY, GateOutcome, compose_gates, hard_fail


def test_left_identity_then_j_is_j():
    g = GateOutcome("g", ("r1", "r2"))
    out = compose_gates(IDENTITY, g)
    assert out.reasons == g.reasons and out.passed == g.passed


def test_right_identity():
    g = GateOutcome("g", ("r1",))
    out = compose_gates(g, IDENTITY)
    assert out.reasons == g.reasons and out.passed == g.passed


def test_none_gate_is_identity():
    g = GateOutcome("g", ("r",))
    assert compose_gates(None, g).reasons == g.reasons
    assert compose_gates(g, None).reasons == g.reasons


def test_absorbing_hard_fail_survives_composition():
    out = compose_gates(hard_fail("x", "boom"), IDENTITY, GateOutcome("ok", ()))
    assert not out.passed and "boom" in out.reasons


def test_all_pass_is_pass():
    out = compose_gates(GateOutcome("a", ()), GateOutcome("b", ()), None)
    assert out.passed and out.reasons == ()


def test_reason_concatenation_is_order_preserving():
    a, b, c = GateOutcome("a", ("1",)), GateOutcome("b", ("2",)), GateOutcome("c", ("3",))
    assert compose_gates(a, b, c).reasons == ("1", "2", "3")
