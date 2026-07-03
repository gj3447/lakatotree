"""omd 채택마찰 F2/F3 가드 — 인터랙티브 페이스 vs crash-fast 회수 (2026-07-02 실전 봉합).

실측: claim(ttl=3600) 후 편집(verb 간 침묵 수십 분) → agent_ttl 기본 90s 좀비 판정 → RETIRED+
fenced_out, sweep 이 TTL 남은 HELD orbit 회수(F3). 봉합 설계: **lease 는 liveness 계약이 아니다**
(죽은 물방울의 긴 lease 를 빨리 회수하는 §D2 crash-fast 불변) — 대신 인터랙티브 세션이
`heartbeat(agent, ttl=)` 로 per-agent 생존창을 *명시 선언*한다. + 활동=생존신호(mutating verb touch).

가드는 omd 실 substrate 를 omd 자신의 venv 로 구동(subprocess — lakatotree venv 에 omd 미설치).

  guard_defect     = test_interactive_pace_survives_and_crash_fast_preserved
  guard_mechanism  = test_omd_substrate_has_pace_declaration_api

# KG: OmdAdoptionFriction_20260702 / F2_liveness_pace_mismatch
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


def _omd_pytest(*node_ids: str) -> subprocess.CompletedProcess:
    return subprocess.run([str(_PY), "-m", "pytest", "-q", "-p", "no:cacheprovider", *node_ids],
                          cwd=_OMD, capture_output=True, text=True, timeout=300)


def test_interactive_pace_survives_and_crash_fast_preserved():
    """defect(음성+반대 오라클 쌍): ① 페이스 선언 agent 는 기본 agent_ttl 넘는 침묵에도 orbit
    보존+release ok(F2/F3 재현 봉합) ② 미선언 agent 는 긴 lease 여도 crash-fast 회수(§D2 불변).
    omd 실 코어를 그 repo 가드로 구동 — 여기서 재구현하지 않는다."""
    r = _omd_pytest(
        "tests/test_adoption_friction.py::test_interactive_pace_agent_survives_declared_lease_window",
        "tests/test_adoption_friction.py::test_crash_fast_reclaim_preserved_for_undeclared_agents",
        "tests/test_adoption_friction.py::test_mutating_verbs_touch_agent_liveness",
    )
    assert r.returncode == 0, f"omd F2 가드 RED:\n{r.stdout[-1500:]}\n{r.stderr[-500:]}"


def test_omd_substrate_has_pace_declaration_api():
    """mechanism(양성): 페이스 선언 API 가 실 substrate 에 있다 — core.heartbeat(ttl=) 서명 +
    store 의 per-agent liveness_ttl(스키마 마이그레이션) + MCP heartbeat 도구의 ttl 노출."""
    code = (
        "import inspect\n"
        "from omd_server.core import Coordinator\n"
        "from omd_server import store as st, server as sv\n"
        "sig = inspect.signature(Coordinator.heartbeat)\n"
        "assert 'ttl' in sig.parameters, 'heartbeat 에 ttl 페이스 선언 없음'\n"
        "assert any(m[:2] == ('agents', 'liveness_ttl') for m in st._MIGRATIONS), 'liveness_ttl 마이그레이션 없음'\n"
        "assert hasattr(st.Store, 'set_agent_liveness_ttl')\n"
        "import pathlib, re\n"
        "src = pathlib.Path(sv.__file__).read_text()\n"
        "assert re.search(r'def heartbeat\\(agent: str, ttl', src), 'MCP heartbeat 가 ttl 미노출'\n"
        "print('pace-api-ok')\n"
    )
    r = subprocess.run([str(_PY), "-c", code], cwd=_OMD, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and "pace-api-ok" in r.stdout, f"{r.stdout}\n{r.stderr}"
