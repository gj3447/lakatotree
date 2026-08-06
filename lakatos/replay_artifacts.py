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
import sys
import tempfile
from pathlib import Path, PurePosixPath


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


def read_portable_repo_file(
    *,
    repo_root: str | Path,
    relative_path: str,
    max_bytes: int,
) -> tuple[bytes, str]:
    """Read one repo-relative file without following any submitter-controlled symlink.

    A prior ``Path.resolve`` containment check is not sufficient: an attacker can replace a
    checked parent directory before the later source open.  This routine anchors traversal at an
    open repository directory and opens every component with ``O_NOFOLLOW``.  The returned bytes
    are the only bytes callers may publish into the private replay cache.
    """
    if not isinstance(relative_path, str) or not relative_path:
        raise ReplayArtifactError("portable source path is empty")
    if ('\x00' in relative_path or '\\' in relative_path or '::' in relative_path
            or relative_path.startswith('~')):
        raise ReplayArtifactError("portable source path has a forbidden spelling")
    if (len(relative_path) >= 2 and relative_path[0].isalpha()
            and relative_path[1] == ':'):
        raise ReplayArtifactError("portable source path has a drive prefix")
    try:
        portable = PurePosixPath(relative_path)
        parts = portable.parts
    except (OSError, ValueError) as exc:
        raise ReplayArtifactError("portable source path is invalid") from exc
    if (portable.is_absolute() or not parts or '..' in parts
            or portable.as_posix() != relative_path or relative_path == '.'):
        raise ReplayArtifactError("portable source path is not canonical repo-relative POSIX")

    nofollow = getattr(os, 'O_NOFOLLOW', None)
    directory = getattr(os, 'O_DIRECTORY', None)
    if nofollow is None or directory is None:
        raise ReplayArtifactError("fd-anchored portable reads are unavailable on this platform")
    cloexec = getattr(os, 'O_CLOEXEC', 0)
    directory_flags = os.O_RDONLY | directory | nofollow | cloexec
    file_flags = os.O_RDONLY | nofollow | cloexec
    opened: list[int] = []
    file_fd = -1
    try:
        root = Path(repo_root).resolve(strict=True)
        directory_fd = os.open(root, directory_flags)
        opened.append(directory_fd)
        for component in parts[:-1]:
            directory_fd = os.open(
                component, directory_flags, dir_fd=directory_fd
            )
            opened.append(directory_fd)
        file_fd = os.open(parts[-1], file_flags, dir_fd=directory_fd)
        st = os.fstat(file_fd)
        if not stat.S_ISREG(st.st_mode):
            raise ReplayArtifactError("portable source is not a regular file")
        if st.st_size > max_bytes:
            raise ReplayArtifactError(
                f"portable source exceeds {max_bytes} bytes"
            )
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(file_fd, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        body = b''.join(chunks)
        if len(body) > max_bytes:
            raise ReplayArtifactError(
                f"portable source exceeds {max_bytes} bytes"
            )
    except ReplayArtifactError:
        raise
    except (NotImplementedError, OSError, TypeError, ValueError) as exc:
        raise ReplayArtifactError("fd-anchored portable source read failed") from exc
    finally:
        active_error = sys.exc_info()[0] is not None
        close_error = None
        if file_fd >= 0:
            try:
                os.close(file_fd)
            except OSError as exc:
                close_error = exc
        for directory_fd in reversed(opened):
            try:
                os.close(directory_fd)
            except OSError as exc:
                if close_error is None:
                    close_error = exc
        if close_error is not None and not active_error:
            raise ReplayArtifactError("portable source fd close failed") from close_error
    return body, hashlib.sha256(body).hexdigest()


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


def materialize_snapshot_bytes(
    *,
    body: bytes,
    expected_sha256: str,
    kind: str,
    source_path: str,
    max_bytes: int,
) -> str:
    """Publish already captured bytes without reopening their submitter-owned source."""
    if not isinstance(body, bytes) or len(body) > max_bytes:
        raise ReplayArtifactError(f"snapshot source exceeds {max_bytes} bytes")
    actual = hashlib.sha256(body).hexdigest()
    if actual != expected_sha256:
        raise ReplayArtifactError(
            f"snapshot bytes mismatch: expected {expected_sha256}, got {actual}"
        )
    destination = snapshot_path(
        kind=kind, sha256=expected_sha256, source_path=source_path
    )
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


def materialize_snapshot(*, source_path: str, expected_sha256: str,
                         kind: str, max_bytes: int) -> str:
    """Atomically copy an exact input into the private content-addressed cache.

    The returned file is owner-readable and not writable.  Existing cache entries
    are reused only after type, owner, mode, size, and content verification.
    """
    source = Path(source_path).resolve(strict=True)
    body = _read_exact(source, expected_sha256, max_bytes)
    return materialize_snapshot_bytes(
        body=body,
        expected_sha256=expected_sha256,
        kind=kind,
        source_path=str(source),
        max_bytes=max_bytes,
    )
