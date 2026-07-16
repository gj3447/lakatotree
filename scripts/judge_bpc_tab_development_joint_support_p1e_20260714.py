#!/usr/bin/env python3
"""Score the frozen P1e decoded-cycle joint-support conformance gates.

The primary metric is the exact ten-case JUnit denominator.  This judge does
not import NumPy or open any decoded array.  It verifies the frozen census and
test sources, the committed P1d private-receipt snapshot, the preregistration
boundary, and the exact JUnit inventory.  Numeric array inspection belongs to
the separately frozen P1e novel judge.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any, Iterable
import xml.etree.ElementTree as ET


BPC_ROOT = Path("/data/kjra/PROJECT/3DLAB/BPC_ICP_SPEC")
LAKATO_ROOT = Path("/data/kjra/PROJECT/PI/lakatotree")
P1D_PRIVATE_ROOT = Path("/data/kjra/PROJECT/3DLAB/.private_bpc_p1d")
P1E_PRIVATE_ROOT = Path("/data/kjra/PROJECT/3DLAB/.private_bpc_p1e")

CENSUS = BPC_ROOT / (
    "scripts/tab_bolt_development_decoded_cycle_joint_support_census.py"
)
TEST_MODULE = BPC_ROOT / (
    "tests/test_tab_bolt_development_decoded_cycle_joint_support_census.py"
)
P1D_NOVEL_SCORER = LAKATO_ROOT / (
    "scripts/judge_bpc_tab_development_zdf_complete_cycle_novel_p1d_20260714.py"
)
PRIMARY_SCORER = Path(__file__).absolute()
NOVEL_SCORER = LAKATO_ROOT / (
    "scripts/judge_bpc_tab_development_joint_support_novel_p1e_20260714.py"
)
PROTOCOL = BPC_ROOT / (
    "evidence/bpc_tab_bolt_development_joint_support_census_protocol_20260714.json"
)
PUBLIC_RESULT = BPC_ROOT / (
    "evidence/bpc_tab_bolt_development_joint_support_census_result_20260714.json"
)
FIXED_JUNIT = BPC_ROOT / (
    "evidence/bpc_tab_bolt_development_joint_support_census_conformance_20260714.xml"
)
P1D_PRIVATE_BUNDLE = P1D_PRIVATE_ROOT / "development_decoded_cycle_r1"
P1D_PRIVATE_RECEIPT = P1D_PRIVATE_ROOT / (
    "bpc_tab_bolt_development_zdf_cycle_decode_private_receipt_20260714.json"
)
P1E_PRIVATE_RECEIPT = P1E_PRIVATE_ROOT / (
    "bpc_tab_bolt_development_joint_support_census_private_receipt_20260714.json"
)

# Replaced only after the two implementation sources are statically frozen.
CENSUS_SHA256 = "c8a264c86b7bd13545a3c5b7c62ffe9258929186a12c1972216c7372568201dd"
TEST_MODULE_SHA256 = "be767a5026bc2ec3955ca75a6480a13af7cfd1063aeb456d635a268f45d2fb40"
P1D_NOVEL_SCORER_SHA256 = (
    "662b5630d5c60cab4f3d82b022648585a289e77c6138228f8f87e5d364ceed52"
)
P1D_PRIVATE_RECEIPT_SHA256 = (
    "a30067e64a1dafb9b19d3762c49c09a4f4e8edd98555b35f293ad9c074128685"
)

PROTOCOL_SCHEMA = (
    "bpc.tab_bolt.development_decoded_cycle_joint_support_preregistration.v1"
)
PROTOCOL_STATUS = "PREREGISTERED_P1E_JOINT_SUPPORT_RESULT_ABSENT"
CLAIM_SCOPE = "ACTUAL_DEVELOPMENT_DECODED_CYCLE_JOINT_SUPPORT_CENSUS_ONLY"
TREE = "LakatosTree_BPC_TabBolt_Inference_20260701"
QUESTION = "q_bpc_development_decoded_cycle_joint_finite_support_20260714"
NODE_TAG = "tab_development_decoded_cycle_joint_support_p1e_20260714"
PARENT_NODE = "tab_development_zdf_complete_23view_private_decode_p1d_20260714"
PRIMARY_METRIC = "development_decoded_cycle_joint_support_conformance_gate_count"
NOVEL_METRIC = "actual_development_views_with_nonzero_joint_finite_support"
EXPECTED_TOTAL = 10
EXPECTED_VIEWS = 23
EXPECTED_ARRAYS = 46
CLASSNAME = "tests.test_tab_bolt_development_decoded_cycle_joint_support_census"
TEST_NAMES = frozenset(
    {
        "test_fake_exact_twenty_three_view_joint_support_census",
        "test_census_rejects_missing_or_extra_bundle_members",
        "test_census_rejects_private_receipt_or_bundle_manifest_commitment_mismatch",
        "test_census_rejects_symlink_hardlink_or_unsafe_modes",
        "test_census_rejects_npy_dtype_shape_order_trailing_or_pickle_drift",
        "test_census_rejects_input_mutation_or_stat_drift",
        "test_zero_joint_support_is_counted_fail_closed_without_overclaim",
        "test_census_never_clobbers_targets_and_publishes_atomic_modes",
        "test_public_result_omits_private_payload_and_overclaims",
        "test_committed_actual_development_cycle_has_joint_support_in_all_views",
    }
)
MAX_SMALL_FILE_BYTES = 16 * 1024 * 1024


class ScoreRejected(RuntimeError):
    """Fail closed without echoing private paths or commitments."""


def _reject() -> None:
    raise ScoreRejected("E_P1E_JOINT_SUPPORT_PRIMARY_REJECTED")


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


def _stable_regular_bytes(
    path: Path,
    *,
    required_mode: int | None = None,
) -> bytes:
    try:
        pathname = path.lstat()
    except OSError:
        _reject()
    if (
        stat.S_ISLNK(pathname.st_mode)
        or not stat.S_ISREG(pathname.st_mode)
        or pathname.st_nlink != 1
        or not 0 < pathname.st_size <= MAX_SMALL_FILE_BYTES
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


def _reject_constant(_: str) -> None:
    _reject()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _reject()
        result[key] = value
    return result


def _load_json(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError):
        _reject()
    if type(value) is not dict:
        _reject()
    return value


def _walk_string_values(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif type(value) is dict:
        for nested in value.values():
            yield from _walk_string_values(nested)
    elif type(value) is list:
        for nested in value:
            yield from _walk_string_values(nested)


def _verify_assets() -> None:
    expected = (
        (CENSUS, CENSUS_SHA256),
        (TEST_MODULE, TEST_MODULE_SHA256),
        (P1D_NOVEL_SCORER, P1D_NOVEL_SCORER_SHA256),
    )
    for path, committed in expected:
        if hashlib.sha256(_stable_regular_bytes(path)).hexdigest() != committed:
            _reject()
    if (
        hashlib.sha256(
            _stable_regular_bytes(P1D_PRIVATE_RECEIPT, required_mode=0o600)
        ).hexdigest()
        != P1D_PRIVATE_RECEIPT_SHA256
    ):
        _reject()


def _validate_scope_boundaries(protocol: dict[str, Any]) -> None:
    boundaries = protocol.get("scope_boundaries")
    false_claims = (
        "strict_v1_provenance_established",
        "literal_role_atlas_established",
        "raw_to_p1b_campaign_staged",
        "calibration_or_absolute_measurement_established",
        "physical_accuracy_established",
        "campaign_720_replayed",
        "production_ready_or_changed",
    )
    if type(boundaries) is not dict or (
        boundaries.get("development_view_count") != EXPECTED_VIEWS
        or boundaries.get("private_input_array_count") != EXPECTED_ARRAYS
        or boundaries.get("joint_finite_support_census_only") is not True
        or any(boundaries.get(name) is not False for name in false_claims)
    ):
        _reject()


def _validate_protocol(protocol: dict[str, Any]) -> None:
    if (
        protocol.get("schema") != PROTOCOL_SCHEMA
        or protocol.get("status") != PROTOCOL_STATUS
        or protocol.get("tree") != TREE
        or protocol.get("question") != QUESTION
        or protocol.get("node_tag") != NODE_TAG
        or protocol.get("parent_node_tag") != PARENT_NODE
        or protocol.get("claim_scope") != CLAIM_SCOPE
        or protocol.get("input_private_decode_receipt_sha256")
        != P1D_PRIVATE_RECEIPT_SHA256
        or protocol.get("production_change") is not False
        or protocol.get("static_preflight_only") is not True
    ):
        _reject()
    _validate_scope_boundaries(protocol)

    prediction = protocol.get("prediction")
    credence = prediction.get("credence") if type(prediction) is dict else None
    if type(prediction) is not dict or (
        prediction.get("metric") != PRIMARY_METRIC
        or prediction.get("baseline") != 0
        or prediction.get("direction") != "higher"
        or prediction.get("noise_band") != 0
        or prediction.get("predicted_value") != EXPECTED_TOTAL
        or prediction.get("novel_metric") != NOVEL_METRIC
        or prediction.get("novel_direction") != "higher"
        or prediction.get("novel_threshold") != EXPECTED_VIEWS
        or prediction.get("predicted_novel_value") != EXPECTED_VIEWS
        or type(credence) not in {int, float}
        or isinstance(credence, bool)
        or credence != 0.94
        or prediction.get("closes_question_on_success") != QUESTION
    ):
        _reject()

    inventory = protocol.get("test_inventory")
    if type(inventory) is not dict or (
        inventory.get("classname") != CLASSNAME
        or inventory.get("total") != EXPECTED_TOTAL
        or type(inventory.get("names")) is not list
        or len(inventory["names"]) != EXPECTED_TOTAL
        or set(inventory["names"]) != TEST_NAMES
        or inventory.get("actual_private_cycle_cases") != 1
    ):
        _reject()

    strings = set(_walk_string_values(protocol))
    required_hashes = {
        CENSUS_SHA256,
        TEST_MODULE_SHA256,
        P1D_NOVEL_SCORER_SHA256,
        P1D_PRIVATE_RECEIPT_SHA256,
        hashlib.sha256(_stable_regular_bytes(PRIMARY_SCORER)).hexdigest(),
        hashlib.sha256(_stable_regular_bytes(NOVEL_SCORER)).hexdigest(),
    }
    required_paths = {
        str(CENSUS),
        str(TEST_MODULE),
        str(P1D_NOVEL_SCORER),
        str(PRIMARY_SCORER),
        str(NOVEL_SCORER),
        str(PROTOCOL),
        str(PUBLIC_RESULT),
        str(FIXED_JUNIT),
        str(P1D_PRIVATE_BUNDLE),
        str(P1D_PRIVATE_RECEIPT),
        str(P1E_PRIVATE_RECEIPT),
    }
    if not required_hashes.issubset(strings) or not required_paths.issubset(strings):
        _reject()


def _integer_attribute(suite: ET.Element, name: str) -> int:
    value = suite.get(name)
    if value is None or not value.isascii() or not value.isdigit():
        _reject()
    return int(value)


def _score_junit() -> int:
    raw = _stable_regular_bytes(FIXED_JUNIT)
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
    counts = {
        name: _integer_attribute(suite, name)
        for name in ("tests", "errors", "failures", "skipped")
    }
    if counts != {
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


def score() -> int:
    """Return ten only for the complete frozen P1e conformance chain."""

    _verify_assets()
    _validate_protocol(_load_json(_stable_regular_bytes(PROTOCOL)))
    return _score_junit()


def main() -> int:
    try:
        if len(sys.argv) != 2 or not _same_fixed_path(sys.argv[1], FIXED_JUNIT):
            _reject()
        metric = score()
    except Exception:
        sys.stderr.write("E_P1E_JOINT_SUPPORT_PRIMARY_REJECTED\n")
        return 2
    print(f"metric={metric}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
