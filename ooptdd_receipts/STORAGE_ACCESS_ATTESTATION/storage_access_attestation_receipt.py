"""Hermetic negative-oracle receipt for the complete storage-access chain."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lakatos.write_cert import did_key_encode, ed25519_public_key  # noqa: E402
from server import storage_access as access  # noqa: E402
from server import storage_predeploy as predeploy  # noqa: E402


PG_SECRET = bytes(range(32))
NEO_SECRET = bytes(range(32, 64))
FENCE_SECRET = bytes([91]) * 32
PG_DID = did_key_encode(ed25519_public_key(PG_SECRET))
NEO_DID = did_key_encode(ed25519_public_key(NEO_SECRET))
ARTIFACT = {"kind": "git", "source_commit": "5" * 40}
EVALUATED_AT = datetime(2026, 8, 2, 0, 3, tzinfo=timezone.utc)


def _canonical(value) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _require(condition: bool, message) -> None:
    if not condition:
        raise RuntimeError(f"storage-access attestation harness red: {message}")


def _event(cid: str, name: str) -> dict:
    return {
        "cid": cid,
        "correlation_id": cid,
        "cycle_id": cid,
        "service": "lakatotree.storage_access_attestation",
        "event": name,
    }


def _policy() -> dict:
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


def _target_details() -> dict:
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


def _role_attributes(login: bool) -> dict:
    return {
        "login": login,
        "superuser": False,
        "createdb": False,
        "createrole": False,
        "inherit": False,
        "bypassrls": False,
        "replication": False,
    }


def _pg_required_acl() -> list[dict]:
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


def _pg_observation(nonce: str) -> dict:
    names = {
        "owner": "lakatos_owner",
        "migrator": "lakatos_migrator",
        "runtime": "lakatos_runtime",
        "audit": "lakatos_audit",
    }
    hashes = {label: access.sha256_bytes(name.encode()) for label, name in names.items()}
    empty = access.sha256_bytes(access.canonical_json([]))
    acl_projection = _pg_required_acl()
    objects = {
        name: {
            "exists": True,
            "owner_class": "owner",
            "runtime_privileges": ["SELECT", "INSERT"],
            "runtime_column_privilege_count": 0,
            "runtime_column_privilege_sha256": empty,
            "runtime_column_only_privileges": [],
        }
        for name in access._PG_TABLES
    }
    objects.update({
        name: {
            "exists": True,
            "owner_class": "owner",
            "runtime_privileges": ["SELECT", "USAGE"],
        }
        for name in access._PG_SEQUENCES
    })
    return {
        "status": "OBSERVED",
        "failure_codes": [],
        "facts": {
            "database": "lakatos",
            "database_matches": True,
            "database_oid_sha256": access.sha256_bytes(b"16384"),
            "system_identifier_sha256": access.sha256_bytes(b"123456789"),
            "transaction_read_only": True,
            "challenge_nonce_sha256": access.sha256_bytes(nonce.encode()),
            "current_actor_class": "audit",
            "current_actor_sha256": hashes["audit"],
            "session_actor_sha256": hashes["audit"],
            "roles_distinct": True,
            "roles": {
                label: {
                    "name_sha256": hashes[label],
                    "present": True,
                    "attributes": _role_attributes(label != "owner"),
                }
                for label in names
            },
            "objects": objects,
            "public_schema_owner_class": "owner",
            "acl_projection_scope": "contract-objects-v1",
            "acl_projection_count": len(acl_projection),
            "acl_projection_sha256": access.sha256_bytes(
                access.canonical_json(acl_projection)
            ),
            "acl_projection": acl_projection,
            "grantable_acl_counts": {label: 0 for label in names},
            "public_acl_entry_counts": {
                scope: 0
                for scope in ("database", "schema", "relation", "sequence", "column")
            },
            "runtime_effective_role_sha256": [hashes["runtime"]],
            "role_effective_membership_sha256": {
                "owner": [hashes["owner"]],
                "migrator": [hashes["migrator"], hashes["owner"]],
                "runtime": [hashes["runtime"]],
                "audit": [hashes["audit"]],
            },
            "role_inbound_membership_sha256": {
                "owner": [hashes["migrator"]],
                "migrator": [],
                "runtime": [],
                "audit": [],
            },
            "migrator_owner_membership": {
                "admin_option": False,
                "inherit_option": False,
                "set_option": True,
            },
            "role_owned_user_object_count": {
                "owner": 8,
                "migrator": 0,
                "runtime": 0,
                "audit": 0,
            },
            "role_user_function_execute_count": {label: 0 for label in names},
            "runtime_database_create": False,
            "runtime_database_temp": False,
            "runtime_schema_create": False,
            "runtime_schema_create_count": 0,
            "runtime_schema_create_sha256": empty,
            "runtime_schema_usage": True,
            "runtime_out_of_contract_write_privilege_count": 0,
            "runtime_out_of_contract_write_privilege_sha256": empty,
            "runtime_out_of_contract_read_privilege_count": 0,
            "runtime_out_of_contract_read_privilege_sha256": empty,
            "authority_boundary_deviation_count": 0,
            "authority_boundary_deviation_sha256": empty,
            "audit_principal_read_only": True,
            "audit_effective_role_sha256": [hashes["audit"]],
            "audit_database_create": False,
            "audit_database_temp": False,
            "audit_schema_create": False,
            "audit_schema_create_count": 0,
            "audit_schema_create_sha256": empty,
            "audit_data_read_privilege_count": 0,
            "audit_data_read_privilege_sha256": empty,
            "audit_write_privilege_count": 0,
            "audit_write_privilege_sha256": empty,
            "audit_column_write_privilege_count": 0,
            "audit_column_write_privilege_sha256": empty,
        },
    }


def _neo_row(
    action: str, *, segment: str | None = None, graph: str | None = None
) -> dict:
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
        "access": "GRANTED",
        "action": action,
        "resource": resource,
        "graph": graph,
        "segment": segment,
        "immutable": False,
    }


def _neo_data_role(*, migrator: bool = False) -> list[dict]:
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


def _neo_audit_role() -> list[dict]:
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


def _neo_auth_settings() -> list[dict]:
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


def _neo_observation(nonce: str) -> dict:
    neo = _policy()["neo4j"]
    runtime = _neo_data_role()
    migrator = _neo_data_role(migrator=True)
    named = {
        "audit": _neo_audit_role(),
        "migrator": migrator,
        "runtime": runtime,
        "public": [],
    }
    effective = list(named["audit"])
    role_hashes = {
        label: access.sha256_bytes(neo[f"{label}_role"].encode())
        for label in ("audit", "migrator", "runtime")
    }
    public_hash = access.sha256_bytes(b"PUBLIC")
    empty = access.sha256_bytes(access.canonical_json([]))
    return {
        "status": "OBSERVED",
        "failure_codes": [],
        "facts": {
            "database": "neo4j",
            "challenge_nonce_sha256": access.sha256_bytes(nonce.encode()),
            "database_name_matches": True,
            "database_direct_local": True,
            "database_alias_count": 0,
            "database_alias_sha256": empty,
            "database_catalog_sha256": access.sha256_bytes(access.canonical_json([{
                "name_sha256": access.sha256_bytes(b"neo4j"),
                "type": "standard", "current_status": "online",
            }])),
            "database_id_sha256": access.sha256_bytes(b"neo4j-db-id"),
            "edition": "enterprise",
            "version": "2026.06.0",
            "enterprise": True,
            "current_actor_sha256": access.sha256_bytes(neo["audit_user"].encode()),
            "role_sha256": sorted([role_hashes["audit"], public_hash]),
            "role_count": 2,
            "effective_privilege_sha256": access.sha256_bytes(
                access.canonical_json(effective)
            ),
            "effective_privilege_count": len(effective),
            "effective_privileges": effective,
            "audit_principal_read_only": True,
            "audit_unsafe_granted_action_count": 0,
            "audit_unsafe_granted_action_sha256": empty,
            "named_role_sha256": role_hashes,
            "named_role_privilege_sha256": {
                label: access.sha256_bytes(access.canonical_json(named[label]))
                for label in ("audit", "migrator", "runtime")
            },
            "named_role_privileges": named,
            "public_role_binding_sha256": access.sha256_bytes(
                access.canonical_json(named["public"])
            ),
            "custom_role_binding_ok": True,
            "named_user_role_sha256": {
                label: sorted([role_hashes[label], public_hash])
                for label in role_hashes
            },
            "named_role_assignee_sha256": {
                label: [access.sha256_bytes(neo[f"{label}_user"].encode())]
                for label in ("audit", "migrator", "runtime")
            },
            "named_user_role_binding_ok": True,
            "runtime_role_least_privilege": True,
            "migrator_role_least_privilege": True,
            "public_role_safe": True,
            "auth_settings": _neo_auth_settings(),
            "auth_settings_sha256": access.sha256_bytes(
                access.canonical_json(_neo_auth_settings())
            ),
            "native_only_auth": True,
            "global_unsafe_privilege_count": 0,
            "global_unsafe_privilege_sha256": empty,
            "system_database_id_sha256": access.sha256_bytes(b"system-db-id"),
            "system_last_committed_tx": 41,
            "authorization_snapshot_stable": True,
            "read_query_count": 12,
        },
    }


def _receipt(target_sha: str) -> dict:
    operation = predeploy.operation_identity(ARTIFACT)
    report = {
        "contract_id": predeploy.CONTRACT_ID,
        "ok": True,
        "failures": [],
        "details": {},
    }
    fence_body = {
        "schema_version": predeploy.FENCE_VERIFICATION_SCHEMA,
        "active": True,
        "nonce": "d" * 64,
        "environment": "production",
        "target_sha256": target_sha,
        "operation_sha256": operation["sha256"],
        "lease_id": "lease-storage-access-ooptdd",
        "drain_receipt_sha256": "d" * 64,
        "verified_at": "2026-08-01T23:59:54+00:00",
        "expires_at": "2026-08-02T00:00:40+00:00",
        "evidence_refs": ["lease-store://ooptdd-exact-readback"],
    }
    signed_fence = {
        **fence_body,
        "signature": Ed25519PrivateKey.from_private_bytes(FENCE_SECRET).sign(
            predeploy._fence_signing_payload(fence_body)
        ).hex(),
    }
    body = {
        "schema_version": predeploy.RECEIPT_SCHEMA,
        "contract_id": predeploy.CONTRACT_ID,
        "environment": "production",
        "artifact": ARTIFACT,
        "operation": operation,
        "target_sha256": target_sha,
        "target": _target_details(),
        "principals": predeploy.principal_bindings(
            postgresql_migrator="lakatos_migrator",
            postgresql_runtime="lakatos_runtime",
            neo4j_migrator="lakatos_migrator_user",
            neo4j_runtime="lakatos_runtime_user",
        ),
        "writer_drain": {
            "sha256": "d" * 64,
            "schema_version": predeploy.DRAIN_SCHEMA,
            "environment": "production",
            "lease_id": "lease-storage-access-ooptdd",
            "verified_at": "2026-08-01T23:59:00+00:00",
            "expires_at": "2026-08-02T00:10:00+00:00",
            "target_sha256": target_sha,
            "operation_sha256": operation["sha256"],
            "evidence_refs": ["ops://drain/ooptdd"],
            "live_fence": {
                "schema_version": predeploy.FENCE_VERIFICATION_SCHEMA,
                "verifier_sha256": "f" * 64,
                "authority_key_sha256": predeploy._fence_authority_sha256(
                    ed25519_public_key(FENCE_SECRET).hex()
                ),
                "signed_response": signed_fence,
                "verified_at": fence_body["verified_at"],
                "expires_at": fence_body["expires_at"],
                "evidence_refs": fence_body["evidence_refs"],
            },
        },
        "postgresql": {"ok": True, "report": report},
        "neo4j": {
            "ok": True,
            "migration_ok": True,
            "payload_normalization": {
                "schema_version": predeploy.NORMALIZATION_RECEIPT_SCHEMA,
                "before": {"row_count": 0, "projection_sha256": "a" * 64},
                "after": {"row_count": 0, "projection_sha256": "a" * 64},
                "updated_count": 0,
            },
            "report": report,
        },
        "created_at": "2026-08-01T23:59:55+00:00",
    }
    return {**body, "receipt_sha256": _sha(_canonical(body))}


def _expected(
    phase: str,
    *,
    policy_sha: str,
    receipt_file_sha: str,
    receipt_sha: str,
    previous: str | None = None,
) -> dict:
    target = _target_details()
    return {
        "request_nonce": ("1" if phase == "predeploy" else "2") * 64,
        "request_sha256": ("3" if phase == "predeploy" else "4") * 64,
        "target_sha256": access.sha256_bytes(access.canonical_json(target)),
        "target_details": target,
        "operation_sha256": predeploy.operation_identity(ARTIFACT)["sha256"],
        "access_policy_file_sha256": policy_sha,
        "predeploy_receipt_file_sha256": receipt_file_sha,
        "predeploy_receipt_sha256": receipt_sha,
        "previous_phase_bundle_file_sha256": previous,
    }


def _signed(
    store: str,
    phase: str,
    position: str,
    expected: dict,
    observation: dict,
    observed_at: str,
    expires_at: str,
) -> dict:
    secret, did = (
        (PG_SECRET, PG_DID) if store == "postgresql" else (NEO_SECRET, NEO_DID)
    )
    body = access.build_attestation_body(
        store=store,
        phase=phase,
        position=position,
        expected=expected,
        environment="production",
        observation=observation,
        target_binding=expected["target_details"][store],
        observed_at=observed_at,
        expires_at=expires_at,
        evidence_refs=[f"fixture://{phase}/{store}/{position}"],
        signer_did=did,
    )
    return access.seal_datastore_attestation(body, secret)


def _bundle(
    phase: str,
    expected: dict,
    *,
    within_change: str | None = None,
    stable_change: str | None = None,
    times: tuple[str, str, str] | None = None,
) -> dict:
    if times is None:
        times = (
            (
                "2026-08-02T00:00:00+00:00",
                "2026-08-02T00:00:01+00:00",
                "2026-08-02T00:05:00+00:00",
            )
            if phase == "predeploy"
            else (
                "2026-08-02T00:02:00+00:00",
                "2026-08-02T00:02:01+00:00",
                "2026-08-02T00:07:00+00:00",
            )
        )
    before_at, after_at, expires_at = times
    observations = {
        "postgresql": _pg_observation(expected["request_nonce"]),
        "neo4j": _neo_observation(expected["request_nonce"]),
    }
    if stable_change == "postgresql":
        observations["postgresql"]["facts"]["role_owned_user_object_count"][
            "owner"
        ] = 9
    elif stable_change == "neo4j":
        observations["neo4j"]["facts"]["version"] = "2026.06.1"
    pairs = {}
    for store in ("postgresql", "neo4j"):
        after_observation = copy.deepcopy(observations[store])
        if within_change == store:
            if store == "postgresql":
                after_observation["facts"]["role_owned_user_object_count"]["owner"] = 9
            else:
                after_observation["facts"]["version"] = "2026.06.1"
        pairs[store] = {
            "before": _signed(
                store,
                phase,
                "before",
                expected,
                observations[store],
                before_at,
                expires_at,
            ),
            "after": _signed(
                store,
                phase,
                "after",
                expected,
                after_observation,
                after_at,
                expires_at,
            ),
        }
    return access.build_storage_audit_bundle(
        phase=phase,
        request_nonce=expected["request_nonce"],
        request_sha256=expected["request_sha256"],
        previous_phase_bundle_file_sha256=expected[
            "previous_phase_bundle_file_sha256"
        ],
        postgresql_before=pairs["postgresql"]["before"],
        postgresql_after=pairs["postgresql"]["after"],
        neo4j_before=pairs["neo4j"]["before"],
        neo4j_after=pairs["neo4j"]["after"],
    )


def _documents() -> dict:
    policy_raw = _canonical(_policy())
    target_sha = access.sha256_bytes(access.canonical_json(_target_details()))
    receipt = _receipt(target_sha)
    receipt_raw = _canonical(receipt)
    pre_expected = _expected(
        "predeploy",
        policy_sha=_sha(policy_raw),
        receipt_file_sha=_sha(receipt_raw),
        receipt_sha=receipt["receipt_sha256"],
    )
    pre_bundle = _bundle("predeploy", pre_expected)
    pre_raw = _canonical(pre_bundle)
    start_expected = _expected(
        "startup",
        policy_sha=_sha(policy_raw),
        receipt_file_sha=_sha(receipt_raw),
        receipt_sha=receipt["receipt_sha256"],
        previous=_sha(pre_raw),
    )
    start_bundle = _bundle("startup", start_expected)
    return {
        "policy": _policy(),
        "policy_raw": policy_raw,
        "receipt": receipt,
        "receipt_raw": receipt_raw,
        "pre_expected": pre_expected,
        "pre_bundle": pre_bundle,
        "pre_raw": pre_raw,
        "start_expected": start_expected,
        "start_bundle": start_bundle,
        "start_raw": _canonical(start_bundle),
    }


def _raw_pair(docs: dict, **overrides):
    values = {
        "expected_predeploy_file_sha256": _sha(docs["pre_raw"]),
        "expected_startup_file_sha256": _sha(docs["start_raw"]),
        "policy_raw": docs["policy_raw"],
        "expected_policy_file_sha256": _sha(docs["policy_raw"]),
        "predeploy_receipt_raw": docs["receipt_raw"],
        "expected_predeploy_receipt_file_sha256": _sha(docs["receipt_raw"]),
        "evaluated_at": EVALUATED_AT,
    }
    values.update(overrides)
    return access.verify_access_attestation_pair_bytes(
        docs["pre_raw"], docs["start_raw"], **values
    )


def _direct_observation(
    docs: dict,
    store: str,
    observation: dict,
    *,
    evaluated_at: datetime = datetime(2026, 8, 2, 0, 1, tzinfo=timezone.utc),
):
    signed = _signed(
        store,
        "predeploy",
        "before",
        docs["pre_expected"],
        observation,
        "2026-08-02T00:00:00+00:00",
        "2026-08-02T00:05:00+00:00",
    )
    return access.verify_datastore_attestation(
        signed,
        policy=docs["policy"],
        expected=docs["pre_expected"],
        expected_store=store,
        expected_phase="predeploy",
        expected_position="before",
        expected_signer_did=(PG_DID if store == "postgresql" else NEO_DID),
        evaluated_at=evaluated_at,
    )


def verify(backend, cid):
    manifest = json.loads(
        Path(__file__).with_name("harness.json").read_text(encoding="utf-8")
    )
    required_controls = set(manifest["required_controls"])
    executed: set[str] = set()

    def control(name: str, condition: bool, message) -> None:
        _require(condition, message)
        _require(name in required_controls, f"undeclared control executed: {name}")
        executed.add(name)

    docs = _documents()
    policy = docs["policy"]
    control(
        "policy.exact_positive",
        access.validate_access_policy(policy) is policy,
        "canonical policy rejected",
    )
    for control_id, mutate in (
        (
            "policy.pg_roles_distinct",
            lambda value: value["postgresql"].__setitem__(
                "audit_role", value["postgresql"]["runtime_role"]
            ),
        ),
        (
            "policy.store_signers_distinct",
            lambda value: value["attestors"].__setitem__(
                "neo4j", value["attestors"]["postgresql"]
            ),
        ),
        (
            "policy.fence_attestor_distinct",
            lambda value: value["predeploy_authority"].__setitem__(
                "fence_public_key_hex", ed25519_public_key(PG_SECRET).hex()
            ),
        ),
    ):
        attacked = copy.deepcopy(policy)
        mutate(attacked)
        try:
            access.validate_access_policy(attacked)
        except access.StorageAccessError:
            rejected = True
        else:
            rejected = False
        control(control_id, rejected, f"policy attack accepted: {control_id}")
    attacked = copy.deepcopy(policy)
    attacked["neo4j"]["database"] = "*"
    try:
        access.validate_access_policy(attacked)
    except access.StorageAccessError:
        rejected = True
    else:
        rejected = False
    control(
        "policy.neo_concrete_database",
        rejected,
        "global Neo4j graph name accepted as a concrete application database",
    )
    backend.ship([_event(cid, "exact_policy_and_signer_separation_enforced")])

    original_artifact = predeploy._artifact_identity
    try:
        predeploy._artifact_identity = lambda: dict(ARTIFACT)
        positive = _raw_pair(docs)
        control(
            "raw.complete_positive_chain",
            positive.status == "ACCESS_PAIR_VERIFIED"
            and positive.production_ready is False
            and positive.deployment_status == "NOT_READY",
            positive.failures,
        )
        control(
            "raw.predeploy_file_pin",
            _raw_pair(
                docs, expected_predeploy_file_sha256="0" * 64
            ).status == "NOT_READY",
            "predeploy raw pin splice accepted",
        )
        control(
            "raw.startup_file_pin",
            _raw_pair(
                docs, expected_startup_file_sha256="0" * 64
            ).status == "NOT_READY",
            "startup raw pin splice accepted",
        )
        duplicate_policy = docs["policy_raw"].replace(
            b'{"attestors":', b'{"attestors":{},"attestors":', 1
        )
        control(
            "raw.duplicate_policy_key",
            _raw_pair(
                docs,
                policy_raw=duplicate_policy,
                expected_policy_file_sha256=_sha(duplicate_policy),
            ).status == "NOT_READY",
            "duplicate-key policy accepted",
        )
        weak_receipt = _canonical({
            "schema_version": predeploy.RECEIPT_SCHEMA,
            "receipt_sha256": "0" * 64,
        })
        control(
            "raw.v5_receipt_splice",
            _raw_pair(
                docs,
                predeploy_receipt_raw=weak_receipt,
                expected_predeploy_receipt_file_sha256=_sha(weak_receipt),
            ).status == "NOT_READY",
            "weak v5 receipt accepted",
        )
        predeploy._artifact_identity = lambda: {
            "kind": "git",
            "source_commit": "6" * 40,
        }
        control(
            "raw.artifact_operation_binding",
            _raw_pair(docs).status == "NOT_READY",
            "well-formed wrong artifact operation accepted",
        )
    finally:
        predeploy._artifact_identity = original_artifact
    backend.ship([_event(cid, "signed_phase_pair_verified_claim_bounded")])

    signed = docs["pre_bundle"]["attestations"]["postgresql"]["before"]
    forged = copy.deepcopy(signed)
    forged["target_sha256"] = "c" * 64
    forged_proof = access.verify_datastore_attestation(
        forged,
        policy=policy,
        expected=docs["pre_expected"],
        expected_store="postgresql",
        expected_phase="predeploy",
        expected_position="before",
        expected_signer_did=PG_DID,
        evaluated_at=datetime(2026, 8, 2, 0, 1, tzinfo=timezone.utc),
    )
    control(
        "crypto.signature_tamper",
        not forged_proof.ok and "signature_invalid" in forged_proof.failures,
        "signature forgery accepted",
    )
    wrong_signer = access.verify_datastore_attestation(
        signed,
        policy=policy,
        expected=docs["pre_expected"],
        expected_store="postgresql",
        expected_phase="predeploy",
        expected_position="before",
        expected_signer_did=NEO_DID,
        evaluated_at=datetime(2026, 8, 2, 0, 1, tzinfo=timezone.utc),
    )
    control(
        "crypto.signer_mismatch",
        "signer_mismatch" in wrong_signer.failures,
        "wrong signer accepted",
    )
    wrong_phase = access.verify_datastore_attestation(
        signed,
        policy=policy,
        expected=docs["pre_expected"],
        expected_store="postgresql",
        expected_phase="startup",
        expected_position="before",
        expected_signer_did=PG_DID,
        evaluated_at=datetime(2026, 8, 2, 0, 1, tzinfo=timezone.utc),
    )
    control(
        "crypto.phase_mismatch",
        "phase_mismatch" in wrong_phase.failures,
        "signed phase mismatch accepted",
    )
    expired = access.verify_datastore_attestation(
        signed,
        policy=policy,
        expected=docs["pre_expected"],
        expected_store="postgresql",
        expected_phase="predeploy",
        expected_position="before",
        expected_signer_did=PG_DID,
        evaluated_at=datetime(2026, 8, 2, 0, 6, tzinfo=timezone.utc),
    )
    control(
        "crypto.attestation_expiry",
        "freshness_invalid" in expired.failures,
        "expired attestation accepted",
    )
    replay_expected = copy.deepcopy(docs["start_expected"])
    replay_expected["request_nonce"] = docs["pre_expected"]["request_nonce"]
    replay = access.verify_access_attestation_pair(
        docs["pre_bundle"],
        _bundle("startup", replay_expected),
        predeploy_bundle_file_sha256=_sha(docs["pre_raw"]),
        policy=policy,
        expected_predeploy=docs["pre_expected"],
        expected_startup=replay_expected,
        signer_dids=policy["attestors"],
        evaluated_at=EVALUATED_AT,
    )
    control(
        "crypto.cross_phase_nonce_reuse",
        "phase_nonce_reused" in replay.failures,
        "cross-phase nonce reuse accepted",
    )
    backend.ship([_event(
        cid, "crypto_schema_cross_phase_nonce_attacks_rejected"
    )])

    within = access.verify_storage_audit_bundle(
        _bundle("predeploy", docs["pre_expected"], within_change="postgresql"),
        policy=policy,
        expected=docs["pre_expected"],
        phase="predeploy",
        signer_dids=policy["attestors"],
        evaluated_at=datetime(2026, 8, 2, 0, 1, tzinfo=timezone.utc),
    )
    control(
        "drift.within_phase",
        not within.ok and any("observation_drift" in item for item in within.failures),
        "within-phase observation drift accepted",
    )
    cross = access.verify_access_attestation_pair(
        docs["pre_bundle"],
        _bundle("startup", docs["start_expected"], stable_change="neo4j"),
        predeploy_bundle_file_sha256=_sha(docs["pre_raw"]),
        policy=policy,
        expected_predeploy=docs["pre_expected"],
        expected_startup=docs["start_expected"],
        signer_dids=policy["attestors"],
        evaluated_at=EVALUATED_AT,
    )
    control(
        "drift.cross_phase",
        "neo4j.phase_projection_drift" in cross.failures,
        "cross-phase projection drift accepted",
    )
    disjoint = access.build_storage_audit_bundle(
        phase="predeploy",
        request_nonce=docs["pre_expected"]["request_nonce"],
        request_sha256=docs["pre_expected"]["request_sha256"],
        previous_phase_bundle_file_sha256=None,
        postgresql_before=_signed(
            "postgresql", "predeploy", "before", docs["pre_expected"],
            _pg_observation(docs["pre_expected"]["request_nonce"]),
            "2026-08-02T00:00:00+00:00", "2026-08-02T00:05:00+00:00",
        ),
        postgresql_after=_signed(
            "postgresql", "predeploy", "after", docs["pre_expected"],
            _pg_observation(docs["pre_expected"]["request_nonce"]),
            "2026-08-02T00:01:00+00:00", "2026-08-02T00:05:00+00:00",
        ),
        neo4j_before=_signed(
            "neo4j", "predeploy", "before", docs["pre_expected"],
            _neo_observation(docs["pre_expected"]["request_nonce"]),
            "2026-08-02T00:02:00+00:00", "2026-08-02T00:05:00+00:00",
        ),
        neo4j_after=_signed(
            "neo4j", "predeploy", "after", docs["pre_expected"],
            _neo_observation(docs["pre_expected"]["request_nonce"]),
            "2026-08-02T00:03:00+00:00", "2026-08-02T00:05:00+00:00",
        ),
    )
    disjoint_proof = access.verify_storage_audit_bundle(
        disjoint,
        policy=policy,
        expected=docs["pre_expected"],
        phase="predeploy",
        signer_dids=policy["attestors"],
        evaluated_at=datetime(2026, 8, 2, 0, 4, tzinfo=timezone.utc),
    )
    control(
        "drift.cross_store_observation_bracket",
        "bundle.cross_store_observation_order_invalid"
        in disjoint_proof.failures,
        "disjoint datastore observation intervals accepted",
    )
    late_start = _bundle(
        "startup",
        docs["start_expected"],
        times=(
            "2026-08-02T00:06:00+00:00",
            "2026-08-02T00:06:01+00:00",
            "2026-08-02T00:11:00+00:00",
        ),
    )
    handoff = access.verify_access_attestation_pair(
        docs["pre_bundle"],
        late_start,
        predeploy_bundle_file_sha256=_sha(docs["pre_raw"]),
        policy=policy,
        expected_predeploy=docs["pre_expected"],
        expected_startup=docs["start_expected"],
        signer_dids=policy["attestors"],
        evaluated_at=datetime(2026, 8, 2, 0, 7, tzinfo=timezone.utc),
    )
    control(
        "drift.phase_handoff_expiry",
        "phase_handoff_window_invalid" in handoff.failures,
        "expired phase handoff accepted",
    )

    pg_runtime = _pg_observation(docs["pre_expected"]["request_nonce"])
    pg_runtime["facts"]["runtime_database_temp"] = True
    pg_runtime["facts"]["runtime_out_of_contract_write_privilege_count"] = 1
    pg_proof = _direct_observation(docs, "postgresql", pg_runtime)
    control(
        "authority.pg_runtime_overgrant",
        "postgresql.runtime_database_temp" in pg_proof.failures
        and "postgresql.runtime_out_of_contract_write_privilege" in pg_proof.failures,
        "PostgreSQL runtime overgrant accepted",
    )
    pg_acl = _pg_observation(docs["pre_expected"]["request_nonce"])
    pg_acl_rows = pg_acl["facts"]["acl_projection"]
    pg_acl_rows.pop()
    pg_acl["facts"]["acl_projection_count"] = len(pg_acl_rows)
    pg_acl["facts"]["acl_projection_sha256"] = access.sha256_bytes(
        access.canonical_json(pg_acl_rows)
    )
    pg_acl_proof = _direct_observation(docs, "postgresql", pg_acl)
    control(
        "authority.pg_required_acl",
        "postgresql.required_acl" in pg_acl_proof.failures,
        "PostgreSQL required runtime ACL omission accepted",
    )
    pg_boundary = _pg_observation(docs["pre_expected"]["request_nonce"])
    pg_boundary["facts"]["authority_boundary_deviation_count"] = 1
    pg_boundary_proof = _direct_observation(docs, "postgresql", pg_boundary)
    control(
        "authority.pg_system_boundary",
        "postgresql.authority_boundary_deviation" in pg_boundary_proof.failures,
        "PostgreSQL system authority deviation accepted",
    )
    pg_assignee = _pg_observation(docs["pre_expected"]["request_nonce"])
    pg_assignee["facts"]["role_inbound_membership_sha256"]["runtime"] = [
        "b" * 64
    ]
    pg_assignee_proof = _direct_observation(docs, "postgresql", pg_assignee)
    control(
        "authority.pg_inbound_assignee",
        "postgresql.inbound_role_memberships" in pg_assignee_proof.failures,
        "PostgreSQL rogue inbound role member accepted",
    )

    neo_scope = _neo_observation(docs["pre_expected"]["request_nonce"])
    runtime_rows = neo_scope["facts"]["named_role_privileges"]["runtime"]
    runtime_rows[1]["segment"] = "NODE(Secret)"
    neo_scope["facts"]["named_role_privilege_sha256"]["runtime"] = (
        access.sha256_bytes(access.canonical_json(runtime_rows))
    )
    neo_scope_proof = _direct_observation(docs, "neo4j", neo_scope)
    control(
        "authority.neo_runtime_scope",
        "neo4j.runtime_privileges" in neo_scope_proof.failures,
        "Neo4j label-scoped runtime role accepted as whole graph",
    )
    neo_migrator = _neo_observation(docs["pre_expected"]["request_nonce"])
    migrator_rows = neo_migrator["facts"]["named_role_privileges"]["migrator"]
    migrator_rows.pop()
    neo_migrator["facts"]["named_role_privilege_sha256"]["migrator"] = (
        access.sha256_bytes(access.canonical_json(migrator_rows))
    )
    neo_migrator_proof = _direct_observation(docs, "neo4j", neo_migrator)
    control(
        "authority.neo_migrator_token",
        "neo4j.migrator_privileges" in neo_migrator_proof.failures,
        "Neo4j migrator without NAME MANAGEMENT token authority accepted",
    )
    neo_system = _neo_observation(docs["pre_expected"]["request_nonce"])
    neo_system_rows = neo_system["facts"]["named_role_privileges"]["audit"]
    neo_system_rows[:] = [
        row for row in neo_system_rows
        if not (row["action"] == "access" and row["graph"] == "system")
    ]
    neo_system["facts"]["named_role_privilege_sha256"]["audit"] = (
        access.sha256_bytes(access.canonical_json(neo_system_rows))
    )
    neo_system["facts"]["effective_privileges"] = list(neo_system_rows)
    neo_system["facts"]["effective_privilege_count"] = len(neo_system_rows)
    neo_system["facts"]["effective_privilege_sha256"] = access.sha256_bytes(
        access.canonical_json(neo_system_rows)
    )
    neo_system_proof = _direct_observation(docs, "neo4j", neo_system)
    control(
        "authority.neo_audit_system_access",
        "neo4j.audit_role_privileges" in neo_system_proof.failures,
        "Neo4j audit role without system database access accepted",
    )
    neo_release = _neo_observation(docs["pre_expected"]["request_nonce"])
    neo_release["facts"]["version"] = "2026.07.0"
    neo_release_proof = _direct_observation(docs, "neo4j", neo_release)
    control(
        "authority.neo_supported_release",
        "neo4j.version" in neo_release_proof.failures,
        "unaudited future Neo4j release accepted",
    )
    neo_immutable = _neo_observation(docs["pre_expected"]["request_nonce"])
    immutable_rows = neo_immutable["facts"]["named_role_privileges"]["runtime"]
    immutable_rows[0]["immutable"] = True
    neo_immutable["facts"]["named_role_privilege_sha256"]["runtime"] = (
        access.sha256_bytes(access.canonical_json(immutable_rows))
    )
    neo_immutable_proof = _direct_observation(docs, "neo4j", neo_immutable)
    control(
        "authority.neo_mutable_privileges",
        "neo4j.runtime_privileges" in neo_immutable_proof.failures,
        "immutable Neo4j privilege accepted by exact mutable topology",
    )
    neo_snapshot = _neo_observation(docs["pre_expected"]["request_nonce"])
    neo_snapshot["facts"]["authorization_snapshot_stable"] = False
    neo_snapshot_proof = _direct_observation(docs, "neo4j", neo_snapshot)
    control(
        "authority.neo_authorization_snapshot",
        "neo4j.authorization_snapshot" in neo_snapshot_proof.failures,
        "Neo4j authority mutation during projection accepted",
    )
    neo_auth = _neo_observation(docs["pre_expected"]["request_nonce"])
    auth_row = next(
        row for row in neo_auth["facts"]["auth_settings"]
        if row["name"] == "dbms.security.authorization_providers"
    )
    auth_row["value"] = auth_row["startup_value"] = "ldap,native"
    neo_auth["facts"]["auth_settings_sha256"] = access.sha256_bytes(
        access.canonical_json(neo_auth["facts"]["auth_settings"])
    )
    neo_auth_proof = _direct_observation(docs, "neo4j", neo_auth)
    control(
        "authority.neo_native_only_auth",
        "neo4j.native_only_auth_settings" in neo_auth_proof.failures,
        "Neo4j external authorization provider accepted",
    )
    neo_access = _neo_observation(docs["pre_expected"]["request_nonce"])
    neo_access["facts"]["named_role_privileges"]["audit"][0]["access"] = "UNKNOWN"
    neo_access["facts"]["named_role_privilege_sha256"]["audit"] = (
        access.sha256_bytes(
            access.canonical_json(neo_access["facts"]["named_role_privileges"]["audit"])
        )
    )
    neo_access_proof = _direct_observation(docs, "neo4j", neo_access)
    control(
        "authority.neo_unknown_access",
        "neo4j.privilege_schema" in neo_access_proof.failures,
        "Neo4j unknown privilege access state accepted",
    )
    neo_alias = _neo_observation(docs["pre_expected"]["request_nonce"])
    neo_alias["facts"]["database_direct_local"] = False
    neo_alias_proof = _direct_observation(docs, "neo4j", neo_alias)
    control(
        "authority.neo_remote_alias",
        "neo4j.database_direct_local" in neo_alias_proof.failures,
        "Neo4j remote or aliased database accepted as direct local storage",
    )
    neo_global = _neo_observation(docs["pre_expected"]["request_nonce"])
    neo_global["facts"]["global_unsafe_privilege_count"] = 1
    neo_global_proof = _direct_observation(docs, "neo4j", neo_global)
    control(
        "authority.neo_unknown_active_role",
        "neo4j.global_unsafe_privilege" in neo_global_proof.failures,
        "Neo4j undeclared active authority accepted",
    )
    neo_public = _neo_observation(docs["pre_expected"]["request_nonce"])
    neo_public["facts"]["named_role_privileges"]["public"] = [_neo_row("write")]
    neo_public["facts"]["public_role_binding_sha256"] = access.sha256_bytes(
        access.canonical_json(neo_public["facts"]["named_role_privileges"]["public"])
    )
    neo_public_proof = _direct_observation(docs, "neo4j", neo_public)
    control(
        "authority.neo_public_overgrant",
        "neo4j.public_privileges" in neo_public_proof.failures,
        "Neo4j PUBLIC overgrant accepted",
    )
    neo_assignee = _neo_observation(docs["pre_expected"]["request_nonce"])
    neo_assignee["facts"]["named_role_assignee_sha256"]["runtime"].append(
        "c" * 64
    )
    neo_assignee_proof = _direct_observation(docs, "neo4j", neo_assignee)
    control(
        "authority.neo_extra_assignee",
        "neo4j.role_assignees" in neo_assignee_proof.failures,
        "Neo4j extra custom-role assignee accepted",
    )

    target_splice = copy.deepcopy(docs["pre_expected"])
    target_splice["target_details"]["postgresql"]["server_address"] = "192.0.2.50"
    target_splice["target_sha256"] = access.sha256_bytes(
        access.canonical_json(target_splice["target_details"])
    )
    try:
        access.validate_expected(target_splice, policy)
    except access.StorageAccessError:
        target_rejected = True
    else:
        target_rejected = False
    control(
        "binding.live_target",
        target_rejected,
        "different live target accepted",
    )

    attacked_receipt = copy.deepcopy(docs["receipt"])
    attacked_receipt.pop("receipt_sha256")
    attacked_receipt["principals"]["postgresql_runtime_sha256"] = "0" * 64
    attacked_receipt = {
        **attacked_receipt,
        "receipt_sha256": _sha(_canonical(attacked_receipt)),
    }
    attacked_receipt_raw = _canonical(attacked_receipt)
    try:
        predeploy.verify_predeploy_receipt_document(
            attacked_receipt,
            file_sha256=_sha(attacked_receipt_raw),
            expected_file_sha256=_sha(attacked_receipt_raw),
            expected_environment="production",
            expected_fence_verifier_sha256="f" * 64,
            expected_fence_public_key_hex=ed25519_public_key(FENCE_SECRET).hex(),
            artifact=ARTIFACT,
            operation=predeploy.operation_identity(ARTIFACT),
            target={
                "sha256": docs["pre_expected"]["target_sha256"],
                "details": _target_details(),
            },
            evaluated_at=EVALUATED_AT,
            expected_principals=predeploy.principal_bindings(
                postgresql_migrator="lakatos_migrator",
                postgresql_runtime="lakatos_runtime",
                neo4j_migrator="lakatos_migrator_user",
                neo4j_runtime="lakatos_runtime_user",
            ),
        )
    except (ValueError, RuntimeError):
        principal_rejected = True
    else:
        principal_rejected = False
    control(
        "binding.v5_principals",
        principal_rejected,
        "v5 principal splice accepted",
    )
    backend.ship([_event(cid, "authority_and_drift_attacks_rejected")])

    control(
        "manifest.exact_control_set",
        executed | {"manifest.exact_control_set"} == required_controls,
        {
            "missing": sorted(required_controls - executed),
            "unexpected": sorted(executed - required_controls),
        },
    )
    _require(executed == required_controls, "executed control manifest drift")
