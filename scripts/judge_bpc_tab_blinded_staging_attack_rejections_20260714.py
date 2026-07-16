#!/usr/bin/env python3
"""Independently score frozen BPC fail-closed attack rejections from JUnit."""

from __future__ import annotations

import hashlib
from pathlib import Path
import stat
import sys
from xml.dom import minidom


VERIFIER = Path(
    "/data/kjra/PROJECT/3DLAB/BPC_ICP_SPEC/scripts/tab_bolt_blinded_staging_verifier.py"
)
TEST_MODULE = Path(
    "/data/kjra/PROJECT/3DLAB/BPC_ICP_SPEC/tests/"
    "test_tab_bolt_blinded_staging_verifier.py"
)
VERIFIER_SHA256 = "fe2322ef88e662f6ca725ad84883f11c7df21a97b7430f76f0ebfeead1c0dc9a"
TEST_MODULE_SHA256 = "198d4ce13fad5a7033a0a3a508d8298485b7c02287bbae0586b2273d0290c3ba"
CLASSNAME = "tests.test_tab_bolt_blinded_staging_verifier"
POSITIVE_NAME = "test_accepts_valid_geometry_only_bundle"
ATTACK_NAMES = frozenset(
    {
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


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _elements(node: minidom.Node) -> list[minidom.Element]:
    return [
        child
        for child in node.childNodes
        if child.nodeType == minidom.Node.ELEMENT_NODE
    ]


def _integer_attribute(node: minidom.Element, name: str) -> int:
    value = node.getAttribute(name)
    if not value or not value.isascii() or not value.isdigit():
        raise RuntimeError(f"JUnit suite lacks integer {name}")
    return int(value)


def _attack_count(path: Path) -> int:
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
        document = minidom.parseString(raw)
    except Exception as exc:
        raise RuntimeError(f"invalid JUnit XML: {exc}") from exc
    root = document.documentElement
    if root.tagName != "testsuites" or root.namespaceURI is not None:
        raise RuntimeError("expected non-namespaced testsuites root")
    suites = _elements(root)
    if len(suites) != 1 or suites[0].tagName != "testsuite":
        raise RuntimeError("exactly one testsuite is required")
    suite = suites[0]
    aggregate = {
        key: _integer_attribute(suite, key)
        for key in ("tests", "errors", "failures", "skipped")
    }
    if aggregate != {"tests": 13, "errors": 0, "failures": 0, "skipped": 0}:
        raise RuntimeError(
            f"JUnit aggregate is not the frozen all-green denominator: {aggregate}"
        )
    cases = _elements(suite)
    if len(cases) != 13 or any(case.tagName != "testcase" for case in cases):
        raise RuntimeError("testsuite must contain exactly 13 testcase elements")
    names: list[str] = []
    for case in cases:
        if case.getAttribute("classname") != CLASSNAME or _elements(case):
            raise RuntimeError("testcase classname or all-green state drifted")
        names.append(case.getAttribute("name"))
    expected = ATTACK_NAMES | {POSITIVE_NAME}
    if len(set(names)) != 13 or set(names) != expected:
        raise RuntimeError("testcase inventory drifted")
    return sum(name in ATTACK_NAMES for name in names)


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit(
            "usage: judge_bpc_tab_blinded_staging_attack_rejections_20260714.py RESULT.xml"
        )
    if (
        _digest(VERIFIER) != VERIFIER_SHA256
        or _digest(TEST_MODULE) != TEST_MODULE_SHA256
    ):
        raise RuntimeError("frozen BPC verifier/test source hash mismatch")
    count = _attack_count(Path(sys.argv[1]))
    if count != 12:
        raise RuntimeError(f"expected 12 fail-closed attack tests, found {count}")
    print(f"metric={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
