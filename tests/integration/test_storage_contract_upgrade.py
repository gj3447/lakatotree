"""Disposable-database rehearsal of the dated storage migrations."""

from __future__ import annotations

import importlib.resources
import hashlib
import http.server
import json
import sys
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import psycopg2
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from psycopg2 import errors, sql
from neo4j.exceptions import ConstraintError, Neo4jError
import pytest

from lakatos import temporal as temporal_mod
from lakatos.io.reconcile import canonical_history_payload, history_event_id
from lakatos.verdicts import (
    RECEIPT_FIELDS,
    RECEIPT_FIELDS_V5,
    prediction_content_sha,
    prediction_history_payload_sha,
    receipt_content_sha,
)
from server.contexts.tree.schemas import PredictionIn
from server.storage_contract import inspect_neo_outbox_contract, inspect_pg_history_contract
from server.settings import ServerSettings
from server import storage_predeploy


pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


def _pg_migration() -> str:
    return importlib.resources.files("server.storage_migrations").joinpath(
        "critique_history_v1.sql"
    ).read_text(encoding="utf-8")


def _neo_migration_statements() -> list[str]:
    statements = []
    resources = importlib.resources.files("server.storage_migrations")
    for name in storage_predeploy.NEO_RESOURCES:
        statements.extend(storage_predeploy._migration_cypher(
            resources.joinpath(name).read_bytes()
        ))
    return statements


def _run_neo_migration(kg) -> None:
    for statement in _neo_migration_statements():
        kg(statement)


def _create_database(pg_kw: dict, name: str) -> dict:
    admin_kw = {**pg_kw, "dbname": pg_kw["dbname"]}
    connection = psycopg2.connect(**admin_kw)
    try:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    finally:
        connection.close()
    return {**pg_kw, "dbname": name}


def _drop_database(pg_kw: dict, name: str) -> None:
    connection = psycopg2.connect(**pg_kw)
    try:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname=%s AND pid<>pg_backend_pid()",
                (name,),
            )
            cursor.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
    finally:
        connection.close()


def test_postgresql_legacy_upgrade_is_idempotent_and_fail_closed(pg_kw):
    database = f"lkt_migration_{uuid4().hex}"
    isolated_kw = _create_database(pg_kw, database)
    migration = _pg_migration()
    legacy_schema = """
    CREATE TABLE history(
      id BIGSERIAL PRIMARY KEY,
      ts TIMESTAMPTZ NOT NULL DEFAULT now(),
      tree TEXT NOT NULL,
      op TEXT NOT NULL,
      node_tag TEXT,
      payload JSONB,
      event_id TEXT
    );
    CREATE UNIQUE INDEX uq_history_event_id
      ON history(event_id) WHERE event_id IS NOT NULL;
    INSERT INTO history(id,tree,op,node_tag,payload,event_id)
      VALUES (41,'T','critique','n','{"arg_id":"a1","body":"legacy"}',NULL);
    """
    try:
        connection = psycopg2.connect(**isolated_kw)
        try:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute(legacy_schema)
                cursor.execute(migration)
                cursor.execute(migration)
                cursor.execute(
                    "SELECT id,tree,op,node_tag,payload,event_id FROM history ORDER BY id"
                )
                original = cursor.fetchall()
            report = inspect_pg_history_contract(connection)
            assert report["ok"] is True
            assert len(original) == 1
            with connection.cursor() as cursor:
                cursor.execute("SELECT last_value,is_called FROM public.history_id_seq")
                assert cursor.fetchone() == (41, True)

            with pytest.raises(errors.UniqueViolation):
                with connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO history(tree,op,node_tag,payload,event_id) "
                        "VALUES ('T','critique','other','{\"arg_id\":\"a1\"}',%s)",
                        ("he-" + "0" * 64,),
                    )
            with pytest.raises(errors.CheckViolation):
                with connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO history(tree,op,node_tag,payload,event_id) "
                        "VALUES ('T','critique','other','{}',%s)",
                        ("he-" + "1" * 64,),
                    )
            for malformed in ('{"arg_id":123}', '{"arg_id":true}',
                              '{"arg_id":null}', '{"arg_id":{}}'):
                with pytest.raises(errors.CheckViolation):
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "INSERT INTO public.history(tree,op,node_tag,payload,event_id) "
                            "VALUES ('T','critique','other',%s::jsonb,%s)",
                            (malformed, "he-" + "2" * 64),
                        )
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO public.history(tree,op,node_tag,payload,event_id) "
                    "VALUES ('T','critique','old-writer','{\"arg_id\":\"old\"}',NULL) "
                    "RETURNING id"
                )
                old_writer_id = cursor.fetchone()[0]
                old_writer_stable = history_event_id(
                    "T", "critique", "T/old"
                )
                cursor.execute(
                    "INSERT INTO history_event_claims(stable_event_id,history_id) "
                    "VALUES (%s,%s)",
                    (old_writer_stable, old_writer_id),
                )
                cursor.execute(
                    "SELECT stable_event_id FROM history_event_claims "
                    "WHERE history_id=%s",
                    (old_writer_id,),
                )
                assert cursor.fetchone() == (old_writer_stable,)
                second_stable = history_event_id("T", "critique", "T/a2")
                cursor.execute(
                    "INSERT INTO history(tree,op,node_tag,payload,event_id) "
                    "VALUES ('T','critique','other','{\"arg_id\":\"a2\"}',%s) RETURNING id",
                    (second_stable,),
                )
                second_id = cursor.fetchone()[0]
                first_id = original[0][0]
                first_stable = history_event_id("T", "critique", "T/a1")
                cursor.execute(
                    "INSERT INTO history_event_claims(stable_event_id,history_id) "
                    "VALUES (%s,%s)",
                    (first_stable, first_id),
                )
            with pytest.raises(errors.UniqueViolation):
                with connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO history_event_claims(stable_event_id,history_id) "
                        "VALUES (%s,%s)",
                        (first_stable, second_id),
                    )
            with pytest.raises(errors.UniqueViolation):
                with connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO history_event_claims(stable_event_id,history_id) "
                        "VALUES (%s,%s)",
                        (second_stable, first_id),
                    )
            with pytest.raises(errors.ForeignKeyViolation):
                with connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO history_event_claims(stable_event_id,history_id) "
                        "VALUES (%s,%s)",
                        (second_stable, 2**62),
                    )
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM history_event_claims"
                )
                cursor.execute(
                    "DELETE FROM history WHERE id IN (%s,%s)",
                    (second_id, old_writer_id),
                )
                cursor.execute(
                    "SELECT id,tree,op,node_tag,payload,event_id FROM history ORDER BY id"
                )
                assert cursor.fetchall() == original
        finally:
            connection.close()
    finally:
        _drop_database(pg_kw, database)


def test_neo4j_outbox_migration_exact_readback_and_duplicate_guard(neo4j_driver):
    def kg(query, **params):
        with neo4j_driver.session() as session:
            return session.run(query, **params).data()

    _run_neo_migration(kg)
    _run_neo_migration(kg)
    report = inspect_neo_outbox_contract(kg)
    assert report["ok"] is True

    identity = f"ob-{uuid4().hex}"
    try:
        kg("CREATE (:OutboxEntry {id:$id})", id=identity)
        with pytest.raises(ConstraintError):
            kg("CREATE (:OutboxEntry {id:$id})", id=identity)
        rows = kg(
            "MATCH (o:OutboxEntry {id:$id}) RETURN count(o) AS copies",
            id=identity,
        )
        assert rows == [{"copies": 1}]
    finally:
        kg("MATCH (o:OutboxEntry {id:$id}) DETACH DELETE o", id=identity)

    duplicate = f"ob-{uuid4().hex}"
    kg("DROP CONSTRAINT lkt_outbox_id_unique IF EXISTS")
    try:
        kg("CREATE (:OutboxEntry {id:$id}), (:OutboxEntry {id:$id})", id=duplicate)
        with pytest.raises(Neo4jError) as exc_info:
            _run_neo_migration(kg)
        assert exc_info.value.code == "Neo.DatabaseError.Schema.ConstraintCreationFailed"
        assert kg(
            "MATCH (o:OutboxEntry {id:$id}) RETURN count(o) AS copies",
            id=duplicate,
        ) == [{"copies": 2}]
    finally:
        kg("MATCH (o:OutboxEntry {id:$id}) DETACH DELETE o", id=duplicate)
        _run_neo_migration(kg)

    kg("DROP CONSTRAINT lkt_argument_id_unique IF EXISTS")
    try:
        report = inspect_neo_outbox_contract(kg)
        assert "neo4j.constraint.lkt_argument_id_unique.missing" in report["failures"]
    finally:
        _run_neo_migration(kg)

    kg(
        "CREATE CONSTRAINT evil_outbox_tree_unique IF NOT EXISTS "
        "FOR (n:OutboxEntry) REQUIRE n.tree IS UNIQUE"
    )
    try:
        report = inspect_neo_outbox_contract(kg)
        assert "neo4j.constraint.allowlist" in report["failures"]
    finally:
        kg("DROP CONSTRAINT evil_outbox_tree_unique IF EXISTS")

    kg("DROP CONSTRAINT lkt_argument_id_unique IF EXISTS")
    kg(
        "CREATE CONSTRAINT lkt_argument_id_unique "
        "FOR (n:LakatosArgument) REQUIRE n.tree_name IS UNIQUE"
    )
    try:
        report = inspect_neo_outbox_contract(kg)
        assert "neo4j.constraint.lkt_argument_id_unique.shape" in report["failures"]
    finally:
        kg("DROP CONSTRAINT lkt_argument_id_unique IF EXISTS")
        _run_neo_migration(kg)


def test_postgresql_fresh_install_bootstraps_exact_contract(pg_kw):
    database = f"lkt_fresh_{uuid4().hex}"
    isolated_kw = _create_database(pg_kw, database)
    try:
        connection = psycopg2.connect(**isolated_kw)
        try:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute(_pg_migration())
                cursor.execute(_pg_migration())
                cursor.execute(
                    "SELECT to_regclass('public.metric_snapshots'), "
                    "to_regclass('public.lineage')"
                )
                assert cursor.fetchone() == (
                    "metric_snapshots", "lineage"
                )
            assert inspect_pg_history_contract(connection)["ok"] is True
        finally:
            connection.close()
    finally:
        _drop_database(pg_kw, database)


def test_postgresql_upgrade_backfills_existing_stable_event_claim(pg_kw):
    database = f"lkt_stable_backfill_{uuid4().hex}"
    isolated_kw = _create_database(pg_kw, database)
    stable_id = history_event_id("T", "critique", "T/a1")
    try:
        connection = psycopg2.connect(**isolated_kw)
        try:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE public.history(
                      id BIGSERIAL PRIMARY KEY,
                      ts TIMESTAMPTZ NOT NULL DEFAULT now(),
                      tree TEXT NOT NULL,
                      op TEXT NOT NULL,
                      node_tag TEXT,
                      payload JSONB,
                      event_id TEXT
                    );
                    CREATE UNIQUE INDEX uq_history_event_id
                      ON public.history(event_id) WHERE event_id IS NOT NULL;
                    INSERT INTO public.history(tree,op,node_tag,payload,event_id)
                      VALUES ('T','critique','n','{"arg_id":"a1"}',%s);
                """, (stable_id,))
                cursor.execute(_pg_migration())
                cursor.execute(
                    "SELECT c.stable_event_id, h.event_id "
                    "FROM public.history_event_claims c "
                    "JOIN public.history h ON h.id=c.history_id"
                )
                assert cursor.fetchall() == [(stable_id, stable_id)]
            assert inspect_pg_history_contract(connection)["ok"] is True
        finally:
            connection.close()
    finally:
        _drop_database(pg_kw, database)


def test_postgresql_wrong_base_shape_fails_without_false_green(pg_kw):
    database = f"lkt_wrong_shape_{uuid4().hex}"
    isolated_kw = _create_database(pg_kw, database)
    try:
        connection = psycopg2.connect(**isolated_kw)
        try:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE public.history(
                      id BIGSERIAL PRIMARY KEY,
                      ts TIMESTAMPTZ NOT NULL DEFAULT now(),
                      tree TEXT NOT NULL,
                      op TEXT NOT NULL,
                      node_tag TEXT,
                      payload JSONB,
                      event_id VARCHAR(8)
                    )
                """)
                with pytest.raises(psycopg2.Error, match="column shape mismatch"):
                    cursor.execute(_pg_migration())
                cursor.execute("ROLLBACK")
                cursor.execute(
                    "SELECT format_type(a.atttypid,a.atttypmod) "
                    "FROM pg_attribute a WHERE "
                    "a.attrelid='public.history'::regclass AND a.attname='event_id'"
                )
                assert cursor.fetchone() == ("character varying(8)",)
        finally:
            connection.close()
    finally:
        _drop_database(pg_kw, database)


@pytest.mark.parametrize(
    ("table_name", "schema", "column_name"),
    [
        (
            "metric_snapshots",
            """
            CREATE TABLE public.metric_snapshots(
              id BIGSERIAL PRIMARY KEY,
              ts TIMESTAMPTZ NOT NULL DEFAULT now(),
              tree INTEGER NOT NULL,
              metrics JSONB
            )
            """,
            "tree",
        ),
        (
            "lineage",
            """
            CREATE TABLE public.lineage(
              id BIGSERIAL PRIMARY KEY,
              ts TIMESTAMPTZ NOT NULL DEFAULT now(),
              output INTEGER NOT NULL,
              output_sha TEXT,
              producer TEXT,
              producer_sha TEXT,
              inputs JSONB,
              params JSONB,
              kind TEXT,
              env TEXT
            )
            """,
            "output",
        ),
    ],
)
def test_postgresql_wrong_auxiliary_shape_rolls_back_atomically(
    pg_kw, table_name, schema, column_name
):
    database = f"lkt_wrong_aux_{uuid4().hex}"
    isolated_kw = _create_database(pg_kw, database)
    try:
        connection = psycopg2.connect(**isolated_kw)
        try:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute(schema)
                with pytest.raises(psycopg2.Error, match="column shape mismatch"):
                    cursor.execute(_pg_migration())
                cursor.execute("ROLLBACK")
                cursor.execute(
                    "SELECT format_type(a.atttypid,a.atttypmod) "
                    "FROM pg_attribute a WHERE "
                    "a.attrelid=%s::regclass AND a.attname=%s",
                    (f"public.{table_name}", column_name),
                )
                assert cursor.fetchone() == ("integer",)
        finally:
            connection.close()
    finally:
        _drop_database(pg_kw, database)


def test_postgresql_wrong_lineage_index_fails_and_preserves_existing_rows(pg_kw):
    database = f"lkt_wrong_lineage_index_{uuid4().hex}"
    isolated_kw = _create_database(pg_kw, database)
    try:
        connection = psycopg2.connect(**isolated_kw)
        try:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute((ROOT / "server" / "schema.sql").read_text())
                cursor.execute(
                    "INSERT INTO public.lineage(output,producer) "
                    "VALUES ('artifact://kept','producer://kept')"
                )
                cursor.execute("DROP INDEX public.idx_lineage_output")
                cursor.execute(
                    "CREATE INDEX idx_lineage_output ON public.lineage(producer)"
                )
                with pytest.raises(
                    psycopg2.Error, match="lineage output index exact readback failed"
                ):
                    cursor.execute(_pg_migration())
                cursor.execute("ROLLBACK")
                cursor.execute(
                    "SELECT output,producer FROM public.lineage"
                )
                assert cursor.fetchall() == [
                    ("artifact://kept", "producer://kept")
                ]
        finally:
            connection.close()
    finally:
        _drop_database(pg_kw, database)


def test_postgresql_auxiliary_sequence_heads_are_repaired_without_row_rewrite(
    pg_kw,
):
    database = f"lkt_aux_sequence_{uuid4().hex}"
    isolated_kw = _create_database(pg_kw, database)
    try:
        connection = psycopg2.connect(**isolated_kw)
        try:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute((ROOT / "server" / "schema.sql").read_text())
                cursor.execute(
                    "INSERT INTO public.metric_snapshots(id,tree,metrics) "
                    "VALUES (41,'T','{\"kept\":true}')"
                )
                cursor.execute(
                    "INSERT INTO public.lineage(id,output,producer) "
                    "VALUES (37,'artifact://kept','producer://kept')"
                )
                cursor.execute(_pg_migration())
                cursor.execute(
                    "SELECT (SELECT last_value FROM metric_snapshots_id_seq), "
                    "       (SELECT last_value FROM lineage_id_seq), "
                    "       (SELECT count(*) FROM metric_snapshots), "
                    "       (SELECT count(*) FROM lineage)"
                )
                assert cursor.fetchone() == (41, 37, 1, 1)
            assert inspect_pg_history_contract(connection)["ok"] is True
        finally:
            connection.close()
    finally:
        _drop_database(pg_kw, database)


def test_postgresql_wrong_same_name_nonunique_index_fails_closed(pg_kw):
    database = f"lkt_wrong_index_{uuid4().hex}"
    isolated_kw = _create_database(pg_kw, database)
    try:
        connection = psycopg2.connect(**isolated_kw)
        try:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute((ROOT / "server" / "schema.sql").read_text())
                cursor.execute("DROP INDEX public.idx_history_tree_ts")
                cursor.execute(
                    "CREATE INDEX idx_history_tree_ts ON public.history "
                    "((1 / (length(op) - length(op))))"
                )
                with pytest.raises(
                    psycopg2.Error, match="history index exact readback failed"
                ):
                    cursor.execute(_pg_migration())
        finally:
            connection.close()
    finally:
        _drop_database(pg_kw, database)


def test_postgresql_expected_index_name_in_other_schema_does_not_collide(pg_kw):
    database = f"lkt_index_namespace_{uuid4().hex}"
    isolated_kw = _create_database(pg_kw, database)
    try:
        connection = psycopg2.connect(**isolated_kw)
        try:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute((ROOT / "server" / "schema.sql").read_text())
                cursor.execute(
                    "CREATE SCHEMA shadow; CREATE TABLE shadow.x(v text); "
                    "CREATE INDEX expected_uq_history_event_id ON shadow.x(v)"
                )
                cursor.execute(_pg_migration())
            assert inspect_pg_history_contract(connection)["ok"] is True
        finally:
            connection.close()
    finally:
        _drop_database(pg_kw, database)


def test_postgresql_exhausted_sequence_fails_audit_and_migration(pg_kw):
    database = f"lkt_sequence_exhausted_{uuid4().hex}"
    isolated_kw = _create_database(pg_kw, database)
    try:
        connection = psycopg2.connect(**isolated_kw)
        try:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute((ROOT / "server" / "schema.sql").read_text())
                cursor.execute(
                    "SELECT setval('public.history_id_seq'::regclass, %s, true)",
                    (9223372036854775807,),
                )
            report = inspect_pg_history_contract(connection)
            assert "pg.history.id_sequence_head" in report["failures"]
            with pytest.raises(psycopg2.Error, match="id sequence is exhausted"):
                with connection.cursor() as cursor:
                    cursor.execute(_pg_migration())
        finally:
            connection.close()
    finally:
        _drop_database(pg_kw, database)


def test_postgresql_user_trigger_fails_audit_and_migration(pg_kw):
    database = f"lkt_trigger_blocker_{uuid4().hex}"
    isolated_kw = _create_database(pg_kw, database)
    try:
        connection = psycopg2.connect(**isolated_kw)
        try:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute((ROOT / "server" / "schema.sql").read_text())
                cursor.execute("""
                    CREATE FUNCTION public.reject_history_insert()
                    RETURNS trigger LANGUAGE plpgsql AS $$
                    BEGIN
                      RAISE EXCEPTION 'blocked';
                    END
                    $$;
                    CREATE TRIGGER reject_history_insert
                    BEFORE INSERT ON public.history
                    FOR EACH ROW EXECUTE FUNCTION public.reject_history_insert();
                """)
            report = inspect_pg_history_contract(connection)
            assert "pg.behavioral_objects.allowlist" in report["failures"]
            with pytest.raises(
                psycopg2.Error, match="unexpected behavioral object"
            ):
                with connection.cursor() as cursor:
                    cursor.execute(_pg_migration())
        finally:
            connection.close()
    finally:
        _drop_database(pg_kw, database)


def test_postgresql_unlogged_critique_storage_fails_audit_and_migration(pg_kw):
    database = f"lkt_unlogged_{uuid4().hex}"
    isolated_kw = _create_database(pg_kw, database)
    try:
        connection = psycopg2.connect(**isolated_kw)
        try:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute("""
                    CREATE UNLOGGED TABLE public.history(
                      id BIGSERIAL PRIMARY KEY,
                      ts TIMESTAMPTZ NOT NULL DEFAULT now(),
                      tree TEXT NOT NULL,
                      op TEXT NOT NULL,
                      node_tag TEXT,
                      payload JSONB,
                      event_id TEXT
                    );
                    CREATE UNLOGGED TABLE public.history_event_claims(
                      stable_event_id TEXT PRIMARY KEY,
                      history_id BIGINT NOT NULL UNIQUE REFERENCES public.history(id),
                      claimed_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    );
                """)
            report = inspect_pg_history_contract(connection)
            assert "pg.object.persistence" in report["failures"]
            with pytest.raises(
                psycopg2.Error, match="must be permanent ordinary storage"
            ):
                with connection.cursor() as cursor:
                    cursor.execute(_pg_migration())
        finally:
            connection.close()
    finally:
        _drop_database(pg_kw, database)


def test_postgresql_disabled_fk_triggers_fail_audit_and_migration(pg_kw):
    database = f"lkt_disabled_fk_{uuid4().hex}"
    isolated_kw = _create_database(pg_kw, database)
    try:
        connection = psycopg2.connect(**isolated_kw)
        try:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute(_pg_migration())
                cursor.execute(
                    "ALTER TABLE public.history_event_claims DISABLE TRIGGER ALL"
                )
            report = inspect_pg_history_contract(connection)
            assert "pg.internal_triggers" in report["failures"]
            with pytest.raises(
                psycopg2.Error, match="internal trigger shape mismatch"
            ):
                with connection.cursor() as cursor:
                    cursor.execute(_pg_migration())
        finally:
            connection.close()
    finally:
        _drop_database(pg_kw, database)


def test_postgresql_inherited_history_path_fails_audit_and_migration(pg_kw):
    database = f"lkt_inheritance_{uuid4().hex}"
    isolated_kw = _create_database(pg_kw, database)
    try:
        connection = psycopg2.connect(**isolated_kw)
        try:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute(_pg_migration())
                cursor.execute(
                    "CREATE TABLE public.history_shadow(extra text) "
                    "INHERITS (public.history)"
                )
            report = inspect_pg_history_contract(connection)
            assert "pg.object.inheritance" in report["failures"]
            with pytest.raises(
                psycopg2.Error, match="must not participate in inheritance"
            ):
                with connection.cursor() as cursor:
                    cursor.execute(_pg_migration())
        finally:
            connection.close()
    finally:
        _drop_database(pg_kw, database)


def test_neo4j_argument_binding_query_rejects_creation_claim_leak(neo4j_driver):
    tree = f"LKT_BINDING_{uuid4().hex}"
    arg_id = "a1"
    stable_id = history_event_id(tree, "critique", f"{tree}/{arg_id}")
    payload_doc = {
        "arg_id": arg_id,
        "attacks": "n",
        "by": "alice",
        "kind": "doubt",
        "body": "same",
    }
    payload = json.dumps(
        payload_doc, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )

    def kg(query, **params):
        with neo4j_driver.session() as session:
            return session.run(query, **params).data()

    _run_neo_migration(kg)
    try:
        kg(
            "CREATE (t:LakatosTree {name:$tree})-[:HAS_NODE]->"
            "(e:LakatosNode {name:$node, tag:'n'})-[:HAS_ARGUMENT]->"
            "(a:Argument:LakatosArgument {id:$arg_full, tree_name:$tree, "
            "local_id:$arg_id, attacks:'n', by:'alice', kind:'doubt', "
            "body:'same', at:$ts}) "
            "CREATE (:OutboxEntry {id:$event_id, tree:$tree, op:'critique', "
            "node_tag:'n', payload:$payload, status:'applied', "
            "created_at:$ts, applied_at:$ts, reason:'critique_commit_intent'})",
            tree=tree,
            node=f"{tree}/n",
            arg_full=f"{tree}/{arg_id}",
            arg_id=arg_id,
            event_id=stable_id,
            payload=payload,
            ts="2026-08-02T00:00:00+00:00",
        )
        assert inspect_neo_outbox_contract(kg)["ok"] is True
        kg(
            "MATCH (a:Argument {id:$id}) SET a._argument_create_claim='leaked'",
            id=f"{tree}/{arg_id}",
        )
        report = inspect_neo_outbox_contract(kg)
        assert "neo4j.outbox.argument_binding" in report["failures"]
    finally:
        kg("MATCH (o:OutboxEntry {tree:$tree}) DETACH DELETE o", tree=tree)
        kg(
            "MATCH (a:Argument) WHERE a.id STARTS WITH $prefix DETACH DELETE a",
            prefix=f"{tree}/",
        )
        kg("MATCH (t:LakatosTree {name:$tree}) DETACH DELETE t", tree=tree)


def test_pending_v5_causal_receipt_is_not_predeploy_recoverable(neo4j_driver):
    tree = f"LKT_PENDING_V5_{uuid4().hex}"
    tag = "n"
    judged_at = "2026-08-02T00:00:00+00:00"
    receipt_fields = {key: None for key in RECEIPT_FIELDS_V5}
    receipt_fields.update({
        "tree": tree,
        "tag": tag,
        "target_id": f"{tree}/question",
        "verdict": "proof",
        "verdict_source": "scripted",
        "metric_name": "score",
        "metric_value": 1.0,
        "novel_confirmed": False,
        "lakatos_status": "progressive",
        "judged_at": judged_at,
        "judge_script_sha": "1" * 64,
        "prev_receipt_sha": "2" * 64,
        "measurement_grade": "server_regenerated",
        "engine_rule_sha": "3" * 64,
        "replay_status": "verified",
        "replay_reason": None,
        "regenerated_metric": 1.0,
        "judge_script_path": "/srv/judge.py",
        "result_path": "/srv/result.json",
        "result_sha256": "4" * 64,
        "measurement_lock_sha": "5" * 64,
        "source_script_path": "/source/judge.py",
        "source_result_path": "/source/result.json",
    })
    receipt_sha = receipt_content_sha(
        receipt_fields, fieldset=RECEIPT_FIELDS_V5
    )
    event_id = f"ob-test-result-{receipt_sha}"
    payload = json.dumps(
        {"receipt_sha": receipt_sha}, sort_keys=True, separators=(",", ":")
    )

    def kg(query, **params):
        with neo4j_driver.session() as session:
            return session.run(query, **params).data()

    _run_neo_migration(kg)
    try:
        kg(
            "CREATE (t:LakatosTree {name:$tree})-[:HAS_NODE]->"
            "(e:LakatosNode {name:$node, tag:$tag, "
            "current_receipt_sha:$receipt_sha})-[:HAS_RECEIPT]->"
            "(rec:VerdictReceipt) SET rec=$receipt "
            "CREATE (:OutboxEntry {id:$event_id, tree:$tree, "
            "op:'test_result', node_tag:$tag, payload:$payload, "
            "status:'pending', created_at:$judged_at, "
            "reason:'test_result_commit_intent', receipt_sha:$receipt_sha, "
            "causal_group:$receipt_sha, causal_index:0, "
            "request_sha256:$request_sha})",
            tree=tree,
            node=f"{tree}/{tag}",
            tag=tag,
            receipt_sha=receipt_sha,
            receipt={"receipt_sha": receipt_sha, **receipt_fields},
            event_id=event_id,
            payload=payload,
            judged_at=judged_at,
            request_sha="6" * 64,
        )
        report = inspect_neo_outbox_contract(kg)
        assert "neo4j.outbox.pending" in report["failures"]
        assert (
            "neo4j.outbox.causal_receipt_v6" in report["failures"]
        )
        assert "neo4j.receipt_chain" in report["failures"]
    finally:
        kg("MATCH (o:OutboxEntry {tree:$tree}) DETACH DELETE o", tree=tree)
        kg("MATCH (t:LakatosTree {name:$tree}) DETACH DELETE t", tree=tree)
        kg(
            "MATCH (r:VerdictReceipt {receipt_sha:$sha}) DETACH DELETE r",
            sha=receipt_sha,
        )


def test_real_neo_receipt_chain_rejects_dangling_parent(neo4j_driver):
    tree = f"LKT_DANGLING_CHAIN_{uuid4().hex}"
    fields = {key: None for key in RECEIPT_FIELDS}
    fields.update(
        tree=tree,
        tag="n",
        verdict="progressive",
        verdict_source="scripted",
        judged_at="2026-08-02T00:00:00+00:00",
        prev_receipt_sha="f" * 64,
    )
    receipt_sha = receipt_content_sha(fields)

    def kg(query, **params):
        with neo4j_driver.session() as session:
            return session.run(query, **params).data()

    _run_neo_migration(kg)
    try:
        kg(
            "CREATE (t:LakatosTree {name:$tree})-[:HAS_NODE]->"
            "(e:LakatosNode {name:$node, tag:'n', "
            "current_receipt_sha:$sha})-[:HAS_RECEIPT]->"
            "(r:VerdictReceipt) SET r=$receipt",
            tree=tree,
            node=f"{tree}/n",
            sha=receipt_sha,
            receipt={"receipt_sha": receipt_sha, **fields},
        )
        report = inspect_neo_outbox_contract(kg)
        assert "neo4j.receipt_chain" in report["failures"]
    finally:
        kg("MATCH (t:LakatosTree {name:$tree}) DETACH DELETE t", tree=tree)
        kg(
            "MATCH (r:VerdictReceipt {receipt_sha:$sha}) DETACH DELETE r",
            sha=receipt_sha,
        )


def test_real_neo_prediction_intent_detects_history_tamper(neo4j_driver):
    tree = f"LKT_PREDICTION_V3_{uuid4().hex}"
    tag = "n"
    registered_at = "2026-08-02T00:00:00+00:00"
    payload = PredictionIn(
        metric_name="latency",
        direction="lower",
        baseline_value=10.0,
        noise_band=0.5,
    ).model_dump()
    bundle = {
        "schema": "lakatotree-prediction-anchor-bundle/v1",
        "spec_digest": temporal_mod.spec_digest({
            key: value
            for key, value in payload.items()
            if key not in ("write_cert", "temporal_anchor", "temporal_anchors")
        }),
        "witness_dids": [],
        "witness_threshold": 1,
        "anchors": [],
    }
    bundle_json = canonical_history_payload(bundle)
    receipt_fields = {
        "receipt_kind": "prediction",
        "tree": tree,
        "tag": tag,
        "baseline_lineage": "no_prior",
        "registered_at": registered_at,
        "prev_receipt_sha": None,
        "anchor_bundle_sha256": hashlib.sha256(
            bundle_json.encode("utf-8")
        ).hexdigest(),
        "anchor_bundle_json": bundle_json,
        "history_payload_sha256": prediction_history_payload_sha(payload),
        **payload,
    }
    receipt_sha = prediction_content_sha(receipt_fields)
    event_id = f"ob-prediction-register-{receipt_sha}"

    def kg(query, **params):
        with neo4j_driver.session() as session:
            return session.run(query, **params).data()

    _run_neo_migration(kg)
    try:
        kg(
            "CREATE (t:LakatosTree {name:$tree})-[:HAS_NODE]->"
            "(e:LakatosNode {name:$node, tag:$tag, "
            "current_receipt_sha:$sha, pred_receipt_sha:$sha, "
            "pred_registered_at:$ts, baseline_lineage:'no_prior', "
            "pred_metric:$metric, pred_direction:$direction, "
            "pred_baseline:$baseline, pred_noise_band:$noise, "
            "pred_scale_type:$scale, pred_novel:'', pred_closes:'', "
            "novel_registered:false, pred_question_bound:true})"
            "-[:HAS_RECEIPT]->(r:VerdictReceipt) SET r=$receipt "
            "CREATE (:OutboxEntry {id:$event_id, tree:$tree, "
            "op:'prediction_register', node_tag:$tag, payload:$payload, "
            "status:'applied', created_at:$ts, applied_at:$ts, "
            "reason:'prediction_register_commit_intent', receipt_sha:$sha})",
            tree=tree,
            node=f"{tree}/{tag}",
            tag=tag,
            sha=receipt_sha,
            ts=registered_at,
            metric=payload["metric_name"],
            direction=payload["direction"],
            baseline=payload["baseline_value"],
            noise=payload["noise_band"],
            scale=payload["scale_type"],
            receipt={"receipt_sha": receipt_sha, **receipt_fields},
            event_id=event_id,
            payload=canonical_history_payload(payload),
        )
        assert inspect_neo_outbox_contract(kg)["ok"] is True
        forged = {**payload, "baseline_value": 999.0}
        kg(
            "MATCH (o:OutboxEntry {id:$id}) SET o.payload=$payload",
            id=event_id,
            payload=canonical_history_payload(forged),
        )
        report = inspect_neo_outbox_contract(kg)
        assert "neo4j.outbox.prediction_intent_v3" in report["failures"]
    finally:
        kg("MATCH (o:OutboxEntry {id:$id}) DETACH DELETE o", id=event_id)
        kg("MATCH (t:LakatosTree {name:$tree}) DETACH DELETE t", tree=tree)
        kg(
            "MATCH (r:VerdictReceipt {receipt_sha:$sha}) DETACH DELETE r",
            sha=receipt_sha,
        )


class _BorrowedDriver:
    def __init__(self, driver):
        self._driver = driver

    def session(self, *args, **kwargs):
        return self._driver.session(*args, **kwargs)

    def close(self):
        return None


def test_predeploy_and_runtime_receipt_round_trip_real_stores(
    neo4j_driver, pg_kw, tmp_path, monkeypatch
):
    """Blocking CI proves the coordinator and runtime receipt share real identities."""

    with neo4j_driver.session() as session:
        session.run("DROP CONSTRAINT lkt_outbox_id_unique IF EXISTS").consume()
        session.run("DROP CONSTRAINT lkt_argument_id_unique IF EXISTS").consume()

    monkeypatch.setenv("NEO4J_URI", "bolt://fixture.invalid:7687")
    monkeypatch.setenv("NEO4J_DATABASE", "neo4j")
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "fixture")
    monkeypatch.setenv("LAKATOS_PG_HOST", str(pg_kw["host"]))
    monkeypatch.setenv("LAKATOS_PG_PORT", str(pg_kw["port"]))
    monkeypatch.setenv("LAKATOS_PG_USER", str(pg_kw["user"]))
    monkeypatch.setenv("LAKATOS_PG_PASSWORD", str(pg_kw["password"]))
    monkeypatch.setenv("LAKATOS_PG_DB", str(pg_kw["dbname"]))
    monkeypatch.setenv("LAKATOS_STORAGE_ENVIRONMENT", "ci-integration")
    artifact = {"kind": "git", "source_commit": "c" * 40}
    monkeypatch.setattr(storage_predeploy, "_artifact_identity", lambda: artifact)
    monkeypatch.setattr(
        storage_predeploy,
        "_database_clients",
        lambda: (psycopg2, lambda **_kwargs: _BorrowedDriver(neo4j_driver)),
    )
    settings = ServerSettings.from_env()
    connection = psycopg2.connect(
        **pg_kw, options="-c search_path=pg_catalog"
    )
    borrowed = _BorrowedDriver(neo4j_driver)
    try:
        connection.autocommit = True
        target = storage_predeploy.target_identity(settings, connection, borrowed)
    finally:
        connection.close()
    operation = storage_predeploy.operation_identity(artifact)
    now = datetime.now(timezone.utc)
    drain = {
        "schema_version": storage_predeploy.DRAIN_SCHEMA,
        "contract_id": storage_predeploy.CONTRACT_ID,
        "environment": "ci-integration",
        "lease_id": "ci-exclusive-writer-lease",
        "target_sha256": target["sha256"],
        "operation_sha256": operation["sha256"],
        "writers_drained": True,
        "listener_count": 0,
        "replica_count": 0,
        "verified_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=5)).isoformat(),
        "evidence_refs": ["ci://isolated-testcontainers/session"],
    }
    drain_path = (tmp_path / "drain.json").absolute()
    drain_path.write_text(json.dumps(drain), encoding="utf-8")
    lease_snapshot = {
        "active": True,
        "writer_count": 0,
        "environment": drain["environment"],
        "target_sha256": drain["target_sha256"],
        "operation_sha256": drain["operation_sha256"],
        "lease_id": drain["lease_id"],
        "drain_receipt_sha256": hashlib.sha256(drain_path.read_bytes()).hexdigest(),
        "expires_at": drain["expires_at"],
    }
    fence_private_bytes = bytes(range(32))
    fence_public_key_hex = Ed25519PrivateKey.from_private_bytes(
        fence_private_bytes
    ).public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()

    class _FenceHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - stdlib handler API
            length = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(length))
            verified = datetime.now(timezone.utc)
            try:
                lease_expires = datetime.fromisoformat(
                    lease_snapshot["expires_at"].replace("Z", "+00:00")
                )
            except (AttributeError, ValueError):
                lease_expires = verified - timedelta(seconds=1)
            nonce = request.get("nonce")
            exact_request = (
                set(request) == {
                    "schema_version",
                    "nonce",
                    "environment",
                    "target_sha256",
                    "operation_sha256",
                    "lease_id",
                    "drain_receipt_sha256",
                }
                and request.get("schema_version")
                    == storage_predeploy.FENCE_VERIFICATION_SCHEMA
                and isinstance(nonce, str)
                and len(nonce) == 64
                and all(char in "0123456789abcdef" for char in nonce)
                and lease_snapshot["active"] is True
                and type(lease_snapshot["writer_count"]) is int
                and lease_snapshot["writer_count"] == 0
                and verified < lease_expires
                and all(
                    request.get(field) == lease_snapshot[field]
                    for field in (
                        "environment",
                        "target_sha256",
                        "operation_sha256",
                        "lease_id",
                        "drain_receipt_sha256",
                    )
                )
            )
            if not exact_request:
                self.send_response(409)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            proof_expires = min(
                lease_expires, verified + timedelta(seconds=20)
            )
            response = {
                "schema_version": request["schema_version"],
                "active": True,
                "nonce": request["nonce"],
                "environment": lease_snapshot["environment"],
                "target_sha256": lease_snapshot["target_sha256"],
                "operation_sha256": lease_snapshot["operation_sha256"],
                "lease_id": lease_snapshot["lease_id"],
                "drain_receipt_sha256": lease_snapshot["drain_receipt_sha256"],
                # Exercise exact signed timestamp spelling across the full
                # apply -> publish -> runtime readback path.
                "verified_at": verified.isoformat().replace("+00:00", "Z"),
                "expires_at": proof_expires.astimezone(
                    timezone(timedelta(hours=9))
                ).isoformat(),
                "evidence_refs": ["lease-store://independent-ci-snapshot"],
            }
            response["signature"] = Ed25519PrivateKey.from_private_bytes(
                fence_private_bytes
            ).sign(storage_predeploy._fence_signing_payload(response)).hex()
            payload = json.dumps(response, sort_keys=True).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args):
            pass

    authority = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FenceHandler)
    authority_thread = threading.Thread(
        target=authority.serve_forever, daemon=True
    )
    authority_thread.start()
    authority_url = f"http://127.0.0.1:{authority.server_port}/verify"
    mismatched_request = {
        "schema_version": storage_predeploy.FENCE_VERIFICATION_SCHEMA,
        "nonce": "0" * 64,
        "environment": lease_snapshot["environment"],
        "target_sha256": "0" * 64,
        "operation_sha256": lease_snapshot["operation_sha256"],
        "lease_id": lease_snapshot["lease_id"],
        "drain_receipt_sha256": lease_snapshot["drain_receipt_sha256"],
    }
    denied = urllib.request.Request(
        authority_url,
        data=json.dumps(mismatched_request, sort_keys=True).encode("utf-8"),
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as denied_info:
        urllib.request.urlopen(denied, timeout=3)
    assert denied_info.value.code == 409
    verifier = (tmp_path / "fence-verifier.py").absolute()
    verifier.write_text(
        f"#!{Path(sys.executable).resolve()}\n" + '''\
import json, sys, urllib.request
request = json.load(sys.stdin)
payload = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
call = urllib.request.Request("__AUTHORITY_URL__", data=payload, method="POST")
with urllib.request.urlopen(call, timeout=3) as response:
    sys.stdout.buffer.write(response.read())
'''.replace("__AUTHORITY_URL__", authority_url),
        encoding="utf-8",
    )
    verifier.chmod(0o755)
    verifier_sha = storage_predeploy.fence_verifier_identity(verifier)["sha256"]
    monkeypatch.setenv("LAKATOS_STORAGE_FENCE_VERIFIER_SHA256", verifier_sha)
    monkeypatch.setenv(
        "LAKATOS_STORAGE_FENCE_PUBLIC_KEY_HEX", fence_public_key_hex
    )
    settings = ServerSettings.from_env()
    receipt_path = (tmp_path / "predeploy.json").absolute()

    try:
        receipt = storage_predeploy.apply(
            drain_receipt=drain_path,
            environment="ci-integration",
            receipt_out=receipt_path,
            fence_verifier=verifier,
            fence_verifier_sha256=verifier_sha,
        )
    finally:
        authority.shutdown()
        authority.server_close()
        authority_thread.join(timeout=2)

    assert receipt["receipt_file_sha256"] == hashlib.sha256(
        receipt_path.read_bytes()
    ).hexdigest()
    connection = psycopg2.connect(**pg_kw)
    try:
        connection.autocommit = True
        runtime = storage_predeploy.verify_predeploy_receipt(
            receipt_path,
            receipt["receipt_file_sha256"],
            settings,
            connection,
            borrowed,
        )
    finally:
        connection.close()
    assert runtime["ok"] is True
    assert runtime["target_sha256"] == target["sha256"]
