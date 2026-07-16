#!/usr/bin/env python3
"""Score the two required channels in the frozen development-ZDF receipt chain.

This scorer deliberately does not invoke Zivid.  It rehashes the committed raw
source and audits the preregistration -> protocol -> private receipt ->
sanitized public-result chain.  Payload digests are receipt commitments, not an
independent decoder replay, and both public and private evidence must say so.
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


BPC_ROOT = Path("/data/kjra/PROJECT/3DLAB/BPC_ICP_SPEC")
LAKATO_ROOT = Path("/data/kjra/PROJECT/PI/lakatotree")
PRIVATE_ROOT = Path("/data/kjra/PROJECT/3DLAB/.private_bpc_p1c")

PROBE = BPC_ROOT / "scripts/tab_bolt_real_zdf_decoder_capability_probe.py"
TEST_MODULE = BPC_ROOT / "tests/test_tab_bolt_real_zdf_decoder_capability_probe.py"
PRIMARY_SCORER = (
    LAKATO_ROOT / "scripts/judge_bpc_tab_real_zdf_decoder_capability_20260714.py"
)
NOVEL_SCORER = (
    LAKATO_ROOT
    / "scripts/judge_bpc_tab_real_zdf_required_channel_rejections_20260714.py"
)
PROTOCOL = (
    BPC_ROOT / "evidence/"
    "bpc_tab_bolt_development_zdf_offline_decoder_capability_"
    "protocol_20260714.json"
)
PUBLIC_RESULT = (
    BPC_ROOT / "evidence/"
    "bpc_tab_bolt_development_zdf_offline_decoder_capability_"
    "result_20260714.json"
)
SOURCE_PREREGISTRATION = (
    PRIVATE_ROOT / "bpc_tab_bolt_real_zdf_source_preregistration_20260714.json"
)
PRIVATE_RECEIPT = (
    PRIVATE_ROOT
    / "bpc_tab_bolt_real_zdf_decoder_capability_private_receipt_20260714.json"
)
FIXED_SCRATCH = PRIVATE_ROOT / "scratch"

PROBE_SHA256 = "d8e32ad87693a06beb91140f1bb54edd3815f3dab438c74869af081cd196a1c9"
TEST_MODULE_SHA256 = "2388b793c32c5b79d5e025a8cc9fa605dc30f02d9c049c65b39df0d1b5dbb5e2"

CLAIM_SCOPE = "ACTUAL_DEVELOPMENT_ZDF_OFFLINE_DECODER_CAPABILITY_ONLY"
SOURCE_SCHEMA = "bpc.tab_bolt.development_zdf_source_preregistration.v1"
PROTOCOL_SCHEMA = (
    "bpc.tab_bolt.development_zdf_offline_decoder_capability_preregistration.v1"
)
PRIVATE_RECEIPT_SCHEMA = "bpc.tab_bolt.development_zdf_decoder_private_receipt.v1"
PUBLIC_RESULT_SCHEMA = "bpc.tab_bolt.development_zdf_decoder_result.v1"

EXPECTED_HEIGHT = 2048
EXPECTED_WIDTH = 2448
EXPECTED_RUNTIME = {
    "python": "3.10.20",
    "zivid": "2.17.2",
    "numpy": "2.2.6",
}
EXPECTED_CHANNELS = ("xyz", "snr")
EXPECTED_OPERATIONS = (
    "zivid.Frame",
    "frame.point_cloud",
    "copy_data:xyz",
    "copy_data:snr",
)
EXPECTED_SOURCE_ROLE = "POINT_GEOMETRY"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
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
PRIVATE_RECEIPT_KEYS = frozenset(
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
        "source_role",
        "source_stat_fingerprint_before",
        "source_stat_fingerprint_after",
        "source_fd_stability_verified",
        "snapshot_sha256",
        "snapshot_size_bytes",
        "snapshot_stat_fingerprint",
        "source_snapshot_byte_identity_verified",
        "source_snapshot_distinct_inode_verified",
        "scratch_snapshot_removed_before_publication",
        "requested_channels",
        "application_call_trace",
        "runtime_versions",
        "organized_image_shape",
        "xyz",
        "snr",
        "public_identity_or_geometry_payload_present",
        "independent_decoder_replay_performed",
        "semantic_raw_to_array_fidelity_independently_established",
        "actual_strict_layout_provenance_established",
        "complete_23_view_cycle_evaluated",
        "datamatrix_coverage_established",
        "physical_accuracy_established",
        "campaign_720_replayed",
        "production_ready_or_changed",
    }
)
PUBLIC_RESULT_KEYS = frozenset(
    {
        "schema",
        "status",
        "claim_scope",
        "execution_boundary",
        "protocol_sha256",
        "source_preregistration_sha256",
        "actual_development_zdf_decoded",
        "requested_channels",
        "required_channel_count",
        "application_call_trace",
        "organized_image_shape",
        "array_contract",
        "shared_pixel_grid",
        "source_commitment_match",
        "source_fd_stability_verified",
        "source_snapshot_byte_identity_verified",
        "source_snapshot_distinct_inode_verified",
        "scratch_snapshot_removed_before_publication",
        "runtime_versions",
        "private_receipt_sha256",
        "public_identity_or_geometry_payload_present",
        "independent_decoder_replay_performed",
        "semantic_raw_to_array_fidelity_independently_established",
        "actual_strict_layout_provenance_established",
        "complete_23_view_cycle_evaluated",
        "calibration_or_absolute_measurement_established",
        "datamatrix_coverage_established",
        "raw_to_p1b_campaign_staged",
        "physical_accuracy_established",
        "campaign_720_replayed",
        "anonymity_or_reidentification_resistance_established",
        "postpublication_immutability_established",
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
        "xyz_payload_sha256",
        "snr_payload_sha256",
        "payload_sha256",
        "lot_id",
        "capture_id",
        "serial_id",
        "view_id",
        "private_receipt_path",
        "source_preregistration_path",
    }
)


class ScoreRejected(RuntimeError):
    """Fail closed without echoing private paths, identities, or hashes."""


def _reject() -> None:
    raise ScoreRejected("E_P1C_REQUIRED_CHANNEL_REJECTED")


def _same_fixed_path(supplied: str, expected: Path) -> bool:
    try:
        observed = Path(os.path.abspath(os.fspath(supplied)))
    except (OSError, TypeError, ValueError):
        return False
    return observed == expected


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
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or (opened.st_dev, opened.st_ino, opened.st_size)
            != (pathname.st_dev, pathname.st_ino, pathname.st_size)
            or (
                required_mode is not None
                and stat.S_IMODE(opened.st_mode) != required_mode
            )
        ):
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
        closed_read = os.fstat(descriptor)
        if _fingerprint(closed_read) != _fingerprint(opened):
            _reject()
        return bytes(value)
    finally:
        os.close(descriptor)


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


def _open_absolute_nofollow(path: Path) -> int:
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
            current = os.fstat(next_directory)
            if not stat.S_ISDIR(current.st_mode):
                os.close(next_directory)
                _reject()
            os.close(directory)
            directory = next_directory
        final_name = parts[-1]
        if final_name in {"", ".", ".."}:
            _reject()
        pathname = os.stat(
            final_name,
            dir_fd=directory,
            follow_symlinks=False,
        )
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


def _hash_stable_source(path: Path, expected_size: int) -> tuple[str, tuple[int, ...]]:
    if not 0 < expected_size <= MAX_SOURCE_BYTES:
        _reject()
    descriptor = _open_absolute_nofollow(path)
    try:
        opened = os.fstat(descriptor)
        if opened.st_size != expected_size:
            _reject()
        digest = hashlib.sha256()
        observed_size = 0
        while observed_size < expected_size:
            chunk = os.read(
                descriptor,
                min(1024 * 1024, expected_size - observed_size),
            )
            if not chunk:
                _reject()
            digest.update(chunk)
            observed_size += len(chunk)
        if os.read(descriptor, 1):
            _reject()
        after = os.fstat(descriptor)
        if _fingerprint(after) != _fingerprint(opened):
            _reject()
        fingerprint = _fingerprint(opened)
    finally:
        os.close(descriptor)
    reopened = _open_absolute_nofollow(path)
    try:
        if _fingerprint(os.fstat(reopened)) != fingerprint:
            _reject()
    finally:
        os.close(reopened)
    return digest.hexdigest(), fingerprint


def _reject_constant(_: str) -> None:
    _reject()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, nested in pairs:
        if key in value:
            _reject()
        value[key] = nested
    return value


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


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def _exact_keys(value: Any, expected: frozenset[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != expected:
        _reject()
    return value


def _exact_int_list(value: Any, length: int) -> list[int]:
    if (
        type(value) is not list
        or len(value) != length
        or any(type(item) is not int for item in value)
    ):
        _reject()
    return value


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


def _validate_private_root_and_scratch() -> None:
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


def _validate_source_preregistration(value: dict[str, Any]) -> dict[str, Any]:
    source = _exact_keys(value, SOURCE_KEYS)
    if (
        source.get("schema") != SOURCE_SCHEMA
        or source.get("claim_scope") != CLAIM_SCOPE
        or source.get("source_role") != EXPECTED_SOURCE_ROLE
        or source.get("expected_image_shape") != [EXPECTED_HEIGHT, EXPECTED_WIDTH]
        or source.get("expected_python_version") != EXPECTED_RUNTIME["python"]
        or source.get("expected_zivid_version") != EXPECTED_RUNTIME["zivid"]
        or source.get("expected_numpy_version") != EXPECTED_RUNTIME["numpy"]
        or not _is_sha256(source.get("private_nonce"))
        or not _is_sha256(source.get("source_sha256"))
        or type(source.get("source_size_bytes")) is not int
        or not 0 < source["source_size_bytes"] <= MAX_SOURCE_BYTES
    ):
        _reject()
    source_path = source.get("source_path")
    if not isinstance(source_path, str):
        _reject()
    parsed_path = Path(source_path)
    if not parsed_path.is_absolute() or str(parsed_path) != source_path:
        _reject()
    tokens = source.get("forbidden_public_identity_tokens")
    if (
        type(tokens) is not list
        or not tokens
        or len(set(tokens)) != len(tokens)
        or any(
            not isinstance(token, str) or len(token.encode("utf-8")) < 8
            for token in tokens
        )
    ):
        _reject()
    normalized_tokens = {token.casefold() for token in tokens}
    if not {
        parsed_path.name.casefold(),
        parsed_path.parent.name.casefold(),
    }.issubset(normalized_tokens):
        _reject()
    return source


def _sensitive_needles(
    source: dict[str, Any],
    receipt: dict[str, Any] | None = None,
) -> list[bytes]:
    source_path = Path(source["source_path"])
    values: list[str] = [
        str(source_path),
        source_path.name,
        source_path.parent.name,
        source["source_sha256"],
        source["private_nonce"],
        str(SOURCE_PREREGISTRATION),
        str(PRIVATE_RECEIPT),
        *source["forbidden_public_identity_tokens"],
    ]
    if receipt is not None:
        values.extend(
            [
                receipt["private_receipt_nonce"],
                receipt["xyz"]["payload_sha256"],
                receipt["snr"]["payload_sha256"],
            ]
        )
    return [value.encode("utf-8").lower() for value in values]


def _assert_public_privacy(
    raw: bytes,
    parsed: dict[str, Any],
    source: dict[str, Any],
    receipt: dict[str, Any] | None = None,
) -> None:
    if set(_walk_keys(parsed)) & FORBIDDEN_PUBLIC_KEYS:
        _reject()
    lowered = raw.lower()
    for needle in _sensitive_needles(source, receipt):
        if len(needle) >= 8 and needle in lowered:
            _reject()


def _validate_protocol(
    raw: bytes,
    value: dict[str, Any],
    source: dict[str, Any],
    source_preregistration_sha256: str,
) -> None:
    if (
        value.get("schema") != PROTOCOL_SCHEMA
        or value.get("claim_scope") != CLAIM_SCOPE
    ):
        _reject()
    string_values = set(_walk_string_values(value))
    live_source_hashes = {
        source_preregistration_sha256,
        PROBE_SHA256,
        TEST_MODULE_SHA256,
        hashlib.sha256(_stable_regular_bytes(PRIMARY_SCORER)).hexdigest(),
        hashlib.sha256(_stable_regular_bytes(NOVEL_SCORER)).hexdigest(),
    }
    if not live_source_hashes.issubset(string_values):
        _reject()
    _assert_public_privacy(raw, value, source)


def _validate_channel(
    value: Any,
    *,
    shape: list[int],
    payload_size_bytes: int,
) -> int:
    channel = _exact_keys(
        value,
        frozenset(
            {
                "shape",
                "dtype",
                "c_contiguous",
                "payload_size_bytes",
                "payload_sha256",
            }
        ),
    )
    if (
        channel.get("shape") != shape
        or channel.get("dtype") != "<f4"
        or channel.get("c_contiguous") is not True
        or channel.get("payload_size_bytes") != payload_size_bytes
        or not _is_sha256(channel.get("payload_sha256"))
        or channel["payload_sha256"] == "0" * 64
    ):
        _reject()
    return 1


def _validate_private_receipt(
    receipt: dict[str, Any],
    *,
    source: dict[str, Any],
    source_preregistration_sha256: str,
    protocol_sha256: str,
    source_fingerprint: tuple[int, ...],
) -> int:
    private = _exact_keys(receipt, PRIVATE_RECEIPT_KEYS)
    false_claims = (
        "public_identity_or_geometry_payload_present",
        "independent_decoder_replay_performed",
        "semantic_raw_to_array_fidelity_independently_established",
        "actual_strict_layout_provenance_established",
        "complete_23_view_cycle_evaluated",
        "datamatrix_coverage_established",
        "physical_accuracy_established",
        "campaign_720_replayed",
        "production_ready_or_changed",
    )
    if (
        private.get("schema") != PRIVATE_RECEIPT_SCHEMA
        or private.get("status") != "PASS"
        or private.get("claim_scope") != CLAIM_SCOPE
        or private.get("execution_boundary")
        != "PRIVATE_RECEIPT_CHAIN_AUDIT_NOT_INDEPENDENT_DECODER_REPLAY"
        or not _is_sha256(private.get("private_receipt_nonce"))
        or private["private_receipt_nonce"] == source["private_nonce"]
        or private.get("protocol_sha256") != protocol_sha256
        or private.get("source_preregistration_path") != str(SOURCE_PREREGISTRATION)
        or private.get("source_preregistration_sha256") != source_preregistration_sha256
        or private.get("source_path") != source["source_path"]
        or private.get("source_sha256") != source["source_sha256"]
        or private.get("source_size_bytes") != source["source_size_bytes"]
        or private.get("source_role") != EXPECTED_SOURCE_ROLE
        or private.get("source_fd_stability_verified") is not True
        or private.get("snapshot_sha256") != source["source_sha256"]
        or private.get("snapshot_size_bytes") != source["source_size_bytes"]
        or private.get("source_snapshot_byte_identity_verified") is not True
        or private.get("source_snapshot_distinct_inode_verified") is not True
        or private.get("scratch_snapshot_removed_before_publication") is not True
        or private.get("requested_channels") != list(EXPECTED_CHANNELS)
        or private.get("application_call_trace") != list(EXPECTED_OPERATIONS)
        or private.get("runtime_versions") != EXPECTED_RUNTIME
        or private.get("organized_image_shape") != [EXPECTED_HEIGHT, EXPECTED_WIDTH]
        or any(private.get(name) is not False for name in false_claims)
    ):
        _reject()
    before = _exact_int_list(private["source_stat_fingerprint_before"], 7)
    after = _exact_int_list(private["source_stat_fingerprint_after"], 7)
    snapshot = _exact_int_list(private["snapshot_stat_fingerprint"], 7)
    if (
        before != after
        or tuple(before) != source_fingerprint
        or snapshot[2] != 0o600
        or snapshot[3] != 1
        or snapshot[4] != source["source_size_bytes"]
        or snapshot[:2] == before[:2]
    ):
        _reject()
    xyz_count = _validate_channel(
        private["xyz"],
        shape=[EXPECTED_HEIGHT, EXPECTED_WIDTH, 3],
        payload_size_bytes=EXPECTED_HEIGHT * EXPECTED_WIDTH * 3 * 4,
    )
    snr_count = _validate_channel(
        private["snr"],
        shape=[EXPECTED_HEIGHT, EXPECTED_WIDTH],
        payload_size_bytes=EXPECTED_HEIGHT * EXPECTED_WIDTH * 4,
    )
    payload_hashes = {
        private["xyz"]["payload_sha256"],
        private["snr"]["payload_sha256"],
    }
    if len(payload_hashes) != 2 or source["source_sha256"] in payload_hashes:
        _reject()
    return xyz_count + snr_count


def _validate_public_result(
    public: dict[str, Any],
    *,
    source_preregistration_sha256: str,
    protocol_sha256: str,
    private_receipt_sha256: str,
) -> None:
    result = _exact_keys(public, PUBLIC_RESULT_KEYS)
    true_gates = (
        "actual_development_zdf_decoded",
        "shared_pixel_grid",
        "source_commitment_match",
        "source_fd_stability_verified",
        "source_snapshot_byte_identity_verified",
        "source_snapshot_distinct_inode_verified",
        "scratch_snapshot_removed_before_publication",
    )
    false_claims = (
        "public_identity_or_geometry_payload_present",
        "independent_decoder_replay_performed",
        "semantic_raw_to_array_fidelity_independently_established",
        "actual_strict_layout_provenance_established",
        "complete_23_view_cycle_evaluated",
        "calibration_or_absolute_measurement_established",
        "datamatrix_coverage_established",
        "raw_to_p1b_campaign_staged",
        "physical_accuracy_established",
        "campaign_720_replayed",
        "anonymity_or_reidentification_resistance_established",
        "postpublication_immutability_established",
        "production_ready_or_changed",
    )
    expected_array_contract = {
        "xyz": {
            "shape": [EXPECTED_HEIGHT, EXPECTED_WIDTH, 3],
            "dtype": "<f4",
            "c_contiguous": True,
        },
        "snr": {
            "shape": [EXPECTED_HEIGHT, EXPECTED_WIDTH],
            "dtype": "<f4",
            "c_contiguous": True,
        },
    }
    if (
        result.get("schema") != PUBLIC_RESULT_SCHEMA
        or result.get("status") != "PASS"
        or result.get("claim_scope") != CLAIM_SCOPE
        or result.get("execution_boundary")
        != "ONE_PRECOMMITTED_ACTUAL_DEVELOPMENT_ZDF_OFFLINE_SNAPSHOT"
        or result.get("protocol_sha256") != protocol_sha256
        or result.get("source_preregistration_sha256") != source_preregistration_sha256
        or result.get("requested_channels") != list(EXPECTED_CHANNELS)
        or result.get("required_channel_count") != 2
        or result.get("application_call_trace") != list(EXPECTED_OPERATIONS)
        or result.get("organized_image_shape") != [EXPECTED_HEIGHT, EXPECTED_WIDTH]
        or result.get("array_contract") != expected_array_contract
        or result.get("runtime_versions") != EXPECTED_RUNTIME
        or result.get("private_receipt_sha256") != private_receipt_sha256
        or any(result.get(name) is not True for name in true_gates)
        or any(result.get(name) is not False for name in false_claims)
    ):
        _reject()


def _verify_frozen_sources() -> None:
    for path, expected in (
        (PROBE, PROBE_SHA256),
        (TEST_MODULE, TEST_MODULE_SHA256),
    ):
        observed = hashlib.sha256(_stable_regular_bytes(path)).hexdigest()
        if observed != expected:
            _reject()


def _score() -> int:
    _verify_frozen_sources()
    _validate_private_root_and_scratch()

    source_raw = _stable_regular_bytes(
        SOURCE_PREREGISTRATION,
        required_mode=0o600,
    )
    source_preregistration_sha256 = hashlib.sha256(source_raw).hexdigest()
    source = _validate_source_preregistration(_load_json(source_raw))
    observed_source_sha256, source_fingerprint = _hash_stable_source(
        Path(source["source_path"]),
        source["source_size_bytes"],
    )
    if observed_source_sha256 != source["source_sha256"]:
        _reject()

    protocol_raw = _stable_regular_bytes(PROTOCOL)
    protocol_sha256 = hashlib.sha256(protocol_raw).hexdigest()
    protocol = _load_json(protocol_raw)
    _validate_protocol(
        protocol_raw,
        protocol,
        source,
        source_preregistration_sha256,
    )

    private_raw = _stable_regular_bytes(PRIVATE_RECEIPT, required_mode=0o600)
    private_receipt_sha256 = hashlib.sha256(private_raw).hexdigest()
    private = _load_json(private_raw)
    channel_count = _validate_private_receipt(
        private,
        source=source,
        source_preregistration_sha256=source_preregistration_sha256,
        protocol_sha256=protocol_sha256,
        source_fingerprint=source_fingerprint,
    )

    public_raw = _stable_regular_bytes(PUBLIC_RESULT, required_mode=0o444)
    public = _load_json(public_raw)
    _validate_public_result(
        public,
        source_preregistration_sha256=source_preregistration_sha256,
        protocol_sha256=protocol_sha256,
        private_receipt_sha256=private_receipt_sha256,
    )
    _assert_public_privacy(public_raw, public, source, private)
    if channel_count != len(EXPECTED_CHANNELS):
        _reject()
    return channel_count


def main() -> int:
    try:
        if len(sys.argv) != 2 or not _same_fixed_path(sys.argv[1], PUBLIC_RESULT):
            _reject()
        metric = _score()
    except Exception:
        sys.stderr.write("E_P1C_REQUIRED_CHANNEL_REJECTED\n")
        return 2
    print(f"metric={metric}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
