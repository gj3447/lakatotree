from __future__ import annotations

import copy
from datetime import datetime, timezone

import pytest

from lakatos.write_cert import did_key_encode, ed25519_public_key
from server import storage_access as access


PG_SECRET = bytes(range(32))
NEO_SECRET = bytes(range(32, 64))
FENCE_SECRET = bytes([91]) * 32
PG_DID = did_key_encode(ed25519_public_key(PG_SECRET))
NEO_DID = did_key_encode(ed25519_public_key(NEO_SECRET))
EVALUATED_AT = datetime(2026, 8, 2, 0, 1, tzinfo=timezone.utc)


def _policy():
    return {
        "schema_version": access.ACCESS_POLICY_SCHEMA,
        "environment": "production",
        "attestors": {"postgresql": PG_DID, "neo4j": NEO_DID},
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


def _expected(*, phase="predeploy"):
    details = _target_details()
    return {
        "request_nonce": ("1" if phase == "predeploy" else "a") * 64,
        "request_sha256": "2" * 64,
        "target_sha256": access.sha256_bytes(access.canonical_json(details)),
        "target_details": details,
        "operation_sha256": "5" * 64,
        "access_policy_file_sha256": "6" * 64,
        "predeploy_receipt_file_sha256": "7" * 64,
        "predeploy_receipt_sha256": "8" * 64,
        "previous_phase_bundle_file_sha256": None if phase == "predeploy" else "9" * 64,
    }


def _pg_attributes(login):
    return {
        "login": login, "superuser": False, "createdb": False,
        "createrole": False, "inherit": False, "bypassrls": False,
        "replication": False,
    }


def _pg_required_acl():
    pg = _policy()["postgresql"]
    rows = [
        {
            "scope": "database",
            "object_sha256": access.sha256_bytes(pg["database"].encode()),
            "grantor": "owner",
            "grantee": label,
            "privilege": "CONNECT",
            "grantable": False,
        }
        for label in ("migrator", "runtime", "audit")
    ]
    rows.append({
        "scope": "schema",
        "object_sha256": access.sha256_bytes(b"public"),
        "grantor": "owner",
        "grantee": "runtime",
        "privilege": "USAGE",
        "grantable": False,
    })
    rows.extend(
        {
            "scope": "relation",
            "object_sha256": access.sha256_bytes(name.encode()),
            "grantor": "owner",
            "grantee": "runtime",
            "privilege": privilege,
            "grantable": False,
        }
        for name in access._PG_TABLES
        for privilege in ("SELECT", "INSERT")
    )
    rows.extend(
        {
            "scope": "sequence",
            "object_sha256": access.sha256_bytes(name.encode()),
            "grantor": "owner",
            "grantee": "runtime",
            "privilege": privilege,
            "grantable": False,
        }
        for name in access._PG_SEQUENCES
        for privilege in ("SELECT", "USAGE")
    )
    return sorted(rows, key=access.canonical_json)


def _pg_observation(*, nonce="1" * 64):
    role_names = {
        "owner": "lakatos_owner", "migrator": "lakatos_migrator",
        "runtime": "lakatos_runtime", "audit": "lakatos_audit",
    }
    hashes = {label: access.sha256_bytes(name.encode()) for label, name in role_names.items()}
    empty_sha = access.sha256_bytes(access.canonical_json([]))
    acl_projection = _pg_required_acl()
    objects = {
        name: {
            "exists": True, "owner_class": "owner",
            "runtime_privileges": ["SELECT", "INSERT"],
            "runtime_column_privilege_count": 0,
            "runtime_column_privilege_sha256": empty_sha,
            "runtime_column_only_privileges": [],
        }
        for name in access._PG_TABLES
    }
    objects.update({
        name: {"exists": True, "owner_class": "owner", "runtime_privileges": ["SELECT", "USAGE"]}
        for name in access._PG_SEQUENCES
    })
    return {
        "status": "OBSERVED", "failure_codes": [],
        "facts": {
            "database": "lakatos", "database_matches": True,
            "database_oid_sha256": access.sha256_bytes(b"16384"),
            "system_identifier_sha256": access.sha256_bytes(b"123456789"),
            "transaction_read_only": True,
            "challenge_nonce_sha256": access.sha256_bytes(nonce.encode()),
            "current_actor_class": "audit",
            "current_actor_sha256": hashes["audit"],
            "session_actor_sha256": hashes["audit"], "roles_distinct": True,
            "roles": {
                label: {"name_sha256": hashes[label], "present": True, "attributes": _pg_attributes(label != "owner")}
                for label in role_names
            },
            "objects": objects, "public_schema_owner_class": "owner",
            "acl_projection_scope": "contract-objects-v1",
            "acl_projection_count": len(acl_projection),
            "acl_projection_sha256": access.sha256_bytes(
                access.canonical_json(acl_projection)
            ),
            "acl_projection": acl_projection,
            "grantable_acl_counts": {label: 0 for label in role_names},
            "public_acl_entry_counts": {scope: 0 for scope in ("database", "schema", "relation", "sequence", "column")},
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
            "migrator_owner_membership": {"admin_option": False, "inherit_option": False, "set_option": True},
            "role_owned_user_object_count": {"owner": 8, "migrator": 0, "runtime": 0, "audit": 0},
            "role_user_function_execute_count": {"owner": 0, "migrator": 0, "runtime": 0, "audit": 0},
            "runtime_database_create": False, "runtime_database_temp": False,
            "runtime_schema_create": False, "runtime_schema_create_count": 0,
            "runtime_schema_create_sha256": empty_sha,
            "runtime_schema_usage": True, "audit_principal_read_only": True,
            "runtime_out_of_contract_write_privilege_count": 0,
            "runtime_out_of_contract_write_privilege_sha256": empty_sha,
            "runtime_out_of_contract_read_privilege_count": 0,
            "runtime_out_of_contract_read_privilege_sha256": empty_sha,
            "authority_boundary_deviation_count": 0,
            "authority_boundary_deviation_sha256": empty_sha,
            "audit_effective_role_sha256": [hashes["audit"]],
            "audit_database_create": False, "audit_database_temp": False,
            "audit_schema_create": False, "audit_schema_create_count": 0,
            "audit_schema_create_sha256": empty_sha,
            "audit_data_read_privilege_count": 0,
            "audit_data_read_privilege_sha256": empty_sha,
            "audit_write_privilege_count": 0, "audit_write_privilege_sha256": empty_sha,
            "audit_column_write_privilege_count": 0,
            "audit_column_write_privilege_sha256": empty_sha,
        },
    }


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
        for name in access._NEO_AUTH_SETTING_NAMES
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
        for name in access._NEO_AUTH_SETTING_NAMES
    ]


def _neo_observation(*, nonce="1" * 64):
    neo = _policy()["neo4j"]
    runtime = _neo_data_role()
    migrator = _neo_data_role(migrator=True)
    named = {"audit": _neo_audit_role(), "migrator": migrator, "runtime": runtime, "public": []}
    effective = list(named["audit"])
    role_hashes = {label: access.sha256_bytes(neo[f"{label}_role"].encode()) for label in ("audit", "migrator", "runtime")}
    public_hash = access.sha256_bytes(b"PUBLIC")
    empty_sha = access.sha256_bytes(access.canonical_json([]))
    return {
        "status": "OBSERVED", "failure_codes": [],
        "facts": {
            "database": "neo4j", "challenge_nonce_sha256": access.sha256_bytes(nonce.encode()),
            "database_name_matches": True,
            "database_direct_local": True,
            "database_alias_count": 0,
            "database_alias_sha256": empty_sha,
            "database_catalog_sha256": access.sha256_bytes(access.canonical_json([{
                "name_sha256": access.sha256_bytes(b"neo4j"),
                "type": "standard", "current_status": "online",
            }])),
            "database_id_sha256": access.sha256_bytes(b"neo4j-db-id"),
            "edition": "enterprise", "version": "2026.06.0", "enterprise": True,
            "current_actor_sha256": access.sha256_bytes(neo["audit_user"].encode()),
            "role_sha256": sorted([role_hashes["audit"], public_hash]), "role_count": 2,
            "effective_privilege_sha256": access.sha256_bytes(access.canonical_json(effective)),
            "effective_privilege_count": len(effective), "effective_privileges": effective,
            "audit_principal_read_only": True, "audit_unsafe_granted_action_count": 0,
            "audit_unsafe_granted_action_sha256": empty_sha,
            "named_role_sha256": role_hashes,
            "named_role_privilege_sha256": {label: access.sha256_bytes(access.canonical_json(named[label])) for label in ("audit", "migrator", "runtime")},
            "named_role_privileges": named,
            "public_role_binding_sha256": access.sha256_bytes(access.canonical_json(named["public"])),
            "custom_role_binding_ok": True,
            "named_user_role_sha256": {label: sorted([role_hashes[label], public_hash]) for label in role_hashes},
            "named_role_assignee_sha256": {
                label: [access.sha256_bytes(neo[f"{label}_user"].encode())]
                for label in ("audit", "migrator", "runtime")
            },
            "named_user_role_binding_ok": True, "runtime_role_least_privilege": True,
            "migrator_role_least_privilege": True, "public_role_safe": True,
            "auth_settings": _neo_auth_settings(),
            "auth_settings_sha256": access.sha256_bytes(
                access.canonical_json(_neo_auth_settings())
            ),
            "native_only_auth": True,
            "global_unsafe_privilege_count": 0,
            "global_unsafe_privilege_sha256": empty_sha,
            "system_database_id_sha256": access.sha256_bytes(b"system-db-id"),
            "system_last_committed_tx": 41,
            "authorization_snapshot_stable": True,
            "read_query_count": 12,
        },
    }


def _signed(
    store: str, position: str, *, phase="predeploy", observation=None,
    expected=None, observed_at="2026-08-02T00:00:00+00:00",
    expires_at="2026-08-02T00:05:00+00:00",
):
    expected = expected or _expected(phase=phase)
    signer_did, secret = (PG_DID, PG_SECRET) if store == "postgresql" else (NEO_DID, NEO_SECRET)
    observation = observation or (
        _pg_observation(nonce=expected["request_nonce"])
        if store == "postgresql"
        else _neo_observation(nonce=expected["request_nonce"])
    )
    body = access.build_attestation_body(
        store=store, phase=phase, position=position, expected=expected,
        environment="production", observation=observation,
        target_binding=expected["target_details"][store], observed_at=observed_at,
        expires_at=expires_at, evidence_refs=[f"audit://{store}/{position}"],
        signer_did=signer_did,
    )
    return access.seal_datastore_attestation(body, secret)


@pytest.mark.parametrize(
    ("store", "did"), (("postgresql", PG_DID), ("neo4j", NEO_DID))
)
def test_signed_before_after_pair_verifies_and_derives_no_drift(store, did):
    result = access.verify_datastore_attestation_pair(
        _signed(store, "before"),
        _signed(store, "after", observed_at="2026-08-02T00:00:01+00:00"),
        policy=_policy(),
        expected=_expected(),
        store=store,
        phase="predeploy",
        signer_did=did,
        evaluated_at=EVALUATED_AT,
    )
    assert result.ok is True
    assert result.failures == ()
    assert result.before_body_sha256 != result.after_body_sha256
    assert result.observation_sha256


def test_pair_detects_signed_projection_drift_instead_of_trusting_a_flag():
    changed = _pg_observation()
    changed["facts"]["role_owned_user_object_count"]["owner"] = 9
    result = access.verify_datastore_attestation_pair(
        _signed("postgresql", "before"),
        _signed("postgresql", "after", observation=changed),
        policy=_policy(), expected=_expected(), store="postgresql",
        phase="predeploy", signer_did=PG_DID, evaluated_at=EVALUATED_AT,
    )
    assert result.ok is False
    assert "observation_drift" in result.failures


def test_signature_body_mutation_is_rejected():
    attestation = _signed("postgresql", "before")
    attestation["target_sha256"] = "a" * 64
    result = access.verify_datastore_attestation(
        attestation,
        policy=_policy(), expected=_expected(), expected_store="postgresql",
        expected_phase="predeploy", expected_position="before",
        expected_signer_did=PG_DID, evaluated_at=EVALUATED_AT,
    )
    assert result.ok is False
    assert "signature_invalid" in result.failures


def test_wrong_store_key_is_rejected_even_with_valid_signature():
    result = access.verify_datastore_attestation(
        _signed("postgresql", "before"),
        policy=_policy(), expected=_expected(), expected_store="postgresql",
        expected_phase="predeploy", expected_position="before",
        expected_signer_did=NEO_DID, evaluated_at=EVALUATED_AT,
    )
    assert result.ok is False
    assert "signer_mismatch" in result.failures


def test_stale_attestation_is_rejected():
    result = access.verify_datastore_attestation(
        _signed(
            "postgresql", "before",
            observed_at="2026-08-01T23:50:00+00:00",
            expires_at="2026-08-01T23:55:00+00:00",
        ),
        policy=_policy(), expected=_expected(), expected_store="postgresql",
        expected_phase="predeploy", expected_position="before",
        expected_signer_did=PG_DID, evaluated_at=EVALUATED_AT,
    )
    assert result.ok is False
    assert "freshness_invalid" in result.failures


@pytest.mark.parametrize(
    ("store", "field", "value", "failure"),
    (
        ("postgresql", "audit_principal_read_only", False, "postgresql.audit_read_only"),
        ("postgresql", "audit_write_privilege_count", 1, "postgresql.audit_write_privilege"),
        ("postgresql", "runtime_database_temp", True, "postgresql.runtime_database_temp"),
        ("postgresql", "runtime_schema_create_count", 1, "postgresql.runtime_schema_create_count"),
        ("postgresql", "runtime_out_of_contract_write_privilege_count", 1, "postgresql.runtime_out_of_contract_write_privilege"),
        ("postgresql", "runtime_out_of_contract_read_privilege_count", 1, "postgresql.runtime_out_of_contract_read_privilege"),
        ("postgresql", "authority_boundary_deviation_count", 1, "postgresql.authority_boundary_deviation"),
        ("postgresql", "audit_data_read_privilege_count", 1, "postgresql.audit_data_read_privilege"),
        ("neo4j", "enterprise", False, "neo4j.enterprise"),
        ("neo4j", "database_direct_local", False, "neo4j.database_direct_local"),
        ("neo4j", "global_unsafe_privilege_count", 1, "neo4j.global_unsafe_privilege"),
        ("neo4j", "audit_unsafe_granted_action_count", 1, "neo4j.audit_unsafe_count"),
    ),
)
def test_signed_policy_violation_remains_not_ready(store, field, value, failure):
    observation = _pg_observation() if store == "postgresql" else _neo_observation()
    observation["facts"][field] = value
    did = PG_DID if store == "postgresql" else NEO_DID
    result = access.verify_datastore_attestation(
        _signed(store, "before", observation=observation),
        policy=_policy(), expected=_expected(), expected_store=store,
        expected_phase="predeploy", expected_position="before",
        expected_signer_did=did, evaluated_at=EVALUATED_AT,
    )
    assert result.ok is False
    assert failure in result.failures


def test_startup_must_bind_exact_predeploy_bundle_sha():
    expected = _expected(phase="startup")
    attestation = _signed(
        "neo4j", "before", phase="startup", expected=expected
    )
    changed_expected = dict(expected)
    changed_expected["previous_phase_bundle_file_sha256"] = "a" * 64
    result = access.verify_datastore_attestation(
        attestation,
        policy=_policy(), expected=changed_expected, expected_store="neo4j",
        expected_phase="startup", expected_position="before",
        expected_signer_did=NEO_DID, evaluated_at=EVALUATED_AT,
    )
    assert result.ok is False
    assert "previous_phase_bundle_file_sha256_mismatch" in result.failures


def test_unknown_attestation_field_fails_closed():
    attestation = _signed("neo4j", "before")
    attestation["production_ready"] = True
    result = access.verify_datastore_attestation(
        attestation,
        policy=_policy(), expected=_expected(), expected_store="neo4j",
        expected_phase="predeploy", expected_position="before",
        expected_signer_did=NEO_DID, evaluated_at=EVALUATED_AT,
    )
    assert result == access.AttestationVerification(False, ("malformed",), None, None)


def test_policy_rejects_looser_membership_and_builtin_neo_role():
    policy = _policy()
    policy["environment"] = "prod"
    with pytest.raises(access.StorageAccessError, match="must be production"):
        access.validate_access_policy(policy)

    policy = _policy()
    policy["postgresql"]["migrator_owner_membership"]["inherit_option"] = True
    with pytest.raises(access.StorageAccessError):
        access.validate_access_policy(policy)

    policy = _policy()
    policy["neo4j"]["uri"] = "bolt+s://db.example:7687"
    with pytest.raises(access.StorageAccessError, match="literal IP"):
        access.validate_access_policy(policy)

    policy = _policy()
    policy["postgresql"]["host"] = "192.0.2.10"
    with pytest.raises(access.StorageAccessError, match="loopback"):
        access.validate_access_policy(policy)

    policy = _policy()
    policy["neo4j"]["runtime_role"] = "publisher"
    with pytest.raises(access.StorageAccessError):
        access.validate_access_policy(policy)

    policy = _policy()
    policy["neo4j"]["database"] = "system"
    with pytest.raises(access.StorageAccessError, match="application database"):
        access.validate_access_policy(policy)

    for database in ("*", "DEFAULT", "neo4j.", "-neo4j", "systemfoo"):
        policy = _policy()
        policy["neo4j"]["database"] = database
        with pytest.raises(access.StorageAccessError, match="canonical"):
            access.validate_access_policy(policy)


def test_pg_required_acl_cannot_be_omitted_or_duplicated():
    observation = _pg_observation()
    acl = observation["facts"]["acl_projection"]
    acl.pop()
    acl.append(copy.deepcopy(acl[0]))
    observation["facts"]["acl_projection_sha256"] = access.sha256_bytes(
        access.canonical_json(acl)
    )
    result = access.verify_datastore_attestation(
        _signed("postgresql", "before", observation=observation),
        policy=_policy(), expected=_expected(), expected_store="postgresql",
        expected_phase="predeploy", expected_position="before",
        expected_signer_did=PG_DID, evaluated_at=EVALUATED_AT,
    )
    assert result.ok is False
    assert "postgresql.required_acl" in result.failures
    assert "postgresql.acl_duplicates" in result.failures


def test_pg_rogue_acl_and_inbound_role_assignee_are_rejected():
    observation = _pg_observation()
    observation["facts"]["acl_projection"] = [{
        "scope": "relation",
        "object_sha256": access.sha256_bytes(b"public.history"),
        "grantor": "owner",
        "grantee": "sha256:" + "a" * 64,
        "privilege": "SELECT",
        "grantable": False,
    }]
    observation["facts"]["acl_projection_count"] = 1
    observation["facts"]["acl_projection_sha256"] = access.sha256_bytes(
        access.canonical_json(observation["facts"]["acl_projection"])
    )
    observation["facts"]["role_inbound_membership_sha256"]["runtime"] = [
        "b" * 64
    ]
    result = access.verify_datastore_attestation(
        _signed("postgresql", "before", observation=observation),
        policy=_policy(), expected=_expected(), expected_store="postgresql",
        expected_phase="predeploy", expected_position="before",
        expected_signer_did=PG_DID, evaluated_at=EVALUATED_AT,
    )
    assert result.ok is False
    assert "postgresql.unknown_acl_principal" in result.failures
    assert "postgresql.inbound_role_memberships" in result.failures


def test_neo_subset_scope_public_overgrant_and_extra_assignee_are_rejected():
    observation = _neo_observation()
    facts = observation["facts"]
    facts["named_role_privileges"]["runtime"][1]["segment"] = "NODE(Secret)"
    facts["named_role_privilege_sha256"]["runtime"] = access.sha256_bytes(
        access.canonical_json(facts["named_role_privileges"]["runtime"])
    )
    facts["named_role_privileges"]["public"] = [_neo_row("write")]
    facts["public_role_binding_sha256"] = access.sha256_bytes(
        access.canonical_json(facts["named_role_privileges"]["public"])
    )
    facts["named_role_assignee_sha256"]["runtime"].append("c" * 64)
    result = access.verify_datastore_attestation(
        _signed("neo4j", "before", observation=observation),
        policy=_policy(), expected=_expected(), expected_store="neo4j",
        expected_phase="predeploy", expected_position="before",
        expected_signer_did=NEO_DID, evaluated_at=EVALUATED_AT,
    )
    assert result.ok is False
    assert "neo4j.runtime_privileges" in result.failures
    assert "neo4j.public_privileges" in result.failures
    assert "neo4j.role_assignees" in result.failures


@pytest.mark.parametrize(
    ("mutate", "failure"),
    (
        (
            lambda facts: facts["named_role_privileges"]["migrator"].pop(),
            "neo4j.migrator_privileges",
        ),
        (
            lambda facts: facts["auth_settings"][2].update(
                value="ldap,native", startup_value="ldap,native"
            ),
            "neo4j.native_only_auth_settings",
        ),
        (
            lambda facts: facts["named_role_privileges"]["audit"][0].update(
                access="UNKNOWN"
            ),
            "neo4j.privilege_schema",
        ),
    ),
)
def test_neo_raw_rbac_and_native_auth_policy_fail_closed(mutate, failure):
    observation = _neo_observation()
    mutate(observation["facts"])
    result = access.verify_datastore_attestation(
        _signed("neo4j", "before", observation=observation),
        policy=_policy(), expected=_expected(), expected_store="neo4j",
        expected_phase="predeploy", expected_position="before",
        expected_signer_did=NEO_DID, evaluated_at=EVALUATED_AT,
    )
    assert result.ok is False
    assert failure in result.failures


def test_neo_actual_show_privileges_vocabulary_is_accepted():
    observation = _neo_observation()
    assert access._neo_role_rows_exact(
        observation["facts"]["named_role_privileges"]["runtime"],
        database="neo4j",
        migrator=False,
    )
    assert access._neo_role_rows_exact(
        observation["facts"]["named_role_privileges"]["migrator"],
        database="neo4j",
        migrator=True,
    )
    assert access._neo_audit_rows_exact(
        observation["facts"]["named_role_privileges"]["audit"],
        database="neo4j",
        version=observation["facts"]["version"],
    )


def test_neo_audit_requires_system_access_and_rejects_future_semantics():
    observation = _neo_observation()
    facts = observation["facts"]
    audit_rows = facts["named_role_privileges"]["audit"]
    audit_rows[:] = [
        row for row in audit_rows
        if not (row["action"] == "access" and row["graph"] == "system")
    ]
    facts["named_role_privilege_sha256"]["audit"] = access.sha256_bytes(
        access.canonical_json(audit_rows)
    )
    facts["effective_privileges"] = list(audit_rows)
    facts["effective_privilege_count"] = len(audit_rows)
    facts["effective_privilege_sha256"] = access.sha256_bytes(
        access.canonical_json(audit_rows)
    )
    missing_system = access.verify_datastore_attestation(
        _signed("neo4j", "before", observation=observation),
        policy=_policy(), expected=_expected(), expected_store="neo4j",
        expected_phase="predeploy", expected_position="before",
        expected_signer_did=NEO_DID, evaluated_at=EVALUATED_AT,
    )
    assert missing_system.ok is False
    assert "neo4j.audit_role_privileges" in missing_system.failures

    observation = _neo_observation()
    observation["facts"]["version"] = "2026.07.0"
    unsupported = access.verify_datastore_attestation(
        _signed("neo4j", "before", observation=observation),
        policy=_policy(), expected=_expected(), expected_store="neo4j",
        expected_phase="predeploy", expected_position="before",
        expected_signer_did=NEO_DID, evaluated_at=EVALUATED_AT,
    )
    assert unsupported.ok is False
    assert "neo4j.version" in unsupported.failures


def test_neo_immutable_privilege_and_unstable_authority_snapshot_are_rejected():
    observation = _neo_observation()
    facts = observation["facts"]
    facts["named_role_privileges"]["audit"][0]["immutable"] = True
    audit_rows = facts["named_role_privileges"]["audit"]
    facts["named_role_privilege_sha256"]["audit"] = access.sha256_bytes(
        access.canonical_json(audit_rows)
    )
    facts["effective_privileges"] = list(audit_rows)
    facts["effective_privilege_count"] = len(audit_rows)
    facts["effective_privilege_sha256"] = access.sha256_bytes(
        access.canonical_json(audit_rows)
    )
    immutable = access.verify_datastore_attestation(
        _signed("neo4j", "before", observation=observation),
        policy=_policy(), expected=_expected(), expected_store="neo4j",
        expected_phase="predeploy", expected_position="before",
        expected_signer_did=NEO_DID, evaluated_at=EVALUATED_AT,
    )
    assert immutable.ok is False
    assert "neo4j.audit_role_privileges" in immutable.failures
    assert "neo4j.audit_unsafe_action" in immutable.failures

    observation = _neo_observation()
    observation["facts"]["authorization_snapshot_stable"] = False
    unstable = access.verify_datastore_attestation(
        _signed("neo4j", "before", observation=observation),
        policy=_policy(), expected=_expected(), expected_store="neo4j",
        expected_phase="predeploy", expected_position="before",
        expected_signer_did=NEO_DID, evaluated_at=EVALUATED_AT,
    )
    assert unstable.ok is False
    assert "neo4j.authorization_snapshot" in unstable.failures


def test_pg_target_binding_rejects_a_different_live_server_address():
    expected = _expected()
    expected["target_details"]["postgresql"]["server_address"] = "192.0.2.50"
    expected["target_sha256"] = access.sha256_bytes(
        access.canonical_json(expected["target_details"])
    )
    with pytest.raises(access.StorageAccessError, match="target binding"):
        access.validate_expected(expected, _policy())


def test_seal_refuses_signer_did_key_mismatch():
    body = copy.deepcopy(_signed("postgresql", "before"))
    body.pop("signature")
    body["signer_did"] = NEO_DID
    with pytest.raises(access.StorageAccessError):
        access.seal_datastore_attestation(body, PG_SECRET)


def _bundle(phase: str, expected, *, changed_store=None, expiry_overrides=None):
    if phase == "predeploy":
        before_at = "2026-08-02T00:00:00+00:00"
        after_at = "2026-08-02T00:00:01+00:00"
        expires_at = "2026-08-02T00:05:00+00:00"
    else:
        before_at = "2026-08-02T00:02:00+00:00"
        after_at = "2026-08-02T00:02:01+00:00"
        expires_at = "2026-08-02T00:07:00+00:00"
    observations = {
        "postgresql": _pg_observation(nonce=expected["request_nonce"]),
        "neo4j": _neo_observation(nonce=expected["request_nonce"]),
    }
    if changed_store:
        if changed_store == "postgresql":
            observations[changed_store]["facts"][
                "role_owned_user_object_count"
            ]["owner"] = 9
        else:
            observations[changed_store]["facts"]["version"] = "2026.06.1"
    signed = {}
    expiry_overrides = expiry_overrides or {}
    for store in ("postgresql", "neo4j"):
        signed[store] = {
            "before": _signed(
                store, "before", phase=phase, expected=expected,
                observation=observations[store], observed_at=before_at,
                expires_at=expiry_overrides.get((store, "before"), expires_at),
            ),
            "after": _signed(
                store, "after", phase=phase, expected=expected,
                observation=observations[store], observed_at=after_at,
                expires_at=expiry_overrides.get((store, "after"), expires_at),
            ),
        }
    return access.build_storage_audit_bundle(
        phase=phase,
        request_nonce=expected["request_nonce"],
        request_sha256=expected["request_sha256"],
        previous_phase_bundle_file_sha256=expected[
            "previous_phase_bundle_file_sha256"
        ],
        postgresql_before=signed["postgresql"]["before"],
        postgresql_after=signed["postgresql"]["after"],
        neo4j_before=signed["neo4j"]["before"],
        neo4j_after=signed["neo4j"]["after"],
    )


def test_predeploy_startup_pair_binds_phase_sha_and_stable_projections():
    predeploy_expected = _expected(phase="predeploy")
    predeploy_bundle = _bundle("predeploy", predeploy_expected)
    predeploy_sha = access.sha256_bytes(access.canonical_json(predeploy_bundle))
    startup_expected = _expected(phase="startup")
    startup_expected["previous_phase_bundle_file_sha256"] = predeploy_sha
    result = access.verify_access_attestation_pair(
        predeploy_bundle,
        _bundle("startup", startup_expected),
        predeploy_bundle_file_sha256=predeploy_sha,
        policy=_policy(),
        expected_predeploy=predeploy_expected,
        expected_startup=startup_expected,
        signer_dids={"postgresql": PG_DID, "neo4j": NEO_DID},
        evaluated_at=datetime(2026, 8, 2, 0, 3, tzinfo=timezone.utc),
    )
    assert result.status == "ACCESS_PAIR_VERIFIED"
    assert result.production_ready is False
    assert result.deployment_status == "NOT_READY"
    assert result.failures == ()


def test_phase_pair_detects_neo_only_drift():
    predeploy_expected = _expected(phase="predeploy")
    predeploy_bundle = _bundle("predeploy", predeploy_expected)
    predeploy_sha = access.sha256_bytes(access.canonical_json(predeploy_bundle))
    startup_expected = _expected(phase="startup")
    startup_expected["previous_phase_bundle_file_sha256"] = predeploy_sha
    result = access.verify_access_attestation_pair(
        predeploy_bundle,
        _bundle("startup", startup_expected, changed_store="neo4j"),
        predeploy_bundle_file_sha256=predeploy_sha,
        policy=_policy(),
        expected_predeploy=predeploy_expected,
        expected_startup=startup_expected,
        signer_dids={"postgresql": PG_DID, "neo4j": NEO_DID},
        evaluated_at=datetime(2026, 8, 2, 0, 3, tzinfo=timezone.utc),
    )
    assert result.status == "NOT_READY"
    assert result.production_ready is False
    assert "neo4j.phase_projection_drift" in result.failures


def test_bundle_rejects_disjoint_cross_store_observation_intervals():
    expected = _expected()
    bundle = access.build_storage_audit_bundle(
        phase="predeploy",
        request_nonce=expected["request_nonce"],
        request_sha256=expected["request_sha256"],
        previous_phase_bundle_file_sha256=None,
        postgresql_before=_signed(
            "postgresql", "before", expected=expected,
            observed_at="2026-08-02T00:00:00+00:00",
        ),
        postgresql_after=_signed(
            "postgresql", "after", expected=expected,
            observed_at="2026-08-02T00:01:00+00:00",
        ),
        neo4j_before=_signed(
            "neo4j", "before", expected=expected,
            observed_at="2026-08-02T00:02:00+00:00",
        ),
        neo4j_after=_signed(
            "neo4j", "after", expected=expected,
            observed_at="2026-08-02T00:03:00+00:00",
        ),
    )
    proof = access.verify_storage_audit_bundle(
        bundle,
        policy=_policy(), expected=expected, phase="predeploy",
        signer_dids={"postgresql": PG_DID, "neo4j": NEO_DID},
        evaluated_at=datetime(2026, 8, 2, 0, 4, tzinfo=timezone.utc),
    )
    assert proof.ok is False
    assert "bundle.cross_store_observation_order_invalid" in proof.failures


def test_phase_pair_rejects_same_signer_for_both_stores():
    predeploy_expected = _expected(phase="predeploy")
    predeploy_bundle = _bundle("predeploy", predeploy_expected)
    predeploy_sha = access.sha256_bytes(access.canonical_json(predeploy_bundle))
    startup_expected = _expected(phase="startup")
    startup_expected["previous_phase_bundle_file_sha256"] = predeploy_sha
    result = access.verify_access_attestation_pair(
        predeploy_bundle,
        _bundle("startup", startup_expected),
        predeploy_bundle_file_sha256=predeploy_sha,
        policy=_policy(), expected_predeploy=predeploy_expected,
        expected_startup=startup_expected,
        signer_dids={"postgresql": PG_DID, "neo4j": PG_DID},
        evaluated_at=datetime(2026, 8, 2, 0, 3, tzinfo=timezone.utc),
    )
    assert result.status == "NOT_READY"
    assert any("store_signers_not_separated" in item for item in result.failures)


def test_phase_handoff_uses_earliest_expiry_of_all_predeploy_attestations():
    predeploy_expected = _expected(phase="predeploy")
    predeploy_bundle = _bundle(
        "predeploy",
        predeploy_expected,
        expiry_overrides={
            ("postgresql", "before"): "2026-08-02T00:01:00+00:00"
        },
    )
    predeploy_sha = access.sha256_bytes(access.canonical_json(predeploy_bundle))
    startup_expected = _expected(phase="startup")
    startup_expected["previous_phase_bundle_file_sha256"] = predeploy_sha
    result = access.verify_access_attestation_pair(
        predeploy_bundle,
        _bundle("startup", startup_expected),
        predeploy_bundle_file_sha256=predeploy_sha,
        policy=_policy(), expected_predeploy=predeploy_expected,
        expected_startup=startup_expected,
        signer_dids={"postgresql": PG_DID, "neo4j": NEO_DID},
        evaluated_at=datetime(2026, 8, 2, 0, 3, tzinfo=timezone.utc),
    )
    assert result.status == "NOT_READY"
    assert "phase_handoff_window_invalid" in result.failures
