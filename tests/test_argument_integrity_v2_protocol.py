"""Frozen-protocol and activation-gate tests for ARG-5 v2."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from judges import arg5_unconditional_ownership_oracle as oracle
from judges import argument_integrity_bundle_validator_v2 as validator
from ooptdd_receipts.ARGUMENT_INTEGRITY.v2 import real_harness_v2 as harness


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_protocol_hash_chain_and_frozen_v1_are_exact():
    protocol = json.loads(validator.PROTOCOL_PATH.read_text(encoding="utf-8"))

    assert _sha(validator.PROTOCOL_PATH) == oracle.FROZEN_PROTOCOL_SHA256
    assert protocol["locked_inputs"]["producer_sha256"] == _sha(
        Path(harness.__file__).resolve()
    )
    assert protocol["locked_inputs"]["validator_sha256"] == _sha(
        Path(validator.__file__).resolve()
    )
    for item in protocol["frozen_v1"].values():
        assert _sha(validator.REPO / item["path"]) == item["sha256"]
    assert protocol["classification"] == (
        "prospective_confirmatory_replication_with_prior_exposure"
    )
    assert protocol["scientific_status"] == "UNJUDGED"


def test_exact_mutation_preserves_assignment_and_canonical_source(tmp_path):
    protocol = json.loads(validator.PROTOCOL_PATH.read_text(encoding="utf-8"))
    base = protocol["base_source"]["commit"]
    source = subprocess.run(
        ["git", "show", f"{base}:{harness.SERVICE_REL}"],
        cwd=validator.REPO,
        check=True,
        capture_output=True,
    ).stdout
    temporary = tmp_path / "evidence_claim_service.py"
    temporary.write_bytes(source)
    canonical_before = _sha(validator.REPO / harness.SERVICE_REL)

    result = harness.apply_unconditional_ownership_mutation(
        temporary,
        expected_preimage_sha256=protocol["locked_inputs"]["service_sha256"],
        expected_postimage_sha256=protocol["intervention"][
            "expected_postimage_sha256"
        ],
    )

    assert result["replacements"] == 1
    assert result["assignment_before_count"] == result["assignment_after_count"] == 1
    assert result["comparison_after_count"] == 0
    assert result["unconditional_after_count"] == 1
    assert _sha(temporary) == protocol["intervention"]["expected_postimage_sha256"]
    assert _sha(validator.REPO / harness.SERVICE_REL) == canonical_before


def test_live_capture_is_physically_closed_without_server_activation(
    tmp_path, monkeypatch
):
    missing_activation = tmp_path / "activation_20260802.json"
    monkeypatch.setattr(harness, "ACTIVATION_PATH", missing_activation)
    monkeypatch.setattr(harness, "_git_status", lambda: b"")
    monkeypatch.setattr(
        harness.legacy,
        "_docker_probe",
        lambda images=None: {
            "reachable": True,
            "images": {
                tag: {"present": True, "repo_digests": [digest]}
                for tag, digest in harness._load_protocol()["runtime"]["images"].items()
            },
        },
    )
    artifact_dir = tmp_path / "preflight"

    exit_code = harness.capture(
        artifact_dir=artifact_dir,
        python=str(Path(harness.sys.executable)),
        timeout=30,
        preflight_only=False,
    )

    report = json.loads((artifact_dir / "preflight.json").read_text(encoding="utf-8"))
    assert exit_code == 2
    assert report["ready"] is False
    assert report["checks"]["activation_present"] is False
    assert sorted(path.name for path in artifact_dir.iterdir()) == ["preflight.json"]
