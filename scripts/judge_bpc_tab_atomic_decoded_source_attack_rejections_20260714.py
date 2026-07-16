#!/usr/bin/env python3
"""Independently score frozen BPC atomic-stager attack rejections."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import sys
from xml.dom import minidom


STAGER = Path(
    "/data/kjra/PROJECT/3DLAB/BPC_ICP_SPEC/scripts/"
    "tab_bolt_atomic_decoded_source_stager.py"
)
TEST_MODULE = Path(
    "/data/kjra/PROJECT/3DLAB/BPC_ICP_SPEC/tests/"
    "test_tab_bolt_atomic_decoded_source_stager.py"
)
P1A_VERIFIER = Path(
    "/data/kjra/PROJECT/3DLAB/BPC_ICP_SPEC/scripts/tab_bolt_blinded_staging_verifier.py"
)
STAGER_SHA256 = "b233ccade2ae58c88da794b4f6808b6f3d8c001c35818bbe7c3ab3e4abdb8f2d"
TEST_MODULE_SHA256 = "f47cc0f892b9046120f907110b622d04290cfaea0409cc633456d76b5be7835a"
P1A_VERIFIER_SHA256 = "fe2322ef88e662f6ca725ad84883f11c7df21a97b7430f76f0ebfeead1c0dc9a"
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
EXPECTED_TOTAL = 29
EXPECTED_ATTACKS = 27
MAX_FILE_BYTES = 8 * 1024 * 1024


def _stable_regular_bytes(path: Path, description: str) -> bytes:
    try:
        pathname = path.lstat()
    except OSError as exc:
        raise RuntimeError(f"missing {description}: {path}") from exc
    if stat.S_ISLNK(pathname.st_mode) or not stat.S_ISREG(pathname.st_mode):
        raise RuntimeError(f"{description} is not a regular non-symlink: {path}")
    if pathname.st_size <= 0 or pathname.st_size > MAX_FILE_BYTES:
        raise RuntimeError(f"{description} is empty or exceeds 8 MiB: {path}")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size) != (
            pathname.st_dev,
            pathname.st_ino,
            pathname.st_size,
        ) or not stat.S_ISREG(before.st_mode):
            raise RuntimeError(f"{description} changed before open: {path}")
        value = bytearray()
        while len(value) < before.st_size:
            block = os.read(descriptor, min(1024 * 1024, before.st_size - len(value)))
            if not block:
                raise RuntimeError(f"{description} truncated during read: {path}")
            value.extend(block)
        if os.read(descriptor, 1):
            raise RuntimeError(f"{description} grew during read: {path}")
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise RuntimeError(f"{description} changed during read: {path}")
        return bytes(value)
    finally:
        os.close(descriptor)


def _digest_frozen(path: Path) -> str:
    return hashlib.sha256(_stable_regular_bytes(path, "frozen source")).hexdigest()


def _element_children(node: minidom.Node) -> list[minidom.Element]:
    return [
        child
        for child in node.childNodes
        if child.nodeType == minidom.Node.ELEMENT_NODE
    ]


def _decimal_attribute(node: minidom.Element, name: str) -> int:
    value = node.getAttribute(name)
    if not value or not value.isascii() or not value.isdigit():
        raise RuntimeError(f"JUnit suite lacks integer {name}")
    return int(value)


def _count_attack_rejections(path: Path) -> int:
    raw = _stable_regular_bytes(path, "JUnit result")
    lowered = raw.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise RuntimeError("DTD/entity declarations are forbidden")
    try:
        document = minidom.parseString(raw)
    except Exception as exc:
        raise RuntimeError(f"invalid JUnit XML: {exc}") from exc
    root = document.documentElement
    if root.tagName != "testsuites" or root.namespaceURI is not None:
        raise RuntimeError("expected a non-namespaced testsuites root")
    suites = _element_children(root)
    if len(suites) != 1 or suites[0].tagName != "testsuite":
        raise RuntimeError("exactly one testsuite is required")
    suite = suites[0]
    aggregate = {
        name: _decimal_attribute(suite, name)
        for name in ("tests", "errors", "failures", "skipped")
    }
    if aggregate != {"tests": 29, "errors": 0, "failures": 0, "skipped": 0}:
        raise RuntimeError(
            f"JUnit aggregate is not the frozen all-green denominator: {aggregate}"
        )
    cases = _element_children(suite)
    if len(cases) != EXPECTED_TOTAL or any(
        case.tagName != "testcase" for case in cases
    ):
        raise RuntimeError("testsuite must contain exactly 29 testcase elements")
    names: list[str] = []
    for case in cases:
        if case.getAttribute("classname") != CLASSNAME or _element_children(case):
            raise RuntimeError("testcase classname or child state drifted")
        names.append(case.getAttribute("name"))
    expected_inventory = POSITIVE_NAMES | ATTACK_NAMES
    if len(set(names)) != EXPECTED_TOTAL or set(names) != expected_inventory:
        raise RuntimeError("testcase inventory drifted")
    attack_count = sum(name in ATTACK_NAMES for name in names)
    if attack_count != EXPECTED_ATTACKS:
        raise RuntimeError(
            f"expected {EXPECTED_ATTACKS} fail-closed attacks, found {attack_count}"
        )
    return attack_count


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit(
            "usage: judge_bpc_tab_atomic_decoded_source_attack_rejections_20260714.py RESULT.xml"
        )
    frozen = (
        (STAGER, STAGER_SHA256),
        (TEST_MODULE, TEST_MODULE_SHA256),
        (P1A_VERIFIER, P1A_VERIFIER_SHA256),
    )
    for path, expected in frozen:
        if _digest_frozen(path) != expected:
            raise RuntimeError(f"frozen BPC source hash mismatch: {path}")
    count = _count_attack_rejections(Path(sys.argv[1]))
    print(f"metric={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
