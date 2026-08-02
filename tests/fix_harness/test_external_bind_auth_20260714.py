"""외부 listener는 인증을 fail-closed하고, loopback open 개발 결정은 보존한다."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from server import auth_posture
from server.auth_posture import require_safe_bind, validate_listener_args

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.0.12", "lakatotree.internal"])
def test_external_bind_without_token_is_rejected(host):
    with pytest.raises(ValueError, match="LAKATOS_API_TOKEN"):
        require_safe_bind(host, None)


@pytest.mark.parametrize("host", ["127.0.0.1", "127.9.8.7", "::1", "localhost"])
def test_loopback_bind_without_token_is_allowed(host):
    assert require_safe_bind(host, None) == host


def test_bracketed_ipv6_is_rejected_as_non_runnable_uvicorn_host():
    with pytest.raises(ValueError, match="대괄호 없는 IPv6"):
        require_safe_bind("[::1]", None)


def test_external_bind_with_nonempty_token_is_allowed():
    assert require_safe_bind("0.0.0.0", "secret") == "0.0.0.0"
    with pytest.raises(ValueError):
        require_safe_bind("0.0.0.0", "   ")


@pytest.mark.parametrize("args", [
    ["--host", "0.0.0.0"], ["--host=0.0.0.0"], ["--fd", "3"], ["--fd=3"],
    ["--uds", "/tmp/lakatotree.sock"], ["--uds=/tmp/lakatotree.sock"],
])
def test_listener_override_arguments_are_rejected(args):
    with pytest.raises(ValueError, match="listener"):
        validate_listener_args(args)


@pytest.mark.parametrize("env", [
    {"UVICORN_FD": "9"},
    {"UVICORN_UDS": "/tmp/lakatotree.sock"},
])
def test_listener_override_environment_is_rejected(env):
    with pytest.raises(ValueError, match="listener override 환경변수"):
        auth_posture.validate_listener_env(env)


def _run_launcher(path: str, *args: str,
                  env_overrides: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""),
           "PYTHONPATH": str(ROOT), "LAKATOS_BIND_HOST": "0.0.0.0",
           "LAKATOS_ENV_FILE": str(ROOT / ".missing-test-server.env"),
           # GitHub Actions installs into setup-python, not a repository .venv. Security posture
           # must be checked before the durable server interpreter requirement in either layout.
           "LAKATOS_PYTHON": str(ROOT / ".missing-ci-venv" / "bin" / "python")}
    env.update(env_overrides or {})
    return subprocess.run(["bash", path, *args], cwd=ROOT, env=env,
                          capture_output=True, text=True, check=False, timeout=5)


def test_both_launchers_reject_external_open_before_touching_dependencies():
    for launcher in ("server/run.sh", "server/run_internal.sh"):
        proc = _run_launcher(launcher)
        assert proc.returncode == 2, (launcher, proc.stdout, proc.stderr)
        assert "LAKATOS_API_TOKEN" in proc.stderr


def test_both_launchers_accept_external_token_before_enforcing_server_interpreter():
    for launcher in ("server/run.sh", "server/run_internal.sh"):
        proc = _run_launcher(launcher, env_overrides={"LAKATOS_API_TOKEN": "secret"})
        assert proc.returncode == 2, (launcher, proc.stdout, proc.stderr)
        assert "Python venv 없음" in proc.stderr
        assert "외부 bind에는 LAKATOS_API_TOKEN" not in proc.stderr


def test_launchers_reject_listener_override_and_have_no_fallback_credentials():
    for launcher in ("server/run.sh", "server/run_internal.sh"):
        src = (ROOT / launcher).read_text(encoding="utf-8")
        assert "LAKATOS_BIND_HOST" in src and "server.auth_posture" in src
        assert src.count("-m server.auth_posture") >= 2, \
            f"{launcher}: env source 뒤 definitive preflight 없음"
        proc = _run_launcher(launcher, "--fd", "3")
        assert proc.returncode == 2
    internal = (ROOT / "server/run_internal.sh").read_text(encoding="utf-8")
    assert 'NEO4J_PASSWORD="${NEO4J_PASSWORD:-' not in internal
    assert 'LAKATOS_MONGO_URI="${LAKATOS_MONGO_URI:-' not in internal
    public = (ROOT / "server/run.sh").read_text(encoding="utf-8")
    assert "set -euo pipefail" in public
    assert 'eval "$(' not in public
    assert "docker exec postgresql" not in public
    assert ".claude/settings.json" not in public


@pytest.mark.parametrize("name,value", [
    ("UVICORN_FD", "9"),
    ("UVICORN_UDS", "/tmp/lakatotree.sock"),
])
def test_both_launchers_reject_uvicorn_listener_env_before_dependencies(name, value):
    for launcher in ("server/run.sh", "server/run_internal.sh"):
        proc = _run_launcher(
            launcher,
            env_overrides={"LAKATOS_BIND_HOST": "127.0.0.1", name: value},
        )
        assert proc.returncode == 2, (launcher, name, proc.stdout, proc.stderr)
        assert name in proc.stderr and "listener override" in proc.stderr


def test_internal_launcher_revalidates_env_file_listener_override(tmp_path):
    env_file = tmp_path / "server.env"
    env_file.write_text(
        "NEO4J_URI=bolt://example.invalid\n"
        "NEO4J_DATABASE=neo4j\n"
        "NEO4J_USER=neo4j\n"
        "NEO4J_PASSWORD=test\n"
        "LAKATOS_MONGO_URI=mongodb://example.invalid\n"
        "UVICORN_FD=9\n",
        encoding="utf-8",
    )
    env_file.chmod(0o600)
    proc = _run_launcher(
        "server/run_internal.sh",
        env_overrides={
            "LAKATOS_BIND_HOST": "127.0.0.1",
            "LAKATOS_ENV_FILE": str(env_file),
            "LAKATOS_PYTHON": sys.executable,
        },
    )
    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    assert "UVICORN_FD" in proc.stderr and "listener override" in proc.stderr


def test_internal_launcher_revalidates_token_after_env_file(tmp_path):
    env_file = tmp_path / "server.env"
    env_file.write_text(
        "NEO4J_URI=bolt://example.invalid\n"
        "NEO4J_DATABASE=neo4j\n"
        "NEO4J_USER=neo4j\n"
        "NEO4J_PASSWORD=test\n"
        "LAKATOS_MONGO_URI=mongodb://example.invalid\n"
        "LAKATOS_API_TOKEN=\n",
        encoding="utf-8",
    )
    env_file.chmod(0o600)
    proc = _run_launcher(
        "server/run_internal.sh",
        env_overrides={
            "LAKATOS_BIND_HOST": "0.0.0.0",
            "LAKATOS_API_TOKEN": "outer-token",
            "LAKATOS_ENV_FILE": str(env_file),
        },
    )
    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    assert "LAKATOS_API_TOKEN" in proc.stderr


def test_internal_launcher_uses_canonical_env_bind_for_both_checks_and_exec(
    tmp_path
):
    trace = tmp_path / "python-argv.log"
    fake_python = tmp_path / "fake-python"
    fake_python.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" >> \"$TRACE_FILE\"\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    env_file = tmp_path / "server.env"
    env_file.write_text(
        f"LAKATOS_PYTHON={fake_python}\n"
        "LAKATOS_BIND_HOST=0.0.0.0\n"
        "LAKATOS_API_TOKEN=canonical-token\n"
        "NEO4J_URI=bolt://example.invalid\n"
        "NEO4J_DATABASE=neo4j\n"
        "NEO4J_USER=neo4j\n"
        "NEO4J_PASSWORD=test\n"
        "LAKATOS_MONGO_URI=mongodb://example.invalid\n",
        encoding="utf-8",
    )
    env_file.chmod(0o600)

    proc = _run_launcher(
        "server/run_internal.sh",
        env_overrides={
            "LAKATOS_BIND_HOST": "127.0.0.1",
            "LAKATOS_ENV_FILE": str(env_file),
            "TRACE_FILE": str(trace),
        },
    )

    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    calls = trace.read_text(encoding="utf-8").splitlines()
    assert calls[:2] == [
        "-m server.auth_posture 0.0.0.0",
        "-m server.auth_posture 0.0.0.0",
    ]
    assert calls[2] == (
        "-m uvicorn --app-dir server app:app --host 0.0.0.0 --port 55170 --workers 1"
    )


@pytest.mark.parametrize("launcher", ["server/run.sh", "server/run_internal.sh"])
def test_runtime_launchers_reject_migration_credentials(tmp_path, launcher):
    env_file = tmp_path / "server.env"
    env_file.write_text(
        "NEO4J_URI=bolt://example.invalid\n"
        "NEO4J_DATABASE=neo4j\n"
        "NEO4J_USER=runtime\n"
        "NEO4J_PASSWORD=runtime-secret\n"
        "LAKATOS_MONGO_URI=mongodb://example.invalid\n"
        "LAKATOS_STORAGE_NEO4J_MIGRATION_PASSWORD=must-not-leak\n",
        encoding="utf-8",
    )
    env_file.chmod(0o600)

    proc = _run_launcher(
        launcher,
        env_overrides={
            "LAKATOS_BIND_HOST": "127.0.0.1",
            "LAKATOS_ENV_FILE": str(env_file),
            "LAKATOS_PYTHON": sys.executable,
        },
    )

    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    assert "migration credential" in proc.stderr
    assert "must-not-leak" not in proc.stderr


@pytest.mark.parametrize("launcher", ["server/run.sh", "server/run_internal.sh"])
def test_launchers_never_source_world_readable_or_symlink_env(tmp_path, launcher):
    env_file = tmp_path / "server.env"
    env_file.write_text("LAKATOS_API_TOKEN=secret\n", encoding="utf-8")
    env_file.chmod(0o644)
    insecure = _run_launcher(
        launcher,
        env_overrides={
            "LAKATOS_BIND_HOST": "127.0.0.1",
            "LAKATOS_ENV_FILE": str(env_file),
            "LAKATOS_PYTHON": sys.executable,
        },
    )
    assert insecure.returncode == 2
    assert "0600" in insecure.stderr

    env_file.chmod(0o600)
    link = tmp_path / "linked.env"
    link.symlink_to(env_file)
    symlinked = _run_launcher(
        launcher,
        env_overrides={
            "LAKATOS_BIND_HOST": "127.0.0.1",
            "LAKATOS_ENV_FILE": str(link),
            "LAKATOS_PYTHON": sys.executable,
        },
    )
    assert symlinked.returncode == 2
    assert "symlink" in symlinked.stderr


GUARD_DEFECT = test_external_bind_without_token_is_rejected.__name__
GUARD_MECHANISM = test_loopback_bind_without_token_is_allowed.__name__
