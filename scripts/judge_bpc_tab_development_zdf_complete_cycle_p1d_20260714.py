#!/usr/bin/env python3
"""Score the frozen P1d 23-view development-cycle conformance gates.

The primary metric is the exact twelve-case JUnit denominator.  This judge is
static with respect to Zivid and NumPy: it verifies frozen source commitments,
the private cycle-manifest commitment, the preregistration contract, and the
JUnit artifact, but it never imports the exporter or opens an array/ZDF.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any, Iterable
import xml.etree.ElementTree as ET


BPC_ROOT = Path("/data/kjra/PROJECT/3DLAB/BPC_ICP_SPEC")
LAKATO_ROOT = Path("/data/kjra/PROJECT/PI/lakatotree")
PRIVATE_ROOT = Path("/data/kjra/PROJECT/3DLAB/.private_bpc_p1d")

MANIFEST_GENERATOR = BPC_ROOT / "scripts/tab_bolt_development_zdf_cycle_manifest.py"
EXPORTER = BPC_ROOT / "scripts/tab_bolt_development_zdf_cycle_export.py"
P1B_STAGER = BPC_ROOT / "scripts/tab_bolt_atomic_decoded_source_stager.py"
TEST_MODULE = BPC_ROOT / "tests/test_tab_bolt_development_zdf_cycle_export.py"
PRIMARY_SCORER = Path(__file__).absolute()
NOVEL_SCORER = LAKATO_ROOT / (
    "scripts/judge_bpc_tab_development_zdf_complete_cycle_novel_p1d_20260714.py"
)
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
PRIVATE_RECEIPT = PRIVATE_ROOT / (
    "bpc_tab_bolt_development_zdf_cycle_decode_private_receipt_20260714.json"
)

MANIFEST_GENERATOR_SHA256 = (
    "0c24bcb4638cba044141e4c1c880e532559aca57eafa51afa22ca4e885cd56a4"
)
EXPORTER_SHA256 = "adf66b5853c84f82fc7a6b77d22a7b76135cb4023576682a7cf29ecf40318c30"
P1B_STAGER_SHA256 = "b233ccade2ae58c88da794b4f6808b6f3d8c001c35818bbe7c3ab3e4abdb8f2d"
TEST_MODULE_SHA256 = "69508db580400ed4ec7f88fe57d47f613a93085b866e2a19ff27474835696341"
CYCLE_MANIFEST_SHA256 = (
    "52319e2b424a5784c5bcfc60431fd812966414ab5901590bf53cd353443eddfe"
)

PROTOCOL_SCHEMA = "bpc.tab_bolt.development_zdf_cycle_decode_preregistration.v1"
PROTOCOL_STATUS = "PREREGISTERED_P1D_COMPLETE_CYCLE_RESULT_ABSENT"
CLAIM_SCOPE = "ACTUAL_DEVELOPMENT_23VIEW_PRIVATE_DECODE_EXPORT_ONLY"
TREE = "LakatosTree_BPC_TabBolt_Inference_20260701"
QUESTION = "q_bpc_development_zdf_complete_23view_private_decode_export_20260714"
NODE_TAG = "tab_development_zdf_complete_23view_private_decode_p1d_20260714"
PARENT_NODE = "tab_development_zdf_application_initialized_decode_r3_20260714"
PRIMARY_METRIC = "development_zdf_cycle_decode_export_conformance_gate_count"
NOVEL_METRIC = "actual_development_zdf_decoded_view_count"
VIEW_INDEX_SEMANTICS = "FILENAME_DERIVED_DEVELOPMENT_INDEX_ONLY"
EXPECTED_TOTAL = 12
EXPECTED_VIEWS = 23
EXPECTED_ARRAYS = 46
CLASSNAME = "tests.test_tab_bolt_development_zdf_cycle_export"
TEST_NAMES = frozenset(
    {
        "test_fake_twenty_three_source_cycle_manifest_is_indexed_and_committed",
        "test_manifest_rejects_missing_or_duplicate_view_index",
        "test_manifest_rejects_duplicate_source_identity",
        "test_manifest_rejects_symlink_or_hardlink_sources",
        "test_manifest_rejects_anchor_or_source_commitment_mismatch",
        "test_export_rejects_source_mutation_and_cleans_scratch",
        "test_fake_decoder_exports_exact_twenty_three_organized_xyz_snr_pairs",
        "test_export_rejects_missing_snr_or_array_contract_drift",
        "test_export_never_clobbers_existing_targets",
        "test_public_result_omits_identity_payload_and_overclaims",
        "test_p1b_stager_rejects_development_scope_before_payload_staging",
        "test_committed_actual_development_cycle_decodes_and_exports_twenty_three_views",
    }
)
MAX_SMALL_FILE_BYTES = 16 * 1024 * 1024


class ScoreRejected(RuntimeError):
    """Fail closed without echoing private identities or paths."""


def _reject() -> None:
    raise ScoreRejected("E_P1D_COMPLETE_CYCLE_PRIMARY_REJECTED")


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


def _verify_assets() -> None:
    expected = (
        (MANIFEST_GENERATOR, MANIFEST_GENERATOR_SHA256),
        (EXPORTER, EXPORTER_SHA256),
        (P1B_STAGER, P1B_STAGER_SHA256),
        (TEST_MODULE, TEST_MODULE_SHA256),
    )
    for path, committed in expected:
        if hashlib.sha256(_stable_regular_bytes(path)).hexdigest() != committed:
            _reject()
    if (
        hashlib.sha256(
            _stable_regular_bytes(CYCLE_MANIFEST, required_mode=0o600)
        ).hexdigest()
        != CYCLE_MANIFEST_SHA256
    ):
        _reject()


def _validate_scope_boundaries(protocol: dict[str, Any]) -> None:
    boundaries = protocol.get("scope_boundaries")
    false_claims = (
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
    if type(boundaries) is not dict or (
        boundaries.get("development_view_index_semantics") != VIEW_INDEX_SEMANTICS
        or boundaries.get("development_view_count") != EXPECTED_VIEWS
        or boundaries.get("private_export_array_count") != EXPECTED_ARRAYS
        or any(boundaries.get(name) is not False for name in false_claims)
    ):
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
        or protocol.get("production_change") is not False
        or protocol.get("static_preflight_only") is not True
    ):
        _reject()
    _validate_scope_boundaries(protocol)

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
        or not 0 < credence <= 1
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
        or inventory.get("actual_private_cycle_cases") != 1
    ):
        _reject()

    strings = set(_walk_string_values(protocol))
    required_hashes = {
        MANIFEST_GENERATOR_SHA256,
        EXPORTER_SHA256,
        P1B_STAGER_SHA256,
        TEST_MODULE_SHA256,
        CYCLE_MANIFEST_SHA256,
        hashlib.sha256(_stable_regular_bytes(PRIMARY_SCORER)).hexdigest(),
        hashlib.sha256(_stable_regular_bytes(NOVEL_SCORER)).hexdigest(),
    }
    required_paths = {
        str(MANIFEST_GENERATOR),
        str(EXPORTER),
        str(P1B_STAGER),
        str(TEST_MODULE),
        str(PRIMARY_SCORER),
        str(NOVEL_SCORER),
        str(PROTOCOL),
        str(PUBLIC_RESULT),
        str(FIXED_JUNIT),
        str(CYCLE_MANIFEST),
        str(FIXED_SCRATCH),
        str(PRIVATE_BUNDLE),
        str(PRIVATE_RECEIPT),
    }
    if not required_hashes.issubset(strings) or not required_paths.issubset(strings):
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
    """Return twelve only for the complete frozen P1d conformance chain."""

    _verify_assets()
    _validate_private_root_and_scratch()
    _validate_protocol(_load_json(_stable_regular_bytes(PROTOCOL)))
    return _score_junit()


def main() -> int:
    try:
        if len(sys.argv) != 2 or not _same_fixed_path(sys.argv[1], FIXED_JUNIT):
            _reject()
        metric = score()
    except Exception:
        sys.stderr.write("E_P1D_COMPLETE_CYCLE_PRIMARY_REJECTED\n")
        return 2
    print(f"metric={metric}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
