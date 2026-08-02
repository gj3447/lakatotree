"""Credential recovery artifacts from the restart helper stay private."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_restart_gate_uses_core_healthz_not_full_traffic_readiness():
    script = (ROOT / "scripts/dev_server_restart.sh").read_text(encoding="utf-8")
    probe_lines = [line for line in script.splitlines() if "curl" in line]
    assert any("/healthz" in line and "-sf" in line for line in probe_lines)
    assert all("/readyz" not in line for line in probe_lines)


def test_restart_launcher_rejects_multiworker_cache_split():
    script = (ROOT / "scripts/dev_server_restart.sh").read_text(encoding="utf-8")
    assert 'if [ "${WEB_CONCURRENCY:-1}" != "1" ]' in script
    assert "export WEB_CONCURRENCY=1" in script
    assert "--workers 1" in script


def test_restart_uses_canonical_env_name_and_private_atomic_recovery_recipe():
    script = (ROOT / "scripts/dev_server_restart.sh").read_text(encoding="utf-8")
    assert "LAKATOS_ENV_FILE" in script
    assert "RECOVERY_TMP" in script and "mktemp" in script
    assert 'chmod 600 \\"\\$RECOVERY_TMP\\" && mv' in script
    assert "> $ENV_FILE && chmod" not in script


def test_restart_health_probe_tracks_the_effective_bind_host():
    script = (ROOT / "scripts/dev_server_restart.sh").read_text(encoding="utf-8")
    assert 'HEALTH_BASE="http://$PROBE_HOST:55170"' in script
    assert '"$HEALTH_BASE/healthz"' in script
    assert '"$HEALTH_BASE/version"' in script


def test_restart_validates_sourced_listener_before_stopping_old_process():
    script = (ROOT / "scripts/dev_server_restart.sh").read_text(encoding="utf-8")
    sourced = script.index('. "$ENV_FILE"')
    posture = script.index('-m server.auth_posture')
    old_pid_lookup = script.index('PID="$(listener_pid)"')
    assert sourced < posture < old_pid_lookup
    assert 'UVICORN_FD' not in script or 'server.auth_posture' in script


def test_restart_proves_old_exit_and_new_listener_identity():
    script = (ROOT / "scripts/dev_server_restart.sh").read_text(encoding="utf-8")
    assert 'kill -0 "$PID"' in script
    assert 'REMAINING_PID="$(listener_pid)"' in script
    assert 'NEW_PID=$!' in script
    assert 'kill -0 "$NEW_PID"' in script
    assert '[ "$LISTENER_PID" != "$NEW_PID" ]' in script
    assert 'process_is_this_server "$PID"' in script
    assert 'process_start_time "$PID"' in script
    assert 'realpath "$PROC_ROOT/$candidate/cwd"' in script
    assert 'realpath "$PROC_ROOT/$candidate/exe"' in script


def test_lastboot_backup_is_atomic_and_mode_0600_under_public_umask(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_ss = fake_bin / "ss"
    fake_ss.write_text(
        "#!/bin/sh\nprintf '%s\\n' 'LISTEN :55170 users:((python,pid=99999999,fd=3))'\n",
        encoding="utf-8",
    )
    fake_ss.chmod(0o755)
    fake_grep = fake_bin / "grep"
    fake_grep.write_text(
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = '-oP' ]; then\n"
        "  sed -n 's/.*pid=\\([0-9][0-9]*\\).*/\\1/p'\n"
        "else\n"
        "  exec /usr/bin/grep \"$@\"\n"
        "fi\n",
        encoding="utf-8",
    )
    fake_grep.chmod(0o755)

    proc_root = tmp_path / "proc"
    environ_dir = proc_root / "99999999"
    environ_dir.mkdir(parents=True)
    (environ_dir / "environ").write_bytes(
        b"NEO4J_PASSWORD=secret-db\0LAKATOS_API_TOKEN=secret-api\0"
        b"LAKATOS_STORAGE_PG_MIGRATION_PASSWORD=must-not-persist\0IGNORED=x\0"
    )
    (environ_dir / "cmdline").write_bytes(
        b".venv/bin/python\0-m\0uvicorn\0--app-dir\0server\0app:app\0"
        b"--host\x00127.0.0.1\x00--port\x0055170\x00--workers\x001\x00"
    )
    (environ_dir / "stat").write_text(
        "99999999 (python) " + " ".join(["S", *(["0"] * 18), "12345"]) + "\n",
        encoding="utf-8",
    )
    interpreter = Path(sys.executable).resolve()
    (environ_dir / "cwd").symlink_to(ROOT, target_is_directory=True)
    (environ_dir / "exe").symlink_to(interpreter)
    env_file = tmp_path / "server.env"
    env_file.write_text(
        "NEO4J_URI=bolt://example.invalid\n"
        "NEO4J_DATABASE=neo4j\n"
        "NEO4J_USER=neo4j\n"
        "NEO4J_PASSWORD=canonical\n"
        "LAKATOS_MONGO_URI=mongodb://example.invalid\n",
        encoding="utf-8",
    )
    env_file.chmod(0o600)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "LAKATOS_PYTHON": str(interpreter),
        "LAKATOS_SERVER_ENV": str(env_file),
        "LAKATOS_PROC_ROOT": str(proc_root),
    }
    completed = subprocess.run(
        [
            "bash",
            "-c",
            "umask 022; exec bash scripts/dev_server_restart.sh",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode != 0  # fake PID cannot be signalled; backup precedes kill
    backup = Path(f"{env_file}.lastboot")
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    assert backup.read_text(encoding="utf-8").splitlines() == [
        "NEO4J_PASSWORD=secret-db",
        "LAKATOS_API_TOKEN=secret-api",
    ]
    assert list(tmp_path.glob("server.env.lastboot.*")) == []
