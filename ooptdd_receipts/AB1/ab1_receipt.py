"""AB1 emit-adapter — 외부 bind 인증과 listener 우회 차단을 실 정책 함수로 검증한다."""
from __future__ import annotations

import contextlib
import io
import os
import sys
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from server import auth_posture as auth  # noqa: E402


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.AB1", "event": name, **attrs}


def _rejected(host: str) -> bool:
    try:
        auth.require_safe_bind(host, None)
    except ValueError:
        return True
    return False


def verify(backend, cid):
    external = ("0.0.0.0", "::", "192.168.0.12", "lakatotree.internal")
    assert all(_rejected(host) for host in external)
    backend.ship([_ev(cid, "external_bind_requires_token", rejected=list(external))])

    loopback = ("127.0.0.1", "127.9.8.7", "::1", "localhost")
    assert all(auth.require_safe_bind(host, None) == host for host in loopback)
    assert auth.require_safe_bind("0.0.0.0", "token") == "0.0.0.0"
    backend.ship([_ev(cid, "safe_bind_paths_preserved", loopback=list(loopback))])

    with patch.dict(os.environ, {}, clear=True), contextlib.redirect_stderr(io.StringIO()):
        assert auth._launcher_main(["127.0.0.1", "--fd", "3"]) == 2
        with patch.object(auth, "validate_listener_args", lambda args: None):
            assert auth._launcher_main(["127.0.0.1", "--fd", "3"]) == 0
    with patch.dict(os.environ, {"UVICORN_FD": "9"}, clear=True), \
            contextlib.redirect_stderr(io.StringIO()):
        assert auth._launcher_main(["127.0.0.1"]) == 2
        with patch.object(auth, "validate_listener_env", lambda environ=None: None):
            assert auth._launcher_main(["127.0.0.1"]) == 0
    backend.ship([_ev(cid, "listener_override_negative_oracle",
                      cli_and_env_validator_removal_opens_listener=True)])
