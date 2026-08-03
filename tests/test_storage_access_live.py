from __future__ import annotations

import hashlib
import json
import os
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from lakatos.write_cert import did_key_encode, ed25519_public_key
from server import production_readiness_live as live
from server import storage_access
from server import storage_access_live as producer
from server import storage_predeploy


PG_SECRET = bytes(range(32))
NEO_SECRET = bytes(range(32, 64))
FENCE_SECRET = bytes([91]) * 32
ARTIFACT = {"kind": "git", "source_commit": "3" * 40}
OPERATION = storage_predeploy.operation_identity(ARTIFACT)


def _canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def _write_json(path, value):
    raw = _canonical(value)
    if path.exists():
        if path.read_bytes() != raw:
            raise AssertionError("test attempted to replace a pinned JSON artifact")
    else:
        path.write_bytes(raw)
        os.chmod(path, 0o400)
    return {"path": str(path.resolve()), "file_sha256": hashlib.sha256(raw).hexdigest()}


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
            "host": "127.0.0.1",
            "port": 5432,
            "database": "lakatos",
            "owner_role": "lakatos_owner",
            "migrator_role": "lakatos_migrator",
            "runtime_role": "lakatos_runtime",
            "audit_role": "lakatos_audit",
            "runtime_profile_sha256": "8" * 64,
            "runtime_ca_sha256": "9" * 64,
            "migrator_owner_membership": {
                "admin_option": False,
                "inherit_option": False,
                "set_option": True,
            },
        },
        "neo4j": {
            "uri": "bolt+s://127.0.0.1:7687",
            "database": "neo4j",
            "audit_user": "lakatos_audit_user",
            "audit_role": "lakatos_audit_role",
            "migrator_user": "lakatos_migrator_user",
            "migrator_role": "lakatos_migrator_role",
            "runtime_user": "lakatos_runtime_user",
            "runtime_role": "lakatos_runtime_role",
        },
    }


def _target_details():
    return {
        "postgresql": {
            "configured_host": "127.0.0.1",
            "configured_port": 5432,
            "configured_database": "lakatos",
            "database": "lakatos",
            "database_oid": "16384",
            "server_address": "127.0.0.1",
            "server_port": 5432,
            "server_version_num": "170000",
            "system_identifier": "123456789",
        },
        "neo4j": {
            "configured_uri": "bolt+s://127.0.0.1:7687",
            "configured_database": "neo4j",
            "database_id": "neo4j-db-id",
            "database_name": "neo4j",
        },
    }


def _signed_fence_response(body):
    return {
        **body,
        "signature": Ed25519PrivateKey.from_private_bytes(FENCE_SECRET).sign(
            storage_predeploy._fence_signing_payload(body)
        ).hex(),
    }


def _predeploy_receipt(target_sha, *, artifact=ARTIFACT):
    operation = storage_predeploy.operation_identity(artifact)
    report = {
        "contract_id": storage_predeploy.CONTRACT_ID,
        "ok": True,
        "failures": [],
        "details": {},
    }
    live_fence_body = {
        "schema_version": storage_predeploy.FENCE_VERIFICATION_SCHEMA,
        "active": True,
        "nonce": "d" * 64,
        "environment": "production",
        "target_sha256": target_sha,
        "operation_sha256": operation["sha256"],
        "lease_id": "lease-storage-access-test",
        "drain_receipt_sha256": "d" * 64,
        "verified_at": "2026-08-01T23:59:54+00:00",
        "expires_at": "2026-08-02T00:00:40+00:00",
        "evidence_refs": ["lease-store://exact-readback"],
    }
    body = {
        "schema_version": storage_predeploy.RECEIPT_SCHEMA,
        "contract_id": storage_predeploy.CONTRACT_ID,
        "environment": "production",
        "artifact": artifact,
        "operation": operation,
        "target_sha256": target_sha,
        "target": _target_details(),
        "principals": storage_predeploy.principal_bindings(
            postgresql_migrator="lakatos_migrator",
            postgresql_runtime="lakatos_runtime",
            neo4j_migrator="lakatos_migrator_user",
            neo4j_runtime="lakatos_runtime_user",
        ),
        "writer_drain": {
            "sha256": "d" * 64,
            "schema_version": storage_predeploy.DRAIN_SCHEMA,
            "environment": "production",
            "lease_id": "lease-storage-access-test",
            "verified_at": "2026-08-01T23:59:00+00:00",
            "expires_at": "2026-08-02T00:10:00+00:00",
            "target_sha256": target_sha,
            "operation_sha256": operation["sha256"],
            "evidence_refs": ["ops://drain/readback/storage-access-test"],
            "live_fence": {
                "schema_version": storage_predeploy.FENCE_VERIFICATION_SCHEMA,
                "verifier_sha256": "f" * 64,
                "authority_key_sha256": storage_predeploy._fence_authority_sha256(
                    ed25519_public_key(FENCE_SECRET).hex()
                ),
                "signed_response": _signed_fence_response(live_fence_body),
                "verified_at": live_fence_body["verified_at"],
                "expires_at": live_fence_body["expires_at"],
                "evidence_refs": live_fence_body["evidence_refs"],
            },
        },
        "postgresql": {"ok": True, "report": report},
        "neo4j": {
            "ok": True,
            "migration_ok": True,
            "payload_normalization": {
                "schema_version": storage_predeploy.NORMALIZATION_RECEIPT_SCHEMA,
                "before": {"row_count": 0, "projection_sha256": "a" * 64},
                "after": {"row_count": 0, "projection_sha256": "a" * 64},
                "updated_count": 0,
            },
            "report": report,
        },
        "created_at": "2026-08-01T23:59:55+00:00",
    }
    return {
        **body,
        "receipt_sha256": hashlib.sha256(_canonical(body)).hexdigest(),
    }


def _request(tmp_path, *, phase="predeploy", previous=None, artifact=ARTIFACT):
    details = _target_details()
    target_sha = hashlib.sha256(_canonical(details)).hexdigest()
    policy_ref = _write_json(tmp_path / "policy.json", _policy())
    predeploy_ref = _write_json(
        tmp_path / "predeploy.json",
        _predeploy_receipt(target_sha, artifact=artifact),
    )
    return {
        "schema_version": producer.REQUEST_SCHEMA,
        "phase": phase,
        "request_nonce": ("1" if phase == "predeploy" else "2") * 64,
        "environment": "production",
        "target_sha256": target_sha,
        "operation_sha256": storage_predeploy.operation_identity(artifact)["sha256"],
        "access_policy": policy_ref,
        "predeploy_receipt": predeploy_ref,
        "previous_phase_bundle": previous,
        "timeout_seconds": 3,
    }


def _pg_attributes(login):
    return {
        "login": login, "superuser": False, "createdb": False,
        "createrole": False, "inherit": False, "bypassrls": False,
        "replication": False,
    }


def _pg_required_acl():
    rows = [
        {
            "scope": "database",
            "object_sha256": hashlib.sha256(b"lakatos").hexdigest(),
            "grantor": "owner",
            "grantee": label,
            "privilege": "CONNECT",
            "grantable": False,
        }
        for label in ("migrator", "runtime", "audit")
    ]
    rows.append({
        "scope": "schema",
        "object_sha256": hashlib.sha256(b"public").hexdigest(),
        "grantor": "owner",
        "grantee": "runtime",
        "privilege": "USAGE",
        "grantable": False,
    })
    rows.extend(
        {
            "scope": "relation",
            "object_sha256": hashlib.sha256(name.encode()).hexdigest(),
            "grantor": "owner",
            "grantee": "runtime",
            "privilege": privilege,
            "grantable": False,
        }
        for name in storage_access._PG_TABLES
        for privilege in ("SELECT", "INSERT")
    )
    rows.extend(
        {
            "scope": "sequence",
            "object_sha256": hashlib.sha256(name.encode()).hexdigest(),
            "grantor": "owner",
            "grantee": "runtime",
            "privilege": privilege,
            "grantable": False,
        }
        for name in storage_access._PG_SEQUENCES
        for privilege in ("SELECT", "USAGE")
    )
    return sorted(rows, key=_canonical)


def _pg_result(*, read_only=True, database_oid="16384", nonce="1" * 64):
    roles = {
        "owner": "lakatos_owner", "migrator": "lakatos_migrator",
        "runtime": "lakatos_runtime", "audit": "lakatos_audit",
    }
    hashes = {key: hashlib.sha256(value.encode()).hexdigest() for key, value in roles.items()}
    empty = hashlib.sha256(_canonical([])).hexdigest()
    acl_projection = _pg_required_acl()
    objects = {
        name: {
            "exists": True, "owner_class": "owner",
            "runtime_privileges": ["SELECT", "INSERT"],
            "runtime_column_privilege_count": 0,
            "runtime_column_privilege_sha256": empty,
            "runtime_column_only_privileges": [],
        }
        for name in storage_access._PG_TABLES
    }
    objects.update({
        name: {"exists": True, "owner_class": "owner", "runtime_privileges": ["SELECT", "USAGE"]}
        for name in storage_access._PG_SEQUENCES
    })
    facts = {
        "database": "lakatos", "database_matches": True,
        "database_oid_sha256": hashlib.sha256(database_oid.encode()).hexdigest(),
        "system_identifier_sha256": hashlib.sha256(b"123456789").hexdigest(),
        "transaction_read_only": True,
        "challenge_nonce_sha256": hashlib.sha256(nonce.encode()).hexdigest(),
        "current_actor_class": "audit", "current_actor_sha256": hashes["audit"],
        "session_actor_sha256": hashes["audit"], "roles_distinct": True,
        "roles": {
            label: {
                "name_sha256": hashes[label], "present": True,
                "attributes": _pg_attributes(label != "owner"),
            }
            for label in roles
        },
        "objects": objects, "public_schema_owner_class": "owner",
        "acl_projection_scope": "contract-objects-v1",
        "acl_projection_count": len(acl_projection),
        "acl_projection_sha256": hashlib.sha256(
            _canonical(acl_projection)
        ).hexdigest(),
        "acl_projection": acl_projection,
        "grantable_acl_counts": {label: 0 for label in roles},
        "public_acl_entry_counts": {
            scope: 0 for scope in ("database", "schema", "relation", "sequence", "column")
        },
        "runtime_effective_role_sha256": [hashes["runtime"]],
        "role_effective_membership_sha256": {
            "owner": [hashes["owner"]],
            "migrator": [hashes["migrator"], hashes["owner"]],
            "runtime": [hashes["runtime"]], "audit": [hashes["audit"]],
        },
        "role_inbound_membership_sha256": {
            "owner": [hashes["migrator"]],
            "migrator": [], "runtime": [], "audit": [],
        },
        "migrator_owner_membership": {
            "admin_option": False, "inherit_option": False, "set_option": True,
        },
        "role_owned_user_object_count": {
            "owner": 8, "migrator": 0, "runtime": 0, "audit": 0,
        },
        "role_user_function_execute_count": {label: 0 for label in roles},
        "runtime_database_create": False, "runtime_database_temp": False,
        "runtime_schema_create": False, "runtime_schema_create_count": 0,
        "runtime_schema_create_sha256": empty,
        "runtime_schema_usage": True, "audit_principal_read_only": read_only,
        "runtime_out_of_contract_write_privilege_count": 0,
        "runtime_out_of_contract_write_privilege_sha256": empty,
        "runtime_out_of_contract_read_privilege_count": 0,
        "runtime_out_of_contract_read_privilege_sha256": empty,
        "authority_boundary_deviation_count": 0,
        "authority_boundary_deviation_sha256": empty,
        "audit_effective_role_sha256": [hashes["audit"]],
        "audit_database_create": False, "audit_database_temp": False,
        "audit_schema_create": False, "audit_schema_create_count": 0,
        "audit_schema_create_sha256": empty,
        "audit_data_read_privilege_count": 0,
        "audit_data_read_privilege_sha256": empty,
        "audit_write_privilege_count": 0, "audit_write_privilege_sha256": empty,
        "audit_column_write_privilege_count": 0,
        "audit_column_write_privilege_sha256": empty,
    }
    return live.AdapterResult("OBSERVED", facts, binding_material=_target_details()["postgresql"])


def _neo_row(action, *, segment=None, graph=None):
    if action == "access":
        resource, graph, segment = "database", graph or "neo4j", "database"
    elif action == "match":
        resource, graph, segment = "all_properties", "neo4j", segment or "NODE(*)"
    elif action == "write":
        resource, graph, segment = "graph", "neo4j", segment or "NODE(*)"
    elif action in {"constraint", "token"}:
        resource, graph, segment = "database", "neo4j", "database"
    elif action == "execute":
        resource, graph = "database", "*"
    elif action in {"show_alias", "show_database", "show_user", "show_privilege"}:
        resource, graph, segment = "database", "*", "database"
    elif action == "show_setting":
        resource, graph = "database", "*"
    else:
        raise AssertionError(f"unsupported test privilege action: {action}")
    return {
        "access": "GRANTED", "action": action, "resource": resource,
        "graph": graph, "segment": segment, "immutable": False,
    }


def _neo_data_role(*, migrator=False):
    rows = [
        _neo_row("access"),
        _neo_row("match", segment="NODE(*)"),
        _neo_row("match", segment="RELATIONSHIP(*)"),
        _neo_row("write", segment="NODE(*)"),
        _neo_row("write", segment="RELATIONSHIP(*)"),
    ]
    if migrator:
        rows.extend([_neo_row("constraint"), _neo_row("token")])
    return rows


def _neo_audit_role():
    rows = [
        _neo_row("access"),
        _neo_row("access", graph="system"),
        _neo_row("execute", segment="PROCEDURE(db.info)"),
        _neo_row("execute", segment="PROCEDURE(dbms.components)"),
        _neo_row("show_privilege"),
        _neo_row("show_user"),
        _neo_row("show_alias"),
        _neo_row("show_database"),
    ]
    rows.extend(
        _neo_row("show_setting", segment=f"SETTING({name})")
        for name in live._NEO_AUTH_SETTING_NAMES
    )
    return rows


def _neo_auth_settings():
    values = {
        "dbms.security.auth_enabled": "true",
        "dbms.security.authentication_providers": "native",
        "dbms.security.authorization_providers": "native",
        "dbms.security.abac.authorization_providers": "",
    }
    return [
        {"name": name, "value": values[name], "startup_value": values[name]}
        for name in live._NEO_AUTH_SETTING_NAMES
    ]


def _neo_result(*, read_only=True, database_id="neo4j-db-id", nonce="1" * 64):
    policy = _policy()["neo4j"]
    runtime = _neo_data_role()
    migrator = _neo_data_role(migrator=True)
    named = {
        "audit": _neo_audit_role(), "migrator": migrator,
        "runtime": runtime, "public": [],
    }
    role_hashes = {
        label: hashlib.sha256(policy[f"{label}_role"].encode()).hexdigest()
        for label in ("audit", "migrator", "runtime")
    }
    public_hash = hashlib.sha256(b"PUBLIC").hexdigest()
    effective = list(named["audit"])
    empty = hashlib.sha256(_canonical([])).hexdigest()
    facts = {
        "database": "neo4j",
        "challenge_nonce_sha256": hashlib.sha256(nonce.encode()).hexdigest(),
        "database_name_matches": True,
        "database_direct_local": True,
        "database_alias_count": 0,
        "database_alias_sha256": empty,
        "database_catalog_sha256": hashlib.sha256(_canonical([{
            "name_sha256": hashlib.sha256(b"neo4j").hexdigest(),
            "type": "standard", "current_status": "online",
        }])).hexdigest(),
        "database_id_sha256": hashlib.sha256(database_id.encode()).hexdigest(),
        "edition": "enterprise", "version": "2026.06.0", "enterprise": True,
        "current_actor_sha256": hashlib.sha256(policy["audit_user"].encode()).hexdigest(),
        "role_sha256": sorted([role_hashes["audit"], public_hash]), "role_count": 2,
        "effective_privilege_sha256": hashlib.sha256(_canonical(effective)).hexdigest(),
        "effective_privilege_count": len(effective), "effective_privileges": effective,
        "audit_principal_read_only": read_only,
        "audit_unsafe_granted_action_count": 0,
        "audit_unsafe_granted_action_sha256": empty,
        "named_role_sha256": role_hashes,
        "named_role_privilege_sha256": {
            label: hashlib.sha256(_canonical(named[label])).hexdigest()
            for label in ("audit", "migrator", "runtime")
        },
        "named_role_privileges": named,
        "public_role_binding_sha256": hashlib.sha256(_canonical(named["public"])).hexdigest(),
        "custom_role_binding_ok": True,
        "named_user_role_sha256": {
            label: sorted([role_hashes[label], public_hash]) for label in role_hashes
        },
        "named_role_assignee_sha256": {
            label: [hashlib.sha256(policy[f"{label}_user"].encode()).hexdigest()]
            for label in ("audit", "migrator", "runtime")
        },
        "named_user_role_binding_ok": True, "runtime_role_least_privilege": True,
        "migrator_role_least_privilege": True, "public_role_safe": True,
        "auth_settings": _neo_auth_settings(),
        "auth_settings_sha256": hashlib.sha256(_canonical(_neo_auth_settings())).hexdigest(),
        "native_only_auth": True,
        "global_unsafe_privilege_count": 0,
        "global_unsafe_privilege_sha256": empty,
        "system_database_id_sha256": hashlib.sha256(b"system-db-id").hexdigest(),
        "system_last_committed_tx": 41,
        "authorization_snapshot_stable": True,
        "read_query_count": 12,
    }
    return live.AdapterResult("OBSERVED", facts, binding_material=_target_details()["neo4j"])


@pytest.fixture(autouse=True)
def _stable_artifact_identity(monkeypatch):
    monkeypatch.setattr(producer, "_artifact_identity", lambda: dict(ARTIFACT))
    monkeypatch.setattr(storage_predeploy, "_artifact_identity", lambda: dict(ARTIFACT))


def _ports(pg, neo):
    def unused(config, timeout, environ):
        raise AssertionError("unused adapter called")

    return live.CollectorPorts(
        runtime=unused,
        postgresql=pg,
        neo4j=neo,
        predeploy=unused,
        temporal=unused,
    )


def _clock(start=None):
    current = start or datetime(2026, 8, 2, tzinfo=timezone.utc)

    def now():
        nonlocal current
        value = current
        current += timedelta(seconds=1)
        return value

    return now


def _phase_pair_artifacts(tmp_path, *, artifact=ARTIFACT):
    ports = _ports(
        lambda config, timeout, environ: _pg_result(
            nonce=config["challenge_nonce"]
        ),
        lambda config, timeout, environ: _neo_result(
            nonce=config["challenge_nonce"]
        ),
    )
    predeploy_request = _request(tmp_path, artifact=artifact)
    predeploy_bundle = producer.collect_signed_storage_audit(
        predeploy_request,
        request_file_sha256=hashlib.sha256(
            _canonical(predeploy_request)
        ).hexdigest(),
        signing_seeds={"postgresql": PG_SECRET, "neo4j": NEO_SECRET},
        ports=ports,
        environ={},
        now=_clock(),
    )
    previous_ref = _write_json(
        tmp_path / "predeploy-bundle.json", predeploy_bundle
    )
    startup_dir = tmp_path / "startup"
    startup_dir.mkdir()
    startup_request = _request(
        startup_dir, phase="startup", previous=previous_ref, artifact=artifact
    )
    startup_bundle = producer.collect_signed_storage_audit(
        startup_request,
        request_file_sha256=hashlib.sha256(
            _canonical(startup_request)
        ).hexdigest(),
        signing_seeds={"postgresql": PG_SECRET, "neo4j": NEO_SECRET},
        ports=ports,
        environ={},
        now=_clock(datetime(2026, 8, 2, 0, 2, tzinfo=timezone.utc)),
    )
    policy_raw = Path(predeploy_request["access_policy"]["path"]).read_bytes()
    receipt_raw = Path(predeploy_request["predeploy_receipt"]["path"]).read_bytes()
    predeploy_raw = _canonical(predeploy_bundle)
    startup_raw = _canonical(startup_bundle)
    return {
        "policy": policy_raw,
        "receipt": receipt_raw,
        "predeploy": predeploy_raw,
        "startup": startup_raw,
    }


def _verify_phase_pair_raw(artifacts, **overrides):
    values = {
        "expected_predeploy_file_sha256": hashlib.sha256(
            artifacts["predeploy"]
        ).hexdigest(),
        "expected_startup_file_sha256": hashlib.sha256(
            artifacts["startup"]
        ).hexdigest(),
        "policy_raw": artifacts["policy"],
        "expected_policy_file_sha256": hashlib.sha256(
            artifacts["policy"]
        ).hexdigest(),
        "predeploy_receipt_raw": artifacts["receipt"],
        "expected_predeploy_receipt_file_sha256": hashlib.sha256(
            artifacts["receipt"]
        ).hexdigest(),
        "evaluated_at": datetime(2026, 8, 2, 0, 3, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return storage_access.verify_access_attestation_pair_bytes(
        artifacts["predeploy"], artifacts["startup"], **values
    )


def test_producer_signs_separate_store_before_after_and_self_verifies(tmp_path):
    request = _request(tmp_path)
    request_sha = hashlib.sha256(_canonical(request)).hexdigest()
    bundle = producer.collect_signed_storage_audit(
        request,
        request_file_sha256=request_sha,
        signing_seeds={"postgresql": PG_SECRET, "neo4j": NEO_SECRET},
        ports=_ports(
            lambda config, timeout, environ: _pg_result(
                nonce=config["challenge_nonce"]
            ),
            lambda config, timeout, environ: _neo_result(
                nonce=config["challenge_nonce"]
            ),
        ),
        environ={},
        now=_clock(),
    )
    assert bundle["phase"] == "predeploy"
    assert bundle["request_sha256"] == request_sha
    assert set(bundle["attestations"]) == {"postgresql", "neo4j"}
    assert all(
        set(bundle["attestations"][store]) == {"before", "after"}
        for store in ("postgresql", "neo4j")
    )
    body = dict(bundle)
    bundle_sha = body.pop("bundle_sha256")
    assert bundle_sha == hashlib.sha256(_canonical(body)).hexdigest()
    assert "production_ready" not in json.dumps(bundle)


def test_complete_raw_phase_pair_binds_policy_v5_receipt_and_files(tmp_path):
    result = _verify_phase_pair_raw(_phase_pair_artifacts(tmp_path))
    assert result.status == "ACCESS_PAIR_VERIFIED"
    assert result.production_ready is False
    assert result.deployment_status == "NOT_READY"


def test_wheel_record_artifact_can_mint_and_verify_access_pair(
    tmp_path, monkeypatch
):
    artifact = {
        "kind": "wheel-record",
        "version": "0.1.0",
        "installed_manifest_sha256": "a" * 64,
        "record_verified_files": 32,
        "stable_files": 64,
    }
    monkeypatch.setattr(producer, "_artifact_identity", lambda: dict(artifact))
    monkeypatch.setattr(
        storage_predeploy, "_artifact_identity", lambda: dict(artifact)
    )
    artifacts = _phase_pair_artifacts(tmp_path, artifact=artifact)

    assert _verify_phase_pair_raw(artifacts).status == "ACCESS_PAIR_VERIFIED"


def test_raw_pair_rejects_pin_duplicate_policy_receipt_and_artifact_splices(
    tmp_path, monkeypatch
):
    artifacts = _phase_pair_artifacts(tmp_path)

    wrong_pin = _verify_phase_pair_raw(
        artifacts, expected_predeploy_file_sha256="0" * 64
    )
    assert wrong_pin.status == "NOT_READY"
    assert wrong_pin.failures == ("access_pair.malformed",)

    duplicate_policy = artifacts["policy"].replace(
        b'{"attestors":', b'{"attestors":{},"attestors":', 1
    )
    duplicate = _verify_phase_pair_raw(
        artifacts,
        policy_raw=duplicate_policy,
        expected_policy_file_sha256=hashlib.sha256(duplicate_policy).hexdigest(),
    )
    assert duplicate.status == "NOT_READY"

    noncanonical_startup = b"\n" + artifacts["startup"]
    noncanonical = storage_access.verify_access_attestation_pair_bytes(
        artifacts["predeploy"],
        noncanonical_startup,
        expected_predeploy_file_sha256=hashlib.sha256(
            artifacts["predeploy"]
        ).hexdigest(),
        expected_startup_file_sha256=hashlib.sha256(
            noncanonical_startup
        ).hexdigest(),
        policy_raw=artifacts["policy"],
        expected_policy_file_sha256=hashlib.sha256(
            artifacts["policy"]
        ).hexdigest(),
        predeploy_receipt_raw=artifacts["receipt"],
        expected_predeploy_receipt_file_sha256=hashlib.sha256(
            artifacts["receipt"]
        ).hexdigest(),
        evaluated_at=datetime(2026, 8, 2, 0, 3, tzinfo=timezone.utc),
    )
    assert noncanonical.status == "NOT_READY"

    weak_receipt = _canonical({
        "schema_version": storage_predeploy.RECEIPT_SCHEMA,
        "receipt_sha256": "0" * 64,
    })
    weak = _verify_phase_pair_raw(
        artifacts,
        predeploy_receipt_raw=weak_receipt,
        expected_predeploy_receipt_file_sha256=hashlib.sha256(
            weak_receipt
        ).hexdigest(),
    )
    assert weak.status == "NOT_READY"

    monkeypatch.setattr(
        storage_predeploy,
        "_artifact_identity",
        lambda: {"kind": "git", "source_commit": "4" * 40},
    )
    wrong_artifact = _verify_phase_pair_raw(artifacts)
    assert wrong_artifact.status == "NOT_READY"


def test_producer_refuses_to_sign_a_non_read_only_audit_principal(tmp_path):
    request = _request(tmp_path)
    with pytest.raises(producer.StorageAuditCollectionError, match="not read-only"):
        producer.collect_signed_storage_audit(
            request,
            request_file_sha256=hashlib.sha256(_canonical(request)).hexdigest(),
            signing_seeds={"postgresql": PG_SECRET, "neo4j": NEO_SECRET},
            ports=_ports(
                lambda config, timeout, environ: _pg_result(
                    read_only=False, nonce=config["challenge_nonce"]
                ),
                lambda config, timeout, environ: _neo_result(
                    nonce=config["challenge_nonce"]
                ),
            ),
            environ={}, now=_clock(),
        )


def test_producer_detects_signed_before_after_drift(tmp_path):
    request = _request(tmp_path)
    calls = 0

    def pg(config, timeout, environ):
        nonlocal calls
        calls += 1
        return _pg_result(
            database_oid="16384" if calls == 1 else "16385",
            nonce=config["challenge_nonce"],
        )

    with pytest.raises(producer.StorageAuditCollectionError, match="self-verification"):
        producer.collect_signed_storage_audit(
            request,
            request_file_sha256=hashlib.sha256(_canonical(request)).hexdigest(),
            signing_seeds={"postgresql": PG_SECRET, "neo4j": NEO_SECRET},
            ports=_ports(
                pg,
                lambda config, timeout, environ: _neo_result(
                    nonce=config["challenge_nonce"]
                ),
            ),
            environ={}, now=_clock(),
        )


def test_startup_bundle_binds_exact_predeploy_bundle_file(tmp_path):
    predeploy = _request(tmp_path)
    predeploy_bundle = producer.collect_signed_storage_audit(
        predeploy,
        request_file_sha256=hashlib.sha256(_canonical(predeploy)).hexdigest(),
        signing_seeds={"postgresql": PG_SECRET, "neo4j": NEO_SECRET},
        ports=_ports(
            lambda config, timeout, environ: _pg_result(
                nonce=config["challenge_nonce"]
            ),
            lambda config, timeout, environ: _neo_result(
                nonce=config["challenge_nonce"]
            ),
        ),
        environ={}, now=_clock(),
    )
    previous_ref = _write_json(tmp_path / "predeploy-bundle.json", predeploy_bundle)
    startup_dir = tmp_path / "startup"
    startup_dir.mkdir()
    startup = _request(startup_dir, phase="startup", previous=previous_ref)
    bundle = producer.collect_signed_storage_audit(
        startup,
        request_file_sha256=hashlib.sha256(_canonical(startup)).hexdigest(),
        signing_seeds={"postgresql": PG_SECRET, "neo4j": NEO_SECRET},
        ports=_ports(
            lambda config, timeout, environ: _pg_result(
                nonce=config["challenge_nonce"]
            ),
            lambda config, timeout, environ: _neo_result(
                nonce=config["challenge_nonce"]
            ),
        ),
        environ={}, now=_clock(datetime(2026, 8, 2, 0, 2, tzinfo=timezone.utc)),
    )
    assert bundle["previous_phase_bundle_file_sha256"] == previous_ref["file_sha256"]


def test_signing_seed_loader_and_publication_require_private_immutable_files(tmp_path):
    key = (tmp_path / "key.raw").resolve()
    key.write_bytes(PG_SECRET)
    os.chmod(key, 0o600)
    assert producer.load_signing_seed(key) == PG_SECRET
    os.chmod(key, 0o644)
    with pytest.raises(producer.StorageAuditCollectionError, match="private raw"):
        producer.load_signing_seed(key)

    output = (tmp_path / "bundle.json").resolve()
    digest = producer._publish_read_only(output, {"value": 1})
    assert digest == hashlib.sha256(output.read_bytes()).hexdigest()
    assert stat.S_IMODE(output.stat().st_mode) == 0o400


def test_access_normalizer_preserves_bounded_acl_projection_above_legacy_limit():
    result = _pg_result()
    result.facts["acl_projection"] = [
        {
            "scope": "relation",
            "object_sha256": hashlib.sha256(f"object-{index}".encode()).hexdigest(),
            "grantor": "owner",
            "grantee": "runtime",
            "privilege": "SELECT",
            "grantable": False,
        }
        for index in range(96)
    ]
    normalized = live._normalize_result(
        "postgresql",
        result,
        max_fact_items=producer.MAX_ACCESS_FACT_ITEMS,
        max_list_items=512,
    )
    assert len(normalized["facts"]["acl_projection"]) == 96


def test_request_rejects_phase_smuggling_and_wrong_operation_identity(tmp_path):
    request = _request(tmp_path)
    request["environment"] = "prod"
    with pytest.raises(
        producer.StorageAuditCollectionError, match="must be production"
    ):
        producer.validate_request(request)
    request = _request(tmp_path)
    request["previous_phase_bundle"] = request["predeploy_receipt"]
    with pytest.raises(producer.StorageAuditCollectionError):
        producer.validate_request(request)
    request = _request(tmp_path)
    request["operation_sha256"] = "short"
    with pytest.raises(producer.StorageAuditCollectionError):
        producer.validate_request(request)


class _NeoAuditSession:
    def __init__(self, database, *, alias=False, rogue=False, marker_drift=False):
        self.database = database
        self.alias = alias
        self.rogue = rogue
        self.marker_drift = marker_drift
        self.marker_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def run(self, query, **params):
        text = getattr(query, "text", str(query))
        if "RETURN $challenge_nonce" in text:
            return [{"challenge_nonce": params["challenge_nonce"]}]
        if "dbms.components" in text:
            return [{"version": "2026.06.0", "edition": "enterprise"}]
        if "CALL db.info" in text:
            return [{"id": "neo4j-db-id", "name": "neo4j"}]
        if "SHOW DATABASE system" in text:
            self.marker_calls += 1
            return [{
                "name": "system",
                "type": "system",
                "database_id": "system-db-id",
                "current_status": "online",
                "writer": True,
                "last_committed_tx": (
                    41 + int(self.marker_drift and self.marker_calls > 1)
                ),
                "replication_lag": 0,
            }]
        if "SHOW CURRENT USER" in text:
            return [{
                "user": "lakatos_audit_user",
                "roles": ["PUBLIC", "lakatos_audit_role"],
            }]
        if "SHOW USER PRIVILEGES" in text:
            return _neo_audit_role()
        if "SHOW ALIASES" in text:
            return ([{
                "name": "neo4j", "database": "remote-db", "location": "remote",
            }] if self.alias else [])
        if "SHOW DATABASES" in text:
            return [{
                "name": "neo4j", "type": "standard", "current_status": "online",
            }]
        if "SHOW SETTINGS" in text:
            return _neo_auth_settings()
        if "SHOW USERS" in text:
            rows = [
                {
                    "user": f"lakatos_{label}_user",
                    "roles": ["PUBLIC", f"lakatos_{label}_role"],
                    "suspended": False,
                }
                for label in ("audit", "migrator", "runtime")
            ]
            if self.rogue:
                rows.append({
                    "user": "break_glass", "roles": ["admin"],
                    "suspended": False,
                })
            return rows
        if "SHOW PRIVILEGES" in text:
            rows = []
            for role, privileges in (
                ("lakatos_audit_role", _neo_audit_role()),
                ("lakatos_migrator_role", _neo_data_role(migrator=True)),
                ("lakatos_runtime_role", _neo_data_role()),
            ):
                rows.extend({"role": role, **item} for item in privileges)
            if self.rogue:
                rows.append({
                    "role": "admin", "access": "GRANTED",
                    "action": "dbms_actions", "resource": "database",
                    "graph": "*", "segment": "database", "immutable": False,
                })
            return rows
        raise AssertionError(f"unexpected Neo4j audit query: {text}")


class _NeoAuditDriver:
    def __init__(self, **session_options):
        self.session_options = session_options

    def session(self, *, database, **_kwargs):
        return _NeoAuditSession(database, **self.session_options)


@pytest.mark.parametrize(
    ("session_options", "direct", "unsafe_count"),
    (({}, True, 0), ({"alias": True}, False, 0), ({"rogue": True}, True, 1)),
)
def test_live_neo_audit_rejects_alias_and_undeclared_active_authority(
    session_options, direct, unsafe_count
):
    config = {
        **_policy()["neo4j"],
        "challenge_nonce": "1" * 64,
    }
    result = live._collect_neo4j_impl(
        config,
        5,
        {},
        injected_driver=_NeoAuditDriver(**session_options),
        injected_uri="bolt+s://127.0.0.1:7687",
    )
    assert result.status == "OBSERVED"
    assert result.facts["database_direct_local"] is direct
    assert result.facts["global_unsafe_privilege_count"] == unsafe_count
    assert result.facts["audit_principal_read_only"] is (
        direct and unsafe_count == 0
    )


def test_live_neo_audit_rejects_authority_commit_during_projection():
    result = live._collect_neo4j_impl(
        {**_policy()["neo4j"], "challenge_nonce": "1" * 64},
        5,
        {},
        injected_driver=_NeoAuditDriver(marker_drift=True),
        injected_uri="bolt+s://127.0.0.1:7687",
    )
    assert result.status == "PARTIAL"
    assert result.facts["authorization_snapshot_stable"] is False
    assert result.facts["audit_principal_read_only"] is False
    assert "neo4j.authorization_snapshot.unstable" in result.failure_codes


def test_request_accepts_declared_development_environment(tmp_path):
    request = _request(tmp_path)
    request["environment"] = "development"
    assert producer.validate_request(request)["environment"] == "development"


class _NeoCommunitySession:
    def __init__(self, database, *, marker_drift=False):
        self.database = database
        self.marker_drift = marker_drift
        self.marker_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def run(self, query, **params):
        text = getattr(query, "text", str(query))
        if "RETURN $challenge_nonce" in text:
            return [{"challenge_nonce": params["challenge_nonce"]}]
        if "dbms.components" in text:
            return [{"version": "2026.02.0", "edition": "community"}]
        if "CALL db.info" in text:
            return [{"id": "neo4j-db-id", "name": "neo4j"}]
        if "SHOW DATABASE system" in text:
            self.marker_calls += 1
            return [{
                "name": "system",
                "type": "system",
                "database_id": "system-db-id",
                "current_status": "online",
                "writer": True,
                "last_committed_tx": (
                    41 + int(self.marker_drift and self.marker_calls > 1)
                ),
                "replication_lag": 0,
            }]
        if "SHOW CURRENT USER" in text:
            return [{"user": "lakatos_audit_user"}]
        if "SHOW ALIASES" in text:
            # Enterprise-only administration command (live 2026.02 rejects it).
            raise AssertionError(
                "community collector must not run SHOW ALIASES"
            )
        if "SHOW DATABASES" in text:
            return [{
                "name": "neo4j", "type": "standard", "aliases": [],
                "current_status": "online",
            }]
        if "SHOW SETTINGS" in text:
            # Community 2026.02 predates the abac provider setting.
            return [
                row for row in _neo_auth_settings()
                if row["name"] in live._NEO_BASE_AUTH_SETTING_NAMES
            ]
        if "SHOW USERS" in text:
            # Community reports suspended as null for every user.
            return [
                {"user": f"lakatos_{label}_user", "suspended": None}
                for label in ("audit", "migrator", "runtime")
            ]
        if "SHOW USER PRIVILEGES" in text or "SHOW PRIVILEGES" in text:
            raise AssertionError("community collector must not run RBAC queries")
        raise AssertionError(f"unexpected Neo4j community audit query: {text}")


class _NeoCommunityDriver:
    def __init__(self, **session_options):
        self.session_options = session_options

    def session(self, *, database, **_kwargs):
        return _NeoCommunitySession(database, **self.session_options)


def _development_policy():
    policy = _policy()
    policy["environment"] = "development"
    policy["postgresql"]["host"] = "192.168.0.25"
    return policy


def test_live_community_collector_matches_the_development_verifier():
    config = {
        **_development_policy()["neo4j"],
        "environment": "development",
        "challenge_nonce": "1" * 64,
    }
    result = producer._collect_neo4j_community_impl(
        config,
        5,
        {},
        injected_driver=_NeoCommunityDriver(),
        injected_uri="bolt+s://127.0.0.1:7687",
    )
    assert result.status == "OBSERVED"
    facts = result.facts
    assert facts["community_semantics"] is True
    assert facts["rbac_available"] is False
    assert facts["enterprise"] is False
    assert facts["read_query_count"] == (
        storage_access._NEO_COMMUNITY_READ_QUERY_COUNT
    )
    assert storage_access._neo4j_projection_failures(
        facts, _development_policy(), "1" * 64
    ) == []


def test_live_community_collector_flags_authority_commit_during_projection():
    result = producer._collect_neo4j_community_impl(
        {
            **_development_policy()["neo4j"],
            "environment": "development",
            "challenge_nonce": "1" * 64,
        },
        5,
        {},
        injected_driver=_NeoCommunityDriver(marker_drift=True),
        injected_uri="bolt+s://127.0.0.1:7687",
    )
    assert result.status == "PARTIAL"
    assert result.facts["authorization_snapshot_stable"] is False
    assert "neo4j.authorization_snapshot.unstable" in result.failure_codes


def _community_adapter_result(*, nonce="1" * 64):
    policy = _development_policy()["neo4j"]
    empty = hashlib.sha256(_canonical([])).hexdigest()
    base_settings = [
        row for row in _neo_auth_settings()
        if row["name"] in live._NEO_BASE_AUTH_SETTING_NAMES
    ]
    facts = {
        "database": "neo4j",
        "challenge_nonce_sha256": hashlib.sha256(nonce.encode()).hexdigest(),
        "database_name_matches": True,
        "database_direct_local": True,
        "database_alias_count": 0,
        "database_alias_sha256": empty,
        "database_catalog_sha256": hashlib.sha256(_canonical([{
            "name_sha256": hashlib.sha256(b"neo4j").hexdigest(),
            "type": "standard", "current_status": "online",
        }])).hexdigest(),
        "database_id_sha256": hashlib.sha256(b"neo4j-db-id").hexdigest(),
        "edition": "community", "version": "2026.02.0",
        "enterprise": False,
        "community_semantics": True,
        "rbac_available": False,
        "current_actor_sha256": hashlib.sha256(
            policy["audit_user"].encode()
        ).hexdigest(),
        "named_user_sha256": {
            label: hashlib.sha256(
                policy[f"{label}_user"].encode()
            ).hexdigest()
            for label in ("audit", "migrator", "runtime")
        },
        "named_user_suspended": {
            label: False for label in ("audit", "migrator", "runtime")
        },
        "auth_settings": base_settings,
        "auth_settings_sha256": hashlib.sha256(
            _canonical(base_settings)
        ).hexdigest(),
        "native_only_auth": True,
        "system_database_id_sha256": hashlib.sha256(b"system-db-id").hexdigest(),
        "system_last_committed_tx": 41,
        "authorization_snapshot_stable": True,
        "read_query_count": storage_access._NEO_COMMUNITY_READ_QUERY_COUNT,
    }
    return live.AdapterResult(
        "OBSERVED", facts, binding_material=_target_details()["neo4j"]
    )


def test_normalizer_accepts_community_projection_only_in_development():
    def neo(config, timeout, environ):
        return _community_adapter_result()

    development_config = {
        **_development_policy()["neo4j"],
        "environment": "development",
        "challenge_nonce": "1" * 64,
    }
    normalized, binding = producer._normalized_observation(
        "neo4j", development_config, 5, {}, _ports(neo, neo)
    )
    assert normalized["status"] == "OBSERVED"
    assert normalized["facts"]["community_semantics"] is True
    assert binding == _target_details()["neo4j"]

    production_config = {
        **_policy()["neo4j"],
        "environment": "production",
        "challenge_nonce": "1" * 64,
    }
    with pytest.raises(
        producer.StorageAuditCollectionError, match="not read-only"
    ):
        producer._normalized_observation(
            "neo4j", production_config, 5, {}, _ports(neo, neo)
        )
