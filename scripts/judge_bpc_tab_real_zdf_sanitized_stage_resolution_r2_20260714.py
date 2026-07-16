#!/usr/bin/env python3
"""Independently score one sanitized R2 decoder-stage resolution.

The score is one only for an all-green frozen JUnit plus a fully verified
private-to-public receipt chain resolving to ``FRAME_OPEN_FAILURE`` after the
metadata and import stages.  A structurally valid different stage scores zero.
Invalid custody, commitments, schemas, modes, or privacy boundaries fail closed.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Iterable
import xml.etree.ElementTree as ET


BPC_ROOT = Path("/data/kjra/PROJECT/3DLAB/BPC_ICP_SPEC")
LAKATO_ROOT = Path("/data/kjra/PROJECT/PI/lakatotree")
PRIVATE_ROOT = Path("/data/kjra/PROJECT/3DLAB/.private_bpc_p1c")

CUSTODY_PROBE = BPC_ROOT / "scripts/tab_bolt_real_zdf_decoder_capability_probe.py"
DIAGNOSTIC = BPC_ROOT / "scripts/tab_bolt_real_zdf_decoder_stage_diagnostic.py"
TEST_MODULE = BPC_ROOT / "tests/test_tab_bolt_real_zdf_decoder_stage_diagnostic.py"
PRIMARY_SCORER = (
    LAKATO_ROOT
    / "scripts/judge_bpc_tab_real_zdf_decoder_stage_diagnostic_r2_20260714.py"
)
NOVEL_SCORER = Path(__file__).absolute()
PROTOCOL = (
    BPC_ROOT / "evidence/bpc_tab_bolt_development_zdf_decoder_diagnostic_"
    "r2_20260714_protocol.json"
)
PUBLIC_RESULT = (
    BPC_ROOT / "evidence/bpc_tab_bolt_development_zdf_decoder_diagnostic_"
    "r2_20260714_result.json"
)
FIXED_JUNIT = (
    BPC_ROOT / "evidence/bpc_tab_bolt_development_zdf_decoder_diagnostic_"
    "r2_20260714_conformance.xml"
)
SOURCE_PREREGISTRATION = (
    PRIVATE_ROOT / "bpc_tab_bolt_real_zdf_source_preregistration_20260714.json"
)
PRIVATE_RECEIPT = (
    PRIVATE_ROOT
    / "bpc_tab_bolt_real_zdf_decoder_diagnostic_r2_private_receipt_20260714.json"
)
FIXED_SCRATCH = PRIVATE_ROOT / "scratch_r2"

CUSTODY_PROBE_SHA256 = (
    "d8e32ad87693a06beb91140f1bb54edd3815f3dab438c74869af081cd196a1c9"
)
DIAGNOSTIC_SHA256 = "496e3ed171169b2a19bded533ead7cfaeb9929991c90449db131db36c8f0c0c3"
TEST_MODULE_SHA256 = "cdd93d1fa3e64c0703e183a0206e27bf6a756d8dd84f1b088a8a77fd9d351c68"
SOURCE_PREREGISTRATION_SHA256 = (
    "29e09511d4ab88611f087f204d7f986d7693114cafc72b488d883a2117b83d8e"
)

CLAIM_SCOPE = "SANITIZED_ACTUAL_DEVELOPMENT_ZDF_DECODER_STAGE_DIAGNOSTIC_ONLY"
SOURCE_CLAIM_SCOPE = "ACTUAL_DEVELOPMENT_ZDF_OFFLINE_DECODER_CAPABILITY_ONLY"
SOURCE_SCHEMA = "bpc.tab_bolt.development_zdf_source_preregistration.v1"
PROTOCOL_SCHEMA = (
    "bpc.tab_bolt.development_zdf_decoder_stage_diagnostic_preregistration.v1"
)
PRIVATE_SCHEMA = (
    "bpc.tab_bolt.development_zdf_decoder_stage_diagnostic_private_receipt.v1"
)
PUBLIC_SCHEMA = "bpc.tab_bolt.development_zdf_decoder_stage_diagnostic.v1"
PROTOCOL_STATUS = "PREREGISTERED_R2_DIAGNOSTIC_RESULT_ABSENT"
EXECUTION_BOUNDARY = "SANITIZED_STAGE_CLASSIFICATION_NOT_ROOT_CAUSE"
EXPECTED_TERMINAL = "FRAME_OPEN_FAILURE"
EXPECTED_COMPLETED_STAGES = ["METADATA_VERSION", "IMPORT_ZIVID"]
STAGES = (
    "METADATA_VERSION",
    "IMPORT_ZIVID",
    "FRAME_OPEN",
    "POINT_CLOUD",
    "COPY_XYZ",
    "COPY_SNR",
)
FAILURE_TERMINALS = (
    "PACKAGE_METADATA_FAILURE",
    "ZIVID_IMPORT_FAILURE",
    "FRAME_OPEN_FAILURE",
    "POINT_CLOUD_ACCESS_FAILURE",
    "XYZ_COPY_FAILURE",
    "SNR_COPY_FAILURE",
)
STAGE_BY_TERMINAL = dict(zip(FAILURE_TERMINALS, STAGES, strict=True))
COMPLETED_TERMINAL = "DECODE_SEQUENCE_COMPLETED"
EXPECTED_TOTAL = 11
CLASSNAME = "tests.test_tab_bolt_real_zdf_decoder_stage_diagnostic"
TEST_NAMES = frozenset(
    {
        "test_each_decode_stage_failure_is_exactly_classified_sanitized_and_cleaned[PACKAGE_METADATA_FAILURE]",
        "test_each_decode_stage_failure_is_exactly_classified_sanitized_and_cleaned[ZIVID_IMPORT_FAILURE]",
        "test_each_decode_stage_failure_is_exactly_classified_sanitized_and_cleaned[FRAME_OPEN_FAILURE]",
        "test_each_decode_stage_failure_is_exactly_classified_sanitized_and_cleaned[POINT_CLOUD_ACCESS_FAILURE]",
        "test_each_decode_stage_failure_is_exactly_classified_sanitized_and_cleaned[XYZ_COPY_FAILURE]",
        "test_each_decode_stage_failure_is_exactly_classified_sanitized_and_cleaned[SNR_COPY_FAILURE]",
        "test_decode_sequence_completion_is_closed_sanitized_and_cleaned",
        "test_rejects_source_commitment_mismatch_or_symlink_before_stage_execution",
        "test_source_mutation_during_staged_decode_fails_closed_and_cleans_snapshot",
        "test_existing_private_or_public_diagnostic_is_never_clobbered",
        "test_committed_actual_development_zdf_resolves_to_preregistered_frame_open_failure",
    }
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
EXCEPTION_CLASS_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,127}$")
MAX_SMALL_FILE_BYTES = 8 * 1024 * 1024
MAX_SOURCE_BYTES = 512 * 1024 * 1024

SOURCE_KEYS = frozenset(
    {
        "schema",
        "claim_scope",
        "private_nonce",
        "source_path",
        "source_sha256",
        "source_size_bytes",
        "source_role",
        "expected_image_shape",
        "expected_python_version",
        "expected_zivid_version",
        "expected_numpy_version",
        "forbidden_public_identity_tokens",
    }
)
PRIVATE_KEYS = frozenset(
    {
        "schema",
        "status",
        "claim_scope",
        "execution_boundary",
        "private_receipt_nonce",
        "protocol_sha256",
        "source_preregistration_path",
        "source_preregistration_sha256",
        "source_path",
        "source_sha256",
        "source_size_bytes",
        "source_stat_fingerprint_before",
        "source_stat_fingerprint_after",
        "snapshot_sha256",
        "snapshot_size_bytes",
        "snapshot_stat_fingerprint",
        "diagnostic_terminal",
        "completed_stages",
        "completed_stage_count",
        "decoder_sequence_completed",
        "failure_stage_classified",
        "exception_class",
        "exception_fingerprint_sha256",
        "application_initialization_performed",
        "source_commitment_match",
        "source_fd_stability_verified",
        "source_snapshot_byte_identity_verified",
        "source_snapshot_distinct_inode_verified",
        "scratch_snapshot_removed_before_publication",
        "exception_message_stored",
        "exception_repr_stored",
        "traceback_stored",
        "root_cause_established",
        "organized_xyz_snr_capability_established",
        "production_ready_or_changed",
    }
)
PUBLIC_KEYS = frozenset(
    {
        "schema",
        "status",
        "claim_scope",
        "execution_boundary",
        "protocol_sha256",
        "source_preregistration_sha256",
        "diagnostic_terminal",
        "completed_stages",
        "completed_stage_count",
        "decoder_sequence_completed",
        "failure_stage_classified",
        "exception_class",
        "exception_fingerprint_sha256",
        "application_initialization_performed",
        "source_commitment_match",
        "source_fd_stability_verified",
        "source_snapshot_byte_identity_verified",
        "source_snapshot_distinct_inode_verified",
        "scratch_snapshot_removed_before_publication",
        "private_receipt_sha256",
        "exception_message_stored",
        "exception_repr_stored",
        "traceback_stored",
        "public_identity_or_geometry_payload_present",
        "root_cause_established",
        "organized_xyz_snr_capability_established",
        "actual_strict_layout_provenance_established",
        "datamatrix_coverage_established",
        "physical_accuracy_established",
        "campaign_720_replayed",
        "production_ready_or_changed",
    }
)
FORBIDDEN_PUBLIC_KEYS = frozenset(
    {
        "source_path",
        "source_sha256",
        "source_size_bytes",
        "source_basename",
        "private_nonce",
        "private_receipt_nonce",
        "raw_zdf_sha256",
        "payload_sha256",
        "xyz",
        "snr",
        "exception_message",
        "exception_repr",
        "traceback",
        "lot_id",
        "capture_id",
        "serial_id",
        "view_id",
        "source_preregistration_path",
        "private_receipt_path",
    }
)


class ScoreRejected(RuntimeError):
    """Stable fail-closed scorer error."""


def _reject() -> None:
    raise ScoreRejected("E_P1C_R2_STAGE_RESOLUTION_REJECTED")


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


def _read(path: Path, *, mode: int | None = None) -> bytes:
    try:
        pathname = path.lstat()
    except OSError:
        _reject()
    if (
        stat.S_ISLNK(pathname.st_mode)
        or not stat.S_ISREG(pathname.st_mode)
        or pathname.st_nlink != 1
        or not 0 < pathname.st_size <= MAX_SMALL_FILE_BYTES
        or (mode is not None and stat.S_IMODE(pathname.st_mode) != mode)
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
        result = bytearray()
        while len(result) < opened.st_size:
            block = os.read(
                descriptor,
                min(1024 * 1024, opened.st_size - len(result)),
            )
            if not block:
                _reject()
            result.extend(block)
        if os.read(descriptor, 1):
            _reject()
        if _fingerprint(os.fstat(descriptor)) != _fingerprint(opened):
            _reject()
        return bytes(result)
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


def _exact(value: Any, keys: frozenset[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        _reject()
    return value


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def _walk_keys(value: Any) -> Iterable[str]:
    if type(value) is dict:
        for key, nested in value.items():
            yield key
            yield from _walk_keys(nested)
    elif type(value) is list:
        for nested in value:
            yield from _walk_keys(nested)


def _walk_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif type(value) is dict:
        for nested in value.values():
            yield from _walk_strings(nested)
    elif type(value) is list:
        for nested in value:
            yield from _walk_strings(nested)


def _validate_junit() -> bool:
    raw = _read(FIXED_JUNIT)
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
    counts: dict[str, int] = {}
    for name in ("tests", "errors", "failures", "skipped"):
        raw_count = suite.get(name)
        if raw_count is None or not raw_count.isascii() or not raw_count.isdigit():
            _reject()
        counts[name] = int(raw_count)
    if counts["tests"] != EXPECTED_TOTAL:
        _reject()
    cases = list(suite)
    if len(cases) != EXPECTED_TOTAL or any(case.tag != "testcase" for case in cases):
        _reject()
    names = [case.get("name") for case in cases]
    if (
        len(set(names)) != EXPECTED_TOTAL
        or set(names) != TEST_NAMES
        or any(case.get("classname") != CLASSNAME for case in cases)
    ):
        _reject()
    observed = {"errors": 0, "failures": 0, "skipped": 0}
    tag_to_count = {"error": "errors", "failure": "failures", "skipped": "skipped"}
    for case in cases:
        children = list(case)
        if len(children) > 1:
            _reject()
        if children:
            count_name = tag_to_count.get(children[0].tag)
            if count_name is None:
                _reject()
            observed[count_name] += 1
    if any(observed[name] != counts[name] for name in observed):
        _reject()
    return counts == {"tests": EXPECTED_TOTAL, "errors": 0, "failures": 0, "skipped": 0}


def _open_source(path: Path) -> int:
    if not path.is_absolute() or not hasattr(os, "O_NOFOLLOW"):
        _reject()
    parts = path.parts
    if len(parts) < 2 or parts[0] != "/":
        _reject()
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory = os.open("/", directory_flags)
    try:
        for component in parts[1:-1]:
            if component in {"", ".", ".."}:
                _reject()
            next_directory = os.open(
                component,
                directory_flags | os.O_NOFOLLOW,
                dir_fd=directory,
            )
            if not stat.S_ISDIR(os.fstat(next_directory).st_mode):
                os.close(next_directory)
                _reject()
            os.close(directory)
            directory = next_directory
        final_name = parts[-1]
        if final_name in {"", ".", ".."}:
            _reject()
        pathname = os.stat(final_name, dir_fd=directory, follow_symlinks=False)
        if (
            stat.S_ISLNK(pathname.st_mode)
            or not stat.S_ISREG(pathname.st_mode)
            or pathname.st_nlink != 1
        ):
            _reject()
        descriptor = os.open(
            final_name,
            os.O_RDONLY | os.O_NOFOLLOW,
            dir_fd=directory,
        )
        if _fingerprint(os.fstat(descriptor)) != _fingerprint(pathname):
            os.close(descriptor)
            _reject()
        return descriptor
    finally:
        os.close(directory)


def _hash_source(path: Path, size: int) -> tuple[str, tuple[int, ...]]:
    if type(size) is not int or not 0 < size <= MAX_SOURCE_BYTES:
        _reject()
    descriptor = _open_source(path)
    try:
        opened = os.fstat(descriptor)
        if opened.st_size != size:
            _reject()
        digest = hashlib.sha256()
        observed = 0
        while observed < size:
            block = os.read(descriptor, min(1024 * 1024, size - observed))
            if not block:
                _reject()
            digest.update(block)
            observed += len(block)
        if os.read(descriptor, 1):
            _reject()
        if _fingerprint(os.fstat(descriptor)) != _fingerprint(opened):
            _reject()
        fingerprint = _fingerprint(opened)
    finally:
        os.close(descriptor)
    reopened = _open_source(path)
    try:
        if _fingerprint(os.fstat(reopened)) != fingerprint:
            _reject()
    finally:
        os.close(reopened)
    return digest.hexdigest(), fingerprint


def _validate_directories() -> None:
    try:
        private_info = PRIVATE_ROOT.lstat()
        scratch_info = FIXED_SCRATCH.lstat()
    except OSError:
        _reject()
    if (
        stat.S_ISLNK(private_info.st_mode)
        or not stat.S_ISDIR(private_info.st_mode)
        or stat.S_IMODE(private_info.st_mode) != 0o700
        or stat.S_ISLNK(scratch_info.st_mode)
        or not stat.S_ISDIR(scratch_info.st_mode)
        or stat.S_IMODE(scratch_info.st_mode) != 0o700
    ):
        _reject()
    try:
        with os.scandir(FIXED_SCRATCH) as entries:
            if next(entries, None) is not None:
                _reject()
    except OSError:
        _reject()


def _validate_source(value: dict[str, Any]) -> dict[str, Any]:
    source = _exact(value, SOURCE_KEYS)
    if (
        source.get("schema") != SOURCE_SCHEMA
        or source.get("claim_scope") != SOURCE_CLAIM_SCOPE
        or source.get("source_role") != "POINT_GEOMETRY"
        or source.get("expected_image_shape") != [2048, 2448]
        or source.get("expected_zivid_version") != "2.17.2"
        or not _is_sha(source.get("private_nonce"))
        or not _is_sha(source.get("source_sha256"))
        or type(source.get("source_size_bytes")) is not int
        or not 0 < source["source_size_bytes"] <= MAX_SOURCE_BYTES
    ):
        _reject()
    path_value = source.get("source_path")
    if not isinstance(path_value, str):
        _reject()
    path = Path(path_value)
    if not path.is_absolute() or str(path) != path_value:
        _reject()
    tokens = source.get("forbidden_public_identity_tokens")
    if (
        type(tokens) is not list
        or not tokens
        or len(set(tokens)) != len(tokens)
        or any(
            not isinstance(token, str) or len(token.encode()) < 8 for token in tokens
        )
    ):
        _reject()
    normalized = {token.casefold() for token in tokens}
    if not {path.name.casefold(), path.parent.name.casefold()}.issubset(normalized):
        _reject()
    return source


def _needles(
    source: dict[str, Any], private: dict[str, Any] | None = None
) -> list[bytes]:
    path = Path(source["source_path"])
    values = [
        str(path),
        path.name,
        path.parent.name,
        source["source_sha256"],
        source["private_nonce"],
        str(SOURCE_PREREGISTRATION),
        str(PRIVATE_RECEIPT),
        *source["forbidden_public_identity_tokens"],
    ]
    if private is not None:
        values.append(private["private_receipt_nonce"])
    return [value.encode().lower() for value in values]


def _privacy(
    raw: bytes,
    value: dict[str, Any],
    source: dict[str, Any],
    private: dict[str, Any] | None = None,
) -> None:
    if set(_walk_keys(value)) & FORBIDDEN_PUBLIC_KEYS:
        _reject()
    lowered = raw.lower()
    if any(
        len(needle) >= 8 and needle in lowered for needle in _needles(source, private)
    ):
        _reject()


def _validate_protocol(
    raw: bytes, value: dict[str, Any], source: dict[str, Any]
) -> None:
    contract = value.get("diagnostic_contract")
    prediction = value.get("prediction")
    inventory = value.get("test_inventory")
    if (
        value.get("schema") != PROTOCOL_SCHEMA
        or value.get("status") != PROTOCOL_STATUS
        or value.get("claim_scope") != CLAIM_SCOPE
        or value.get("production_change") is not False
        or type(contract) is not dict
        or contract.get("predicted_terminal") != EXPECTED_TERMINAL
        or contract.get("expected_completed_stages") != EXPECTED_COMPLETED_STAGES
        or contract.get("expected_completed_stage_count") != 2
        or contract.get("application_initialization_performed") is not False
        or contract.get("root_cause_established") is not False
        or contract.get("organized_xyz_snr_capability_established") is not False
        or contract.get("exception_message_persistence_allowed") is not False
        or contract.get("exception_repr_persistence_allowed") is not False
        or contract.get("traceback_persistence_allowed") is not False
        or contract.get("source_identity_publication_allowed") is not False
        or contract.get("geometry_payload_publication_allowed") is not False
        or type(prediction) is not dict
        or prediction.get("metric")
        != "development_zdf_decoder_diagnostic_r2_conformance_gate_count"
        or prediction.get("predicted_value") != EXPECTED_TOTAL
        or prediction.get("novel_metric")
        != "actual_development_zdf_sanitized_failure_stage_resolution_count"
        or prediction.get("predicted_novel_value") != 1
        or prediction.get("novel_threshold") != 1
        or type(inventory) is not dict
        or inventory.get("classname") != CLASSNAME
        or inventory.get("total") != EXPECTED_TOTAL
        or set(inventory.get("names", [])) != TEST_NAMES
    ):
        _reject()
    strings = set(_walk_strings(value))
    hashes = {
        SOURCE_PREREGISTRATION_SHA256,
        CUSTODY_PROBE_SHA256,
        DIAGNOSTIC_SHA256,
        TEST_MODULE_SHA256,
        hashlib.sha256(_read(PRIMARY_SCORER)).hexdigest(),
        hashlib.sha256(_read(NOVEL_SCORER)).hexdigest(),
    }
    if not hashes.issubset(strings):
        _reject()
    _privacy(raw, value, source)


def _stage_tuple(
    value: dict[str, Any],
) -> tuple[str, tuple[str, ...], str | None, str | None]:
    terminal = value.get("diagnostic_terminal")
    completed = value.get("completed_stages")
    exception_class = value.get("exception_class")
    exception_fingerprint = value.get("exception_fingerprint_sha256")
    if type(completed) is not list or any(
        not isinstance(item, str) for item in completed
    ):
        _reject()
    if terminal == COMPLETED_TERMINAL:
        if (
            completed != list(STAGES)
            or value.get("completed_stage_count") != len(STAGES)
            or value.get("decoder_sequence_completed") is not True
            or value.get("failure_stage_classified") is not False
            or exception_class is not None
            or exception_fingerprint is not None
        ):
            _reject()
    elif terminal in STAGE_BY_TERMINAL:
        failed_stage = STAGE_BY_TERMINAL[terminal]
        expected_completed = list(STAGES[: STAGES.index(failed_stage)])
        if (
            completed != expected_completed
            or value.get("completed_stage_count") != len(expected_completed)
            or value.get("decoder_sequence_completed") is not False
            or value.get("failure_stage_classified") is not True
            or not isinstance(exception_class, str)
            or EXCEPTION_CLASS_RE.fullmatch(exception_class) is None
        ):
            _reject()
        expected_fingerprint = hashlib.sha256(
            f"{terminal}:{exception_class}:EXCEPTION_MESSAGE_REDACTED".encode()
        ).hexdigest()
        if exception_fingerprint != expected_fingerprint:
            _reject()
    else:
        _reject()
    return terminal, tuple(completed), exception_class, exception_fingerprint


def _int_list(value: Any) -> list[int]:
    if (
        type(value) is not list
        or len(value) != 7
        or any(type(item) is not int for item in value)
    ):
        _reject()
    return value


def _validate_private(
    value: dict[str, Any],
    *,
    source: dict[str, Any],
    protocol_sha: str,
    source_fingerprint: tuple[int, ...],
) -> tuple[dict[str, Any], tuple[str, tuple[str, ...], str | None, str | None]]:
    private = _exact(value, PRIVATE_KEYS)
    stage = _stage_tuple(private)
    false_claims = (
        "application_initialization_performed",
        "exception_message_stored",
        "exception_repr_stored",
        "traceback_stored",
        "root_cause_established",
        "organized_xyz_snr_capability_established",
        "production_ready_or_changed",
    )
    true_gates = (
        "source_commitment_match",
        "source_fd_stability_verified",
        "source_snapshot_byte_identity_verified",
        "source_snapshot_distinct_inode_verified",
        "scratch_snapshot_removed_before_publication",
    )
    if (
        private.get("schema") != PRIVATE_SCHEMA
        or private.get("status") != "PASS"
        or private.get("claim_scope") != CLAIM_SCOPE
        or private.get("execution_boundary") != EXECUTION_BOUNDARY
        or not _is_sha(private.get("private_receipt_nonce"))
        or private["private_receipt_nonce"] == source["private_nonce"]
        or private.get("protocol_sha256") != protocol_sha
        or private.get("source_preregistration_path") != str(SOURCE_PREREGISTRATION)
        or private.get("source_preregistration_sha256") != SOURCE_PREREGISTRATION_SHA256
        or private.get("source_path") != source["source_path"]
        or private.get("source_sha256") != source["source_sha256"]
        or private.get("source_size_bytes") != source["source_size_bytes"]
        or private.get("snapshot_sha256") != source["source_sha256"]
        or private.get("snapshot_size_bytes") != source["source_size_bytes"]
        or any(private.get(name) is not False for name in false_claims)
        or any(private.get(name) is not True for name in true_gates)
    ):
        _reject()
    before = _int_list(private.get("source_stat_fingerprint_before"))
    after = _int_list(private.get("source_stat_fingerprint_after"))
    snapshot = _int_list(private.get("snapshot_stat_fingerprint"))
    if (
        before != after
        or tuple(before) != source_fingerprint
        or snapshot[2] != 0o600
        or snapshot[3] != 1
        or snapshot[4] != source["source_size_bytes"]
        or snapshot[:2] == before[:2]
    ):
        _reject()
    return private, stage


def _validate_public(
    value: dict[str, Any],
    *,
    protocol_sha: str,
    private_sha: str,
    private_stage: tuple[str, tuple[str, ...], str | None, str | None],
) -> tuple[str, tuple[str, ...], str | None, str | None]:
    public = _exact(value, PUBLIC_KEYS)
    stage = _stage_tuple(public)
    false_claims = (
        "application_initialization_performed",
        "exception_message_stored",
        "exception_repr_stored",
        "traceback_stored",
        "public_identity_or_geometry_payload_present",
        "root_cause_established",
        "organized_xyz_snr_capability_established",
        "actual_strict_layout_provenance_established",
        "datamatrix_coverage_established",
        "physical_accuracy_established",
        "campaign_720_replayed",
        "production_ready_or_changed",
    )
    true_gates = (
        "source_commitment_match",
        "source_fd_stability_verified",
        "source_snapshot_byte_identity_verified",
        "source_snapshot_distinct_inode_verified",
        "scratch_snapshot_removed_before_publication",
    )
    if (
        public.get("schema") != PUBLIC_SCHEMA
        or public.get("status") != "PASS"
        or public.get("claim_scope") != CLAIM_SCOPE
        or public.get("execution_boundary") != EXECUTION_BOUNDARY
        or public.get("protocol_sha256") != protocol_sha
        or public.get("source_preregistration_sha256") != SOURCE_PREREGISTRATION_SHA256
        or public.get("private_receipt_sha256") != private_sha
        or stage != private_stage
        or any(public.get(name) is not False for name in false_claims)
        or any(public.get(name) is not True for name in true_gates)
    ):
        _reject()
    return stage


def _verify_sources() -> None:
    for path, expected, mode in (
        (CUSTODY_PROBE, CUSTODY_PROBE_SHA256, None),
        (DIAGNOSTIC, DIAGNOSTIC_SHA256, None),
        (TEST_MODULE, TEST_MODULE_SHA256, None),
        (SOURCE_PREREGISTRATION, SOURCE_PREREGISTRATION_SHA256, 0o600),
    ):
        if hashlib.sha256(_read(path, mode=mode)).hexdigest() != expected:
            _reject()


def _score() -> int:
    all_green = _validate_junit()
    _verify_sources()
    _validate_directories()

    source_raw = _read(SOURCE_PREREGISTRATION, mode=0o600)
    source = _validate_source(_load_json(source_raw))
    source_sha, source_fingerprint = _hash_source(
        Path(source["source_path"]), source["source_size_bytes"]
    )
    if source_sha != source["source_sha256"]:
        _reject()

    protocol_raw = _read(PROTOCOL)
    protocol = _load_json(protocol_raw)
    _validate_protocol(protocol_raw, protocol, source)
    protocol_sha = hashlib.sha256(protocol_raw).hexdigest()

    private_raw = _read(PRIVATE_RECEIPT, mode=0o600)
    private_sha = hashlib.sha256(private_raw).hexdigest()
    private, private_stage = _validate_private(
        _load_json(private_raw),
        source=source,
        protocol_sha=protocol_sha,
        source_fingerprint=source_fingerprint,
    )

    public_raw = _read(PUBLIC_RESULT, mode=0o444)
    public = _load_json(public_raw)
    stage = _validate_public(
        public,
        protocol_sha=protocol_sha,
        private_sha=private_sha,
        private_stage=private_stage,
    )
    _privacy(public_raw, public, source, private)

    resolved = (
        stage[0] == EXPECTED_TERMINAL and list(stage[1]) == EXPECTED_COMPLETED_STAGES
    )
    return int(all_green and resolved)


def main() -> int:
    try:
        if len(sys.argv) != 2 or not _same_fixed_path(sys.argv[1], FIXED_JUNIT):
            _reject()
        metric = _score()
    except Exception:
        sys.stderr.write("E_P1C_R2_STAGE_RESOLUTION_REJECTED\n")
        return 2
    print(f"metric={metric}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
