#!/usr/bin/env python3
"""Score the P2a workspace-JSON strict-provenance candidate audit.

The score is a conformance score, not a provenance or authority finding.  The
private receipt may contain eligible JSON identities and structural candidate
commitments; this judge keeps them out of stdout and requires the public record
to contain only the fixed scope, aggregate coverage, outcome, and receipt-chain
commitments.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from typing import Any, Iterable, Mapping, Sequence
import xml.etree.ElementTree as ET


WORKSPACE = Path("/data/kjra/PROJECT/3DLAB")
BPC_ROOT = WORKSPACE / "BPC_ICP_SPEC"
LAKATO_ROOT = Path("/data/kjra/PROJECT/PI/lakatotree")
PRIVATE_ROOT = WORKSPACE / ".private_bpc_p2a"

AUDIT_SCRIPT = BPC_ROOT / (
    "scripts/tab_bolt_existing_authoritative_strict_provenance_audit.py"
)
TEST_MODULE = BPC_ROOT / (
    "tests/test_tab_bolt_existing_authoritative_strict_provenance_audit.py"
)
PRIMARY_SCORER = Path(__file__).absolute()
RESOLUTION_SCORER = LAKATO_ROOT / (
    "scripts/"
    "judge_bpc_tab_existing_strict_provenance_candidate_resolution_p2a_20260714.py"
)
PROTOCOL = BPC_ROOT / (
    "evidence/"
    "bpc_tab_bolt_existing_authoritative_strict_provenance_candidate_protocol_20260714.json"
)
FIXED_JUNIT = BPC_ROOT / (
    "evidence/"
    "bpc_tab_bolt_existing_authoritative_strict_provenance_candidate_conformance_20260714.xml"
)
PUBLIC_RESULT = BPC_ROOT / (
    "evidence/"
    "bpc_tab_bolt_existing_authoritative_strict_provenance_candidate_result_20260714.json"
)
PRIVATE_RECEIPT = PRIVATE_ROOT / (
    "bpc_tab_bolt_existing_authoritative_strict_provenance_candidate_private_receipt_20260714.json"
)
PRIOR_STRICT_AUDIT = BPC_ROOT / (
    "evidence/bpc_tab_bolt_p1c_strict_layout_boundary_audit_20260714.json"
)

AUDIT_SCRIPT_SHA256 = "080881960c65033caba261fc2f02081d3e0542c5134a61b1ae2cff1a9a489374"
TEST_MODULE_SHA256 = "f7da61dd4ec71bf028ba122a7db101457ad027daddc6e314e0cd9c95e174ddde"
PRIOR_STRICT_AUDIT_SHA256 = (
    "60bd0ed2233c4d7e07cc7f0744775fe4e98df17a7a759bdcbdc00fd61bf6a24b"
)
AUDIT_CONTRACT_SHA256 = (
    "2c141413e55e02fe8c508e6158b3711f34455b2eb7ca35923520a08a3c686e00"
)

PROTOCOL_SCHEMA = (
    "bpc.tab_bolt.existing_authoritative_strict_provenance_candidate_"
    "discovery_protocol.v1"
)
PROTOCOL_STATUS = "PREREGISTERED_P2A_UNRUN"
PUBLIC_RESULT_SCHEMA = "bpc.tab_bolt.existing_strict_provenance_candidate_discovery.v1"
PRIVATE_RECEIPT_SCHEMA = (
    "bpc.tab_bolt.existing_strict_provenance_candidate_discovery_private.v1"
)
CLAIM_SCOPE = "WORKSPACE_JSON_STRICT_PROVENANCE_STRUCTURAL_CANDIDATE_DISCOVERY_ONLY"
TREE = "LakatosTree_BPC_TabBolt_Inference_20260701"
QUESTION = "q_bpc_existing_strict_provenance_candidate_json_scope_resolution_20260714"
NODE_TAG = "tab_existing_strict_provenance_candidate_p2a_20260714"
PARENT_NODE = "tab_atomic_decoded_source_handoff_20260714"
EXECUTION_BOUNDARY = (
    "ONE_NOFOLLOW_JSON_SCOPE_WORKSPACE_AUDIT_NO_AUTHORITY_OR_PHYSICAL_TRUTH_CLAIM"
)
PRIMARY_METRIC = "existing_strict_provenance_candidate_audit_conformance_gate_count"
RESOLUTION_METRIC = "strict_provenance_json_scope_audit_resolution_score"
NOVEL_PREDICTION = (
    "precommitted JSON scope audit reaches either terminal outcome without coverage gap"
)

OUTCOME_COMPLETE = "COMPLETE_CANDIDATE_FOUND"
OUTCOME_ABSENT = "NO_COMPLETE_CANDIDATE_IN_JSON_SCOPE"
OUTCOME_INCOMPLETE = "AUDIT_INCOMPLETE"
OUTCOMES = frozenset({OUTCOME_COMPLETE, OUTCOME_ABSENT, OUTCOME_INCOMPLETE})
TERMINAL_OUTCOMES = frozenset({OUTCOME_COMPLETE, OUTCOME_ABSENT})
OUTCOME_PRECEDENCE = (OUTCOME_INCOMPLETE, OUTCOME_COMPLETE, OUTCOME_ABSENT)
RESOLUTION_BY_OUTCOME = {
    OUTCOME_COMPLETE: 1,
    OUTCOME_ABSENT: 1,
    OUTCOME_INCOMPLETE: 0,
}

EXPECTED_TOTAL = 12
CLASSNAME = "tests.test_tab_bolt_existing_authoritative_strict_provenance_audit"
TEST_NAMES_ORDERED = (
    "test_01_complete_machine_readable_candidate_is_only_p2b_candidate",
    "test_02_no_content_anchored_candidate_is_json_scope_absent",
    "test_03_partial_malformed_positional_and_legacy_records_are_rejected",
    "test_04_duplicate_bool_missing_and_extra_raw_ids_are_rejected",
    "test_05_registry_protocol_analysis_and_self_asserted_authority_do_not_pass",
    "test_06_nonexcluded_symlink_makes_audit_incomplete",
    "test_07_missing_root_makes_audit_incomplete",
    "test_08_injected_eligible_json_read_failure_makes_audit_incomplete",
    "test_09_incomplete_coverage_precedes_a_structurally_complete_candidate",
    "test_10_excluded_trees_and_non_json_files_are_outside_scope",
    "test_11_public_output_redacts_identity_and_atomic_writer_enforces_modes",
    "test_99_preregistered_workspace_candidate_discovery_runs_last",
)
TEST_NAMES = frozenset(TEST_NAMES_ORDERED)

MAX_SMALL_FILE_BYTES = 32 * 1024 * 1024
MAX_JSON_BYTES = 4 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
INVENTORY_COMMITMENT_DOMAIN = b"BPC_P2A_ELIGIBLE_JSON_INVENTORY_V1\x00"
CANDIDATE_INTERPRETATION = (
    "A complete record is a machine-readable P2b verification candidate only; "
    "it does not establish authority, signature validity, calibration truth, "
    "or physical truth."
)
ENDPOINT_STABILITY_LIMITATION = (
    "Two equal endpoint inventories are not a filesystem snapshot or lock and "
    "cannot prove that no transient mutation occurred between the two passes."
)
JSON_SCOPE_LIMITATION = (
    "PLC, database, XML, non-JSON, external-system, and excluded-tree "
    "provenance are outside this P2a discovery scope."
)
EXCLUDED_RELATIVE_PREFIXES = (
    "BPC_ICP_SPEC/evidence",
    "BPC_ICP_SPEC/scripts",
    "BPC_ICP_SPEC/tests",
)
EXCLUDED_COMPONENTS = (
    ".git",
    ".hg",
    ".mypy_cache",
    ".nox",
    ".pytest_cache",
    ".ruff_cache",
    ".svn",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "lakatotree",
    "node_modules",
    "venv",
)
EXCLUDED_COMPONENT_PREFIXES = (".private",)

RESEARCH_QUESTION = (
    "Does one preregistered no-follow audit of eligible workspace JSON reach a "
    "coverage-complete terminal structural-candidate outcome, while keeping "
    "authority, signature, calibration, and physical truth unestablished?"
)
PREFLIGHT_ABSENT = "ABSENT_BEFORE_ONE_TIME_RUN"
EXECUTION_CWD = str(BPC_ROOT)
EXECUTION_PYTHON = "/data/kjra/miniconda3/envs/prismv2/bin/python"
EXECUTION_COMMAND = (
    "env PYTHONDONTWRITEBYTECODE=1 "
    "/data/kjra/miniconda3/envs/prismv2/bin/python -m pytest -q "
    "-p no:cacheprovider "
    "tests/test_tab_bolt_existing_authoritative_strict_provenance_audit.py "
    "--junitxml=evidence/"
    "bpc_tab_bolt_existing_authoritative_strict_provenance_candidate_"
    "conformance_20260714.xml"
)
MEASUREMENT_POLICY = (
    "Run the exact-twelve command once only after protocol freeze and LakatoTree "
    "prediction receipt; preserve any failure without overwrite or rerun."
)
QUESTION_CLOSE_POLICY = (
    "Close the question only when the independently regenerated resolution score "
    "is 1; AUDIT_INCOMPLETE leaves it open."
)
SUCCESS_RULE = (
    "Exactly twelve conformance gates must pass, the frozen primary scorer must "
    "regenerate 12, and the frozen resolution scorer must return 1 only for "
    "COMPLETE_CANDIDATE_FOUND or NO_COMPLETE_CANDIDATE_IN_JSON_SCOPE; "
    "AUDIT_INCOMPLETE returns 0 and leaves the question open."
)
EXPLICIT_NON_CLAIMS = (
    "A structural candidate is not verified capture authority or strict provenance.",
    "No signature, calibration truth, physical truth, physical accuracy, or "
    "production readiness is established.",
    "JSON-only coverage excludes PLC, database, XML, non-JSON, external-system, "
    "and excluded-tree provenance.",
    "Equal endpoint inventories are not a filesystem snapshot or lock and cannot "
    "exclude transient mutation between passes.",
    "No production source, calibration, threshold, PLC action, deployment, or "
    "production state is changed.",
)

INCOMPLETE_REASON_ALLOWLIST = frozenset(
    {
        "DIRECTORY_CHANGED_DURING_AUDIT",
        "DIRECTORY_IDENTITY_CHANGED_BEFORE_OPEN",
        "DIRECTORY_LIST_OR_STAT_FAILED",
        "DIRECTORY_OPEN_FAILED",
        "DIRECTORY_POST_STAT_FAILED",
        "ELIGIBLE_JSON_INVENTORY_CHANGED_BETWEEN_PASSES",
        "ELIGIBLE_JSON_READ_FAILED",
        "ELIGIBLE_JSON_SECOND_PASS_READ_FAILED",
        "ELIGIBLE_JSON_SIZE_LIMIT_EXCEEDED",
        "ENTRY_LSTAT_FAILED",
        "NONEXCLUDED_SYMLINK_ENCOUNTERED",
        "PLATFORM_NO_NOFOLLOW_DIRECTORY_SUPPORT",
        "ROOT_IDENTITY_CHANGED_BEFORE_OPEN",
        "ROOT_IS_SYMLINK",
        "ROOT_LSTAT_FAILED",
        "ROOT_NOT_DIRECTORY",
        "ROOT_OPEN_FAILED",
        "ROOT_PATH_IDENTITY_CHANGED_DURING_AUDIT",
        "ROOT_POST_LSTAT_FAILED",
        "SECOND_PASS_DIRECTORY_CHANGED_DURING_AUDIT",
        "SECOND_PASS_DIRECTORY_IDENTITY_CHANGED_BEFORE_OPEN",
        "SECOND_PASS_DIRECTORY_LIST_OR_STAT_FAILED",
        "SECOND_PASS_DIRECTORY_OPEN_FAILED",
        "SECOND_PASS_DIRECTORY_POST_STAT_FAILED",
        "SECOND_PASS_ELIGIBLE_JSON_SIZE_LIMIT_EXCEEDED",
        "SECOND_PASS_ENTRY_LSTAT_FAILED",
        "SECOND_PASS_NONEXCLUDED_SYMLINK_ENCOUNTERED",
    }
)
CANDIDATE_REJECTION_REASON_ALLOWLIST = frozenset(
    {
        "ACQUISITION_RECIPE_HASH_INVALID_OR_CONFLICTING",
        "ATLAS_HASH_INVALID",
        "AUTHORITY_MARKER_NOT_ALLOWLISTED",
        "CALIBRATION_HASH_INVALID_OR_CONFLICTING",
        "CAPTURE_OBSERVED_MARKER_MISSING",
        "CAPTURE_OR_COMMITMENT_TIME_INVALID",
        "COMMITMENT_PRECEDES_CAPTURE",
        "DECODED_DATA_USED_FOR_IDENTITY_NOT_EXACT_FALSE",
        "FALLBACK_LAYOUT_IDS_NOT_EMPTY",
        "FILENAME_USED_FOR_IDENTITY_NOT_EXACT_FALSE",
        "LEGACY_FALLBACK_USED_NOT_EXACT_FALSE",
        "NO_CAPTURE_PROVENANCE_OBJECT",
        "POSITIONAL_MAPPING_USED_NOT_EXACT_FALSE",
        "PRE_ANALYSIS_COMMITMENT_INVALID",
        "PRE_ANALYSIS_MARKER_MISSING",
        "RAW_VIEW_ID_DUPLICATE",
        "RAW_VIEW_ID_NOT_NONBOOL_INTEGER",
        "RAW_VIEW_ID_SET_NOT_EXACT_0_TO_22",
        "RECORD_KIND_NOT_CAPTURE_PROVENANCE",
        "STRICT_LAYOUT_ID_MISMATCH",
        "VIEW_ENTRY_NOT_OBJECT",
        "VIEW_IDENTITY_MODE_NOT_EXPLICIT",
        "VIEW_IDENTITY_SOURCE_NOT_ACQUISITION_SIDE",
        "VIEW_LIST_NOT_EXACTLY_23",
        "VIEW_MEDIA_TYPE_NOT_ZDF",
        "ZDF_HASH_DUPLICATE",
        "ZDF_HASH_INVALID",
        "ZDF_HASH_SET_INCOMPLETE",
    }
)
INVALID_JSON_REASON_ALLOWLIST = frozenset(
    {"DUPLICATE_JSON_KEY", "MALFORMED_OR_NONCANONICAL_JSON"}
)
AGGREGATE_REJECTION_REASON_ALLOWLIST = (
    CANDIDATE_REJECTION_REASON_ALLOWLIST | INVALID_JSON_REASON_ALLOWLIST
)

PROTOCOL_KEYS = frozenset(
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
        "json_scope_contract",
        "complete_candidate_contract",
        "outcome_precedence_contract",
        "privacy_and_publication_contract",
        "scope_boundaries",
        "prediction",
        "source_freeze",
        "contract_binding",
        "measurement_contract",
        "frozen_assets",
        "test_inventory",
        "execution",
        "static_preflight_only",
        "static_preflight_details",
        "success_rule",
        "explicit_non_claims",
    }
)
JSON_SCOPE_CONTRACT_KEYS = frozenset(
    {
        "allowed_root",
        "allowed_root_label",
        "allowed_root_count",
        "allowed_file_suffixes",
        "maximum_eligible_json_bytes",
        "eligible_json_inventory_commitment_domain",
        "nofollow_recursive_walk",
        "decoded_key_discovery_after_full_json_parse",
        "eligible_json_endpoint_inventory_passes",
        "filesystem_snapshot_or_lock_used",
    }
)
COMPLETE_CANDIDATE_CONTRACT_KEYS = frozenset(
    {
        "structural_candidate_only",
        "strict_capture_layout_id",
        "explicit_raw_view_ids",
        "unique_zdf_sha256_per_view",
        "authority_marker_truth_verified",
        "signature_verified",
        "physical_truth_verified",
    }
)
OUTCOME_PRECEDENCE_CONTRACT_KEYS = frozenset(
    {
        "outcome_precedence",
        "terminal_resolution_outcomes",
        "resolution_score_by_outcome",
        "audit_incomplete_leaves_question_unresolved",
    }
)
PRIVACY_PUBLICATION_CONTRACT_KEYS = frozenset(
    {
        "public_result_mode",
        "private_receipt_mode",
        "private_parent_mode",
        "canonical_json_required",
        "public_source_identity_allowed",
        "protocol_sha256_bound_to_both_receipts",
    }
)
SCOPE_BOUNDARY_KEYS = frozenset(
    {
        "prior_strict_boundary_audit_sha256",
        "parent_physical_evidence_inherited",
        "strict_provenance_established",
        "capture_authority_verified",
        "signature_verified",
        "calibration_truth_verified",
        "physical_truth_verified",
        "production_change",
    }
)
PREDICTION_KEYS = frozenset(
    {
        "metric",
        "baseline",
        "direction",
        "noise_band",
        "predicted_value",
        "novel_metric",
        "novel_direction",
        "novel_threshold",
        "predicted_novel_value",
        "novel_prediction",
        "credence",
        "closes_question_on_success",
    }
)
TEST_INVENTORY_KEYS = frozenset(
    {
        "classname",
        "total",
        "names",
        "actual_workspace_audit_cases",
        "synthetic_contract_security_privacy_cases",
    }
)
FROZEN_ASSET_KEYS = frozenset(
    {
        "audit_script",
        "conformance_test",
        "primary_scorer",
        "resolution_scorer",
        "protocol",
        "junit",
        "public_result",
        "private_receipt",
        "prior_strict_boundary_audit",
    }
)
PATH_SHA_ASSET_KEYS = frozenset({"path", "sha256"})
PATH_ONLY_ASSET_KEYS = frozenset({"path"})
PATH_PREFLIGHT_ASSET_KEYS = frozenset({"path", "preflight"})
PRIVATE_ASSET_KEYS = frozenset({"path", "preflight", "mode", "parent_mode"})
EXECUTION_KEYS = frozenset(
    {
        "cwd",
        "python",
        "command",
        "protocol_path",
        "junit_path",
        "public_result_path",
        "private_receipt_path",
        "primary_scorer_path",
        "resolution_scorer_path",
        "measurement_policy",
        "question_close_policy",
    }
)
STATIC_PREFLIGHT_DETAIL_KEYS = frozenset(
    {
        "producer_and_test_hashes_checked",
        "scorer_cross_bind_checked",
        "exact_twelve_test_definitions_checked_statically",
        "ruff_check_passed",
        "ruff_format_check_passed",
        "independent_static_contract_audit_issue_count",
        "protocol_absent_before_write",
        "junit_absent",
        "public_result_absent",
        "private_receipt_absent",
        "test_executed",
        "test_collected",
        "test_imported",
        "actual_workspace_scan_run",
        "private_receipt_opened",
    }
)
PUBLIC_RESULT_KEYS = frozenset(
    {
        "schema",
        "date",
        "status",
        "outcome",
        "strict_provenance_established",
        "candidate_interpretation",
        "audit_contract_sha256",
        "eligible_json_inventory_commitment_sha256",
        "scope",
        "coverage",
        "public_redaction_applied",
        "authority_marker_truth_verified",
        "signature_verified",
        "physical_truth_verified",
        "production_change",
        "protocol_sha256",
        "private_receipt_sha256",
    }
)
PUBLIC_SCOPE_KEYS = frozenset(
    {
        "allowed_root_labels",
        "allowed_root_count",
        "allowed_file_suffixes",
        "maximum_eligible_json_bytes",
        "excluded_relative_prefixes",
        "excluded_components",
        "excluded_component_prefixes",
        "decoded_key_discovery_after_full_json_parse",
        "eligible_json_endpoint_inventory_passes",
        "filesystem_snapshot_or_lock_used",
        "endpoint_stability_limitation",
        "json_only_scope_limitation",
    }
)
PUBLIC_COVERAGE_KEYS = frozenset(
    {
        "roots_requested",
        "roots_opened",
        "directories_scanned",
        "excluded_entries",
        "regular_files_seen",
        "eligible_json_files_seen",
        "eligible_json_files_read",
        "invalid_json_documents",
        "duplicate_key_json_documents",
        "malformed_or_noncanonical_json_documents",
        "candidate_json_documents",
        "noncandidate_json_documents",
        "candidate_objects_checked",
        "complete_candidates_found",
        "rejected_candidate_objects",
        "second_pass_attempted_roots",
        "second_pass_completed_roots",
        "second_pass_equal_roots",
        "second_pass_inventory_records",
        "eligible_json_inventory_two_pass_equal",
        "audit_incomplete_reason_counts",
    }
)
PRIVATE_RECEIPT_KEYS = frozenset(
    {
        "schema",
        "date",
        "outcome",
        "strict_provenance_established",
        "audit_contract_sha256",
        "eligible_json_inventory",
        "eligible_json_inventory_commitment_sha256",
        "invalid_json_documents",
        "roots",
        "candidate_documents",
        "errors",
        "aggregate_rejection_reason_counts",
        "privacy",
        "protocol_sha256",
    }
)
INVENTORY_RECORD_KEYS = frozenset(
    {"root_index", "relative_path", "size", "source_sha256"}
)
INVALID_JSON_RECORD_KEYS = frozenset(
    {"root_index", "relative_path", "source_sha256", "reason"}
)
ERROR_RECORD_KEYS = frozenset({"reason", "root_index", "relative_path"})
CANDIDATE_DOCUMENT_KEYS = frozenset(
    {
        "root_index",
        "relative_path",
        "source_sha256",
        "complete_candidate_object_sha256",
        "rejected_objects",
    }
)
PUBLIC_ALLOWED_HASH_KEYS = frozenset(
    {
        "audit_contract_sha256",
        "eligible_json_inventory_commitment_sha256",
        "protocol_sha256",
        "private_receipt_sha256",
    }
)
PUBLIC_FORBIDDEN_KEYS = frozenset(
    {
        "root_path",
        "relative_path",
        "source_sha256",
        "candidate_object_sha256",
        "complete_candidate_object_sha256",
        "eligible_json_inventory",
        "candidate_documents",
        "errors",
        "roots",
        "zdf_sha256",
        "atlas_sha256",
        "calibration_sha256",
        "pre_analysis_commitment_sha256",
    }
)


class ScoreRejected(RuntimeError):
    """Fail closed with one non-sensitive code."""


def _reject() -> None:
    raise ScoreRejected("E_P2A_STRICT_PROVENANCE_CANDIDATE_PRIMARY_REJECTED")


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
        try:
            pathname_after = path.lstat()
        except OSError:
            _reject()
        if _fingerprint(pathname_after) != _fingerprint(opened):
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
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
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


def _nonnegative_int(value: Any) -> bool:
    return type(value) is int and value >= 0


def _exact_int(value: Any, expected: int) -> bool:
    return type(value) is int and value == expected


def _safe_relative_path(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and path.as_posix() == value
        and all(part not in {"", ".."} for part in path.parts)
    )


def _is_excluded_relative_path(value: str) -> bool:
    parts = PurePosixPath(value).parts
    if not parts:
        return False
    relative = PurePosixPath(*parts).as_posix()
    if any(
        relative == prefix or relative.startswith(prefix + "/")
        for prefix in EXCLUDED_RELATIVE_PREFIXES
    ):
        return True
    for component in parts:
        lowered = component.lower()
        if lowered in EXCLUDED_COMPONENTS or any(
            lowered.startswith(prefix) for prefix in EXCLUDED_COMPONENT_PREFIXES
        ):
            return True
    return False


def _inventory_order_key(value: str) -> tuple[str, ...]:
    return PurePosixPath(value).parts


def eligible_inventory_commitment(inventory: Sequence[Mapping[str, Any]]) -> str:
    return hashlib.sha256(
        INVENTORY_COMMITMENT_DOMAIN
        + _canonical_json_bytes([dict(record) for record in inventory])
    ).hexdigest()


def _validate_counter(
    value: Any,
    allowed_reasons: frozenset[str],
) -> dict[str, int]:
    if type(value) is not dict:
        _reject()
    validated: dict[str, int] = {}
    for reason, count in value.items():
        if (
            not isinstance(reason, str)
            or reason not in allowed_reasons
            or not _nonnegative_int(count)
            or count == 0
        ):
            _reject()
        validated[reason] = count
    if list(value) != sorted(value):
        _reject()
    return validated


def _validate_inventory(value: Any) -> tuple[list[dict[str, Any]], dict[str, str]]:
    if type(value) is not list:
        _reject()
    records: list[dict[str, Any]] = []
    by_path: dict[str, str] = {}
    previous_order_key: tuple[str, ...] | None = None
    for raw in value:
        record = _exact_keys(raw, INVENTORY_RECORD_KEYS)
        relative_path = record.get("relative_path")
        source_sha256 = record.get("source_sha256")
        if (
            not _exact_int(record.get("root_index"), 0)
            or not _safe_relative_path(relative_path)
            or not relative_path.lower().endswith(".json")
            or _is_excluded_relative_path(relative_path)
            or not _nonnegative_int(record.get("size"))
            or record["size"] > MAX_JSON_BYTES
            or not _is_sha256(source_sha256)
            or relative_path in by_path
        ):
            _reject()
        order_key = _inventory_order_key(relative_path)
        if previous_order_key is not None and order_key <= previous_order_key:
            _reject()
        previous_order_key = order_key
        by_path[relative_path] = source_sha256
        records.append(dict(record))
    return records, by_path


def _validate_private_roots(value: Any) -> tuple[int, int]:
    if type(value) is not list or len(value) != 1:
        _reject()
    record = value[0]
    if type(record) is not dict or not _exact_int(record.get("root_index"), 0):
        _reject()
    opened = record.get("opened")
    if record.get("root_path") != str(WORKSPACE) or type(opened) is not bool:
        _reject()
    if opened:
        if set(record) != {"root_index", "root_path", "opened", "root_dev", "root_ino"}:
            _reject()
        if not _nonnegative_int(record.get("root_dev")) or not _nonnegative_int(
            record.get("root_ino")
        ):
            _reject()
        return 1, 1
    if set(record) != {"root_index", "root_path", "opened"}:
        _reject()
    return 1, 0


def _validate_invalid_documents(
    value: Any,
    inventory_by_path: Mapping[str, str],
    inventory_order: Mapping[str, int],
) -> tuple[list[dict[str, Any]], Counter[str], set[str]]:
    if type(value) is not list:
        _reject()
    records: list[dict[str, Any]] = []
    reasons: Counter[str] = Counter()
    seen: set[str] = set()
    previous_index = -1
    for raw in value:
        record = _exact_keys(raw, INVALID_JSON_RECORD_KEYS)
        path = record.get("relative_path")
        reason = record.get("reason")
        if (
            not _exact_int(record.get("root_index"), 0)
            or not _safe_relative_path(path)
            or path in seen
            or inventory_by_path.get(path) != record.get("source_sha256")
            or reason not in INVALID_JSON_REASON_ALLOWLIST
        ):
            _reject()
        index = inventory_order.get(path)
        if index is None or index <= previous_index:
            _reject()
        previous_index = index
        seen.add(path)
        reasons[reason] += 1
        records.append(dict(record))
    return records, reasons, seen


def _validate_errors(value: Any) -> Counter[str]:
    if type(value) is not list:
        _reject()
    counts: Counter[str] = Counter()
    for raw in value:
        record = _exact_keys(raw, ERROR_RECORD_KEYS)
        reason = record.get("reason")
        if (
            not _exact_int(record.get("root_index"), 0)
            or not _safe_relative_path(record.get("relative_path"))
            or _is_excluded_relative_path(record["relative_path"])
            or reason not in INCOMPLETE_REASON_ALLOWLIST
        ):
            _reject()
        counts[reason] += 1
    return counts


def _validate_candidate_documents(
    value: Any,
    inventory_by_path: Mapping[str, str],
    inventory_order: Mapping[str, int],
) -> tuple[int, int, int, Counter[str], set[str]]:
    if type(value) is not list:
        _reject()
    complete = 0
    rejected = 0
    checked = 0
    reasons: Counter[str] = Counter()
    seen_paths: set[str] = set()
    previous_index = -1
    for raw in value:
        document = _exact_keys(raw, CANDIDATE_DOCUMENT_KEYS)
        path = document.get("relative_path")
        if (
            not _exact_int(document.get("root_index"), 0)
            or not _safe_relative_path(path)
            or path in seen_paths
            or inventory_by_path.get(path) != document.get("source_sha256")
        ):
            _reject()
        index = inventory_order.get(path)
        if index is None or index <= previous_index:
            _reject()
        previous_index = index
        seen_paths.add(path)
        complete_hashes = document.get("complete_candidate_object_sha256")
        rejected_objects = document.get("rejected_objects")
        if type(complete_hashes) is not list or type(rejected_objects) is not list:
            _reject()
        if any(not _is_sha256(value) for value in complete_hashes) or len(
            set(complete_hashes)
        ) != len(complete_hashes):
            _reject()
        if not complete_hashes and not rejected_objects:
            _reject()
        complete += len(complete_hashes)
        for raw_rejected in rejected_objects:
            if type(raw_rejected) is not dict or set(raw_rejected) not in (
                {"reasons"},
                {"candidate_object_sha256", "reasons"},
            ):
                _reject()
            if "candidate_object_sha256" in raw_rejected and not _is_sha256(
                raw_rejected["candidate_object_sha256"]
            ):
                _reject()
            if "candidate_object_sha256" in raw_rejected:
                checked += 1
            object_reasons = raw_rejected.get("reasons")
            if (
                type(object_reasons) is not list
                or not object_reasons
                or len(set(object_reasons)) != len(object_reasons)
                or any(
                    not isinstance(reason, str)
                    or reason not in CANDIDATE_REJECTION_REASON_ALLOWLIST
                    for reason in object_reasons
                )
                or object_reasons != sorted(object_reasons)
            ):
                _reject()
            has_object_hash = "candidate_object_sha256" in raw_rejected
            no_capture_object = object_reasons == ["NO_CAPTURE_PROVENANCE_OBJECT"]
            if (
                "NO_CAPTURE_PROVENANCE_OBJECT" in object_reasons
                and not no_capture_object
            ) or has_object_hash is no_capture_object:
                _reject()
            reasons.update(object_reasons)
            rejected += 1
        checked += len(complete_hashes)
    return complete, rejected, checked, reasons, seen_paths


def _validate_public_privacy(public: Mapping[str, Any], raw: bytes) -> None:
    exact = _exact_keys(public, PUBLIC_RESULT_KEYS)
    if _canonical_json_bytes(exact) != raw:
        _reject()
    keys = set(_walk_keys(exact))
    if keys & PUBLIC_FORBIDDEN_KEYS:
        _reject()
    for key in keys:
        if key.endswith("_sha256") and key not in PUBLIC_ALLOWED_HASH_KEYS:
            _reject()
        if key.endswith(("_path", "_filename", "_excerpt")):
            _reject()
    lowered = raw.lower()
    if any(token in lowered for token in (b"/data/", b".private_bpc", b".zdf")):
        _reject()


def _validate_scope(scope: Any) -> None:
    exact = _exact_keys(scope, PUBLIC_SCOPE_KEYS)
    if (
        exact.get("allowed_root_labels") != ["WORKSPACE_ROOT"]
        or not _exact_int(exact.get("allowed_root_count"), 1)
        or exact.get("allowed_file_suffixes") != [".json"]
        or not _exact_int(exact.get("maximum_eligible_json_bytes"), MAX_JSON_BYTES)
        or exact.get("excluded_relative_prefixes") != list(EXCLUDED_RELATIVE_PREFIXES)
        or exact.get("excluded_components") != list(EXCLUDED_COMPONENTS)
        or exact.get("excluded_component_prefixes") != list(EXCLUDED_COMPONENT_PREFIXES)
        or exact.get("decoded_key_discovery_after_full_json_parse") is not True
        or not _exact_int(exact.get("eligible_json_endpoint_inventory_passes"), 2)
        or exact.get("filesystem_snapshot_or_lock_used") is not False
        or exact.get("endpoint_stability_limitation") != ENDPOINT_STABILITY_LIMITATION
        or exact.get("json_only_scope_limitation") != JSON_SCOPE_LIMITATION
    ):
        _reject()


def _validate_coverage(
    coverage: Any,
    *,
    inventory_count: int,
    invalid_count: int,
    invalid_reasons: Counter[str],
    candidate_document_count: int,
    complete_count: int,
    rejected_count: int,
    candidate_objects_checked: int,
    error_counts: Counter[str],
    roots_opened: int,
) -> None:
    exact = _exact_keys(coverage, PUBLIC_COVERAGE_KEYS)
    integer_keys = PUBLIC_COVERAGE_KEYS - {
        "eligible_json_inventory_two_pass_equal",
        "audit_incomplete_reason_counts",
    }
    if any(not _nonnegative_int(exact.get(key)) for key in integer_keys):
        _reject()
    incomplete = _validate_counter(
        exact.get("audit_incomplete_reason_counts"),
        INCOMPLETE_REASON_ALLOWLIST,
    )
    if (
        exact.get("roots_requested") != 1
        or exact.get("roots_opened") != roots_opened
        or exact.get("eligible_json_files_read") != inventory_count
        or exact.get("invalid_json_documents") != invalid_count
        or exact.get("duplicate_key_json_documents")
        != invalid_reasons["DUPLICATE_JSON_KEY"]
        or exact.get("malformed_or_noncanonical_json_documents")
        != invalid_reasons["MALFORMED_OR_NONCANONICAL_JSON"]
        or exact.get("candidate_json_documents") != candidate_document_count
        or exact.get("invalid_json_documents")
        + exact.get("candidate_json_documents")
        + exact.get("noncandidate_json_documents")
        != inventory_count
        or exact.get("complete_candidates_found") != complete_count
        or exact.get("rejected_candidate_objects") != rejected_count
        or exact.get("candidate_objects_checked") != candidate_objects_checked
        or incomplete != dict(error_counts)
        or exact.get("eligible_json_files_seen") < inventory_count
        or exact.get("regular_files_seen") < exact.get("eligible_json_files_seen")
        or type(exact.get("eligible_json_inventory_two_pass_equal")) is not bool
        or exact.get("second_pass_attempted_roots") != roots_opened
        or exact.get("second_pass_completed_roots")
        > exact.get("second_pass_attempted_roots")
        or exact.get("second_pass_equal_roots")
        > exact.get("second_pass_completed_roots")
        or exact.get("eligible_json_inventory_two_pass_equal")
        is not (
            exact.get("second_pass_equal_roots") == 1
            and exact.get("second_pass_completed_roots") == 1
        )
    ):
        _reject()
    if roots_opened == 0:
        if (
            exact.get("directories_scanned") != 0
            or inventory_count != 0
            or exact.get("eligible_json_files_seen") != 0
            or exact.get("regular_files_seen") != 0
        ):
            _reject()
    elif exact.get("directories_scanned") < 1:
        _reject()
    if (
        exact.get("second_pass_equal_roots") == 1
        and exact.get("second_pass_inventory_records") != inventory_count
    ):
        _reject()
    if error_counts:
        return
    if (
        exact.get("second_pass_attempted_roots") != 1
        or exact.get("second_pass_completed_roots") != 1
        or exact.get("second_pass_equal_roots") != 1
        or exact.get("second_pass_inventory_records") != inventory_count
        or exact.get("eligible_json_inventory_two_pass_equal") is not True
    ):
        _reject()


def _expected_outcome(*, errors: Counter[str], complete_count: int) -> str:
    if errors:
        return OUTCOME_INCOMPLETE
    if complete_count:
        return OUTCOME_COMPLETE
    return OUTCOME_ABSENT


def _validate_receipts(protocol_raw: bytes) -> str:
    try:
        root = PRIVATE_ROOT.lstat()
    except OSError:
        _reject()
    if (
        stat.S_ISLNK(root.st_mode)
        or not stat.S_ISDIR(root.st_mode)
        or stat.S_IMODE(root.st_mode) != 0o700
    ):
        _reject()
    private_root_identity = (root.st_dev, root.st_ino, stat.S_IMODE(root.st_mode))
    protocol_sha256 = hashlib.sha256(protocol_raw).hexdigest()
    private_raw = _stable_regular_bytes(PRIVATE_RECEIPT, required_mode=0o600)
    private = _exact_keys(_load_json(private_raw), PRIVATE_RECEIPT_KEYS)
    if _canonical_json_bytes(private) != private_raw:
        _reject()

    inventory, inventory_by_path = _validate_inventory(
        private.get("eligible_json_inventory")
    )
    inventory_order = {
        record["relative_path"]: index for index, record in enumerate(inventory)
    }
    commitment = eligible_inventory_commitment(inventory)
    invalid, invalid_reasons, invalid_paths = _validate_invalid_documents(
        private.get("invalid_json_documents"), inventory_by_path, inventory_order
    )
    roots_requested, roots_opened = _validate_private_roots(private.get("roots"))
    errors = _validate_errors(private.get("errors"))
    candidate_documents = private.get("candidate_documents")
    (
        complete_count,
        rejected_count,
        candidate_objects_checked,
        rejection_reasons,
        candidate_paths,
    ) = _validate_candidate_documents(
        candidate_documents,
        inventory_by_path,
        inventory_order,
    )
    aggregate_rejections = _validate_counter(
        private.get("aggregate_rejection_reason_counts"),
        AGGREGATE_REJECTION_REASON_ALLOWLIST,
    )
    expected_outcome = _expected_outcome(errors=errors, complete_count=complete_count)
    if (
        private.get("schema") != PRIVATE_RECEIPT_SCHEMA
        or private.get("date") != "2026-07-14"
        or private.get("outcome") != expected_outcome
        or private.get("strict_provenance_established") is not False
        or private.get("audit_contract_sha256") != AUDIT_CONTRACT_SHA256
        or private.get("eligible_json_inventory_commitment_sha256") != commitment
        or private.get("protocol_sha256") != protocol_sha256
        or private.get("privacy") != "MODE_0600_IDENTITY_BEARING_RECEIPT_DO_NOT_PUBLISH"
        or aggregate_rejections != dict(rejection_reasons + invalid_reasons)
        or roots_requested != 1
        or not invalid_paths.isdisjoint(candidate_paths)
        or len(invalid_paths | candidate_paths) > len(inventory)
    ):
        _reject()

    private_sha256 = hashlib.sha256(private_raw).hexdigest()
    public_raw = _stable_regular_bytes(PUBLIC_RESULT, required_mode=0o444)
    public = _load_json(public_raw)
    _validate_public_privacy(public, public_raw)
    _validate_scope(public.get("scope"))
    _validate_coverage(
        public.get("coverage"),
        inventory_count=len(inventory),
        invalid_count=len(invalid),
        invalid_reasons=invalid_reasons,
        candidate_document_count=(
            len(candidate_documents) if type(candidate_documents) is list else -1
        ),
        complete_count=complete_count,
        rejected_count=rejected_count,
        candidate_objects_checked=candidate_objects_checked,
        error_counts=errors,
        roots_opened=roots_opened,
    )
    if (
        public.get("schema") != PUBLIC_RESULT_SCHEMA
        or public.get("date") != "2026-07-14"
        or public.get("status") != expected_outcome
        or public.get("outcome") != expected_outcome
        or public.get("strict_provenance_established") is not False
        or public.get("candidate_interpretation") != CANDIDATE_INTERPRETATION
        or public.get("audit_contract_sha256") != AUDIT_CONTRACT_SHA256
        or public.get("audit_contract_sha256") != private.get("audit_contract_sha256")
        or public.get("eligible_json_inventory_commitment_sha256") != commitment
        or public.get("public_redaction_applied") is not True
        or public.get("authority_marker_truth_verified") is not False
        or public.get("signature_verified") is not False
        or public.get("physical_truth_verified") is not False
        or public.get("production_change") is not False
        or public.get("protocol_sha256") != protocol_sha256
        or public.get("private_receipt_sha256") != private_sha256
    ):
        _reject()
    try:
        root_after = PRIVATE_ROOT.lstat()
    except OSError:
        _reject()
    if (
        stat.S_ISLNK(root_after.st_mode)
        or not stat.S_ISDIR(root_after.st_mode)
        or stat.S_IMODE(root_after.st_mode) != 0o700
        or (root_after.st_dev, root_after.st_ino, stat.S_IMODE(root_after.st_mode))
        != private_root_identity
    ):
        _reject()
    return expected_outcome


def _validate_frozen_assets(value: Any) -> None:
    assets = _exact_keys(value, FROZEN_ASSET_KEYS)
    for name in (
        "audit_script",
        "conformance_test",
        "primary_scorer",
        "resolution_scorer",
        "prior_strict_boundary_audit",
    ):
        _exact_keys(assets.get(name), PATH_SHA_ASSET_KEYS)
    _exact_keys(assets.get("protocol"), PATH_ONLY_ASSET_KEYS)
    for name in ("junit", "public_result"):
        _exact_keys(assets.get(name), PATH_PREFLIGHT_ASSET_KEYS)
    _exact_keys(assets.get("private_receipt"), PRIVATE_ASSET_KEYS)

    expected = {
        "audit_script": {
            "path": str(AUDIT_SCRIPT),
            "sha256": AUDIT_SCRIPT_SHA256,
        },
        "conformance_test": {
            "path": str(TEST_MODULE),
            "sha256": TEST_MODULE_SHA256,
        },
        "primary_scorer": {
            "path": str(PRIMARY_SCORER),
            "sha256": hashlib.sha256(_stable_regular_bytes(PRIMARY_SCORER)).hexdigest(),
        },
        "resolution_scorer": {
            "path": str(RESOLUTION_SCORER),
            "sha256": hashlib.sha256(
                _stable_regular_bytes(RESOLUTION_SCORER)
            ).hexdigest(),
        },
        "protocol": {"path": str(PROTOCOL)},
        "junit": {"path": str(FIXED_JUNIT), "preflight": PREFLIGHT_ABSENT},
        "public_result": {
            "path": str(PUBLIC_RESULT),
            "preflight": PREFLIGHT_ABSENT,
        },
        "private_receipt": {
            "path": str(PRIVATE_RECEIPT),
            "preflight": PREFLIGHT_ABSENT,
            "mode": "0600",
            "parent_mode": "0700",
        },
        "prior_strict_boundary_audit": {
            "path": str(PRIOR_STRICT_AUDIT),
            "sha256": PRIOR_STRICT_AUDIT_SHA256,
        },
    }
    if assets != expected:
        _reject()


def _validate_protocol(protocol: dict[str, Any]) -> None:
    exact = _exact_keys(protocol, PROTOCOL_KEYS)
    if (
        exact.get("schema") != PROTOCOL_SCHEMA
        or exact.get("date") != "2026-07-14"
        or exact.get("status") != PROTOCOL_STATUS
        or exact.get("tree") != TREE
        or exact.get("question") != QUESTION
        or exact.get("node_tag") != NODE_TAG
        or exact.get("parent_node_tag") != PARENT_NODE
        or exact.get("claim_scope") != CLAIM_SCOPE
        or exact.get("execution_boundary") != EXECUTION_BOUNDARY
        or exact.get("research_question") != RESEARCH_QUESTION
        or exact.get("static_preflight_only") is not True
        or exact.get("success_rule") != SUCCESS_RULE
        or exact.get("explicit_non_claims") != list(EXPLICIT_NON_CLAIMS)
    ):
        _reject()

    if exact.get("source_freeze") != {
        "audit_script_path": str(AUDIT_SCRIPT),
        "audit_script_sha256": AUDIT_SCRIPT_SHA256,
        "conformance_test_path": str(TEST_MODULE),
        "conformance_test_sha256": TEST_MODULE_SHA256,
    }:
        _reject()
    if exact.get("contract_binding") != {
        "mechanism": "AUDIT_SCRIPT_SHA256",
        "audit_script_sha256": AUDIT_SCRIPT_SHA256,
    }:
        _reject()
    measurement = exact.get("measurement_contract")
    if measurement != {
        "allowed_root": str(WORKSPACE),
        "allowed_file_suffixes": [".json"],
        "actual_scan_before_prediction": False,
        "junit_target_absent_before_run": True,
        "public_source_identity_allowed": False,
        "strict_provenance_established_always": False,
    }:
        _reject()
    if (
        measurement.get("actual_scan_before_prediction") is not False
        or measurement.get("junit_target_absent_before_run") is not True
        or measurement.get("public_source_identity_allowed") is not False
        or measurement.get("strict_provenance_established_always") is not False
    ):
        _reject()

    json_scope = _exact_keys(exact.get("json_scope_contract"), JSON_SCOPE_CONTRACT_KEYS)
    if (
        json_scope.get("allowed_root") != str(WORKSPACE)
        or json_scope.get("allowed_root_label") != "WORKSPACE_ROOT"
        or not _exact_int(json_scope.get("allowed_root_count"), 1)
        or json_scope.get("allowed_file_suffixes") != [".json"]
        or not _exact_int(json_scope.get("maximum_eligible_json_bytes"), MAX_JSON_BYTES)
        or json_scope.get("eligible_json_inventory_commitment_domain")
        != "BPC_P2A_ELIGIBLE_JSON_INVENTORY_V1"
        or json_scope.get("nofollow_recursive_walk") is not True
        or json_scope.get("decoded_key_discovery_after_full_json_parse") is not True
        or not _exact_int(json_scope.get("eligible_json_endpoint_inventory_passes"), 2)
        or json_scope.get("filesystem_snapshot_or_lock_used") is not False
    ):
        _reject()

    candidate = _exact_keys(
        exact.get("complete_candidate_contract"),
        COMPLETE_CANDIDATE_CONTRACT_KEYS,
    )
    if (
        candidate.get("structural_candidate_only") is not True
        or candidate.get("strict_capture_layout_id") != "BPC_PHYSICAL_HOLDOUT_STRICT_V1"
        or candidate.get("explicit_raw_view_ids") != list(range(23))
        or any(
            type(raw_view_id) is not int
            for raw_view_id in candidate.get("explicit_raw_view_ids", [])
        )
        or candidate.get("unique_zdf_sha256_per_view") is not True
        or candidate.get("authority_marker_truth_verified") is not False
        or candidate.get("signature_verified") is not False
        or candidate.get("physical_truth_verified") is not False
    ):
        _reject()

    precedence = _exact_keys(
        exact.get("outcome_precedence_contract"),
        OUTCOME_PRECEDENCE_CONTRACT_KEYS,
    )
    resolution_map = precedence.get("resolution_score_by_outcome")
    if (
        precedence.get("outcome_precedence") != list(OUTCOME_PRECEDENCE)
        or precedence.get("terminal_resolution_outcomes")
        != [OUTCOME_COMPLETE, OUTCOME_ABSENT]
        or resolution_map != RESOLUTION_BY_OUTCOME
        or type(resolution_map) is not dict
        or any(
            not _exact_int(resolution_map.get(outcome), score)
            for outcome, score in RESOLUTION_BY_OUTCOME.items()
        )
        or precedence.get("audit_incomplete_leaves_question_unresolved") is not True
    ):
        _reject()

    privacy = _exact_keys(
        exact.get("privacy_and_publication_contract"),
        PRIVACY_PUBLICATION_CONTRACT_KEYS,
    )
    if (
        privacy.get("public_result_mode") != "0444"
        or privacy.get("private_receipt_mode") != "0600"
        or privacy.get("private_parent_mode") != "0700"
        or privacy.get("canonical_json_required") is not True
        or privacy.get("public_source_identity_allowed") is not False
        or privacy.get("protocol_sha256_bound_to_both_receipts") is not True
    ):
        _reject()

    boundaries = _exact_keys(exact.get("scope_boundaries"), SCOPE_BOUNDARY_KEYS)
    if (
        boundaries.get("prior_strict_boundary_audit_sha256")
        != PRIOR_STRICT_AUDIT_SHA256
        or boundaries.get("parent_physical_evidence_inherited") is not False
        or boundaries.get("strict_provenance_established") is not False
        or boundaries.get("capture_authority_verified") is not False
        or boundaries.get("signature_verified") is not False
        or boundaries.get("calibration_truth_verified") is not False
        or boundaries.get("physical_truth_verified") is not False
        or boundaries.get("production_change") is not False
    ):
        _reject()

    prediction = _exact_keys(exact.get("prediction"), PREDICTION_KEYS)
    credence = prediction.get("credence")
    if (
        prediction.get("metric") != PRIMARY_METRIC
        or not _exact_int(prediction.get("baseline"), 0)
        or prediction.get("direction") != "higher"
        or not _exact_int(prediction.get("noise_band"), 0)
        or not _exact_int(prediction.get("predicted_value"), EXPECTED_TOTAL)
        or prediction.get("novel_metric") != RESOLUTION_METRIC
        or prediction.get("novel_direction") != "higher"
        or not _exact_int(prediction.get("novel_threshold"), 1)
        or not _exact_int(prediction.get("predicted_novel_value"), 1)
        or prediction.get("novel_prediction") != NOVEL_PREDICTION
        or type(credence) not in {int, float}
        or isinstance(credence, bool)
        or credence != 0.55
        or prediction.get("closes_question_on_success") != QUESTION
    ):
        _reject()

    inventory = _exact_keys(exact.get("test_inventory"), TEST_INVENTORY_KEYS)
    if (
        inventory.get("classname") != CLASSNAME
        or not _exact_int(inventory.get("total"), EXPECTED_TOTAL)
        or inventory.get("names") != list(TEST_NAMES_ORDERED)
        or not _exact_int(inventory.get("actual_workspace_audit_cases"), 1)
        or not _exact_int(
            inventory.get("synthetic_contract_security_privacy_cases"), 11
        )
    ):
        _reject()

    execution = _exact_keys(exact.get("execution"), EXECUTION_KEYS)
    if execution != {
        "cwd": EXECUTION_CWD,
        "python": EXECUTION_PYTHON,
        "command": EXECUTION_COMMAND,
        "protocol_path": str(PROTOCOL),
        "junit_path": str(FIXED_JUNIT),
        "public_result_path": str(PUBLIC_RESULT),
        "private_receipt_path": str(PRIVATE_RECEIPT),
        "primary_scorer_path": str(PRIMARY_SCORER),
        "resolution_scorer_path": str(RESOLUTION_SCORER),
        "measurement_policy": MEASUREMENT_POLICY,
        "question_close_policy": QUESTION_CLOSE_POLICY,
    }:
        _reject()

    static_details = _exact_keys(
        exact.get("static_preflight_details"), STATIC_PREFLIGHT_DETAIL_KEYS
    )
    if static_details != {
        "producer_and_test_hashes_checked": True,
        "scorer_cross_bind_checked": True,
        "exact_twelve_test_definitions_checked_statically": True,
        "ruff_check_passed": True,
        "ruff_format_check_passed": True,
        "independent_static_contract_audit_issue_count": 0,
        "protocol_absent_before_write": True,
        "junit_absent": True,
        "public_result_absent": True,
        "private_receipt_absent": True,
        "test_executed": False,
        "test_collected": False,
        "test_imported": False,
        "actual_workspace_scan_run": False,
        "private_receipt_opened": False,
    }:
        _reject()
    boolean_static_keys = STATIC_PREFLIGHT_DETAIL_KEYS - {
        "independent_static_contract_audit_issue_count"
    }
    if any(
        type(static_details.get(key)) is not bool for key in boolean_static_keys
    ) or not _exact_int(
        static_details.get("independent_static_contract_audit_issue_count"), 0
    ):
        _reject()

    _validate_frozen_assets(exact.get("frozen_assets"))


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
    if counts != {"tests": EXPECTED_TOTAL, "errors": 0, "failures": 0, "skipped": 0}:
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


def validate_receipt_chain() -> str:
    """Reopen and validate the fixed public/private chain, returning its outcome."""

    protocol_raw = _stable_regular_bytes(PROTOCOL)
    _validate_protocol(_load_json(protocol_raw))
    return _validate_receipts(protocol_raw)


def resolution_score_for_outcome(outcome: str) -> int:
    if outcome not in OUTCOMES:
        _reject()
    return RESOLUTION_BY_OUTCOME[outcome]


def score() -> int:
    """Return twelve only for the complete P2a conformance and receipt chain."""

    for path, committed in (
        (AUDIT_SCRIPT, AUDIT_SCRIPT_SHA256),
        (TEST_MODULE, TEST_MODULE_SHA256),
        (PRIOR_STRICT_AUDIT, PRIOR_STRICT_AUDIT_SHA256),
    ):
        if hashlib.sha256(_stable_regular_bytes(path)).hexdigest() != committed:
            _reject()
    validate_receipt_chain()
    return _score_junit()


def main() -> int:
    try:
        if len(sys.argv) != 2 or not _same_fixed_path(sys.argv[1], FIXED_JUNIT):
            _reject()
        metric = score()
    except Exception:
        sys.stderr.write("E_P2A_STRICT_PROVENANCE_CANDIDATE_PRIMARY_REJECTED\n")
        return 2
    print(f"metric={metric}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
