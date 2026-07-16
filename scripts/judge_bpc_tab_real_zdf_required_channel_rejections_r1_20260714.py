#!/usr/bin/env python3
"""R1 wrapper for the frozen development-ZDF required-channel scorer."""

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
PRIVATE_ROOT = Path("/data/kjra/PROJECT/3DLAB/.private_bpc_p1c")

ORIGINAL_SCORER = (
    LAKATO_ROOT
    / "scripts/judge_bpc_tab_real_zdf_required_channel_rejections_20260714.py"
)
ORIGINAL_SCORER_SHA256 = (
    "cc000823b3b33b2d51615c8b3f745716feaf1d45f20cb79007f15e176b025bac"
)
R1_TEST_MODULE = (
    BPC_ROOT / "tests/test_tab_bolt_real_zdf_decoder_capability_probe_r1.py"
)
R1_TEST_MODULE_SHA256 = (
    "40251e1bb30596044eee2b6b5df2d5bb2ddd187d62b8ea7402624ba98418b765"
)
R1_PRIMARY_SCORER = (
    LAKATO_ROOT / "scripts/judge_bpc_tab_real_zdf_decoder_capability_r1_20260714.py"
)
R1_PROTOCOL = (
    BPC_ROOT / "evidence/"
    "bpc_tab_bolt_development_zdf_offline_decoder_capability_"
    "r1_protocol_20260714.json"
)
R1_PUBLIC_RESULT = (
    BPC_ROOT / "evidence/"
    "bpc_tab_bolt_development_zdf_offline_decoder_capability_"
    "r1_result_20260714.json"
)
R1_PRIVATE_RECEIPT = (
    PRIVATE_ROOT
    / "bpc_tab_bolt_real_zdf_decoder_capability_r1_private_receipt_20260714.json"
)
R1_SCRATCH = PRIVATE_ROOT / "scratch_r1"
R1_NOVEL_SCORER = Path(__file__).absolute()
MAX_FILE_BYTES = 8 * 1024 * 1024


class WrapperRejected(RuntimeError):
    """Stable fail-closed wrapper error."""


def _reject() -> None:
    raise WrapperRejected("E_P1C_R1_REQUIRED_CHANNEL_REJECTED")


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
        "_bpc_tab_real_zdf_required_channels_frozen",
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
        scorer.PROTOCOL = R1_PROTOCOL
        scorer.PUBLIC_RESULT = R1_PUBLIC_RESULT
        scorer.PRIVATE_RECEIPT = R1_PRIVATE_RECEIPT
        scorer.FIXED_SCRATCH = R1_SCRATCH
        scorer.TEST_MODULE = R1_TEST_MODULE
        scorer.TEST_MODULE_SHA256 = R1_TEST_MODULE_SHA256
        scorer.PRIMARY_SCORER = R1_PRIMARY_SCORER
        scorer.NOVEL_SCORER = R1_NOVEL_SCORER
        scorer.__file__ = str(R1_NOVEL_SCORER)
        return int(scorer.main())
    except Exception:
        sys.stderr.write("E_P1C_R1_REQUIRED_CHANNEL_REJECTED\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
