#!/usr/bin/env python3
"""Score the frozen BPC development-ZDF decoder capability JUnit gates."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import sys
import xml.etree.ElementTree as ET


BPC_ROOT = Path("/data/kjra/PROJECT/3DLAB/BPC_ICP_SPEC")
PROBE = BPC_ROOT / "scripts/tab_bolt_real_zdf_decoder_capability_probe.py"
TEST_MODULE = BPC_ROOT / "tests/test_tab_bolt_real_zdf_decoder_capability_probe.py"
FIXED_JUNIT = (
    BPC_ROOT / "evidence/"
    "bpc_tab_bolt_development_zdf_offline_decoder_capability_"
    "conformance_20260714.xml"
)
PROBE_SHA256 = "d8e32ad87693a06beb91140f1bb54edd3815f3dab438c74869af081cd196a1c9"
TEST_MODULE_SHA256 = "2388b793c32c5b79d5e025a8cc9fa605dc30f02d9c049c65b39df0d1b5dbb5e2"
CLASSNAME = "tests.test_tab_bolt_real_zdf_decoder_capability_probe"
TEST_NAMES = frozenset(
    {
        "test_valid_fake_decoder_emits_sanitized_claim_bounded_result",
        "test_committed_actual_development_zdf_decodes_organized_xyz_and_snr",
        "test_rejects_anchor_or_source_commitment_mismatch_before_decode",
        "test_rejects_source_symlink_before_decode",
        "test_rejects_source_mutation_during_snapshot",
        "test_rejects_python_zivid_or_numpy_version_drift",
        "test_rejects_missing_snr_channel",
        "test_rejects_transposed_snr_grid",
        "test_rejects_non_little_endian_float32_arrays",
        "test_rejects_non_c_contiguous_arrays",
        "test_rejects_xyz_or_snr_shape_drift",
        "test_decoder_requests_only_xyz_and_snr_from_one_point_cloud",
        "test_existing_public_or_private_result_is_never_clobbered",
        "test_decode_failure_removes_snapshot_and_publishes_nothing",
        "test_public_result_omits_identity_payload_and_overclaims",
    }
)
EXPECTED_TOTAL = 15
MAX_FILE_BYTES = 8 * 1024 * 1024


class ScoreRejected(RuntimeError):
    """Fail closed without echoing confidential values or paths."""


def _reject() -> None:
    raise ScoreRejected("E_P1C_PRIMARY_REJECTED")


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
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or (opened.st_dev, opened.st_ino, opened.st_size)
            != (pathname.st_dev, pathname.st_ino, pathname.st_size)
        ):
            _reject()
        value = bytearray()
        while len(value) < opened.st_size:
            try:
                chunk = os.read(
                    descriptor,
                    min(1024 * 1024, opened.st_size - len(value)),
                )
            except OSError:
                _reject()
            if not chunk:
                _reject()
            value.extend(chunk)
        try:
            if os.read(descriptor, 1):
                _reject()
            closed_read = os.fstat(descriptor)
        except OSError:
            _reject()
        if (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_mtime_ns,
            opened.st_ctime_ns,
        ) != (
            closed_read.st_dev,
            closed_read.st_ino,
            closed_read.st_size,
            closed_read.st_mtime_ns,
            closed_read.st_ctime_ns,
        ):
            _reject()
        return bytes(value)
    finally:
        os.close(descriptor)


def _same_fixed_path(supplied: str, expected: Path) -> bool:
    try:
        observed = Path(os.path.abspath(os.fspath(supplied)))
    except (OSError, TypeError, ValueError):
        return False
    return observed == expected


def _verify_frozen_sources() -> None:
    for path, expected in (
        (PROBE, PROBE_SHA256),
        (TEST_MODULE, TEST_MODULE_SHA256),
    ):
        observed = hashlib.sha256(_stable_regular_bytes(path)).hexdigest()
        if observed != expected:
            _reject()


def _integer_attribute(suite: ET.Element, name: str) -> int:
    value = suite.get(name)
    if value is None or not value.isascii() or not value.isdigit():
        _reject()
    return int(value)


def _score_junit(path: Path) -> int:
    raw = _stable_regular_bytes(path)
    lowered = raw.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        _reject()
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        _reject()
    if root.tag != "testsuites" or len(root) != 1 or root[0].tag != "testsuite":
        _reject()
    suite = root[0]
    aggregate = {
        name: _integer_attribute(suite, name)
        for name in ("tests", "errors", "failures", "skipped")
    }
    if aggregate != {
        "tests": EXPECTED_TOTAL,
        "errors": 0,
        "failures": 0,
        "skipped": 0,
    }:
        _reject()
    cases = list(suite)
    if len(cases) != EXPECTED_TOTAL or any(case.tag != "testcase" for case in cases):
        _reject()
    names = [case.get("name") for case in cases]
    if (
        len(set(names)) != EXPECTED_TOTAL
        or set(names) != TEST_NAMES
        or any(case.get("classname") != CLASSNAME for case in cases)
        or any(len(case) != 0 for case in cases)
    ):
        _reject()
    return len(cases)


def main() -> int:
    try:
        if len(sys.argv) != 2 or not _same_fixed_path(sys.argv[1], FIXED_JUNIT):
            _reject()
        _verify_frozen_sources()
        metric = _score_junit(FIXED_JUNIT)
    except (OSError, ValueError, ScoreRejected):
        sys.stderr.write("E_P1C_PRIMARY_REJECTED\n")
        return 2
    print(f"metric={metric}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
