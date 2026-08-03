from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from types import SimpleNamespace

from lakatos.write_cert import did_key_encode, ed25519_public_key
from server import storage_access
from server import storage_access_verify as verifier


PG_SECRET = bytes(range(32))
NEO_SECRET = bytes(range(32, 64))
FENCE_SECRET = bytes([91]) * 32


def _canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def _policy():
    return {
        "schema_version": storage_access.ACCESS_POLICY_SCHEMA,
        "environment": "production",
        "attestors": {
            "postgresql": did_key_encode(ed25519_public_key(PG_SECRET)),
            "neo4j": did_key_encode(ed25519_public_key(NEO_SECRET)),
        },
        "predeploy_authority": {
            "fence_verifier_sha256": "f" * 64,
            "fence_public_key_hex": ed25519_public_key(FENCE_SECRET).hex(),
        },
        "postgresql": {
            "host": "127.0.0.1", "port": 5432, "database": "lakatos",
            "owner_role": "lakatos_owner", "migrator_role": "lakatos_migrator",
            "runtime_role": "lakatos_runtime", "audit_role": "lakatos_audit",
            "runtime_profile_sha256": "8" * 64,
            "runtime_ca_sha256": "9" * 64,
            "migrator_owner_membership": {
                "admin_option": False, "inherit_option": False, "set_option": True,
            },
        },
        "neo4j": {
            "uri": "bolt+s://127.0.0.1:7687", "database": "neo4j",
            "audit_user": "lakatos_audit_user", "audit_role": "lakatos_audit_role",
            "migrator_user": "lakatos_migrator_user",
            "migrator_role": "lakatos_migrator_role",
            "runtime_user": "lakatos_runtime_user",
            "runtime_role": "lakatos_runtime_role",
        },
    }


def _write_read_only(path, value):
    raw = _canonical(value)
    path.write_bytes(raw)
    os.chmod(path, 0o400)
    return str(path.resolve()), hashlib.sha256(raw).hexdigest(), raw


def _settings(tmp_path):
    expires = "2026-08-02T00:05:00+00:00"
    startup = {
        "attestations": {
            store: {
                position: {"expires_at": expires}
                for position in ("before", "after")
            }
            for store in ("postgresql", "neo4j")
        }
    }
    policy_path, policy_sha, policy_raw = _write_read_only(
        tmp_path / "policy.json", _policy()
    )
    receipt_path, receipt_sha, receipt_raw = _write_read_only(
        tmp_path / "receipt.json", {"receipt": True}
    )
    pre_path, pre_sha, pre_raw = _write_read_only(
        tmp_path / "predeploy.json", {"phase": "predeploy"}
    )
    start_path, start_sha, start_raw = _write_read_only(
        tmp_path / "startup.json", startup
    )
    settings = SimpleNamespace(
        storage_access_policy=policy_path,
        storage_access_policy_sha256=policy_sha,
        storage_predeploy_receipt=receipt_path,
        storage_predeploy_receipt_sha256=receipt_sha,
        storage_access_predeploy_bundle=pre_path,
        storage_access_predeploy_bundle_sha256=pre_sha,
        storage_access_startup_bundle=start_path,
        storage_access_startup_bundle_sha256=start_sha,
        storage_environment="production",
        storage_fence_verifier_sha256="f" * 64,
        storage_fence_public_key_hex=ed25519_public_key(FENCE_SECRET).hex(),
        pg_host="127.0.0.1", pg_port=5432, pg_db="lakatos",
        pg_user="lakatos_runtime", neo4j_uri="bolt+s://127.0.0.1:7687",
        neo4j_database="neo4j", neo4j_user="lakatos_runtime_user",
        pg_runtime_binding=lambda: {
            "profile_sha256": "8" * 64, "ca_sha256": "9" * 64,
        },
    )
    return settings, (policy_raw, receipt_raw, pre_raw, start_raw)


def test_missing_pin_is_typed_not_ready_without_path_detail(tmp_path):
    settings, _raw = _settings(tmp_path)
    settings.storage_access_policy = None
    report = verifier.verify_pinned_storage_access(settings)
    assert report["status"] == "NOT_READY"
    assert report["failures"] == ["storage_access.policy.path_missing"]
    assert str(tmp_path) not in json.dumps(report)


def test_safe_files_are_passed_as_the_exact_pinned_raw_bytes(
    tmp_path, monkeypatch
):
    settings, expected_raw = _settings(tmp_path)
    captured = {}

    def fake(predeploy, startup, **kwargs):
        captured["values"] = (
            kwargs["policy_raw"], kwargs["predeploy_receipt_raw"],
            predeploy, startup,
        )
        return SimpleNamespace(status="ACCESS_PAIR_VERIFIED", failures=())

    monkeypatch.setattr(verifier, "verify_access_attestation_pair_bytes", fake)
    report = verifier.verify_pinned_storage_access(
        settings,
        evaluated_at=datetime(2026, 8, 2, 0, 3, tzinfo=timezone.utc),
        environ={},
    )
    assert report["status"] == "ACCESS_PAIR_VERIFIED"
    assert report["valid_until"] == "2026-08-02T00:05:00+00:00"
    assert captured["values"] == expected_raw


def test_runtime_principal_or_endpoint_decoy_is_rejected_before_pair_use(
    tmp_path, monkeypatch
):
    settings, _raw = _settings(tmp_path)
    settings.pg_user = "admin"
    monkeypatch.setattr(
        verifier,
        "verify_access_attestation_pair_bytes",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("pair verifier must not see a decoy runtime binding")
        ),
    )
    report = verifier.verify_pinned_storage_access(settings, environ={})
    assert report["failures"] == ["storage_access.runtime_binding_mismatch"]


def test_writable_or_hash_mismatched_pin_fails_before_parsing(tmp_path):
    settings, _raw = _settings(tmp_path)
    os.chmod(settings.storage_access_policy, 0o600)
    report = verifier.verify_pinned_storage_access(settings, environ={})
    assert report["failures"] == ["storage_access.policy.unsafe_file"]

    os.chmod(settings.storage_access_policy, 0o400)
    settings.storage_access_policy_sha256 = "0" * 64
    report = verifier.verify_pinned_storage_access(settings, environ={})
    assert report["failures"] == ["storage_access.policy.sha256_mismatch"]


def test_direct_app_path_rejects_one_shot_authority(tmp_path):
    settings, _raw = _settings(tmp_path)
    report = verifier.verify_pinned_storage_access(
        settings,
        environ={"LAKATOTREE_READINESS_PG_DSN": "credential-bearing"},
    )
    assert report["failures"] == ["storage_access.one_shot_authority_present"]


def test_cli_emits_only_sanitized_typed_result(monkeypatch, capsys):
    monkeypatch.setattr(
        verifier,
        "verify_pinned_storage_access",
        lambda _settings: verifier._not_ready("storage_access.policy.unavailable"),
    )
    assert verifier.main([]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "NOT_READY"
    assert output["failures"] == ["storage_access.policy.unavailable"]


def test_development_pair_report_carries_development_only_label(
    tmp_path, monkeypatch
):
    settings, _raw = _settings(tmp_path)
    monkeypatch.setattr(
        verifier,
        "verify_access_attestation_pair_bytes",
        lambda *_args, **_kwargs: SimpleNamespace(
            status="ACCESS_PAIR_VERIFIED",
            failures=(),
            deployment_status="DEVELOPMENT_ONLY",
            environment="development",
        ),
    )
    report = verifier.verify_pinned_storage_access(
        settings,
        evaluated_at=datetime(2026, 8, 2, 0, 3, tzinfo=timezone.utc),
        environ={},
    )
    assert report["status"] == "ACCESS_PAIR_VERIFIED"
    assert report["production_ready"] is False
    assert report["deployment_status"] == "DEVELOPMENT_ONLY"
    assert report["environment"] == "development"
