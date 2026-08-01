#!/usr/bin/env python3
"""Capture ARG-1..5 real-datastore positive/negative/restored evidence.

The negative control is an archived historical revision.  The canonical worktree is
never patched, checked out, or used as a datastore target.  All database endpoints are
created by testcontainers inside the integration fixture.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
MANIFEST_PATH = HERE / "harness.json"
TEST_PATH = REPO / "tests/integration/test_argument_integrity_real_neo4j.py"
CONFTEST_PATH = REPO / "tests/integration/conftest.py"
SERVICE_PATH = REPO / "server/contexts/tree/evidence_claim_service.py"
REQUIREMENTS_PATH = HERE / "requirements.yaml"
PREREG_PATH = HERE / "prereg_arg5_semantic_negative_20260801.json"
TARGETED_JUDGE_PATH = REPO / "judges/arg5_targeted_negative_oracle.py"

_ARG5_CLAIM_MARKER = (
    "ON CREATE SET a:LakatosArgument, a._argument_create_claim=$create_claim,\n"
)
_ARG5_CLAIM_REPLACEMENT = "ON CREATE SET a:LakatosArgument,\n"

_DATASTORE_ENV_KEYS = (
    "NEO4J_URI",
    "NEO4J_USER",
    "NEO4J_PASSWORD",
    "DATABASE_URL",
    "POSTGRES_HOST",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "MONGO_URI",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha_file(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as tmp:
        tmp.write(encoded)
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, path)


def _git(*args: str, cwd: Path = REPO, text: bool = True):
    return subprocess.check_output(["git", *args], cwd=cwd, text=text)


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _declared_tests() -> set[str]:
    tree = ast.parse(TEST_PATH.read_text(encoding="utf-8"))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
    }


def _docker_probe(image_names: list[str] | None = None) -> dict:
    report: dict[str, Any] = {"reachable": False, "server_version": None, "images": {}}
    try:
        import docker

        client = docker.from_env()
        try:
            report["reachable"] = bool(client.ping())
            version = client.version()
            report["server_version"] = version.get("Version")
            for image_name in image_names or []:
                try:
                    image = client.images.get(image_name)
                except docker.errors.ImageNotFound:
                    report["images"][image_name] = {"present": False, "repo_digests": []}
                else:
                    report["images"][image_name] = {
                        "present": True,
                        "id": image.id,
                        "repo_digests": sorted(image.attrs.get("RepoDigests") or []),
                    }
        finally:
            client.close()
    except Exception as exc:  # noqa: BLE001 - preflight reports the typed boundary without secrets
        report["error"] = type(exc).__name__
    return report


def preflight(manifest: dict) -> dict:
    checks: dict[str, Any] = {}
    for package in ("testcontainers", "docker", "neo4j", "psycopg2-binary"):
        checks[f"package:{package}"] = _package_version(package)

    declared = set(manifest["tests"].values())
    discovered = _declared_tests()
    checks["declared_tests_present"] = declared <= discovered
    checks["declared_test_count"] = len(declared)

    negative = manifest["negative_control"]
    try:
        old_source = _git(
            "show",
            f"{negative['revision']}:{manifest['system_under_test']['source']}",
            text=False,
        )
        checks["negative_revision_present"] = True
        checks["negative_source_sha256"] = _sha_bytes(old_source)
        checks["negative_source_matches_manifest"] = (
            checks["negative_source_sha256"] == negative["service_sha256"]
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        checks["negative_revision_present"] = False
        checks["negative_source_matches_manifest"] = False

    docker_report = _docker_probe()
    checks["docker_reachable"] = docker_report.get("reachable", False)
    try:
        prereg = json.loads(PREREG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        prereg = {}
    checks["prereg_experiment_id"] = (
        prereg.get("experiment_id")
        == "ARG5_TARGETED_CLAIM_OWNERSHIP_SEMANTIC_NEGATIVE_20260801"
    )
    checks["prereg_judge_sha256"] = (
        prereg.get("judge", {}).get("sha256")
        == (_sha_file(TARGETED_JUDGE_PATH) if TARGETED_JUDGE_PATH.is_file() else None)
    )
    checks["manifest_prereg_sha256"] = (
        manifest.get("preregistration", {}).get("sha256")
        == (_sha_file(PREREG_PATH) if PREREG_PATH.is_file() else None)
    )
    checks["manifest_judge_sha256"] = (
        manifest.get("judge", {}).get("sha256")
        == (_sha_file(TARGETED_JUDGE_PATH) if TARGETED_JUDGE_PATH.is_file() else None)
    )
    checks["prereg_service_preimage_sha256"] = (
        prereg.get("base", {}).get("service_sha256")
        == (_sha_file(SERVICE_PATH) if SERVICE_PATH.is_file() else None)
    )
    checks["arg5_mutation_marker_count"] = (
        SERVICE_PATH.read_text(encoding="utf-8").count(_ARG5_CLAIM_MARKER)
        if SERVICE_PATH.is_file()
        else 0
    )
    checks["required_files_present"] = all(
        path.is_file()
        for path in (
            MANIFEST_PATH,
            TEST_PATH,
            CONFTEST_PATH,
            SERVICE_PATH,
            REQUIREMENTS_PATH,
            PREREG_PATH,
            TARGETED_JUDGE_PATH,
        )
    )
    ready = all(
        (
            checks["package:testcontainers"],
            checks["package:docker"],
            checks["package:neo4j"],
            checks["package:psycopg2-binary"],
            checks["declared_tests_present"],
            checks["negative_revision_present"],
            checks["negative_source_matches_manifest"],
            checks["docker_reachable"],
            checks["required_files_present"],
            checks["prereg_experiment_id"],
            checks["prereg_judge_sha256"],
            checks["manifest_prereg_sha256"],
            checks["manifest_judge_sha256"],
            checks["prereg_service_preimage_sha256"],
            checks["arg5_mutation_marker_count"] == 1,
        )
    )
    return {"ready": bool(ready), "checks": checks, "docker": docker_report}


def parse_junit(path: Path) -> dict:
    if not path.is_file():
        return {"present": False, "tests": 0, "passed": 0, "failed": 0,
                "errors": 0, "skipped": 0, "cases": []}
    root = ET.parse(path).getroot()
    cases = []
    for case in root.iter("testcase"):
        status = "passed"
        detail = None
        for child_name, child_status in (("failure", "failed"), ("error", "error"),
                                         ("skipped", "skipped")):
            child = case.find(child_name)
            if child is not None:
                status = child_status
                detail = (child.get("message") or child.text or "")[:500]
                break
        cases.append({
            "name": case.get("name", ""),
            "classname": case.get("classname", ""),
            "status": status,
            "detail": detail,
            "failure_type": child.get("type") if detail is not None else None,
        })
    counts = {
        "passed": sum(case["status"] == "passed" for case in cases),
        "failed": sum(case["status"] == "failed" for case in cases),
        "errors": sum(case["status"] == "error" for case in cases),
        "skipped": sum(case["status"] == "skipped" for case in cases),
    }
    return {"present": True, "tests": len(cases), **counts, "cases": cases}


def evaluate_junit(
    summary: dict,
    manifest: dict,
    *,
    expected: str,
    required_tests: list[str] | None = None,
    negative_control: dict | None = None,
) -> dict:
    by_name = {case["name"]: case["status"] for case in summary["cases"]}
    by_case = {case["name"]: case for case in summary["cases"]}
    required = set(required_tests or manifest["tests"].values())
    missing = sorted(required.difference(by_name))
    semantic_failures: set[str] = set()
    infra_failures: list[str] = []
    unexpected_failures: list[str] = []
    required_detail_mismatches: list[str] = []
    if expected == "GREEN":
        accepted = (
            not missing
            and all(by_name[name] == "passed" for name in required)
            and set(by_name) == required
            and summary["failed"] == summary["errors"] == summary["skipped"] == 0
        )
        observed = "GREEN" if accepted else "RED"
        execution_ok = summary["present"] and not missing and summary["errors"] == 0
    else:
        control = negative_control or manifest["negative_control"]
        required_failures = set(control["required_failed_tests"])
        semantic_failures = {name for name, status in by_name.items() if status == "failed"}
        unexpected_failures = sorted(semantic_failures.difference(required_failures))
        forbidden = tuple(control.get("forbidden_failure_markers") or ())
        for name in sorted(semantic_failures):
            detail = str((by_case.get(name) or {}).get("detail") or "")
            if any(marker in detail for marker in forbidden):
                infra_failures.append(name)
        for name, markers in (control.get("required_failure_markers") or {}).items():
            detail = str((by_case.get(name) or {}).get("detail") or "")
            if not all(marker in detail for marker in markers):
                required_detail_mismatches.append(name)
        accepted = (
            not missing
            and set(by_name) == required
            and semantic_failures == required_failures
            and not infra_failures
            and not required_detail_mismatches
            and summary["errors"] == summary["skipped"] == 0
        )
        observed = "RED" if semantic_failures and not infra_failures else "INVALID"
        execution_ok = (
            summary["present"]
            and not missing
            and summary["errors"] == 0
            and not infra_failures
        )
    return {
        "accepted": bool(accepted),
        "expected": expected,
        "observed": observed,
        "execution_ok": bool(execution_ok),
        "missing_tests": missing,
        "semantic_failures": sorted(semantic_failures),
        "infra_failures": infra_failures,
        "unexpected_failures": unexpected_failures,
        "required_detail_mismatches": required_detail_mismatches,
    }


def _sanitized_tail(text: str, cwd: Path, limit: int = 4000) -> str:
    return text.replace(str(cwd), ".").replace(str(REPO), ".")[-limit:]


def run_pytest(
    *,
    python: str,
    cwd: Path,
    test_path: Path,
    junit_path: Path,
    timeout: int,
    phase: str,
    source_revision: str,
    source_sha256: str,
    manifest: dict,
    expected: str,
    selected_tests: list[str] | None = None,
    negative_control: dict | None = None,
) -> dict:
    relative_test = test_path.relative_to(cwd)
    targets = (
        [f"{relative_test}::{name}" for name in selected_tests]
        if selected_tests
        else [str(relative_test)]
    )
    command = [
        python,
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        *targets,
        f"--junitxml={junit_path}",
    ]
    env = os.environ.copy()
    for key in _DATASTORE_ENV_KEYS:
        env.pop(key, None)
    env.update({
        "LAKATOS_IT": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONPATH": str(cwd),
    })
    started = time.monotonic()
    timed_out = False
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        exit_code = completed.returncode
        output = completed.stdout + completed.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = None
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        output = stdout + stderr
    duration = round(time.monotonic() - started, 3)
    junit = parse_junit(junit_path)
    evaluation = evaluate_junit(
        junit,
        manifest,
        expected=expected,
        required_tests=selected_tests,
        negative_control=negative_control,
    )
    if timed_out:
        evaluation.update({"accepted": False, "observed": "INVALID", "execution_ok": False})
    return {
        "schema_version": "lakatotree-requirements-harness-run/v1",
        "phase": phase,
        "expected": expected,
        "observed": evaluation["observed"],
        "accepted": evaluation["accepted"],
        "execution_ok": evaluation["execution_ok"],
        "source_revision": source_revision,
        "source_sha256": source_sha256,
        "command": command,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "duration_seconds": duration,
        "output_sha256": _sha_bytes(output.encode()),
        "output_tail": _sanitized_tail(output, cwd),
        "junit": junit,
        "junit_path": junit_path.name,
        "junit_sha256": _sha_file(junit_path) if junit_path.is_file() else None,
        "missing_tests": evaluation["missing_tests"],
        "semantic_failures": evaluation["semantic_failures"],
        "infra_failures": evaluation["infra_failures"],
        "unexpected_failures": evaluation["unexpected_failures"],
        "required_detail_mismatches": evaluation["required_detail_mismatches"],
        "canonical_worktree_mutated": False,
    }


def archive_revision(revision: str, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    archive_path = destination.parent / f"{revision}.tar"
    subprocess.run(
        ["git", "archive", "--format=tar", "--output", str(archive_path), revision],
        cwd=REPO,
        check=True,
    )
    with tarfile.open(archive_path) as archive:
        archive.extractall(destination)  # trusted objects from this repository's own Git history
    archive_path.unlink()
    target_dir = destination / "tests/integration"
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TEST_PATH, target_dir / TEST_PATH.name)
    shutil.copy2(CONFTEST_PATH, target_dir / CONFTEST_PATH.name)


def apply_arg5_claim_mutation(source_path: Path, *, expected_preimage_sha256: str) -> dict:
    """Remove only the ARG-5 ON CREATE ownership marker in an archived source tree."""
    before = source_path.read_text(encoding="utf-8")
    before_sha = _sha_bytes(before.encode())
    if before_sha != expected_preimage_sha256:
        raise ValueError(
            "ARG-5 mutation preimage drift: "
            f"expected {expected_preimage_sha256}, got {before_sha}"
        )
    replacements = before.count(_ARG5_CLAIM_MARKER)
    if replacements != 1:
        raise ValueError(f"ARG-5 mutation marker count must be 1, got {replacements}")
    after = before.replace(_ARG5_CLAIM_MARKER, _ARG5_CLAIM_REPLACEMENT, 1)
    if _ARG5_CLAIM_MARKER in after:
        raise ValueError("ARG-5 mutation marker survived exact replacement")
    source_path.write_text(after, encoding="utf-8")
    return {
        "schema_version": "lakatotree-targeted-source-mutation/v1",
        "mutation_id": "arg5-remove-on-create-claim",
        "source": str(SERVICE_PATH.relative_to(REPO)),
        "replacements": replacements,
        "marker_removed": True,
        "source_before_sha256": before_sha,
        "source_after_sha256": _sha_bytes(after.encode()),
        "canonical_worktree_mutated": False,
    }


def environment_record(preflight_report: dict, manifest: dict) -> dict:
    images = [manifest["runtime"]["neo4j_image"], manifest["runtime"]["postgres_image"]]
    return {
        "schema_version": "lakatotree-requirements-harness-environment/v1",
        "captured_at": _utc_now(),
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "packages": {
            name: _package_version(name)
            for name in (
                "fastapi", "pydantic", "neo4j", "psycopg2-binary", "pytest",
                "testcontainers", "docker",
            )
        },
        "declared_images": images,
        "docker": _docker_probe(images),
        "inputs": {
            str(path.relative_to(REPO)): {
                "bytes": path.stat().st_size,
                "sha256": _sha_file(path),
            }
            for path in (
                Path(__file__).resolve(),
                REQUIREMENTS_PATH,
                MANIFEST_PATH,
                PREREG_PATH,
                TARGETED_JUDGE_PATH,
                TEST_PATH,
                CONFTEST_PATH,
                SERVICE_PATH,
                REPO / "requirements.txt",
                REPO / "requirements-integration.txt",
                REPO / "uv.lock",
            )
        },
        "preflight": preflight_report,
        "datastore_environment_values_recorded": False,
    }


def write_bundle_manifest(artifact_dir: Path) -> dict:
    manifest_path = artifact_dir / "bundle_manifest.json"
    files = []
    for path in sorted(p for p in artifact_dir.rglob("*") if p.is_file() and p != manifest_path):
        files.append({
            "path": path.relative_to(artifact_dir).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": _sha_file(path),
        })
    payload = {
        "schema_version": "lakatotree-requirements-harness-bundle/v1",
        "files": files,
    }
    _write_json(manifest_path, payload)
    return payload


def capture(*, artifact_dir: Path, python: str, timeout: int, preflight_only: bool = False) -> int:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    artifact_dir.mkdir(parents=True, exist_ok=True)
    preflight_report = preflight(manifest)
    if preflight_only or not preflight_report["ready"]:
        environment = environment_record(preflight_report, manifest)
        _write_json(artifact_dir / "environment.json", environment)
        _write_json(artifact_dir / "preflight.json", {
            "ready": preflight_report["ready"],
            "captured_at": _utc_now(),
        })
        write_bundle_manifest(artifact_dir)
        return 0 if preflight_report["ready"] else 2

    head = _git("rev-parse", "HEAD").strip()
    current_sha = _sha_file(SERVICE_PATH)
    prereg = json.loads(PREREG_PATH.read_text(encoding="utf-8"))
    negative = manifest["negative_control"]
    targeted_negative = manifest["targeted_negative_control"]
    positive = run_pytest(
        python=python,
        cwd=REPO,
        test_path=TEST_PATH,
        junit_path=artifact_dir / "positive.junit.xml",
        timeout=timeout,
        phase="positive",
        source_revision=head,
        source_sha256=current_sha,
        manifest=manifest,
        expected="GREEN",
    )

    with tempfile.TemporaryDirectory(prefix="lakatotree-argument-negative-") as tmp:
        old_root = Path(tmp) / "source"
        archive_revision(negative["revision"], old_root)
        old_service = old_root / manifest["system_under_test"]["source"]
        historical_negative = run_pytest(
            python=python,
            cwd=old_root,
            test_path=old_root / "tests/integration" / TEST_PATH.name,
            junit_path=artifact_dir / "negative_historical.junit.xml",
            timeout=timeout,
            phase="negative_historical_arg_1_4",
            source_revision=negative["revision"],
            source_sha256=_sha_file(old_service),
            manifest=manifest,
            expected="RED",
            selected_tests=negative["selected_tests"],
            negative_control=negative,
        )

    with tempfile.TemporaryDirectory(prefix="lakatotree-argument-arg5-negative-") as tmp:
        mutated_root = Path(tmp) / "source"
        archive_revision(head, mutated_root)
        mutated_service = mutated_root / manifest["system_under_test"]["source"]
        mutation = apply_arg5_claim_mutation(
            mutated_service,
            expected_preimage_sha256=prereg["base"]["service_sha256"],
        )
        _write_json(artifact_dir / "arg5_claim_mutation.json", mutation)
        targeted_negative_result = run_pytest(
            python=python,
            cwd=mutated_root,
            test_path=mutated_root / "tests/integration" / TEST_PATH.name,
            junit_path=artifact_dir / "negative_arg5_claim.junit.xml",
            timeout=timeout,
            phase="negative_targeted_arg_5_claim",
            source_revision=f"{head}+mutation:{mutation['mutation_id']}",
            source_sha256=mutation["source_after_sha256"],
            manifest=manifest,
            expected="RED",
            selected_tests=targeted_negative["selected_tests"],
            negative_control=targeted_negative,
        )

    restored = run_pytest(
        python=python,
        cwd=REPO,
        test_path=TEST_PATH,
        junit_path=artifact_dir / "restored_positive.junit.xml",
        timeout=timeout,
        phase="restored_positive",
        source_revision=head,
        source_sha256=current_sha,
        manifest=manifest,
        expected="GREEN",
    )

    environment = environment_record(preflight_report, manifest)
    _write_json(artifact_dir / "environment.json", environment)
    environment_sha = _sha_file(artifact_dir / "environment.json")
    phase_files = (
        ("positive.json", positive),
        ("negative_historical.json", historical_negative),
        ("negative_arg5_claim.json", targeted_negative_result),
        ("restored_positive.json", restored),
    )
    for filename, result in phase_files:
        result["environment_sha256"] = environment_sha
        result["requirements_sha256"] = _sha_file(REQUIREMENTS_PATH)
        result["harness_sha256"] = _sha_file(TEST_PATH)
        _write_json(artifact_dir / filename, result)

    complete = all(result["accepted"] for _, result in phase_files)
    receipt = {
        "schema_version": "lakatotree-requirements-harness-receipt/v2",
        "receipt_id": f"argument-integrity-{head[:12]}",
        "captured_at": _utc_now(),
        "complete": complete,
        "tier": manifest["tier"],
        "requirements": manifest["requirements"],
        "producer": {
            "git_head": head,
            "working_tree_dirty": bool(_git("status", "--porcelain")),
            "entrypoint": str(Path(__file__).relative_to(REPO)),
            "sha256": _sha_file(Path(__file__).resolve()),
        },
        "bindings": {
            "requirements_sha256": _sha_file(REQUIREMENTS_PATH),
            "manifest_sha256": _sha_file(MANIFEST_PATH),
            "preregistration_sha256": _sha_file(PREREG_PATH),
            "targeted_judge_sha256": _sha_file(TARGETED_JUDGE_PATH),
            "producer_sha256": _sha_file(Path(__file__).resolve()),
            "harness_sha256": _sha_file(TEST_PATH),
            "fixture_sha256": _sha_file(CONFTEST_PATH),
            "service_sha256": current_sha,
            "historical_negative_service_sha256": historical_negative["source_sha256"],
            "targeted_negative_service_sha256": targeted_negative_result["source_sha256"],
            "arg5_claim_mutation_sha256": _sha_file(
                artifact_dir / "arg5_claim_mutation.json"
            ),
            "environment_sha256": environment_sha,
        },
        "sequence": [
            {
                "phase": result["phase"],
                "expected": result["expected"],
                "observed": result["observed"],
                "accepted": result["accepted"],
                "path": filename,
                "sha256": _sha_file(artifact_dir / filename),
            }
            for filename, result in phase_files
        ],
        "claim_boundary": manifest["claim_boundary"],
        "canonical_worktree_mutated": False,
    }
    _write_json(artifact_dir / "receipt.json", receipt)
    judge_path = artifact_dir / "judge.json"
    judge_command = [
        python,
        str(TARGETED_JUDGE_PATH),
        "--artifact-dir",
        str(artifact_dir),
        "--output",
        str(judge_path),
    ]
    judge_run = subprocess.run(judge_command, capture_output=True, text=True, check=False)
    if judge_path.is_file():
        judge_result = json.loads(judge_path.read_text(encoding="utf-8"))
    else:
        judge_result = {
            "schema_version": "lakatotree-judge-result/v1",
            "experiment_id": prereg["experiment_id"],
            "metric_name": prereg["judge"]["metric_name"],
            "metric": 1,
            "direction": prereg["judge"]["direction"],
            "threshold": prereg["judge"]["threshold"],
            "noise_band": prereg["judge"]["noise_band"],
            "status": "FAIL",
            "failures": [f"judge_execution:{judge_run.returncode}"],
        }
        _write_json(judge_path, judge_result)
    judge_ok = judge_run.returncode == 0 and judge_result.get("metric") == 0
    receipt["judge"] = {
        "path": judge_path.name,
        "sha256": _sha_file(judge_path),
        "command": judge_command,
        "exit_code": judge_run.returncode,
        "metric_name": judge_result.get("metric_name"),
        "metric": judge_result.get("metric"),
    }
    receipt["complete"] = bool(complete and judge_ok)
    _write_json(artifact_dir / "receipt.json", receipt)
    write_bundle_manifest(artifact_dir)
    return 0 if receipt["complete"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be a positive number of seconds")
    return capture(
        artifact_dir=args.artifact_dir.resolve(),
        python=args.python,
        timeout=args.timeout,
        preflight_only=args.preflight_only,
    )


if __name__ == "__main__":
    raise SystemExit(main())
