"""판정 신뢰성 하네스 NB1 — 이중가드 측정값을 LakatoTree judge가 직접 판정한다."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from lakatos.verdict.judge import NovelTarget, Prediction, judge

ROOT = Path(__file__).resolve().parents[1]
GUARD_FILE = ROOT / "tests" / "fix_harness" / "test_fix_3_noise-band-maxes-bayes.py"
GUARD_DEFECT = "test_absent_noise_band_must_not_mint_max_bayes_factor"
GUARD_MECHANISM = "test_declared_noise_band_separates_marginal_from_big"


def receipt() -> dict[str, bool]:
    """각 독립 가드를 별도 pytest 실행으로 측정한다(self-report 아님)."""
    out: dict[str, bool] = {}
    for guard in (GUARD_DEFECT, GUARD_MECHANISM):
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
             f"{GUARD_FILE}::{guard}"],
            cwd=ROOT, capture_output=True, text=True, check=False)
        out[guard] = proc.returncode == 0
    return out


def run(rc: dict[str, bool] | None = None) -> dict:
    """결함 폐쇄와 메커니즘 실재를 독립 축으로 judge해 verdict를 생성한다."""
    rc = receipt() if rc is None else rc
    defect_closed = bool(rc.get(GUARD_DEFECT))
    mechanism_present = bool(rc.get(GUARD_MECHANISM))
    pred = Prediction(
        metric_name="absent_noise_fail_open_gaps", direction="lower",
        baseline_value=1.0, noise_band=0.0,
        novel_prediction="declared noise scale preserves effect-size ordering",
        closes_question="q_nb1_noise_absence_failsafe")
    novel = NovelTarget(
        metric_name="declared_noise_mechanism_present", direction="higher", threshold=1.0)
    verdict = judge(
        pred, 0.0 if defect_closed else 1.0,
        novel_target=novel, novel_measured=1.0 if mechanism_present else 0.0,
        require_independent_source=True,
        independence_witness="NB1 dual oracle: absent-scale negative guard vs declared-scale mechanism guard")
    return {
        "tag": "NB1_noise_band_absence_failsafe",
        "verdict": verdict.verdict,
        "improved": verdict.improved,
        "novel": verdict.novel,
        "defect_closed": defect_closed,
        "mechanism_present": mechanism_present,
        "reason": verdict.reason,
    }


if __name__ == "__main__":
    print(run())
