"""NB1 judge dogfood — 두 독립 가드의 4분면 판별력과 실제 receipt를 고정한다."""
from examples.judgment_trust_20260714_programme import (
    GUARD_DEFECT, GUARD_MECHANISM, run,
)


def _rc(defect: bool, mechanism: bool) -> dict[str, bool]:
    return {GUARD_DEFECT: defect, GUARD_MECHANISM: mechanism}


def test_nb1_judge_discriminates_dual_guard_quadrants():
    assert run(_rc(True, True))["verdict"] == "progressive"
    assert run(_rc(True, False))["verdict"] == "partial"
    assert run(_rc(False, True))["verdict"] == "equivalent"
    assert run(_rc(False, False))["verdict"] == "equivalent"


def test_nb1_live_receipt_is_progressive():
    out = run()
    assert out["defect_closed"] and out["mechanism_present"]
    assert out["verdict"] == "progressive"
