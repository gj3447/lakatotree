#!/usr/bin/env python3
"""Return only the P2a JSON-scope audit coverage-resolution score.

The score is one when the fixed audit reaches either precommitted terminal
outcome and zero when coverage is incomplete.  It does not establish strict
provenance, capture authority, signature validity, calibration truth, physical
truth, or the existence of a complete candidate.  Candidate counts, paths,
and hashes never reach stdout.
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
    "scripts/judge_bpc_tab_existing_strict_provenance_candidate_p2a_20260714.py"
)
FIXED_JUNIT = BPC_ROOT / (
    "evidence/"
    "bpc_tab_bolt_existing_authoritative_strict_provenance_candidate_conformance_20260714.xml"
)

PRIMARY_SCORER_SHA256 = (
    "efe8d0845a8dc9efab5265cf885880549dc8b4564169ea1a0c781e0655535388"
)
EXPECTED_PRIMARY = 12
TERMINAL_OUTCOMES = frozenset(
    {"COMPLETE_CANDIDATE_FOUND", "NO_COMPLETE_CANDIDATE_IN_JSON_SCOPE"}
)
INCOMPLETE_OUTCOME = "AUDIT_INCOMPLETE"
MAX_SMALL_FILE_BYTES = 32 * 1024 * 1024


class ScoreRejected(RuntimeError):
    """Fail closed with one non-sensitive code."""


def _reject() -> None:
    raise ScoreRejected("E_P2A_STRICT_PROVENANCE_CANDIDATE_RESOLUTION_REJECTED")


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
        return Path(os.path.abspath(os.fspath(supplied))) == expected
    except (OSError, TypeError, ValueError):
        return False


def _load_primary() -> ModuleType:
    source = _stable_regular_bytes(PRIMARY_SCORER)
    if hashlib.sha256(source).hexdigest() != PRIMARY_SCORER_SHA256:
        _reject()
    name = "_bpc_tab_existing_strict_provenance_candidate_primary_p2a_frozen"
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
        if _stable_regular_bytes(PRIMARY_SCORER) != source:
            _reject()
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def score() -> int:
    """Return one for terminal coverage resolution and zero for incomplete audit."""

    primary = _load_primary()
    if primary.score() != EXPECTED_PRIMARY:
        _reject()

    # This second call deliberately reopens the protocol and both receipts.
    outcome = primary.validate_receipt_chain()
    resolution = primary.resolution_score_for_outcome(outcome)
    if outcome in TERMINAL_OUTCOMES:
        if resolution != 1:
            _reject()
        return 1
    if outcome == INCOMPLETE_OUTCOME:
        if resolution != 0:
            _reject()
        return 0
    _reject()


def main() -> int:
    try:
        if len(sys.argv) != 2 or not _same_fixed_path(sys.argv[1], FIXED_JUNIT):
            _reject()
        metric = score()
    except Exception:
        sys.stderr.write("E_P2A_STRICT_PROVENANCE_CANDIDATE_RESOLUTION_REJECTED\n")
        return 2
    print(f"metric={metric}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
