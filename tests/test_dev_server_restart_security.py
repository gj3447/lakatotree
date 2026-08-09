"""Credential recovery artifacts from the restart helper stay private."""

from __future__ import annotations

import os
import shlex
import stat
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _write_fake_process(
    proc_root: Path,
    pid: str,
    *,
    python_bin: Path,
    start_time: str,
) -> None:
    process = proc_root / pid
    process.mkdir(parents=True)
    (process / "environ").write_bytes(
        b"NEO4J_PASSWORD=secret-db\0LAKATOS_API_TOKEN=secret-api\0"
    )
    (process / "cmdline").write_bytes(
        f"{python_bin}\0-m\0uvicorn\0--app-dir\0server\0app:app\0"
        "--host\x000.0.0.0\x00--port\x0055170\x00".encode()
    )
    (process / "stat").write_text(
        f"{pid} (python) " + " ".join(["S", *(["0"] * 18), start_time]) + "\n",
        encoding="utf-8",
    )
    (process / "cwd").symlink_to(ROOT, target_is_directory=True)
    (process / "exe").symlink_to(python_bin)


def _systemd_restart_fixture(
    tmp_path: Path,
    *,
    initial_state: str = "old",
    listener_matches: bool = True,
    restart_mode: str = "success",
    health_mode: str = "ready",
    version_mode: str = "valid",
    stop_mode: str = "success",
    auth_mutation: str = "none",
    post_invocation: str = "new",
    post_listener_matches: bool = True,
    new_start_time: str = "23456",
):
    assert initial_state in {"old", "inactive"}
    assert restart_mode in {"success", "fail_unchanged", "fail_changed"}
    assert health_mode in {"ready", "degraded"}
    assert version_mode in {"valid", "invalid"}
    assert stop_mode in {"success", "fail"}
    assert auth_mutation in {"none", "listener", "static", "env"}
    assert post_invocation in {"new", "old"}
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    state_file = tmp_path / "systemd-state"
    state_file.write_text(f"{initial_state}\n", encoding="utf-8")
    systemctl_log = tmp_path / "systemctl.log"
    nohup_marker = tmp_path / "nohup-called"
    old_pid = "90000001"
    listener_old_pid = old_pid if listener_matches else "90000999"
    new_pid = "90000002"

    _write_executable(
        fake_bin / "systemctl",
        """#!/bin/sh
set -eu
state=$(tr -d '\\n' < "$SYSTEMD_TEST_STATE")
install_new_process() {
  if [ -d "$SYSTEMD_TEST_PENDING_PROC/$SYSTEMD_TEST_MAIN_NEW" ]; then
    mv "$SYSTEMD_TEST_PENDING_PROC/$SYSTEMD_TEST_MAIN_NEW" "$SYSTEMD_TEST_PROC/$SYSTEMD_TEST_MAIN_NEW"
  fi
}
retire_old_process() {
  if [ -d "$SYSTEMD_TEST_PROC/$SYSTEMD_TEST_MAIN_OLD" ]; then
    mv "$SYSTEMD_TEST_PROC/$SYSTEMD_TEST_MAIN_OLD" "$SYSTEMD_TEST_RETIRED_PROC/$SYSTEMD_TEST_MAIN_OLD"
  fi
}
if [ "${1:-}" = show ]; then
  property=${3#--property=}
  case "$property" in
    LoadState) printf '%s\\n' loaded ;;
    Id|Names) printf '%s\\n' lakatotree.service ;;
    Type) printf '%s\\n' simple ;;
    Restart)
      if [ -e "$SYSTEMD_TEST_STATIC_DRIFT" ]; then printf '%s\\n' always; else printf '%s\\n' on-failure; fi
      ;;
    KillMode) printf '%s\\n' control-group ;;
    WorkingDirectory) printf '%s\\n' "$SYSTEMD_TEST_ROOT" ;;
    Environment) printf '\\n' ;;
    EnvironmentFiles) printf '%s (ignore_errors=no)\\n' "$SYSTEMD_TEST_ENV" ;;
    ExecStart)
      printf '{ path=%s ; argv[]=%s -m uvicorn --app-dir server app:app --host 0.0.0.0 --port 55170 --log-level warning ; ignore_errors=no ; }\\n' "$SYSTEMD_TEST_PYTHON" "$SYSTEMD_TEST_PYTHON"
      ;;
    User|Group|DropInPaths) printf '\\n' ;;
    FragmentPath) printf '%s\\n' /etc/systemd/system/lakatotree.service ;;
    ActiveState)
      case "$state" in old|new) printf '%s\\n' active ;; *) printf '%s\\n' inactive ;; esac
      ;;
    SubState)
      case "$state" in old|new) printf '%s\\n' running ;; *) printf '%s\\n' dead ;; esac
      ;;
    Result)
      if [ "$state" = inactive ]; then printf '\\n'; else printf '%s\\n' success; fi
      ;;
    MainPID)
      case "$state" in
        old) printf '%s\\n' "$SYSTEMD_TEST_MAIN_OLD" ;;
        new) printf '%s\\n' "$SYSTEMD_TEST_MAIN_NEW" ;;
        *) printf '%s\\n' 0 ;;
      esac
      ;;
    InvocationID)
      case "$state" in
        old) printf '%s\\n' aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa ;;
        new|stopped)
          if [ "$SYSTEMD_TEST_POST_INVOCATION" = old ]; then
            printf '%s\\n' aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
          else
            printf '%s\\n' bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
          fi
          ;;
        *) printf '\\n' ;;
      esac
      ;;
    *) exit 9 ;;
  esac
  exit 0
fi
if [ "${1:-}" = --no-ask-password ] && [ "${2:-}" = restart ]; then
  printf '%s\\n' 'restart lakatotree.service' >> "$SYSTEMD_TEST_LOG"
  case "$SYSTEMD_TEST_RESTART_MODE" in
    success)
      install_new_process
      retire_old_process
      printf '%s\\n' new > "$SYSTEMD_TEST_STATE"
      exit 0
      ;;
    fail_unchanged) exit 1 ;;
    fail_changed)
      install_new_process
      retire_old_process
      printf '%s\\n' new > "$SYSTEMD_TEST_STATE"
      exit 1
      ;;
    *) exit 9 ;;
  esac
fi
if [ "${1:-}" = --no-ask-password ] && [ "${2:-}" = stop ]; then
  printf '%s\\n' 'stop lakatotree.service' >> "$SYSTEMD_TEST_LOG"
  if [ "$SYSTEMD_TEST_STOP_MODE" = success ]; then
    printf '%s\\n' stopped > "$SYSTEMD_TEST_STATE"
    exit 0
  fi
  exit 1
fi
exit 9
""",
    )
    _write_executable(
        fake_bin / "ss",
        """#!/bin/sh
state=$(tr -d '\\n' < "$SYSTEMD_TEST_STATE")
case "$state" in
  old)
    if [ -e "$SYSTEMD_TEST_LISTENER_DRIFT" ]; then pid=$SYSTEMD_TEST_LISTENER_OTHER; else pid=$SYSTEMD_TEST_LISTENER_OLD; fi
    ;;
  new)
    if [ "$SYSTEMD_TEST_POST_LISTENER_MATCHES" = 1 ]; then pid=$SYSTEMD_TEST_MAIN_NEW; else pid=$SYSTEMD_TEST_LISTENER_OTHER; fi
    ;;
  *) pid= ;;
esac
[ -n "$pid" ] && printf 'LISTEN :55170 users:((python,pid=%s,fd=3))\\n' "$pid"
""",
    )
    _write_executable(
        fake_bin / "grep",
        """#!/bin/sh
if [ "${1:-}" = '-oP' ]; then
  sed -n 's/.*pid=\\([0-9][0-9]*\\).*/\\1/p'
else
  exec /usr/bin/grep "$@"
fi
""",
    )
    _write_executable(
        fake_bin / "curl",
        """#!/bin/sh
for argument do url=$argument; done
case "$url" in
  */healthz)
    if [ "$SYSTEMD_TEST_HEALTH_MODE" = ready ]; then
      printf '%s\\n' '{"neo4j":"ok","mongo":"ok"}'
    else
      printf '%s\\n' '{"neo4j":"down","mongo":"ok"}'
    fi
    ;;
  */version)
    if [ "$SYSTEMD_TEST_VERSION_MODE" = valid ]; then
      printf '{"disk_git_sha":"%s","boot_git_sha":"%s","identity_verified":true,"stale":false}\\n' "$SYSTEMD_TEST_SHA" "$SYSTEMD_TEST_SHA"
    else
      printf '{"disk_git_sha":"bad","boot_git_sha":"bad","identity_verified":false,"stale":true}\\n'
    fi
    ;;
  *) exit 22 ;;
esac
""",
    )
    _write_executable(fake_bin / "sleep", "#!/bin/sh\nexit 0\n")
    _write_executable(
        fake_bin / "nohup",
        "#!/bin/sh\nprintf called > \"$SYSTEMD_TEST_NOHUP\"\nexit 97\n",
    )

    interpreter = Path(sys.executable).resolve()
    verifier_stub = tmp_path / "verifier-python"
    auth_counter = tmp_path / "auth-counter"
    listener_drift = tmp_path / "listener-drift"
    static_drift = tmp_path / "static-drift"
    _write_executable(
        verifier_stub,
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = '-m' ] && [ \"${2:-}\" = 'server.auth_posture' ]; then\n"
        "  count=0\n"
        "  [ ! -f \"$SYSTEMD_TEST_AUTH_COUNTER\" ] || count=$(tr -d '\\n' < \"$SYSTEMD_TEST_AUTH_COUNTER\")\n"
        "  count=$((count + 1))\n"
        "  printf '%s\\n' \"$count\" > \"$SYSTEMD_TEST_AUTH_COUNTER\"\n"
        "  if [ \"$count\" = 2 ]; then\n"
        "    case \"$SYSTEMD_TEST_AUTH_MUTATION\" in\n"
        "      listener) : > \"$SYSTEMD_TEST_LISTENER_DRIFT\" ;;\n"
        "      static) : > \"$SYSTEMD_TEST_STATIC_DRIFT\" ;;\n"
        "      env) printf '%s\\n' '# concurrent drift' >> \"$SYSTEMD_TEST_ENV\" ;;\n"
        "    esac\n"
        "  fi\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"${1:-}\" = '-m' ] && [ \"${2:-}\" = 'server.storage_access_verify' ]; then exit 0; fi\n"
        f"exec {shlex.quote(str(interpreter))} \"$@\"\n",
    )

    proc_root = tmp_path / "proc"
    if initial_state == "old":
        _write_fake_process(
            proc_root, old_pid, python_bin=verifier_stub, start_time="12345"
        )
    else:
        proc_root.mkdir()
    pending_proc_root = tmp_path / "pending-proc"
    pending_proc_root.mkdir()
    retired_proc_root = tmp_path / "retired-proc"
    retired_proc_root.mkdir()
    _write_fake_process(
        pending_proc_root,
        new_pid,
        python_bin=verifier_stub,
        start_time=new_start_time,
    )
    if initial_state == "old" and not listener_matches:
        _write_fake_process(
            proc_root,
            listener_old_pid,
            python_bin=verifier_stub,
            start_time="34567",
        )

    env_file = tmp_path / "server.env"
    env_file.write_text(
        "NEO4J_URI=bolt://example.invalid\n"
        "NEO4J_DATABASE=neo4j\n"
        "NEO4J_USER=neo4j\n"
        "NEO4J_PASSWORD=canonical\n"
        "LAKATOS_MONGO_URI=mongodb://example.invalid\n"
        "LAKATOS_BIND_HOST=0.0.0.0\n"
        "WEB_CONCURRENCY=1\n"
        "UVICORN_WORKERS=1\n"
        f"LAKATOS_PYTHON={verifier_stub}\n",
        encoding="utf-8",
    )
    env_file.chmod(0o600)
    source_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "LAKATOS_SERVER_ENV": str(env_file),
        "LAKATOS_PROC_ROOT": str(proc_root),
        "SYSTEMD_TEST_STATE": str(state_file),
        "SYSTEMD_TEST_PROC": str(proc_root),
        "SYSTEMD_TEST_PENDING_PROC": str(pending_proc_root),
        "SYSTEMD_TEST_RETIRED_PROC": str(retired_proc_root),
        "SYSTEMD_TEST_LOG": str(systemctl_log),
        "SYSTEMD_TEST_NOHUP": str(nohup_marker),
        "SYSTEMD_TEST_ROOT": str(ROOT),
        "SYSTEMD_TEST_ENV": str(env_file),
        "SYSTEMD_TEST_PYTHON": str(verifier_stub),
        "SYSTEMD_TEST_MAIN_OLD": old_pid,
        "SYSTEMD_TEST_LISTENER_OLD": listener_old_pid,
        "SYSTEMD_TEST_MAIN_NEW": new_pid,
        "SYSTEMD_TEST_LISTENER_OTHER": "90000998",
        "SYSTEMD_TEST_SHA": source_sha,
        "SYSTEMD_TEST_RESTART_MODE": restart_mode,
        "SYSTEMD_TEST_HEALTH_MODE": health_mode,
        "SYSTEMD_TEST_VERSION_MODE": version_mode,
        "SYSTEMD_TEST_STOP_MODE": stop_mode,
        "SYSTEMD_TEST_AUTH_COUNTER": str(auth_counter),
        "SYSTEMD_TEST_AUTH_MUTATION": auth_mutation,
        "SYSTEMD_TEST_LISTENER_DRIFT": str(listener_drift),
        "SYSTEMD_TEST_STATIC_DRIFT": str(static_drift),
        "SYSTEMD_TEST_POST_INVOCATION": post_invocation,
        "SYSTEMD_TEST_POST_LISTENER_MATCHES": "1" if post_listener_matches else "0",
    }
    return env, state_file, systemctl_log, nohup_marker, env_file


def test_restart_gate_uses_core_healthz_not_full_traffic_readiness():
    script = (ROOT / "scripts/dev_server_restart.sh").read_text(encoding="utf-8")
    probe_lines = [line for line in script.splitlines() if "curl" in line]
    assert any("/healthz" in line and "-sf" in line for line in probe_lines)
    assert all("/readyz" not in line for line in probe_lines)


def test_restart_launcher_rejects_multiworker_cache_split():
    script = (ROOT / "scripts/dev_server_restart.sh").read_text(encoding="utf-8")
    assert '[ "${WEB_CONCURRENCY:-1}" != "1" ]' in script
    assert '[ "${UVICORN_WORKERS:-1}" != "1" ]' in script
    assert "export WEB_CONCURRENCY=1" in script
    assert "export UVICORN_WORKERS=1" in script
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
    access = script.index('-m server.storage_access_verify')
    old_pid_lookup = script.index('PID="$(listener_pid)"')
    assert sourced < posture < access < old_pid_lookup
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


def test_loaded_systemd_unit_is_the_only_restart_authority():
    script = (ROOT / "scripts/dev_server_restart.sh").read_text(encoding="utf-8")
    managed = script.index('if [ "$SYSTEMD_LOAD_STATE" = "loaded" ]')
    restart = script.index('restart "$SYSTEMD_UNIT"', managed)
    managed_exit = script.index("exit 0", restart)
    manual_kill = script.index('kill -TERM "$PID"', managed_exit)
    manual_nohup = script.index('nohup "$PYTHON_BIN"', manual_kill)
    assert managed < restart < managed_exit < manual_kill < manual_nohup
    assert 'SYSTEMD_UNIT="lakatotree.service"' in script
    assert "direct/nohup fallback" in script


def test_systemd_owned_listener_restarts_exact_unit_without_term_or_nohup(tmp_path):
    env, state_file, systemctl_log, nohup_marker, env_file = (
        _systemd_restart_fixture(tmp_path)
    )
    completed = subprocess.run(
        ["bash", "scripts/dev_server_restart.sh"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    assert "systemd core healthz ready" in completed.stdout
    assert state_file.read_text(encoding="utf-8").strip() == "new"
    assert systemctl_log.read_text(encoding="utf-8").splitlines() == [
        "restart lakatotree.service"
    ]
    assert not nohup_marker.exists()
    assert Path(f"{env_file}.lastboot").exists()
    assert (Path(env["LAKATOS_PROC_ROOT"]) / env["SYSTEMD_TEST_MAIN_NEW"]).is_dir()
    assert not (Path(env["LAKATOS_PROC_ROOT"]) / env["SYSTEMD_TEST_MAIN_OLD"]).exists()


def test_loaded_inactive_never_started_unit_still_uses_systemd(tmp_path):
    env, state_file, systemctl_log, nohup_marker, env_file = (
        _systemd_restart_fixture(tmp_path, initial_state="inactive")
    )
    completed = subprocess.run(
        ["bash", "scripts/dev_server_restart.sh"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    assert state_file.read_text(encoding="utf-8").strip() == "new"
    assert systemctl_log.read_text(encoding="utf-8").splitlines() == [
        "restart lakatotree.service"
    ]
    assert not nohup_marker.exists()
    assert not Path(f"{env_file}.lastboot").exists()


def test_failed_restart_preserves_exact_unchanged_healthy_invocation(tmp_path):
    env, state_file, systemctl_log, nohup_marker, _ = _systemd_restart_fixture(
        tmp_path, restart_mode="fail_unchanged"
    )
    completed = subprocess.run(
        ["bash", "scripts/dev_server_restart.sh"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 1
    assert "기존 systemd invocation" in completed.stderr
    assert state_file.read_text(encoding="utf-8").strip() == "old"
    assert systemctl_log.read_text(encoding="utf-8").splitlines() == [
        "restart lakatotree.service"
    ]
    assert not nohup_marker.exists()


def test_failed_restart_after_state_change_stops_and_proves_no_listener(tmp_path):
    env, state_file, systemctl_log, nohup_marker, _ = _systemd_restart_fixture(
        tmp_path, restart_mode="fail_changed"
    )
    completed = subprocess.run(
        ["bash", "scripts/dev_server_restart.sh"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 1
    assert state_file.read_text(encoding="utf-8").strip() == "stopped"
    assert systemctl_log.read_text(encoding="utf-8").splitlines() == [
        "restart lakatotree.service",
        "stop lakatotree.service",
    ]
    assert not nohup_marker.exists()


def test_degraded_post_restart_health_stops_managed_unit(tmp_path):
    env, state_file, systemctl_log, nohup_marker, _ = _systemd_restart_fixture(
        tmp_path, health_mode="degraded"
    )
    completed = subprocess.run(
        ["bash", "scripts/dev_server_restart.sh"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 1
    assert "수렴하지 않음" in completed.stderr
    assert state_file.read_text(encoding="utf-8").strip() == "stopped"
    assert systemctl_log.read_text(encoding="utf-8").splitlines() == [
        "restart lakatotree.service",
        "stop lakatotree.service",
    ]
    assert not nohup_marker.exists()


def test_failed_emergency_stop_is_reported_without_unmanaged_fallback(tmp_path):
    env, state_file, systemctl_log, nohup_marker, _ = _systemd_restart_fixture(
        tmp_path, health_mode="degraded", stop_mode="fail"
    )
    completed = subprocess.run(
        ["bash", "scripts/dev_server_restart.sh"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 3
    assert "중대 실패" in completed.stderr
    assert state_file.read_text(encoding="utf-8").strip() == "new"
    assert systemctl_log.read_text(encoding="utf-8").splitlines() == [
        "restart lakatotree.service",
        "stop lakatotree.service",
    ]
    assert not nohup_marker.exists()


def test_auth_window_listener_drift_refuses_before_restart(tmp_path):
    env, state_file, systemctl_log, nohup_marker, _ = _systemd_restart_fixture(
        tmp_path, auth_mutation="listener"
    )
    completed = subprocess.run(
        ["bash", "scripts/dev_server_restart.sh"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 2
    assert "restart 직전 바뀌었다" in completed.stderr
    assert state_file.read_text(encoding="utf-8").strip() == "old"
    assert not systemctl_log.exists()
    assert not nohup_marker.exists()


def test_auth_window_static_unit_drift_refuses_before_restart(tmp_path):
    env, state_file, systemctl_log, nohup_marker, _ = _systemd_restart_fixture(
        tmp_path, auth_mutation="static"
    )
    completed = subprocess.run(
        ["bash", "scripts/dev_server_restart.sh"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 2
    assert "restart 직전 바뀌었다" in completed.stderr
    assert state_file.read_text(encoding="utf-8").strip() == "old"
    assert not systemctl_log.exists()
    assert not nohup_marker.exists()


def test_auth_window_canonical_env_drift_refuses_before_restart(tmp_path):
    env, state_file, systemctl_log, nohup_marker, _ = _systemd_restart_fixture(
        tmp_path, auth_mutation="env"
    )
    completed = subprocess.run(
        ["bash", "scripts/dev_server_restart.sh"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 2
    assert "restart 직전 바뀌었다" in completed.stderr
    assert state_file.read_text(encoding="utf-8").strip() == "old"
    assert not systemctl_log.exists()
    assert not nohup_marker.exists()


def test_invalid_version_identity_stops_managed_unit(tmp_path):
    env, state_file, systemctl_log, nohup_marker, _ = _systemd_restart_fixture(
        tmp_path, version_mode="invalid"
    )
    completed = subprocess.run(
        ["bash", "scripts/dev_server_restart.sh"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 1
    assert state_file.read_text(encoding="utf-8").strip() == "stopped"
    assert systemctl_log.read_text(encoding="utf-8").splitlines() == [
        "restart lakatotree.service",
        "stop lakatotree.service",
    ]
    assert not nohup_marker.exists()


def test_unchanged_post_restart_invocation_is_stopped(tmp_path):
    env, state_file, systemctl_log, nohup_marker, _ = _systemd_restart_fixture(
        tmp_path, post_invocation="old"
    )
    completed = subprocess.run(
        ["bash", "scripts/dev_server_restart.sh"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 1
    assert state_file.read_text(encoding="utf-8").strip() == "stopped"
    assert systemctl_log.read_text(encoding="utf-8").splitlines() == [
        "restart lakatotree.service",
        "stop lakatotree.service",
    ]
    assert not nohup_marker.exists()


def test_post_restart_listener_mismatch_is_stopped(tmp_path):
    env, state_file, systemctl_log, nohup_marker, _ = _systemd_restart_fixture(
        tmp_path, post_listener_matches=False
    )
    completed = subprocess.run(
        ["bash", "scripts/dev_server_restart.sh"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 1
    assert state_file.read_text(encoding="utf-8").strip() == "stopped"
    assert systemctl_log.read_text(encoding="utf-8").splitlines() == [
        "restart lakatotree.service",
        "stop lakatotree.service",
    ]
    assert not nohup_marker.exists()


def test_nonpositive_post_restart_start_time_is_stopped(tmp_path):
    env, state_file, systemctl_log, nohup_marker, _ = _systemd_restart_fixture(
        tmp_path, new_start_time="0"
    )
    completed = subprocess.run(
        ["bash", "scripts/dev_server_restart.sh"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 1
    assert state_file.read_text(encoding="utf-8").strip() == "stopped"
    assert systemctl_log.read_text(encoding="utf-8").splitlines() == [
        "restart lakatotree.service",
        "stop lakatotree.service",
    ]
    assert not nohup_marker.exists()


def test_systemd_mainpid_listener_mismatch_refuses_before_effect(tmp_path):
    env, state_file, systemctl_log, nohup_marker, _ = _systemd_restart_fixture(
        tmp_path, listener_matches=False
    )
    completed = subprocess.run(
        ["bash", "scripts/dev_server_restart.sh"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 2
    assert "MainPID" in completed.stderr
    assert state_file.read_text(encoding="utf-8").strip() == "old"
    assert not systemctl_log.exists()
    assert not nohup_marker.exists()


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
    fake_systemctl = fake_bin / "systemctl"
    fake_systemctl.write_text(
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = show ] && [ \"${3:-}\" = --property=LoadState ]; then\n"
        "  printf '%s\\n' not-found\n"
        "  exit 0\n"
        "fi\n"
        "exit 9\n",
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)

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
    verifier_stub = tmp_path / "verifier-python"
    verifier_stub.write_text(
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = '-m' ] && "
        "[ \"${2:-}\" = 'server.storage_access_verify' ]; then exit 0; fi\n"
        f"exec {shlex.quote(str(interpreter))} \"$@\"\n",
        encoding="utf-8",
    )
    verifier_stub.chmod(0o755)
    (environ_dir / "cwd").symlink_to(ROOT, target_is_directory=True)
    (environ_dir / "exe").symlink_to(verifier_stub)
    env_file = tmp_path / "server.env"
    env_file.write_text(
        "NEO4J_URI=bolt://example.invalid\n"
        "NEO4J_DATABASE=neo4j\n"
        "NEO4J_USER=neo4j\n"
        "NEO4J_PASSWORD=canonical\n"
        "LAKATOS_MONGO_URI=mongodb://example.invalid\n"
        f"LAKATOS_PYTHON={verifier_stub}\n",
        encoding="utf-8",
    )
    env_file.chmod(0o600)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "LAKATOS_PYTHON": str(verifier_stub),
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
