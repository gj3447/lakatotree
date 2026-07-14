"""외부 bind 인증 하네스 AB1 — 독립 가드 결과를 judge가 직접 판정한다."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from lakatos.verdict.judge import NovelTarget, Prediction, judge

ROOT = Path(__file__).resolve().parents[1]
GUARD_FILE = ROOT / "tests" / "fix_harness" / "test_external_bind_auth_20260714.py"
GUARD_DEFECT = "test_external_bind_without_token_is_rejected"
GUARD_MECHANISM = "test_loopback_bind_without_token_is_allowed"


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
        metric_name="unauthenticated_external_bind_paths", direction="lower",
        baseline_value=1.0, noise_band=0.0,
        novel_prediction="loopback open remains available while external bind requires token",
        closes_question="q_ab1_external_bind_auth")
    novel = NovelTarget(
        metric_name="safe_local_development_path", direction="higher", threshold=1.0)
    verdict = judge(
        pred, 0.0 if defect_closed else 1.0,
        novel_target=novel, novel_measured=1.0 if mechanism_present else 0.0,
        require_independent_source=True,
        independence_witness="AB1 dual oracle: external rejection corpus vs loopback compatibility corpus")
    return {"tag": "AB1_external_bind_auth", "verdict": verdict.verdict,
            "defect_closed": defect_closed, "mechanism_present": mechanism_present,
            "reason": verdict.reason}


if __name__ == "__main__":
    print(run())
