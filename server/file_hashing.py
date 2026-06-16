"""Filesystem hashing helpers for lineage freshness checks."""

from __future__ import annotations

import hashlib
import os


def file_sha(path: str, chunk: int = 1 << 20) -> str:
    """Return a streaming sha256 for a file without loading it all into memory."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(chunk), b""):
            h.update(blk)
    return h.hexdigest()


def path_sha(path: str) -> str | None:
    """Return a stable content sha for a file or directory, or None if absent."""
    try:
        if os.path.isfile(path):
            return file_sha(path)
        if os.path.isdir(path):
            h = hashlib.sha256()
            for root, dirs, files in os.walk(path):
                dirs.sort()
                for f in sorted(files):
                    fp = os.path.join(root, f)
                    if os.path.isfile(fp):
                        rel = os.path.relpath(fp, path).replace(os.sep, "/")
                        h.update(rel.encode())
                        h.update(b"\0")
                        h.update(file_sha(fp).encode())
                        h.update(b"\0")
            return h.hexdigest()
    except OSError as e:
        return f"__unreadable__:{type(e).__name__}"
    return None
