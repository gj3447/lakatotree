"""Fast structural tests for the ARG-1..5 real-datastore harness runner."""
from __future__ import annotations

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
