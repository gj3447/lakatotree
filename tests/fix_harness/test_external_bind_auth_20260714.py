"""외부 listener는 인증을 fail-closed하고, loopback open 개발 결정은 보존한다."""
from __future__ import annotations

import os
import subprocess
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
           "PYTHONPATH": str(ROOT), "LAKATOS_BIND_HOST": "0.0.0.0"}
    env.update(env_overrides or {})
    return subprocess.run(["bash", path, *args], cwd=ROOT, env=env,
                          capture_output=True, text=True, check=False, timeout=5)


def test_both_launchers_reject_external_open_before_touching_dependencies():
    for launcher in ("server/run.sh", "server/run_internal.sh"):
        proc = _run_launcher(launcher)
        assert proc.returncode == 2, (launcher, proc.stdout, proc.stderr)
        assert "LAKATOS_API_TOKEN" in proc.stderr


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
        "NEO4J_USER=neo4j\n"
        "NEO4J_PASSWORD=test\n"
        "LAKATOS_MONGO_URI=mongodb://example.invalid\n"
        "UVICORN_FD=9\n",
        encoding="utf-8",
    )
    proc = _run_launcher(
        "server/run_internal.sh",
        env_overrides={
            "LAKATOS_BIND_HOST": "127.0.0.1",
            "LAKATOS_ENV_FILE": str(env_file),
        },
    )
    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    assert "UVICORN_FD" in proc.stderr and "listener override" in proc.stderr


def test_internal_launcher_revalidates_token_after_env_file(tmp_path):
    env_file = tmp_path / "server.env"
    env_file.write_text(
        "NEO4J_URI=bolt://example.invalid\n"
        "NEO4J_USER=neo4j\n"
        "NEO4J_PASSWORD=test\n"
        "LAKATOS_MONGO_URI=mongodb://example.invalid\n"
        "LAKATOS_API_TOKEN=\n",
        encoding="utf-8",
    )
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


GUARD_DEFECT = test_external_bind_without_token_is_rejected.__name__
GUARD_MECHANISM = test_loopback_bind_without_token_is_allowed.__name__
