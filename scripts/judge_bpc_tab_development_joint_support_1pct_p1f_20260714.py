#!/usr/bin/env python3
"""Score the frozen P1f one-percent joint-support conformance chain.

P1f is a sealed secondary analysis of already-existing P1e per-view counts.
This primary judge never imports NumPy or opens the decoded arrays.  It binds
the frozen producer, exact-nine test inventory, P1e input receipt, protocol,
and public/private P1f receipt chain, while keeping every per-view value out of
stdout and error messages.  The independent novel judge owns the threshold
measurement and the P1e array replay.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Iterable, Mapping
import xml.etree.ElementTree as ET


BPC_ROOT = Path("/data/kjra/PROJECT/3DLAB/BPC_ICP_SPEC")
LAKATO_ROOT = Path("/data/kjra/PROJECT/PI/lakatotree")
P1E_PRIVATE_ROOT = Path("/data/kjra/PROJECT/3DLAB/.private_bpc_p1e")
P1F_PRIVATE_ROOT = Path("/data/kjra/PROJECT/3DLAB/.private_bpc_p1f")

THRESHOLD_SCRIPT = BPC_ROOT / (
    "scripts/tab_bolt_development_joint_support_1pct_threshold.py"
)
TEST_MODULE = BPC_ROOT / (
    "tests/test_tab_bolt_development_joint_support_1pct_threshold.py"
)
P1E_NOVEL_SCORER = LAKATO_ROOT / (
    "scripts/judge_bpc_tab_development_joint_support_novel_p1e_20260714.py"
)
PRIMARY_SCORER = Path(__file__).absolute()
NOVEL_SCORER = LAKATO_ROOT / (
    "scripts/judge_bpc_tab_development_joint_support_1pct_novel_p1f_20260714.py"
)
PROTOCOL = BPC_ROOT / (
    "evidence/bpc_tab_bolt_development_joint_support_1pct_protocol_20260714.json"
)
PUBLIC_RESULT = BPC_ROOT / (
    "evidence/bpc_tab_bolt_development_joint_support_1pct_result_20260714.json"
)
FIXED_JUNIT = BPC_ROOT / (
    "evidence/bpc_tab_bolt_development_joint_support_1pct_conformance_20260714.xml"
)
P1E_PRIVATE_RECEIPT = P1E_PRIVATE_ROOT / (
    "bpc_tab_bolt_development_joint_support_census_private_receipt_20260714.json"
)
P1F_PRIVATE_RECEIPT = P1F_PRIVATE_ROOT / (
    "bpc_tab_bolt_development_joint_support_1pct_private_receipt_20260714.json"
)

THRESHOLD_SCRIPT_SHA256 = (
    "5c7cd17de907ea69708e91ed737f435d78b0ca2c2290b579a1f1dfe18259c5eb"
)
TEST_MODULE_SHA256 = "32b965fece2f921a491e90ba1acd0960a2f296004e5e50db4775d1349e7332f1"
P1E_NOVEL_SCORER_SHA256 = (
    "3650aca875c5d0aae147ec7a4aef43fed61b1481ece6285f884726a0f9701c61"
)
P1E_PRIVATE_RECEIPT_SHA256 = (
    "a3b035a7a44f9124d24c6f54886f4d2781e62110ee1c7d7d68da1cdaed666ee0"
)
P1D_PRIVATE_RECEIPT_SHA256 = (
    "a30067e64a1dafb9b19d3762c49c09a4f4e8edd98555b35f293ad9c074128685"
)

PROTOCOL_SCHEMA = "bpc.tab_bolt.development_joint_support_1pct_preregistration.v1"
PROTOCOL_STATUS = "PREREGISTERED_P1F_SEALED_SECONDARY_VALUES_DECLARED_UNREAD"
CLAIM_SCOPE = "ACTUAL_DEVELOPMENT_DECODED_CYCLE_JOINT_SUPPORT_1PCT_THRESHOLD_ONLY"
PRIVATE_RECEIPT_SCHEMA = (
    "bpc.tab_bolt.development_joint_support_1pct_private_receipt.v1"
)
PUBLIC_RESULT_SCHEMA = "bpc.tab_bolt.development_joint_support_1pct_result.v1"
P1E_PRIVATE_RECEIPT_SCHEMA = (
    "bpc.tab_bolt.development_decoded_cycle_joint_support_private_receipt.v1"
)
TREE = "LakatosTree_BPC_TabBolt_Inference_20260701"
QUESTION = "q_bpc_development_joint_support_at_least_1pct_all_views_20260714"
NODE_TAG = "tab_development_joint_support_1pct_p1f_20260714"
PARENT_NODE = "tab_development_decoded_cycle_joint_support_p1e_20260714"
PRIMARY_METRIC = "development_joint_support_1pct_conformance_gate_count"
NOVEL_METRIC = "actual_development_views_with_at_least_1pct_joint_finite_support"

EXPECTED_TOTAL = 9
EXPECTED_VIEWS = 23
PIXELS_PER_VIEW = 5_013_504
THRESHOLD_NUMERATOR = 100
THRESHOLD_DENOMINATOR = 10_000
THRESHOLD_BASIS_POINTS = 100
MINIMUM_JOINT_FINITE_PIXEL_COUNT = 50_136
CLASSNAME = "tests.test_tab_bolt_development_joint_support_1pct_threshold"
TEST_NAMES = frozenset(
    {
        "test_fake_exact_twenty_three_view_one_percent_threshold_pass",
        "test_threshold_boundary_is_exact_ceiling_of_one_percent",
        "test_threshold_rejects_private_receipt_hash_schema_or_lineage_drift",
        "test_threshold_rejects_per_view_order_schema_or_count_commitment_drift",
        "test_below_threshold_view_is_counted_without_execution_failure",
        "test_threshold_rejects_unsafe_input_or_output_paths_and_modes",
        "test_threshold_never_clobbers_or_follows_replaced_output_parent",
        "test_public_result_omits_private_counts_commitments_and_overclaims",
        "test_committed_actual_joint_support_receipt_meets_one_percent_in_all_views",
    }
)
MAX_SMALL_FILE_BYTES = 16 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

NEGATIVE_CLAIM_KEYS = frozenset(
    {
        "strict_v1_provenance_established",
        "literal_role_atlas_established",
        "raw_to_p1b_campaign_staged",
        "calibration_or_absolute_measurement_established",
        "physical_accuracy_established",
        "campaign_720_replayed",
        "production_ready_or_changed",
    }
)
PER_VIEW_THRESHOLD_KEYS = frozenset(
    {
        "view_index",
        "view_token",
        "joint_finite_pixel_count",
        "threshold_met",
    }
)
PRIVATE_RECEIPT_KEYS = frozenset(
    {
        "schema",
        "status",
        "claim_scope",
        "protocol_sha256",
        "input_private_census_receipt_sha256",
        "input_private_decode_receipt_sha256",
        "evaluated_view_count",
        "evaluated_array_file_count",
        "organized_image_shape",
        "pixels_per_view",
        "row_chunk_size",
        "threshold_numerator",
        "threshold_denominator",
        "minimum_joint_finite_pixel_count",
        "aggregate_joint_support_count_commitment_sha256",
        "per_view",
        "views_meeting_joint_finite_support_threshold",
        "all_views_meet_joint_finite_support_threshold",
    }
    | NEGATIVE_CLAIM_KEYS
)
PUBLIC_RESULT_KEYS = frozenset(
    {
        "schema",
        "status",
        "claim_scope",
        "protocol_sha256",
        "input_private_census_receipt_sha256",
        "private_threshold_receipt_sha256",
        "evaluated_view_count",
        "pixels_per_view",
        "threshold_numerator",
        "threshold_denominator",
        "minimum_joint_finite_pixel_count",
        "views_meeting_joint_finite_support_threshold",
        "all_views_meet_joint_finite_support_threshold",
    }
    | NEGATIVE_CLAIM_KEYS
)
PUBLIC_ALLOWED_HASH_KEYS = frozenset(
    {
        "protocol_sha256",
        "input_private_census_receipt_sha256",
        "private_threshold_receipt_sha256",
    }
)
PUBLIC_FORBIDDEN_KEYS = frozenset(
    {
        "view_index",
        "view_indices",
        "view_token",
        "per_view",
        "per_view_counts",
        "joint_finite_pixel_count",
        "input_private_decode_receipt_sha256",
        "aggregate_joint_support_count_commitment_sha256",
        "source_path",
        "private_receipt_path",
    }
)


class ScoreRejected(RuntimeError):
    """Fail closed without echoing private paths, counts, or commitments."""


def _reject() -> None:
    raise ScoreRejected("E_P1F_JOINT_SUPPORT_1PCT_PRIMARY_REJECTED")


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


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        _reject()


def _exact_keys(value: Any, expected: frozenset[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != expected:
        _reject()
    return value


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and SHA256_RE.fullmatch(value) is not None
        and value != "0" * 64
    )


def _walk_keys(value: Any) -> Iterable[str]:
    if type(value) is dict:
        for key, nested in value.items():
            yield key
            yield from _walk_keys(nested)
    elif type(value) is list:
        for nested in value:
            yield from _walk_keys(nested)


def _walk_string_values(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif type(value) is dict:
        for nested in value.values():
            yield from _walk_string_values(nested)
    elif type(value) is list:
        for nested in value:
            yield from _walk_string_values(nested)


def _verify_assets() -> dict[str, Any]:
    for path, committed in (
        (THRESHOLD_SCRIPT, THRESHOLD_SCRIPT_SHA256),
        (TEST_MODULE, TEST_MODULE_SHA256),
        (P1E_NOVEL_SCORER, P1E_NOVEL_SCORER_SHA256),
    ):
        if hashlib.sha256(_stable_regular_bytes(path)).hexdigest() != committed:
            _reject()
    p1e_raw = _stable_regular_bytes(P1E_PRIVATE_RECEIPT, required_mode=0o600)
    if hashlib.sha256(p1e_raw).hexdigest() != P1E_PRIVATE_RECEIPT_SHA256:
        _reject()
    p1e = _load_json(p1e_raw)
    if (
        p1e.get("schema") != P1E_PRIVATE_RECEIPT_SCHEMA
        or p1e.get("status") != "PASS"
        or p1e.get("evaluated_view_count") != EXPECTED_VIEWS
        or p1e.get("evaluated_array_file_count") != 46
        or p1e.get("organized_image_shape") != [2048, 2448]
        or p1e.get("pixels_per_view") != PIXELS_PER_VIEW
        or p1e.get("row_chunk_size") != 128
        or p1e.get("input_private_decode_receipt_sha256") != P1D_PRIVATE_RECEIPT_SHA256
        or not _is_sha256(p1e.get("aggregate_joint_support_count_commitment_sha256"))
    ):
        _reject()
    return p1e


def _validate_scope_boundaries(protocol: Mapping[str, Any]) -> None:
    boundaries = protocol.get("scope_boundaries")
    if type(boundaries) is not dict or (
        boundaries.get("development_view_count") != EXPECTED_VIEWS
        or boundaries.get("joint_support_1pct_threshold_only") is not True
        or any(boundaries.get(name) is not False for name in NEGATIVE_CLAIM_KEYS)
    ):
        _reject()


def _validate_threshold_contract(protocol: Mapping[str, Any]) -> None:
    threshold = protocol.get("threshold_contract")
    if (
        type(threshold) is not dict
        or set(threshold)
        != {
            "pixels_per_view",
            "threshold_numerator",
            "threshold_denominator",
            "minimum_joint_finite_pixel_count",
        }
        or (
            threshold.get("pixels_per_view") != PIXELS_PER_VIEW
            or threshold.get("threshold_numerator") != THRESHOLD_NUMERATOR
            or threshold.get("threshold_denominator") != THRESHOLD_DENOMINATOR
            or THRESHOLD_NUMERATOR * 10_000
            != THRESHOLD_BASIS_POINTS * THRESHOLD_DENOMINATOR
            or (PIXELS_PER_VIEW * THRESHOLD_NUMERATOR + THRESHOLD_DENOMINATOR - 1)
            // THRESHOLD_DENOMINATOR
            != MINIMUM_JOINT_FINITE_PIXEL_COUNT
            or threshold.get("minimum_joint_finite_pixel_count")
            != MINIMUM_JOINT_FINITE_PIXEL_COUNT
        )
    ):
        _reject()


def _validate_sealed_secondary_disclosure(protocol: Mapping[str, Any]) -> None:
    sealed = protocol.get("sealed_secondary_analysis_disclosure")
    if type(sealed) is not dict or (
        sealed.get("p1e_private_per_view_values_preexist") is not True
        or sealed.get("p1e_public_nonzero_aggregate_known_before_p1f") is not True
        or sealed.get("p1f_analyst_unread_custody_declaration") is not True
        or sealed.get("cryptographic_or_access_log_proof_of_unread") is not False
        or sealed.get("independent_new_data_or_replication") is not False
    ):
        _reject()
    if set(sealed) != {
        "p1e_private_per_view_values_preexist",
        "p1e_public_nonzero_aggregate_known_before_p1f",
        "p1f_analyst_unread_custody_declaration",
        "cryptographic_or_access_log_proof_of_unread",
        "independent_new_data_or_replication",
    }:
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
        or protocol.get("input_private_census_receipt_sha256")
        != P1E_PRIVATE_RECEIPT_SHA256
        or protocol.get("production_change") is not False
        or protocol.get("static_preflight_only") is not True
    ):
        _reject()
    _validate_scope_boundaries(protocol)
    _validate_threshold_contract(protocol)
    _validate_sealed_secondary_disclosure(protocol)

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
        or credence != 0.80
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
        or inventory.get("actual_private_secondary_cases") != 1
    ):
        _reject()

    strings = set(_walk_string_values(protocol))
    required_hashes = {
        THRESHOLD_SCRIPT_SHA256,
        TEST_MODULE_SHA256,
        P1E_NOVEL_SCORER_SHA256,
        P1E_PRIVATE_RECEIPT_SHA256,
        hashlib.sha256(_stable_regular_bytes(PRIMARY_SCORER)).hexdigest(),
        hashlib.sha256(_stable_regular_bytes(NOVEL_SCORER)).hexdigest(),
    }
    required_paths = {
        str(THRESHOLD_SCRIPT),
        str(TEST_MODULE),
        str(P1E_NOVEL_SCORER),
        str(PRIMARY_SCORER),
        str(NOVEL_SCORER),
        str(PROTOCOL),
        str(PUBLIC_RESULT),
        str(FIXED_JUNIT),
        str(P1E_PRIVATE_RECEIPT),
        str(P1F_PRIVATE_RECEIPT),
    }
    if not required_hashes.issubset(strings) or not required_paths.issubset(strings):
        _reject()


def _validate_private_root() -> None:
    try:
        root = P1F_PRIVATE_ROOT.lstat()
    except OSError:
        _reject()
    if (
        stat.S_ISLNK(root.st_mode)
        or not stat.S_ISDIR(root.st_mode)
        or stat.S_IMODE(root.st_mode) != 0o700
    ):
        _reject()


def _threshold_projection(
    raw_records: Any,
) -> tuple[list[dict[str, Any]], int]:
    if type(raw_records) is not list or len(raw_records) != EXPECTED_VIEWS:
        _reject()
    projected: list[dict[str, Any]] = []
    for expected_index, raw in enumerate(raw_records):
        record = _exact_keys(raw, PER_VIEW_THRESHOLD_KEYS)
        joint_count = record.get("joint_finite_pixel_count")
        meets = record.get("threshold_met")
        if (
            record.get("view_index") != expected_index
            or record.get("view_token") != f"v{expected_index:02d}"
            or type(joint_count) is not int
            or isinstance(joint_count, bool)
            or not 0 <= joint_count <= PIXELS_PER_VIEW
            or meets is not (joint_count >= MINIMUM_JOINT_FINITE_PIXEL_COUNT)
        ):
            _reject()
        projected.append(dict(record))
    return projected, sum(record["threshold_met"] for record in projected)


def _validate_public_privacy(public: Mapping[str, Any], raw: bytes) -> None:
    keys = set(_walk_keys(public))
    if keys & PUBLIC_FORBIDDEN_KEYS:
        _reject()
    for key in keys:
        if key.endswith("_sha256") and key not in PUBLIC_ALLOWED_HASH_KEYS:
            _reject()
        if key.endswith(("_path", "_directory", "_target")):
            _reject()
        if key.startswith("per_view") or key in {"view_index", "view_indices"}:
            _reject()
    lowered = raw.lower()
    if any(
        token in lowered
        for token in (
            b"/data/",
            b".private_bpc",
            b".zdf",
            b".npy",
            b"v00",
            b"joint_finite_pixel_count",
        )
    ):
        _reject()


def _validate_output_chain(protocol_raw: bytes, p1e: Mapping[str, Any]) -> None:
    _validate_private_root()
    protocol_sha256 = hashlib.sha256(protocol_raw).hexdigest()
    private_raw = _stable_regular_bytes(P1F_PRIVATE_RECEIPT, required_mode=0o600)
    receipt = _exact_keys(_load_json(private_raw), PRIVATE_RECEIPT_KEYS)
    _, views_meeting = _threshold_projection(receipt.get("per_view"))
    if (
        _canonical_json_bytes(receipt) != private_raw
        or receipt.get("schema") != PRIVATE_RECEIPT_SCHEMA
        or receipt.get("status") != "PASS"
        or receipt.get("claim_scope") != CLAIM_SCOPE
        or receipt.get("protocol_sha256") != protocol_sha256
        or receipt.get("input_private_census_receipt_sha256")
        != P1E_PRIVATE_RECEIPT_SHA256
        or receipt.get("input_private_decode_receipt_sha256")
        != P1D_PRIVATE_RECEIPT_SHA256
        or receipt.get("evaluated_array_file_count") != 46
        or receipt.get("organized_image_shape") != [2048, 2448]
        or receipt.get("row_chunk_size") != 128
        or receipt.get("aggregate_joint_support_count_commitment_sha256")
        != p1e.get("aggregate_joint_support_count_commitment_sha256")
        or receipt.get("evaluated_view_count") != EXPECTED_VIEWS
        or receipt.get("pixels_per_view") != PIXELS_PER_VIEW
        or receipt.get("threshold_numerator") != THRESHOLD_NUMERATOR
        or receipt.get("threshold_denominator") != THRESHOLD_DENOMINATOR
        or receipt.get("minimum_joint_finite_pixel_count")
        != MINIMUM_JOINT_FINITE_PIXEL_COUNT
        or receipt.get("views_meeting_joint_finite_support_threshold") != views_meeting
        or receipt.get("all_views_meet_joint_finite_support_threshold")
        is not (views_meeting == EXPECTED_VIEWS)
        or any(receipt.get(name) is not False for name in NEGATIVE_CLAIM_KEYS)
    ):
        _reject()

    private_sha256 = hashlib.sha256(private_raw).hexdigest()
    public_raw = _stable_regular_bytes(PUBLIC_RESULT, required_mode=0o444)
    public = _exact_keys(_load_json(public_raw), PUBLIC_RESULT_KEYS)
    if (
        _canonical_json_bytes(public) != public_raw
        or public.get("schema") != PUBLIC_RESULT_SCHEMA
        or public.get("status") != "PASS"
        or public.get("claim_scope") != CLAIM_SCOPE
        or public.get("protocol_sha256") != protocol_sha256
        or public.get("input_private_census_receipt_sha256")
        != P1E_PRIVATE_RECEIPT_SHA256
        or public.get("private_threshold_receipt_sha256") != private_sha256
        or public.get("evaluated_view_count") != EXPECTED_VIEWS
        or public.get("pixels_per_view") != PIXELS_PER_VIEW
        or public.get("threshold_numerator") != THRESHOLD_NUMERATOR
        or public.get("threshold_denominator") != THRESHOLD_DENOMINATOR
        or public.get("minimum_joint_finite_pixel_count")
        != MINIMUM_JOINT_FINITE_PIXEL_COUNT
        or public.get("views_meeting_joint_finite_support_threshold") != views_meeting
        or public.get("all_views_meet_joint_finite_support_threshold")
        is not (views_meeting == EXPECTED_VIEWS)
        or any(public.get(name) is not False for name in NEGATIVE_CLAIM_KEYS)
    ):
        _reject()
    _validate_public_privacy(public, public_raw)
    observed_hashes = {
        value for value in _walk_string_values(public) if _is_sha256(value)
    }
    if observed_hashes != {
        protocol_sha256,
        P1E_PRIVATE_RECEIPT_SHA256,
        private_sha256,
    }:
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
    """Return nine only for the complete frozen P1f conformance chain."""

    p1e = _verify_assets()
    protocol_raw = _stable_regular_bytes(PROTOCOL)
    _validate_protocol(_load_json(protocol_raw))
    _validate_output_chain(protocol_raw, p1e)
    return _score_junit()


def main() -> int:
    try:
        if len(sys.argv) != 2 or not _same_fixed_path(sys.argv[1], FIXED_JUNIT):
            _reject()
        metric = score()
    except Exception:
        sys.stderr.write("E_P1F_JOINT_SUPPORT_1PCT_PRIMARY_REJECTED\n")
        return 2
    print(f"metric={metric}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
