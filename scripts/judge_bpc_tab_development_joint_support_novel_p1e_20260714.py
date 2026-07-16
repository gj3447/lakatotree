#!/usr/bin/env python3
"""Score the frozen P1e private joint-finite-support census.

The novel metric is the number of actual development views with at least one
pixel whose XYZ triplet and SNR value are all finite.  The judge requires the
frozen P1e primary and P1d bundle judges, then independently reloads all 46
committed P1d arrays and recomputes every one of the 23 private count records.
Only aggregate counts and a three-link receipt chain may appear publicly.
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

import numpy as np


BPC_ROOT = Path("/data/kjra/PROJECT/3DLAB/BPC_ICP_SPEC")
LAKATO_ROOT = Path("/data/kjra/PROJECT/PI/lakatotree")
P1D_PRIVATE_ROOT = Path("/data/kjra/PROJECT/3DLAB/.private_bpc_p1d")
P1E_PRIVATE_ROOT = Path("/data/kjra/PROJECT/3DLAB/.private_bpc_p1e")

PRIMARY_SCORER = LAKATO_ROOT / (
    "scripts/judge_bpc_tab_development_joint_support_p1e_20260714.py"
)
NOVEL_SCORER = Path(__file__).absolute()
P1D_NOVEL_SCORER = LAKATO_ROOT / (
    "scripts/judge_bpc_tab_development_zdf_complete_cycle_novel_p1d_20260714.py"
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
P1D_BUNDLE_MANIFEST = P1D_PRIVATE_BUNDLE / "bundle_manifest.json"
P1D_PRIVATE_RECEIPT = P1D_PRIVATE_ROOT / (
    "bpc_tab_bolt_development_zdf_cycle_decode_private_receipt_20260714.json"
)
P1E_PRIVATE_RECEIPT = P1E_PRIVATE_ROOT / (
    "bpc_tab_bolt_development_joint_support_census_private_receipt_20260714.json"
)

PRIMARY_SCORER_SHA256 = (
    "e5eb8f05e021d39d770bb0be3cd30d29d6bc967594f4f6f4a5c3a123e94b3c8b"
)
P1D_NOVEL_SCORER_SHA256 = (
    "662b5630d5c60cab4f3d82b022648585a289e77c6138228f8f87e5d364ceed52"
)
P1D_PRIVATE_RECEIPT_SHA256 = (
    "a30067e64a1dafb9b19d3762c49c09a4f4e8edd98555b35f293ad9c074128685"
)

CLAIM_SCOPE = "ACTUAL_DEVELOPMENT_DECODED_CYCLE_JOINT_SUPPORT_CENSUS_ONLY"
PRIVATE_RECEIPT_SCHEMA = (
    "bpc.tab_bolt.development_decoded_cycle_joint_support_private_receipt.v1"
)
PUBLIC_RESULT_SCHEMA = "bpc.tab_bolt.development_decoded_cycle_joint_support_result.v1"
P1D_BUNDLE_SCHEMA = (
    "bpc.tab_bolt.development_zdf_cycle_decoded_bundle_private_manifest.v1"
)
P1D_RECEIPT_SCHEMA = "bpc.tab_bolt.development_zdf_cycle_decode_private_receipt.v1"
COUNT_COMMITMENT_DOMAIN = (
    "BPC_TAB_BOLT_DEVELOPMENT_DECODED_CYCLE_JOINT_SUPPORT_COUNTS_V1"
)
EXPECTED_PRIMARY = 10
EXPECTED_VIEWS = 23
EXPECTED_ARRAYS = 46
EXPECTED_INDICES = tuple(range(EXPECTED_VIEWS))
EXPECTED_CHANNELS = ("xyz", "snr")
EXPECTED_HEIGHT = 2048
EXPECTED_WIDTH = 2448
EXPECTED_PIXEL_COUNT = EXPECTED_HEIGHT * EXPECTED_WIDTH
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
    "xyz": EXPECTED_PIXEL_COUNT * 3 * 4,
    "snr": EXPECTED_PIXEL_COUNT * 4,
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_SMALL_FILE_BYTES = 16 * 1024 * 1024
MAX_ARRAY_FILE_BYTES = 128 * 1024 * 1024

P1D_OUTPUT_ENTRY_KEYS = frozenset(
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
COUNT_RECORD_KEYS = frozenset(
    {
        "view_index",
        "view_token",
        "pixel_count",
        "xyz_finite_pixel_count",
        "snr_finite_pixel_count",
        "joint_finite_pixel_count",
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
PRIVATE_RECEIPT_KEYS = frozenset(
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
PUBLIC_RESULT_KEYS = frozenset(
    {
        "schema",
        "status",
        "claim_scope",
        "protocol_sha256",
        "input_private_decode_receipt_sha256",
        "private_census_receipt_sha256",
        "evaluated_view_count",
        "views_with_nonzero_joint_finite_support",
        "all_views_have_nonzero_joint_finite_support",
    }
    | NEGATIVE_CLAIM_KEYS
)
PUBLIC_ALLOWED_HASH_KEYS = frozenset(
    {
        "protocol_sha256",
        "input_private_decode_receipt_sha256",
        "private_census_receipt_sha256",
    }
)
PUBLIC_FORBIDDEN_KEYS = frozenset(
    {
        "view_index",
        "view_indices",
        "per_view",
        "per_view_counts",
        "outputs",
        "relative_path",
        "file_sha256",
        "source_sha256",
        "source_path",
        "source_directory",
        "private_bundle_target",
        "private_receipt_path",
        "bundle_manifest_sha256",
        "aggregate_export_commitment_sha256",
        "aggregate_joint_support_count_commitment_sha256",
    }
)


class ScoreRejected(RuntimeError):
    """Fail closed without echoing private paths, counts, or commitments."""


def _reject() -> None:
    raise ScoreRejected("E_P1E_JOINT_SUPPORT_NOVEL_REJECTED")


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
        p1d_root = P1D_PRIVATE_ROOT.lstat()
        p1e_root = P1E_PRIVATE_ROOT.lstat()
        bundle = P1D_PRIVATE_BUNDLE.lstat()
    except OSError:
        _reject()
    if (
        stat.S_ISLNK(p1d_root.st_mode)
        or not stat.S_ISDIR(p1d_root.st_mode)
        or stat.S_IMODE(p1d_root.st_mode) != 0o700
        or stat.S_ISLNK(p1e_root.st_mode)
        or not stat.S_ISDIR(p1e_root.st_mode)
        or stat.S_IMODE(p1e_root.st_mode) != 0o700
        or stat.S_ISLNK(bundle.st_mode)
        or not stat.S_ISDIR(bundle.st_mode)
        or stat.S_IMODE(bundle.st_mode) != 0o700
    ):
        _reject()
    return _fingerprint(bundle)


def _expected_output_names() -> list[str]:
    return [
        f"v{view_index:02d}_{channel}.npy"
        for view_index in EXPECTED_INDICES
        for channel in EXPECTED_CHANNELS
    ]


def _validate_p1d_receipt_and_outputs() -> tuple[list[dict[str, Any]], str, str]:
    receipt_raw = _stable_regular_bytes(P1D_PRIVATE_RECEIPT, required_mode=0o600)
    if hashlib.sha256(receipt_raw).hexdigest() != P1D_PRIVATE_RECEIPT_SHA256:
        _reject()
    receipt = _load_json(receipt_raw)
    if (
        receipt.get("schema") != P1D_RECEIPT_SCHEMA
        or receipt.get("status") != "PASS"
        or receipt.get("claim_scope")
        != "ACTUAL_DEVELOPMENT_23VIEW_PRIVATE_DECODE_EXPORT_ONLY"
        or receipt.get("view_count") != EXPECTED_VIEWS
        or receipt.get("array_file_count") != EXPECTED_ARRAYS
        or receipt.get("private_bundle_target") != str(P1D_PRIVATE_BUNDLE)
        or not _is_sha256(receipt.get("private_bundle_manifest_sha256"))
        or not _is_sha256(receipt.get("aggregate_export_commitment_sha256"))
    ):
        _reject()

    manifest_raw = _stable_regular_bytes(P1D_BUNDLE_MANIFEST, required_mode=0o600)
    manifest = _load_json(manifest_raw)
    outputs = manifest.get("outputs")
    if (
        hashlib.sha256(manifest_raw).hexdigest()
        != receipt["private_bundle_manifest_sha256"]
        or _canonical_json_bytes(manifest) != manifest_raw
        or manifest.get("schema") != P1D_BUNDLE_SCHEMA
        or manifest.get("status") != "PASS"
        or manifest.get("claim_scope")
        != "ACTUAL_DEVELOPMENT_23VIEW_PRIVATE_DECODE_EXPORT_ONLY"
        or manifest.get("view_count") != EXPECTED_VIEWS
        or manifest.get("array_file_count") != EXPECTED_ARRAYS
        or manifest.get("runtime_versions") != EXPECTED_RUNTIME
        or manifest.get("array_contract") != EXPECTED_ARRAY_CONTRACT
        or manifest.get("aggregate_export_commitment_sha256")
        != receipt["aggregate_export_commitment_sha256"]
        or type(outputs) is not list
        or len(outputs) != EXPECTED_ARRAYS
    ):
        _reject()

    validated: list[dict[str, Any]] = []
    for position, raw in enumerate(outputs):
        output = _exact_keys(raw, P1D_OUTPUT_ENTRY_KEYS)
        view_index = position // len(EXPECTED_CHANNELS)
        channel = EXPECTED_CHANNELS[position % len(EXPECTED_CHANNELS)]
        expected_name = f"v{view_index:02d}_{channel}.npy"
        expected_contract = EXPECTED_ARRAY_CONTRACT[channel]
        file_size = output.get("file_size_bytes")
        payload_size = EXPECTED_PAYLOAD_BYTES[channel]
        if (
            output.get("view_index") != view_index
            or output.get("view_token") != f"v{view_index:02d}"
            or output.get("channel") != channel
            or output.get("relative_path") != expected_name
            or not _is_sha256(output.get("file_sha256"))
            or type(file_size) is not int
            or not payload_size < file_size <= payload_size + 4096
            or output.get("array_payload_size_bytes") != payload_size
            or output.get("shape") != expected_contract["shape"]
            or output.get("dtype") != expected_contract["dtype"]
            or output.get("c_contiguous") is not True
        ):
            _reject()
        validated.append(output)
    return (
        validated,
        receipt["private_bundle_manifest_sha256"],
        receipt["aggregate_export_commitment_sha256"],
    )


def _load_committed_npy(output: Mapping[str, Any]) -> np.ndarray:
    path = P1D_PRIVATE_BUNDLE / str(output["relative_path"])
    expected_size = output["file_size_bytes"]
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
        if (
            observed_size != expected_size
            or digest.hexdigest() != output["file_sha256"]
        ):
            _reject()
        os.lseek(descriptor, 0, os.SEEK_SET)
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            array = np.load(stream, allow_pickle=False)
            if stream.read(1):
                _reject()
        try:
            after_pathname = path.lstat()
        except OSError:
            _reject()
        if (
            _fingerprint(os.fstat(descriptor)) != _fingerprint(opened)
            or _fingerprint(after_pathname) != _fingerprint(pathname)
            or not isinstance(array, np.ndarray)
        ):
            _reject()
        return array
    except (OSError, ValueError, TypeError):
        _reject()
    finally:
        os.close(descriptor)


def _validate_array(
    array: np.ndarray,
    *,
    channel: str,
) -> None:
    contract = EXPECTED_ARRAY_CONTRACT[channel]
    if (
        list(array.shape) != contract["shape"]
        or array.dtype.str != contract["dtype"]
        or not array.flags.c_contiguous
        or array.nbytes != EXPECTED_PAYLOAD_BYTES[channel]
    ):
        _reject()


def _recompute_per_view_counts(
    outputs: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if len(outputs) != EXPECTED_ARRAYS or np.__version__ != EXPECTED_RUNTIME["numpy"]:
        _reject()
    per_view: list[dict[str, Any]] = []
    for view_index in EXPECTED_INDICES:
        xyz_output = outputs[view_index * 2]
        snr_output = outputs[view_index * 2 + 1]
        if xyz_output.get("channel") != "xyz" or snr_output.get("channel") != "snr":
            _reject()
        xyz = _load_committed_npy(xyz_output)
        snr = _load_committed_npy(snr_output)
        _validate_array(xyz, channel="xyz")
        _validate_array(snr, channel="snr")

        xyz_finite = np.isfinite(xyz).all(axis=2)
        snr_finite = np.isfinite(snr)
        joint_finite = xyz_finite & snr_finite
        xyz_count = int(np.count_nonzero(xyz_finite))
        snr_count = int(np.count_nonzero(snr_finite))
        joint_count = int(np.count_nonzero(joint_finite))
        if not 0 <= joint_count <= min(xyz_count, snr_count) <= EXPECTED_PIXEL_COUNT:
            _reject()
        per_view.append(
            {
                "view_index": view_index,
                "view_token": f"v{view_index:02d}",
                "pixel_count": EXPECTED_PIXEL_COUNT,
                "xyz_finite_pixel_count": xyz_count,
                "snr_finite_pixel_count": snr_count,
                "joint_finite_pixel_count": joint_count,
            }
        )
    return per_view


def _count_commitment(per_view: Sequence[Mapping[str, Any]]) -> str:
    if len(per_view) != EXPECTED_VIEWS:
        _reject()
    committed: list[dict[str, Any]] = []
    for expected_index, raw in enumerate(per_view):
        record = _exact_keys(raw, COUNT_RECORD_KEYS)
        if (
            record.get("view_index") != expected_index
            or record.get("view_token") != f"v{expected_index:02d}"
            or record.get("pixel_count") != EXPECTED_PIXEL_COUNT
        ):
            _reject()
        values: dict[str, Any] = dict(record)
        for key in COUNT_RECORD_KEYS - {"view_token"}:
            value = record.get(key)
            if type(value) is not int or value < 0:
                _reject()
        if (
            not 0
            <= values["joint_finite_pixel_count"]
            <= min(
                values["xyz_finite_pixel_count"],
                values["snr_finite_pixel_count"],
            )
            <= values["pixel_count"]
        ):
            _reject()
        committed.append(values)
    return hashlib.sha256(
        _canonical_json_bytes(
            {"domain": COUNT_COMMITMENT_DOMAIN, "per_view": committed}
        )
    ).hexdigest()


def _aggregate_counts(per_view: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return {
        "views_with_nonzero_joint_finite_support": sum(
            record["joint_finite_pixel_count"] > 0 for record in per_view
        ),
    }


def _validate_private_receipt(
    raw: bytes,
    *,
    protocol_sha256: str,
    bundle_manifest_sha256: str,
    aggregate_export: str,
    recomputed: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], str, dict[str, int]]:
    receipt = _exact_keys(_load_json(raw), PRIVATE_RECEIPT_KEYS)
    aggregate = _aggregate_counts(recomputed)
    count_commitment = _count_commitment(recomputed)
    views_nonzero = aggregate["views_with_nonzero_joint_finite_support"]
    if (
        _canonical_json_bytes(receipt) != raw
        or receipt.get("schema") != PRIVATE_RECEIPT_SCHEMA
        or receipt.get("status") != "PASS"
        or receipt.get("claim_scope") != CLAIM_SCOPE
        or receipt.get("protocol_sha256") != protocol_sha256
        or receipt.get("input_private_decode_receipt_sha256")
        != P1D_PRIVATE_RECEIPT_SHA256
        or receipt.get("private_bundle_manifest_sha256") != bundle_manifest_sha256
        or receipt.get("aggregate_export_commitment_sha256") != aggregate_export
        or receipt.get("evaluated_view_count") != EXPECTED_VIEWS
        or receipt.get("evaluated_array_file_count") != EXPECTED_ARRAYS
        or receipt.get("organized_image_shape") != [EXPECTED_HEIGHT, EXPECTED_WIDTH]
        or receipt.get("pixels_per_view") != EXPECTED_PIXEL_COUNT
        or receipt.get("row_chunk_size") != 128
        or receipt.get("input_file_pre_census_commitment_verified_count")
        != EXPECTED_ARRAYS
        or receipt.get("input_file_post_census_commitment_verified_count")
        != EXPECTED_ARRAYS
        or receipt.get("per_view") != list(recomputed)
        or receipt.get("aggregate_joint_support_count_commitment_sha256")
        != count_commitment
        or receipt.get("views_with_nonzero_joint_finite_support") != views_nonzero
        or receipt.get("all_views_have_nonzero_joint_finite_support")
        is not (views_nonzero == EXPECTED_VIEWS)
        or any(receipt.get(name) is not False for name in NEGATIVE_CLAIM_KEYS)
    ):
        _reject()
    return receipt, hashlib.sha256(raw).hexdigest(), aggregate


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
        for token in (b"/data/", b".private_bpc", b".zdf", b".npy", b"v00_")
    ):
        _reject()


def _validate_public_result(
    raw: bytes,
    *,
    protocol_sha256: str,
    private_receipt_sha256: str,
    aggregate: Mapping[str, int],
) -> None:
    public = _exact_keys(_load_json(raw), PUBLIC_RESULT_KEYS)
    views_nonzero = aggregate["views_with_nonzero_joint_finite_support"]
    if (
        _canonical_json_bytes(public) != raw
        or public.get("schema") != PUBLIC_RESULT_SCHEMA
        or public.get("status") != "PASS"
        or public.get("claim_scope") != CLAIM_SCOPE
        or public.get("protocol_sha256") != protocol_sha256
        or public.get("input_private_decode_receipt_sha256")
        != P1D_PRIVATE_RECEIPT_SHA256
        or public.get("private_census_receipt_sha256") != private_receipt_sha256
        or public.get("evaluated_view_count") != EXPECTED_VIEWS
        or public.get("views_with_nonzero_joint_finite_support") != views_nonzero
        or public.get("all_views_have_nonzero_joint_finite_support")
        is not (views_nonzero == EXPECTED_VIEWS)
        or any(public.get(name) is not False for name in NEGATIVE_CLAIM_KEYS)
    ):
        _reject()
    _validate_public_privacy(public, raw)
    allowed_hashes = {
        protocol_sha256,
        P1D_PRIVATE_RECEIPT_SHA256,
        private_receipt_sha256,
    }
    observed_hashes = {
        value for value in _walk_string_values(public) if _is_sha256(value)
    }
    if observed_hashes != allowed_hashes:
        _reject()


def _validate_bundle_tree(expected_fingerprint: tuple[int, ...]) -> None:
    expected_names = sorted([*_expected_output_names(), "bundle_manifest.json"])
    try:
        observed_names = sorted(os.listdir(P1D_PRIVATE_BUNDLE))
        after = P1D_PRIVATE_BUNDLE.lstat()
    except OSError:
        _reject()
    if observed_names != expected_names or _fingerprint(after) != expected_fingerprint:
        _reject()


def _validate_p1d_chain_still_committed(bundle_manifest_sha256: str) -> None:
    if (
        hashlib.sha256(
            _stable_regular_bytes(P1D_BUNDLE_MANIFEST, required_mode=0o600)
        ).hexdigest()
        != bundle_manifest_sha256
        or hashlib.sha256(
            _stable_regular_bytes(P1D_PRIVATE_RECEIPT, required_mode=0o600)
        ).hexdigest()
        != P1D_PRIVATE_RECEIPT_SHA256
    ):
        _reject()


def score() -> int:
    """Return 23 only for the frozen, independently recounted P1e chain."""

    primary = _load_frozen(
        "_bpc_tab_development_joint_support_primary_p1e_frozen",
        PRIMARY_SCORER,
        PRIMARY_SCORER_SHA256,
    )
    if primary.score() != EXPECTED_PRIMARY:
        _reject()

    p1d = _load_frozen(
        "_bpc_tab_development_complete_cycle_novel_p1d_frozen_for_p1e",
        P1D_NOVEL_SCORER,
        P1D_NOVEL_SCORER_SHA256,
    )
    if p1d.score() != EXPECTED_VIEWS:
        _reject()

    bundle_fingerprint = _validate_private_directories()
    outputs, bundle_manifest_sha256, aggregate_export = (
        _validate_p1d_receipt_and_outputs()
    )
    recomputed = _recompute_per_view_counts(outputs)
    _validate_bundle_tree(bundle_fingerprint)
    _validate_p1d_chain_still_committed(bundle_manifest_sha256)

    protocol_sha256 = hashlib.sha256(_stable_regular_bytes(PROTOCOL)).hexdigest()
    receipt_raw = _stable_regular_bytes(P1E_PRIVATE_RECEIPT, required_mode=0o600)
    _, private_receipt_sha256, aggregate = _validate_private_receipt(
        receipt_raw,
        protocol_sha256=protocol_sha256,
        bundle_manifest_sha256=bundle_manifest_sha256,
        aggregate_export=aggregate_export,
        recomputed=recomputed,
    )
    public_raw = _stable_regular_bytes(PUBLIC_RESULT, required_mode=0o444)
    _validate_public_result(
        public_raw,
        protocol_sha256=protocol_sha256,
        private_receipt_sha256=private_receipt_sha256,
        aggregate=aggregate,
    )
    return aggregate["views_with_nonzero_joint_finite_support"]


def main() -> int:
    try:
        if len(sys.argv) != 2 or not _same_fixed_path(sys.argv[1], FIXED_JUNIT):
            _reject()
        metric = score()
    except Exception:
        sys.stderr.write("E_P1E_JOINT_SUPPORT_NOVEL_REJECTED\n")
        return 2
    print(f"metric={metric}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
