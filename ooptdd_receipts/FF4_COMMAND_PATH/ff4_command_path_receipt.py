"""Executable ooptdd receipt for FF4 command-like judge-script path totality."""
from __future__ import annotations

import errno
import os
from pathlib import Path
import sys
import tempfile

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from server.contexts.tree.judgement_service import isolate_script_file  # noqa: E402


def _event(cid: str, name: str, **attrs):
    return {
        "cid": cid,
        "correlation_id": cid,
        "cycle_id": cid,
        "service": "server.contexts.tree.judgement_service",
        "event": name,
        **attrs,
    }


def verify(backend, cid):
    command_like = "python -c '" + ("print(1);" * 64) + "'"
    resolved, info = isolate_script_file(command_like)
    assert resolved is None and info.get("reason") == "unresolvable", info
    if os.environ.get("LAKATO_FF4_SUPPRESS_REJECTION_EVENT") != "1":
        backend.ship([_event(cid, "oversized_command_path_rejected", reason=info["reason"])])

    with tempfile.NamedTemporaryFile("w", suffix="_judge.py", delete=False) as handle:
        handle.write("print('metric=0.5')\n")
        normal = Path(handle.name)
    try:
        accepted, accepted_info = isolate_script_file(str(normal))
        assert accepted == normal.resolve() and accepted_info == {}, accepted_info
        backend.ship([_event(cid, "normal_script_path_preserved", path_kind="temp_script")])
    finally:
        normal.unlink(missing_ok=True)

    path_type = type(Path())
    original_is_file = path_type.is_file

    def _raise_name_too_long(_self, *args, **kwargs):
        raise OSError(errno.ENAMETOOLONG, "injected filename too long")

    try:
        path_type.is_file = _raise_name_too_long
        injected, injected_info = isolate_script_file("judge.py")
    finally:
        path_type.is_file = original_is_file
    assert injected is None and injected_info.get("reason") == "unresolvable", injected_info
    backend.ship([_event(cid, "filename_too_long_fault_contained", reason=injected_info["reason"])])
