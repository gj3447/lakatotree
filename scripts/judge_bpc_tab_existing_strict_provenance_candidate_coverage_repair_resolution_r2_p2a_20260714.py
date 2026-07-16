#!/usr/bin/env python3
"""Return only the frozen P2a-R2 public coverage-resolution score.

The score is one only when the primary conformance judge regenerates sixteen
and independently revalidates a coverage-complete terminal public outcome.
Neither scorer opens the identity-bearing private receipt.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import sys
from types import ModuleType


BPC_ROOT = Path("/data/kjra/PROJECT/3DLAB/BPC_ICP_SPEC")
LAKATO_ROOT = Path("/data/kjra/PROJECT/PI/lakatotree")
PRIMARY_SCORER = LAKATO_ROOT / (
    "scripts/"
    "judge_bpc_tab_existing_strict_provenance_candidate_coverage_repair_"
    "r2_p2a_20260714.py"
)
FIXED_JUNIT = BPC_ROOT / (
    "evidence/"
    "bpc_tab_bolt_existing_authoritative_strict_provenance_candidate_"
    "coverage_repair_r2_conformance_20260714.xml"
)

PRIMARY_SCORER_SHA256 = (
    "ca2f1c1933059a0b34ce5f42f5857381991c6780812ad413cff3741076bf3b3f"
)
EXPECTED_PRIMARY = 16
MAX_SMALL_FILE_BYTES = 32 * 1024 * 1024


class ScoreRejected(RuntimeError):
    """Internal fail-closed signal."""


def _reject() -> None:
    raise ScoreRejected("E_P2A_R2_COVERAGE_REPAIR_RESOLUTION_REJECTED")


def _fingerprint(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        stat.S_IMODE(info.st_mode),
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _stable_primary_bytes() -> bytes:
    path = PRIMARY_SCORER
    try:
        pathname = path.lstat()
    except OSError:
        _reject()
    if (
        stat.S_ISLNK(pathname.st_mode)
        or not stat.S_ISREG(pathname.st_mode)
        or pathname.st_nlink != 1
        or not 0 < pathname.st_size <= MAX_SMALL_FILE_BYTES
    ):
        _reject()
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError:
        _reject()
    try:
        opened = os.fstat(descriptor)
        if _fingerprint(opened) != _fingerprint(pathname):
            _reject()
        value = bytearray()
        while len(value) < opened.st_size:
            block = os.read(
                descriptor,
                min(1024 * 1024, opened.st_size - len(value)),
            )
            if not block:
                _reject()
            value.extend(block)
        if os.read(descriptor, 1):
            _reject()
        if _fingerprint(os.fstat(descriptor)) != _fingerprint(opened):
            _reject()
        try:
            pathname_after = path.lstat()
        except OSError:
            _reject()
        if _fingerprint(pathname_after) != _fingerprint(opened):
            _reject()
        return bytes(value)
    finally:
        os.close(descriptor)


def _same_fixed_path(supplied: str, expected: Path) -> bool:
    try:
        return os.path.abspath(os.fspath(supplied)) == os.path.abspath(
            os.fspath(expected)
        )
    except (OSError, TypeError, ValueError):
        return False


def _load_primary() -> ModuleType:
    source = _stable_primary_bytes()
    if hashlib.sha256(source).hexdigest() != PRIMARY_SCORER_SHA256:
        _reject()
    name = "_bpc_tab_existing_strict_provenance_coverage_repair_r2_primary_frozen"
    if name in sys.modules:
        _reject()
    module = ModuleType(name)
    module.__file__ = str(PRIMARY_SCORER)
    module.__package__ = ""
    sys.modules[name] = module
    try:
        code = compile(
            source,
            str(PRIMARY_SCORER),
            "exec",
            dont_inherit=True,
            optimize=0,
        )
        exec(code, module.__dict__)
        if _stable_primary_bytes() != source:
            _reject()
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def _score_strict() -> int:
    primary = _load_primary()
    if primary.score() != EXPECTED_PRIMARY:
        _reject()
    # Reopens the protocol and redacted public record, but never the private
    # receipt, and applies the terminal coverage gates a second time.
    if primary.terminal_resolution_score() != 1:
        return 0
    return 1


def score() -> int:
    """Return one on public terminal coverage resolution; otherwise zero."""

    try:
        return _score_strict()
    except Exception:
        return 0


def main() -> int:
    metric = 0
    if len(sys.argv) == 2 and _same_fixed_path(sys.argv[1], FIXED_JUNIT):
        metric = score()
    print(f"metric={metric}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
