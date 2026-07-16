#!/usr/bin/env python3
"""Score the P2a-R2 scorer repair without rerunning the workspace audit.

The frozen R2 judges are never imported or executed.  This repair judge reads
only public, hash-bound artifacts, applies a structured privacy check that does
not search key spellings as raw substrings, and preserves the known scientific
result: original conformance 16, public ``AUDIT_INCOMPLETE``, resolution 0.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any
import xml.etree.ElementTree as ET


WORKSPACE = Path("/data/kjra/PROJECT/3DLAB")
BPC_ROOT = WORKSPACE / "BPC_ICP_SPEC"
LAKATO_ROOT = Path("/data/kjra/PROJECT/PI/lakatotree")

R2_PRODUCER = BPC_ROOT / (
    "scripts/tab_bolt_existing_authoritative_strict_provenance_audit_"
    "coverage_repair_r2.py"
)
R2_TEST = BPC_ROOT / (
    "tests/test_tab_bolt_existing_authoritative_strict_provenance_audit_"
    "coverage_repair_r2.py"
)
R2_PRIMARY = LAKATO_ROOT / (
    "scripts/judge_bpc_tab_existing_strict_provenance_candidate_coverage_"
    "repair_r2_p2a_20260714.py"
)
R2_RESOLUTION = LAKATO_ROOT / (
    "scripts/judge_bpc_tab_existing_strict_provenance_candidate_coverage_"
    "repair_resolution_r2_p2a_20260714.py"
)
R2_PROTOCOL = BPC_ROOT / (
    "evidence/bpc_tab_bolt_existing_authoritative_strict_provenance_candidate_"
    "coverage_repair_r2_protocol_20260714.json"
)
R2_JUNIT = BPC_ROOT / (
    "evidence/bpc_tab_bolt_existing_authoritative_strict_provenance_candidate_"
    "coverage_repair_r2_conformance_20260714.xml"
)
R2_PUBLIC = BPC_ROOT / (
    "evidence/bpc_tab_bolt_existing_authoritative_strict_provenance_candidate_"
    "coverage_repair_r2_result_20260714.json"
)
R2_FAILURE = BPC_ROOT / (
    "evidence/bpc_tab_bolt_existing_authoritative_strict_provenance_candidate_"
    "coverage_repair_r2_scorer_failure_20260714.json"
)

R3_TEST = BPC_ROOT / (
    "tests/test_tab_bolt_existing_authoritative_strict_provenance_candidate_"
    "coverage_repair_r2_scorer_repair_r3.py"
)
R3_PRIMARY = Path(__file__).absolute()
R3_CONFIRMATORY = LAKATO_ROOT / (
    "scripts/judge_bpc_tab_existing_strict_provenance_candidate_coverage_"
    "repair_r2_scorer_repair_confirmatory_r3_p2a_20260714.py"
)
R3_PROTOCOL = BPC_ROOT / (
    "evidence/bpc_tab_bolt_existing_authoritative_strict_provenance_candidate_"
    "coverage_repair_r2_scorer_repair_r3_protocol_20260714.json"
)
R3_JUNIT = BPC_ROOT / (
    "evidence/bpc_tab_bolt_existing_authoritative_strict_provenance_candidate_"
    "coverage_repair_r2_scorer_repair_r3_conformance_20260714.xml"
)

R2_SHA256 = {
    R2_PRODUCER: "138a026cfee8c95e2d44d8522c2c6406e32e78b4d66047d972fc61e0600788ed",
    R2_TEST: "1acd6525e59a96e79bb18ecdc711c0fb61607414188b33f759a4a19dd91bd405",
    R2_PRIMARY: "ca2f1c1933059a0b34ce5f42f5857381991c6780812ad413cff3741076bf3b3f",
    R2_RESOLUTION: "4fce909b46912a44702c88a4abf80d4a7b2a15dcdae8da42bf1fee929a381aea",
    R2_PROTOCOL: "25cdaef60176bfd4df1786e08cb23e7402f292188c9abb49e212407807b95392",
    R2_JUNIT: "7b87eeb8dfe7d834eacaf1d0fedbe023b551d4d3ca491ef86c5b1c8d7c8ebb08",
    R2_PUBLIC: "91b8b16be8dc38df4ef4e0b70b1c279b52f6ae30a9a50b1f5dcd97d7a8167301",
    R2_FAILURE: "672aeddc8b7c24b35190e78cc7d209afd1530ec66919b9ba5f1bb290f7559ca4",
}
R2_PRIVATE_COMMITMENT = (
    "fc9db2ae20b0d3d2f20f3db61fb7edd6feb6910e0821e0663a8d6e5dc119849d"
)
R2_PREDICTION_RECEIPT = (
    "1109ec62dcd4e744653cee60c85574445ea9a544acf9d824b46be95b5ba4aa5b"
)
R2_JUDGEMENT_RECEIPT = (
    "7619719d6086e7c191f9d57ce0214d350b451c9ef6a1f1ef4c311d1c3f725ca5"
)
R2_AUDIT_CONTRACT_SHA256 = (
    "385511e814a1fcedfee5d7616b209184a68c4e21ee4e6d5fd8c9fe9f20b8b571"
)

TREE = "LakatosTree_BPC_TabBolt_Inference_20260701"
QUESTION = (
    "q_bpc_existing_strict_provenance_candidate_coverage_repair_r2_"
    "scorer_repair_20260714"
)
NODE_TAG = (
    "tab_existing_strict_provenance_candidate_coverage_repair_r2_"
    "scorer_repair_r3_20260714"
)
PARENT_NODE = "tab_existing_strict_provenance_candidate_coverage_repair_r2_20260714"
R2_QUESTION = "q_bpc_existing_strict_provenance_candidate_coverage_repair_r2_20260714"
PRIOR_QUESTION = (
    "q_bpc_existing_strict_provenance_candidate_json_scope_resolution_20260714"
)
PROTOCOL_SCHEMA = (
    "bpc.tab_bolt.existing_strict_provenance_candidate_coverage_repair_r2_"
    "scorer_repair_r3_preregistration.v1"
)
PROTOCOL_STATUS = "PREREGISTERED_R3_EXISTING_RESULT_KNOWN_SCORER_REPAIR_UNRUN"
CLAIM_SCOPE = "P2A_R2_EXISTING_EVIDENCE_SCORER_REPAIR_ONLY"
EXECUTION_BOUNDARY = (
    "SCORER_REPAIR_ONLY_ON_PRESERVED_KNOWN_P2A_R2_ARTIFACTS_"
    "NO_WORKSPACE_MEASUREMENT_RERUN"
)
RESEARCH_QUESTION = (
    "Can a frozen six-case scorer repair eliminate the preserved P2a-R2 "
    "required-key substring false rejection while preserving the original "
    "exact-sixteen measurement, AUDIT_INCOMPLETE outcome, and resolution zero "
    "without a private-receipt read or workspace-scan rerun?"
)
PRIMARY_METRIC = (
    "existing_strict_provenance_candidate_coverage_repair_r2_scorer_repair_gate_count"
)

EXECUTION_CWD = str(BPC_ROOT)
EXECUTION_PYTHON = "/data/kjra/miniconda3/envs/prismv2/bin/python"
EXECUTION_COMMAND = (
    "env PYTHONDONTWRITEBYTECODE=1 "
    "/data/kjra/miniconda3/envs/prismv2/bin/python -m pytest -q "
    "-p no:cacheprovider tests/test_tab_bolt_existing_authoritative_strict_"
    "provenance_candidate_coverage_repair_r2_scorer_repair_r3.py "
    "--junitxml=evidence/bpc_tab_bolt_existing_authoritative_strict_"
    "provenance_candidate_coverage_repair_r2_scorer_repair_r3_"
    "conformance_20260714.xml"
)
MEASUREMENT_POLICY = (
    "Run the exact-six scorer-repair command once only after the R3 protocol "
    "and LakatoTree prediction bind all frozen assets. Do not rerun or overwrite "
    "the R2 producer, workspace scan, JUnit, public result, or private receipt."
)
CONFIRMATORY_POLICY = (
    "Only after the repaired primary returns six, run the frozen confirmatory "
    "judge once against the same R3 JUnit. Its original conformance sixteen and "
    "resolution zero are known-result confirmation only and are not LakatoTree "
    "novel evidence."
)
FAILURE_POLICY = (
    "Preserve every R3 failure without rerun or artifact overwrite; any further "
    "repair requires a new protocol, prediction, node, scorer, and JUnit path."
)
SUCCESS_RULE = (
    "Exactly six repair-conformance tests must pass and the frozen R3 primary "
    "must regenerate metric 6 while independently readjudicating the preserved "
    "R2 public chain as conformance 16 and terminal resolution 0. Only the new "
    "repair question may close; both original coverage questions remain open."
)
EXPLICIT_NON_CLAIMS = (
    "R3 does not rerun or replace the R2 producer, workspace scan, JUnit, public result, or private receipt.",
    "The original conformance count 16 and resolution score 0 were known before R3 and are not novel evidence or independent replication.",
    "The repair changes only scorer treatment of a required public key spelling; it does not change the R2 scientific outcome.",
    "AUDIT_INCOMPLETE remains in force because four outside-root symbolic-link targets per pass remain uncovered.",
    "No full-logical-scope candidate absence, capture authority, signature validity, calibration truth, physical truth, or strict provenance is established.",
    "No production source, calibration, threshold, PLC action, deployment, or production state is changed.",
)

PUBLIC_SCHEMA = (
    "bpc.tab_bolt.existing_strict_provenance_candidate_discovery_coverage_repair_r2.v1"
)
OUTCOME_INCOMPLETE = "AUDIT_INCOMPLETE"
EXPECTED_ORIGINAL = 16
EXPECTED_REPAIR = 6
R2_CLASSNAME = (
    "tests.test_tab_bolt_existing_authoritative_strict_provenance_audit_"
    "coverage_repair_r2"
)
R2_TEST_NAMES = (
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
R3_CLASSNAME = (
    "tests.test_tab_bolt_existing_authoritative_strict_provenance_candidate_"
    "coverage_repair_r2_scorer_repair_r3"
)
R3_TEST_NAMES = (
    "test_r2_required_public_key_triggers_frozen_substring_false_positive",
    "test_r3_privacy_gate_accepts_required_symlink_target_dereference_key",
    "test_r3_privacy_gate_rejects_exact_forbidden_identity_keys",
    "test_r3_privacy_gate_rejects_sensitive_value_tokens",
    "test_r3_privacy_gate_rejects_noncanonical_and_unexpected_hash_keys",
    "test_preserved_r2_chain_recovers_sixteen_and_keeps_resolution_zero",
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
PUBLIC_TERMINAL_KEYS = frozenset(
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
SENSITIVE_VALUE_TOKENS = (
    "/data/",
    ".private_bpc",
    ".zdf",
    "link_target",
    "relative_path",
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_SMALL_FILE_BYTES = 32 * 1024 * 1024

ALLOWED_READ_PATHS = frozenset(
    os.path.abspath(os.fspath(path))
    for path in {
        *R2_SHA256,
        R3_TEST,
        R3_PRIMARY,
        R3_CONFIRMATORY,
        R3_PROTOCOL,
        R3_JUNIT,
    }
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
        "known_existing_result_disclosure",
        "preserved_scientific_result",
        "repair_diff",
        "r2_failure_lineage",
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


class ScoreRejected(RuntimeError):
    """Fail closed without echoing private values or source identities."""


def _reject() -> None:
    raise ScoreRejected("E_P2A_R2_SCORER_REPAIR_R3_REJECTED")


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


def _stable_regular_bytes(path: Path, *, required_mode: int | None = None) -> bytes:
    if os.path.abspath(os.fspath(path)) not in ALLOWED_READ_PATHS:
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
            block = os.read(descriptor, min(1024 * 1024, opened.st_size - len(value)))
            if not block:
                _reject()
            value.extend(block)
        if os.read(descriptor, 1) or _fingerprint(os.fstat(descriptor)) != _fingerprint(
            opened
        ):
            _reject()
        if _fingerprint(path.lstat()) != _fingerprint(opened):
            _reject()
        return bytes(value)
    finally:
        os.close(descriptor)


def _sha256(path: Path) -> str:
    return hashlib.sha256(_stable_regular_bytes(path)).hexdigest()


def _same_fixed_path(supplied: str, expected: Path) -> bool:
    try:
        return os.path.abspath(os.fspath(supplied)) == os.path.abspath(
            os.fspath(expected)
        )
    except (OSError, TypeError, ValueError):
        return False


def _reject_constant(_: str) -> None:
    _reject()


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
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
            object_pairs_hook=_reject_duplicates,
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


def _walk_string_values(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif type(value) is dict:
        for nested in value.values():
            yield from _walk_string_values(nested)
    elif type(value) is list:
        for nested in value:
            yield from _walk_string_values(nested)


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and SHA256_RE.fullmatch(value) is not None
        and value != "0" * 64
    )


def _validate_public_privacy(public: Mapping[str, Any], raw: bytes) -> None:
    """Validate keys structurally and scan only values for sensitive tokens."""

    exact = _exact_keys(public, PUBLIC_RESULT_KEYS)
    if _canonical_json_bytes(exact) != raw:
        _reject()
    _exact_keys(exact.get("scope"), PUBLIC_SCOPE_KEYS)
    _exact_keys(exact.get("coverage"), PUBLIC_COVERAGE_KEYS)
    _exact_keys(exact.get("terminal_coverage"), PUBLIC_TERMINAL_KEYS)
    keys = set(_walk_keys(exact))
    if keys & PUBLIC_FORBIDDEN_KEYS:
        _reject()
    for key in keys:
        if key.endswith("_sha256") and key not in PUBLIC_ALLOWED_HASH_KEYS:
            _reject()
        if key.endswith(("_path", "_filename", "_excerpt")):
            _reject()
    for value in _walk_string_values(exact):
        lowered = value.lower()
        if any(token in lowered for token in SENSITIVE_VALUE_TOKENS):
            _reject()


def _validate_public_result(raw: bytes) -> dict[str, Any]:
    public = _load_json(raw)
    _validate_public_privacy(public, raw)
    coverage = public.get("coverage")
    terminal = public.get("terminal_coverage")
    scope = public.get("scope")
    if (
        type(coverage) is not dict
        or type(terminal) is not dict
        or type(scope) is not dict
    ):
        _reject()
    reasons = coverage.get("audit_incomplete_reason_counts")
    expected_reasons = {
        "SECOND_PASS_SYMLINK_ALIAS_TARGET_OUTSIDE_ROOT": 4,
        "SYMLINK_ALIAS_TARGET_OUTSIDE_ROOT": 4,
    }
    expected_counts = {
        "roots_requested": 1,
        "roots_opened": 1,
        "eligible_json_files_seen": 1580,
        "eligible_json_files_read": 1580,
        "eligible_json_files_over_original_p2a_4mib_limit": 2,
        "invalid_json_documents": 18,
        "json_documents_parse_incomplete": 0,
        "candidate_json_documents": 0,
        "noncandidate_json_documents": 1562,
        "candidate_objects_checked": 0,
        "complete_candidates_found": 0,
        "symlinks_seen": 5,
        "coverage_neutral_symlink_aliases": 1,
        "incomplete_symlink_aliases": 4,
        "second_pass_symlinks_seen": 5,
        "second_pass_coverage_neutral_symlink_aliases": 1,
        "second_pass_incomplete_symlink_aliases": 4,
        "second_pass_attempted_roots": 1,
        "second_pass_completed_roots": 0,
        "second_pass_equal_roots": 0,
        "second_pass_inventory_records": 1580,
    }
    if any(coverage.get(key) != value for key, value in expected_counts.items()):
        _reject()
    if reasons != expected_reasons:
        _reject()
    if (
        coverage.get("eligible_json_inventory_two_pass_equal") is not True
        or coverage.get("symlink_alias_inventory_two_pass_equal") is not True
        or coverage.get("endpoint_inventory_two_pass_equal") is not False
        or scope.get("symlink_target_dereference_used") is not False
        or scope.get("maximum_eligible_json_bytes") != 64 * 1024 * 1024
        or terminal
        != {
            "all_aliases_represented": False,
            "all_eligible_json_fully_analyzed": True,
            "coverage_failure_count": 8,
            "regular_json_inventory_two_pass_equal": True,
            "symlink_alias_inventory_two_pass_equal": True,
            "terminal": False,
        }
        or public.get("schema") != PUBLIC_SCHEMA
        or public.get("date") != "2026-07-14"
        or public.get("status") != OUTCOME_INCOMPLETE
        or public.get("outcome") != OUTCOME_INCOMPLETE
        or public.get("strict_provenance_established") is not False
        or public.get("authority_marker_truth_verified") is not False
        or public.get("signature_verified") is not False
        or public.get("physical_truth_verified") is not False
        or public.get("production_change") is not False
        or public.get("public_redaction_applied") is not True
        or public.get("audit_contract_sha256") != R2_AUDIT_CONTRACT_SHA256
        or public.get("protocol_sha256") != R2_SHA256[R2_PROTOCOL]
        or public.get("private_receipt_sha256") != R2_PRIVATE_COMMITMENT
    ):
        _reject()
    for key in (
        "eligible_json_inventory_commitment_sha256",
        "endpoint_inventory_commitment_sha256",
    ):
        if not _is_sha256(public.get(key)):
            _reject()
    return public


def _integer_attribute(element: ET.Element, name: str) -> int:
    value = element.get(name)
    if value is None or not value.isascii() or not value.isdigit():
        _reject()
    return int(value)


def _score_junit(
    raw: bytes, *, total: int, classname: str, names: tuple[str, ...]
) -> int:
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
        key: _integer_attribute(suite, key)
        for key in ("tests", "errors", "failures", "skipped")
    }
    if counts != {"tests": total, "errors": 0, "failures": 0, "skipped": 0}:
        _reject()
    cases = list(suite)
    if (
        len(cases) != total
        or any(case.tag != "testcase" or len(case) != 0 for case in cases)
        or [case.get("name") for case in cases] != list(names)
        or any(case.get("classname") != classname for case in cases)
    ):
        _reject()
    return total


def _validate_failure_audit(raw: bytes) -> None:
    failure = _load_json(raw)
    expected_keys = {
        "schema",
        "date",
        "tree",
        "tag",
        "parent",
        "question",
        "prior_question",
        "status",
        "protocol_sha256",
        "prediction_receipt_sha256",
        "judgement_receipt_sha256",
        "measurement",
        "frozen_scorers",
        "root_cause",
        "lakatotree_preserved_result",
        "preservation_and_repair_policy",
        "scope_boundaries",
    }
    if set(failure) != expected_keys:
        _reject()
    root = failure.get("root_cause")
    measurement = failure.get("measurement")
    preserved = failure.get("lakatotree_preserved_result")
    policy = failure.get("preservation_and_repair_policy")
    if not all(type(value) is dict for value in (root, measurement, preserved, policy)):
        _reject()
    if (
        failure.get("schema")
        != "bpc.tab_bolt.existing_strict_provenance_candidate_coverage_repair_r2_scorer_failure.v1"
        or failure.get("date") != "2026-07-14"
        or failure.get("tree") != TREE
        or failure.get("tag") != PARENT_NODE
        or failure.get("question") != R2_QUESTION
        or failure.get("prior_question") != PRIOR_QUESTION
        or failure.get("status")
        != "FROZEN_R2_PRIMARY_AND_RESOLUTION_SCORER_FALSE_REJECTION_PRESERVED"
        or failure.get("protocol_sha256") != R2_SHA256[R2_PROTOCOL]
        or failure.get("prediction_receipt_sha256") != R2_PREDICTION_RECEIPT
        or failure.get("judgement_receipt_sha256") != R2_JUDGEMENT_RECEIPT
        or measurement.get("pytest_cases") != 16
        or measurement.get("pytest_passed") != 16
        or measurement.get("pytest_run_count") != 1
        or measurement.get("public_outcome") != OUTCOME_INCOMPLETE
        or measurement.get("public_terminal_resolution_score") != 0
        or root.get("classification")
        != "PUBLIC_PRIVACY_SCORER_REQUIRED_KEY_SUBSTRING_FALSE_POSITIVE"
        or root.get("required_allowed_public_key") != "symlink_target_dereference_used"
        or root.get("overbroad_forbidden_raw_substring") != "link_target"
        or root.get("input_or_measurement_failure") is not False
        or root.get("private_receipt_opened_or_independently_hashed_during_diagnosis")
        is not False
        or preserved.get("metric_value") != 0
        or preserved.get("verdict") != "equivalent"
        or preserved.get("receipt_chain_verified") is not True
        or policy.get("same_node_scorer_mutation_allowed") is not False
        or policy.get("same_measurement_retry_allowed") is not False
        or policy.get("repair_may_change_terminal_resolution_zero") is not False
        or policy.get("repair_may_close_original_coverage_questions") is not False
    ):
        _reject()


def score_preserved_r2_chain() -> int:
    """Readjudicate immutable public R2 artifacts; never import either R2 judge."""

    for path, expected in R2_SHA256.items():
        raw = _stable_regular_bytes(
            path,
            required_mode=0o444 if path in {R2_PROTOCOL, R2_PUBLIC} else None,
        )
        if hashlib.sha256(raw).hexdigest() != expected:
            _reject()
    protocol_raw = _stable_regular_bytes(R2_PROTOCOL, required_mode=0o444)
    if _canonical_json_bytes(_load_json(protocol_raw)) != protocol_raw:
        _reject()
    _validate_public_result(_stable_regular_bytes(R2_PUBLIC, required_mode=0o444))
    _validate_failure_audit(_stable_regular_bytes(R2_FAILURE))
    return _score_junit(
        _stable_regular_bytes(R2_JUNIT),
        total=EXPECTED_ORIGINAL,
        classname=R2_CLASSNAME,
        names=R2_TEST_NAMES,
    )


def terminal_resolution_score() -> int:
    """Return the preserved scientific resolution score after public validation."""

    _validate_public_result(_stable_regular_bytes(R2_PUBLIC, required_mode=0o444))
    return 0


def _asset(path: Path, sha256: str) -> dict[str, str]:
    return {"path": str(path), "sha256": sha256}


def _validate_r3_protocol() -> None:
    raw = _stable_regular_bytes(R3_PROTOCOL, required_mode=0o444)
    protocol = _load_json(raw)
    if _canonical_json_bytes(protocol) != raw:
        _reject()
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
    if exact.get("known_existing_result_disclosure") != {
        "result_known_before_r3": True,
        "producer_or_workspace_measurement_rerun": False,
        "r2_protocol_sha256": R2_SHA256[R2_PROTOCOL],
        "r2_public_result_sha256": R2_SHA256[R2_PUBLIC],
        "r2_junit_sha256": R2_SHA256[R2_JUNIT],
        "r2_private_receipt_sha256": R2_PRIVATE_COMMITMENT,
        "r2_primary_local_metric": 0,
        "r2_resolution_local_metric": 0,
        "r2_server_regenerated_metric": 0,
    }:
        _reject()
    if exact.get("preserved_scientific_result") != {
        "outcome": OUTCOME_INCOMPLETE,
        "strict_provenance_established": False,
        "eligible_json_files_seen": 1580,
        "eligible_json_files_read": 1580,
        "candidate_json_documents": 0,
        "complete_candidates_found": 0,
        "incomplete_external_symlink_aliases_per_pass": 4,
        "terminal_resolution_score": 0,
        "repair_question_status": "OPEN",
        "prior_json_scope_question_status": "OPEN",
    }:
        _reject()
    repair = exact.get("repair_diff")
    if type(repair) is not dict or repair != {
        "frozen_r2_primary_sha256": R2_SHA256[R2_PRIMARY],
        "frozen_r2_resolution_sha256": R2_SHA256[R2_RESOLUTION],
        "repaired_r3_primary_sha256": _sha256(R3_PRIMARY),
        "required_allowed_public_key": "symlink_target_dereference_used",
        "removed_overbroad_raw_substring": "link_target",
        "structured_exact_key_gate_retained": True,
        "canonical_public_bytes_gate_retained": True,
        "unexpected_hash_key_gate_retained": True,
        "sensitive_value_token_gate_retained": True,
        "producer_or_measurement_artifacts_overwritten": False,
    }:
        _reject()
    if exact.get("r2_failure_lineage") != {
        "failure_audit_sha256": R2_SHA256[R2_FAILURE],
        "r2_node_tag": PARENT_NODE,
        "r2_question": R2_QUESTION,
        "prior_question": PRIOR_QUESTION,
        "r2_protocol_sha256": R2_SHA256[R2_PROTOCOL],
        "r2_prediction_receipt_sha256": R2_PREDICTION_RECEIPT,
        "r2_judgement_receipt_sha256": R2_JUDGEMENT_RECEIPT,
        "r2_primary_scorer_sha256": R2_SHA256[R2_PRIMARY],
        "r2_resolution_scorer_sha256": R2_SHA256[R2_RESOLUTION],
        "r2_junit_sha256": R2_SHA256[R2_JUNIT],
        "r2_public_result_sha256": R2_SHA256[R2_PUBLIC],
        "local_primary_metric": 0,
        "local_resolution_metric": 0,
        "server_primary_metric": 0,
        "classification": "PUBLIC_PRIVACY_SCORER_REQUIRED_KEY_SUBSTRING_FALSE_POSITIVE",
        "input_or_measurement_failure": False,
        "r2_measurement_preserved": True,
        "r2_false_rejection_preserved": True,
    }:
        _reject()
    if exact.get("confirmatory_replay_contract") != {
        "preserved_primary_conformance_count": 16,
        "preserved_terminal_resolution_score": 0,
        "result_known_before_r3": True,
        "planned_after_primary_repair": True,
        "lakato_novel_claimed": False,
        "new_data_generated": False,
        "independent_new_data_or_replication": False,
    }:
        _reject()
    if exact.get("scope_boundaries") != {
        "scorer_repair_only": True,
        "workspace_measurement_rerun": False,
        "private_receipt_opened_by_scorers": False,
        "strict_provenance_established": False,
        "json_scope_terminal": False,
        "candidate_absence_in_full_logical_scope_established": False,
        "original_coverage_questions_closed_by_r3": False,
        "already_public_result_reclassified_as_novel": False,
        "production_ready_or_changed": False,
    }:
        _reject()
    if exact.get("prediction") != {
        "metric": PRIMARY_METRIC,
        "baseline": 0,
        "direction": "higher",
        "noise_band": 0,
        "predicted_value": 6,
        "credence": 0.98,
        "closes_question_on_success": QUESTION,
    }:
        _reject()
    expected_assets: dict[str, Any] = {
        "r2_audit_producer": _asset(R2_PRODUCER, R2_SHA256[R2_PRODUCER]),
        "r2_conformance_test": _asset(R2_TEST, R2_SHA256[R2_TEST]),
        "r2_primary_scorer": _asset(R2_PRIMARY, R2_SHA256[R2_PRIMARY]),
        "r2_resolution_scorer": _asset(R2_RESOLUTION, R2_SHA256[R2_RESOLUTION]),
        "r2_protocol": _asset(R2_PROTOCOL, R2_SHA256[R2_PROTOCOL]),
        "r2_junit": _asset(R2_JUNIT, R2_SHA256[R2_JUNIT]),
        "r2_public_result": _asset(R2_PUBLIC, R2_SHA256[R2_PUBLIC]),
        "r2_scorer_failure_audit": _asset(R2_FAILURE, R2_SHA256[R2_FAILURE]),
        "r3_repair_test": _asset(R3_TEST, _sha256(R3_TEST)),
        "r3_primary_repair_scorer": _asset(R3_PRIMARY, _sha256(R3_PRIMARY)),
        "r3_confirmatory_replay_scorer": _asset(
            R3_CONFIRMATORY, _sha256(R3_CONFIRMATORY)
        ),
        "r3_protocol": {"path": str(R3_PROTOCOL)},
        "r3_junit": {"path": str(R3_JUNIT), "preflight": "ABSENT"},
        "r2_private_receipt_commitment": {
            "sha256": R2_PRIVATE_COMMITMENT,
            "scorer_read_forbidden": True,
        },
    }
    if exact.get("frozen_assets") != expected_assets:
        _reject()
    if exact.get("test_inventory") != {
        "classname": R3_CLASSNAME,
        "total": 6,
        "names": list(R3_TEST_NAMES),
        "actual_preserved_chain_cases": 1,
        "synthetic_repair_and_privacy_cases": 5,
    }:
        _reject()
    if exact.get("execution") != {
        "cwd": EXECUTION_CWD,
        "python": EXECUTION_PYTHON,
        "command": EXECUTION_COMMAND,
        "protocol_path": str(R3_PROTOCOL),
        "r3_junit_path": str(R3_JUNIT),
        "primary_scorer_path": str(R3_PRIMARY),
        "confirmatory_replay_scorer_path": str(R3_CONFIRMATORY),
        "measurement_policy": MEASUREMENT_POLICY,
        "confirmatory_policy": CONFIRMATORY_POLICY,
        "failure_policy": FAILURE_POLICY,
    }:
        _reject()
    if exact.get("static_preflight_details") != {
        "r2_measurement_artifacts_preserved": True,
        "r2_failure_evidence_preserved": True,
        "primary_confirmatory_cross_hashes_checked": True,
        "exact_six_test_definitions_checked_statically": True,
        "ruff_check_passed": True,
        "ruff_format_check_passed": True,
        "independent_static_contract_audit_issue_count": 0,
        "r3_junit_absent": True,
        "r3_test_executed": False,
        "r3_test_collected": False,
        "r3_test_imported": False,
        "r3_primary_imported_or_executed": False,
        "r3_confirmatory_imported_or_executed": False,
        "private_receipt_opened_for_r3_static_preflight": False,
        "producer_or_workspace_measurement_rerun": False,
    }:
        _reject()


def score() -> int:
    """Return six only when repair evidence and the preserved chain both pass."""

    try:
        _validate_r3_protocol()
        if score_preserved_r2_chain() != EXPECTED_ORIGINAL:
            _reject()
        if terminal_resolution_score() != 0:
            _reject()
        return _score_junit(
            _stable_regular_bytes(R3_JUNIT),
            total=EXPECTED_REPAIR,
            classname=R3_CLASSNAME,
            names=R3_TEST_NAMES,
        )
    except Exception:
        return 0


def main() -> int:
    metric = 0
    if len(sys.argv) == 2 and _same_fixed_path(sys.argv[1], R3_JUNIT):
        metric = score()
    print(f"metric={metric}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
