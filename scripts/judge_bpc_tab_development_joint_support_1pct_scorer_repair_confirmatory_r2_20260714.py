#!/usr/bin/env python3
"""Confirm the already-public P1f aggregate after the R2 scorer repair.

This judge is a confirmatory replay only because the 23-view aggregate was
public before R2.  It requires the repaired exact-six primary score, runs the
frozen P1e replay, then reopens and revalidates the preserved P1f chain through
the R2 primary API.  Only the aggregate integer can reach stdout.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import stat
import sys
from types import ModuleType


BPC_ROOT = Path("/data/kjra/PROJECT/3DLAB/BPC_ICP_SPEC")
LAKATO_ROOT = Path("/data/kjra/PROJECT/PI/lakatotree")

PRIMARY_SCORER = LAKATO_ROOT / (
    "scripts/judge_bpc_tab_development_joint_support_1pct_scorer_repair_r2_20260714.py"
)
P1E_NOVEL_SCORER = LAKATO_ROOT / (
    "scripts/judge_bpc_tab_development_joint_support_novel_p1e_20260714.py"
)
R2_JUNIT = BPC_ROOT / (
    "evidence/"
    "bpc_tab_bolt_development_joint_support_1pct_scorer_repair_r2_conformance_20260714.xml"
)

PRIMARY_SCORER_SHA256 = (
    "81ae09c49a98ecf2bddff6e47663fda192d575e4f507e69b5d35c33b1568b6bc"
)
P1E_NOVEL_SCORER_SHA256 = (
    "3650aca875c5d0aae147ec7a4aef43fed61b1481ece6285f884726a0f9701c61"
)
EXPECTED_PRIMARY = 6
EXPECTED_PRESERVED_R1 = 9
EXPECTED_VIEWS = 23
MAX_SMALL_FILE_BYTES = 16 * 1024 * 1024


class ScoreRejected(RuntimeError):
    """Fail closed without echoing private values, paths, or commitments."""


def _reject() -> None:
    raise ScoreRejected(
        "E_P1F_JOINT_SUPPORT_1PCT_SCORER_REPAIR_CONFIRMATORY_R2_REJECTED"
    )


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
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
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
        return bytes(value)
    finally:
        os.close(descriptor)


def _same_fixed_path(supplied: str, expected: Path) -> bool:
    try:
        return Path(os.path.abspath(os.fspath(supplied))) == expected
    except (OSError, TypeError, ValueError):
        return False


def _load_frozen(name: str, path: Path, expected_sha256: str) -> ModuleType:
    source = _stable_regular_bytes(path)
    if hashlib.sha256(source).hexdigest() != expected_sha256:
        _reject()
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None or name in sys.modules:
        _reject()
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def score() -> int:
    """Return the already-public aggregate only after all confirmatory gates."""

    primary = _load_frozen(
        "_bpc_tab_development_joint_support_1pct_repair_primary_r2_frozen",
        PRIMARY_SCORER,
        PRIMARY_SCORER_SHA256,
    )
    if primary.score() != EXPECTED_PRIMARY:
        _reject()

    p1e = _load_frozen(
        "_bpc_tab_development_joint_support_novel_p1e_frozen_for_repair_r2",
        P1E_NOVEL_SCORER,
        P1E_NOVEL_SCORER_SHA256,
    )
    if p1e.score() != EXPECTED_VIEWS:
        _reject()

    if primary.score_preserved_p1f_chain() != EXPECTED_PRESERVED_R1:
        _reject()
    return EXPECTED_VIEWS


def main() -> int:
    try:
        if len(sys.argv) != 2 or not _same_fixed_path(sys.argv[1], R2_JUNIT):
            _reject()
        metric = score()
    except Exception:
        sys.stderr.write(
            "E_P1F_JOINT_SUPPORT_1PCT_SCORER_REPAIR_CONFIRMATORY_R2_REJECTED\n"
        )
        return 2
    print(f"metric={metric}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
