#!/usr/bin/env python3
"""Score the frozen BPC atomic decoded-source staging JUnit gates."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import sys
import xml.etree.ElementTree as ET


BPC_ROOT = Path("/data/kjra/PROJECT/3DLAB/BPC_ICP_SPEC")
FROZEN_SOURCES = {
    BPC_ROOT / "scripts/tab_bolt_atomic_decoded_source_stager.py": (
        "b233ccade2ae58c88da794b4f6808b6f3d8c001c35818bbe7c3ab3e4abdb8f2d"
    ),
    BPC_ROOT / "tests/test_tab_bolt_atomic_decoded_source_stager.py": (
        "f47cc0f892b9046120f907110b622d04290cfaea0409cc633456d76b5be7835a"
    ),
    BPC_ROOT / "scripts/tab_bolt_blinded_staging_verifier.py": (
        "fe2322ef88e662f6ca725ad84883f11c7df21a97b7430f76f0ebfeead1c0dc9a"
    ),
}
CLASSNAME = "tests.test_tab_bolt_atomic_decoded_source_stager"
POSITIVE_NAMES = frozenset(
    {
        "test_valid_atomic_handoff_is_p1a_compatible_and_claim_bounded",
        "test_source_npy_hash_and_decode_use_the_same_bytes",
    }
)
ATTACK_NAMES = frozenset(
    {
        "test_rejects_missing_or_duplicate_view[missing]",
        "test_rejects_missing_or_duplicate_view[duplicate]",
        "test_rejects_role_or_mask_drift[point_role-POINT_ROLE_DRIFT]",
        "test_rejects_role_or_mask_drift[label_mask-LABEL_MASK_NOT_FULL_TRUE]",
        "test_rejects_role_or_mask_drift[point_mask-POINT_MASK_NOT_ALL_FALSE]",
        "test_rejects_commitment_or_raw_hash_attack[manifest_commitment-SOURCE_MANIFEST_COMMITMENT_MISMATCH]",
        "test_rejects_commitment_or_raw_hash_attack[artifact_hash-SOURCE_ARTIFACT_HASH_MISMATCH]",
        "test_rejects_commitment_or_raw_hash_attack[duplicate_raw-DUPLICATE_RAW_ZDF_HASH]",
        "test_rejects_commitment_or_raw_hash_attack[duplicate_decoded-DUPLICATE_DECODED_SOURCE_ARTIFACT]",
        "test_rejects_source_path_link_attacks[traversal-SOURCE_PATH_ESCAPE]",
        "test_rejects_source_path_link_attacks[symlink-SYMLINK_FORBIDDEN]",
        "test_rejects_source_path_link_attacks[parent_symlink-SYMLINK_FORBIDDEN]",
        "test_rejects_source_path_link_attacks[hardlink-HARDLINK_FORBIDDEN]",
        "test_rejects_unsafe_array_contract[dtype-SOURCE_ARRAY_CONTRACT]",
        "test_rejects_unsafe_array_contract[shape-SOURCE_ARRAY_SHAPE_MISMATCH]",
        "test_rejects_unsafe_array_contract[order-SOURCE_ARRAY_NOT_C_ORDER]",
        "test_rejects_unsafe_array_contract[trailing-SOURCE_NPY_TRAILING_BYTES]",
        "test_prepublish_fault_leaves_no_target_or_temporary_tree[after_temp_created]",
        "test_prepublish_fault_leaves_no_target_or_temporary_tree[after_capture_staged]",
        "test_prepublish_fault_leaves_no_target_or_temporary_tree[before_input_recheck]",
        "test_prepublish_fault_leaves_no_target_or_temporary_tree[before_publish]",
        "test_existing_public_target_is_never_clobbered",
        "test_renameat2_unavailable_fails_closed_without_rename_fallback",
        "test_public_plaintext_identity_leak_aborts_before_publish",
        "test_input_stat_change_during_run_aborts_atomically",
        "test_private_key_must_be_an_exact_bijection",
        "test_release_basename_must_be_an_opaque_snapshot_id",
    }
)
TEST_NAMES = POSITIVE_NAMES | ATTACK_NAMES
EXPECTED_TOTAL = 29
MAX_FILE_BYTES = 8 * 1024 * 1024


def _read_regular_file(path: Path, *, label: str) -> bytes:
    try:
        pathname = path.lstat()
    except OSError as exc:
        raise RuntimeError(f"{label} is missing: {path}") from exc
    if stat.S_ISLNK(pathname.st_mode) or not stat.S_ISREG(pathname.st_mode):
        raise RuntimeError(f"{label} must be a regular non-symlink file: {path}")
    if not 0 < pathname.st_size <= MAX_FILE_BYTES:
        raise RuntimeError(f"{label} must be non-empty and <= 8 MiB: {path}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or (opened.st_dev, opened.st_ino) != (pathname.st_dev, pathname.st_ino)
            or opened.st_size != pathname.st_size
        ):
            raise RuntimeError(f"{label} changed before open: {path}")
        chunks: list[bytes] = []
        remaining = opened.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise RuntimeError(f"{label} was truncated during read: {path}")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise RuntimeError(f"{label} grew during read: {path}")
        closed_read = os.fstat(descriptor)
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
            raise RuntimeError(f"{label} changed during read: {path}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _verify_frozen_sources() -> None:
    for path, expected in FROZEN_SOURCES.items():
        observed = hashlib.sha256(
            _read_regular_file(path, label="frozen source")
        ).hexdigest()
        if observed != expected:
            raise RuntimeError(f"frozen BPC source hash mismatch: {path}")


def _integer_attribute(suite: ET.Element, name: str) -> int:
    value = suite.get(name)
    if value is None or not value.isascii() or not value.isdigit():
        raise RuntimeError(f"JUnit suite lacks integer {name}")
    return int(value)


def _load_exact_junit(path: Path) -> list[ET.Element]:
    raw = _read_regular_file(path, label="JUnit result")
    lowered = raw.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise RuntimeError("DTD/entity declarations are forbidden")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise RuntimeError(f"invalid JUnit XML: {exc}") from exc
    if root.tag != "testsuites" or len(root) != 1 or root[0].tag != "testsuite":
        raise RuntimeError("expected exactly one non-namespaced testsuites/testsuite")
    suite = root[0]
    aggregate = {
        name: _integer_attribute(suite, name)
        for name in ("tests", "errors", "failures", "skipped")
    }
    expected_aggregate = {
        "tests": EXPECTED_TOTAL,
        "errors": 0,
        "failures": 0,
        "skipped": 0,
    }
    if aggregate != expected_aggregate:
        raise RuntimeError(
            f"JUnit aggregate is not the frozen all-green denominator: {aggregate}"
        )
    cases = list(suite)
    if len(cases) != EXPECTED_TOTAL or any(case.tag != "testcase" for case in cases):
        raise RuntimeError("testsuite must contain exactly 29 testcase elements")
    names = [case.get("name") for case in cases]
    if (
        len(set(names)) != EXPECTED_TOTAL
        or set(names) != TEST_NAMES
        or any(case.get("classname") != CLASSNAME for case in cases)
        or any(len(case) != 0 for case in cases)
    ):
        raise RuntimeError("testcase inventory, classname, or child state drifted")
    return cases


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit(
            "usage: judge_bpc_tab_atomic_decoded_source_gates_20260714.py RESULT.xml"
        )
    _verify_frozen_sources()
    cases = _load_exact_junit(Path(sys.argv[1]))
    print(f"metric={len(cases)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
