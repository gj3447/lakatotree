#!/usr/bin/env python3
"""Capture the preregistration-gated ARG-5 ownership-comparison replication.

The producer never edits the canonical checkout or touches production stores.  It
archives the protocol's frozen source commit, runs disposable testcontainers, and
writes an immutable judge-input -> judge -> receipt -> bundle-manifest DAG.  Live
capture is unreachable until a separately committed activation receipt proves that
server preregistration predates measurement.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from ooptdd_receipts.ARGUMENT_INTEGRITY import real_harness as legacy  # noqa: E402


HERE = Path(__file__).resolve().parent
PROTOCOL_PATH = HERE / "harness_v2.json"
ACTIVATION_PATH = HERE / "activation_20260802.json"
JUDGE_PATH = REPO / "judges/arg5_unconditional_ownership_oracle.py"
VALIDATOR_PATH = REPO / "judges/argument_integrity_bundle_validator_v2.py"
LEGACY_HELPER_PATH = REPO / "ooptdd_receipts/ARGUMENT_INTEGRITY/real_harness.py"
TARGET_TEST = "test_arg_5_create_claim_has_one_owner_and_does_not_leak"
SERVICE_REL = "server/contexts/tree/evidence_claim_service.py"
TEST_REL = "tests/integration/test_argument_integrity_real_neo4j.py"
FIXTURE_REL = "tests/integration/conftest.py"
ASSIGNMENT_MARKER = (
    b"ON CREATE SET a:LakatosArgument, a._argument_create_claim=$create_claim,\n"
)
COMPARISON_MARKER = (
    b"                   coalesce(actual._argument_create_claim=$create_claim, false) AS created\n"
)
UNCONDITIONAL_MARKER = b"                   true AS created\n"


def _sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha_file(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _write_json_once(path: Path, payload: dict) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())


def _write_bytes_once(path: Path, payload: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _git_blob(commit: str, relative_path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{commit}:{relative_path}"],
        cwd=REPO,
        check=True,
        capture_output=True,
    ).stdout


def _archive_revision(revision: str, destination: Path) -> None:
    """Extract only the frozen Git tree; never copy files from the live checkout."""
    destination.mkdir(parents=True, exist_ok=False)
    archive_path = destination.parent / f"{revision}.tar"
    subprocess.run(
        ["git", "archive", "--format=tar", "--output", str(archive_path), revision],
        cwd=REPO,
        check=True,
    )
    try:
        with tarfile.open(archive_path) as archive:
            archive.extractall(destination, filter="data")
    finally:
        archive_path.unlink(missing_ok=True)


def _load_protocol() -> dict:
    return json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))


def _git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _git_status() -> bytes:
    return subprocess.run(
        ["git", "status", "--porcelain=v1", "-z"],
        cwd=REPO,
        check=True,
        capture_output=True,
    ).stdout


def _aware_timestamp(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.utcoffset() is not None


def _activation_evidence_checks(activation: dict) -> dict[str, bool]:
    evidence = activation.get("evidence")
    checks: dict[str, bool] = {"activation_evidence_shape": isinstance(evidence, dict)}
    if not isinstance(evidence, dict):
        return checks
    required = {
        "preregistration_request",
        "server_response",
        "receipts_readback",
        "receipts_verify",
    }
    checks["activation_evidence_keys"] = set(evidence) == required
    for name in sorted(required):
        entry = evidence.get(name)
        valid_shape = (
            isinstance(entry, dict)
            and isinstance(entry.get("path"), str)
            and isinstance(entry.get("sha256"), str)
        )
        checks[f"activation_evidence_shape:{name}"] = valid_shape
        if not valid_shape:
            checks[f"activation_evidence_hash:{name}"] = False
            continue
        path = REPO / entry["path"]
        checks[f"activation_evidence_hash:{name}"] = (
            path.is_file()
            and not path.is_symlink()
            and len(entry["sha256"]) == 64
            and all(char in "0123456789abcdef" for char in entry["sha256"])
            and entry["sha256"] == _sha_file(path)
        )
    return checks


def apply_unconditional_ownership_mutation(
    source_path: Path,
    *,
    expected_preimage_sha256: str,
    expected_postimage_sha256: str,
) -> dict:
    """Replace exactly the owner-token comparison while preserving assignment."""
    before = source_path.read_bytes()
    before_sha = _sha_bytes(before)
    if before_sha != expected_preimage_sha256:
        raise ValueError(
            "ARG-5 v2 mutation preimage drift: "
            f"expected {expected_preimage_sha256}, got {before_sha}"
        )
    comparison_before = before.count(COMPARISON_MARKER)
    unconditional_before = before.count(UNCONDITIONAL_MARKER)
    assignment_before = before.count(ASSIGNMENT_MARKER)
    if (comparison_before, unconditional_before, assignment_before) != (1, 0, 1):
        raise ValueError(
            "ARG-5 v2 marker contract drift: "
            f"comparison={comparison_before}, unconditional={unconditional_before}, "
            f"assignment={assignment_before}"
        )
    after = before.replace(COMPARISON_MARKER, UNCONDITIONAL_MARKER, 1)
    after_sha = _sha_bytes(after)
    comparison_after = after.count(COMPARISON_MARKER)
    unconditional_after = after.count(UNCONDITIONAL_MARKER)
    assignment_after = after.count(ASSIGNMENT_MARKER)
    if (comparison_after, unconditional_after, assignment_after) != (0, 1, 1):
        raise ValueError("ARG-5 v2 post-mutation marker contract failed")
    if after_sha != expected_postimage_sha256:
        raise ValueError(
            "ARG-5 v2 mutation postimage drift: "
            f"expected {expected_postimage_sha256}, got {after_sha}"
        )
    source_path.write_bytes(after)
    return {
        "schema_version": "lakatotree-arg5-ownership-comparison-mutation/v2",
        "mutation_id": "arg5-force-created-true-preserve-claim-assignment",
        "source": SERVICE_REL,
        "source_before_sha256": before_sha,
        "source_after_sha256": after_sha,
        "comparison_before_count": comparison_before,
        "comparison_after_count": comparison_after,
        "unconditional_before_count": unconditional_before,
        "unconditional_after_count": unconditional_after,
        "assignment_before_count": assignment_before,
        "assignment_after_count": assignment_after,
        "replacements": 1,
        "canonical_worktree_mutated": False,
    }


def _activation_report(
    protocol: dict, protocol_sha256: str
) -> tuple[dict | None, dict[str, bool]]:
    checks = {"activation_present": ACTIVATION_PATH.is_file()}
    if not ACTIVATION_PATH.is_file():
        return None, checks
    activation = json.loads(ACTIVATION_PATH.read_text(encoding="utf-8"))
    judge_exists = JUDGE_PATH.is_file() and not JUDGE_PATH.is_symlink()
    judge_sha = _sha_file(JUDGE_PATH) if judge_exists else None
    server = protocol.get("server_preregistration") or {}
    metric = protocol.get("metric") or {}
    readback = activation.get("exact_readback")
    checks.update(
        {
            "activation_schema": activation.get("schema_version")
            == "lakatotree-argument-integrity-v2-activation/v1",
            "activation_enabled": activation.get("active") is True,
            "activation_protocol_sha256": activation.get("protocol_sha256")
            == protocol_sha256,
            "activation_judge_present": judge_exists,
            "activation_judge_sha256": (
                judge_sha is not None
                and activation.get("judge_sha256") == judge_sha
            ),
            "activation_server_readback_verified": activation.get(
                "server_readback_verified"
            )
            is True,
            "activation_scientific_status": activation.get("scientific_status")
            == "PREREGISTERED_UNJUDGED",
            "activation_registered_at": _aware_timestamp(
                activation.get("server_registered_at")
            ),
            "activation_readback_shape": isinstance(readback, dict),
            "activation_readback_tree": isinstance(readback, dict)
            and readback.get("tree_name") == server.get("tree_name"),
            "activation_readback_tag": isinstance(readback, dict)
            and readback.get("node_tag") == server.get("node_tag"),
            "activation_readback_metric": isinstance(readback, dict)
            and readback.get("metric_name") == metric.get("name"),
            "activation_readback_direction": isinstance(readback, dict)
            and readback.get("direction") == metric.get("direction"),
            "activation_readback_baseline": isinstance(readback, dict)
            and type(readback.get("baseline_value")) is int
            and readback.get("baseline_value") == metric.get("baseline"),
            "activation_readback_noise": isinstance(readback, dict)
            and type(readback.get("noise_band")) is int
            and readback.get("noise_band") == metric.get("noise_band"),
            "activation_readback_scale": isinstance(readback, dict)
            and readback.get("scale_type") == metric.get("scale_type"),
            "activation_readback_judge": isinstance(readback, dict)
            and judge_sha is not None
            and readback.get("judge_script_sha") == judge_sha,
            "activation_readback_verify": isinstance(readback, dict)
            and readback.get("verify_ok") is True,
            "activation_readback_unjudged": isinstance(readback, dict)
            and readback.get("rederived") is None
            and readback.get("cached_verdict") is None,
            "activation_readback_head": isinstance(readback, dict)
            and isinstance(readback.get("receipt_chain_head"), str)
            and len(readback.get("receipt_chain_head")) == 64
            and all(
                char in "0123456789abcdef"
                for char in readback.get("receipt_chain_head")
            )
            and readback.get("prediction_receipt_sha")
            == readback.get("receipt_chain_head"),
        }
    )
    checks.update(_activation_evidence_checks(activation))
    return activation, checks


def preflight(protocol: dict) -> dict:
    protocol_sha = _sha_file(PROTOCOL_PATH)
    base_commit = protocol.get("base_source", {}).get("commit", "")
    checks: dict[str, object] = {
        "protocol_schema": protocol.get("schema_version")
        == "lakatotree-argument-integrity-v2-protocol/v1",
        "experiment_id": protocol.get("experiment_id")
        == "ARG5_UNCONDITIONAL_OWNERSHIP_COMPARISON_20260802",
        "replication_classification": protocol.get("classification")
        == "prospective_confirmatory_replication_with_prior_exposure",
        "server_scientific_status": protocol.get("scientific_status") == "UNJUDGED",
        "canonical_worktree_clean": not bool(_git_status()),
        "python_3_14": platform.python_version().startswith("3.14."),
    }
    for package in ("testcontainers", "docker", "neo4j", "psycopg2-binary"):
        checks[f"package:{package}"] = legacy._package_version(package) is not None
    try:
        subprocess.run(
            ["git", "cat-file", "-e", f"{base_commit}^{{commit}}"],
            cwd=REPO,
            check=True,
            capture_output=True,
        )
        checks["base_commit_present"] = True
    except subprocess.CalledProcessError:
        checks["base_commit_present"] = False

    locked = protocol.get("locked_inputs", {})
    current_paths = {
        "producer_sha256": Path(__file__).resolve(),
        "validator_sha256": VALIDATOR_PATH,
        "legacy_helper_sha256": LEGACY_HELPER_PATH,
        "requirements_sha256": REPO / "ooptdd_receipts/ARGUMENT_INTEGRITY/requirements.yaml",
        "dependency_lock_sha256": REPO / "uv.lock",
    }
    for key, path in current_paths.items():
        checks[key] = path.is_file() and locked.get(key) == _sha_file(path)
    base_paths = {
        "service_sha256": SERVICE_REL,
        "integration_test_sha256": TEST_REL,
        "fixture_sha256": FIXTURE_REL,
    }
    for key, relative_path in base_paths.items():
        try:
            checks[key] = locked.get(key) == _sha_bytes(
                _git_blob(base_commit, relative_path)
            )
        except subprocess.CalledProcessError:
            checks[key] = False

    try:
        base_source = (
            _git_blob(base_commit, SERVICE_REL)
            if checks.get("base_commit_present")
            else b""
        )
    except subprocess.CalledProcessError:
        base_source = b""
    checks["comparison_marker_count"] = base_source.count(COMPARISON_MARKER)
    checks["assignment_marker_count"] = base_source.count(ASSIGNMENT_MARKER)
    mutated = base_source.replace(COMPARISON_MARKER, UNCONDITIONAL_MARKER, 1)
    checks["expected_postimage_sha256"] = (
        _sha_bytes(mutated)
        == protocol.get("intervention", {}).get("expected_postimage_sha256")
    )
    activation, activation_checks = _activation_report(protocol, protocol_sha)
    checks.update(activation_checks)
    docker = legacy._docker_probe(list(protocol.get("runtime", {}).get("images", {})))
    checks["docker_reachable"] = docker.get("reachable") is True
    for tag, digest in (protocol.get("runtime", {}).get("images", {})).items():
        image = (docker.get("images") or {}).get(tag) or {}
        checks[f"docker_image_digest:{tag}"] = (
            image.get("present") is True
            and digest in (image.get("repo_digests") or [])
        )

    required_true = [
        "protocol_schema",
        "experiment_id",
        "replication_classification",
        "server_scientific_status",
        "canonical_worktree_clean",
        "python_3_14",
        "package:testcontainers",
        "package:docker",
        "package:neo4j",
        "package:psycopg2-binary",
        "base_commit_present",
        *current_paths,
        *base_paths,
        "expected_postimage_sha256",
        "activation_present",
        "activation_schema",
        "activation_enabled",
        "activation_protocol_sha256",
        "activation_judge_present",
        "activation_judge_sha256",
        "activation_server_readback_verified",
        "activation_scientific_status",
        "activation_registered_at",
        "activation_readback_shape",
        "activation_readback_tree",
        "activation_readback_tag",
        "activation_readback_metric",
        "activation_readback_direction",
        "activation_readback_baseline",
        "activation_readback_noise",
        "activation_readback_scale",
        "activation_readback_judge",
        "activation_readback_verify",
        "activation_readback_unjudged",
        "activation_readback_head",
        "activation_evidence_shape",
        "activation_evidence_keys",
        "docker_reachable",
    ]
    required_true.extend(
        key
        for key in checks
        if key.startswith("activation_evidence_shape:")
        or key.startswith("activation_evidence_hash:")
        or key.startswith("docker_image_digest:")
    )
    ready = all(checks.get(key) is True for key in required_true) and (
        checks.get("comparison_marker_count") == 1
        and checks.get("assignment_marker_count") == 1
    )
    return {
        "ready": ready,
        "checks": checks,
        "required_checks": sorted(required_true),
        "activation": activation,
        "docker": docker,
        "protocol_sha256": protocol_sha,
        "canonical_head": _git_head(),
        "canonical_status_sha256": _sha_bytes(_git_status()),
    }


def _environment(
    protocol: dict,
    report: dict,
    *,
    archive_readback: dict,
    postflight: dict,
) -> dict:
    return {
        "schema_version": "lakatotree-argument-integrity-v2-environment/v1",
        "captured_at": legacy._utc_now(),
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "packages": {
            package: legacy._package_version(package)
            for package in (
                "testcontainers",
                "docker",
                "neo4j",
                "psycopg2-binary",
            )
        },
        "declared_images": protocol["runtime"]["images"],
        "docker": legacy._docker_probe(list(protocol["runtime"]["images"])),
        "preflight": report,
        "archive_readback": archive_readback,
        "postflight": postflight,
        "datastore_environment_values_recorded": False,
    }


def _archive_readback(root: Path, protocol: dict) -> dict:
    locked = protocol["locked_inputs"]
    paths = {
        "service_sha256": root / SERVICE_REL,
        "integration_test_sha256": root / TEST_REL,
        "fixture_sha256": root / FIXTURE_REL,
    }
    result = {
        key: _sha_file(path) if path.is_file() and not path.is_symlink() else None
        for key, path in paths.items()
    }
    if any(result[key] != locked[key] for key in paths):
        raise ValueError(f"frozen archive input drift: {result}")
    return result


def _canonical_postflight(report: dict) -> dict:
    status = _git_status()
    head = _git_head()
    postflight = {
        "head": head,
        "status_sha256": _sha_bytes(status),
        "clean": not bool(status),
        "matches_preflight": (
            head == report.get("canonical_head")
            and _sha_bytes(status) == report.get("canonical_status_sha256")
        ),
    }
    if postflight["clean"] is not True or postflight["matches_preflight"] is not True:
        raise RuntimeError("canonical checkout drifted during v2 capture")
    return postflight


def _run_phase(
    *,
    protocol: dict,
    python: str,
    source_root: Path,
    artifact_dir: Path,
    filename: str,
    phase: str,
    expected: str,
    source_revision: str,
    source_sha256: str,
    timeout: int,
) -> dict:
    negative = protocol["run_manifest"].get("targeted_negative_control")
    return legacy.run_pytest(
        python=python,
        cwd=source_root,
        test_path=source_root / TEST_REL,
        junit_path=artifact_dir / filename,
        timeout=timeout,
        phase=phase,
        source_revision=source_revision,
        source_sha256=source_sha256,
        manifest=protocol["run_manifest"],
        expected=expected,
        selected_tests=[TARGET_TEST],
        negative_control=negative if expected == "RED" else None,
    )


def _write_bundle_manifest(artifact_dir: Path, allowlist: list[str]) -> None:
    entries = list(artifact_dir.rglob("*"))
    if any(path.is_symlink() or not path.is_file() for path in entries):
        raise ValueError("v2 artifact directory contains a non-regular entry")
    actual = sorted(path.relative_to(artifact_dir).as_posix() for path in entries)
    if actual != sorted(allowlist):
        raise ValueError(f"pre-manifest artifact set drift: {actual}")
    files = []
    for filename in sorted(allowlist):
        path = artifact_dir / filename
        files.append(
            {"path": filename, "bytes": path.stat().st_size, "sha256": _sha_file(path)}
        )
    _write_json_once(
        artifact_dir / "bundle_manifest.json",
        {
            "schema_version": "lakatotree-argument-integrity-v2-bundle/v1",
            "files": files,
        },
    )


def capture(
    *, artifact_dir: Path, python: str, timeout: int, preflight_only: bool = False
) -> int:
    if type(timeout) is not int or timeout <= 0:
        raise ValueError("timeout must be a positive integer")
    protocol = _load_protocol()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    if any(artifact_dir.iterdir()):
        raise FileExistsError("v2 artifact directory must start empty")
    report = preflight(protocol)
    if preflight_only or not report["ready"]:
        _write_json_once(artifact_dir / "preflight.json", report)
        return 0 if report["ready"] else 2

    _write_bytes_once(artifact_dir / "protocol.json", PROTOCOL_PATH.read_bytes())
    _write_bytes_once(artifact_dir / "activation.json", ACTIVATION_PATH.read_bytes())

    base_commit = protocol["base_source"]["commit"]
    source_sha = protocol["locked_inputs"]["service_sha256"]
    with tempfile.TemporaryDirectory(prefix="lakatotree-arg5-v2-") as tmp:
        temp_root = Path(tmp)
        positive_root = temp_root / "positive"
        mutated_root = temp_root / "mutated"
        _archive_revision(base_commit, positive_root)
        _archive_revision(base_commit, mutated_root)
        positive_archive = _archive_readback(positive_root, protocol)
        mutated_archive = _archive_readback(mutated_root, protocol)

        positive = _run_phase(
            protocol=protocol,
            python=python,
            source_root=positive_root,
            artifact_dir=artifact_dir,
            filename="positive.junit.xml",
            phase="positive",
            expected="GREEN",
            source_revision=base_commit,
            source_sha256=source_sha,
            timeout=timeout,
        )
        mutation = apply_unconditional_ownership_mutation(
            mutated_root / SERVICE_REL,
            expected_preimage_sha256=source_sha,
            expected_postimage_sha256=protocol["intervention"][
                "expected_postimage_sha256"
            ],
        )
        _write_json_once(artifact_dir / "mutation.json", mutation)
        negative = _run_phase(
            protocol=protocol,
            python=python,
            source_root=mutated_root,
            artifact_dir=artifact_dir,
            filename="negative.junit.xml",
            phase="negative_unconditional_ownership",
            expected="RED",
            source_revision=f"{base_commit}+mutation:{mutation['mutation_id']}",
            source_sha256=mutation["source_after_sha256"],
            timeout=timeout,
        )
        restored = _run_phase(
            protocol=protocol,
            python=python,
            source_root=positive_root,
            artifact_dir=artifact_dir,
            filename="restored.junit.xml",
            phase="restored",
            expected="GREEN",
            source_revision=base_commit,
            source_sha256=source_sha,
            timeout=timeout,
        )

    postflight = _canonical_postflight(report)
    environment = _environment(
        protocol,
        report,
        archive_readback={
            "positive": positive_archive,
            "mutated_preimage": mutated_archive,
        },
        postflight=postflight,
    )
    _write_json_once(artifact_dir / "environment.json", environment)
    environment_sha = _sha_file(artifact_dir / "environment.json")
    phase_specs = (
        ("positive.json", positive),
        ("negative.json", negative),
        ("restored.json", restored),
    )
    for filename, phase in phase_specs:
        phase["environment_sha256"] = environment_sha
        phase["protocol_sha256"] = report["protocol_sha256"]
        phase["producer_sha256"] = _sha_file(Path(__file__).resolve())
        _write_json_once(artifact_dir / filename, phase)

    activation_sha = _sha_file(ACTIVATION_PATH)
    judge_input = {
        "schema_version": "lakatotree-argument-integrity-v2-judge-input/v1",
        "experiment_id": protocol["experiment_id"],
        "protocol": {
            "path": "protocol.json",
            "source_path": str(PROTOCOL_PATH.relative_to(REPO)),
            "sha256": report["protocol_sha256"],
        },
        "activation": {
            "path": "activation.json",
            "source_path": str(ACTIVATION_PATH.relative_to(REPO)),
            "sha256": activation_sha,
        },
        "producer": {
            "path": str(Path(__file__).resolve().relative_to(REPO)),
            "sha256": _sha_file(Path(__file__).resolve()),
            "working_tree_dirty": False,
        },
        "source_commit": base_commit,
        "bindings": {
            "protocol.json": _sha_file(artifact_dir / "protocol.json"),
            "activation.json": _sha_file(artifact_dir / "activation.json"),
            "environment.json": environment_sha,
            "mutation.json": _sha_file(artifact_dir / "mutation.json"),
            **{
                filename: _sha_file(artifact_dir / filename)
                for filename, _ in phase_specs
            },
            **{
                phase["junit_path"]: phase["junit_sha256"]
                for _, phase in phase_specs
            },
        },
        "phase_sequence": [
            {
                "phase": phase["phase"],
                "path": filename,
                "sha256": _sha_file(artifact_dir / filename),
                "junit_path": phase["junit_path"],
                "junit_sha256": phase["junit_sha256"],
            }
            for filename, phase in phase_specs
        ],
        "canonical_worktree_mutated": False,
    }
    _write_json_once(artifact_dir / "judge_input.json", judge_input)

    judge_path = artifact_dir / "judge.json"
    judge_run = subprocess.run(
        [
            python,
            str(JUDGE_PATH),
            "--artifact-dir",
            str(artifact_dir),
            "--output",
            str(judge_path),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
        timeout=min(timeout, 60),
    )
    if not judge_path.is_file():
        raise RuntimeError(f"v2 judge emitted no result (exit {judge_run.returncode})")
    judge = json.loads(judge_path.read_text(encoding="utf-8"))
    complete = (
        all(phase.get("accepted") is True for _, phase in phase_specs)
        and judge_run.returncode == 0
        and type(judge.get("metric")) is int
        and judge.get("metric") == 0
        and judge.get("status") == "PASS"
        and judge.get("failures") == []
        and judge.get("scientific_status") == "UNJUDGED"
    )
    receipt = {
        "schema_version": "lakatotree-argument-integrity-v2-receipt/v1",
        "experiment_id": protocol["experiment_id"],
        "captured_at": legacy._utc_now(),
        "complete": complete,
        "scientific_status": "UNJUDGED",
        "server_result_submitted": False,
        "claim_boundary": protocol["claim_boundary"],
        "source_commit": base_commit,
        "protocol_sha256": report["protocol_sha256"],
        "activation_sha256": activation_sha,
        "producer_sha256": _sha_file(Path(__file__).resolve()),
        "judge_input_sha256": _sha_file(artifact_dir / "judge_input.json"),
        "judge": {
            "source_sha256": _sha_file(JUDGE_PATH),
            "result_sha256": _sha_file(judge_path),
            "exit_code": judge_run.returncode,
            "metric": judge.get("metric"),
        },
        "canonical_worktree_mutated": False,
    }
    _write_json_once(artifact_dir / "receipt.json", receipt)
    _write_bundle_manifest(artifact_dir, protocol["artifact_allowlist"])
    from judges import argument_integrity_bundle_validator_v2 as bundle_validator

    structural = bundle_validator.validate_bundle(artifact_dir)
    if structural.get("valid") is not True:
        raise RuntimeError(
            "v2 structural validation failed: "
            + ", ".join(structural.get("failures") or [])
        )
    return 0 if complete else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args(argv)
    return capture(
        artifact_dir=args.artifact_dir,
        python=args.python,
        timeout=args.timeout,
        preflight_only=args.preflight_only,
    )


if __name__ == "__main__":
    raise SystemExit(main())
