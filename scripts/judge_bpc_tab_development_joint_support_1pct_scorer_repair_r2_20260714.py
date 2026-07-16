#!/usr/bin/env python3
"""Adjudicate the P1f R1 evidence with one narrowly repaired privacy gate.

The R1 measurement and every R1 artifact remain frozen.  This R2 judge only
removes an impossible raw-substring check: the forbidden token
``joint_finite_pixel_count`` is a suffix of the explicitly allowed public key
``minimum_joint_finite_pixel_count``.  Exact public/private keysets, allowed
hash keys, path checks, canonical JSON, modes, commitments, and the complete
private/public receipt chain remain mandatory.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Iterable, Mapping, Sequence
import xml.etree.ElementTree as ET


BPC_ROOT = Path("/data/kjra/PROJECT/3DLAB/BPC_ICP_SPEC")
LAKATO_ROOT = Path("/data/kjra/PROJECT/PI/lakatotree")
P1E_PRIVATE_ROOT = Path("/data/kjra/PROJECT/3DLAB/.private_bpc_p1e")
P1F_PRIVATE_ROOT = Path("/data/kjra/PROJECT/3DLAB/.private_bpc_p1f")

THRESHOLD_SCRIPT = BPC_ROOT / (
    "scripts/tab_bolt_development_joint_support_1pct_threshold.py"
)
FROZEN_TEST_MODULE = BPC_ROOT / (
    "tests/test_tab_bolt_development_joint_support_1pct_threshold.py"
)
REPAIR_TEST_MODULE = BPC_ROOT / (
    "tests/test_tab_bolt_development_joint_support_1pct_scorer_repair_r2.py"
)
R1_PRIMARY_SCORER = LAKATO_ROOT / (
    "scripts/judge_bpc_tab_development_joint_support_1pct_p1f_20260714.py"
)
R1_NOVEL_SCORER = LAKATO_ROOT / (
    "scripts/judge_bpc_tab_development_joint_support_1pct_novel_p1f_20260714.py"
)
P1E_NOVEL_SCORER = LAKATO_ROOT / (
    "scripts/judge_bpc_tab_development_joint_support_novel_p1e_20260714.py"
)
PRIMARY_SCORER = Path(__file__).absolute()
CONFIRMATORY_SCORER = LAKATO_ROOT / (
    "scripts/"
    "judge_bpc_tab_development_joint_support_1pct_scorer_repair_confirmatory_r2_20260714.py"
)

R1_PROTOCOL = BPC_ROOT / (
    "evidence/bpc_tab_bolt_development_joint_support_1pct_protocol_20260714.json"
)
R1_JUNIT = BPC_ROOT / (
    "evidence/bpc_tab_bolt_development_joint_support_1pct_conformance_20260714.xml"
)
R1_PUBLIC_RESULT = BPC_ROOT / (
    "evidence/bpc_tab_bolt_development_joint_support_1pct_result_20260714.json"
)
R1_FAILURE_EVIDENCE = BPC_ROOT / (
    "evidence/"
    "bpc_tab_bolt_development_joint_support_1pct_r1_scorer_failure_20260714.json"
)
R2_PROTOCOL = BPC_ROOT / (
    "evidence/"
    "bpc_tab_bolt_development_joint_support_1pct_scorer_repair_r2_protocol_20260714.json"
)
R2_JUNIT = BPC_ROOT / (
    "evidence/"
    "bpc_tab_bolt_development_joint_support_1pct_scorer_repair_r2_conformance_20260714.xml"
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
FROZEN_TEST_MODULE_SHA256 = (
    "32b965fece2f921a491e90ba1acd0960a2f296004e5e50db4775d1349e7332f1"
)
REPAIR_TEST_MODULE_SHA256 = (
    "cadc9c5b5d4b7aba8dd1675a2517ef036d04dfc34d51688597ea668e6fbc044b"
)
R1_PRIMARY_SCORER_SHA256 = (
    "76f92bce8757f654c72e4b529d20fb46fe0d7e0fb031e82d90eb8ecf31de3f84"
)
R1_NOVEL_SCORER_SHA256 = (
    "6a9560dd220cda85bfde2dcf3498fd92b6de96c710159ce5101372440fb7481d"
)
P1E_NOVEL_SCORER_SHA256 = (
    "3650aca875c5d0aae147ec7a4aef43fed61b1481ece6285f884726a0f9701c61"
)
R1_PROTOCOL_SHA256 = "81b61e977f71c1b9d907f7a9b440f8303f5e72eadabc66bf93e5e1d82a4968e3"
R1_JUNIT_SHA256 = "487ef2f419f54764c34a552355436754502eb3f9c5ca8d7e13a5bc9c955023f5"
R1_PUBLIC_RESULT_SHA256 = (
    "2b7fb11d188013703aa18d04fc999698baa9235c27ba988ee31e9fb2f1f2646f"
)
P1F_PRIVATE_RECEIPT_SHA256 = (
    "8f0e0c170026aae57343376b158bcfd3893f22f3b3f594a239eb9e5a10e88fc2"
)
R1_FAILURE_EVIDENCE_SHA256 = (
    "c8c03f619b68b378035eb6d1a6d8139862d8767a75f474b89206d8327522c2b9"
)
P1E_PRIVATE_RECEIPT_SHA256 = (
    "a3b035a7a44f9124d24c6f54886f4d2781e62110ee1c7d7d68da1cdaed666ee0"
)
P1D_PRIVATE_RECEIPT_SHA256 = (
    "a30067e64a1dafb9b19d3762c49c09a4f4e8edd98555b35f293ad9c074128685"
)

R1_PROTOCOL_SCHEMA = "bpc.tab_bolt.development_joint_support_1pct_preregistration.v1"
R1_PROTOCOL_STATUS = "PREREGISTERED_P1F_SEALED_SECONDARY_VALUES_DECLARED_UNREAD"
R2_PROTOCOL_SCHEMA = (
    "bpc.tab_bolt.development_joint_support_1pct_scorer_repair_preregistration.v1"
)
R2_PROTOCOL_STATUS = "PREREGISTERED_R2_EXISTING_RESULT_KNOWN_REPAIR_UNRUN"
P1F_CLAIM_SCOPE = "ACTUAL_DEVELOPMENT_DECODED_CYCLE_JOINT_SUPPORT_1PCT_THRESHOLD_ONLY"
REPAIR_CLAIM_SCOPE = "P1F_EXISTING_EVIDENCE_SCORER_REPAIR_ONLY"
P1E_CLAIM_SCOPE = "ACTUAL_DEVELOPMENT_DECODED_CYCLE_JOINT_SUPPORT_CENSUS_ONLY"
P1F_PRIVATE_RECEIPT_SCHEMA = (
    "bpc.tab_bolt.development_joint_support_1pct_private_receipt.v1"
)
P1F_PUBLIC_RESULT_SCHEMA = "bpc.tab_bolt.development_joint_support_1pct_result.v1"
P1E_PRIVATE_RECEIPT_SCHEMA = (
    "bpc.tab_bolt.development_decoded_cycle_joint_support_private_receipt.v1"
)
R1_FAILURE_SCHEMA = "bpc.tab_bolt.development_joint_support_1pct_scorer_failure.v1"

TREE = "LakatosTree_BPC_TabBolt_Inference_20260701"
QUESTION = "q_bpc_development_joint_support_1pct_scorer_repair_20260714"
NODE_TAG = "tab_development_joint_support_1pct_scorer_repair_r2_20260714"
PARENT_NODE = "tab_development_decoded_cycle_joint_support_p1e_20260714"
PRIMARY_METRIC = "development_joint_support_1pct_scorer_repair_gate_count"
EXPECTED_REPAIR_TOTAL = 6
EXPECTED_R1_TOTAL = 9
EXPECTED_VIEWS = 23
EXPECTED_ARRAYS = 46
EXPECTED_HEIGHT = 2048
EXPECTED_WIDTH = 2448
PIXELS_PER_VIEW = 5_013_504
ROW_CHUNK_SIZE = 128
THRESHOLD_NUMERATOR = 100
THRESHOLD_DENOMINATOR = 10_000
MINIMUM_JOINT_FINITE_PIXEL_COUNT = 50_136
MAX_SMALL_FILE_BYTES = 16 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
P1E_COUNT_COMMITMENT_DOMAIN = (
    "BPC_TAB_BOLT_DEVELOPMENT_DECODED_CYCLE_JOINT_SUPPORT_COUNTS_V1"
)

R1_CLASSNAME = "tests.test_tab_bolt_development_joint_support_1pct_threshold"
R1_TEST_NAMES = frozenset(
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
REPAIR_CLASSNAME = "tests.test_tab_bolt_development_joint_support_1pct_scorer_repair_r2"
REPAIR_TEST_NAMES = frozenset(
    {
        "test_r1_privacy_gate_reproduces_allowed_key_substring_false_positive",
        "test_r2_privacy_gate_accepts_exact_allowed_minimum_key",
        "test_r2_privacy_gate_rejects_direct_private_count_keys",
        "test_r2_privacy_gate_rejects_private_paths_and_array_tokens",
        "test_r2_privacy_gate_rejects_noncanonical_or_unexpected_hash_keys",
        "test_preserved_p1f_chain_passes_repaired_primary_adjudication",
    }
)
R2_PROTOCOL_KEYS = frozenset(
    {
        "schema",
        "date",
        "status",
        "tree",
        "question",
        "node_tag",
        "parent_node_tag",
        "claim_scope",
        "execution_boundary",
        "research_question",
        "known_existing_result_disclosure",
        "scientific_threshold_contract",
        "repair_diff",
        "r1_failure_lineage",
        "confirmatory_replay_contract",
        "scope_boundaries",
        "prediction",
        "frozen_assets",
        "test_inventory",
        "execution",
        "static_preflight_only",
        "static_preflight_details",
        "success_rule",
        "explicit_non_claims",
    }
)
KNOWN_RESULT_DISCLOSURE_KEYS = frozenset(
    {
        "result_known_before_r2",
        "producer_or_measurement_rerun",
        "r1_protocol_sha256",
        "r1_public_result_sha256",
        "r1_junit_sha256",
        "r1_private_receipt_sha256",
    }
)
SCIENTIFIC_THRESHOLD_CONTRACT_KEYS = frozenset(
    {
        "pixels_per_view",
        "threshold_numerator",
        "threshold_denominator",
        "minimum_joint_finite_pixel_count",
        "scientific_threshold_unchanged",
    }
)
CONFIRMATORY_REPLAY_CONTRACT_KEYS = frozenset(
    {
        "already_public_aggregate",
        "result_known_before_r2",
        "planned_after_primary_repair",
        "lakato_novel_claimed",
        "new_data_generated",
        "independent_new_data_or_replication",
    }
)

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
SCOPE_BOUNDARY_KEYS = NEGATIVE_CLAIM_KEYS | frozenset(
    {
        "scorer_repair_only",
        "measurement_rerun",
        "already_public_aggregate_reclassified_as_novel",
    }
)
P1E_COUNT_RECORD_KEYS = frozenset(
    {
        "view_index",
        "view_token",
        "pixel_count",
        "xyz_finite_pixel_count",
        "snr_finite_pixel_count",
        "joint_finite_pixel_count",
    }
)
P1E_PRIVATE_RECEIPT_KEYS = frozenset(
    {
        "schema",
        "status",
        "claim_scope",
        "protocol_sha256",
        "input_private_decode_receipt_sha256",
        "private_bundle_manifest_sha256",
        "aggregate_export_commitment_sha256",
        "evaluated_view_count",
        "evaluated_array_file_count",
        "organized_image_shape",
        "pixels_per_view",
        "row_chunk_size",
        "input_file_pre_census_commitment_verified_count",
        "input_file_post_census_commitment_verified_count",
        "per_view",
        "aggregate_joint_support_count_commitment_sha256",
        "views_with_nonzero_joint_finite_support",
        "all_views_have_nonzero_joint_finite_support",
    }
    | NEGATIVE_CLAIM_KEYS
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
REPAIR_DIFF_KEYS = frozenset(
    {
        "frozen_r1_primary_sha256",
        "repaired_r2_primary_sha256",
        "allowed_public_key",
        "removed_overbroad_raw_substring",
        "exact_public_keyset_gate_retained",
        "canonical_public_bytes_gate_retained",
        "unexpected_hash_key_gate_retained",
        "private_path_and_array_token_gates_retained",
        "producer_or_measurement_artifacts_overwritten",
    }
)
R1_FAILURE_LINEAGE_KEYS = frozenset(
    {
        "failure_audit_sha256",
        "r1_node_tag",
        "r1_question",
        "r1_protocol_sha256",
        "r1_prediction_receipt_sha256",
        "r1_primary_scorer_sha256",
        "r1_junit_sha256",
        "r1_public_result_sha256",
        "r1_private_receipt_sha256",
        "process_returncode",
        "metric_emitted",
        "classification",
        "input_or_measurement_failure",
        "scientific_threshold_result_refuted",
        "r1_measurement_preserved",
        "r1_false_rejection_preserved",
    }
)


class ScoreRejected(RuntimeError):
    """Fail closed without echoing a private value, path, or commitment."""


def _reject() -> None:
    raise ScoreRejected("E_P1F_JOINT_SUPPORT_1PCT_SCORER_REPAIR_R2_REJECTED")


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


def _validate_public_privacy(public: Mapping[str, Any], raw: bytes) -> None:
    """Apply the repaired exact-key privacy gate to one public result."""

    exact = _exact_keys(public, PUBLIC_RESULT_KEYS)
    if _canonical_json_bytes(exact) != raw:
        _reject()
    keys = set(_walk_keys(exact))
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
        )
    ):
        _reject()


def _validate_private_roots() -> tuple[tuple[int, ...], tuple[int, ...]]:
    try:
        p1e = P1E_PRIVATE_ROOT.lstat()
        p1f = P1F_PRIVATE_ROOT.lstat()
    except OSError:
        _reject()
    if (
        stat.S_ISLNK(p1e.st_mode)
        or not stat.S_ISDIR(p1e.st_mode)
        or stat.S_IMODE(p1e.st_mode) != 0o700
        or stat.S_ISLNK(p1f.st_mode)
        or not stat.S_ISDIR(p1f.st_mode)
        or stat.S_IMODE(p1f.st_mode) != 0o700
    ):
        _reject()
    return _fingerprint(p1e), _fingerprint(p1f)


def _count_commitment(per_view: Sequence[Mapping[str, Any]]) -> str:
    return hashlib.sha256(
        _canonical_json_bytes(
            {"domain": P1E_COUNT_COMMITMENT_DOMAIN, "per_view": list(per_view)}
        )
    ).hexdigest()


def _validate_p1e_receipt(raw: bytes) -> tuple[list[dict[str, Any]], str]:
    if hashlib.sha256(raw).hexdigest() != P1E_PRIVATE_RECEIPT_SHA256:
        _reject()
    receipt = _exact_keys(_load_json(raw), P1E_PRIVATE_RECEIPT_KEYS)
    per_view = receipt.get("per_view")
    if type(per_view) is not list or len(per_view) != EXPECTED_VIEWS:
        _reject()
    records: list[dict[str, Any]] = []
    for expected_index, raw_record in enumerate(per_view):
        record = _exact_keys(raw_record, P1E_COUNT_RECORD_KEYS)
        values = {
            key: record.get(key) for key in P1E_COUNT_RECORD_KEYS - {"view_token"}
        }
        if (
            record.get("view_index") != expected_index
            or record.get("view_token") != f"v{expected_index:02d}"
            or record.get("pixel_count") != PIXELS_PER_VIEW
            or any(
                type(value) is not int
                or isinstance(value, bool)
                or not 0 <= value <= PIXELS_PER_VIEW
                for value in values.values()
            )
            or not 0
            <= record["joint_finite_pixel_count"]
            <= min(
                record["xyz_finite_pixel_count"],
                record["snr_finite_pixel_count"],
            )
            <= PIXELS_PER_VIEW
        ):
            _reject()
        records.append(dict(record))
    count_commitment = _count_commitment(records)
    views_nonzero = sum(record["joint_finite_pixel_count"] > 0 for record in records)
    if (
        _canonical_json_bytes(receipt) != raw
        or receipt.get("schema") != P1E_PRIVATE_RECEIPT_SCHEMA
        or receipt.get("status") != "PASS"
        or receipt.get("claim_scope") != P1E_CLAIM_SCOPE
        or receipt.get("input_private_decode_receipt_sha256")
        != P1D_PRIVATE_RECEIPT_SHA256
        or not _is_sha256(receipt.get("protocol_sha256"))
        or not _is_sha256(receipt.get("private_bundle_manifest_sha256"))
        or not _is_sha256(receipt.get("aggregate_export_commitment_sha256"))
        or receipt.get("evaluated_view_count") != EXPECTED_VIEWS
        or receipt.get("evaluated_array_file_count") != EXPECTED_ARRAYS
        or receipt.get("organized_image_shape") != [EXPECTED_HEIGHT, EXPECTED_WIDTH]
        or receipt.get("pixels_per_view") != PIXELS_PER_VIEW
        or receipt.get("row_chunk_size") != ROW_CHUNK_SIZE
        or receipt.get("input_file_pre_census_commitment_verified_count")
        != EXPECTED_ARRAYS
        or receipt.get("input_file_post_census_commitment_verified_count")
        != EXPECTED_ARRAYS
        or receipt.get("aggregate_joint_support_count_commitment_sha256")
        != count_commitment
        or receipt.get("views_with_nonzero_joint_finite_support") != views_nonzero
        or receipt.get("all_views_have_nonzero_joint_finite_support")
        is not (views_nonzero == EXPECTED_VIEWS)
        or views_nonzero != EXPECTED_VIEWS
        or any(receipt.get(name) is not False for name in NEGATIVE_CLAIM_KEYS)
    ):
        _reject()
    return records, count_commitment


def _derive_threshold_records(
    p1e_records: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    if len(p1e_records) != EXPECTED_VIEWS:
        _reject()
    derived = [
        {
            "view_index": expected_index,
            "view_token": f"v{expected_index:02d}",
            "joint_finite_pixel_count": record["joint_finite_pixel_count"],
            "threshold_met": (
                record["joint_finite_pixel_count"] >= MINIMUM_JOINT_FINITE_PIXEL_COUNT
            ),
        }
        for expected_index, record in enumerate(p1e_records)
    ]
    return derived, sum(record["threshold_met"] for record in derived)


def _validate_p1f_output_chain(
    *,
    p1e_records: Sequence[Mapping[str, Any]],
    p1e_count_commitment: str,
) -> int:
    derived, views_meeting = _derive_threshold_records(p1e_records)
    private_raw = _stable_regular_bytes(P1F_PRIVATE_RECEIPT, required_mode=0o600)
    if hashlib.sha256(private_raw).hexdigest() != P1F_PRIVATE_RECEIPT_SHA256:
        _reject()
    receipt = _exact_keys(_load_json(private_raw), PRIVATE_RECEIPT_KEYS)
    if (
        _canonical_json_bytes(receipt) != private_raw
        or receipt.get("schema") != P1F_PRIVATE_RECEIPT_SCHEMA
        or receipt.get("status") != "PASS"
        or receipt.get("claim_scope") != P1F_CLAIM_SCOPE
        or receipt.get("protocol_sha256") != R1_PROTOCOL_SHA256
        or receipt.get("input_private_census_receipt_sha256")
        != P1E_PRIVATE_RECEIPT_SHA256
        or receipt.get("input_private_decode_receipt_sha256")
        != P1D_PRIVATE_RECEIPT_SHA256
        or receipt.get("evaluated_view_count") != EXPECTED_VIEWS
        or receipt.get("evaluated_array_file_count") != EXPECTED_ARRAYS
        or receipt.get("organized_image_shape") != [EXPECTED_HEIGHT, EXPECTED_WIDTH]
        or receipt.get("pixels_per_view") != PIXELS_PER_VIEW
        or receipt.get("row_chunk_size") != ROW_CHUNK_SIZE
        or receipt.get("threshold_numerator") != THRESHOLD_NUMERATOR
        or receipt.get("threshold_denominator") != THRESHOLD_DENOMINATOR
        or receipt.get("minimum_joint_finite_pixel_count")
        != MINIMUM_JOINT_FINITE_PIXEL_COUNT
        or receipt.get("aggregate_joint_support_count_commitment_sha256")
        != p1e_count_commitment
        or receipt.get("per_view") != derived
        or receipt.get("views_meeting_joint_finite_support_threshold") != views_meeting
        or receipt.get("all_views_meet_joint_finite_support_threshold")
        is not (views_meeting == EXPECTED_VIEWS)
        or any(receipt.get(name) is not False for name in NEGATIVE_CLAIM_KEYS)
    ):
        _reject()

    public_raw = _stable_regular_bytes(R1_PUBLIC_RESULT, required_mode=0o444)
    if hashlib.sha256(public_raw).hexdigest() != R1_PUBLIC_RESULT_SHA256:
        _reject()
    public = _load_json(public_raw)
    _validate_public_privacy(public, public_raw)
    if (
        public.get("schema") != P1F_PUBLIC_RESULT_SCHEMA
        or public.get("status") != "PASS"
        or public.get("claim_scope") != P1F_CLAIM_SCOPE
        or public.get("protocol_sha256") != R1_PROTOCOL_SHA256
        or public.get("input_private_census_receipt_sha256")
        != P1E_PRIVATE_RECEIPT_SHA256
        or public.get("private_threshold_receipt_sha256") != P1F_PRIVATE_RECEIPT_SHA256
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
    observed_hashes = {
        value for value in _walk_string_values(public) if _is_sha256(value)
    }
    if observed_hashes != {
        R1_PROTOCOL_SHA256,
        P1E_PRIVATE_RECEIPT_SHA256,
        P1F_PRIVATE_RECEIPT_SHA256,
    }:
        _reject()
    return views_meeting


def _integer_attribute(suite: ET.Element, name: str) -> int:
    value = suite.get(name)
    if value is None or not value.isascii() or not value.isdigit():
        _reject()
    return int(value)


def _score_junit(
    path: Path,
    *,
    expected_sha256: str | None,
    expected_total: int,
    classname: str,
    names: frozenset[str],
) -> int:
    raw = _stable_regular_bytes(path)
    if (
        expected_sha256 is not None
        and hashlib.sha256(raw).hexdigest() != expected_sha256
    ):
        _reject()
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
        "tests": expected_total,
        "errors": 0,
        "failures": 0,
        "skipped": 0,
    }:
        _reject()
    cases = list(suite)
    if len(cases) != expected_total or any(case.tag != "testcase" for case in cases):
        _reject()
    observed_names = [case.get("name") for case in cases]
    if (
        len(set(observed_names)) != expected_total
        or set(observed_names) != names
        or any(case.get("classname") != classname for case in cases)
        or any(len(case) != 0 for case in cases)
    ):
        _reject()
    return len(cases)


def _validate_r1_protocol(raw: bytes) -> None:
    if hashlib.sha256(raw).hexdigest() != R1_PROTOCOL_SHA256:
        _reject()
    protocol = _load_json(raw)
    if (
        protocol.get("schema") != R1_PROTOCOL_SCHEMA
        or protocol.get("status") != R1_PROTOCOL_STATUS
        or protocol.get("tree") != TREE
        or protocol.get("claim_scope") != P1F_CLAIM_SCOPE
        or protocol.get("static_preflight_only") is not True
        or protocol.get("production_change") is not False
    ):
        _reject()


def _validate_failure_evidence() -> None:
    raw = _stable_regular_bytes(R1_FAILURE_EVIDENCE)
    if hashlib.sha256(raw).hexdigest() != R1_FAILURE_EVIDENCE_SHA256:
        _reject()
    evidence = _load_json(raw)
    measurement = evidence.get("measurement")
    frozen = evidence.get("frozen_primary_scorer")
    root_cause = evidence.get("root_cause")
    policy = evidence.get("preservation_and_repair_policy")
    if (
        evidence.get("schema") != R1_FAILURE_SCHEMA
        or evidence.get("status")
        != "FIRST_FROZEN_PRIMARY_SCORER_FALSE_REJECTION_PRESERVED"
        or evidence.get("tree") != TREE
        or type(measurement) is not dict
        or measurement.get("pytest_cases") != EXPECTED_R1_TOTAL
        or measurement.get("pytest_passed") != EXPECTED_R1_TOTAL
        or measurement.get("junit_sha256") != R1_JUNIT_SHA256
        or measurement.get("sanitized_public_result_sha256") != R1_PUBLIC_RESULT_SHA256
        or measurement.get("private_threshold_receipt_sha256")
        != P1F_PRIVATE_RECEIPT_SHA256
        or measurement.get("public_views_meeting_threshold") != EXPECTED_VIEWS
        or measurement.get("public_all_views_meet_threshold") is not True
        or measurement.get("measurement_rerun") is not False
        or type(frozen) is not dict
        or frozen.get("sha256") != R1_PRIMARY_SCORER_SHA256
        or frozen.get("process_returncode") != 2
        or frozen.get("metric_emitted") is not False
        or type(root_cause) is not dict
        or root_cause.get("classification")
        != "PUBLIC_PRIVACY_SCORER_SUBSTRING_FALSE_POSITIVE"
        or root_cause.get("allowed_public_key") != "minimum_joint_finite_pixel_count"
        or root_cause.get("overbroad_forbidden_raw_substring")
        != "joint_finite_pixel_count"
        or root_cause.get("input_or_measurement_failure") is not False
        or root_cause.get("private_payload_leak_observed") is not False
        or root_cause.get("scientific_threshold_result_refuted") is not False
        or type(policy) is not dict
        or policy.get(
            "existing_junit_public_result_and_private_receipt_preserved_without_overwrite"
        )
        is not True
        or policy.get("same_node_scorer_mutation_allowed") is not False
        or policy.get("same_measurement_retry_allowed") is not False
        or policy.get("repair_requires_new_protocol_prediction_and_node") is not True
        or policy.get(
            "already_public_23_view_aggregate_may_be_called_novel_after_repair"
        )
        is not False
    ):
        _reject()


def _verify_frozen_file_hashes() -> None:
    for path, committed in (
        (THRESHOLD_SCRIPT, THRESHOLD_SCRIPT_SHA256),
        (FROZEN_TEST_MODULE, FROZEN_TEST_MODULE_SHA256),
        (R1_PRIMARY_SCORER, R1_PRIMARY_SCORER_SHA256),
        (R1_NOVEL_SCORER, R1_NOVEL_SCORER_SHA256),
        (P1E_NOVEL_SCORER, P1E_NOVEL_SCORER_SHA256),
        (R1_PROTOCOL, R1_PROTOCOL_SHA256),
        (R1_JUNIT, R1_JUNIT_SHA256),
        (R1_PUBLIC_RESULT, R1_PUBLIC_RESULT_SHA256),
        (R1_FAILURE_EVIDENCE, R1_FAILURE_EVIDENCE_SHA256),
    ):
        if hashlib.sha256(_stable_regular_bytes(path)).hexdigest() != committed:
            _reject()


def score_preserved_p1f_chain() -> int:
    """Return nine only for the unchanged R1 evidence under the repaired gate."""

    _verify_frozen_file_hashes()
    roots_before = _validate_private_roots()
    protocol_raw = _stable_regular_bytes(R1_PROTOCOL)
    _validate_r1_protocol(protocol_raw)
    p1e_raw = _stable_regular_bytes(P1E_PRIVATE_RECEIPT, required_mode=0o600)
    p1e_records, count_commitment = _validate_p1e_receipt(p1e_raw)
    if (
        _validate_p1f_output_chain(
            p1e_records=p1e_records,
            p1e_count_commitment=count_commitment,
        )
        != EXPECTED_VIEWS
    ):
        _reject()
    _validate_failure_evidence()
    score = _score_junit(
        R1_JUNIT,
        expected_sha256=R1_JUNIT_SHA256,
        expected_total=EXPECTED_R1_TOTAL,
        classname=R1_CLASSNAME,
        names=R1_TEST_NAMES,
    )
    if (
        _stable_regular_bytes(P1E_PRIVATE_RECEIPT, required_mode=0o600) != p1e_raw
        or _validate_private_roots() != roots_before
    ):
        _reject()
    return score


def _validate_repair_diff(protocol: Mapping[str, Any]) -> None:
    diff = protocol.get("repair_diff")
    if type(diff) is not dict or set(diff) != REPAIR_DIFF_KEYS:
        _reject()
    if (
        diff.get("frozen_r1_primary_sha256") != R1_PRIMARY_SCORER_SHA256
        or diff.get("repaired_r2_primary_sha256")
        != hashlib.sha256(_stable_regular_bytes(PRIMARY_SCORER)).hexdigest()
        or diff.get("allowed_public_key") != "minimum_joint_finite_pixel_count"
        or diff.get("removed_overbroad_raw_substring") != "joint_finite_pixel_count"
        or diff.get("exact_public_keyset_gate_retained") is not True
        or diff.get("canonical_public_bytes_gate_retained") is not True
        or diff.get("unexpected_hash_key_gate_retained") is not True
        or diff.get("private_path_and_array_token_gates_retained") is not True
        or diff.get("producer_or_measurement_artifacts_overwritten") is not False
    ):
        _reject()


def _validate_r1_failure_lineage(protocol: Mapping[str, Any]) -> None:
    lineage = protocol.get("r1_failure_lineage")
    if type(lineage) is not dict or set(lineage) != R1_FAILURE_LINEAGE_KEYS:
        _reject()
    if (
        lineage.get("failure_audit_sha256") != R1_FAILURE_EVIDENCE_SHA256
        or lineage.get("r1_node_tag")
        != "tab_development_joint_support_1pct_p1f_20260714"
        or lineage.get("r1_question")
        != "q_bpc_development_joint_support_at_least_1pct_all_views_20260714"
        or lineage.get("r1_protocol_sha256") != R1_PROTOCOL_SHA256
        or lineage.get("r1_prediction_receipt_sha256")
        != "349d7c1ab4bc001f3eaa02cd0d2956bf5c4aeb24fd2ec580531021c6290d225d"
        or lineage.get("r1_primary_scorer_sha256") != R1_PRIMARY_SCORER_SHA256
        or lineage.get("r1_junit_sha256") != R1_JUNIT_SHA256
        or lineage.get("r1_public_result_sha256") != R1_PUBLIC_RESULT_SHA256
        or lineage.get("r1_private_receipt_sha256") != P1F_PRIVATE_RECEIPT_SHA256
        or lineage.get("process_returncode") != 2
        or lineage.get("metric_emitted") is not False
        or lineage.get("classification")
        != "PUBLIC_PRIVACY_SCORER_SUBSTRING_FALSE_POSITIVE"
        or lineage.get("input_or_measurement_failure") is not False
        or lineage.get("scientific_threshold_result_refuted") is not False
        or lineage.get("r1_measurement_preserved") is not True
        or lineage.get("r1_false_rejection_preserved") is not True
    ):
        _reject()


def _validate_r2_protocol(protocol: dict[str, Any]) -> None:
    if (
        set(protocol) != R2_PROTOCOL_KEYS
        or protocol.get("schema") != R2_PROTOCOL_SCHEMA
        or protocol.get("date") != "2026-07-14"
        or protocol.get("status") != R2_PROTOCOL_STATUS
        or protocol.get("tree") != TREE
        or protocol.get("question") != QUESTION
        or protocol.get("node_tag") != NODE_TAG
        or protocol.get("parent_node_tag") != PARENT_NODE
        or protocol.get("claim_scope") != REPAIR_CLAIM_SCOPE
        or protocol.get("execution_boundary")
        != "SCORER_REPAIR_ONLY_ON_PRESERVED_KNOWN_P1F_R1_ARTIFACTS_NO_MEASUREMENT_RERUN"
        or protocol.get("research_question")
        != (
            "Can a frozen six-case scorer repair eliminate the preserved P1f R1 "
            "scorer false rejection without changing the R1 measurement, the "
            "one-percent threshold, or treating the already-public 23-view "
            "aggregate as novel?"
        )
        or protocol.get("static_preflight_only") is not True
    ):
        _reject()

    known = protocol.get("known_existing_result_disclosure")
    if type(known) is not dict or set(known) != KNOWN_RESULT_DISCLOSURE_KEYS:
        _reject()
    if (
        known.get("result_known_before_r2") is not True
        or known.get("producer_or_measurement_rerun") is not False
        or known.get("r1_protocol_sha256") != R1_PROTOCOL_SHA256
        or known.get("r1_public_result_sha256") != R1_PUBLIC_RESULT_SHA256
        or known.get("r1_junit_sha256") != R1_JUNIT_SHA256
        or known.get("r1_private_receipt_sha256") != P1F_PRIVATE_RECEIPT_SHA256
    ):
        _reject()

    threshold = protocol.get("scientific_threshold_contract")
    if (
        type(threshold) is not dict
        or set(threshold) != SCIENTIFIC_THRESHOLD_CONTRACT_KEYS
        or threshold.get("pixels_per_view") != PIXELS_PER_VIEW
        or threshold.get("threshold_numerator") != THRESHOLD_NUMERATOR
        or threshold.get("threshold_denominator") != THRESHOLD_DENOMINATOR
        or threshold.get("minimum_joint_finite_pixel_count")
        != MINIMUM_JOINT_FINITE_PIXEL_COUNT
        or threshold.get("scientific_threshold_unchanged") is not True
    ):
        _reject()

    _validate_repair_diff(protocol)
    _validate_r1_failure_lineage(protocol)

    replay = protocol.get("confirmatory_replay_contract")
    if (
        type(replay) is not dict
        or set(replay) != CONFIRMATORY_REPLAY_CONTRACT_KEYS
        or replay.get("already_public_aggregate") != EXPECTED_VIEWS
        or replay.get("result_known_before_r2") is not True
        or replay.get("planned_after_primary_repair") is not True
        or replay.get("lakato_novel_claimed") is not False
        or replay.get("new_data_generated") is not False
        or replay.get("independent_new_data_or_replication") is not False
    ):
        _reject()

    boundaries = protocol.get("scope_boundaries")
    if (
        type(boundaries) is not dict
        or set(boundaries) != SCOPE_BOUNDARY_KEYS
        or (
            any(boundaries.get(name) is not False for name in NEGATIVE_CLAIM_KEYS)
            or boundaries.get("scorer_repair_only") is not True
            or boundaries.get("measurement_rerun") is not False
            or boundaries.get("already_public_aggregate_reclassified_as_novel")
            is not False
        )
    ):
        _reject()

    prediction = protocol.get("prediction")
    if type(prediction) is not dict or set(prediction) != {
        "metric",
        "baseline",
        "direction",
        "noise_band",
        "predicted_value",
        "credence",
        "closes_question_on_success",
    }:
        _reject()
    credence = prediction.get("credence")
    if (
        prediction.get("metric") != PRIMARY_METRIC
        or prediction.get("baseline") != 0
        or prediction.get("direction") != "higher"
        or prediction.get("noise_band") != 0
        or prediction.get("predicted_value") != EXPECTED_REPAIR_TOTAL
        or type(credence) not in {int, float}
        or isinstance(credence, bool)
        or credence != 0.98
        or prediction.get("closes_question_on_success") != QUESTION
        or any(key.startswith("novel_") for key in prediction)
    ):
        _reject()

    inventory = protocol.get("test_inventory")
    if type(inventory) is not dict or inventory != {
        "classname": REPAIR_CLASSNAME,
        "total": EXPECTED_REPAIR_TOTAL,
        "names": list(
            (
                "test_r1_privacy_gate_reproduces_allowed_key_substring_false_positive",
                "test_r2_privacy_gate_accepts_exact_allowed_minimum_key",
                "test_r2_privacy_gate_rejects_direct_private_count_keys",
                "test_r2_privacy_gate_rejects_private_paths_and_array_tokens",
                "test_r2_privacy_gate_rejects_noncanonical_or_unexpected_hash_keys",
                "test_preserved_p1f_chain_passes_repaired_primary_adjudication",
            )
        ),
        "actual_preserved_chain_cases": 1,
        "synthetic_repair_and_privacy_cases": 5,
    }:
        _reject()

    strings = set(_walk_string_values(protocol))
    required_hashes = {
        THRESHOLD_SCRIPT_SHA256,
        FROZEN_TEST_MODULE_SHA256,
        REPAIR_TEST_MODULE_SHA256,
        R1_PRIMARY_SCORER_SHA256,
        R1_NOVEL_SCORER_SHA256,
        P1E_NOVEL_SCORER_SHA256,
        R1_PROTOCOL_SHA256,
        R1_JUNIT_SHA256,
        R1_PUBLIC_RESULT_SHA256,
        P1F_PRIVATE_RECEIPT_SHA256,
        R1_FAILURE_EVIDENCE_SHA256,
        P1E_PRIVATE_RECEIPT_SHA256,
        hashlib.sha256(_stable_regular_bytes(PRIMARY_SCORER)).hexdigest(),
        hashlib.sha256(_stable_regular_bytes(CONFIRMATORY_SCORER)).hexdigest(),
    }
    required_paths = {
        str(THRESHOLD_SCRIPT),
        str(FROZEN_TEST_MODULE),
        str(REPAIR_TEST_MODULE),
        str(R1_PRIMARY_SCORER),
        str(R1_NOVEL_SCORER),
        str(P1E_NOVEL_SCORER),
        str(PRIMARY_SCORER),
        str(CONFIRMATORY_SCORER),
        str(R1_PROTOCOL),
        str(R1_JUNIT),
        str(R1_PUBLIC_RESULT),
        str(R1_FAILURE_EVIDENCE),
        str(R2_PROTOCOL),
        str(R2_JUNIT),
        str(P1E_PRIVATE_RECEIPT),
        str(P1F_PRIVATE_RECEIPT),
    }
    if not required_hashes.issubset(strings) or not required_paths.issubset(strings):
        _reject()


def _verify_r2_static_assets() -> None:
    for path, committed in (
        (REPAIR_TEST_MODULE, REPAIR_TEST_MODULE_SHA256),
        (THRESHOLD_SCRIPT, THRESHOLD_SCRIPT_SHA256),
        (FROZEN_TEST_MODULE, FROZEN_TEST_MODULE_SHA256),
        (R1_PRIMARY_SCORER, R1_PRIMARY_SCORER_SHA256),
        (R1_NOVEL_SCORER, R1_NOVEL_SCORER_SHA256),
        (P1E_NOVEL_SCORER, P1E_NOVEL_SCORER_SHA256),
    ):
        if hashlib.sha256(_stable_regular_bytes(path)).hexdigest() != committed:
            _reject()


def score() -> int:
    """Return six only for the repair protocol and preserved R1 evidence."""

    _verify_r2_static_assets()
    protocol_raw = _stable_regular_bytes(R2_PROTOCOL)
    _validate_r2_protocol(_load_json(protocol_raw))
    if score_preserved_p1f_chain() != EXPECTED_R1_TOTAL:
        _reject()
    return _score_junit(
        R2_JUNIT,
        expected_sha256=None,
        expected_total=EXPECTED_REPAIR_TOTAL,
        classname=REPAIR_CLASSNAME,
        names=REPAIR_TEST_NAMES,
    )


def main() -> int:
    try:
        if len(sys.argv) != 2 or not _same_fixed_path(sys.argv[1], R2_JUNIT):
            _reject()
        metric = score()
    except Exception:
        sys.stderr.write("E_P1F_JOINT_SUPPORT_1PCT_SCORER_REPAIR_R2_REJECTED\n")
        return 2
    print(f"metric={metric}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
