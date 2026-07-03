"""omd 채택마찰 F4 가드 — lease-only 태스크의 종결 verb (2026-07-02 실전 봉합).

실측: declare+claim(start 미경유) 태스크는 finish 가 FSM 거부("from state PENDING!") 되고
complete_task 도 start 전제 → PENDING 영구 잔류(next() 추천 오염). 봉합: cancel(task, reason) —
미시작(PENDING/READY/BLOCKED) 전용 종결(FSM 기존 abort 전이 재사용 = 상태기계/TLA 모델 무변경),
시작된 태스크는 거부(무단 증발 금지, finish/bail 경유), 멱등, MCP 노출.

  guard_defect     = test_lease_only_task_closable_and_started_protected
  guard_mechanism  = test_omd_substrate_exposes_cancel_verb

# KG: OmdAdoptionFriction_20260702 / F4_lease_only_no_terminal_verb
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_OMD = Path("<WORKSPACE>/PROJECT/PI/omd")
_PY = _OMD / ".venv" / "bin" / "python"

pytestmark = pytest.mark.skipif(
    not _OMD.is_dir(),
    reason="OMD 자매 repo 미체크아웃(hermetic CI) — 크로스레포 도그푸드 가드는 로컬에서만 실측")


def test_lease_only_task_closable_and_started_protected():
    """defect: ① lease-only 태스크 cancel → ABORTED + next() 추천에서 소멸(PENDING 잔류 봉합)
    ② 시작된 태스크는 cancel 거부(진행중 작업 무단 증발 금지) ③ 멱등+미존재 fail-loud.
    omd 실 코어를 그 repo 가드로 구동."""
    r = subprocess.run(
        [str(_PY), "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "tests/test_adoption_friction.py::test_lease_only_task_can_be_cancelled",
         "tests/test_adoption_friction.py::test_cancel_refuses_started_tasks",
         "tests/test_adoption_friction.py::test_cancel_is_idempotent_and_missing_task_fails_loud"],
        cwd=_OMD, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, f"omd F4 가드 RED:\n{r.stdout[-1500:]}\n{r.stderr[-500:]}"


def test_omd_substrate_exposes_cancel_verb():
    """mechanism: cancel 이 실 substrate 에 — core.cancel 실재 + FSM 신규 전이 0(기존 abort 재사용
    = TLA 모델 불변) + MCP 도구 노출."""
    code = (
        "import inspect, pathlib, re\n"
        "from omd_server.core import Coordinator\n"
        "from omd_server import fsm, server as sv\n"
        "assert callable(getattr(Coordinator, 'cancel', None)), 'core.cancel 없음'\n"
        "trigs = {t['trigger'] for t in fsm.TASK_TRANSITIONS}\n"
        "assert 'cancel' not in trigs and 'abort' in trigs, 'FSM 에 신규 전이가 생김(TLA 모델 변경)'\n"
        "src = pathlib.Path(sv.__file__).read_text()\n"
        "assert re.search(r'def cancel\\(task: str', src), 'MCP cancel 도구 미노출'\n"
        "print('cancel-verb-ok')\n"
    )
    r = subprocess.run([str(_PY), "-c", code], cwd=_OMD, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and "cancel-verb-ok" in r.stdout, f"{r.stdout}\n{r.stderr}"
