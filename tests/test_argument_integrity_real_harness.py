"""Fast structural tests for the ARG-1..5 real-datastore harness runner."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from ooptdd_receipts.ARGUMENT_INTEGRITY import real_harness


def test_manifest_maps_every_locked_requirement_to_a_real_test():
    manifest = json.loads(real_harness.MANIFEST_PATH.read_text(encoding="utf-8"))
    requirements = yaml.safe_load(real_harness.REQUIREMENTS_PATH.read_text(encoding="utf-8"))
    requirement_ids = {item["id"] for item in requirements["requirements"]}

    assert set(manifest["requirements"]["ids"]) == requirement_ids
    assert set(manifest["tests"]) == requirement_ids
    assert set(manifest["tests"].values()) <= real_harness._declared_tests()
    assert manifest["tier"] == "L_IDE"
    assert manifest["judge"]["sha256"] == real_harness._sha_file(
        real_harness.TARGETED_JUDGE_PATH
    )
    assert manifest["preregistration"]["sha256"] == real_harness._sha_file(
        real_harness.PREREG_PATH
    )


def test_junit_evaluator_distinguishes_green_semantic_red_and_infra_error(tmp_path):
    manifest = json.loads(real_harness.MANIFEST_PATH.read_text(encoding="utf-8"))
    names = list(manifest["tests"].values())

    def write_junit(path: Path, statuses: dict[str, str]):
        cases = []
        for name in names:
            child = "" if statuses[name] == "passed" else f"<{statuses[name]}/>"
            cases.append(f'<testcase classname="argument" name="{name}">{child}</testcase>')
        path.write_text("<testsuites><testsuite>" + "".join(cases) + "</testsuite></testsuites>")

    green_path = tmp_path / "green.xml"
    write_junit(green_path, {name: "passed" for name in names})
    green = real_harness.evaluate_junit(real_harness.parse_junit(green_path), manifest, expected="GREEN")
    assert green["accepted"] and green["observed"] == "GREEN"

    red_statuses = {name: "passed" for name in names}
    for name in manifest["negative_control"]["required_failed_tests"]:
        red_statuses[name] = "failure"
    red_path = tmp_path / "red.xml"
    write_junit(red_path, red_statuses)
    red = real_harness.evaluate_junit(real_harness.parse_junit(red_path), manifest, expected="RED")
    assert red["accepted"] and red["observed"] == "RED" and red["execution_ok"]

    error_path = tmp_path / "error.xml"
    error_statuses = dict(red_statuses)
    error_statuses[names[-1]] = "error"
    write_junit(error_path, error_statuses)
    invalid = real_harness.evaluate_junit(
        real_harness.parse_junit(error_path), manifest, expected="RED"
    )
    assert not invalid["accepted"] and not invalid["execution_ok"]


def test_targeted_arg5_evaluator_accepts_assertion_and_rejects_poolerror(tmp_path):
    manifest = json.loads(real_harness.MANIFEST_PATH.read_text(encoding="utf-8"))
    control = manifest["targeted_negative_control"]
    name = control["selected_tests"][0]

    assertion_path = tmp_path / "assertion.xml"
    assertion_path.write_text(
        '<testsuites><testsuite><testcase classname="argument" '
        f'name="{name}"><failure message="AssertionError: ownership"/>'
        "</testcase></testsuite></testsuites>"
    )
    accepted = real_harness.evaluate_junit(
        real_harness.parse_junit(assertion_path),
        manifest,
        expected="RED",
        required_tests=control["selected_tests"],
        negative_control=control,
    )
    assert accepted["accepted"] and accepted["observed"] == "RED"
    assert accepted["infra_failures"] == []

    pool_path = tmp_path / "pool.xml"
    pool_path.write_text(
        '<testsuites><testsuite><testcase classname="argument" '
        f'name="{name}"><failure message="psycopg2.pool.PoolError: exhausted"/>'
        "</testcase></testsuite></testsuites>"
    )
    rejected = real_harness.evaluate_junit(
        real_harness.parse_junit(pool_path),
        manifest,
        expected="RED",
        required_tests=control["selected_tests"],
        negative_control=control,
    )
    assert not rejected["accepted"] and rejected["observed"] == "INVALID"
    assert rejected["infra_failures"] == [name]
    assert rejected["required_detail_mismatches"] == [name]


def test_arg5_mutation_is_exact_once_and_never_touches_canonical_source(tmp_path):
    source = tmp_path / "evidence_claim_service.py"
    original = real_harness.SERVICE_PATH.read_bytes()
    source.write_bytes(original)

    receipt = real_harness.apply_arg5_claim_mutation(
        source,
        expected_preimage_sha256=hashlib.sha256(original).hexdigest(),
    )

    assert receipt["replacements"] == 1
    assert receipt["marker_removed"] is True
    assert receipt["source_after_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert real_harness._ARG5_CLAIM_MARKER not in source.read_text(encoding="utf-8")
    assert hashlib.sha256(real_harness.SERVICE_PATH.read_bytes()).hexdigest() == receipt[
        "source_before_sha256"
    ]


def test_bundle_manifest_hashes_every_artifact_except_itself(tmp_path):
    (tmp_path / "positive.json").write_text('{"ok":true}\n')
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "evidence.xml").write_text("<ok/>")

    payload = real_harness.write_bundle_manifest(tmp_path)

    assert [item["path"] for item in payload["files"]] == [
        "nested/evidence.xml",
        "positive.json",
    ]
    assert all(len(item["sha256"]) == 64 and item["bytes"] > 0 for item in payload["files"])
    assert (tmp_path / "bundle_manifest.json").is_file()
