"""COV1 judge dogfood — fail-closed default and earned exhaustive mechanism."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from lakatos.verdict.judge import NovelTarget, Prediction, judge

ROOT = Path(__file__).resolve().parents[1]
GUARD_FILE = ROOT / "tests" / "fix_harness" / "test_coverage_status_20260714.py"
GUARD_DEFECT = "test_missing_coverage_declaration_must_not_mint_exhaustive"
GUARD_MECHANISM = "test_scoped_exhaustive_declaration_is_earned_and_guarded"


def receipt() -> dict[str, bool]:
    out: dict[str, bool] = {}
    for guard in (GUARD_DEFECT, GUARD_MECHANISM):
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
             f"{GUARD_FILE}::{guard}"], cwd=ROOT,
            capture_output=True, text=True, check=False)
        out[guard] = proc.returncode == 0
    return out


def run(rc: dict[str, bool] | None = None) -> dict:
    rc = receipt() if rc is None else rc
    defect_closed = bool(rc.get(GUARD_DEFECT))
    mechanism_present = bool(rc.get(GUARD_MECHANISM))
    pred = Prediction(
        metric_name="unearned_exhaustive_paths", direction="lower",
        baseline_value=1.0, noise_band=0.0,
        novel_prediction="explicit scoped declaration is the sole exhaustive path",
        closes_question="q_cov1_coverage_status")
    novel = NovelTarget(
        metric_name="earned_exhaustive_mechanism", direction="higher", threshold=1.0)
    verdict = judge(
        pred, 0.0 if defect_closed else 1.0,
        novel_target=novel, novel_measured=1.0 if mechanism_present else 0.0,
        require_independent_source=True,
        independence_witness="COV1 dual oracle: missing-status denial vs scoped-exhaustive admission")
    return {"tag": "COV1_explicit_coverage_status", "verdict": verdict.verdict,
            "defect_closed": defect_closed, "mechanism_present": mechanism_present,
            "reason": verdict.reason}


if __name__ == "__main__":
    print(run())
