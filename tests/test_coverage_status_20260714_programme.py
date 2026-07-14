"""COV1 judge dogfood — two independent guards and their four quadrants."""
from examples.coverage_status_20260714_programme import (
    GUARD_DEFECT, GUARD_MECHANISM, run,
)


def _rc(defect: bool, mechanism: bool) -> dict[str, bool]:
    return {GUARD_DEFECT: defect, GUARD_MECHANISM: mechanism}


def test_cov1_judge_discriminates_dual_guard_quadrants():
    assert run(_rc(True, True))["verdict"] == "progressive"
    assert run(_rc(True, False))["verdict"] == "partial"
    assert run(_rc(False, True))["verdict"] == "equivalent"
    assert run(_rc(False, False))["verdict"] == "equivalent"


def test_cov1_live_receipt_is_progressive():
    out = run()
    assert out["defect_closed"] and out["mechanism_present"]
    assert out["verdict"] == "progressive"
