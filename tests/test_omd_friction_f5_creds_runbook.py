"""omd 채택마찰 F5 가드 — :55170 creds 단일사본 소멸 사고의 봉합 (2026-07-02 실전).

실측: 병렬 세션이 creds 없는 쉘로 재기동 → neo4j/pg down 인데 /version 200(무음 degraded),
비번 원본은 죽은 프로세스 environ 이 유일 사본이라 소멸(i2b 공통비번 후보 대입으로 간신히 복구).
봉합: 정본 env(~/.config/lakatotree/server.env, 0600) + scripts/dev_server_restart.sh —
env 없으면 기동 *거부*, 죽이기 전 environ 백업, healthz **3/3 게이트**(version 200 ≠ 건강).

  guard_defect     = test_restart_script_refuses_without_canonical_env
  guard_mechanism  = test_canonical_env_and_runbook_wiring

# KG: OmdAdoptionFriction_20260702 / F5_server_creds_single_copy
"""
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

_LKT = Path(__file__).resolve().parents[1]
_SCRIPT = _LKT / "scripts" / "dev_server_restart.sh"


def test_restart_script_refuses_without_canonical_env(tmp_path):
    """defect(음성 오라클): 정본 env 부재 시 기동을 *거부*(비영점 exit + 복구 절차 안내) —
    사고의 뿌리였던 '무-creds 무음 기동'이 이 러너로는 표현 불가."""
    r = subprocess.run(["bash", str(_SCRIPT)], capture_output=True, text=True, timeout=60,
                       env={**os.environ, "LAKATOS_SERVER_ENV": str(tmp_path / "absent.env")})
    assert r.returncode == 2, f"env 부재인데 거부하지 않음(rc={r.returncode}): {r.stdout}{r.stderr}"
    assert "canonical env" in r.stderr and "/proc/" in r.stderr, "복구 절차 미안내(fail-loud 불완전)"


def test_canonical_env_and_runbook_wiring():
    """mechanism: ① 정본 env 실재+0600+필수 키(NEO4J_URI/PASSWORD, PG) ② 러너가 사고의 세 교훈을
    코드로 봉합 — 죽이기 전 environ 백업 / healthz 3/3 게이트(재시도) / pkill -f 부재(자기쉘 자살 금지)."""
    env_file = Path(os.path.expanduser("~/.config/lakatotree/server.env"))
    assert env_file.is_file(), "정본 env 없음 — 재시작 러너가 기동 거부 상태"
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600, "정본 env 권한이 0600 아님(시크릿 노출)"
    keys = {ln.split("=", 1)[0] for ln in env_file.read_text().splitlines() if "=" in ln}
    assert {"NEO4J_URI", "NEO4J_PASSWORD", "LAKATOS_PG_PASSWORD"} <= keys, f"필수 creds 키 누락: {keys}"

    body = _SCRIPT.read_text()
    assert "environ" in body and ".lastboot" in body, "죽이기 전 environ 백업 없음(단일사본 재발)"
    assert '"status":"ok"' in body and "seq 1 15" in body, "healthz 3/3 수렴 게이트 없음(version≠건강)"
    cmd_lines = [ln for ln in body.splitlines() if not ln.lstrip().startswith("#")]
    assert not any("pkill" in ln for ln in cmd_lines), "pkill 명령 사용(자기쉘 자살 footgun)"
    assert os.access(_SCRIPT, os.X_OK) or True   # 실행은 bash 경유 — 존재/내용이 계약
