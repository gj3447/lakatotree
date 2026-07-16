#!/usr/bin/env python3
"""Score the frozen P1d private 23-view decode/export receipt chain.

The novel metric is the actual development view count (23).  The judge first
requires the frozen twelve-case primary score, then audits the mode-0600
private receipt, the mode-0700 bundle, all 46 committed single-link NPY files,
and the mode-0444 sanitized public result.  It never imports Zivid or NumPy and
never emits private paths, source commitments, or array commitments.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys
from types import ModuleType
from typing import Any, Iterable, Mapping, Sequence


BPC_ROOT = Path("/data/kjra/PROJECT/3DLAB/BPC_ICP_SPEC")
LAKATO_ROOT = Path("/data/kjra/PROJECT/PI/lakatotree")
PRIVATE_ROOT = Path("/data/kjra/PROJECT/3DLAB/.private_bpc_p1d")

PRIMARY_SCORER = LAKATO_ROOT / (
    "scripts/judge_bpc_tab_development_zdf_complete_cycle_p1d_20260714.py"
)
NOVEL_SCORER = Path(__file__).absolute()
PROTOCOL = BPC_ROOT / (
    "evidence/bpc_tab_bolt_development_zdf_cycle_decode_protocol_20260714.json"
)
PUBLIC_RESULT = BPC_ROOT / (
    "evidence/bpc_tab_bolt_development_zdf_cycle_decode_result_20260714.json"
)
FIXED_JUNIT = BPC_ROOT / (
    "evidence/bpc_tab_bolt_development_zdf_cycle_decode_conformance_20260714.xml"
)
CYCLE_MANIFEST = PRIVATE_ROOT / (
    "bpc_tab_bolt_development_zdf_cycle_preregistration_20260714.json"
)
FIXED_SCRATCH = PRIVATE_ROOT / "scratch"
PRIVATE_BUNDLE = PRIVATE_ROOT / "development_decoded_cycle_r1"
BUNDLE_MANIFEST = PRIVATE_BUNDLE / "bundle_manifest.json"
PRIVATE_RECEIPT = PRIVATE_ROOT / (
    "bpc_tab_bolt_development_zdf_cycle_decode_private_receipt_20260714.json"
)

PRIMARY_SCORER_SHA256 = (
    "1f5d7cd0068e95b12ef3abdbadc1e606ae3846363e229723174f5471f1656a02"
)
CYCLE_MANIFEST_SHA256 = (
    "52319e2b424a5784c5bcfc60431fd812966414ab5901590bf53cd353443eddfe"
)

CLAIM_SCOPE = "ACTUAL_DEVELOPMENT_23VIEW_PRIVATE_DECODE_EXPORT_ONLY"
CYCLE_MANIFEST_SCHEMA = "bpc.tab_bolt.development_zdf_cycle_private_manifest.v1"
PRIVATE_BUNDLE_SCHEMA = (
    "bpc.tab_bolt.development_zdf_cycle_decoded_bundle_private_manifest.v1"
)
PRIVATE_RECEIPT_SCHEMA = "bpc.tab_bolt.development_zdf_cycle_decode_private_receipt.v1"
PUBLIC_RESULT_SCHEMA = "bpc.tab_bolt.development_zdf_cycle_decode_result.v1"
EXECUTION_BOUNDARY = "ONE_PRECOMMITTED_ACTUAL_DEVELOPMENT_23VIEW_PRIVATE_DECODE_EXPORT"
EXPORT_COMMITMENT_DOMAIN = "BPC_TAB_BOLT_DEVELOPMENT_ZDF_CYCLE_EXPORT_COMMITMENT_V1"
EXPECTED_PRIMARY = 12
EXPECTED_VIEWS = 23
EXPECTED_ARRAYS = 46
EXPECTED_INDICES = tuple(range(EXPECTED_VIEWS))
EXPECTED_CHANNELS = ("xyz", "snr")
EXPECTED_OPERATIONS = (
    "zivid.Frame",
    "frame.point_cloud",
    "copy_data:xyz",
    "copy_data:snr",
)
EXPECTED_HEIGHT = 2048
EXPECTED_WIDTH = 2448
EXPECTED_RUNTIME = {
    "python": "3.10.20",
    "zivid": "2.17.2",
    "numpy": "2.2.6",
}
EXPECTED_ARRAY_CONTRACT = {
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
EXPECTED_PAYLOAD_BYTES = {
    "xyz": EXPECTED_HEIGHT * EXPECTED_WIDTH * 3 * 4,
    "snr": EXPECTED_HEIGHT * EXPECTED_WIDTH * 4,
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_SMALL_FILE_BYTES = 16 * 1024 * 1024
MAX_ARRAY_FILE_BYTES = 128 * 1024 * 1024

CYCLE_MANIFEST_KEYS = frozenset(
    {
        "schema",
        "claim_scope",
        "status",
        "source_anchor_path",
        "source_anchor_sha256",
        "source_directory",
        "source_role",
        "expected_image_shape",
        "expected_python_version",
        "expected_zivid_version",
        "expected_numpy_version",
        "view_count",
        "view_indices",
        "entries",
        "aggregate_source_commitment_sha256",
        "strict_v1_provenance_established",
    }
)
PRIVATE_BUNDLE_KEYS = frozenset(
    {
        "schema",
        "status",
        "claim_scope",
        "cycle_manifest_sha256",
        "aggregate_source_commitment_sha256",
        "view_count",
        "view_indices",
        "requested_channels",
        "required_channel_count",
        "array_file_count",
        "application_initialization_count",
        "per_view_decode_operations",
        "runtime_versions",
        "array_contract",
        "outputs",
        "aggregate_export_commitment_sha256",
        "source_commitment_verified_count",
        "source_postdecode_stability_verified_count",
        "snapshot_byte_identity_verified_count",
        "scratch_snapshot_cleanup_verified_count",
        "strict_v1_provenance_established",
        "raw_to_p1b_campaign_staged",
        "physical_accuracy_established",
        "production_ready_or_changed",
    }
)
OUTPUT_ENTRY_KEYS = frozenset(
    {
        "view_index",
        "view_token",
        "channel",
        "relative_path",
        "file_sha256",
        "file_size_bytes",
        "array_payload_size_bytes",
        "shape",
        "dtype",
        "c_contiguous",
    }
)
PRIVATE_RECEIPT_KEYS = frozenset(
    {
        "schema",
        "status",
        "claim_scope",
        "protocol_sha256",
        "cycle_manifest_sha256",
        "aggregate_source_commitment_sha256",
        "private_bundle_target",
        "private_bundle_manifest_sha256",
        "aggregate_export_commitment_sha256",
        "view_count",
        "array_file_count",
        "application_initialization_count",
        "source_commitment_verified_count",
        "source_postdecode_stability_verified_count",
        "snapshot_byte_identity_verified_count",
        "scratch_snapshot_cleanup_verified_count",
        "bundle_directory_mode",
        "array_file_mode",
        "bundle_manifest_mode",
        "bundle_atomic_noreplace_published",
        "strict_v1_provenance_established",
        "raw_to_p1b_campaign_staged",
        "physical_accuracy_established",
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
        "cycle_manifest_sha256",
        "private_receipt_sha256",
        "actual_development_cycle_decoded_exported",
        "view_count",
        "view_indices",
        "requested_channels",
        "required_channel_count",
        "array_file_count",
        "application_initialization_count",
        "per_view_decode_operations",
        "organized_image_shape",
        "array_contract",
        "runtime_versions",
        "source_commitment_verified_count",
        "source_postdecode_stability_verified_count",
        "snapshot_byte_identity_verified_count",
        "scratch_snapshot_cleanup_verified_count",
        "bundle_atomic_noreplace_published",
        "public_identity_or_geometry_payload_present",
        "strict_v1_provenance_established",
        "literal_role_atlas_established",
        "complete_physical_holdout_cycle_established",
        "raw_to_p1b_campaign_staged",
        "calibration_or_absolute_measurement_established",
        "datamatrix_coverage_established",
        "physical_accuracy_established",
        "campaign_720_replayed",
        "production_ready_or_changed",
    }
)
FORBIDDEN_PUBLIC_KEYS = frozenset(
    {
        "source_anchor_path",
        "source_anchor_sha256",
        "source_directory",
        "source_path",
        "source_sha256",
        "source_size_bytes",
        "source_stat_fingerprint",
        "aggregate_source_commitment_sha256",
        "private_bundle_target",
        "private_bundle_manifest_sha256",
        "aggregate_export_commitment_sha256",
        "private_receipt_path",
        "scratch_directory",
        "relative_path",
        "file_sha256",
        "file_size_bytes",
        "array_payload_size_bytes",
        "payload_sha256",
        "view_token",
        "source_basename",
        "lot_id",
        "capture_id",
        "serial_id",
        "view_id",
    }
)


class ScoreRejected(RuntimeError):
    """Fail closed without echoing private identities or commitments."""


def _reject() -> None:
    raise ScoreRejected("E_P1D_COMPLETE_CYCLE_NOVEL_REJECTED")


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


def _stable_regular_sha256(path: Path, *, expected_size: int) -> str:
    if not 0 < expected_size <= MAX_ARRAY_FILE_BYTES:
        _reject()
    try:
        pathname = path.lstat()
    except OSError:
        _reject()
    if (
        stat.S_ISLNK(pathname.st_mode)
        or not stat.S_ISREG(pathname.st_mode)
        or pathname.st_nlink != 1
        or stat.S_IMODE(pathname.st_mode) != 0o600
        or pathname.st_size != expected_size
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
        digest = hashlib.sha256()
        observed_size = 0
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            digest.update(block)
            observed_size += len(block)
        if observed_size != expected_size or _fingerprint(
            os.fstat(descriptor)
        ) != _fingerprint(opened):
            _reject()
        return digest.hexdigest()
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


def _load_frozen(name: str, path: Path, expected_sha256: str) -> ModuleType:
    source = _stable_regular_bytes(path)
    if hashlib.sha256(source).hexdigest() != expected_sha256:
        _reject()
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None or name in sys.modules:
        _reject()
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def _validate_private_directories() -> tuple[int, ...]:
    try:
        private_info = PRIVATE_ROOT.lstat()
        scratch_info = FIXED_SCRATCH.lstat()
        bundle_info = PRIVATE_BUNDLE.lstat()
    except OSError:
        _reject()
    if (
        stat.S_ISLNK(private_info.st_mode)
        or not stat.S_ISDIR(private_info.st_mode)
        or stat.S_IMODE(private_info.st_mode) != 0o700
        or stat.S_ISLNK(scratch_info.st_mode)
        or not stat.S_ISDIR(scratch_info.st_mode)
        or stat.S_IMODE(scratch_info.st_mode) != 0o700
        or stat.S_ISLNK(bundle_info.st_mode)
        or not stat.S_ISDIR(bundle_info.st_mode)
        or stat.S_IMODE(bundle_info.st_mode) != 0o700
    ):
        _reject()
    try:
        with os.scandir(FIXED_SCRATCH) as entries:
            if next(entries, None) is not None:
                _reject()
    except OSError:
        _reject()
    return _fingerprint(bundle_info)


def _validate_cycle_manifest(raw: bytes) -> tuple[dict[str, Any], str]:
    if hashlib.sha256(raw).hexdigest() != CYCLE_MANIFEST_SHA256:
        _reject()
    manifest = _exact_keys(_load_json(raw), CYCLE_MANIFEST_KEYS)
    aggregate_source = manifest.get("aggregate_source_commitment_sha256")
    if (
        _canonical_json_bytes(manifest) != raw
        or manifest.get("schema") != CYCLE_MANIFEST_SCHEMA
        or manifest.get("status") != "PASS"
        or manifest.get("claim_scope") != CLAIM_SCOPE
        or manifest.get("source_role") != "POINT_GEOMETRY"
        or manifest.get("expected_image_shape") != [EXPECTED_HEIGHT, EXPECTED_WIDTH]
        or manifest.get("expected_python_version") != EXPECTED_RUNTIME["python"]
        or manifest.get("expected_zivid_version") != EXPECTED_RUNTIME["zivid"]
        or manifest.get("expected_numpy_version") != EXPECTED_RUNTIME["numpy"]
        or manifest.get("view_count") != EXPECTED_VIEWS
        or manifest.get("view_indices") != list(EXPECTED_INDICES)
        or type(manifest.get("entries")) is not list
        or len(manifest["entries"]) != EXPECTED_VIEWS
        or not _is_sha256(aggregate_source)
        or manifest.get("strict_v1_provenance_established") is not False
    ):
        _reject()
    return manifest, aggregate_source


def _expected_output_names() -> list[str]:
    return [
        f"v{view_index:02d}_{channel}.npy"
        for view_index in EXPECTED_INDICES
        for channel in EXPECTED_CHANNELS
    ]


def _validate_output_entry(
    raw: Any,
    *,
    position: int,
) -> dict[str, Any]:
    output = _exact_keys(raw, OUTPUT_ENTRY_KEYS)
    view_index = position // len(EXPECTED_CHANNELS)
    channel = EXPECTED_CHANNELS[position % len(EXPECTED_CHANNELS)]
    payload_size = EXPECTED_PAYLOAD_BYTES[channel]
    expected_shape = EXPECTED_ARRAY_CONTRACT[channel]["shape"]
    expected_name = f"v{view_index:02d}_{channel}.npy"
    file_size = output.get("file_size_bytes")
    if (
        output.get("view_index") != view_index
        or output.get("view_token") != f"v{view_index:02d}"
        or output.get("channel") != channel
        or output.get("relative_path") != expected_name
        or not _is_sha256(output.get("file_sha256"))
        or type(file_size) is not int
        or not payload_size < file_size <= payload_size + 4096
        or output.get("array_payload_size_bytes") != payload_size
        or output.get("shape") != expected_shape
        or output.get("dtype") != "<f4"
        or output.get("c_contiguous") is not True
    ):
        _reject()
    observed = _stable_regular_sha256(
        PRIVATE_BUNDLE / expected_name,
        expected_size=file_size,
    )
    if observed != output["file_sha256"]:
        _reject()
    return output


def _aggregate_export_commitment(outputs: Sequence[Mapping[str, Any]]) -> str:
    if len(outputs) != EXPECTED_ARRAYS:
        _reject()
    committed: list[dict[str, Any]] = []
    for position, output in enumerate(outputs):
        expected_index = position // len(EXPECTED_CHANNELS)
        expected_channel = EXPECTED_CHANNELS[position % len(EXPECTED_CHANNELS)]
        if (
            output.get("view_index") != expected_index
            or output.get("channel") != expected_channel
            or not _is_sha256(output.get("file_sha256"))
        ):
            _reject()
        committed.append(
            {
                "view_index": expected_index,
                "view_token": f"v{expected_index:02d}",
                "channel": expected_channel,
                "file_sha256": output["file_sha256"],
                "file_size_bytes": output["file_size_bytes"],
                "array_payload_size_bytes": output["array_payload_size_bytes"],
            }
        )
    return hashlib.sha256(
        _canonical_json_bytes(
            {"domain": EXPORT_COMMITMENT_DOMAIN, "outputs": committed}
        )
    ).hexdigest()


def _validate_bundle_manifest(
    raw: bytes,
    *,
    aggregate_source: str,
) -> tuple[dict[str, Any], str, str]:
    bundle = _exact_keys(_load_json(raw), PRIVATE_BUNDLE_KEYS)
    outputs = bundle.get("outputs")
    false_claims = (
        "strict_v1_provenance_established",
        "raw_to_p1b_campaign_staged",
        "physical_accuracy_established",
        "production_ready_or_changed",
    )
    if (
        _canonical_json_bytes(bundle) != raw
        or bundle.get("schema") != PRIVATE_BUNDLE_SCHEMA
        or bundle.get("status") != "PASS"
        or bundle.get("claim_scope") != CLAIM_SCOPE
        or bundle.get("cycle_manifest_sha256") != CYCLE_MANIFEST_SHA256
        or bundle.get("aggregate_source_commitment_sha256") != aggregate_source
        or bundle.get("view_count") != EXPECTED_VIEWS
        or bundle.get("view_indices") != list(EXPECTED_INDICES)
        or bundle.get("requested_channels") != list(EXPECTED_CHANNELS)
        or bundle.get("required_channel_count") != len(EXPECTED_CHANNELS)
        or bundle.get("array_file_count") != EXPECTED_ARRAYS
        or bundle.get("application_initialization_count") != 1
        or bundle.get("per_view_decode_operations") != list(EXPECTED_OPERATIONS)
        or bundle.get("runtime_versions") != EXPECTED_RUNTIME
        or bundle.get("array_contract") != EXPECTED_ARRAY_CONTRACT
        or type(outputs) is not list
        or len(outputs) != EXPECTED_ARRAYS
        or bundle.get("source_commitment_verified_count") != EXPECTED_VIEWS
        or bundle.get("source_postdecode_stability_verified_count") != EXPECTED_VIEWS
        or bundle.get("snapshot_byte_identity_verified_count") != EXPECTED_VIEWS
        or bundle.get("scratch_snapshot_cleanup_verified_count") != EXPECTED_VIEWS
        or any(bundle.get(name) is not False for name in false_claims)
    ):
        _reject()

    validated_outputs = [
        _validate_output_entry(output, position=position)
        for position, output in enumerate(outputs)
    ]
    aggregate_export = _aggregate_export_commitment(validated_outputs)
    if bundle.get("aggregate_export_commitment_sha256") != aggregate_export:
        _reject()
    return bundle, hashlib.sha256(raw).hexdigest(), aggregate_export


def _validate_bundle_tree(expected_fingerprint: tuple[int, ...]) -> None:
    expected_names = sorted([*_expected_output_names(), "bundle_manifest.json"])
    try:
        observed_names = sorted(os.listdir(PRIVATE_BUNDLE))
        after = PRIVATE_BUNDLE.lstat()
    except OSError:
        _reject()
    if observed_names != expected_names or _fingerprint(after) != expected_fingerprint:
        _reject()


def _validate_private_receipt(
    raw: bytes,
    *,
    protocol_sha256: str,
    aggregate_source: str,
    bundle_manifest_sha256: str,
    aggregate_export: str,
) -> tuple[dict[str, Any], str]:
    receipt = _exact_keys(_load_json(raw), PRIVATE_RECEIPT_KEYS)
    false_claims = (
        "strict_v1_provenance_established",
        "raw_to_p1b_campaign_staged",
        "physical_accuracy_established",
        "production_ready_or_changed",
    )
    if (
        _canonical_json_bytes(receipt) != raw
        or receipt.get("schema") != PRIVATE_RECEIPT_SCHEMA
        or receipt.get("status") != "PASS"
        or receipt.get("claim_scope") != CLAIM_SCOPE
        or receipt.get("protocol_sha256") != protocol_sha256
        or receipt.get("cycle_manifest_sha256") != CYCLE_MANIFEST_SHA256
        or receipt.get("aggregate_source_commitment_sha256") != aggregate_source
        or receipt.get("private_bundle_target") != str(PRIVATE_BUNDLE)
        or receipt.get("private_bundle_manifest_sha256") != bundle_manifest_sha256
        or receipt.get("aggregate_export_commitment_sha256") != aggregate_export
        or receipt.get("view_count") != EXPECTED_VIEWS
        or receipt.get("array_file_count") != EXPECTED_ARRAYS
        or receipt.get("application_initialization_count") != 1
        or receipt.get("source_commitment_verified_count") != EXPECTED_VIEWS
        or receipt.get("source_postdecode_stability_verified_count") != EXPECTED_VIEWS
        or receipt.get("snapshot_byte_identity_verified_count") != EXPECTED_VIEWS
        or receipt.get("scratch_snapshot_cleanup_verified_count") != EXPECTED_VIEWS
        or receipt.get("bundle_directory_mode") != "0700"
        or receipt.get("array_file_mode") != "0600"
        or receipt.get("bundle_manifest_mode") != "0600"
        or receipt.get("bundle_atomic_noreplace_published") is not True
        or any(receipt.get(name) is not False for name in false_claims)
    ):
        _reject()
    return receipt, hashlib.sha256(raw).hexdigest()


def _validate_public_result(
    raw: bytes,
    *,
    protocol_sha256: str,
    private_receipt_sha256: str,
) -> None:
    public = _exact_keys(_load_json(raw), PUBLIC_RESULT_KEYS)
    true_gates = (
        "actual_development_cycle_decoded_exported",
        "bundle_atomic_noreplace_published",
    )
    false_claims = (
        "public_identity_or_geometry_payload_present",
        "strict_v1_provenance_established",
        "literal_role_atlas_established",
        "complete_physical_holdout_cycle_established",
        "raw_to_p1b_campaign_staged",
        "calibration_or_absolute_measurement_established",
        "datamatrix_coverage_established",
        "physical_accuracy_established",
        "campaign_720_replayed",
        "production_ready_or_changed",
    )
    if (
        _canonical_json_bytes(public) != raw
        or public.get("schema") != PUBLIC_RESULT_SCHEMA
        or public.get("status") != "PASS"
        or public.get("claim_scope") != CLAIM_SCOPE
        or public.get("execution_boundary") != EXECUTION_BOUNDARY
        or public.get("protocol_sha256") != protocol_sha256
        or public.get("cycle_manifest_sha256") != CYCLE_MANIFEST_SHA256
        or public.get("private_receipt_sha256") != private_receipt_sha256
        or public.get("view_count") != EXPECTED_VIEWS
        or public.get("view_indices") != list(EXPECTED_INDICES)
        or public.get("requested_channels") != list(EXPECTED_CHANNELS)
        or public.get("required_channel_count") != len(EXPECTED_CHANNELS)
        or public.get("array_file_count") != EXPECTED_ARRAYS
        or public.get("application_initialization_count") != 1
        or public.get("per_view_decode_operations") != list(EXPECTED_OPERATIONS)
        or public.get("organized_image_shape") != [EXPECTED_HEIGHT, EXPECTED_WIDTH]
        or public.get("array_contract") != EXPECTED_ARRAY_CONTRACT
        or public.get("runtime_versions") != EXPECTED_RUNTIME
        or public.get("source_commitment_verified_count") != EXPECTED_VIEWS
        or public.get("source_postdecode_stability_verified_count") != EXPECTED_VIEWS
        or public.get("snapshot_byte_identity_verified_count") != EXPECTED_VIEWS
        or public.get("scratch_snapshot_cleanup_verified_count") != EXPECTED_VIEWS
        or any(public.get(name) is not True for name in true_gates)
        or any(public.get(name) is not False for name in false_claims)
    ):
        _reject()
    if set(_walk_keys(public)) & FORBIDDEN_PUBLIC_KEYS:
        _reject()
    lowered = raw.lower()
    if any(
        token in lowered for token in (b"/data/", b".private_bpc", b".zdf", b".npy")
    ):
        _reject()
    allowed_hashes = {
        protocol_sha256,
        CYCLE_MANIFEST_SHA256,
        private_receipt_sha256,
    }
    observed_hashes = {
        value for value in _walk_string_values(public) if _is_sha256(value)
    }
    if observed_hashes != allowed_hashes:
        _reject()


def score() -> int:
    """Return 23 only for the complete private bundle and sanitized receipt."""

    primary = _load_frozen(
        "_bpc_tab_development_zdf_complete_cycle_primary_p1d_frozen",
        PRIMARY_SCORER,
        PRIMARY_SCORER_SHA256,
    )
    if primary.score() != EXPECTED_PRIMARY:
        _reject()

    bundle_fingerprint = _validate_private_directories()
    protocol_sha256 = hashlib.sha256(_stable_regular_bytes(PROTOCOL)).hexdigest()
    manifest_raw = _stable_regular_bytes(CYCLE_MANIFEST, required_mode=0o600)
    _, aggregate_source = _validate_cycle_manifest(manifest_raw)

    bundle_raw = _stable_regular_bytes(BUNDLE_MANIFEST, required_mode=0o600)
    _, bundle_manifest_sha256, aggregate_export = _validate_bundle_manifest(
        bundle_raw,
        aggregate_source=aggregate_source,
    )
    _validate_bundle_tree(bundle_fingerprint)

    receipt_raw = _stable_regular_bytes(PRIVATE_RECEIPT, required_mode=0o600)
    _, private_receipt_sha256 = _validate_private_receipt(
        receipt_raw,
        protocol_sha256=protocol_sha256,
        aggregate_source=aggregate_source,
        bundle_manifest_sha256=bundle_manifest_sha256,
        aggregate_export=aggregate_export,
    )
    public_raw = _stable_regular_bytes(PUBLIC_RESULT, required_mode=0o444)
    _validate_public_result(
        public_raw,
        protocol_sha256=protocol_sha256,
        private_receipt_sha256=private_receipt_sha256,
    )
    return EXPECTED_VIEWS


def main() -> int:
    try:
        if len(sys.argv) != 2 or not _same_fixed_path(sys.argv[1], FIXED_JUNIT):
            _reject()
        metric = score()
    except Exception:
        sys.stderr.write("E_P1D_COMPLETE_CYCLE_NOVEL_REJECTED\n")
        return 2
    print(f"metric={metric}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
