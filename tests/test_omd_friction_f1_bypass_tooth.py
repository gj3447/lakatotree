"""omd 채택마찰 F1 가드 — 세션이 OMD 를 안 보는 문제의 기계적 이빨 (2026-07-02 실전 봉합).

실측: 병렬충돌 2회 모두 'OMD 가 있는데 아무도 기본으로 안 탐'에서 발생. CLAUDE.md(규율층)는
지시일 뿐 이빨이 없다 — omd 의 bypass 감지(P1, warn-only)를 lakatotree 에 *실설치*하고, 글로벌
core.hooksPath(ooptdd-hooks)가 repo-local 훅을 가리는 footgun 을 체인-스루로 뚫는다.

  guard_defect     = test_bypass_gate_detects_unleased_commits_warn_only
  guard_mechanism  = test_pre_push_hook_installed_and_chained

# KG: OmdAdoptionFriction_20260702 / F1_session_bypasses_omd
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

_OMD = Path("<WORKSPACE>/PROJECT/PI/omd")
_LKT = Path(__file__).resolve().parents[1]
_PY = _OMD / ".venv" / "bin" / "python"

pytestmark = pytest.mark.skipif(
    not _OMD.is_dir(),
    reason="OMD 자매 repo 미체크아웃(hermetic CI) — 크로스레포 도그푸드 가드는 로컬에서만 실측")


def test_bypass_gate_detects_unleased_commits_warn_only():
    """defect(이빨 관측): 실제 lakatotree 브랜치에 대해 gate --warn-only 를 돌리면 OMD 안 거친
    직접커밋을 *감지·보고*하되(이 repo 는 lease-only 흐름이라 직접커밋 존재) exit 0(warn-only —
    채택 0% 단계에서 hard-block 은 닭-달걀). 감지가 0 이고 보고도 없으면 이빨이 진공."""
    r = subprocess.run(
        [str(_PY), str(_OMD / "scripts" / "omd_bypass_gate.py"),
         "--repo", str(_LKT), "--branch", "git-absorption/g1-immutable-receipts",
         "--since", "HEAD~30", "--warn-only"],
        capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, f"warn-only 인데 비영점 exit: {r.stdout}\n{r.stderr}"
    out = r.stdout + r.stderr
    assert ("bypass" in out.lower() or "우회" in out or "adoption" in out.lower()), \
        f"게이트가 아무것도 보고하지 않음(진공 이빨): {out[:400]}"


def test_pre_push_hook_installed_and_chained():
    """mechanism: ① repo-local pre-push 훅 실재+실행가능+warn-only ② 글로벌 hooksPath 가 설정된
    경우 그 pre-push 가 repo-local 훅으로 체인-스루(footgun 뚫림 — 안 뚫리면 훅이 영원히 무발화)."""
    local_hook = _LKT / ".git" / "hooks" / "pre-push"
    assert local_hook.is_file() and os.access(local_hook, os.X_OK), "omd bypass pre-push 훅 미설치"
    body = local_hook.read_text()
    assert "OMD P1 bypass guard" in body and 'WARN="1"' in body, "훅이 omd bypass warn-only 가 아님"

    hooks_path = subprocess.run(["git", "config", "--get", "core.hooksPath"],
                                capture_output=True, text=True).stdout.strip()
    if hooks_path:   # 글로벌/로컬 hooksPath 가 로컬 훅을 가리는 환경 — 체인-스루 필수
        chained = Path(os.path.expanduser(hooks_path)) / "pre-push"
        assert chained.is_file(), f"hooksPath({hooks_path})에 pre-push 없음"
        assert "LOCAL_HOOK" in chained.read_text(), \
            "글로벌 pre-push 가 repo-local 훅으로 체인-스루하지 않음(훅 무발화 footgun 잔존)"
