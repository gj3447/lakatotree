"""Static and packaging controls for privileged datastore provisioning."""

from __future__ import annotations

import importlib.resources
import re

from server import production_readiness_live as live


RESOURCE = "postgresql_large_object_acl_v1.sql"


def _sql() -> str:
    return importlib.resources.files("server.storage_provisioning").joinpath(
        RESOURCE
    ).read_text(encoding="utf-8")


def test_postgresql_large_object_resource_is_packaged_and_inventory_bound():
    sql = _sql()
    inventory = sql.split(
        "WITH expected(signature) AS (VALUES", 1
    )[1].split(")\n  SELECT", 1)[0]
    signatures = tuple(re.findall(r"\('([^']+)'\)", inventory))

    assert set(signatures) == set(live._PG16_17_LARGE_OBJECT_ROUTINES)
    assert len(signatures) == len(set(signatures))
    assert "server_version < 160000 OR server_version >= 180000" in sql
    assert "current_user = session_user" in sql
    assert "transaction_read_only" in sql
    assert "observed_oids IS DISTINCT FROM expected_oids" in sql
    assert "p.oid >= 16384" in sql
    assert "p.proowner <> 10" in sql
    assert "public_execute_count <> 0" in sql


def test_postgresql_large_object_resource_only_narrows_authority_atomically():
    sql = _sql()
    executable = "\n".join(
        line for line in sql.splitlines() if not line.lstrip().startswith("--")
    )

    assert executable.lstrip().startswith("BEGIN;")
    assert executable.rstrip().endswith("COMMIT;")
    assert re.search(r"\bREVOKE EXECUTE ON FUNCTION\b", executable)
    assert re.search(r"\bGRANT\b", executable) is None
    assert re.search(r"\bCASCADE\b", executable) is None
    assert "CREATE ROLE" not in executable
    assert "CREATE DATABASE" not in executable
