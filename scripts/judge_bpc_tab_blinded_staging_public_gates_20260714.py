#!/usr/bin/env python3
"""Score the frozen BPC custodian-side public handoff conformance JUnit."""

from __future__ import annotations

import hashlib
from pathlib import Path
import stat
import sys
import xml.etree.ElementTree as ET


BPC_ROOT = Path("/data/kjra/PROJECT/3DLAB/BPC_ICP_SPEC")
FROZEN_SOURCES = {
    BPC_ROOT / "scripts/tab_bolt_blinded_staging_verifier.py": (
        "fe2322ef88e662f6ca725ad84883f11c7df21a97b7430f76f0ebfeead1c0dc9a"
    ),
    BPC_ROOT / "tests/test_tab_bolt_blinded_staging_verifier.py": (
        "198d4ce13fad5a7033a0a3a508d8298485b7c02287bbae0586b2273d0290c3ba"
    ),
}
CLASSNAME = "tests.test_tab_bolt_blinded_staging_verifier"
TEST_NAMES = frozenset(
    {
        "test_accepts_valid_geometry_only_bundle",
        "test_rejects_non_bijective_private_key",
        "test_rejects_path_traversal",
        "test_rejects_symlink_artifact",
        "test_rejects_missing_view",
        "test_rejects_color_or_metadata_artifact",
        "test_rejects_artifact_hash_drift",
        "test_rejects_unexpected_file",
        "test_rejects_unsafe_npy",
        "test_rejects_sensitive_token_in_geometry_bytes",
        "test_rejects_manifest_hash_drift",
        "test_rejects_duplicate_json_key",
        "test_rejects_mutated_committed_skeleton",
    }
)
MAX_RESULT_BYTES = 8 * 1024 * 1024


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _count(suite: ET.Element, name: str) -> int:
    value = suite.get(name)
    if value is None or not value.isascii() or not value.isdigit():
        raise RuntimeError(f"JUnit suite lacks integer {name}")
    return int(value)


def _load_exact_junit(path: Path) -> list[ET.Element]:
    if path.is_symlink():
        raise RuntimeError("JUnit result symlink is forbidden")
    status = path.stat()
    if not stat.S_ISREG(status.st_mode) or not 0 < status.st_size <= MAX_RESULT_BYTES:
        raise RuntimeError("JUnit result must be a non-empty regular file <= 8 MiB")
    raw = path.read_bytes()
    lowered = raw.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise RuntimeError("DTD/entity declarations are forbidden")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise RuntimeError(f"invalid JUnit XML: {exc}") from exc
    if root.tag != "testsuites" or any(child.tag != "testsuite" for child in root):
        raise RuntimeError("expected one non-namespaced testsuites root")
    suites = list(root)
    if len(suites) != 1:
        raise RuntimeError("exactly one testsuite is required")
    suite = suites[0]
    counts = {
        name: _count(suite, name) for name in ("tests", "errors", "failures", "skipped")
    }
    if counts != {"tests": 13, "errors": 0, "failures": 0, "skipped": 0}:
        raise RuntimeError(
            f"JUnit aggregate is not the frozen all-green denominator: {counts}"
        )
    cases = list(suite)
    if len(cases) != 13 or any(case.tag != "testcase" for case in cases):
        raise RuntimeError("testsuite must contain exactly 13 testcase elements")
    names = [case.get("name") for case in cases]
    if (
        len(set(names)) != 13
        or set(names) != TEST_NAMES
        or any(case.get("classname") != CLASSNAME for case in cases)
        or any(list(case) for case in cases)
    ):
        raise RuntimeError("testcase inventory, classname, or all-green state drifted")
    return cases


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit(
            "usage: judge_bpc_tab_blinded_staging_public_gates_20260714.py RESULT.xml"
        )
    for path, expected in FROZEN_SOURCES.items():
        if _sha256(path) != expected:
            raise RuntimeError(f"frozen BPC source hash mismatch: {path}")
    cases = _load_exact_junit(Path(sys.argv[1]))
    print(f"metric={len(cases)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
