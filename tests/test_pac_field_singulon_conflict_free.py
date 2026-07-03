"""PAC-field 초점 프로그램의 *유일 실측 corroboration* — 서로소 write-set ⇒ 무충돌 머지 by construction.

병렬-에이전트 코딩 프로그램은 'a-priori disjointness 가 optimistic-merge 를 이긴다'는 use-novel 사실이
아직 미측정(head-to-head 없음)이라 strict progressive 아님. 단, *무충돌 by construction* 이라는 협소 주장은
실 4-에이전트 git 세션으로 corroborated 됐다 — OMD tests/test_multiagent_session.py(4 물방울 서로소 모듈 실
worktree 개발+동시 connect → 실 git merge 4회, 통합 worktree clean=충돌 0, merge_token max held=1, 겹침 직렬화)를
OMD 자기 venv 로 subprocess 실행해 rc==0 으로 독립 확증. (크로스레포 도그푸드 — OMD 부재 시 honest skip.)
# KG: LakatosTree_ParallelAgentCodingField_20260627 / focal_singulon_conflict_free_by_construction
"""
import os
import subprocess

import pytest

OMD_ROOT = "<WORKSPACE>/PROJECT/PI/omd"
OMD_PY = os.path.join(OMD_ROOT, ".venv/bin/python")
SESSION_TEST = "tests/test_multiagent_session.py"

pytestmark = pytest.mark.skipif(
    not os.path.isdir(OMD_ROOT),
    reason="OMD 자매 repo 미체크아웃(hermetic CI) — 크로스레포 도그푸드는 로컬에서만 실측")


def test_pac_field_singulon_conflict_free_by_construction():
    assert os.path.isfile(OMD_PY), f"OMD venv python 부재: {OMD_PY}"
    assert os.path.isfile(os.path.join(OMD_ROOT, SESSION_TEST)), f"세션 테스트 부재: {SESSION_TEST}"
    proc = subprocess.run(
        [OMD_PY, "-m", "pytest", SESSION_TEST, "-q", "-p", "no:cacheprovider"],
        cwd=OMD_ROOT, capture_output=True, text=True, timeout=300)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, (
        "실 멀티에이전트 무충돌 git 세션이 green 아님 — 'by construction' 협소주장 미corroborated\n" + out[-3000:])
    assert "passed" in out, out[-1500:]


def test_negative_control_bogus_session_test_path_fails():
    """음성 대조: 존재하지 않는 세션 테스트 경로는 rc!=0 (오라클 비공허)."""
    proc = subprocess.run(
        [OMD_PY, "-m", "pytest", "tests/test_NOPE_session.py", "-q"],
        cwd=OMD_ROOT, capture_output=True, text=True, timeout=120)
    assert proc.returncode != 0
