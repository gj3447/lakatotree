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


def raw_root() -> str:
    """source/raw 파일 해시를 가둘 루트 (나생문 #15: 무인증 임의경로 walk/read 차단).

    LAKATOS_RAW_ROOT env 우선, 미설정 시 repo 루트(이 파일의 두 단계 상위). 이 루트 밖 경로는
    path_sha 가 거부(None) — 에이전트가 '/'·'/proc'·거대 마운트를 kind='source' 로 선언해 서버
    요청 스레드를 재귀 walk·hash 시켜 hang/DoS 하거나, 루트 밖 파일 내용을 sha 로 누설하지 못하게
    한다. repo 밖 데이터를 쓰는 배포는 LAKATOS_RAW_ROOT 를 그 데이터 루트로 설정한다.
    """
    base = os.environ.get("LAKATOS_RAW_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.realpath(base)


def _within_raw_root(path: str) -> bool:
    """path 의 realpath 가 raw_root() 와 같거나 그 하위인가 (symlink 탈출 포함 차단)."""
    rp = os.path.realpath(path)
    base = raw_root()
    return rp == base or rp.startswith(base + os.sep)


def path_sha(path: str) -> str | None:
    """Return a stable content sha for a file or directory, or None if absent.

    보안(나생문 #15): raw_root() 밖 경로는 *거부*(None) — open/os.walk 하지 않는다.
    무인증 에이전트가 임의/거대 경로를 walk·hash 하게 두지 않는다(DoS + content read 차단).
    """
    if not _within_raw_root(path):
        return None
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
