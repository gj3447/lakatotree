"""Server-owned, content-addressed inputs for producer replay.

Replay authority must not depend on a path that a submitter can rewrite while the
scorer is running.  The write boundary therefore copies the already-hashed script
and result into a private cache, executes those copies, and seals their canonical
paths in the receipt/MeasurementLock.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
from pathlib import Path


class ReplayArtifactError(RuntimeError):
    """A replay input could not be materialised as a private immutable snapshot."""


def replay_cache_root() -> Path:
    configured = (os.environ.get("LAKATOS_REPLAY_CACHE_ROOT") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    state = (os.environ.get("XDG_STATE_HOME") or "").strip()
    base = Path(state).expanduser() if state else Path.home() / ".local" / "state"
    return (base / "lakatotree" / "replay-artifacts" / "v1").resolve()


def _safe_suffix(source_path: str, kind: str) -> str:
    if kind == "script":
        return ".py"
    suffix = Path(source_path).suffix.lower()
    return suffix if re.fullmatch(r"\.[a-z0-9]{1,12}", suffix or "") else ".bin"


def snapshot_path(*, kind: str, sha256: str, source_path: str) -> Path:
    if kind not in {"script", "result"}:
        raise ReplayArtifactError(f"unknown replay artifact kind: {kind}")
    if not re.fullmatch(r"[0-9a-f]{64}", sha256 or ""):
        raise ReplayArtifactError("snapshot sha256 must be canonical lower-case hex")
    return replay_cache_root() / kind / f"{sha256}{_safe_suffix(source_path, kind)}"


def _ensure_private_dir(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        st = path.lstat()
    except OSError as exc:
        raise ReplayArtifactError(f"snapshot directory unavailable: {path}") from exc
    if not stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode):
        raise ReplayArtifactError(f"snapshot directory is not a real directory: {path}")
    if hasattr(os, "getuid") and st.st_uid != os.getuid():
        raise ReplayArtifactError(f"snapshot directory owner mismatch: {path}")
    if st.st_mode & 0o077:
        try:
            path.chmod(0o700)
            st = path.lstat()
        except OSError as exc:
            raise ReplayArtifactError(f"snapshot directory is not private: {path}") from exc
        if st.st_mode & 0o077:
            raise ReplayArtifactError(f"snapshot directory is group/world accessible: {path}")


def _read_exact(source: Path, expected_sha256: str, max_bytes: int) -> bytes:
    try:
        with source.open("rb") as stream:
            body = stream.read(max_bytes + 1)
    except OSError as exc:
        raise ReplayArtifactError(f"snapshot source read failed: {source}") from exc
    if len(body) > max_bytes:
        raise ReplayArtifactError(f"snapshot source exceeds {max_bytes} bytes: {source}")
    actual = hashlib.sha256(body).hexdigest()
    if actual != expected_sha256:
        raise ReplayArtifactError(
            f"snapshot source changed before copy: expected {expected_sha256}, got {actual}")
    return body


def _valid_existing(path: Path, expected_sha256: str, max_bytes: int) -> bool:
    try:
        st = path.lstat()
        if not stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode):
            return False
        if hasattr(os, "getuid") and st.st_uid != os.getuid():
            return False
        if st.st_mode & 0o222 or st.st_size > max_bytes:
            return False
        with path.open("rb") as stream:
            return hashlib.sha256(stream.read(max_bytes + 1)).hexdigest() == expected_sha256
    except OSError:
        return False


def materialize_snapshot(*, source_path: str, expected_sha256: str,
                         kind: str, max_bytes: int) -> str:
    """Atomically copy an exact input into the private content-addressed cache.

    The returned file is owner-readable and not writable.  Existing cache entries
    are reused only after type, owner, mode, size, and content verification.
    """
    source = Path(source_path).resolve(strict=True)
    body = _read_exact(source, expected_sha256, max_bytes)
    destination = snapshot_path(kind=kind, sha256=expected_sha256, source_path=str(source))
    _ensure_private_dir(replay_cache_root())
    _ensure_private_dir(destination.parent)
    if _valid_existing(destination, expected_sha256, max_bytes):
        return str(destination)

    fd, temporary = tempfile.mkstemp(prefix=".snapshot-", dir=str(destination.parent))
    try:
        os.fchmod(fd, 0o400)
        with os.fdopen(fd, "wb", closefd=True) as stream:
            fd = -1
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        destination.chmod(0o400)
    except OSError as exc:
        raise ReplayArtifactError(f"snapshot materialisation failed: {destination}") from exc
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            Path(temporary).unlink(missing_ok=True)
        except OSError:
            pass
    if not _valid_existing(destination, expected_sha256, max_bytes):
        raise ReplayArtifactError(f"snapshot verification failed: {destination}")
    return str(destination)
