from __future__ import annotations

import hashlib
import os
from pathlib import Path

import psycopg2
import pytest

from server.settings import ServerSettings
from server.storage_predeploy import _migration_pg_connect_parameters


def _settings(**overrides):
    values = {
        "neo4j_uri": "bolt+s://192.0.2.20:7687",
        "neo4j_user": "lakatos_runtime",
        "neo4j_password": "runtime-secret",
        "neo4j_database": "neo4j",
        "pg_host": "pg.example",
        "pg_port": 5432,
        "pg_user": "lakatos_runtime",
        "pg_password": "runtime-secret",
        "pg_db": "lakatos",
        "mongo_uri": "mongodb://127.0.0.1:27017",
        "storage_predeploy_receipt": None,
        "storage_predeploy_receipt_sha256": None,
        "storage_environment": "production",
        "storage_fence_verifier_sha256": None,
        "storage_fence_public_key_hex": None,
        "pg_migration_dsn": (
            "host=pg.example hostaddr=192.0.2.10 port=5432 dbname=lakatos "
            "user=lakatos_migrator password=migration-secret sslmode=verify-full "
            "sslrootcert=system channel_binding=require require_auth=scram-sha-256 "
            "target_session_attrs=read-write gssencmode=disable "
            "load_balance_hosts=disable"
        ),
        "pg_migration_user": "lakatos_migrator",
        "pg_migration_password": "migration-secret",
        "neo4j_migration_uri": "bolt+s://192.0.2.20:7687",
        "neo4j_migration_user": "lakatos_migrator",
        "neo4j_migration_password": "migration-secret",
    }
    values.update(overrides)
    return ServerSettings(**values)


def test_pg_migration_profile_is_explicit_tls_scram_single_target():
    parameters = _migration_pg_connect_parameters(_settings(), psycopg2)
    assert parameters["host"] == "pg.example"
    assert parameters["hostaddr"] == "192.0.2.10"
    assert parameters["user"] == "lakatos_migrator"
    assert parameters["sslmode"] == "verify-full"
    assert parameters["channel_binding"] == "require"
    assert parameters["require_auth"] == "scram-sha-256"
    assert parameters["target_session_attrs"] == "read-write"
    assert parameters["application_name"] == "lakatotree-storage-predeploy"


def test_pg_migration_profile_rejects_ambient_libpq_authority(monkeypatch):
    monkeypatch.setenv("PGSERVICE", "ambient-service")
    with pytest.raises(RuntimeError, match="ambient PG authority"):
        _migration_pg_connect_parameters(_settings(), psycopg2)


@pytest.mark.parametrize(
    "replace",
    (
        ("sslmode=verify-full", "sslmode=require"),
        ("channel_binding=require", "channel_binding=prefer"),
        ("require_auth=scram-sha-256", "require_auth=password"),
        ("target_session_attrs=read-write", "target_session_attrs=any"),
        ("hostaddr=192.0.2.10", "hostaddr=pg.example"),
        ("host=pg.example", "host=other.example"),
        ("user=lakatos_migrator", "user=lakatos_runtime"),
    ),
)
def test_pg_migration_profile_rejects_transport_target_or_actor_drift(replace):
    before, after = replace
    settings = _settings()
    settings = _settings(pg_migration_dsn=settings.pg_migration_dsn.replace(before, after))
    with pytest.raises(RuntimeError):
        _migration_pg_connect_parameters(settings, psycopg2)


def test_pg_migration_literal_host_cannot_alias_a_different_hostaddr():
    settings = _settings(
        pg_host="192.0.2.11",
        pg_migration_dsn=_settings().pg_migration_dsn.replace(
            "host=pg.example", "host=192.0.2.11"
        ),
    )
    with pytest.raises(RuntimeError, match="hostaddr differs"):
        _migration_pg_connect_parameters(settings, psycopg2)


def test_migration_principals_must_differ_from_runtime():
    with pytest.raises(RuntimeError, match="must be distinct"):
        _settings(
            pg_migration_user="lakatos_runtime",
            pg_migration_dsn=_settings().pg_migration_dsn.replace(
                "user=lakatos_migrator", "user=lakatos_runtime"
            ),
        ).require_pg_migration_dsn()
    with pytest.raises(RuntimeError, match="must be distinct"):
        _settings(neo4j_migration_user="lakatos_runtime").require_neo4j_migration()


def test_neo4j_migration_profile_requires_system_trusted_transport():
    uri, user, password = _settings().require_neo4j_migration()
    assert uri == "bolt+s://192.0.2.20:7687"
    assert user == "lakatos_migrator"
    assert password == "migration-secret"
    for uri in (
        "bolt://192.0.2.20:7687",
        "neo4j://192.0.2.20:7687",
        "neo4j+s://192.0.2.20:7687",
        "bolt+s://user:pass@192.0.2.20:7687",
        "bolt+s://192.0.2.20:7687?trust=all",
        "bolt+s://runtime.example:7687",
        "bolt+s://192.0.2.20",
    ):
        with pytest.raises(RuntimeError):
            _settings(neo4j_migration_uri=uri).require_neo4j_migration()

    with pytest.raises(RuntimeError, match="exact same URI"):
        _settings(
            neo4j_migration_uri="bolt+s://192.0.2.21:7687"
        ).require_neo4j_migration()


def test_runtime_neo4j_profile_uses_the_same_pinned_endpoint_shape():
    uri, user, password = _settings().require_neo4j()
    assert uri == "bolt+s://192.0.2.20:7687"
    assert user == "lakatos_runtime"
    assert password == "runtime-secret"
    for uri in (
        "neo4j+s://192.0.2.20:7687",
        "bolt+s://runtime.example:7687",
        "bolt+s://192.0.2.20",
        "bolt+s://user:pass@192.0.2.20:7687",
    ):
        with pytest.raises(RuntimeError):
            _settings(neo4j_uri=uri).require_neo4j()


def _runtime_profile(tmp_path: Path, **overrides) -> ServerSettings:
    ca = (tmp_path / "runtime-ca.pem").resolve()
    if not ca.exists():
        ca.write_bytes(b"test-runtime-ca")
        os.chmod(ca, 0o400)
    dsn = (
        "host=192.0.2.10 hostaddr=192.0.2.10 port=5432 dbname=lakatos "
        "user=lakatos_runtime password=runtime-secret sslmode=verify-full "
        f"sslrootcert={ca} channel_binding=require require_auth=scram-sha-256 "
        "target_session_attrs=read-write gssencmode=disable "
        "load_balance_hosts=disable ssl_min_protocol_version=TLSv1.2 "
        "ssl_max_protocol_version=TLSv1.3 "
        "options='-c search_path=pg_catalog'"
    )
    values = {
        "pg_host": "192.0.2.10",
        "pg_runtime_dsn": dsn,
        "pg_runtime_ca_sha256": hashlib.sha256(ca.read_bytes()).hexdigest(),
    }
    values.update(overrides)
    return _settings(
        **values,
    )


def test_pg_runtime_profile_is_one_pinned_tls_scram_session(tmp_path):
    parameters = _runtime_profile(tmp_path).pg_kw
    assert parameters["host"] == parameters["hostaddr"] == "192.0.2.10"
    assert parameters["user"] == "lakatos_runtime"
    assert parameters["sslmode"] == "verify-full"
    assert parameters["channel_binding"] == "require"
    assert parameters["require_auth"] == "scram-sha-256"
    assert parameters["options"] == "-c search_path=pg_catalog"
    assert parameters["sslcertmode"] == "disable"


def test_pg_runtime_profile_rejects_ambient_authority_and_ca_drift(
    tmp_path, monkeypatch
):
    settings = _runtime_profile(tmp_path)
    monkeypatch.setenv("PGSERVICE", "ambient")
    with pytest.raises(RuntimeError, match="ambient PG authority"):
        settings.require_pg_runtime_profile()
    monkeypatch.delenv("PGSERVICE")
    ca = Path(settings.require_pg_runtime_profile()["sslrootcert"])
    os.chmod(ca, 0o600)
    ca.write_bytes(b"replaced")
    os.chmod(ca, 0o400)
    with pytest.raises(RuntimeError, match="immutable pin"):
        settings.require_pg_runtime_profile()


@pytest.mark.parametrize(
    "before,after",
    (
        ("sslmode=verify-full", "sslmode=require"),
        ("require_auth=scram-sha-256", "require_auth=password"),
        ("hostaddr=192.0.2.10", "hostaddr=192.0.2.11"),
        ("load_balance_hosts=disable", "load_balance_hosts=random"),
        (
            "options='-c search_path=pg_catalog'",
            "options='-c search_path=public'",
        ),
    ),
)
def test_pg_runtime_profile_rejects_security_drift(tmp_path, before, after):
    settings = _runtime_profile(tmp_path)
    with pytest.raises(RuntimeError):
        _runtime_profile(
            tmp_path,
            pg_runtime_dsn=settings.pg_runtime_dsn.replace(before, after),
        ).require_pg_runtime_profile()


def test_pg_runtime_live_session_guard_rejects_non_scram_hba(tmp_path):
    settings = _runtime_profile(tmp_path)

    class _Cursor:
        def __init__(self, system_user):
            self.system_user = system_user
            self.query_count = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, _query):
            self.query_count += 1

        def fetchone(self):
            if self.query_count == 1:
                return (
                    "lakatos", "lakatos_runtime", "lakatos_runtime",
                    self.system_user, "pg_catalog", "origin", "off",
                    "192.0.2.10", 5432,
                )
            return (True, "TLSv1.3", "TLS_AES_256_GCM_SHA384", 256)

    class _Connection:
        def __init__(self, system_user):
            self.cursor_value = _Cursor(system_user)

        def cursor(self):
            return self.cursor_value

    settings.verify_pg_runtime_connection(
        _Connection("scram-sha-256:lakatos_runtime")
    )
    with pytest.raises(RuntimeError, match="pinned TLS/SCRAM posture"):
        settings.verify_pg_runtime_connection(_Connection(None))


def test_runtime_launchers_reject_all_one_shot_authority_material():
    root = Path(__file__).parents[1]
    for relative in (
        "server/run.sh", "server/run_internal.sh", "scripts/dev_server_restart.sh"
    ):
        source = (root / relative).read_text(encoding="utf-8")
        for name in (
            "LAKATOS_STORAGE_PG_MIGRATION_USER",
            "LAKATOS_STORAGE_PG_MIGRATION_PASSWORD",
            "LAKATOS_STORAGE_PG_MIGRATION_DSN",
            "LAKATOS_STORAGE_NEO4J_MIGRATION_URI",
            "LAKATOS_STORAGE_NEO4J_MIGRATION_USER",
            "LAKATOS_STORAGE_NEO4J_MIGRATION_PASSWORD",
            "LAKATOTREE_READINESS_PG_DSN",
            "LAKATOTREE_READINESS_NEO4J_URI",
            "LAKATOTREE_READINESS_NEO4J_USER",
            "LAKATOTREE_READINESS_NEO4J_PASSWORD",
        ):
            assert name in source
        assert 'if [ "$STORAGE_ACCESS_REQUESTED" = "1" ]' in source
        assert "LAKATOS_STORAGE_PG_RUNTIME_DSN" in source
        assert "LAKATOS_STORAGE_PG_RUNTIME_CA_SHA256" in source
        assert "LAKATOS_STORAGE_RUNTIME_WRITER_VERIFIER" in source
        assert "LAKATOS_STORAGE_RUNTIME_WRITER_VERIFIER_SHA256" in source
        assert "LAKATOS_STORAGE_RUNTIME_WRITER_PUBLIC_KEY_HEX" in source


def test_runtime_writer_authority_profile_is_complete_and_key_separated(tmp_path):
    verifier = (tmp_path / "runtime-writer-verifier").resolve()
    settings = _settings(
        storage_fence_public_key_hex="1" * 64,
        storage_runtime_writer_verifier=str(verifier),
        storage_runtime_writer_verifier_sha256="2" * 64,
        storage_runtime_writer_public_key_hex="3" * 64,
    )
    assert settings.require_runtime_writer_authority() == (
        verifier,
        "2" * 64,
        "3" * 64,
    )
    with pytest.raises(RuntimeError, match="must differ"):
        _settings(
            storage_fence_public_key_hex="1" * 64,
            storage_runtime_writer_verifier=str(verifier),
            storage_runtime_writer_verifier_sha256="2" * 64,
            storage_runtime_writer_public_key_hex="1" * 64,
        ).require_runtime_writer_authority()
    with pytest.raises(RuntimeError, match="settings missing"):
        _settings(
            storage_runtime_writer_verifier=str(verifier),
        ).require_runtime_writer_authority()
