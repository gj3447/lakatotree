from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import hashlib
import os
from pathlib import Path
import sys

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from server import runtime_authority as authority
from server import runtime_authority_live as live
from server.storage_predeploy import fence_verifier_identity


NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)


def _artifact(*, wheel: bool = False):
    if wheel:
        return {
            "kind": "wheel-record",
            "version": "1.2.3",
            "installed_manifest_sha256": "a" * 64,
            "record_verified_files": 12,
            "stable_files": 14,
        }
    return {"kind": "git", "source_commit": "b" * 40}


def _lease(
    *,
    lease_id: str = "critique-history-writer-v1",
    generation: int = 7,
    backend_pid: int = 4242,
    advisory_key: list[int] | None = None,
):
    return {
        "lease_id": lease_id,
        "owner_token_sha256": "c" * 64,
        "generation": generation,
        "postgresql_backend_pid": backend_pid,
        "postgresql_advisory_key": advisory_key or [1279349588, 20260802],
    }


def _challenge(*, wheel: bool = False, lease=None, environment="production"):
    return authority.build_runtime_challenge(
        nonce="d" * 64,
        environment=environment,
        boot_id="e" * 64,
        artifact=_artifact(wheel=wheel),
        operation_sha256="1" * 64,
        target_sha256="2" * 64,
        storage_access_policy_file_sha256="3" * 64,
        predeploy_receipt_file_sha256="4" * 64,
        predeploy_receipt_sha256="5" * 64,
        startup_bundle_file_sha256="6" * 64,
        historical_drain_lease_id_sha256="7" * 64,
        runtime_writer_lease=lease or _lease(),
        workers=[{"worker_id": "8" * 64, "boot_id": "e" * 64}],
    )


def _keypair():
    private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("09" * 32))
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    ).hex()
    return private, public


def _response(challenge, *, mutate=None, observed=NOW, expires=None):
    expires = expires or NOW + timedelta(seconds=20)
    body = {
        "schema_version": authority.RUNTIME_SNAPSHOT_SCHEMA,
        "challenge_sha256": authority.challenge_sha256(challenge),
        "nonce": challenge["nonce"],
        "environment": challenge["environment"],
        "effect_scope": challenge["effect_scope"],
        "active": True,
        "boot_id": challenge["boot_id"],
        "artifact": challenge["artifact"],
        "artifact_identity_sha256": challenge["artifact_identity_sha256"],
        "operation_sha256": challenge["operation_sha256"],
        "target_sha256": challenge["target_sha256"],
        "storage_access_policy_file_sha256": challenge[
            "storage_access_policy_file_sha256"
        ],
        "predeploy_receipt_file_sha256": challenge[
            "predeploy_receipt_file_sha256"
        ],
        "predeploy_receipt_sha256": challenge["predeploy_receipt_sha256"],
        "startup_bundle_file_sha256": challenge["startup_bundle_file_sha256"],
        "historical_drain_lease_id_sha256": challenge[
            "historical_drain_lease_id_sha256"
        ],
        "runtime_writer_lease": challenge["runtime_writer_lease"],
        "workers": challenge["workers"],
        "observed_at": observed.isoformat(),
        "expires_at": expires.isoformat(),
        "evidence_refs": ["9" * 64],
    }
    if mutate is not None:
        mutate(body)
    private, public = _keypair()
    signature = private.sign(authority.signing_bytes(body)).hex()
    return authority.canonical_json({**body, "signature": signature}), public


@pytest.mark.parametrize("wheel", [False, True])
def test_runtime_snapshot_accepts_git_and_wheel_artifact_identity(wheel):
    challenge = _challenge(wheel=wheel)
    raw, public = _response(challenge)

    proof = authority.verify_runtime_snapshot(
        raw,
        challenge=challenge,
        public_key_hex=public,
        evaluated_at=NOW,
        authority_not_after=NOW + timedelta(minutes=1),
    )

    assert proof.artifact["kind"] == ("wheel-record" if wheel else "git")
    assert proof.body_sha256 == authority.sha256_bytes(
        authority.canonical_json(
            {key: value for key, value in json.loads(raw).items() if key != "signature"}
        )
    )
    report_text = json.dumps(proof.public_report(), sort_keys=True)
    assert "signature" not in report_text
    assert challenge["nonce"] not in report_text
    assert challenge["runtime_writer_lease"]["owner_token_sha256"] not in report_text
    assert proof.public_report()["production_ready"] is False


@pytest.mark.parametrize(
    "field,replacement",
    [
        ("nonce", "0" * 64),
        ("boot_id", "0" * 64),
        ("operation_sha256", "0" * 64),
        ("target_sha256", "0" * 64),
        ("predeploy_receipt_file_sha256", "0" * 64),
        ("startup_bundle_file_sha256", "0" * 64),
        ("effect_scope", "all-runtime-writes"),
        ("environment", "development"),
    ],
)
def test_runtime_snapshot_rejects_individually_resigned_binding_splices(
    field, replacement
):
    challenge = _challenge()
    raw, public = _response(
        challenge, mutate=lambda body: body.__setitem__(field, replacement)
    )

    with pytest.raises(authority.RuntimeAuthorityError, match="binding mismatches"):
        authority.verify_runtime_snapshot(
            raw,
            challenge=challenge,
            public_key_hex=public,
            evaluated_at=NOW,
            authority_not_after=NOW + timedelta(minutes=1),
        )


def test_development_snapshot_verifies_but_is_development_only():
    challenge = _challenge(environment="development")
    raw, public = _response(challenge)

    proof = authority.verify_runtime_snapshot(
        raw,
        challenge=challenge,
        public_key_hex=public,
        evaluated_at=NOW,
        authority_not_after=NOW + timedelta(minutes=1),
    )

    assert proof.environment == "development"
    report = proof.public_report()
    assert report["ok"] is True
    assert report["environment"] == "development"
    assert report["production_ready"] is False
    assert report["deployment_status"] == "DEVELOPMENT_ONLY"

    production_report = authority.verify_runtime_snapshot(
        _response(_challenge())[0],
        challenge=_challenge(),
        public_key_hex=public,
        evaluated_at=NOW,
        authority_not_after=NOW + timedelta(minutes=1),
    ).public_report()
    assert production_report["environment"] == "production"
    assert production_report["deployment_status"] == "NOT_READY"


def test_runtime_challenge_rejects_undeclared_environments():
    for environment in ("staging", "prod", "", None):
        with pytest.raises(
            authority.RuntimeAuthorityError, match="must be production"
        ):
            _challenge(environment=environment)


def test_runtime_snapshot_rejects_drain_lease_as_runtime_lease():
    lease = _lease(lease_id="migration-drain-lease")
    historical = authority.sha256_bytes(lease["lease_id"].encode())
    with pytest.raises(authority.RuntimeAuthorityError, match="historical drain"):
        authority.build_runtime_challenge(
            nonce="d" * 64,
            environment="production",
            boot_id="e" * 64,
            artifact=_artifact(),
            operation_sha256="1" * 64,
            target_sha256="2" * 64,
            storage_access_policy_file_sha256="3" * 64,
            predeploy_receipt_file_sha256="4" * 64,
            predeploy_receipt_sha256="5" * 64,
            startup_bundle_file_sha256="6" * 64,
            historical_drain_lease_id_sha256=historical,
            runtime_writer_lease=lease,
            workers=[{"worker_id": "8" * 64, "boot_id": "e" * 64}],
        )


def test_runtime_snapshot_rejects_expiry_outer_authority_and_wrong_key():
    challenge = _challenge()
    raw, public = _response(challenge, expires=NOW + timedelta(minutes=2))
    with pytest.raises(authority.RuntimeAuthorityError, match="exceeds"):
        authority.verify_runtime_snapshot(
            raw,
            challenge=challenge,
            public_key_hex=public,
            evaluated_at=NOW,
            authority_not_after=NOW + timedelta(seconds=30),
        )
    with pytest.raises(authority.RuntimeAuthorityError, match="signature"):
        authority.verify_runtime_snapshot(
            raw,
            challenge=challenge,
            public_key_hex="f" * 64,
            evaluated_at=NOW,
            authority_not_after=NOW + timedelta(minutes=3),
        )


def test_snapshot_current_check_binds_full_lease_boot_and_margin():
    challenge = _challenge()
    raw, public = _response(challenge)
    proof = authority.verify_runtime_snapshot(
        raw,
        challenge=challenge,
        public_key_hex=public,
        evaluated_at=NOW,
        authority_not_after=NOW + timedelta(minutes=1),
    )
    assert authority.snapshot_is_current(
        proof,
        boot_id=challenge["boot_id"],
        lease=_lease(),
        evaluated_at=NOW,
        commit_margin_seconds=1,
    )
    assert not authority.snapshot_is_current(
        proof,
        boot_id="0" * 64,
        lease=_lease(),
        evaluated_at=NOW,
    )
    assert not authority.snapshot_is_current(
        proof,
        boot_id=challenge["boot_id"],
        lease=_lease(generation=8),
        evaluated_at=NOW,
    )
    assert not authority.snapshot_is_current(
        proof,
        boot_id=challenge["boot_id"],
        lease=_lease(backend_pid=4243),
        evaluated_at=NOW,
    )
    assert not authority.snapshot_is_current(
        proof,
        boot_id=challenge["boot_id"],
        lease=_lease(advisory_key=[1279349588, 20260803]),
        evaluated_at=NOW,
    )
    assert not authority.snapshot_is_current(
        proof,
        boot_id=challenge["boot_id"],
        lease=_lease(),
        evaluated_at=NOW + timedelta(seconds=19),
        commit_margin_seconds=1,
    )


def test_live_adapter_executes_exact_pinned_copy_and_verifies_reply(
    tmp_path, monkeypatch
):
    _private, public = _keypair()
    interpreter = Path(sys._base_executable).resolve()
    script = tmp_path / "runtime-authority"
    script.write_text(
        f"""#!{interpreter}
import sys
sys.stdout.buffer.write(sys.stdin.buffer.read())
""",
        encoding="utf-8",
    )
    os.chmod(script, 0o500)
    identity = fence_verifier_identity(script)
    not_after = datetime.now(timezone.utc) + timedelta(minutes=1)
    sentinel = object()

    def verify_echo(raw, *, challenge, public_key_hex, evaluated_at, authority_not_after):
        assert json.loads(raw) == challenge
        assert public_key_hex == public
        assert evaluated_at.tzinfo is not None
        assert authority_not_after == not_after
        return sentinel

    monkeypatch.setattr(live, "verify_runtime_snapshot", verify_echo)

    proof = live.challenge_runtime_authority(
        executable=script,
        expected_executable_sha256=identity["sha256"],
        public_key_hex=public,
        environment="production",
        boot_id="e" * 64,
        artifact=_artifact(),
        operation_sha256="1" * 64,
        target_sha256="2" * 64,
        storage_access_policy_file_sha256="3" * 64,
        predeploy_receipt_file_sha256="4" * 64,
        predeploy_receipt_sha256="5" * 64,
        startup_bundle_file_sha256="6" * 64,
        historical_drain_lease_id_sha256="7" * 64,
        runtime_writer_lease=_lease(),
        workers=[{"worker_id": "8" * 64, "boot_id": "e" * 64}],
        authority_not_after=not_after,
        nonce_factory=lambda _size: "d" * 64,
    )

    assert proof is sentinel


@pytest.mark.parametrize(
    "stream,byte_count",
    [
        ("stdout", live.RUNTIME_AUTHORITY_STDOUT_MAX_BYTES + 1),
        ("stderr", live.RUNTIME_AUTHORITY_STDERR_MAX_BYTES + 1),
    ],
)
def test_live_adapter_rejects_signer_output_over_byte_cap(
    tmp_path, stream, byte_count
):
    _private, public = _keypair()
    interpreter = Path(sys._base_executable).resolve()
    script = tmp_path / f"runtime-authority-{stream}"
    script.write_text(
        f"""#!{interpreter}
import sys
sys.{stream}.buffer.write(b'x' * {byte_count})
sys.{stream}.buffer.flush()
""",
        encoding="utf-8",
    )
    os.chmod(script, 0o500)
    identity = fence_verifier_identity(script)

    with pytest.raises(authority.RuntimeAuthorityError, match="byte limit"):
        live.challenge_runtime_authority(
            executable=script,
            expected_executable_sha256=identity["sha256"],
            public_key_hex=public,
            environment="production",
            boot_id="e" * 64,
            artifact=_artifact(),
            operation_sha256="1" * 64,
            target_sha256="2" * 64,
            storage_access_policy_file_sha256="3" * 64,
            predeploy_receipt_file_sha256="4" * 64,
            predeploy_receipt_sha256="5" * 64,
            startup_bundle_file_sha256="6" * 64,
            historical_drain_lease_id_sha256="7" * 64,
            runtime_writer_lease=_lease(),
            workers=[{"worker_id": "8" * 64, "boot_id": "e" * 64}],
            authority_not_after=datetime.now(timezone.utc) + timedelta(minutes=1),
            nonce_factory=lambda _size: "d" * 64,
        )


def test_runtime_authority_cli_verifies_only_pinned_public_files(tmp_path, capsys):
    challenge = _challenge()
    raw, public = _response(challenge)
    snapshot_path = (tmp_path / "snapshot.json").resolve()
    artifact_path = (tmp_path / "artifact.json").resolve()
    snapshot_path.write_bytes(raw)
    artifact_raw = authority.canonical_json(challenge["artifact"])
    artifact_path.write_bytes(artifact_raw)

    result = authority.main([
        "--snapshot", str(snapshot_path),
        "--snapshot-sha256", hashlib.sha256(raw).hexdigest(),
        "--expected-artifact", str(artifact_path),
        "--expected-artifact-sha256", hashlib.sha256(artifact_raw).hexdigest(),
        "--public-key-hex", public,
        "--evaluated-at", NOW.isoformat(),
    ])

    assert result == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert "signature" not in report
    assert challenge["nonce"] not in json.dumps(report, sort_keys=True)

    result = authority.main([
        "--snapshot", str(snapshot_path),
        "--snapshot-sha256", "0" * 64,
        "--expected-artifact", str(artifact_path),
        "--expected-artifact-sha256", hashlib.sha256(artifact_raw).hexdigest(),
        "--public-key-hex", public,
        "--evaluated-at", NOW.isoformat(),
    ])
    assert result == 1
    assert json.loads(capsys.readouterr().out)["status"] == "NOT_READY"
