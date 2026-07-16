#!/usr/bin/env python3
"""Score the frozen P2a-R2 strict-provenance coverage-repair audit.

The primary score is a conformance count, never a provenance finding.  The
producer and test module are read as inert bytes and inspected with ``ast``;
they are never imported or executed.  The identity-bearing private receipt is
outside this judge's read allowlist.  Its digest is accepted only as a
non-zero commitment carried by the canonical redacted public result.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Iterable, Mapping
import xml.etree.ElementTree as ET


WORKSPACE = Path("/data/kjra/PROJECT/3DLAB")
BPC_ROOT = WORKSPACE / "BPC_ICP_SPEC"
LAKATO_ROOT = Path("/data/kjra/PROJECT/PI/lakatotree")

AUDIT_SCRIPT = BPC_ROOT / (
    "scripts/"
    "tab_bolt_existing_authoritative_strict_provenance_audit_coverage_repair_r2.py"
)
TEST_MODULE = BPC_ROOT / (
    "tests/"
    "test_tab_bolt_existing_authoritative_strict_provenance_audit_coverage_repair_r2.py"
)
PRIMARY_SCORER = Path(__file__).absolute()
RESOLUTION_SCORER = LAKATO_ROOT / (
    "scripts/"
    "judge_bpc_tab_existing_strict_provenance_candidate_coverage_repair_"
    "resolution_r2_p2a_20260714.py"
)
PROTOCOL = BPC_ROOT / (
    "evidence/"
    "bpc_tab_bolt_existing_authoritative_strict_provenance_candidate_"
    "coverage_repair_r2_protocol_20260714.json"
)
FIXED_JUNIT = BPC_ROOT / (
    "evidence/"
    "bpc_tab_bolt_existing_authoritative_strict_provenance_candidate_"
    "coverage_repair_r2_conformance_20260714.xml"
)
PUBLIC_RESULT = BPC_ROOT / (
    "evidence/"
    "bpc_tab_bolt_existing_authoritative_strict_provenance_candidate_"
    "coverage_repair_r2_result_20260714.json"
)
PRIVATE_RECEIPT = WORKSPACE / (
    ".private_bpc_p2a_r2/"
    "bpc_tab_bolt_existing_authoritative_strict_provenance_candidate_"
    "coverage_repair_r2_private_receipt_20260714.json"
)
PRIOR_P2A_PUBLIC_RESULT = BPC_ROOT / (
    "evidence/"
    "bpc_tab_bolt_existing_authoritative_strict_provenance_candidate_"
    "result_20260714.json"
)
PRIOR_STRICT_AUDIT = BPC_ROOT / (
    "evidence/bpc_tab_bolt_p1c_strict_layout_boundary_audit_20260714.json"
)

AUDIT_SCRIPT_SHA256 = "138a026cfee8c95e2d44d8522c2c6406e32e78b4d66047d972fc61e0600788ed"
TEST_MODULE_SHA256 = "1acd6525e59a96e79bb18ecdc711c0fb61607414188b33f759a4a19dd91bd405"
PRIOR_P2A_PUBLIC_RESULT_SHA256 = (
    "391645d813216d8e8149cf502c388e7c93af8f25e60cf6c48c939ebaf3318d65"
)
PRIOR_STRICT_AUDIT_SHA256 = (
    "60bd0ed2233c4d7e07cc7f0744775fe4e98df17a7a759bdcbdc00fd61bf6a24b"
)

PROTOCOL_SCHEMA = (
    "bpc.tab_bolt.existing_authoritative_strict_provenance_candidate_"
    "coverage_repair_r2_protocol.v1"
)
PROTOCOL_STATUS = "PREREGISTERED_P2A_R2_UNRUN"
PUBLIC_RESULT_SCHEMA = (
    "bpc.tab_bolt.existing_strict_provenance_candidate_discovery_coverage_repair_r2.v1"
)
TREE = "LakatosTree_BPC_TabBolt_Inference_20260701"
QUESTION = "q_bpc_existing_strict_provenance_candidate_coverage_repair_r2_20260714"
PRIOR_QUESTION = (
    "q_bpc_existing_strict_provenance_candidate_json_scope_resolution_20260714"
)
NODE_TAG = "tab_existing_strict_provenance_candidate_coverage_repair_r2_20260714"
PARENT_NODE = "tab_existing_strict_provenance_candidate_p2a_20260714"
CLAIM_SCOPE = (
    "WORKSPACE_JSON_STRICT_PROVENANCE_STRUCTURAL_CANDIDATE_"
    "DISCOVERY_COVERAGE_REPAIR_ONLY"
)
EXECUTION_BOUNDARY = (
    "ONE_NOFOLLOW_JSON_SCOPE_COVERAGE_REPAIR_NO_TARGET_DEREFERENCE_"
    "NO_AUTHORITY_OR_PHYSICAL_TRUTH_CLAIM"
)
PRIMARY_METRIC = (
    "existing_strict_provenance_candidate_coverage_repair_r2_conformance_gate_count"
)
RESOLUTION_METRIC = "strict_provenance_json_scope_coverage_repair_resolution_score"
NOVEL_PREDICTION = (
    "precommitted coverage repair reaches a terminal JSON-scope outcome without "
    "an incomplete coverage gate"
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

EXPECTED_TOTAL = 16
CLASSNAME = (
    "tests."
    "test_tab_bolt_existing_authoritative_strict_provenance_audit_coverage_repair_r2"
)
TEST_NAMES_ORDERED = (
    "test_01_complete_machine_readable_record_is_only_p2b_candidate",
    "test_02_absent_scope_has_exact_inventory_and_endpoint_commitments",
    "test_03_partial_duplicate_malformed_and_noncanonical_json_are_rejected",
    "test_04_raw_id_and_self_asserted_authority_fail_structural_gate",
    "test_05_relative_and_absolute_internal_json_aliases_are_redundant",
    "test_06_internal_normal_file_and_covered_directory_aliases_are_redundant",
    "test_07_external_lexical_target_is_fail_closed",
    "test_08_dangling_target_is_fail_closed",
    "test_09_excluded_and_link_chain_targets_are_not_represented",
    "test_10_link_chain_cycle_is_fail_closed_without_dereference",
    "test_11_json_named_alias_requires_exact_eligible_json_target",
    "test_12_over_4mib_is_fully_parsed_and_over_64mib_is_fail_closed",
    "test_13_read_failure_and_between_pass_mutation_are_fail_closed",
    "test_14_exclusions_missing_root_and_incomplete_precedence_are_explicit",
    "test_15_public_redaction_atomic_modes_and_no_clobber",
    "test_99_preregistered_workspace_coverage_repair_runs_last",
)
TEST_NAMES = frozenset(TEST_NAMES_ORDERED)

MAX_SMALL_FILE_BYTES = 32 * 1024 * 1024
MAX_JSON_BYTES = 64 * 1024 * 1024
ORIGINAL_P2A_MAX_JSON_BYTES = 4 * 1024 * 1024
READ_CHUNK_BYTES = 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
INVENTORY_DOMAIN = "BPC_P2A_R2_ELIGIBLE_JSON_INVENTORY_V1"
ENDPOINT_DOMAIN = "BPC_P2A_R2_ENDPOINT_INVENTORY_V1"
SYMLINK_POLICY = (
    "NO_FOLLOW_AND_NO_TARGET_DEREFERENCE; classify after traversal from readlink "
    "text and the normal-entry map; coverage-neutral only for a lexical internal "
    "target through represented non-symlink directories to a represented regular "
    "file or covered directory; a .json-named link must target an exact eligible "
    "JSON inventory path"
)
CANDIDATE_INTERPRETATION = (
    "A complete record is a machine-readable P2b verification candidate only; "
    "it does not establish authority, signature validity, calibration truth, "
    "or physical truth."
)
MAXIMUM_INTERPRETATION = "PRECOMMITTED_RESOURCE_SAFETY_BOUND_FAIL_CLOSED_IF_EXCEEDED"
ENDPOINT_STABILITY_LIMITATION = (
    "Two equal endpoint inventories are not a filesystem snapshot or lock and "
    "cannot prove that no transient mutation occurred between the two passes."
)
JSON_SCOPE_LIMITATION = (
    "PLC, database, XML, non-JSON, external-system, and excluded-tree "
    "provenance are outside this P2a-R2 discovery scope."
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
    "Does one preregistered no-follow coverage-repair audit of eligible workspace "
    "JSON reach a coverage-complete terminal structural-candidate outcome after "
    "lexically classifying represented symlink aliases and raising the bounded "
    "JSON read ceiling to 64 MiB, while keeping strict provenance unestablished?"
)
EXECUTION_CWD = str(BPC_ROOT)
EXECUTION_PYTHON = "/data/kjra/miniconda3/envs/prismv2/bin/python"
EXECUTION_COMMAND = (
    "env PYTHONDONTWRITEBYTECODE=1 "
    "/data/kjra/miniconda3/envs/prismv2/bin/python -m pytest -q "
    "-p no:cacheprovider "
    "tests/"
    "test_tab_bolt_existing_authoritative_strict_provenance_audit_coverage_repair_r2.py "
    "--junitxml=evidence/"
    "bpc_tab_bolt_existing_authoritative_strict_provenance_candidate_"
    "coverage_repair_r2_conformance_20260714.xml"
)
MEASUREMENT_POLICY = (
    "Run the exact-sixteen command once only after protocol freeze and LakatoTree "
    "prediction receipt; preserve any failure without overwrite or rerun."
)
QUESTION_CLOSE_POLICY = (
    "Close both the repair question and prior JSON-scope question only when the "
    "independently regenerated resolution score is 1; AUDIT_INCOMPLETE leaves "
    "both questions open."
)
SUCCESS_RULE = (
    "Exactly sixteen conformance gates must pass and the frozen primary scorer "
    "must regenerate 16; the resolution scorer returns 1 only for a terminal "
    "outcome with every terminal coverage gate satisfied, while AUDIT_INCOMPLETE "
    "returns 0 and leaves both questions open."
)
EXPLICIT_NON_CLAIMS = (
    "A structural candidate is not verified capture authority or strict provenance.",
    "No signature, calibration truth, physical truth, physical accuracy, or "
    "production readiness is established.",
    "Coverage-neutral symlink aliases are classified lexically without target "
    "dereference and do not add source evidence.",
    "The 64 MiB ceiling is a precommitted resource-safety bound; an eligible JSON "
    "above it leaves the audit incomplete.",
    "JSON-only coverage excludes PLC, database, XML, non-JSON, external-system, "
    "and excluded-tree provenance.",
    "Equal endpoint inventories are not a filesystem snapshot or lock and cannot "
    "exclude transient mutation between passes.",
    "No production source, calibration, threshold, PLC action, deployment, or "
    "production state is changed.",
)

BASE_PASS_INCOMPLETE_REASONS = frozenset(
    {
        "DIRECTORY_CHANGED_DURING_AUDIT",
        "DIRECTORY_IDENTITY_CHANGED_BEFORE_OPEN",
        "DIRECTORY_LIST_OR_STAT_FAILED",
        "DIRECTORY_OPEN_FAILED",
        "DIRECTORY_POST_STAT_FAILED",
        "ELIGIBLE_JSON_PARSE_RESOURCE_EXHAUSTED",
        "ELIGIBLE_JSON_READ_FAILED",
        "ELIGIBLE_JSON_READ_RESOURCE_EXHAUSTED",
        "ELIGIBLE_JSON_SIZE_LIMIT_EXCEEDED",
        "ENTRY_LSTAT_FAILED",
        "SYMLINK_ALIAS_JSON_NAME_TARGET_NOT_IN_ELIGIBLE_JSON_INVENTORY",
        "SYMLINK_ALIAS_TRAILING_SLASH_TARGET_NOT_REPRESENTED_DIRECTORY",
        "SYMLINK_ALIAS_TARGET_COMPONENT_NOT_REPRESENTED_DIRECTORY",
        "SYMLINK_ALIAS_TARGET_DIRECTORY_SUBTREE_NOT_COVERED",
        "SYMLINK_ALIAS_TARGET_NOT_REGULAR_FILE_OR_DIRECTORY",
        "SYMLINK_ALIAS_TARGET_NOT_REPRESENTED",
        "SYMLINK_ALIAS_TARGET_OUTSIDE_ROOT",
        "SYMLINK_CHANGED_DURING_READLINK",
        "SYMLINK_READLINK_FAILED",
    }
)
ROOT_OR_CROSS_PASS_INCOMPLETE_REASONS = frozenset(
    {
        "ELIGIBLE_JSON_INVENTORY_CHANGED_BETWEEN_PASSES",
        "PLATFORM_NO_NOFOLLOW_DIRECTORY_SUPPORT",
        "ROOT_IDENTITY_CHANGED_BEFORE_OPEN",
        "ROOT_IS_SYMLINK",
        "ROOT_LEXICAL_ABSOLUTE_PATH_FAILED",
        "ROOT_LSTAT_FAILED",
        "ROOT_NOT_DIRECTORY",
        "ROOT_OPEN_FAILED",
        "ROOT_PATH_IDENTITY_CHANGED_DURING_AUDIT",
        "ROOT_POST_LSTAT_FAILED",
        "SYMLINK_ALIAS_INVENTORY_CHANGED_BETWEEN_PASSES",
    }
)
INCOMPLETE_REASON_ALLOWLIST = frozenset(
    BASE_PASS_INCOMPLETE_REASONS
    | {f"SECOND_PASS_{reason}" for reason in BASE_PASS_INCOMPLETE_REASONS}
    | ROOT_OR_CROSS_PASS_INCOMPLETE_REASONS
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
        "endpoint_inventory_commitment_sha256",
        "scope",
        "coverage",
        "terminal_coverage",
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
        "maximum_eligible_json_bytes_interpretation",
        "bounded_read_chunk_bytes",
        "original_p2a_maximum_eligible_json_bytes",
        "symlink_policy",
        "symlink_target_dereference_used",
        "symlink_classification_inputs",
        "excluded_relative_prefixes",
        "excluded_components",
        "excluded_component_prefixes",
        "decoded_key_discovery_after_full_json_parse",
        "eligible_json_endpoint_inventory_passes",
        "symlink_alias_endpoint_inventory_passes",
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
        "second_pass_directories_scanned",
        "excluded_entries",
        "regular_files_seen",
        "eligible_json_files_seen",
        "eligible_json_files_read",
        "eligible_json_files_over_original_p2a_4mib_limit",
        "invalid_json_documents",
        "json_documents_parse_incomplete",
        "duplicate_key_json_documents",
        "malformed_or_noncanonical_json_documents",
        "candidate_json_documents",
        "noncandidate_json_documents",
        "candidate_objects_checked",
        "complete_candidates_found",
        "rejected_candidate_objects",
        "symlinks_seen",
        "coverage_neutral_symlink_aliases",
        "incomplete_symlink_aliases",
        "second_pass_symlinks_seen",
        "second_pass_coverage_neutral_symlink_aliases",
        "second_pass_incomplete_symlink_aliases",
        "second_pass_attempted_roots",
        "second_pass_completed_roots",
        "second_pass_equal_roots",
        "second_pass_inventory_records",
        "eligible_json_inventory_two_pass_equal",
        "symlink_alias_inventory_two_pass_equal",
        "endpoint_inventory_two_pass_equal",
        "audit_incomplete_reason_counts",
    }
)
TERMINAL_COVERAGE_KEYS = frozenset(
    {
        "terminal",
        "all_aliases_represented",
        "all_eligible_json_fully_analyzed",
        "regular_json_inventory_two_pass_equal",
        "symlink_alias_inventory_two_pass_equal",
        "coverage_failure_count",
    }
)
PUBLIC_ALLOWED_HASH_KEYS = frozenset(
    {
        "audit_contract_sha256",
        "eligible_json_inventory_commitment_sha256",
        "endpoint_inventory_commitment_sha256",
        "protocol_sha256",
        "private_receipt_sha256",
    }
)
PUBLIC_FORBIDDEN_KEYS = frozenset(
    {
        "root_path",
        "relative_path",
        "link_target",
        "resolved_relative_path",
        "source_sha256",
        "target_source_sha256",
        "candidate_object_sha256",
        "complete_candidate_object_sha256",
        "eligible_json_inventory",
        "symlink_alias_inventory",
        "candidate_documents",
        "invalid_json_documents_private",
        "errors",
        "roots",
        "zdf_sha256",
        "atlas_sha256",
        "calibration_sha256",
        "pre_analysis_commitment_sha256",
    }
)

PROTOCOL_KEYS = frozenset(
    {
        "schema",
        "date",
        "status",
        "tree",
        "question",
        "prior_question",
        "node_tag",
        "parent_node_tag",
        "claim_scope",
        "execution_boundary",
        "research_question",
        "post_failure_context",
        "outcome_resolution_contract",
        "privacy_boundary",
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


class ScoreRejected(RuntimeError):
    """Internal fail-closed signal with no source identity in its message."""


def _reject() -> None:
    raise ScoreRejected("E_P2A_R2_COVERAGE_REPAIR_PRIMARY_REJECTED")


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


def _normalized_absolute(path: Path) -> str:
    return os.path.abspath(os.fspath(path))


ALLOWED_READ_PATHS = frozenset(
    {
        _normalized_absolute(AUDIT_SCRIPT),
        _normalized_absolute(TEST_MODULE),
        _normalized_absolute(PRIMARY_SCORER),
        _normalized_absolute(RESOLUTION_SCORER),
        _normalized_absolute(PROTOCOL),
        _normalized_absolute(FIXED_JUNIT),
        _normalized_absolute(PUBLIC_RESULT),
        _normalized_absolute(PRIOR_P2A_PUBLIC_RESULT),
        _normalized_absolute(PRIOR_STRICT_AUDIT),
    }
)


def _stable_regular_bytes(
    path: Path,
    *,
    required_mode: int | None = None,
) -> bytes:
    # PRIVATE_RECEIPT is intentionally absent.  No caller can broaden this at
    # runtime by supplying a path that merely contains an allowed substring.
    if _normalized_absolute(path) not in ALLOWED_READ_PATHS:
        _reject()
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
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
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
        return os.path.abspath(os.fspath(supplied)) == _normalized_absolute(expected)
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


def _exact_int(value: Any, expected: int) -> bool:
    return type(value) is int and value == expected


def _nonnegative_int(value: Any) -> bool:
    return type(value) is int and value >= 0


def _walk_keys(value: Any) -> Iterable[str]:
    if type(value) is dict:
        for key, nested in value.items():
            if not isinstance(key, str):
                _reject()
            yield key
            yield from _walk_keys(nested)
    elif type(value) is list:
        for nested in value:
            yield from _walk_keys(nested)


def _static_eval(node: ast.AST, env: Mapping[str, Any]) -> Any:
    """Evaluate only the small literal language used by producer constants."""

    if isinstance(node, ast.Constant):
        if type(node.value) in {str, bytes, int, bool, type(None)}:
            return node.value
        _reject()
    if isinstance(node, ast.Name):
        if node.id not in env:
            _reject()
        return env[node.id]
    if isinstance(node, ast.List):
        return [_static_eval(item, env) for item in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_static_eval(item, env) for item in node.elts)
    if isinstance(node, ast.Set):
        return {_static_eval(item, env) for item in node.elts}
    if isinstance(node, ast.Dict):
        if any(key is None for key in node.keys):
            _reject()
        return {
            _static_eval(key, env): _static_eval(value, env)
            for key, value in zip(node.keys, node.values, strict=True)
        }
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        operand = _static_eval(node.operand, env)
        if type(operand) is not int:
            _reject()
        return operand if isinstance(node.op, ast.UAdd) else -operand
    if isinstance(node, ast.BinOp) and isinstance(
        node.op, (ast.Add, ast.Sub, ast.Mult)
    ):
        left = _static_eval(node.left, env)
        right = _static_eval(node.right, env)
        if (
            isinstance(node.op, ast.Add)
            and type(left) is type(right)
            and isinstance(left, (str, bytes, tuple, list, int))
        ):
            return left + right
        if isinstance(node.op, ast.Sub) and type(left) is int and type(right) is int:
            return left - right
        if isinstance(node.op, ast.Mult):
            if type(left) is int and type(right) is int:
                return left * right
            if type(left) is int and isinstance(right, (str, bytes, tuple, list)):
                return left * right
            if type(right) is int and isinstance(left, (str, bytes, tuple, list)):
                return left * right
        _reject()
    if isinstance(node, ast.Subscript):
        value = _static_eval(node.value, env)
        if isinstance(node.slice, ast.Slice):
            lower = (
                None
                if node.slice.lower is None
                else _static_eval(node.slice.lower, env)
            )
            upper = (
                None
                if node.slice.upper is None
                else _static_eval(node.slice.upper, env)
            )
            step = (
                None if node.slice.step is None else _static_eval(node.slice.step, env)
            )
            if any(
                item is not None and type(item) is not int
                for item in (lower, upper, step)
            ):
                _reject()
            return value[slice(lower, upper, step)]
        index = _static_eval(node.slice, env)
        if type(index) not in {int, str}:
            _reject()
        return value[index]
    if isinstance(node, ast.Call):
        if node.keywords:
            _reject()
        args = [_static_eval(argument, env) for argument in node.args]
        if isinstance(node.func, ast.Name):
            if node.func.id == "list" and len(args) == 1:
                return list(args[0])
            if node.func.id == "tuple" and len(args) == 1:
                return tuple(args[0])
            if node.func.id == "frozenset" and len(args) == 1:
                return frozenset(args[0])
            if node.func.id == "sorted" and len(args) == 1:
                return sorted(args[0])
            if (
                node.func.id == "range"
                and 1 <= len(args) <= 3
                and all(type(item) is int for item in args)
            ):
                return range(*args)
            _reject()
        if isinstance(node.func, ast.Attribute) and node.func.attr == "decode":
            receiver = _static_eval(node.func.value, env)
            if not isinstance(receiver, bytes) or args not in ([], ["ascii"]):
                _reject()
            try:
                return receiver.decode("ascii" if not args else args[0])
            except UnicodeDecodeError:
                _reject()
        _reject()
    if isinstance(node, ast.ListComp):
        if len(node.generators) != 1:
            _reject()
        generator = node.generators[0]
        if (
            generator.ifs
            or generator.is_async
            or not isinstance(generator.target, ast.Name)
        ):
            _reject()
        result = []
        for item in _static_eval(generator.iter, env):
            local = dict(env)
            local[generator.target.id] = item
            result.append(_static_eval(node.elt, local))
        return result
    _reject()


def _top_level_definitions(
    tree: ast.Module,
) -> tuple[dict[str, ast.ClassDef], dict[str, ast.FunctionDef]]:
    classes: dict[str, ast.ClassDef] = {}
    functions: dict[str, ast.FunctionDef] = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            if node.name in classes:
                _reject()
            classes[node.name] = node
        elif isinstance(node, ast.FunctionDef):
            if node.name in functions:
                _reject()
            functions[node.name] = node
    return classes, functions


def _string_literals(node: ast.AST) -> set[str]:
    return {
        value.value
        for value in ast.walk(node)
        if isinstance(value, ast.Constant) and isinstance(value.value, str)
    }


def _validate_producer_security_ast(tree: ast.Module) -> None:
    """Require the frozen fail-closed repair structures without executing them."""

    classes, functions = _top_level_definitions(tree)
    for class_name in ("_ReadResourceExhausted", "_OutputRollbackFailure"):
        definition = classes.get(class_name)
        if (
            definition is None
            or len(definition.bases) != 1
            or not isinstance(definition.bases[0], ast.Name)
            or definition.bases[0].id != "RuntimeError"
        ):
            _reject()

    required_functions = {
        "_read_regular_file_at",
        "_scan_directory",
        "_lexical_alias_target_parts",
        "_validate_alias",
        "write_audit_outputs",
    }
    if not required_functions.issubset(functions):
        _reject()

    read_wrapper = functions["_read_regular_file_at"]
    read_names = {
        node.id for node in ast.walk(read_wrapper) if isinstance(node, ast.Name)
    }
    if "_ReadResourceExhausted" not in read_names or not {
        "MemoryError",
        "OverflowError",
        "RecursionError",
    }.issubset(read_names):
        _reject()

    scan = functions["_scan_directory"]
    scan_names = {node.id for node in ast.walk(scan) if isinstance(node, ast.Name)}
    if (
        "_ReadResourceExhausted" not in scan_names
        or "ELIGIBLE_JSON_READ_RESOURCE_EXHAUSTED" not in _string_literals(scan)
    ):
        _reject()

    lexical = functions["_lexical_alias_target_parts"]
    lexical_arguments = [argument.arg for argument in lexical.args.args]
    lexical_literals = _string_literals(lexical)
    lexical_attributes = {
        node.attr for node in ast.walk(lexical) if isinstance(node, ast.Attribute)
    }
    if (
        lexical_arguments != ["alias", "root_absolute_parts", "normal_entries"]
        or not {
            "SYMLINK_ALIAS_TARGET_OUTSIDE_ROOT",
            "SYMLINK_ALIAS_TARGET_COMPONENT_NOT_REPRESENTED_DIRECTORY",
        }.issubset(lexical_literals)
        or not any(isinstance(node, ast.For) for node in ast.walk(lexical))
        or not any(isinstance(node, ast.While) for node in ast.walk(lexical))
        or "get" not in lexical_attributes
        or lexical_attributes & {"resolve", "realpath", "stat", "readlink"}
    ):
        _reject()

    validate_alias = functions["_validate_alias"]
    alias_literals = _string_literals(validate_alias)
    alias_attributes = {
        node.attr
        for node in ast.walk(validate_alias)
        if isinstance(node, ast.Attribute)
    }
    if (
        "SYMLINK_ALIAS_TRAILING_SLASH_TARGET_NOT_REPRESENTED_DIRECTORY"
        not in alias_literals
        or "/" not in alias_literals
        or "endswith" not in alias_attributes
        or alias_attributes & {"resolve", "realpath", "stat", "readlink"}
    ):
        _reject()

    writer = functions["write_audit_outputs"]
    writer_names = {node.id for node in ast.walk(writer) if isinstance(node, ast.Name)}
    if "_OutputRollbackFailure" not in writer_names:
        _reject()


def _producer_static_contract(source: bytes) -> tuple[dict[str, Any], str]:
    try:
        text = source.decode("utf-8", errors="strict")
        tree = ast.parse(text, filename=str(AUDIT_SCRIPT), mode="exec")
    except (UnicodeError, SyntaxError, ValueError):
        _reject()
    _validate_producer_security_ast(tree)
    env: dict[str, Any] = {}
    required = {
        "SCHEMA",
        "PRIVATE_SCHEMA",
        "AUDIT_DATE",
        "OUTCOME_COMPLETE",
        "OUTCOME_ABSENT",
        "OUTCOME_INCOMPLETE",
        "OUTCOMES",
        "STRICT_LAYOUT_ID",
        "JSON_SUFFIX",
        "ORIGINAL_P2A_MAX_JSON_BYTES",
        "MAX_JSON_BYTES",
        "READ_CHUNK_BYTES",
        "INVENTORY_COMMITMENT_DOMAIN",
        "ENDPOINT_COMMITMENT_DOMAIN",
        "EXCLUDED_RELATIVE_PREFIXES",
        "EXCLUDED_COMPONENTS",
        "EXCLUDED_COMPONENT_PREFIXES",
        "DECODED_KEY_GROUPS",
        "RECORD_KINDS",
        "AUTHORITY_MARKERS",
        "SYMLINK_POLICY",
        "CONTRACT",
    }
    for statement in tree.body:
        name: str | None = None
        value_node: ast.AST | None = None
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        ):
            name = statement.targets[0].id
            value_node = statement.value
        elif isinstance(statement, ast.AnnAssign) and isinstance(
            statement.target, ast.Name
        ):
            name = statement.target.id
            value_node = statement.value
        if name is None or value_node is None:
            continue
        try:
            env[name] = _static_eval(value_node, env)
        except ScoreRejected:
            if name in required:
                _reject()
    if not required.issubset(env):
        _reject()
    contract = env["CONTRACT"]
    if type(contract) is not dict:
        _reject()
    expected_contract_keys = {
        "contract_version",
        "outcomes",
        "outcome_precedence",
        "interpretation",
        "strict_provenance_established_always",
        "allowed_root_labels",
        "allowed_file_suffixes",
        "suffix_matching",
        "maximum_eligible_json_bytes",
        "maximum_eligible_json_bytes_interpretation",
        "bounded_read_chunk_bytes",
        "original_p2a_maximum_eligible_json_bytes",
        "oversize_repair_aggregate_definition",
        "eligible_json_inventory_commitment_domain",
        "endpoint_inventory_commitment_domain",
        "symlink_policy",
        "symlink_target_dereference_used",
        "symlink_classification_inputs",
        "exclusion_relative_prefixes",
        "exclusion_components",
        "exclusion_component_prefixes",
        "decoded_json_key_groups",
        "eligible_json_parse_policy",
        "endpoint_stability_policy",
        "terminal_coverage_definition",
        "filesystem_snapshot_or_lock_used",
        "endpoint_stability_limitation",
        "complete_candidate_requirements",
        "public_redaction",
    }
    if set(contract) != expected_contract_keys:
        _reject()
    if (
        env["SCHEMA"] != PUBLIC_RESULT_SCHEMA
        or env["AUDIT_DATE"] != "2026-07-14"
        or env["OUTCOMES"] != (OUTCOME_COMPLETE, OUTCOME_ABSENT, OUTCOME_INCOMPLETE)
        or env["JSON_SUFFIX"] != ".json"
        or not _exact_int(
            env["ORIGINAL_P2A_MAX_JSON_BYTES"], ORIGINAL_P2A_MAX_JSON_BYTES
        )
        or not _exact_int(env["MAX_JSON_BYTES"], MAX_JSON_BYTES)
        or not _exact_int(env["READ_CHUNK_BYTES"], READ_CHUNK_BYTES)
        or env["SYMLINK_POLICY"] != SYMLINK_POLICY
        or contract.get("contract_version")
        != "p2a-json-candidate-discovery-coverage-repair-r2-v1"
        or contract.get("outcomes")
        != [OUTCOME_COMPLETE, OUTCOME_ABSENT, OUTCOME_INCOMPLETE]
        or contract.get("outcome_precedence") != list(OUTCOME_PRECEDENCE)
        or contract.get("interpretation") != CANDIDATE_INTERPRETATION
        or contract.get("strict_provenance_established_always") is not False
        or contract.get("allowed_root_labels") != ["WORKSPACE_ROOT"]
        or contract.get("allowed_file_suffixes") != [".json"]
        or contract.get("suffix_matching") != "ASCII_CASE_INSENSITIVE"
        or not _exact_int(contract.get("maximum_eligible_json_bytes"), MAX_JSON_BYTES)
        or contract.get("maximum_eligible_json_bytes_interpretation")
        != MAXIMUM_INTERPRETATION
        or not _exact_int(contract.get("bounded_read_chunk_bytes"), READ_CHUNK_BYTES)
        or not _exact_int(
            contract.get("original_p2a_maximum_eligible_json_bytes"),
            ORIGINAL_P2A_MAX_JSON_BYTES,
        )
        or contract.get("oversize_repair_aggregate_definition")
        != (
            "First-pass count of regular .json files whose lstat size is strictly "
            "greater than the original P2a 4 MiB bound."
        )
        or contract.get("eligible_json_inventory_commitment_domain") != INVENTORY_DOMAIN
        or contract.get("endpoint_inventory_commitment_domain") != ENDPOINT_DOMAIN
        or contract.get("symlink_policy") != SYMLINK_POLICY
        or contract.get("symlink_target_dereference_used") is not False
        or contract.get("symlink_classification_inputs")
        != ["STABLE_READLINK_TEXT", "COMPLETE_NOFOLLOW_NORMAL_ENTRY_MAP"]
        or contract.get("exclusion_relative_prefixes")
        != list(EXCLUDED_RELATIVE_PREFIXES)
        or contract.get("exclusion_components") != list(EXCLUDED_COMPONENTS)
        or contract.get("exclusion_component_prefixes")
        != list(EXCLUDED_COMPONENT_PREFIXES)
        or contract.get("terminal_coverage_definition")
        != (
            "terminal is true iff all_aliases_represented, "
            "all_eligible_json_fully_analyzed, "
            "regular_json_inventory_two_pass_equal, and "
            "symlink_alias_inventory_two_pass_equal are all true and "
            "coverage_failure_count is zero"
        )
        or contract.get("filesystem_snapshot_or_lock_used") is not False
        or contract.get("endpoint_stability_limitation")
        != ENDPOINT_STABILITY_LIMITATION
    ):
        _reject()
    candidate = contract.get("complete_candidate_requirements")
    if (
        type(candidate) is not dict
        or candidate.get("strict_capture_layout_id") != "BPC_PHYSICAL_HOLDOUT_STRICT_V1"
        or candidate.get("explicit_raw_view_ids") != list(range(23))
        or any(type(value) is not int for value in candidate["explicit_raw_view_ids"])
        or candidate.get("unique_zdf_sha256_per_view") is not True
    ):
        _reject()
    return dict(contract), hashlib.sha256(_canonical_json_bytes(contract)).hexdigest()


def _validate_test_ast(source: bytes) -> None:
    try:
        text = source.decode("utf-8", errors="strict")
        tree = ast.parse(text, filename=str(TEST_MODULE), mode="exec")
    except (UnicodeError, SyntaxError, ValueError):
        _reject()
    top_level = [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    ]
    all_tests = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    ]
    if (
        top_level != list(TEST_NAMES_ORDERED)
        or all_tests != list(TEST_NAMES_ORDERED)
        or any(
            isinstance(node, ast.AsyncFunctionDef) and node.name.startswith("test_")
            for node in ast.walk(tree)
        )
    ):
        _reject()

    definitions = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    }
    alias_regression_literals = _string_literals(
        definitions["test_09_excluded_and_link_chain_targets_are_not_represented"]
    )
    if not {
        "missing/../target.json",
        "bridge/../target.json",
        "real/../target.json",
        "target.json/",
        "absolute-leave-reenter",
        "SYMLINK_ALIAS_TARGET_COMPONENT_NOT_REPRESENTED_DIRECTORY",
        "SYMLINK_ALIAS_TARGET_OUTSIDE_ROOT",
        "SYMLINK_ALIAS_TRAILING_SLASH_TARGET_NOT_REPRESENTED_DIRECTORY",
        "SECOND_PASS_SYMLINK_ALIAS_TARGET_COMPONENT_NOT_REPRESENTED_DIRECTORY",
        "SECOND_PASS_SYMLINK_ALIAS_TARGET_OUTSIDE_ROOT",
        "SECOND_PASS_SYMLINK_ALIAS_TRAILING_SLASH_TARGET_NOT_REPRESENTED_DIRECTORY",
    }.issubset(alias_regression_literals):
        _reject()

    read_regression_literals = _string_literals(
        definitions["test_13_read_failure_and_between_pass_mutation_are_fail_closed"]
    )
    if not {
        "ELIGIBLE_JSON_READ_RESOURCE_EXHAUSTED",
        "SECOND_PASS_ELIGIBLE_JSON_READ_RESOURCE_EXHAUSTED",
    }.issubset(read_regression_literals):
        _reject()

    output_regression = definitions[
        "test_15_public_redaction_atomic_modes_and_no_clobber"
    ]
    output_attributes = {
        node.attr
        for node in ast.walk(output_regression)
        if isinstance(node, ast.Attribute)
    }
    if "_OutputRollbackFailure" not in output_attributes:
        _reject()

    test_99_literals = _string_literals(
        definitions["test_99_preregistered_workspace_coverage_repair_runs_last"]
    )
    if not {
        "2026-07-14",
        "protocol_path",
        "junit_path",
        "public_result_path",
        "private_receipt_path",
        "primary_scorer_path",
        "resolution_scorer_path",
    }.issubset(test_99_literals):
        _reject()


def _validate_counter(value: Any) -> dict[str, int]:
    if type(value) is not dict or list(value) != sorted(value):
        _reject()
    result: dict[str, int] = {}
    for reason, count in value.items():
        if (
            not isinstance(reason, str)
            or reason not in INCOMPLETE_REASON_ALLOWLIST
            or not _nonnegative_int(count)
            or count == 0
        ):
            _reject()
        result[reason] = count
    return result


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
    if any(
        token in lowered
        for token in (
            b"/data/",
            b".private_bpc",
            b".zdf",
            b"link_target",
            b"relative_path",
        )
    ):
        _reject()


def _validate_scope(scope: Any) -> None:
    exact = _exact_keys(scope, PUBLIC_SCOPE_KEYS)
    if (
        exact.get("allowed_root_labels") != ["WORKSPACE_ROOT"]
        or not _exact_int(exact.get("allowed_root_count"), 1)
        or exact.get("allowed_file_suffixes") != [".json"]
        or not _exact_int(exact.get("maximum_eligible_json_bytes"), MAX_JSON_BYTES)
        or exact.get("maximum_eligible_json_bytes_interpretation")
        != MAXIMUM_INTERPRETATION
        or not _exact_int(exact.get("bounded_read_chunk_bytes"), READ_CHUNK_BYTES)
        or not _exact_int(
            exact.get("original_p2a_maximum_eligible_json_bytes"),
            ORIGINAL_P2A_MAX_JSON_BYTES,
        )
        or exact.get("symlink_policy") != SYMLINK_POLICY
        or exact.get("symlink_target_dereference_used") is not False
        or exact.get("symlink_classification_inputs")
        != ["STABLE_READLINK_TEXT", "COMPLETE_NOFOLLOW_NORMAL_ENTRY_MAP"]
        or exact.get("excluded_relative_prefixes") != list(EXCLUDED_RELATIVE_PREFIXES)
        or exact.get("excluded_components") != list(EXCLUDED_COMPONENTS)
        or exact.get("excluded_component_prefixes") != list(EXCLUDED_COMPONENT_PREFIXES)
        or exact.get("decoded_key_discovery_after_full_json_parse") is not True
        or not _exact_int(exact.get("eligible_json_endpoint_inventory_passes"), 2)
        or not _exact_int(exact.get("symlink_alias_endpoint_inventory_passes"), 2)
        or exact.get("filesystem_snapshot_or_lock_used") is not False
        or exact.get("endpoint_stability_limitation") != ENDPOINT_STABILITY_LIMITATION
        or exact.get("json_only_scope_limitation") != JSON_SCOPE_LIMITATION
    ):
        _reject()


def _validate_coverage(coverage: Any) -> tuple[dict[str, Any], dict[str, int]]:
    exact = _exact_keys(coverage, PUBLIC_COVERAGE_KEYS)
    boolean_keys = {
        "eligible_json_inventory_two_pass_equal",
        "symlink_alias_inventory_two_pass_equal",
        "endpoint_inventory_two_pass_equal",
    }
    counter_key = "audit_incomplete_reason_counts"
    for key in PUBLIC_COVERAGE_KEYS - boolean_keys - {counter_key}:
        if not _nonnegative_int(exact.get(key)):
            _reject()
    if any(type(exact.get(key)) is not bool for key in boolean_keys):
        _reject()
    reasons = _validate_counter(exact.get(counter_key))
    if (
        exact.get("roots_requested") != 1
        or exact.get("roots_opened") > 1
        or exact.get("invalid_json_documents")
        != exact.get("duplicate_key_json_documents")
        + exact.get("malformed_or_noncanonical_json_documents")
        or exact.get("eligible_json_files_read")
        != exact.get("invalid_json_documents")
        + exact.get("json_documents_parse_incomplete")
        + exact.get("candidate_json_documents")
        + exact.get("noncandidate_json_documents")
        or exact.get("eligible_json_files_seen") < exact.get("eligible_json_files_read")
        or exact.get("eligible_json_files_over_original_p2a_4mib_limit")
        > exact.get("eligible_json_files_seen")
        or exact.get("regular_files_seen") < exact.get("eligible_json_files_seen")
        or exact.get("coverage_neutral_symlink_aliases")
        + exact.get("incomplete_symlink_aliases")
        != exact.get("symlinks_seen")
        or exact.get("second_pass_coverage_neutral_symlink_aliases")
        + exact.get("second_pass_incomplete_symlink_aliases")
        != exact.get("second_pass_symlinks_seen")
        or exact.get("second_pass_attempted_roots") != exact.get("roots_opened")
        or exact.get("second_pass_completed_roots")
        > exact.get("second_pass_attempted_roots")
        or exact.get("second_pass_equal_roots")
        > exact.get("second_pass_completed_roots")
        or exact.get("endpoint_inventory_two_pass_equal")
        is not (
            exact.get("eligible_json_inventory_two_pass_equal") is True
            and exact.get("symlink_alias_inventory_two_pass_equal") is True
            and exact.get("second_pass_equal_roots") == 1
        )
    ):
        _reject()
    if exact.get("roots_opened") == 0:
        if any(
            exact.get(key) != 0
            for key in (
                "directories_scanned",
                "second_pass_directories_scanned",
                "regular_files_seen",
                "eligible_json_files_seen",
                "eligible_json_files_read",
                "second_pass_attempted_roots",
            )
        ):
            _reject()
    elif (
        exact.get("directories_scanned") < 1
        or exact.get("second_pass_directories_scanned") < 1
    ):
        _reject()
    if exact.get("second_pass_equal_roots") == 1 and (
        exact.get("second_pass_inventory_records")
        != exact.get("eligible_json_files_read")
    ):
        _reject()
    return exact, reasons


def _validate_terminal_coverage(
    value: Any,
    *,
    coverage: Mapping[str, Any],
    reasons: Mapping[str, int],
) -> dict[str, Any]:
    exact = _exact_keys(value, TERMINAL_COVERAGE_KEYS)
    boolean_keys = TERMINAL_COVERAGE_KEYS - {"coverage_failure_count"}
    if (
        any(type(exact.get(key)) is not bool for key in boolean_keys)
        or not _nonnegative_int(exact.get("coverage_failure_count"))
        or exact.get("coverage_failure_count") != sum(reasons.values())
        or exact.get("regular_json_inventory_two_pass_equal")
        is not coverage.get("eligible_json_inventory_two_pass_equal")
        or exact.get("symlink_alias_inventory_two_pass_equal")
        is not coverage.get("symlink_alias_inventory_two_pass_equal")
        or exact.get("terminal")
        is not (
            exact.get("all_aliases_represented") is True
            and exact.get("all_eligible_json_fully_analyzed") is True
            and exact.get("regular_json_inventory_two_pass_equal") is True
            and exact.get("symlink_alias_inventory_two_pass_equal") is True
            and exact.get("coverage_failure_count") == 0
        )
    ):
        _reject()
    if exact.get("all_eligible_json_fully_analyzed") is True and (
        coverage.get("roots_opened") != coverage.get("roots_requested")
        or coverage.get("eligible_json_files_seen")
        != coverage.get("eligible_json_files_read")
        or coverage.get("json_documents_parse_incomplete") != 0
    ):
        _reject()
    if exact.get("all_aliases_represented") is True and (
        coverage.get("incomplete_symlink_aliases") != 0
        or coverage.get("second_pass_incomplete_symlink_aliases") != 0
    ):
        _reject()
    return exact


def _terminal_coverage_gates(
    coverage: Mapping[str, Any], terminal: Mapping[str, Any]
) -> bool:
    return (
        terminal.get("terminal") is True
        and terminal.get("all_aliases_represented") is True
        and terminal.get("all_eligible_json_fully_analyzed") is True
        and terminal.get("regular_json_inventory_two_pass_equal") is True
        and terminal.get("symlink_alias_inventory_two_pass_equal") is True
        and terminal.get("coverage_failure_count") == 0
        and coverage.get("audit_incomplete_reason_counts") == {}
        and coverage.get("roots_requested") == 1
        and coverage.get("roots_opened") == 1
        and coverage.get("json_documents_parse_incomplete") == 0
        and coverage.get("incomplete_symlink_aliases") == 0
        and coverage.get("second_pass_incomplete_symlink_aliases") == 0
        and coverage.get("symlinks_seen")
        == coverage.get("coverage_neutral_symlink_aliases")
        and coverage.get("second_pass_symlinks_seen")
        == coverage.get("second_pass_coverage_neutral_symlink_aliases")
        and coverage.get("second_pass_attempted_roots") == 1
        and coverage.get("second_pass_completed_roots") == 1
        and coverage.get("second_pass_equal_roots") == 1
        and coverage.get("second_pass_inventory_records")
        == coverage.get("eligible_json_files_read")
        and coverage.get("eligible_json_inventory_two_pass_equal") is True
        and coverage.get("symlink_alias_inventory_two_pass_equal") is True
        and coverage.get("endpoint_inventory_two_pass_equal") is True
    )


def _validate_public(protocol_raw: bytes, audit_contract_sha256: str) -> str:
    public_raw = _stable_regular_bytes(PUBLIC_RESULT, required_mode=0o444)
    public = _load_json(public_raw)
    _validate_public_privacy(public, public_raw)
    _validate_scope(public.get("scope"))
    coverage, reasons = _validate_coverage(public.get("coverage"))
    terminal = _validate_terminal_coverage(
        public.get("terminal_coverage"), coverage=coverage, reasons=reasons
    )
    outcome = public.get("outcome")
    expected_outcome = (
        OUTCOME_INCOMPLETE
        if terminal.get("terminal") is not True
        else (
            OUTCOME_COMPLETE
            if coverage.get("complete_candidates_found", 0) > 0
            else OUTCOME_ABSENT
        )
    )
    if (
        outcome not in OUTCOMES
        or outcome != expected_outcome
        or public.get("status") != outcome
        or public.get("schema") != PUBLIC_RESULT_SCHEMA
        or public.get("date") != "2026-07-14"
        or public.get("strict_provenance_established") is not False
        or public.get("candidate_interpretation") != CANDIDATE_INTERPRETATION
        or public.get("audit_contract_sha256") != audit_contract_sha256
        or not _is_sha256(public.get("eligible_json_inventory_commitment_sha256"))
        or not _is_sha256(public.get("endpoint_inventory_commitment_sha256"))
        or public.get("public_redaction_applied") is not True
        or public.get("authority_marker_truth_verified") is not False
        or public.get("signature_verified") is not False
        or public.get("physical_truth_verified") is not False
        or public.get("production_change") is not False
        or public.get("protocol_sha256") != hashlib.sha256(protocol_raw).hexdigest()
        or not _is_sha256(public.get("private_receipt_sha256"))
    ):
        _reject()
    if outcome in TERMINAL_OUTCOMES and not _terminal_coverage_gates(
        coverage, terminal
    ):
        _reject()
    if outcome == OUTCOME_INCOMPLETE and terminal.get("terminal") is not False:
        _reject()
    return outcome


def _validate_protocol(protocol_raw: bytes) -> None:
    protocol = _load_json(protocol_raw)
    if _canonical_json_bytes(protocol) != protocol_raw:
        _reject()
    exact = _exact_keys(protocol, PROTOCOL_KEYS)
    if (
        exact.get("schema") != PROTOCOL_SCHEMA
        or exact.get("date") != "2026-07-14"
        or exact.get("status") != PROTOCOL_STATUS
        or exact.get("tree") != TREE
        or exact.get("question") != QUESTION
        or exact.get("prior_question") != PRIOR_QUESTION
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
    if exact.get("post_failure_context") != {
        "classification": "POST_FAILURE_COVERAGE_REPAIR_NOT_INDEPENDENT_CONFIRMATION",
        "prior_p2a_outcome": OUTCOME_INCOMPLETE,
        "prior_p2a_prediction_and_judgement_preserved": True,
        "prior_p2a_public_result_sha256": PRIOR_P2A_PUBLIC_RESULT_SHA256,
        "known_public_aggregates": {
            "eligible_json_files_seen": 1580,
            "eligible_json_files_read": 1578,
            "candidate_json_documents": 0,
            "complete_candidates_found": 0,
            "nonexcluded_symlinks_per_pass": 5,
            "eligible_json_over_4mib_per_pass": 2,
        },
        "private_identity_or_exact_size_read_before_r2_freeze": False,
        "exclusions_changed": False,
        "candidate_contract_changed": False,
        "r2_prediction_targets_coverage_resolution_not_candidate_presence": True,
        "incomplete_result_preserved_without_rerun_or_policy_adjustment": True,
    }:
        _reject()
    if exact.get("outcome_resolution_contract") != {
        "outcome_precedence": list(OUTCOME_PRECEDENCE),
        "terminal_resolution_outcomes": [OUTCOME_COMPLETE, OUTCOME_ABSENT],
        "resolution_score_by_outcome": RESOLUTION_BY_OUTCOME,
        "terminal_coverage_gates_required": True,
        "audit_incomplete_leaves_both_questions_open": True,
    }:
        _reject()
    if exact.get("privacy_boundary") != {
        "public_result_mode": "0444",
        "private_receipt_mode": "0600",
        "private_parent_mode": "0700",
        "canonical_json_required": True,
        "public_source_identity_allowed": False,
        "scorers_may_read_private_receipt": False,
        "private_receipt_sha256_commitment_required": True,
    }:
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
    if exact.get("measurement_contract") != {
        "allowed_root": str(WORKSPACE),
        "allowed_file_suffixes": [".json"],
        "maximum_eligible_json_bytes": MAX_JSON_BYTES,
        "maximum_eligible_json_bytes_interpretation": MAXIMUM_INTERPRETATION,
        "symlink_classification": (
            "READLINK_TEXT_PLUS_COMPLETE_NOFOLLOW_NORMAL_ENTRY_MAP_"
            "NO_TARGET_DEREFERENCE"
        ),
        "actual_scan_before_prediction": False,
        "junit_target_absent_before_run": True,
        "public_source_identity_allowed": False,
        "strict_provenance_established_always": False,
    }:
        _reject()
    prediction = exact.get("prediction")
    if type(prediction) is not dict or set(prediction) != {
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
        "closes_questions_on_success",
    }:
        _reject()
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
        or prediction.get("closes_questions_on_success") != [QUESTION, PRIOR_QUESTION]
    ):
        _reject()
    inventory = exact.get("test_inventory")
    if inventory != {
        "classname": CLASSNAME,
        "total": EXPECTED_TOTAL,
        "names": list(TEST_NAMES_ORDERED),
        "actual_workspace_audit_cases": 1,
        "synthetic_contract_security_privacy_cases": 15,
    }:
        _reject()
    assets = exact.get("frozen_assets")
    expected_assets = {
        "audit_script": {"path": str(AUDIT_SCRIPT), "sha256": AUDIT_SCRIPT_SHA256},
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
        "junit": {"path": str(FIXED_JUNIT), "preflight": "ABSENT_BEFORE_ONE_TIME_RUN"},
        "public_result": {
            "path": str(PUBLIC_RESULT),
            "preflight": "ABSENT_BEFORE_ONE_TIME_RUN",
        },
        "private_receipt": {
            "path": str(PRIVATE_RECEIPT),
            "preflight": "ABSENT_BEFORE_ONE_TIME_RUN",
            "mode": "0600",
            "parent_mode": "0700",
            "scorer_read_forbidden": True,
        },
        "prior_p2a_public_result": {
            "path": str(PRIOR_P2A_PUBLIC_RESULT),
            "sha256": PRIOR_P2A_PUBLIC_RESULT_SHA256,
        },
        "prior_strict_boundary_audit": {
            "path": str(PRIOR_STRICT_AUDIT),
            "sha256": PRIOR_STRICT_AUDIT_SHA256,
        },
    }
    if assets != expected_assets:
        _reject()
    execution = exact.get("execution")
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
    static = exact.get("static_preflight_details")
    if static != {
        "producer_and_test_hashes_checked": True,
        "producer_contract_checked_by_static_ast": True,
        "scorer_cross_bind_checked": True,
        "exact_sixteen_test_definitions_checked_statically": True,
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


def validate_public_result() -> str:
    """Validate frozen public evidence without opening the private receipt."""

    audit_source = _stable_regular_bytes(AUDIT_SCRIPT)
    test_source = _stable_regular_bytes(TEST_MODULE)
    if (
        hashlib.sha256(audit_source).hexdigest() != AUDIT_SCRIPT_SHA256
        or hashlib.sha256(test_source).hexdigest() != TEST_MODULE_SHA256
    ):
        _reject()
    _validate_test_ast(test_source)
    _, contract_sha256 = _producer_static_contract(audit_source)
    protocol_raw = _stable_regular_bytes(PROTOCOL, required_mode=0o444)
    _validate_protocol(protocol_raw)
    return _validate_public(protocol_raw, contract_sha256)


def terminal_resolution_score() -> int:
    """Return one only for a validated terminal public coverage result."""

    outcome = validate_public_result()
    if outcome in TERMINAL_OUTCOMES:
        return 1
    if outcome == OUTCOME_INCOMPLETE:
        return 0
    _reject()


def _score_strict() -> int:
    for path, committed in (
        (AUDIT_SCRIPT, AUDIT_SCRIPT_SHA256),
        (TEST_MODULE, TEST_MODULE_SHA256),
        (PRIOR_P2A_PUBLIC_RESULT, PRIOR_P2A_PUBLIC_RESULT_SHA256),
        (PRIOR_STRICT_AUDIT, PRIOR_STRICT_AUDIT_SHA256),
    ):
        if not _is_sha256(committed):
            _reject()
        if hashlib.sha256(_stable_regular_bytes(path)).hexdigest() != committed:
            _reject()
    validate_public_result()
    return _score_junit()


def score() -> int:
    """Return sixteen on full conformance and zero on every rejection."""

    try:
        return _score_strict()
    except Exception:
        return 0


def main() -> int:
    metric = 0
    if len(sys.argv) == 2 and _same_fixed_path(sys.argv[1], FIXED_JUNIT):
        metric = score()
    print(f"metric={metric}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
