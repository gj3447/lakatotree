"""Fail-closed exhaustive storage contract projections."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from lakatos.io.reconcile import canonical_history_payload, history_event_id
from lakatos.verdicts import (
    RECEIPT_FIELDS,
    receipt_content_sha,
    verdict_history_payload_sha,
)
from server.storage_contract import (
    CONTRACT_ID,
    StorageContractError,
    _boolean_ast,
    _diagnose_neo_outbox_projection,
    _diagnose_pg_projection,
    require_storage_contract,
)


TS = "2026-08-02T00:00:00+00:00"


def _pg_column(table_name, name, data_type, not_null, collation, default=None):
    return {
        "table_name": table_name,
        "name": name,
        "data_type": data_type,
        "not_null": not_null,
        "collation": collation,
        "default_expr": default,
        "identity_kind": "",
        "generated_kind": "",
    }


def _valid_aux_columns():
    return [
        _pg_column("lineage", "id", "bigint", True, None,
                   "nextval('lineage_id_seq'::regclass)"),
        _pg_column("lineage", "ts", "timestamp with time zone", True, None,
                   "now()"),
        _pg_column("lineage", "output", "text", True, "pg_catalog.default"),
        _pg_column("lineage", "output_sha", "text", False,
                   "pg_catalog.default"),
        _pg_column("lineage", "producer", "text", False,
                   "pg_catalog.default"),
        _pg_column("lineage", "producer_sha", "text", False,
                   "pg_catalog.default"),
        _pg_column("lineage", "inputs", "jsonb", False, None),
        _pg_column("lineage", "params", "jsonb", False, None),
        _pg_column("lineage", "kind", "text", False, "pg_catalog.default"),
        _pg_column("lineage", "env", "text", False, "pg_catalog.default"),
        _pg_column("metric_snapshots", "id", "bigint", True, None,
                   "nextval('metric_snapshots_id_seq'::regclass)"),
        _pg_column("metric_snapshots", "ts", "timestamp with time zone", True,
                   None, "now()"),
        _pg_column("metric_snapshots", "tree", "text", True,
                   "pg_catalog.default"),
        _pg_column("metric_snapshots", "metrics", "jsonb", False, None),
    ]


def _valid_pg_projection():
    tree, arg_id = "T", "a1"
    stable_id = history_event_id(tree, "critique", f"{tree}/{arg_id}")
    payload = {"arg_id": arg_id, "body": "same"}
    return {
        "objects": {
            "history_exists": True,
            "claims_exists": True,
            "metrics_exists": True,
            "lineage_exists": True,
            "history_kind": "r",
            "history_persistence": "p",
            "history_has_subclass": False,
            "history_is_partition": False,
            "claims_kind": "r",
            "claims_persistence": "p",
            "claims_has_subclass": False,
            "claims_is_partition": False,
            "metrics_kind": "r",
            "metrics_persistence": "p",
            "metrics_has_subclass": False,
            "metrics_is_partition": False,
            "lineage_kind": "r",
            "lineage_persistence": "p",
            "lineage_has_subclass": False,
            "lineage_is_partition": False,
            "sequence_kind": "S",
            "sequence_persistence": "p",
            "metrics_sequence_kind": "S",
            "metrics_sequence_persistence": "p",
            "lineage_sequence_kind": "S",
            "lineage_sequence_persistence": "p",
            "inheritance_edges": 0,
        },
        "history_columns": [
            {"name": "id", "data_type": "bigint", "not_null": True,
             "collation": None,
             "default_expr": "nextval('history_id_seq'::regclass)",
             "identity_kind": "", "generated_kind": ""},
            {"name": "ts", "data_type": "timestamp with time zone", "not_null": True,
             "collation": None,
             "default_expr": "now()", "identity_kind": "", "generated_kind": ""},
            {"name": "tree", "data_type": "text", "not_null": True,
             "collation": "pg_catalog.default",
             "default_expr": None, "identity_kind": "", "generated_kind": ""},
            {"name": "op", "data_type": "text", "not_null": True,
             "collation": "pg_catalog.default",
             "default_expr": None, "identity_kind": "", "generated_kind": ""},
            {"name": "node_tag", "data_type": "text", "not_null": False,
             "collation": "pg_catalog.default",
             "default_expr": None, "identity_kind": "", "generated_kind": ""},
            {"name": "payload", "data_type": "jsonb", "not_null": False,
             "collation": None,
             "default_expr": None, "identity_kind": "", "generated_kind": ""},
            {"name": "event_id", "data_type": "text", "not_null": False,
             "collation": "pg_catalog.default",
             "default_expr": None, "identity_kind": "", "generated_kind": ""},
        ],
        "claims_columns": [
            {"name": "stable_event_id", "data_type": "text", "not_null": True,
             "collation": "pg_catalog.default",
             "default_expr": None, "identity_kind": "", "generated_kind": ""},
            {"name": "history_id", "data_type": "bigint", "not_null": True,
             "collation": None,
             "default_expr": None, "identity_kind": "", "generated_kind": ""},
            {"name": "claimed_at", "data_type": "timestamp with time zone",
             "not_null": True, "collation": None, "default_expr": "now()",
             "identity_kind": "", "generated_kind": ""},
        ],
        "aux_columns": _valid_aux_columns(),
        "constraints": [
            {"name": "history_pkey", "kind": "p", "validated": True,
             "table_schema": "public", "table_name": "history",
             "referenced_schema": None, "referenced_table": None,
             "deferrable": False, "initially_deferred": False,
             "update_action": " ", "delete_action": " ", "match_type": " ",
             "columns": ["id"], "referenced_columns": []},
            {"name": "history_event_claims_pkey", "kind": "p", "validated": True,
             "table_schema": "public", "table_name": "history_event_claims",
             "referenced_schema": None, "referenced_table": None,
             "deferrable": False, "initially_deferred": False,
             "update_action": " ", "delete_action": " ", "match_type": " ",
             "columns": ["stable_event_id"], "referenced_columns": []},
            {"name": "history_event_claims_history_id_key", "kind": "u",
             "validated": True, "table_schema": "public",
             "table_name": "history_event_claims", "referenced_schema": None,
             "referenced_table": None, "deferrable": False,
             "initially_deferred": False, "update_action": " ",
             "delete_action": " ", "match_type": " ",
             "columns": ["history_id"], "referenced_columns": []},
            {"name": "history_event_claims_history_id_fkey", "kind": "f",
             "validated": True, "table_schema": "public",
             "table_name": "history_event_claims", "referenced_schema": "public",
             "referenced_table": "history", "deferrable": False,
             "initially_deferred": False, "update_action": "a",
             "delete_action": "a", "match_type": "s",
             "columns": ["history_id"], "referenced_columns": ["id"]},
            {"name": "metric_snapshots_pkey", "kind": "p",
             "validated": True, "table_schema": "public",
             "table_name": "metric_snapshots", "referenced_schema": None,
             "referenced_table": None, "deferrable": False,
             "initially_deferred": False, "update_action": " ",
             "delete_action": " ", "match_type": " ",
             "columns": ["id"], "referenced_columns": []},
            {"name": "lineage_pkey", "kind": "p", "validated": True,
             "table_schema": "public", "table_name": "lineage",
             "referenced_schema": None, "referenced_table": None,
             "deferrable": False, "initially_deferred": False,
             "update_action": " ", "delete_action": " ", "match_type": " ",
             "columns": ["id"], "referenced_columns": []},
        ],
        "indexes": [
            {"name": "history_pkey", "table_schema": "public",
             "table_name": "history", "is_unique": True,
             "access_method": "btree", "nulls_not_distinct": False,
             "is_exclusion": False, "is_valid": True, "is_ready": True,
             "is_live": True, "key_count": 1, "total_count": 1,
             "keys": ["id"], "options": [0],
             "opclasses": ["pg_catalog.int8_ops"], "collations": [None],
             "predicate": None},
            {"name": "idx_history_tree_ts", "table_schema": "public",
             "table_name": "history", "is_unique": False,
             "access_method": "btree", "nulls_not_distinct": False,
             "is_exclusion": False, "is_valid": True, "is_ready": True,
             "is_live": True, "key_count": 2, "total_count": 2,
             "keys": ["tree", "ts"], "options": [0, 3],
             "opclasses": ["pg_catalog.text_ops", "pg_catalog.timestamptz_ops"],
             "collations": ["pg_catalog.default", None], "predicate": None},
            {"name": "uq_history_event_id", "table_schema": "public",
             "table_name": "history", "is_exclusion": False,
             "access_method": "btree", "nulls_not_distinct": False,
             "is_unique": True, "is_valid": True, "is_ready": True,
             "is_live": True, "key_count": 1, "total_count": 1,
             "keys": ["event_id"], "options": [0],
             "opclasses": ["pg_catalog.text_ops"],
             "collations": ["pg_catalog.default"],
             "predicate": "(event_id IS NOT NULL)"},
            {"name": "uq_history_critique_logical_identity",
             "table_schema": "public", "is_unique": True, "is_valid": True,
             "access_method": "btree", "nulls_not_distinct": False,
             "table_name": "history", "is_exclusion": False,
             "is_ready": True, "is_live": True, "key_count": 2,
             "total_count": 2, "keys": ["tree", "((payload ->> 'arg_id'::text))"],
             "options": [0, 0],
             "opclasses": ["pg_catalog.text_ops", "pg_catalog.text_ops"],
             "collations": ["pg_catalog.default", "pg_catalog.default"],
             "predicate": "(op = 'critique'::text)"},
            {"name": "history_event_claims_pkey", "table_schema": "public",
             "table_name": "history_event_claims", "is_unique": True,
             "access_method": "btree", "nulls_not_distinct": False,
             "is_exclusion": False, "is_valid": True, "is_ready": True,
             "is_live": True, "key_count": 1, "total_count": 1,
             "keys": ["stable_event_id"], "options": [0],
             "opclasses": ["pg_catalog.text_ops"],
             "collations": ["pg_catalog.default"], "predicate": None},
            {"name": "history_event_claims_history_id_key",
             "table_schema": "public", "table_name": "history_event_claims",
             "access_method": "btree", "nulls_not_distinct": False,
             "is_unique": True, "is_exclusion": False, "is_valid": True,
             "is_ready": True, "is_live": True, "key_count": 1,
             "total_count": 1, "keys": ["history_id"], "options": [0],
             "opclasses": ["pg_catalog.int8_ops"], "collations": [None],
             "predicate": None},
            {"name": "metric_snapshots_pkey", "table_schema": "public",
             "table_name": "metric_snapshots", "access_method": "btree",
             "nulls_not_distinct": False, "is_unique": True,
             "is_exclusion": False, "is_valid": True, "is_ready": True,
             "is_live": True, "key_count": 1, "total_count": 1,
             "keys": ["id"], "options": [0],
             "opclasses": ["pg_catalog.int8_ops"], "collations": [None],
             "predicate": None},
            {"name": "lineage_pkey", "table_schema": "public",
             "table_name": "lineage", "access_method": "btree",
             "nulls_not_distinct": False, "is_unique": True,
             "is_exclusion": False, "is_valid": True, "is_ready": True,
             "is_live": True, "key_count": 1, "total_count": 1,
             "keys": ["id"], "options": [0],
             "opclasses": ["pg_catalog.int8_ops"], "collations": [None],
             "predicate": None},
            {"name": "idx_lineage_output", "table_schema": "public",
             "table_name": "lineage", "access_method": "btree",
             "nulls_not_distinct": False, "is_unique": False,
             "is_exclusion": False, "is_valid": True, "is_ready": True,
             "is_live": True, "key_count": 1, "total_count": 1,
             "keys": ["output"], "options": [0],
             "opclasses": ["pg_catalog.text_ops"],
             "collations": ["pg_catalog.default"], "predicate": None},
        ],
        "checks": [
            {
                "table_name": "history",
                "name": "ck_history_critique_identity", "validated": True,
                "expression": "((op <> 'critique'::text) OR ((payload IS NOT NULL) "
                              "AND (jsonb_typeof(payload) = 'object'::text) "
                              "AND (payload ? 'arg_id'::text) "
                              "AND (jsonb_typeof(payload -> 'arg_id'::text) = 'string'::text) "
                              "AND ((payload ->> 'arg_id'::text) <> ''::text) "
                              "AND (strpos((payload ->> 'arg_id'::text), '/'::text) = 0)))",
            },
            {
                "table_name": "history",
                "name": "ck_history_new_critique_stable_event", "validated": False,
                "expression": "((op <> 'critique'::text) OR "
                              "(event_id IS NULL) OR "
                              "(event_id ~ '^(ob-[A-Za-z0-9._:-]+|he-[0-9a-f]{64})$'::text))",
            },
        ],
        "sequences": [{
            "schemaname": "public", "sequencename": "history_id_seq",
            "data_type": "bigint", "start_value": 1, "min_value": 1,
            "max_value": 9223372036854775807, "increment_by": 1,
            "cycle": False, "cache_size": 1,
            "owned_sequence": "public.history_id_seq",
        }, {
            "schemaname": "public", "sequencename": "lineage_id_seq",
            "data_type": "bigint", "start_value": 1, "min_value": 1,
            "max_value": 9223372036854775807, "increment_by": 1,
            "cycle": False, "cache_size": 1,
            "owned_sequence": "public.lineage_id_seq",
        }, {
            "schemaname": "public", "sequencename": "metric_snapshots_id_seq",
            "data_type": "bigint", "start_value": 1, "min_value": 1,
            "max_value": 9223372036854775807, "increment_by": 1,
            "cycle": False, "cache_size": 1,
            "owned_sequence": "public.metric_snapshots_id_seq",
        }],
        "sequence_state": [
            {"table_name": "history", "sequence_name": "history_id_seq",
             "last_value": 7, "is_called": True, "max_id": 7},
            {"table_name": "lineage", "sequence_name": "lineage_id_seq",
             "last_value": 3, "is_called": True, "max_id": 3},
            {"table_name": "metric_snapshots",
             "sequence_name": "metric_snapshots_id_seq",
             "last_value": 2, "is_called": True, "max_id": 2},
        ],
        "behavioral_objects": {
            "user_triggers": 0,
            "rewrite_rules": 0,
            "policies": 0,
            "rls_tables": 0,
        },
        "internal_triggers": [
            {
                "table_schema": "public", "table_name": "history",
                "function_name": "RI_FKey_noaction_del", "enabled": "O",
                "is_internal": True, "trigger_type": 9,
                "constraint_name": "history_event_claims_history_id_fkey",
            },
            {
                "table_schema": "public", "table_name": "history",
                "function_name": "RI_FKey_noaction_upd", "enabled": "O",
                "is_internal": True, "trigger_type": 17,
                "constraint_name": "history_event_claims_history_id_fkey",
            },
            {
                "table_schema": "public", "table_name": "history_event_claims",
                "function_name": "RI_FKey_check_ins", "enabled": "O",
                "is_internal": True, "trigger_type": 5,
                "constraint_name": "history_event_claims_history_id_fkey",
            },
            {
                "table_schema": "public", "table_name": "history_event_claims",
                "function_name": "RI_FKey_check_upd", "enabled": "O",
                "is_internal": True, "trigger_type": 17,
                "constraint_name": "history_event_claims_history_id_fkey",
            },
        ],
        "blockers": {
            "malformed_critique_rows": 0,
            "duplicate_critique_identities": 0,
            "duplicate_event_ids": 0,
            "unclaimed_stable_critique_rows": 0,
        },
        "critique_rows": [{
            "history_id": 7, "tree": tree, "op": "critique", "node_tag": "n",
            "payload": payload, "event_id": stable_id, "stable_event_id": stable_id,
        }],
        "claims": [{
            "stable_event_id": stable_id, "history_id": 7, "tree": tree,
            "op": "critique", "node_tag": "n", "payload": payload,
            "event_id": stable_id,
        }],
    }


def test_pg_storage_contract_accepts_only_exact_projection():
    report = _diagnose_pg_projection(**_valid_pg_projection())
    assert report["contract_id"] == CONTRACT_ID
    assert report["ok"] is True
    assert report["failures"] == []


@pytest.mark.parametrize(
    ("mutation", "failure"),
    [
        (lambda p: p["history_columns"][6].update(data_type="character varying(8)"),
         "pg.history.columns"),
        (lambda p: p["objects"].update(history_persistence="u"),
         "pg.object.persistence"),
        (lambda p: p["objects"].update(history_has_subclass=True,
                                       inheritance_edges=1),
         "pg.object.inheritance"),
        (lambda p: p["claims_columns"][2].update(default_expr="clock_timestamp()"),
         "pg.history_event_claims.columns"),
        (lambda p: p["history_columns"][4].update(collation="public.nondeterministic"),
         "pg.history.columns"),
        (lambda p: p["aux_columns"][-1].update(data_type="text"),
         "pg.metric_snapshots.columns"),
        (lambda p: p["aux_columns"][2].update(not_null=False),
         "pg.lineage.columns"),
        (lambda p: p["constraints"][2].update(deferrable=True), "pg.constraints"),
        (lambda p: p["constraints"][3].update(delete_action="c"), "pg.constraints"),
        (lambda p: p["constraints"][3].update(referenced_schema="shadow"), "pg.constraints"),
        (lambda p: p["indexes"][3].update(keys=["tree", "payload->>'other'"]),
         "pg.index.history.uq_history_critique_logical_identity"),
        (lambda p: p["indexes"][1].update(keys=["1/(length(op)-length(op))"]),
         "pg.index.history.idx_history_tree_ts"),
        (lambda p: p["indexes"][1].update(options=[0, 0]),
         "pg.index.history.idx_history_tree_ts"),
        (lambda p: p["indexes"][-1].update(keys=["producer"]),
         "pg.index.lineage.idx_lineage_output"),
        (lambda p: p["indexes"].append({**p["indexes"][0], "name": "evil_unique"}),
         "pg.index.allowlist"),
        (lambda p: p["sequences"][0].update(cycle=True),
         "pg.history.id_sequence"),
        (lambda p: p["sequences"][2].update(cycle=True),
         "pg.metric_snapshots.id_sequence"),
        (lambda p: p["sequence_state"][1].update(last_value=1),
         "pg.lineage.id_sequence_head"),
        (lambda p: p["sequence_state"][0].update(is_called=False),
         "pg.history.id_sequence_head"),
        (lambda p: p["sequence_state"][0].update(
            last_value=9223372036854775807, is_called=True,
            max_history_id=None,
        ), "pg.history.id_sequence_head"),
        (lambda p: p["behavioral_objects"].update(user_triggers=1),
         "pg.behavioral_objects.allowlist"),
        (lambda p: p["internal_triggers"][2].update(enabled="D"),
         "pg.internal_triggers"),
        (lambda p: p["checks"][0].update(
            expression="(op <> 'critique' OR payload IS NOT NULL) AND "
                       "jsonb_typeof(payload)='object'"),
         "pg.check.ck_history_critique_identity"),
        (lambda p: p["checks"][1].update(validated=True),
         "pg.check.ck_history_new_critique_stable_event"),
        (lambda p: p["checks"].append({
            "table_name": "history_event_claims", "name": "evil_check",
            "validated": True, "expression": "history_id < 0",
        }), "pg.check.history_event_claims_allowlist"),
        (lambda p: p["checks"].append({
            "table_name": "lineage", "name": "evil_check",
            "validated": True, "expression": "id < 0",
        }), "pg.check.aux_allowlist"),
        (lambda p: p["blockers"].update(duplicate_event_ids=False),
         "pg.blocker.duplicate_event_ids"),
        (lambda p: p["critique_rows"][0].update(event_id="legacy-random"),
         "pg.history.critique_binding"),
        (lambda p: p["claims"][0].update(stable_event_id="he-" + "0" * 64),
         "pg.history_event_claims.binding"),
    ],
)
def test_pg_storage_contract_rejects_false_green_shapes(mutation, failure):
    projection = deepcopy(_valid_pg_projection())
    mutation(projection)
    report = _diagnose_pg_projection(**projection)
    assert report["ok"] is False
    assert failure in report["failures"]


def test_boolean_check_comparison_preserves_and_or_grouping():
    expected = "a OR (b AND c)"
    assert _boolean_ast(expected) == _boolean_ast("((a) OR ((b) AND (c)))")
    assert _boolean_ast(expected) != _boolean_ast("(a OR b) AND c")
    assert _boolean_ast("op='CRITIQUE'") != _boolean_ast("op='critique'")
    assert _boolean_ast("payload ? 'arg_id::text'") != _boolean_ast(
        "payload ? 'arg_id'::text"
    )


def _neo_constraint(**overrides):
    row = {
        "name": "lkt_outbox_id_unique", "type": "UNIQUENESS",
        "entityType": "NODE", "labelsOrTypes": ["OutboxEntry"],
        "properties": ["id"],
    }
    row.update(overrides)
    return row


def _neo_constraints(**outbox_overrides):
    return [
        _neo_constraint(**outbox_overrides),
        {
            "name": "lkt_argument_id_unique",
            "type": "UNIQUENESS",
            "entityType": "NODE",
            "labelsOrTypes": ["LakatosArgument"],
            "properties": ["id"],
        },
        {
            "name": "lkt_runtime_writer_lease_name_unique",
            "type": "UNIQUENESS",
            "entityType": "NODE",
            "labelsOrTypes": ["RuntimeWriterLease"],
            "properties": ["name"],
        },
    ]


def _stable_outbox():
    tree, arg_id = "T", "a1"
    event_id = history_event_id(tree, "critique", f"{tree}/{arg_id}")
    payload = {
        "arg_id": arg_id,
        "attacks": "n",
        "by": "alice",
        "kind": "doubt",
        "body": "same",
    }
    return {
        "element_id": "neo-1", "id": event_id, "tree": tree,
        "op": "critique", "node_tag": "n",
        "payload": json.dumps(payload, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":")),
        "status": "applied", "created_at": TS,
        "reason": "critique_commit_intent", "applied_at": TS,
        "adopted_by": None, "adopted_at": None, "argument_copies": 1,
    }


def _stable_projection(entry):
    return {
        "history_id": 7, "tree": entry["tree"], "op": entry["op"],
        "node_tag": entry["node_tag"], "payload": json.loads(entry["payload"]),
        "event_id": entry["id"], "stable_event_id": entry["id"],
    }


def _causal_test_result_fixture(*, status="pending"):
    summary = {
        "value": 1.0, "baseline": 0.0, "delta": 1.0,
        "verdict": "progressive_unverified", "script": "inline",
        "result_path": "", "source_script_path": "inline",
        "source_result_path": "", "result_sha256": None,
        "measurement_lock_sha": None, "novel": None,
        "script_sha": "", "freshen": False,
        "replay_status": "not_attempted",
        "replay_reason": "unsealed_script", "regenerated_metric": None,
        "lakatos": "unverified", "metric_verdict": "progressive",
        "novel_server_anchored": False, "requires_human": False,
        "script_sha_server_verified": False, "rule": "improved",
        "attested_by": None, "cycle_claim": None,
        "cycle_request_sha256": None, "request_sha256": "b" * 64,
        "verdict_display": (
            "progressive_unverified@L0(client_asserted,"
            "client_asserted_unverified)"
        ),
        "assurance": {"val": 0, "basis": ["client_asserted_unverified"]},
        "qualitative_self_report": False,
        "replay_authoritative": False,
        "eureka_open": {
            "felt": False, "true": False, "hallucinated": False,
            "reasons": [], "bf": 0.0,
        },
        "eureka_closed": {
            "felt": False, "true": False, "hallucinated": False,
            "reasons": [], "bf": 0.0,
        },
    }
    receipt_fields = {
        "tree": "T", "tag": "n", "target_id": None,
        "verdict": "progressive_unverified", "verdict_source": "scripted",
        "metric_name": "m", "metric_value": 1.0,
        "novel_confirmed": None, "lakatos_status": "unverified",
        "judged_at": TS, "judge_script_sha": "", "prev_receipt_sha": None,
        "measurement_grade": "client_asserted", "engine_rule_sha": None,
        "comment_sha": None, "replay_status": "not_attempted",
        "replay_reason": "unsealed_script", "regenerated_metric": None,
        "judge_script_path": "inline", "result_path": "",
        "result_sha256": None, "measurement_lock_sha": None,
        "source_script_path": "inline", "source_result_path": "",
        "history_payload_sha256": verdict_history_payload_sha(summary),
    }
    group = receipt_content_sha(receipt_fields)
    payload = canonical_history_payload({**summary, "receipt_sha": group})
    entry = {
        "element_id": "neo-causal-1",
        "id": f"ob-test-result-{group}",
        "tree": "T",
        "op": "test_result",
        "node_tag": "n",
        "payload": payload,
        "status": status,
        "created_at": TS,
        "reason": "test_result_commit_intent",
        "applied_at": TS if status == "applied" else None,
        "adopted_by": None,
        "adopted_at": None,
        "receipt_sha": group,
        "causal_group": group,
        "causal_index": 0,
        "request_sha256": "b" * 64,
    }
    authority = {
        "group": group, "expected_tree": "T", "expected_tag": "n",
        "trees": 1, "nodes": 1, "bindings": 1, "receipts": 1,
        "current_tree": "T", "current_tag": "n",
        "current_receipt_sha": group,
        "current_verdict": receipt_fields["verdict"],
        "current_verdict_source": receipt_fields["verdict_source"],
        "current_lakatos_status": receipt_fields["lakatos_status"],
        "current_metric_value": receipt_fields["metric_value"],
        "receipt": {"receipt_sha": group, **receipt_fields},
        "question_state": None, "question_closed_by": None,
        "question_closed_events": None, "closure_id": None,
        "closure_closed_by": None, "closure_at": None,
        "closure_tree": None, "closure_question": None,
        "closure_trigger": None, "closure_verdict": None,
        "closure_receipt_sha": None, "closure_bound_count": 0,
        "closure_global_count": 0, "closes_rel_count": 0,
        "closes_rel_receipt_sha": None, "closes_rel_verdict": None,
        "closes_rel_at": None,
    }
    return entry, authority


def test_neo_storage_contract_checks_record_provenance_and_cross_store_binding():
    entry = _stable_outbox()
    report = _diagnose_neo_outbox_projection(
        _neo_constraints(), [{"id": entry["id"], "copies": 1}], [entry],
        [_stable_projection(entry)],
    )
    assert report["ok"] is True

    malformed = {**entry, "status": "aplied", "applied_at": None}
    report = _diagnose_neo_outbox_projection(
        _neo_constraints(), [{"id": entry["id"], "copies": 1}], [malformed],
        [_stable_projection(entry)],
    )
    assert "neo4j.outbox.record" in report["failures"]

    wrong_projection = {**_stable_projection(entry), "node_tag": "other"}
    report = _diagnose_neo_outbox_projection(
        _neo_constraints(), [{"id": entry["id"], "copies": 1}], [entry],
        [wrong_projection],
    )
    assert "cross_store.outbox_projection" in report["failures"]

    pending = {**entry, "status": "pending", "applied_at": None}
    report = _diagnose_neo_outbox_projection(
        _neo_constraints(), [{"id": entry["id"], "copies": 1}], [pending],
        [],
    )
    assert "neo4j.outbox.pending" in report["failures"]


def test_every_causal_outbox_requires_exact_v6_receipt_authority():
    entry, authority = _causal_test_result_fixture()
    identity = [{"id": entry["id"], "copies": 1}]

    missing = _diagnose_neo_outbox_projection(
        _neo_constraints(), identity, [entry], [], causal_receipt_rows=[]
    )
    assert "neo4j.outbox.causal_receipt_v6" in missing["failures"]

    malformed_authority = deepcopy(authority)
    malformed_authority["receipt"]["history_payload_sha256"] = "d" * 64
    malformed = _diagnose_neo_outbox_projection(
        _neo_constraints(), identity, [entry], [],
        causal_receipt_rows=[malformed_authority],
    )
    assert "neo4j.outbox.causal_receipt_v6" in malformed["failures"]

    valid = _diagnose_neo_outbox_projection(
        _neo_constraints(), identity, [entry], [],
        causal_receipt_rows=[authority],
    )
    assert "neo4j.outbox.causal_receipt_v6" not in valid["failures"]
    assert "neo4j.outbox.pending" in valid["failures"]


@pytest.mark.parametrize(
    ("op", "payload", "expected_failure"),
    [
        ("verdict", {"verdict": "CANONICAL"}, "neo4j.outbox.admin_intent"),
        (
            "prediction_register",
            {"metric_name": "m", "baseline_value": 1.0},
            "neo4j.outbox.prediction_intent_v3",
        ),
        (
            "test_result",
            {"receipt_sha": "a" * 64},
            "neo4j.outbox.causal_binding",
        ),
        (
            "question_close",
            {"receipt_sha": "a" * 64},
            "neo4j.outbox.causal_binding",
        ),
        (
            "cycle_result",
            {"verdict_receipt_sha": "a" * 64},
            "neo4j.outbox.causal_binding",
        ),
    ],
)
def test_protected_op_cannot_downgrade_to_generic_applied_outbox(
    op, payload, expected_failure,
):
    event_id = f"ob-legacy-{op.replace('_', '-')}"
    payload_text = canonical_history_payload(payload)
    entry = {
        "id": event_id,
        "tree": "T",
        "op": op,
        "node_tag": "n",
        "payload": payload_text,
        "status": "applied",
        "created_at": TS,
        "reason": "PgOperationalError",
        "applied_at": TS,
        "adopted_by": None,
        "adopted_at": None,
    }
    projection = {
        "history_id": 99,
        "tree": "T",
        "op": op,
        "node_tag": "n",
        "payload": payload,
        "event_id": event_id,
        "stable_event_id": None,
    }

    report = _diagnose_neo_outbox_projection(
        _neo_constraints(),
        [{"id": event_id, "copies": 1}],
        [entry],
        [projection],
    )

    assert expected_failure in report["failures"]
    assert report["ok"] is False


def test_applied_generic_critique_requires_exact_argument_binding():
    payload = {
        "arg_id": "a1",
        "attacks": "n",
        "by": "alice",
        "kind": "doubt",
        "body": "same",
    }
    event_id = "ob-legacy-critique"
    entry = {
        "id": event_id,
        "tree": "T",
        "op": "critique",
        "node_tag": "n",
        "payload": canonical_history_payload(payload),
        "status": "applied",
        "created_at": TS,
        "reason": "PgOperationalError",
        "applied_at": TS,
        "adopted_by": None,
        "adopted_at": None,
        "argument_copies": 0,
    }
    projection = {
        "history_id": 100,
        "tree": "T",
        "op": "critique",
        "node_tag": "n",
        "payload": payload,
        "event_id": event_id,
        "stable_event_id": None,
    }

    report = _diagnose_neo_outbox_projection(
        _neo_constraints(),
        [{"id": event_id, "copies": 1}],
        [entry],
        [projection],
    )

    assert "neo4j.outbox.argument_binding" in report["failures"]
    assert report["ok"] is False


def test_applied_causal_receipt_is_audited_after_newer_current_verdict():
    entry, authority = _causal_test_result_fixture(status="applied")
    identity = [{"id": entry["id"], "copies": 1}]
    projection = {
        "history_id": 8, "tree": entry["tree"], "op": entry["op"],
        "node_tag": entry["node_tag"], "payload": json.loads(entry["payload"]),
        "event_id": entry["id"], "stable_event_id": None,
    }
    authority["current_receipt_sha"] = "f" * 64
    authority["current_verdict"] = "rejected"
    authority["current_lakatos_status"] = "degenerating"
    authority["current_metric_value"] = -1.0

    valid = _diagnose_neo_outbox_projection(
        _neo_constraints(), identity, [entry], [projection],
        causal_receipt_rows=[authority],
    )
    assert valid["ok"] is True

    missing = _diagnose_neo_outbox_projection(
        _neo_constraints(), identity, [entry], [projection],
        causal_receipt_rows=[],
    )
    assert "neo4j.outbox.causal_receipt_v6" in missing["failures"]

    tampered = deepcopy(authority)
    tampered["receipt"]["metric_value"] = 2.0
    bad = _diagnose_neo_outbox_projection(
        _neo_constraints(), identity, [entry], [projection],
        causal_receipt_rows=[tampered],
    )
    assert "neo4j.outbox.causal_receipt_v6" in bad["failures"]


def test_pending_causal_receipt_still_requires_current_effect():
    entry, authority = _causal_test_result_fixture()
    identity = [{"id": entry["id"], "copies": 1}]
    authority["current_receipt_sha"] = "f" * 64

    report = _diagnose_neo_outbox_projection(
        _neo_constraints(), identity, [entry], [],
        causal_receipt_rows=[authority],
    )
    assert "neo4j.outbox.causal_receipt_v6" in report["failures"]


def test_preflight_can_identify_valid_noncanonical_legacy_outbox_for_migration():
    entry = _stable_outbox()
    legacy = {
        **entry,
        "payload": json.dumps(json.loads(entry["payload"]), ensure_ascii=False),
    }
    projection = _stable_projection(legacy)

    strict = _diagnose_neo_outbox_projection(
        _neo_constraints(), [{"id": legacy["id"], "copies": 1}], [legacy],
        [projection],
    )
    relaxed = _diagnose_neo_outbox_projection(
        _neo_constraints(), [{"id": legacy["id"], "copies": 1}], [legacy],
        [projection], require_canonical_payload=False,
    )

    assert "neo4j.outbox.record" in strict["failures"]
    assert relaxed["ok"] is True
    assert relaxed["details"]["noncanonical_outbox_rows"] == 1


def test_projection_local_history_identity_does_not_require_a_neo_outbox():
    projection = {
        "history_id": 9,
        "tree": "T",
        "op": "node_add",
        "node_tag": "n",
        "payload": {"ok": True},
        "event_id": "ph-history-0123456789abcdef",
        "stable_event_id": None,
    }
    report = _diagnose_neo_outbox_projection(
        _neo_constraints(), [], [], [projection]
    )
    assert report["ok"] is True


def test_neo_storage_contract_accepts_exact_legacy_null_row_adoption():
    stable = _stable_outbox()
    legacy = {
        **stable,
        "element_id": "neo-legacy",
        "id": "ob-legacy",
        "status": "adopted",
        "reason": "PgOperationalError",
        "applied_at": None,
        "adopted_by": stable["id"],
        "adopted_at": TS,
        "argument_copies": 1,
    }
    projection = {
        **_stable_projection(stable),
        "event_id": None,
    }
    report = _diagnose_neo_outbox_projection(
        _neo_constraints(), [{"id": legacy["id"], "copies": 1}], [legacy],
        [projection],
    )
    assert report["ok"] is True


def test_applied_generic_legacy_critique_passes_with_exact_argument_binding():
    stable = _stable_outbox()
    legacy = {
        **stable,
        "id": "ob-legacy-exact",
        "status": "applied",
        "reason": "PgOperationalError",
        "applied_at": TS,
        "argument_copies": 1,
    }
    projection = {
        **_stable_projection(legacy),
        "event_id": legacy["id"],
        "stable_event_id": None,
    }

    report = _diagnose_neo_outbox_projection(
        _neo_constraints(),
        [{"id": legacy["id"], "copies": 1}],
        [legacy],
        [projection],
    )

    assert report["ok"] is True


def test_neo_storage_contract_rejects_multiple_legacy_aliases_for_one_stable_id():
    stable = _stable_outbox()
    aliases = []
    identities = [{"id": stable["id"], "copies": 1}]
    for suffix in ("one", "two"):
        alias = {
            **stable,
            "element_id": f"neo-{suffix}",
            "id": f"ob-{suffix}",
            "status": "adopted",
            "reason": "PgOperationalError",
            "applied_at": None,
            "adopted_by": stable["id"],
            "adopted_at": TS,
            "argument_copies": 1,
        }
        aliases.append(alias)
        identities.append({"id": alias["id"], "copies": 1})
    projection = {**_stable_projection(stable), "event_id": None}

    report = _diagnose_neo_outbox_projection(
        _neo_constraints(), identities, [stable, *aliases], [projection]
    )

    assert "cross_store.outbox_projection" in report["failures"]


def test_neo_storage_contract_rejects_adopted_stable_identity():
    stable = _stable_outbox()
    corrupt = {
        **stable,
        "status": "adopted",
        "applied_at": None,
        "adopted_by": stable["id"],
        "adopted_at": TS,
    }

    report = _diagnose_neo_outbox_projection(
        _neo_constraints(), [{"id": corrupt["id"], "copies": 1}], [corrupt],
        [_stable_projection(stable)],
    )

    assert "neo4j.outbox.record" in report["failures"]


def test_neo_storage_contract_requires_claimed_legacy_alias_to_be_adopted():
    stable = _stable_outbox()
    legacy = {
        **stable,
        "id": "ob-old",
        "status": "applied",
        "argument_copies": 1,
    }
    projection = {
        **_stable_projection(stable),
        "event_id": legacy["id"],
    }

    report = _diagnose_neo_outbox_projection(
        _neo_constraints(),
        [
            {"id": stable["id"], "copies": 1},
            {"id": legacy["id"], "copies": 1},
        ],
        [stable, legacy],
        [projection],
    )

    assert "cross_store.outbox_projection" in report["failures"]


def test_neo_storage_contract_rejects_wrong_constraint_and_bad_argument_binding():
    entry = {**_stable_outbox(), "argument_copies": 0}
    report = _diagnose_neo_outbox_projection(
        _neo_constraints(type="NODE_PROPERTY_EXISTENCE"),
        [{"id": entry["id"], "copies": 1}], [entry],
    )
    assert "neo4j.constraint.lkt_outbox_id_unique.shape" in report["failures"]
    assert "neo4j.outbox.argument_binding" in report["failures"]


def test_neo_storage_contract_rejects_duplicate_or_missing_global_argument_ids():
    report = _diagnose_neo_outbox_projection(
        _neo_constraints(), [], [], [],
        argument_identity_rows=[
            {"id": "T/a", "copies": 2},
            {"id": None, "copies": 1},
        ],
    )

    assert "neo4j.argument.identity" in report["failures"]


def test_expected_constraint_name_on_wrong_label_is_shape_conflict():
    constraints = _neo_constraints()
    constraints[0] = {**constraints[0], "labelsOrTypes": ["WrongLabel"]}

    report = _diagnose_neo_outbox_projection(constraints, [], [])

    assert "neo4j.constraint.lkt_outbox_id_unique.shape" in report["failures"]


def test_neo_storage_contract_requires_argument_guard_and_rejects_extra_constraints():
    report = _diagnose_neo_outbox_projection([_neo_constraint()], [], [])
    assert "neo4j.constraint.lkt_argument_id_unique.missing" in report["failures"]

    constraints = _neo_constraints() + [{
        "name": "evil_outbox_tree_unique",
        "type": "UNIQUENESS",
        "entityType": "NODE",
        "labelsOrTypes": ["OutboxEntry"],
        "properties": ["tree"],
    }]
    report = _diagnose_neo_outbox_projection(constraints, [], [])
    assert "neo4j.constraint.allowlist" in report["failures"]


def test_neo_storage_contract_rejects_duplicate_or_wrong_writer_lease_identity():
    report = _diagnose_neo_outbox_projection(
        _neo_constraints(), [], [], [],
        writer_lease_identity_rows=[
            {
                "name": "critique-history-writer-v1",
                "generation": 3,
                "owner_token": "a",
                "copies": 2,
            }
        ],
    )

    assert "neo4j.writer_lease.identity" in report["failures"]


def test_neo_storage_contract_accepts_exact_single_writer_lease_identity():
    report = _diagnose_neo_outbox_projection(
        _neo_constraints(), [], [], [],
        writer_lease_identity_rows=[
            {
                "name": "critique-history-writer-v1",
                "generation": 3,
                "owner_token": "owner",
                "copies": 1,
            }
        ],
    )

    assert "neo4j.writer_lease.identity" not in report["failures"]

@pytest.mark.parametrize(
    "payload_text",
    [
        '{"body":"same", "arg_id":"a1", "attacks":"n", '
        '"by":"alice", "kind":"doubt"}',
        '{"arg_id":"a1","attacks":"n","body":"same",'
        '"by":"alice","extra":true,"kind":"doubt"}',
    ],
)
def test_neo_storage_contract_rejects_noncanonical_or_extended_critique_payload(
    payload_text,
):
    entry = {**_stable_outbox(), "payload": payload_text}
    report = _diagnose_neo_outbox_projection(
        _neo_constraints(), [{"id": entry["id"], "copies": 1}], [entry],
        [_stable_projection(entry)],
    )
    assert "neo4j.outbox.record" in report["failures"]


def test_require_storage_contract_fails_closed(monkeypatch):
    import server.storage_contract as storage_contract

    monkeypatch.setattr(
        storage_contract,
        "inspect_storage_contract",
        lambda _container: {
            "ok": False,
            "postgresql": {"failures": ["pg.bad"]},
            "neo4j": {"failures": ["neo.bad"]},
        },
    )
    with pytest.raises(StorageContractError, match="pg.bad, neo.bad"):
        require_storage_contract(object())
