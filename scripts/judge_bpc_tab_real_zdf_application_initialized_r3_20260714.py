#!/usr/bin/env python3
"""Score the frozen R3 Application-initialized ZDF conformance gates.

The metric is the exact sixteen-case JUnit denominator.  This scorer is
static with respect to Zivid: it reads committed source files, the R3
preregistration, and JUnit, but it never imports the probe, imports Zivid, or
opens a ZDF through a decoder API.
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
PRIVATE_ROOT = Path("/data/kjra/PROJECT/3DLAB/.private_bpc_p1c")

FROZEN_PROBE = BPC_ROOT / "scripts/tab_bolt_real_zdf_decoder_capability_probe.py"
APPLICATION_WRAPPER = (
    BPC_ROOT / "scripts/tab_bolt_real_zdf_application_initialized_probe.py"
)
BASE_TEST = BPC_ROOT / "tests/test_tab_bolt_real_zdf_decoder_capability_probe.py"
R3_TEST = BPC_ROOT / "tests/test_tab_bolt_real_zdf_application_initialized_probe_r3.py"
ORIGINAL_PRIMARY_SCORER = (
    LAKATO_ROOT / "scripts/judge_bpc_tab_real_zdf_decoder_capability_20260714.py"
)
ORIGINAL_NOVEL_SCORER = LAKATO_ROOT / (
    "scripts/judge_bpc_tab_real_zdf_required_channel_rejections_20260714.py"
)
R3_PRIMARY_SCORER = Path(__file__).absolute()
R3_NOVEL_SCORER = LAKATO_ROOT / (
    "scripts/judge_bpc_tab_real_zdf_application_initialized_"
    "required_channels_r3_20260714.py"
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

R2_PROTOCOL = BPC_ROOT / (
    "evidence/bpc_tab_bolt_development_zdf_decoder_diagnostic_r2_20260714_protocol.json"
)
R2_PUBLIC_RESULT = BPC_ROOT / (
    "evidence/bpc_tab_bolt_development_zdf_decoder_diagnostic_r2_20260714_result.json"
)
R2_JUNIT = BPC_ROOT / (
    "evidence/bpc_tab_bolt_development_zdf_decoder_diagnostic_"
    "r2_20260714_conformance.xml"
)
R2_PRIMARY_SCORER = LAKATO_ROOT / (
    "scripts/judge_bpc_tab_real_zdf_decoder_stage_diagnostic_r2_20260714.py"
)
R2_NOVEL_SCORER = LAKATO_ROOT / (
    "scripts/judge_bpc_tab_real_zdf_sanitized_stage_resolution_r2_20260714.py"
)
STRICT_LAYOUT_AUDIT = BPC_ROOT / (
    "evidence/bpc_tab_bolt_p1c_strict_layout_boundary_audit_20260714.json"
)

FROZEN_PROBE_SHA256 = "d8e32ad87693a06beb91140f1bb54edd3815f3dab438c74869af081cd196a1c9"
APPLICATION_WRAPPER_SHA256 = (
    "6bd8bb1b2b03f51cde80e375c98dd2368076b0e38914185e5394c100097a1f35"
)
BASE_TEST_SHA256 = "2388b793c32c5b79d5e025a8cc9fa605dc30f02d9c049c65b39df0d1b5dbb5e2"
R3_TEST_SHA256 = "9b52a75b9d4ef9f87b04d4f672b08b71e49eacd88f859575ecc9dbf6fed2d567"
SOURCE_PREREGISTRATION_SHA256 = (
    "29e09511d4ab88611f087f204d7f986d7693114cafc72b488d883a2117b83d8e"
)
ORIGINAL_PRIMARY_SCORER_SHA256 = (
    "9e6e0aaa30f874f738d28d2ac5bbdd5f0203fa848f67de396b30d759386752f5"
)
ORIGINAL_NOVEL_SCORER_SHA256 = (
    "cc000823b3b33b2d51615c8b3f745716feaf1d45f20cb79007f15e176b025bac"
)
R2_PROTOCOL_SHA256 = "b75ca8e294c6718615b43324c2c7d8f4dd08a3c6fa2a48d84080c5668d098e94"
R2_PUBLIC_RESULT_SHA256 = (
    "5847824b7f39ad8fe30879de02c58a3f1de90b78732c2b6ef651642e9929afd6"
)
R2_JUNIT_SHA256 = "b1be1fbf81b616ed7ed1674a55ac3d1b50c2bca74d5caf3bf2fd14de493bde13"
R2_PRIMARY_SCORER_SHA256 = (
    "44fcfe8998c3e703d6369d690da413895e9452cfb966d4252f571e7b76d35dea"
)
R2_NOVEL_SCORER_SHA256 = (
    "8975fdfd0189c8196be50c7416644dd9c456f7b1a13a19d00c896f2d660f0c02"
)
STRICT_LAYOUT_AUDIT_SHA256 = (
    "60bd0ed2233c4d7e07cc7f0744775fe4e98df17a7a759bdcbdc00fd61bf6a24b"
)

PROTOCOL_SCHEMA = (
    "bpc.tab_bolt.development_zdf_application_initialized_preregistration.v1"
)
PROTOCOL_STATUS = "PREREGISTERED_R3_APPLICATION_REPAIR_RESULT_ABSENT"
CLAIM_SCOPE = "ACTUAL_DEVELOPMENT_ZDF_OFFLINE_DECODER_CAPABILITY_ONLY"
TREE = "LakatosTree_BPC_TabBolt_Inference_20260701"
QUESTION = "q_bpc_development_zdf_organized_xyz_snr_decode_20260714"
PARENT_NODE = "tab_development_zdf_decoder_stage_diagnostic_r2_20260714"
CONTROLLED_REPAIR_OPERATION = "zivid.Application"
FROZEN_POST_INITIALIZATION_OPERATIONS = [
    "zivid.Frame",
    "frame.point_cloud",
    "copy_data:xyz",
    "copy_data:snr",
]
FULL_REPAIRED_SEQUENCE = [
    CONTROLLED_REPAIR_OPERATION,
    *FROZEN_POST_INITIALIZATION_OPERATIONS,
]
PRIMARY_METRIC = "development_zdf_application_initialized_r3_conformance_gate_count"
NOVEL_METRIC = "actual_development_zdf_required_channel_count"
EXPECTED_TOTAL = 16
EXPECTED_NOVEL = 2
CLASSNAME = "tests.test_tab_bolt_real_zdf_application_initialized_probe_r3"
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
        "test_application_is_initialized_before_frame_retained_through_copies_without_camera_access",
    }
)
MAX_FILE_BYTES = 8 * 1024 * 1024


class ScoreRejected(RuntimeError):
    """Fail closed without echoing confidential values or paths."""


def _reject() -> None:
    raise ScoreRejected("E_P1C_R3_APPLICATION_PRIMARY_REJECTED")


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


def _verify_assets() -> dict[Path, str]:
    expected = {
        FROZEN_PROBE: FROZEN_PROBE_SHA256,
        APPLICATION_WRAPPER: APPLICATION_WRAPPER_SHA256,
        BASE_TEST: BASE_TEST_SHA256,
        R3_TEST: R3_TEST_SHA256,
        ORIGINAL_PRIMARY_SCORER: ORIGINAL_PRIMARY_SCORER_SHA256,
        ORIGINAL_NOVEL_SCORER: ORIGINAL_NOVEL_SCORER_SHA256,
        R2_PROTOCOL: R2_PROTOCOL_SHA256,
        R2_PUBLIC_RESULT: R2_PUBLIC_RESULT_SHA256,
        R2_JUNIT: R2_JUNIT_SHA256,
        R2_PRIMARY_SCORER: R2_PRIMARY_SCORER_SHA256,
        R2_NOVEL_SCORER: R2_NOVEL_SCORER_SHA256,
        STRICT_LAYOUT_AUDIT: STRICT_LAYOUT_AUDIT_SHA256,
    }
    for path, committed in expected.items():
        if hashlib.sha256(_stable_regular_bytes(path)).hexdigest() != committed:
            _reject()
    source_hash = hashlib.sha256(
        _stable_regular_bytes(SOURCE_PREREGISTRATION, required_mode=0o600)
    ).hexdigest()
    if source_hash != SOURCE_PREREGISTRATION_SHA256:
        _reject()
    expected[SOURCE_PREREGISTRATION] = SOURCE_PREREGISTRATION_SHA256
    return expected


def _validate_protocol(raw: bytes, protocol: dict[str, Any]) -> None:
    if (
        protocol.get("schema") != PROTOCOL_SCHEMA
        or protocol.get("status") != PROTOCOL_STATUS
        or protocol.get("tree") != TREE
        or protocol.get("question") != QUESTION
        or protocol.get("parent_node_tag") != PARENT_NODE
        or protocol.get("claim_scope") != CLAIM_SCOPE
        or protocol.get("production_change") is not False
    ):
        _reject()

    repair = protocol.get("repair_contract")
    if type(repair) is not dict or (
        repair.get("controlled_repair_operation") != CONTROLLED_REPAIR_OPERATION
        or repair.get("application_initialized_before_frame") is not True
        or repair.get("application_retained_through_xyz_and_snr_copies") is not True
        or repair.get("explicit_camera_enumeration_connect_or_capture_api_invoked")
        is not False
        or repair.get(
            "internal_application_initialization_behavior_independently_audited"
        )
        is not False
        or repair.get("frozen_post_initialization_operations")
        != FROZEN_POST_INITIALIZATION_OPERATIONS
        or repair.get("frozen_requested_channels") != ["xyz", "snr"]
        or repair.get("frozen_custody_probe_changed") is not False
        or repair.get("frozen_public_or_private_schema_changed") is not False
        or repair.get("frozen_base_scientific_gates_reused") != 15
        or repair.get("new_mechanism_gates") != 1
        or repair.get("unique_root_cause_established") is not False
        or repair.get("application_initialization_sufficiency_tested") is not True
        or repair.get("other_decoder_repair_allowed") is not False
    ):
        _reject()

    prediction = protocol.get("prediction")
    if type(prediction) is not dict or (
        prediction.get("metric") != PRIMARY_METRIC
        or prediction.get("baseline") != 0
        or prediction.get("direction") != "higher"
        or prediction.get("noise_band") != 0
        or prediction.get("predicted_value") != EXPECTED_TOTAL
        or prediction.get("novel_metric") != NOVEL_METRIC
        or prediction.get("novel_direction") != "higher"
        or prediction.get("novel_threshold") != EXPECTED_NOVEL
        or prediction.get("predicted_novel_value") != EXPECTED_NOVEL
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
    ):
        _reject()

    required_hashes = {
        FROZEN_PROBE_SHA256,
        APPLICATION_WRAPPER_SHA256,
        BASE_TEST_SHA256,
        R3_TEST_SHA256,
        SOURCE_PREREGISTRATION_SHA256,
        R2_PROTOCOL_SHA256,
        R2_PUBLIC_RESULT_SHA256,
        R2_JUNIT_SHA256,
        STRICT_LAYOUT_AUDIT_SHA256,
        hashlib.sha256(_stable_regular_bytes(R3_PRIMARY_SCORER)).hexdigest(),
        hashlib.sha256(_stable_regular_bytes(R3_NOVEL_SCORER)).hexdigest(),
    }
    strings = set(_walk_string_values(protocol))
    required_paths = {
        str(FROZEN_PROBE),
        str(APPLICATION_WRAPPER),
        str(BASE_TEST),
        str(R3_TEST),
        str(R3_PRIMARY_SCORER),
        str(R3_NOVEL_SCORER),
        str(PROTOCOL),
        str(PUBLIC_RESULT),
        str(FIXED_JUNIT),
        str(R2_PROTOCOL),
        str(R2_PUBLIC_RESULT),
        str(R2_JUNIT),
        str(STRICT_LAYOUT_AUDIT),
    }
    if not required_hashes.issubset(strings) or not required_paths.issubset(strings):
        _reject()
    if CONTROLLED_REPAIR_OPERATION not in strings:
        _reject()
    if raw.count(CONTROLLED_REPAIR_OPERATION.encode("utf-8")) < 1:
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
    """Return sixteen only for the complete frozen R3 conformance chain."""

    _verify_assets()
    protocol_raw = _stable_regular_bytes(PROTOCOL)
    _validate_protocol(protocol_raw, _load_json(protocol_raw))
    return _score_junit()


def main() -> int:
    try:
        if len(sys.argv) != 2 or not _same_fixed_path(sys.argv[1], FIXED_JUNIT):
            _reject()
        metric = score()
    except Exception:
        sys.stderr.write("E_P1C_R3_APPLICATION_PRIMARY_REJECTED\n")
        return 2
    print(f"metric={metric}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
