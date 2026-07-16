#!/usr/bin/env python3
"""Confirm the known R2 conformance count after the R3 scorer repair.

This replay is not a novel scientific measurement.  It first requires the
repair primary to regenerate six, then confirms the immutable public R2 chain
as conformance sixteen and terminal resolution zero.
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
PRIMARY = LAKATO_ROOT / (
    "scripts/judge_bpc_tab_existing_strict_provenance_candidate_coverage_"
    "repair_r2_scorer_repair_r3_p2a_20260714.py"
)
R3_JUNIT = BPC_ROOT / (
    "evidence/bpc_tab_bolt_existing_authoritative_strict_provenance_candidate_"
    "coverage_repair_r2_scorer_repair_r3_conformance_20260714.xml"
)
PRIMARY_SHA256 = "935f27bf32aa927a4cd614c0e44e0bc638ec1c857e29b8f5e0c9761c537c5050"
EXPECTED_REPAIR = 6
EXPECTED_ORIGINAL = 16
EXPECTED_RESOLUTION = 0
MAX_SMALL_FILE_BYTES = 32 * 1024 * 1024


class ScoreRejected(RuntimeError):
    """Fail closed without echoing private values or source identities."""


def _reject() -> None:
    raise ScoreRejected("E_P2A_R2_SCORER_REPAIR_CONFIRMATORY_R3_REJECTED")


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


def _stable_regular_bytes(path: Path) -> bytes:
    if os.path.abspath(os.fspath(path)) != os.path.abspath(os.fspath(PRIMARY)):
        _reject()
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
            block = os.read(descriptor, min(1024 * 1024, opened.st_size - len(value)))
            if not block:
                _reject()
            value.extend(block)
        if os.read(descriptor, 1) or _fingerprint(os.fstat(descriptor)) != _fingerprint(
            opened
        ):
            _reject()
        if _fingerprint(path.lstat()) != _fingerprint(opened):
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
    source = _stable_regular_bytes(PRIMARY)
    if hashlib.sha256(source).hexdigest() != PRIMARY_SHA256:
        _reject()
    name = "_bpc_p2a_r2_scorer_repair_r3_confirmatory_primary"
    if name in sys.modules:
        _reject()
    try:
        code = compile(source, str(PRIMARY), "exec", dont_inherit=True)
    except (SyntaxError, ValueError):
        _reject()
    module = ModuleType(name)
    module.__file__ = str(PRIMARY)
    module.__package__ = ""
    sys.modules[name] = module
    try:
        exec(code, module.__dict__)
        if hashlib.sha256(_stable_regular_bytes(PRIMARY)).hexdigest() != PRIMARY_SHA256:
            _reject()
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def score() -> int:
    """Return the already-known original count only after all repair gates."""

    try:
        primary = _load_primary()
        if primary.score() != EXPECTED_REPAIR:
            _reject()
        if primary.score_preserved_r2_chain() != EXPECTED_ORIGINAL:
            _reject()
        if primary.terminal_resolution_score() != EXPECTED_RESOLUTION:
            _reject()
        return EXPECTED_ORIGINAL
    except Exception:
        return 0


def main() -> int:
    metric = 0
    if len(sys.argv) == 2 and _same_fixed_path(sys.argv[1], R3_JUNIT):
        metric = score()
    print(f"metric={metric}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
