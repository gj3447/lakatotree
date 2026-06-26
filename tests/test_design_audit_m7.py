"""M7 design-audit guard: CI/kernel actually *enforces* sorry=0 (not just documents it).

결함(감사 M7): formal job 의 주석은 "ground-truth gate: error=0, sorry=0" 라 약속하지만
Lean 에서 `sorry` 는 warning 이고 `lake build` 는 warning 에 exit 0 을 낸다(직접 재현됨).
따라서 `Rung.derived` 타입 불변식(self-report 거부)이 sorry 한 줄로 위조 가능 — 강제되지 않는
보증. 수정(PROM 처방 a): `formal/Pidna.lean` 파일 스코프에 `set_option warningAsError true`
→ sorry → error → exit≠0. (대안 b: ci.yml 의 sorry-거부 grep step.)

이 테스트는 *강제 메커니즘이 실제로 배선됐는지* 검증한다(환경독립·durable):
  - 1차 게이트: Pidna.lean 의 warningAsError 또는 ci.yml 의 sorry-거부 step 존재 — 둘 다 없으면 RED.
  - 2차(강): lean 툴체인이 있으면, 배선된 메커니즘을 적용한 채 sorry-주입 파일을 실제로
    컴파일해 비0 exit 를 내는지 확인(없으면 skip 명시). vacuous green 금지.
# KG: span_lakatotree_design_audit_20260625
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_PIDNA = _REPO / "formal" / "Pidna.lean"
_CI = _REPO / ".github" / "workflows" / "ci.yml"

# file-scope `set_option warningAsError true` (sorry-warning → error). Tolerant of spacing.
_WAE_RE = re.compile(r"set_option\s+warningAsError\s+true")
# a CI step that rejects sorry: greps the build log for Lean's sorry-warning and fails.
_CI_SORRY_GUARD_RE = re.compile(r"uses 'sorry'|uses .sorry.|warningAsError")


def _pidna_enforces_sorry_zero() -> bool:
    return bool(_WAE_RE.search(_PIDNA.read_text(encoding="utf-8")))


def _ci_rejects_sorry() -> bool:
    if not _CI.exists():
        return False
    return bool(_CI_SORRY_GUARD_RE.search(_CI.read_text(encoding="utf-8")))


def test_ci_fails_on_lean_sorry() -> None:
    """sorry=0 is *enforced*, not merely documented.

    RED when no enforcement mechanism is wired (the M7 defect state). GREEN once
    Pidna.lean carries `set_option warningAsError true` (or ci.yml gains a
    sorry-rejecting step). NOT vacuous: absence of any mechanism fails here.
    """
    pidna_ok = _pidna_enforces_sorry_zero()
    ci_ok = _ci_rejects_sorry()
    assert pidna_ok or ci_ok, (
        "M7: no enforced sorry=0 gate. Expected `set_option warningAsError true` in "
        f"{_PIDNA} (PROM rx a) or a sorry-rejecting step in {_CI} (PROM rx b). "
        "Without it, `lake build` exits 0 on a `sorry` warning and the Rung.derived "
        "self-report invariant can be forged by one `sorry` line."
    )

    # Stronger, environment-dependent check: if a Lean toolchain is present, prove the
    # wired mechanism actually turns a `sorry` into a non-zero exit. Skip cleanly otherwise.
    if not pidna_ok:
        pytest.skip(
            "compile-level check verifies the warningAsError path (PROM rx a); "
            "ci.yml grep guard (rx b) is exercised by CI, not by this unit test."
        )
    lean = shutil.which("lean")
    if lean is None:
        pytest.skip("lean toolchain not on PATH — wiring asserted statically above")

    # Compile a minimal file that mirrors the wired option and contains a `sorry`.
    # With warningAsError, the sorry-warning must be promoted to a build error (exit != 0).
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "SorryProbe.lean"
        src.write_text(
            "set_option warningAsError true\n"
            "theorem _m7_probe : True := by sorry\n",
            encoding="utf-8",
        )
        proc = subprocess.run(  # noqa: S603
            [lean, str(src)],
            capture_output=True,
            text=True,
            timeout=120,
        )
    assert proc.returncode != 0, (
        "warningAsError must promote Lean's `declaration uses 'sorry'` warning to a "
        f"build error (non-zero exit). Got exit 0.\nstdout={proc.stdout!r}\n"
        f"stderr={proc.stderr!r}"
    )
    combined = f"{proc.stdout}\n{proc.stderr}"
    assert "sorry" in combined, (
        "expected the failure to be about `sorry`, got:\n" + combined
    )
