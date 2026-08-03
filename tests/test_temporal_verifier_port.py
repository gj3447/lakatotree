"""Gate-4 process isolation and permanent-read promotion harness."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import shutil
import stat
import sys

import pytest

from c1verify.artifact import temporal_artifact_sha256 as c1_artifact_sha256
from lakatos.write_cert import did_key_encode, ed25519_public_key
from server.contexts.tree.temporal_service import TemporalProofService
from server.contexts.tree.temporal_verifier_port import (
    IndependentTemporalCandidate,
    IndependentTemporalResult,
    IndependentTemporalVerifierUnavailable,
    SubprocessIndependentTemporalVerifier,
    SubprocessTimeAuthority,
    temporal_artifact_sha256,
    temporal_request_id,
    transport_receipt,
)
from server.settings import ServerSettings
from tests.test_temporal_proof_service import _World, _anchors


_AUTHORITY_SECRET = bytes([240]) * 32
_AUTHORITY_DID = did_key_encode(ed25519_public_key(_AUTHORITY_SECRET))


def _authority_executable(
    tmp_path: Path,
) -> tuple[Path, str]:
    executable = tmp_path / "time-authority"
    source = f'''#!{sys.executable}
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

DOMAIN = b"lakatotree-independent-time-authority-challenge/v1\\0"
SIGN_DOMAIN = b"lakatotree-independent-time-authority-attestation/v1\\0"
SCHEMA = "lakatotree-independent-time-authority-attestation/v1"
RESPONSE_SCHEMA = "lakatotree-independent-time-authority-response/v1"
SECRET = bytes.fromhex("{_AUTHORITY_SECRET.hex()}")
SIGNER = "{_AUTHORITY_DID}"

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")

raw = sys.stdin.buffer.read()
challenge = json.loads(raw)
challenge_sha = hashlib.sha256(DOMAIN + raw).hexdigest()
private = Ed25519PrivateKey.from_private_bytes(SECRET)
now = datetime.now(timezone.utc)
attestations = []
for proof in challenge["proofs"]:
    body = {{
        "schema_version": SCHEMA,
        "challenge_sha256": challenge_sha,
        "signer_did": SIGNER,
        **proof,
        "verifier_artifact_sha256": challenge["verifier_artifact_sha256"],
        "verifier_python_sha256": challenge["verifier_python_sha256"],
        "observed_at": (now - timedelta(seconds=1)).isoformat(),
        "valid_until": (now + timedelta(minutes=1)).isoformat(),
    }}
    attestations.append({{**body, "signature": private.sign(SIGN_DOMAIN + canonical(body)).hex()}})
response = {{
    "schema_version": RESPONSE_SCHEMA,
    "challenge_sha256": challenge_sha,
    "attestations": attestations,
}}
sys.stdout.buffer.write(canonical(response) + b"\\n")
'''
    executable.write_text(source, encoding="utf-8")
    executable.chmod(stat.S_IRUSR | stat.S_IXUSR)
    return executable, hashlib.sha256(executable.read_bytes()).hexdigest()


def _world_with_sidecar(*, tag: str = "n") -> _World:
    world = _World(tag=tag)
    evaluated_at = datetime.now(timezone.utc)
    world.now = evaluated_at
    service = world.service()
    commitment = service.attach_prediction_commitment(
        "T",
        tag,
        _anchors(
            ("w1", "w2"),
            world.prediction_sha,
            (evaluated_at - timedelta(minutes=4)).isoformat(),
        ),
    )
    verdict_sha = world.mint_verdict(commitment["commitment_sha256"])
    service.finalize_sidecar(
        "T",
        tag,
        _anchors(
            ("w1", "w2"),
            verdict_sha,
            (evaluated_at - timedelta(minutes=2)).isoformat(),
        ),
    )
    return world


def _port(tmp_path: Path) -> SubprocessIndependentTemporalVerifier:
    authority_path, authority_sha = _authority_executable(tmp_path)
    artifact_directory = Path(__file__).resolve().parents[1] / "c1verify"
    artifact_sha, _files = temporal_artifact_sha256(artifact_directory)
    python = Path(sys.executable).resolve(strict=True)
    python_sha = hashlib.sha256(python.read_bytes()).hexdigest()
    authority = SubprocessTimeAuthority(
        executable=authority_path,
        expected_executable_sha256=authority_sha,
        expected_signer_did=_AUTHORITY_DID,
        nonce_factory=lambda _size: "a" * 64,
    )
    return SubprocessIndependentTemporalVerifier(
        python_executable=python,
        artifact_directory=artifact_directory,
        expected_artifact_sha256=artifact_sha,
        expected_python_sha256=python_sha,
        time_authority=authority,
    )


def _candidate(world: _World) -> IndependentTemporalCandidate:
    service = world.service()
    proof = service.read_proof("T", world.tag)
    snapshot = world.snapshot("T", world.tag)
    return service._independent_candidate("T", world.tag, snapshot, proof)


def _accepted(candidate, proof) -> IndependentTemporalResult:
    return IndependentTemporalResult(
        request_id=candidate.request_id,
        accepted=True,
        reason="independent_two_ended_temporal_verified",
        input_sha256="a" * 64,
        sidecar_sha256=proof.sidecar_sha256,
        authority_policy_sha256=proof.authority_policy_sha256,
        receipt_graph_sha256=proof.receipt_graph_sha256,
        prediction_receipt_sha256=proof.prediction_receipt_sha256,
        verdict_receipt_sha256=proof.verdict_receipt_sha256,
        prediction_temporal_commitment_sha256=(
            proof.prediction_temporal_commitment_sha256
        ),
        threshold=proof.threshold,
        t1_latest=proof.t1_latest,
        t2_earliest=proof.t2_earliest,
        independent_verifier="sha256:" + "b" * 64,
        time_authority="did-key-sha256:" + "c" * 64,
        independent_valid_until="2999-01-01T00:00:00+00:00",
        authority_identity_sha256s=("d" * 64,),
    )


def test_server_and_c1_compute_the_same_pinned_artifact_identity():
    artifact_directory = Path(__file__).resolve().parents[1] / "c1verify"
    server_sha, files = temporal_artifact_sha256(artifact_directory)

    assert server_sha == c1_artifact_sha256(artifact_directory)
    assert set(files) == {
        "_ed25519.py", "artifact.py", "jcs.py", "receipts.py",
        "temporal_cli.py", "temporal_sidecar.py",
    }


def test_artifact_manifest_rejects_an_import_outside_the_pinned_stdlib_closure(
    tmp_path,
):
    source = Path(__file__).resolve().parents[1] / "c1verify"
    artifact = tmp_path / "c1"
    artifact.mkdir()
    for name in (
        "_ed25519.py", "artifact.py", "jcs.py", "receipts.py",
        "temporal_cli.py", "temporal_sidecar.py",
    ):
        shutil.copyfile(source / name, artifact / name)
    with (artifact / "temporal_sidecar.py").open("ab") as handle:
        handle.write(b"\nimport lakatos\n")

    with pytest.raises(ValueError, match="escapes pinned closure"):
        c1_artifact_sha256(artifact)
    with pytest.raises(
        IndependentTemporalVerifierUnavailable,
        match="escapes pinned closure",
    ):
        temporal_artifact_sha256(artifact)


def test_gate4_runtime_profile_is_strict_all_or_none(monkeypatch, tmp_path):
    names = (
        "LAKATOS_TEMPORAL_C1_PYTHON",
        "LAKATOS_TEMPORAL_C1_ARTIFACT_DIRECTORY",
        "LAKATOS_TEMPORAL_C1_ARTIFACT_SHA256",
        "LAKATOS_TEMPORAL_C1_PYTHON_SHA256",
        "LAKATOS_TEMPORAL_TIME_AUTHORITY_EXECUTABLE",
        "LAKATOS_TEMPORAL_TIME_AUTHORITY_EXECUTABLE_SHA256",
        "LAKATOS_TEMPORAL_TIME_AUTHORITY_DID",
    )
    for name in names:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(names[0], str(Path(sys.executable).resolve()))
    partial = ServerSettings.from_env()
    assert partial.temporal_independent_verifier_requested is True
    with pytest.raises(RuntimeError, match="settings missing"):
        partial.require_temporal_independent_verifier()

    values = {
        names[0]: str(Path(sys.executable).resolve()),
        names[1]: str((Path(__file__).resolve().parents[1] / "c1verify").resolve()),
        names[2]: "1" * 64,
        names[3]: "2" * 64,
        names[4]: str((tmp_path / "authority").resolve()),
        names[5]: "3" * 64,
        names[6]: _AUTHORITY_DID,
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    complete = ServerSettings.from_env()
    profile = complete.require_temporal_independent_verifier()
    assert profile[2:4] == ("1" * 64, "2" * 64)
    assert profile[5:] == ("3" * 64, _AUTHORITY_DID)


def test_two_external_processes_promote_exact_current_head_to_l3(tmp_path):
    world = _world_with_sidecar()
    port = _port(tmp_path)
    service = TemporalProofService(
        kg=lambda *_a, **_k: [],
        ledger_kg_tx=world.tx,
        hist=world.hist,
        clock=lambda: world.now,
        snapshot_provider=world.snapshot,
        independent_verifier=port,
    )

    proof = service.read_proof("T", "n")

    assert proof.component_ok is True
    assert proof.chain_ok is True
    assert proof.l3_eligible is True
    assert proof.reason == "independent_two_ended_temporal_verified"
    assert proof.independent_verifier.startswith("sha256:")
    assert proof.time_authority.startswith("did-key-sha256:")


def test_subprocess_port_batches_many_candidates_into_two_process_calls(
    tmp_path, monkeypatch
):
    world = _world_with_sidecar()
    first = _candidate(world)
    second = _candidate(_world_with_sidecar(tag="other"))
    port = _port(tmp_path)
    import server.contexts.tree.temporal_verifier_port as module

    calls = []
    real_run = module._run_bounded

    def counted(*args, **kwargs):
        calls.append(tuple(args[0]))
        return real_run(*args, **kwargs)

    monkeypatch.setattr(module, "_run_bounded", counted)
    results = port.verify_batch((first, second))

    assert set(results) == {first.request_id, second.request_id}
    assert all(result.accepted for result in results.values())
    assert len(calls) == 2
    assert calls[0][0].endswith("authority")
    assert calls[1][1:4] == ("-I", "-S", "-B")
    assert calls[1][-1].endswith("temporal_cli.py")


def test_c1_rejection_keeps_gate3_component_at_l2(tmp_path):
    world = _world_with_sidecar()
    candidate = _candidate(world)
    spliced = IndependentTemporalCandidate(
        **{
            **candidate.__dict__,
            "sidecar": {
                **candidate.sidecar,
                "receipt_graph_sha256": "0" * 64,
            },
        }
    )

    result = _port(tmp_path).verify_batch((spliced,))[spliced.request_id]

    assert result.accepted is False
    assert result.reason in {"sidecar.content_sha", "sidecar.receipt_graph_binding"}


@pytest.mark.parametrize(
    "mutation",
    ("authority_executable", "authority_signer", "artifact", "python"),
)
def test_authority_or_verifier_pin_failure_never_promotes(tmp_path, mutation):
    world = _world_with_sidecar()
    candidate = _candidate(world)
    port = _port(tmp_path)
    if mutation == "authority_executable":
        port.time_authority.expected_executable_sha256 = "0" * 64
    elif mutation == "authority_signer":
        port.time_authority.expected_signer_did = candidate.witness_dids[0]
    elif mutation == "artifact":
        port.expected_artifact_sha256 = "0" * 64
    else:
        port.expected_python_sha256 = "0" * 64

    with pytest.raises(IndependentTemporalVerifierUnavailable):
        port.verify_batch((candidate,))


def test_service_turns_external_unavailability_into_l2_not_chain_refutation(tmp_path):
    world = _world_with_sidecar()
    port = _port(tmp_path)
    port.expected_artifact_sha256 = "0" * 64
    service = TemporalProofService(
        kg=lambda *_a, **_k: [],
        ledger_kg_tx=world.tx,
        hist=world.hist,
        clock=lambda: world.now,
        snapshot_provider=world.snapshot,
        independent_verifier=port,
    )

    proof = service.read_proof("T", "n")

    assert proof.component_ok is True
    assert proof.chain_ok is True
    assert proof.l3_eligible is False
    assert proof.reason == "independent_verifier_unavailable"
    assert proof.independent_verifier is None
    assert proof.time_authority is None


def test_service_calls_verifier_once_for_a_sorted_candidate_batch():
    world = _world_with_sidecar()
    base_service = world.service()
    proof = base_service.read_proof("T", "n")
    first = _candidate(world)
    second = replace(first, request_id="0" * 64)

    class Verifier:
        def __init__(self):
            self.calls = []

        def verify_batch(self, candidates):
            self.calls.append(tuple(candidates))
            return {
                candidate.request_id: _accepted(candidate, proof)
                for candidate in candidates
            }

    verifier = Verifier()
    service = TemporalProofService(
        kg=lambda *_a, **_k: [],
        ledger_kg_tx=world.tx,
        hist=world.hist,
        independent_verifier=verifier,
    )

    results = service._apply_independent_verifier(
        {"first": proof, "second": proof},
        {"first": first, "second": second},
    )

    assert len(verifier.calls) == 1
    assert tuple(item.request_id for item in verifier.calls[0]) == (
        second.request_id,
        first.request_id,
    )
    assert all(result.l3_eligible for result in results.values())


def test_service_keeps_gate3_at_l2_for_malformed_or_incomplete_results():
    world = _world_with_sidecar()
    proof = world.service().read_proof("T", "n")
    candidate = _candidate(world)
    malformed_results = (
        None,
        {},
        {candidate.request_id: object()},
        {
            candidate.request_id: _accepted(candidate, proof),
            "f" * 64: _accepted(candidate, proof),
        },
    )

    for returned in malformed_results:
        class Verifier:
            def verify_batch(self, _candidates):
                return returned

        service = TemporalProofService(
            kg=lambda *_a, **_k: [],
            ledger_kg_tx=world.tx,
            hist=world.hist,
            independent_verifier=Verifier(),
        )
        result = service._apply_independent_verifier(
            {"n": proof}, {"n": candidate}
        )["n"]

        assert result.component_ok is True
        assert result.chain_ok is True
        assert result.l3_eligible is False
        assert result.reason == "independent_verifier_unavailable"
        assert result.independent_verifier is None
        assert result.time_authority is None


def test_service_does_not_reuse_one_accepted_result_for_two_candidates():
    world = _world_with_sidecar()
    proof = world.service().read_proof("T", "n")
    first = _candidate(world)
    second = replace(first, request_id="0" * 64)
    accepted_first = _accepted(first, proof)

    class Verifier:
        def verify_batch(self, _candidates):
            return {
                first.request_id: accepted_first,
                second.request_id: accepted_first,
            }

    service = TemporalProofService(
        kg=lambda *_a, **_k: [],
        ledger_kg_tx=world.tx,
        hist=world.hist,
        independent_verifier=Verifier(),
    )
    results = service._apply_independent_verifier(
        {"first": proof, "second": proof},
        {"first": first, "second": second},
    )

    assert results["first"].l3_eligible is True
    assert results["second"].l3_eligible is False
    assert results["second"].reason == "independent_verifier_unavailable"


def test_service_preserves_gate3_when_c1_explicitly_rejects():
    world = _world_with_sidecar()
    proof = world.service().read_proof("T", "n")
    candidate = _candidate(world)
    rejected = IndependentTemporalResult(
        request_id=candidate.request_id,
        accepted=False,
        reason="sidecar.splice",
        input_sha256="a" * 64,
    )

    class Verifier:
        def verify_batch(self, _candidates):
            return {candidate.request_id: rejected}

    service = TemporalProofService(
        kg=lambda *_a, **_k: [],
        ledger_kg_tx=world.tx,
        hist=world.hist,
        independent_verifier=Verifier(),
    )
    result = service._apply_independent_verifier(
        {"n": proof}, {"n": candidate}
    )["n"]

    assert result.component_ok is True
    assert result.chain_ok is True
    assert result.l3_eligible is False
    assert result.reason == "independent_verifier_rejected"
    assert result.independent_verifier is None
    assert result.time_authority is None
