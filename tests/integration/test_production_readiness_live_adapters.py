"""Execute the shadow readiness SQL/Cypher against disposable real databases."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.resources
import socket
from uuid import uuid4

import psycopg2
import pytest
from psycopg2 import sql

from server import production_readiness_live as live
from server import storage_access
from server import storage_predeploy


pytestmark = pytest.mark.integration


def _pg_dsn(pg_kw) -> str:
    values = dict(pg_kw)
    values["host"] = socket.gethostbyname(str(values["host"]))
    return psycopg2.extensions.make_dsn(**values)


def _resource(package: str, name: str) -> str:
    return importlib.resources.files(package).joinpath(name).read_text(
        encoding="utf-8"
    )


def _public_large_object_execute_count(cursor) -> int:
    cursor.execute(
        "SELECT count(*) "
        "FROM pg_catalog.pg_proc p "
        "JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace "
        "CROSS JOIN LATERAL pg_catalog.aclexplode(COALESCE("
        "p.proacl,pg_catalog.acldefault('f'::\"char\",p.proowner))) acl "
        "WHERE n.nspname='pg_catalog' "
        "AND (pg_catalog.left(p.proname,3)='lo_' "
        "OR p.proname IN ('loread','lowrite')) "
        "AND acl.grantee=0 AND acl.privilege_type='EXECUTE'"
    )
    return int(cursor.fetchone()[0])


def test_postgresql_live_adapter_executes_catalog_acl_and_column_projection(pg_kw):
    dsn = _pg_dsn(pg_kw)
    owner = "readiness_it_owner"
    migrator = "readiness_it_migrator"
    runtime = "readiness_it_runtime"
    inherited = "readiness_it_inherited"
    connection = psycopg2.connect(dsn)
    try:
        with connection, connection.cursor() as cursor:
            for role in (owner, migrator, runtime, inherited):
                cursor.execute(f'CREATE ROLE "{role}" NOLOGIN')
            cursor.execute(f'GRANT "{inherited}" TO "{runtime}"')
            cursor.execute(f'GRANT SELECT (tree) ON public.history TO "{inherited}"')
            cursor.execute("GRANT UPDATE (tree) ON public.history TO PUBLIC")
            cursor.execute("SELECT count(*) FROM public.history")
            before = int(cursor.fetchone()[0])

        parsed_dsn = psycopg2.extensions.parse_dsn(dsn)
        result = live._collect_postgresql_impl(
            {
                "database": str(pg_kw["dbname"]),
                "owner_role": owner,
                "migrator_role": migrator,
                "runtime_role": runtime,
            },
            10,
            {},
            injected_connection=connection,
            injected_endpoint=(parsed_dsn["host"], int(parsed_dsn["port"])),
        )
        connection.rollback()
        connection.set_session(readonly=False, autocommit=False)

        with connection, connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM public.history")
            after = int(cursor.fetchone()[0])

        assert result.status == "OBSERVED"
        assert result.failure_codes == ()
        assert result.facts["transaction_read_only"] is True
        assert result.facts["database_matches"] is True
        assert result.facts["acl_projection_scope"] == "contract-objects-v1"
        assert result.facts["acl_projection_count"] > 0
        assert result.facts["public_acl_entry_counts"]["column"] > 0
        history = result.facts["objects"]["public.history"]
        assert "SELECT" in history["runtime_column_only_privileges"]
        assert history["runtime_column_privilege_count"] > 0
        assert live._sha256(inherited.encode()) in result.facts["runtime_effective_role_sha256"]
        assert before == after
        assert result.binding_material["system_identifier"]
        assert live._normalize_result("postgresql", result)["status"] == "OBSERVED"
    finally:
        with connection, connection.cursor() as cursor:
            cursor.execute("REVOKE UPDATE (tree) ON public.history FROM PUBLIC")
            cursor.execute(f'REVOKE SELECT (tree) ON public.history FROM "{inherited}"')
            cursor.execute(f'REVOKE "{inherited}" FROM "{runtime}"')
            for role in (runtime, inherited, migrator, owner):
                cursor.execute(f'DROP ROLE IF EXISTS "{role}"')
        connection.close()


def test_postgresql_strict_access_topology_is_realizable_and_exact(pg_kw):
    suffix = uuid4().hex[:12]
    database = f"lkt_access_{suffix}"
    roles = {
        "owner": f"lkt_owner_{suffix}",
        "migrator": f"lkt_migrator_{suffix}",
        "runtime": f"lkt_runtime_{suffix}",
        "audit": f"lkt_audit_{suffix}",
    }
    passwords = {
        label: uuid4().hex for label in ("migrator", "runtime", "audit")
    }
    admin = psycopg2.connect(**pg_kw)
    target_admin = None
    migrator_connection = None
    audit_connection = None
    try:
        admin.autocommit = True
        with admin.cursor() as cursor:
            cursor.execute(sql.SQL(
                "CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                "NOINHERIT NOREPLICATION NOBYPASSRLS"
            ).format(sql.Identifier(roles["owner"])))
            for label in ("migrator", "runtime", "audit"):
                cursor.execute(sql.SQL(
                    "CREATE ROLE {} LOGIN PASSWORD %s NOSUPERUSER NOCREATEDB "
                    "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
                ).format(sql.Identifier(roles[label])), (passwords[label],))
            cursor.execute(sql.SQL(
                "GRANT {} TO {} WITH ADMIN FALSE, INHERIT FALSE, SET TRUE"
            ).format(
                sql.Identifier(roles["owner"]),
                sql.Identifier(roles["migrator"]),
            ))
            cursor.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(database), sql.Identifier(roles["owner"])
            ))

        target_kw = {**pg_kw, "dbname": database}
        target_admin = psycopg2.connect(**target_kw)
        target_admin.autocommit = True
        with target_admin.cursor() as cursor:
            cursor.execute(sql.SQL("ALTER SCHEMA public OWNER TO {}").format(
                sql.Identifier(roles["owner"])
            ))
            public_before = _public_large_object_execute_count(cursor)
            cursor.execute(sql.SQL("SET ROLE {}").format(
                sql.Identifier(roles["owner"])
            ))
            with pytest.raises(psycopg2.Error, match="direct superuser"):
                cursor.execute(_resource(
                    "server.storage_provisioning",
                    "postgresql_large_object_acl_v1.sql",
                ))
            cursor.execute("ROLLBACK")
            cursor.execute("RESET ROLE")
            assert _public_large_object_execute_count(cursor) == public_before

            cursor.execute(
                "CREATE FUNCTION pg_catalog.lo_probe() RETURNS integer "
                "LANGUAGE SQL AS 'SELECT 1'"
            )
            with pytest.raises(psycopg2.Error, match="inventory differs"):
                cursor.execute(_resource(
                    "server.storage_provisioning",
                    "postgresql_large_object_acl_v1.sql",
                ))
            cursor.execute("ROLLBACK")
            assert _public_large_object_execute_count(cursor) == public_before
            cursor.execute("DROP FUNCTION pg_catalog.lo_probe()")

            cursor.execute(_resource(
                "server.storage_provisioning",
                "postgresql_large_object_acl_v1.sql",
            ))
            cursor.execute(_resource(
                "server.storage_provisioning",
                "postgresql_large_object_acl_v1.sql",
            ))
            cursor.execute(sql.SQL("SET ROLE {}").format(
                sql.Identifier(roles["owner"])
            ))
            cursor.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(
                sql.Identifier(database)
            ))
            cursor.execute(sql.SQL(
                "GRANT CONNECT ON DATABASE {} TO {}, {}, {}"
            ).format(
                sql.Identifier(database),
                sql.Identifier(roles["migrator"]),
                sql.Identifier(roles["runtime"]),
                sql.Identifier(roles["audit"]),
            ))
            cursor.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
            cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(
                sql.Identifier(roles["runtime"])
            ))
            cursor.execute("RESET ROLE")

        migrator_kw = {
            **target_kw,
            "user": roles["migrator"],
            "password": passwords["migrator"],
        }
        migrator_connection = psycopg2.connect(**migrator_kw)
        migrator_connection.autocommit = True
        storage_predeploy._bounded_pg_migration(
            migrator_connection,
            (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat(),
            _resource(
                "server.storage_migrations", "critique_history_v1.sql"
            ).encode("utf-8"),
        )
        with migrator_connection.cursor() as cursor:
            cursor.execute(sql.SQL("SET ROLE {}").format(
                sql.Identifier(roles["owner"])
            ))
            cursor.execute(sql.SQL(
                "GRANT SELECT,INSERT ON TABLE "
                "public.history,public.history_event_claims,"
                "public.metric_snapshots,public.lineage TO {}"
            ).format(sql.Identifier(roles["runtime"])))
            cursor.execute(sql.SQL(
                "GRANT SELECT,USAGE ON SEQUENCE "
                "public.history_id_seq,public.metric_snapshots_id_seq,"
                "public.lineage_id_seq TO {}"
            ).format(sql.Identifier(roles["runtime"])))
            cursor.execute("RESET ROLE")

        audit_kw = {
            **target_kw,
            "user": roles["audit"],
            "password": passwords["audit"],
            "options": "-c search_path=pg_catalog",
        }
        audit_connection = psycopg2.connect(**audit_kw)
        parsed_dsn = psycopg2.extensions.parse_dsn(_pg_dsn(target_kw))
        nonce = "7" * 64
        result = live._collect_postgresql_impl(
            {
                "database": database,
                "owner_role": roles["owner"],
                "migrator_role": roles["migrator"],
                "runtime_role": roles["runtime"],
                "audit_role": roles["audit"],
                "challenge_nonce": nonce,
            },
            10,
            {},
            injected_connection=audit_connection,
            injected_endpoint=(
                socket.gethostbyname(parsed_dsn["host"]),
                int(parsed_dsn["port"]),
            ),
        )
        policy = {
            "postgresql": {
                "database": database,
                **{f"{label}_role": name for label, name in roles.items()},
                "migrator_owner_membership": {
                    "admin_option": False,
                    "inherit_option": False,
                    "set_option": True,
                },
            }
        }

        assert result.status == "OBSERVED"
        assert result.failure_codes == ()
        assert result.facts["audit_principal_read_only"] is True
        assert result.facts["authority_boundary_deviation_count"] == 0
        assert result.facts["acl_projection"]
        assert storage_access._postgresql_projection_failures(
            result.facts, policy, nonce
        ) == []

        with target_admin.cursor() as cursor:
            cursor.execute(
                "GRANT EXECUTE ON FUNCTION "
                "pg_catalog.lo_open(oid,integer) TO PUBLIC"
            )
        compromised = live._collect_postgresql_impl(
            {
                "database": database,
                "owner_role": roles["owner"],
                "migrator_role": roles["migrator"],
                "runtime_role": roles["runtime"],
                "audit_role": roles["audit"],
                "challenge_nonce": nonce,
            },
            10,
            {},
            injected_connection=audit_connection,
            injected_endpoint=(
                socket.gethostbyname(parsed_dsn["host"]),
                int(parsed_dsn["port"]),
            ),
        )
        assert compromised.status == "PARTIAL"
        assert compromised.facts["audit_principal_read_only"] is False
        assert compromised.facts["authority_boundary_deviation_count"] > 0
        with target_admin.cursor() as cursor:
            cursor.execute(_resource(
                "server.storage_provisioning",
                "postgresql_large_object_acl_v1.sql",
            ))
    finally:
        if audit_connection is not None:
            audit_connection.close()
        if migrator_connection is not None:
            migrator_connection.close()
        if target_admin is not None:
            target_admin.close()
        try:
            with admin.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname=%s AND pid<>pg_backend_pid()",
                    (database,),
                )
                cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(
                    sql.Identifier(database)
                ))
                for label in ("migrator", "runtime", "audit", "owner"):
                    cursor.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(
                        sql.Identifier(roles[label])
                    ))
        finally:
            admin.close()


def test_neo4j_live_adapter_executes_identity_and_privilege_query_path(
    neo4j_connection_info, neo4j_driver,
):
    result = live._collect_neo4j_impl(
        {"database": "neo4j"},
        10,
        {},
        injected_driver=neo4j_driver,
        injected_uri=neo4j_connection_info["uri"],
    )

    assert result.status in {"OBSERVED", "PARTIAL"}
    assert result.facts["database_name_matches"] is True
    assert result.facts["database_id_sha256"]
    assert result.facts["version"]
    assert result.facts["read_query_count"] == 6
    assert result.binding_material["database_id"]
    assert live._normalize_result(
        "neo4j",
        result,
        sensitive_values=frozenset({neo4j_connection_info["password"]}),
    )["status"] == result.status
    if result.facts["enterprise"] is False:
        assert result.status == "PARTIAL"
        assert "neo4j.effective_privileges.unavailable" in result.failure_codes
