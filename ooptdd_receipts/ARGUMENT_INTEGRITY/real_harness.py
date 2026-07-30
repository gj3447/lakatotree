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
    checks["required_files_present"] = all(
        path.is_file()
        for path in (MANIFEST_PATH, TEST_PATH, CONFTEST_PATH, SERVICE_PATH, REQUIREMENTS_PATH)
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
        })
    counts = {
        "passed": sum(case["status"] == "passed" for case in cases),
        "failed": sum(case["status"] == "failed" for case in cases),
        "errors": sum(case["status"] == "error" for case in cases),
        "skipped": sum(case["status"] == "skipped" for case in cases),
    }
    return {"present": True, "tests": len(cases), **counts, "cases": cases}


def evaluate_junit(summary: dict, manifest: dict, *, expected: str) -> dict:
    by_name = {case["name"]: case["status"] for case in summary["cases"]}
    required = set(manifest["tests"].values())
    missing = sorted(required.difference(by_name))
    if expected == "GREEN":
        accepted = (
            not missing
            and all(by_name[name] == "passed" for name in required)
            and summary["failed"] == summary["errors"] == summary["skipped"] == 0
        )
        observed = "GREEN" if accepted else "RED"
        execution_ok = summary["present"] and not missing and summary["errors"] == 0
    else:
        required_failures = set(manifest["negative_control"]["required_failed_tests"])
        semantic_failures = {name for name, status in by_name.items() if status == "failed"}
        accepted = (
            not missing
            and required_failures <= semantic_failures
            and summary["errors"] == summary["skipped"] == 0
        )
        observed = "RED" if semantic_failures else "INVALID"
        execution_ok = summary["present"] and not missing and summary["errors"] == 0
    return {
        "accepted": bool(accepted),
        "expected": expected,
        "observed": observed,
        "execution_ok": bool(execution_ok),
        "missing_tests": missing,
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
) -> dict:
    command = [
        python,
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        str(test_path.relative_to(cwd)),
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
    evaluation = evaluate_junit(junit, manifest, expected=expected)
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
        "command": [Path(command[0]).name, *command[1:-1], "--junitxml=<artifact>"],
        "exit_code": exit_code,
        "timed_out": timed_out,
        "duration_seconds": duration,
        "output_sha256": _sha_bytes(output.encode()),
        "output_tail": _sanitized_tail(output, cwd),
        "junit": junit,
        "junit_path": junit_path.name,
        "junit_sha256": _sha_file(junit_path) if junit_path.is_file() else None,
        "missing_tests": evaluation["missing_tests"],
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
                REQUIREMENTS_PATH,
                MANIFEST_PATH,
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
    negative = manifest["negative_control"]
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
        negative_result = run_pytest(
            python=python,
            cwd=old_root,
            test_path=old_root / "tests/integration" / TEST_PATH.name,
            junit_path=artifact_dir / "negative.junit.xml",
            timeout=timeout,
            phase="negative_historical_revert",
            source_revision=negative["revision"],
            source_sha256=_sha_file(old_service),
            manifest=manifest,
            expected="RED",
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
        ("negative.json", negative_result),
        ("restored_positive.json", restored),
    )
    for filename, result in phase_files:
        result["environment_sha256"] = environment_sha
        result["requirements_sha256"] = _sha_file(REQUIREMENTS_PATH)
        result["harness_sha256"] = _sha_file(TEST_PATH)
        _write_json(artifact_dir / filename, result)

    complete = all(result["accepted"] for _, result in phase_files)
    receipt = {
        "schema_version": "lakatotree-requirements-harness-receipt/v1",
        "receipt_id": f"argument-integrity-{head[:12]}",
        "captured_at": _utc_now(),
        "complete": complete,
        "tier": manifest["tier"],
        "requirements": manifest["requirements"],
        "producer": {
            "git_head": head,
            "working_tree_dirty": bool(_git("status", "--porcelain")),
            "entrypoint": str(Path(__file__).relative_to(REPO)),
        },
        "bindings": {
            "requirements_sha256": _sha_file(REQUIREMENTS_PATH),
            "manifest_sha256": _sha_file(MANIFEST_PATH),
            "harness_sha256": _sha_file(TEST_PATH),
            "fixture_sha256": _sha_file(CONFTEST_PATH),
            "service_sha256": current_sha,
            "negative_service_sha256": negative_result["source_sha256"],
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
    write_bundle_manifest(artifact_dir)
    return 0 if complete else 1


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
