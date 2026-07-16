#!/usr/bin/env python3
"""Score the sealed P1f one-percent joint-support secondary analysis.

The novel metric is the honest 0..23 count of P1e development views whose
joint-finite XYZ/SNR support reaches the exact integer floor of 50,136 pixels.
The frozen P1e novel judge first replays all 46 decoded arrays and validates its
private receipt.  This judge then securely reopens that receipt, derives the
threshold classifications, validates the P1f private/public chain, and finally
rechecks the P1e receipt.  No per-view value reaches stdout or an error string.
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
P1E_PRIVATE_ROOT = Path("/data/kjra/PROJECT/3DLAB/.private_bpc_p1e")
P1F_PRIVATE_ROOT = Path("/data/kjra/PROJECT/3DLAB/.private_bpc_p1f")

PRIMARY_SCORER = LAKATO_ROOT / (
    "scripts/judge_bpc_tab_development_joint_support_1pct_p1f_20260714.py"
)
NOVEL_SCORER = Path(__file__).absolute()
P1E_NOVEL_SCORER = LAKATO_ROOT / (
    "scripts/judge_bpc_tab_development_joint_support_novel_p1e_20260714.py"
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

PRIMARY_SCORER_SHA256 = (
    "76f92bce8757f654c72e4b529d20fb46fe0d7e0fb031e82d90eb8ecf31de3f84"
)
P1E_NOVEL_SCORER_SHA256 = (
    "3650aca875c5d0aae147ec7a4aef43fed61b1481ece6285f884726a0f9701c61"
)
P1E_PRIVATE_RECEIPT_SHA256 = (
    "a3b035a7a44f9124d24c6f54886f4d2781e62110ee1c7d7d68da1cdaed666ee0"
)
P1D_PRIVATE_RECEIPT_SHA256 = (
    "a30067e64a1dafb9b19d3762c49c09a4f4e8edd98555b35f293ad9c074128685"
)

CLAIM_SCOPE = "ACTUAL_DEVELOPMENT_DECODED_CYCLE_JOINT_SUPPORT_1PCT_THRESHOLD_ONLY"
PRIVATE_RECEIPT_SCHEMA = (
    "bpc.tab_bolt.development_joint_support_1pct_private_receipt.v1"
)
PUBLIC_RESULT_SCHEMA = "bpc.tab_bolt.development_joint_support_1pct_result.v1"
P1E_CLAIM_SCOPE = "ACTUAL_DEVELOPMENT_DECODED_CYCLE_JOINT_SUPPORT_CENSUS_ONLY"
P1E_PRIVATE_RECEIPT_SCHEMA = (
    "bpc.tab_bolt.development_decoded_cycle_joint_support_private_receipt.v1"
)
P1E_COUNT_COMMITMENT_DOMAIN = (
    "BPC_TAB_BOLT_DEVELOPMENT_DECODED_CYCLE_JOINT_SUPPORT_COUNTS_V1"
)

EXPECTED_PRIMARY = 9
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


class ScoreRejected(RuntimeError):
    """Fail closed without echoing private paths, counts, or commitments."""


def _reject() -> None:
    raise ScoreRejected("E_P1F_JOINT_SUPPORT_1PCT_NOVEL_REJECTED")


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


def _validate_p1e_receipt(
    raw: bytes,
) -> tuple[list[dict[str, Any]], str]:
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


def _validate_p1f_outputs(
    *,
    protocol_sha256: str,
    p1e_records: Sequence[Mapping[str, Any]],
    p1e_count_commitment: str,
) -> int:
    derived, views_meeting = _derive_threshold_records(p1e_records)
    private_raw = _stable_regular_bytes(P1F_PRIVATE_RECEIPT, required_mode=0o600)
    receipt = _exact_keys(_load_json(private_raw), PRIVATE_RECEIPT_KEYS)
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
    return views_meeting


def _recheck_private_inputs(
    p1e_raw: bytes,
    root_fingerprints: tuple[tuple[int, ...], tuple[int, ...]],
) -> None:
    if (
        _stable_regular_bytes(P1E_PRIVATE_RECEIPT, required_mode=0o600) != p1e_raw
        or _validate_private_roots() != root_fingerprints
    ):
        _reject()


def score() -> int:
    """Return the honest 0..23 count after replay and sealed revalidation."""

    primary = _load_frozen(
        "_bpc_tab_development_joint_support_1pct_primary_p1f_frozen",
        PRIMARY_SCORER,
        PRIMARY_SCORER_SHA256,
    )
    if primary.score() != EXPECTED_PRIMARY:
        _reject()

    p1e = _load_frozen(
        "_bpc_tab_development_joint_support_novel_p1e_frozen_for_p1f",
        P1E_NOVEL_SCORER,
        P1E_NOVEL_SCORER_SHA256,
    )
    if p1e.score() != EXPECTED_VIEWS:
        _reject()

    root_fingerprints = _validate_private_roots()
    p1e_raw = _stable_regular_bytes(P1E_PRIVATE_RECEIPT, required_mode=0o600)
    p1e_records, p1e_count_commitment = _validate_p1e_receipt(p1e_raw)
    protocol_sha256 = hashlib.sha256(_stable_regular_bytes(PROTOCOL)).hexdigest()
    views_meeting = _validate_p1f_outputs(
        protocol_sha256=protocol_sha256,
        p1e_records=p1e_records,
        p1e_count_commitment=p1e_count_commitment,
    )
    _recheck_private_inputs(p1e_raw, root_fingerprints)
    return views_meeting


def main() -> int:
    try:
        if len(sys.argv) != 2 or not _same_fixed_path(sys.argv[1], FIXED_JUNIT):
            _reject()
        metric = score()
    except Exception:
        sys.stderr.write("E_P1F_JOINT_SUPPORT_1PCT_NOVEL_REJECTED\n")
        return 2
    print(f"metric={metric}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
