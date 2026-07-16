#!/usr/bin/env python3
"""R1 wrapper for the frozen BPC development-ZDF JUnit scorer."""

from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import stat
import sys
from types import ModuleType


LAKATO_ROOT = Path("/data/kjra/PROJECT/PI/lakatotree")
BPC_ROOT = Path("/data/kjra/PROJECT/3DLAB/BPC_ICP_SPEC")
ORIGINAL_SCORER = (
    LAKATO_ROOT / "scripts/judge_bpc_tab_real_zdf_decoder_capability_20260714.py"
)
ORIGINAL_SCORER_SHA256 = (
    "9e6e0aaa30f874f738d28d2ac5bbdd5f0203fa848f67de396b30d759386752f5"
)
R1_TEST_MODULE = (
    BPC_ROOT / "tests/test_tab_bolt_real_zdf_decoder_capability_probe_r1.py"
)
R1_TEST_MODULE_SHA256 = (
    "40251e1bb30596044eee2b6b5df2d5bb2ddd187d62b8ea7402624ba98418b765"
)
R1_JUNIT = (
    BPC_ROOT / "evidence/"
    "bpc_tab_bolt_development_zdf_offline_decoder_capability_"
    "r1_conformance_20260714.xml"
)
R1_CLASSNAME = "tests.test_tab_bolt_real_zdf_decoder_capability_probe_r1"
MAX_FILE_BYTES = 8 * 1024 * 1024


class WrapperRejected(RuntimeError):
    """Stable fail-closed wrapper error."""


def _reject() -> None:
    raise WrapperRejected("E_P1C_R1_PRIMARY_REJECTED")


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
        or not 0 < pathname.st_size <= MAX_FILE_BYTES
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
            chunk = os.read(
                descriptor,
                min(1024 * 1024, opened.st_size - len(value)),
            )
            if not chunk:
                _reject()
            value.extend(chunk)
        if os.read(descriptor, 1):
            _reject()
        if _fingerprint(os.fstat(descriptor)) != _fingerprint(opened):
            _reject()
        return bytes(value)
    finally:
        os.close(descriptor)


def _load_frozen_original() -> ModuleType:
    source = _stable_regular_bytes(ORIGINAL_SCORER)
    if hashlib.sha256(source).hexdigest() != ORIGINAL_SCORER_SHA256:
        _reject()
    spec = importlib.util.spec_from_file_location(
        "_bpc_tab_real_zdf_decoder_capability_primary_frozen",
        ORIGINAL_SCORER,
    )
    if spec is None or spec.loader is None:
        _reject()
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(spec.name, None)
        raise
    return module


def main() -> int:
    try:
        scorer = _load_frozen_original()
        scorer.FIXED_JUNIT = R1_JUNIT
        scorer.TEST_MODULE = R1_TEST_MODULE
        scorer.TEST_MODULE_SHA256 = R1_TEST_MODULE_SHA256
        scorer.CLASSNAME = R1_CLASSNAME
        return int(scorer.main())
    except Exception:
        sys.stderr.write("E_P1C_R1_PRIMARY_REJECTED\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
