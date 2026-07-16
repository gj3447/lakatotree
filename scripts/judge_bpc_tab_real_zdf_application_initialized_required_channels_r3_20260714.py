#!/usr/bin/env python3
"""Score two channels from the frozen R3 Application-initialized receipt chain.

The scorer first requires the exact sixteen-case R3 conformance score, then
reuses the frozen P1c receipt-chain judge with only R3 paths and commitments
substituted.  It does not import Zivid or independently decode the ZDF; the two
payload digests remain receipt commitments rather than an independent replay.
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
PRIVATE_ROOT = Path("/data/kjra/PROJECT/3DLAB/.private_bpc_p1c")

FROZEN_PROBE = BPC_ROOT / "scripts/tab_bolt_real_zdf_decoder_capability_probe.py"
APPLICATION_WRAPPER = (
    BPC_ROOT / "scripts/tab_bolt_real_zdf_application_initialized_probe.py"
)
R3_TEST = BPC_ROOT / "tests/test_tab_bolt_real_zdf_application_initialized_probe_r3.py"
R3_PRIMARY_SCORER = LAKATO_ROOT / (
    "scripts/judge_bpc_tab_real_zdf_application_initialized_r3_20260714.py"
)
R3_NOVEL_SCORER = Path(__file__).absolute()
FROZEN_NOVEL_SCORER = LAKATO_ROOT / (
    "scripts/judge_bpc_tab_real_zdf_required_channel_rejections_20260714.py"
)
PROTOCOL = BPC_ROOT / (
    "evidence/bpc_tab_bolt_development_zdf_application_initialized_"
    "r3_20260714_protocol.json"
)
PUBLIC_RESULT = BPC_ROOT / (
    "evidence/bpc_tab_bolt_development_zdf_application_initialized_"
    "r3_20260714_result.json"
)
FIXED_JUNIT = BPC_ROOT / (
    "evidence/bpc_tab_bolt_development_zdf_application_initialized_"
    "r3_20260714_conformance.xml"
)
SOURCE_PREREGISTRATION = PRIVATE_ROOT / (
    "bpc_tab_bolt_real_zdf_source_preregistration_20260714.json"
)
PRIVATE_RECEIPT = PRIVATE_ROOT / (
    "bpc_tab_bolt_real_zdf_application_initialized_r3_private_receipt_20260714.json"
)
FIXED_SCRATCH = PRIVATE_ROOT / "scratch_r3"

FROZEN_PROBE_SHA256 = "d8e32ad87693a06beb91140f1bb54edd3815f3dab438c74869af081cd196a1c9"
APPLICATION_WRAPPER_SHA256 = (
    "6bd8bb1b2b03f51cde80e375c98dd2368076b0e38914185e5394c100097a1f35"
)
R3_TEST_SHA256 = "9b52a75b9d4ef9f87b04d4f672b08b71e49eacd88f859575ecc9dbf6fed2d567"
SOURCE_PREREGISTRATION_SHA256 = (
    "29e09511d4ab88611f087f204d7f986d7693114cafc72b488d883a2117b83d8e"
)
FROZEN_NOVEL_SCORER_SHA256 = (
    "cc000823b3b33b2d51615c8b3f745716feaf1d45f20cb79007f15e176b025bac"
)
R3_PRIMARY_SCORER_SHA256 = (
    "a321083da0cab0373fefd23c5d7c3bd10490e202cef8d1f824f01d8798818f63"
)

PROTOCOL_SCHEMA = (
    "bpc.tab_bolt.development_zdf_application_initialized_preregistration.v1"
)
EXPECTED_PRIMARY = 16
EXPECTED_CHANNELS = 2
MAX_FILE_BYTES = 8 * 1024 * 1024


class ScoreRejected(RuntimeError):
    """Fail closed without echoing private identities or paths."""


def _reject() -> None:
    raise ScoreRejected("E_P1C_R3_APPLICATION_CHANNELS_REJECTED")


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


def _read(path: Path, *, required_mode: int | None = None) -> bytes:
    try:
        pathname = path.lstat()
    except OSError:
        _reject()
    if (
        stat.S_ISLNK(pathname.st_mode)
        or not stat.S_ISREG(pathname.st_mode)
        or pathname.st_nlink != 1
        or not 0 < pathname.st_size <= MAX_FILE_BYTES
        or (
            required_mode is not None
            and stat.S_IMODE(pathname.st_mode) != required_mode
        )
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
    source = _read(path)
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


def _verify_r3_assets() -> None:
    expected = (
        (FROZEN_PROBE, FROZEN_PROBE_SHA256),
        (APPLICATION_WRAPPER, APPLICATION_WRAPPER_SHA256),
        (R3_TEST, R3_TEST_SHA256),
    )
    for path, committed in expected:
        if hashlib.sha256(_read(path)).hexdigest() != committed:
            _reject()
    source_hash = hashlib.sha256(
        _read(SOURCE_PREREGISTRATION, required_mode=0o600)
    ).hexdigest()
    if source_hash != SOURCE_PREREGISTRATION_SHA256:
        _reject()


def _configure_frozen_receipt_judge(judge: ModuleType) -> None:
    judge.PROBE = FROZEN_PROBE
    judge.TEST_MODULE = R3_TEST
    judge.PRIMARY_SCORER = R3_PRIMARY_SCORER
    judge.NOVEL_SCORER = R3_NOVEL_SCORER
    judge.PROTOCOL = PROTOCOL
    judge.PUBLIC_RESULT = PUBLIC_RESULT
    judge.SOURCE_PREREGISTRATION = SOURCE_PREREGISTRATION
    judge.PRIVATE_RECEIPT = PRIVATE_RECEIPT
    judge.FIXED_SCRATCH = FIXED_SCRATCH
    judge.PROBE_SHA256 = FROZEN_PROBE_SHA256
    judge.TEST_MODULE_SHA256 = R3_TEST_SHA256
    judge.PROTOCOL_SCHEMA = PROTOCOL_SCHEMA


def score() -> int:
    """Return two only for the exact R3 JUnit and receipt-chain evidence."""

    _verify_r3_assets()
    primary = _load_frozen(
        "_bpc_tab_real_zdf_application_r3_primary_frozen",
        R3_PRIMARY_SCORER,
        R3_PRIMARY_SCORER_SHA256,
    )
    if primary.score() != EXPECTED_PRIMARY:
        _reject()

    receipt_judge = _load_frozen(
        "_bpc_tab_real_zdf_required_channels_frozen_for_r3",
        FROZEN_NOVEL_SCORER,
        FROZEN_NOVEL_SCORER_SHA256,
    )
    _configure_frozen_receipt_judge(receipt_judge)
    metric = receipt_judge._score()  # noqa: SLF001 - frozen scorer entry point
    if metric != EXPECTED_CHANNELS:
        _reject()
    return metric


def main() -> int:
    try:
        if len(sys.argv) != 2 or not _same_fixed_path(sys.argv[1], FIXED_JUNIT):
            _reject()
        metric = score()
    except Exception:
        sys.stderr.write("E_P1C_R3_APPLICATION_CHANNELS_REJECTED\n")
        return 2
    print(f"metric={metric}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
