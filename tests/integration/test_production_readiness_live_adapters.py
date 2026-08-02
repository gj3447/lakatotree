"""Execute the shadow readiness SQL/Cypher against disposable real databases."""

from __future__ import annotations

import socket

import psycopg2
import pytest

from server import production_readiness_live as live


pytestmark = pytest.mark.integration


def _pg_dsn(pg_kw) -> str:
    values = dict(pg_kw)
    values["host"] = socket.gethostbyname(str(values["host"]))
    return psycopg2.extensions.make_dsn(**values)


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
    assert result.facts["read_query_count"] == 4
    assert result.binding_material["database_id"]
    assert live._normalize_result(
        "neo4j",
        result,
        sensitive_values=frozenset({neo4j_connection_info["password"]}),
    )["status"] == result.status
    if result.facts["enterprise"] is False:
        assert result.status == "PARTIAL"
        assert "neo4j.effective_privileges.unavailable" in result.failure_codes
