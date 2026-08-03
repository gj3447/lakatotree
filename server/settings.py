"""Runtime settings for the Lakatos server.

# KG: span_lakatotree_server_architecture
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import stat
from urllib.parse import urlsplit


_MAX_RUNTIME_CA_BYTES = 1024 * 1024


def _load_immutable_pinned_file(path: Path, sha256_hex: str) -> bytes:
    """Read one authority file without following or racing a mutable leaf."""

    if not path.is_absolute():
        raise RuntimeError("PostgreSQL runtime CA path must be absolute")
    try:
        before = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError("PostgreSQL runtime CA file is unavailable") from exc
    if (
        resolved != path
        or stat.S_ISLNK(before.st_mode)
        or not stat.S_ISREG(before.st_mode)
        or bool(before.st_mode & 0o222)
        or not 0 < before.st_size <= _MAX_RUNTIME_CA_BYTES
    ):
        raise RuntimeError(
            "PostgreSQL runtime CA file is not an immutable regular file"
        )
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise RuntimeError("PostgreSQL runtime CA file is unavailable") from exc
    try:
        opened = os.fstat(descriptor)
        if (
            (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
            or not stat.S_ISREG(opened.st_mode)
            or bool(opened.st_mode & 0o222)
            or not 0 < opened.st_size <= _MAX_RUNTIME_CA_BYTES
        ):
            raise RuntimeError(
                "PostgreSQL runtime CA file changed during secure open"
            )
        raw = os.pread(descriptor, _MAX_RUNTIME_CA_BYTES + 1, 0)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        len(raw) > _MAX_RUNTIME_CA_BYTES
        or (
            after.st_dev,
            after.st_ino,
            after.st_size,
            stat.S_IMODE(after.st_mode),
        )
        != (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            stat.S_IMODE(opened.st_mode),
        )
        or not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), sha256_hex)
    ):
        raise RuntimeError(
            "PostgreSQL runtime CA file changed or differs from its immutable pin"
        )
    return raw


def _require_pinned_neo4j_uri(value: str, *, setting: str) -> str:
    """Require the one endpoint shape that live access evidence can bind."""

    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise RuntimeError(f"{setting} port is invalid") from exc
    if (
        parsed.scheme != "bolt+s"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.hostname is None
        or port is None
        or not 1 <= port <= 65535
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError(
            f"{setting} must be one credential-free bolt+s literal-IP endpoint "
            "with an explicit port"
        )
    try:
        ipaddress.ip_address(parsed.hostname)
    except ValueError as exc:
        raise RuntimeError(f"{setting} host must be one literal IP") from exc
    return value


@dataclass(frozen=True)
class ServerSettings:
    neo4j_uri: str | None = field(repr=False)
    neo4j_user: str | None
    neo4j_password: str | None = field(repr=False)
    neo4j_database: str | None
    pg_host: str
    pg_port: int
    pg_user: str
    pg_password: str = field(repr=False)
    pg_db: str
    mongo_uri: str = field(repr=False)
    storage_predeploy_receipt: str | None
    storage_predeploy_receipt_sha256: str | None
    storage_environment: str | None
    storage_fence_verifier_sha256: str | None
    storage_fence_public_key_hex: str | None
    storage_access_policy: str | None = None
    storage_access_policy_sha256: str | None = None
    storage_access_predeploy_bundle: str | None = None
    storage_access_predeploy_bundle_sha256: str | None = None
    storage_access_startup_bundle: str | None = None
    storage_access_startup_bundle_sha256: str | None = None
    storage_runtime_writer_verifier: str | None = None
    storage_runtime_writer_verifier_sha256: str | None = None
    storage_runtime_writer_public_key_hex: str | None = None
    pg_runtime_dsn: str | None = field(default=None, repr=False)
    pg_runtime_ca_sha256: str | None = None
    pg_migration_dsn: str | None = field(default=None, repr=False)
    pg_migration_user: str | None = None
    pg_migration_password: str | None = field(default=None, repr=False)
    neo4j_migration_uri: str | None = field(default=None, repr=False)
    neo4j_migration_user: str | None = None
    neo4j_migration_password: str | None = field(default=None, repr=False)
    temporal_c1_python: str | None = None
    temporal_c1_artifact_directory: str | None = None
    temporal_c1_artifact_sha256: str | None = None
    temporal_c1_python_sha256: str | None = None
    temporal_time_authority_executable: str | None = None
    temporal_time_authority_executable_sha256: str | None = None
    temporal_time_authority_did: str | None = None

    @classmethod
    def from_env(cls) -> "ServerSettings":
        return cls(
            neo4j_uri=os.environ.get("NEO4J_URI"),
            neo4j_user=os.environ.get("NEO4J_USER"),
            neo4j_password=os.environ.get("NEO4J_PASSWORD"),
            neo4j_database=os.environ.get("NEO4J_DATABASE"),
            pg_host=os.environ.get("LAKATOS_PG_HOST", "localhost"),
            pg_port=int(os.environ.get("LAKATOS_PG_PORT", "55100")),
            pg_user=os.environ.get("LAKATOS_PG_USER", "admin"),
            pg_password=os.environ.get("LAKATOS_PG_PASSWORD", ""),
            pg_db=os.environ.get("LAKATOS_PG_DB", "lakatos"),
            mongo_uri=os.environ.get("LAKATOS_MONGO_URI", "mongodb://localhost:27017"),
            storage_predeploy_receipt=os.environ.get(
                "LAKATOS_STORAGE_PREDEPLOY_RECEIPT"
            ),
            storage_predeploy_receipt_sha256=os.environ.get(
                "LAKATOS_STORAGE_PREDEPLOY_RECEIPT_SHA256"
            ),
            storage_environment=os.environ.get("LAKATOS_STORAGE_ENVIRONMENT"),
            storage_fence_verifier_sha256=os.environ.get(
                "LAKATOS_STORAGE_FENCE_VERIFIER_SHA256"
            ),
            storage_fence_public_key_hex=os.environ.get(
                "LAKATOS_STORAGE_FENCE_PUBLIC_KEY_HEX"
            ),
            storage_access_policy=os.environ.get(
                "LAKATOS_STORAGE_ACCESS_POLICY"
            ),
            storage_access_policy_sha256=os.environ.get(
                "LAKATOS_STORAGE_ACCESS_POLICY_SHA256"
            ),
            storage_access_predeploy_bundle=os.environ.get(
                "LAKATOS_STORAGE_ACCESS_PREDEPLOY_BUNDLE"
            ),
            storage_access_predeploy_bundle_sha256=os.environ.get(
                "LAKATOS_STORAGE_ACCESS_PREDEPLOY_BUNDLE_SHA256"
            ),
            storage_access_startup_bundle=os.environ.get(
                "LAKATOS_STORAGE_ACCESS_STARTUP_BUNDLE"
            ),
            storage_access_startup_bundle_sha256=os.environ.get(
                "LAKATOS_STORAGE_ACCESS_STARTUP_BUNDLE_SHA256"
            ),
            storage_runtime_writer_verifier=os.environ.get(
                "LAKATOS_STORAGE_RUNTIME_WRITER_VERIFIER"
            ),
            storage_runtime_writer_verifier_sha256=os.environ.get(
                "LAKATOS_STORAGE_RUNTIME_WRITER_VERIFIER_SHA256"
            ),
            storage_runtime_writer_public_key_hex=os.environ.get(
                "LAKATOS_STORAGE_RUNTIME_WRITER_PUBLIC_KEY_HEX"
            ),
            pg_runtime_dsn=os.environ.get(
                "LAKATOS_STORAGE_PG_RUNTIME_DSN"
            ),
            pg_runtime_ca_sha256=os.environ.get(
                "LAKATOS_STORAGE_PG_RUNTIME_CA_SHA256"
            ),
            pg_migration_user=os.environ.get(
                "LAKATOS_STORAGE_PG_MIGRATION_USER"
            ),
            pg_migration_dsn=os.environ.get(
                "LAKATOS_STORAGE_PG_MIGRATION_DSN"
            ),
            pg_migration_password=os.environ.get(
                "LAKATOS_STORAGE_PG_MIGRATION_PASSWORD"
            ),
            neo4j_migration_user=os.environ.get(
                "LAKATOS_STORAGE_NEO4J_MIGRATION_USER"
            ),
            neo4j_migration_uri=os.environ.get(
                "LAKATOS_STORAGE_NEO4J_MIGRATION_URI"
            ),
            neo4j_migration_password=os.environ.get(
                "LAKATOS_STORAGE_NEO4J_MIGRATION_PASSWORD"
            ),
            temporal_c1_python=os.environ.get(
                "LAKATOS_TEMPORAL_C1_PYTHON"
            ),
            temporal_c1_artifact_directory=os.environ.get(
                "LAKATOS_TEMPORAL_C1_ARTIFACT_DIRECTORY"
            ),
            temporal_c1_artifact_sha256=os.environ.get(
                "LAKATOS_TEMPORAL_C1_ARTIFACT_SHA256"
            ),
            temporal_c1_python_sha256=os.environ.get(
                "LAKATOS_TEMPORAL_C1_PYTHON_SHA256"
            ),
            temporal_time_authority_executable=os.environ.get(
                "LAKATOS_TEMPORAL_TIME_AUTHORITY_EXECUTABLE"
            ),
            temporal_time_authority_executable_sha256=os.environ.get(
                "LAKATOS_TEMPORAL_TIME_AUTHORITY_EXECUTABLE_SHA256"
            ),
            temporal_time_authority_did=os.environ.get(
                "LAKATOS_TEMPORAL_TIME_AUTHORITY_DID"
            ),
        )

    @property
    def pg_kw(self) -> dict:
        if self.storage_access_requested:
            return self.require_pg_runtime_profile()
        return {
            "host": self.pg_host,
            "port": self.pg_port,
            "user": self.pg_user,
            "password": self.pg_password,
            "dbname": self.pg_db,
            "connect_timeout": 5,
        }

    @property
    def storage_access_requested(self) -> bool:
        """Treat every partial runtime-attestation profile as strict mode."""

        return any(
            value is not None
            for value in (
                self.storage_environment,
                self.storage_fence_verifier_sha256,
                self.storage_fence_public_key_hex,
                self.storage_predeploy_receipt,
                self.storage_predeploy_receipt_sha256,
                self.storage_access_policy,
                self.storage_access_policy_sha256,
                self.storage_access_predeploy_bundle,
                self.storage_access_predeploy_bundle_sha256,
                self.storage_access_startup_bundle,
                self.storage_access_startup_bundle_sha256,
                self.storage_runtime_writer_verifier,
                self.storage_runtime_writer_verifier_sha256,
                self.storage_runtime_writer_public_key_hex,
                self.pg_runtime_dsn,
                self.pg_runtime_ca_sha256,
            )
        )

    @property
    def temporal_independent_verifier_requested(self) -> bool:
        """Any partial Gate-4 profile is an explicit fail-closed request."""

        return any(
            value is not None
            for value in (
                self.temporal_c1_python,
                self.temporal_c1_artifact_directory,
                self.temporal_c1_artifact_sha256,
                self.temporal_c1_python_sha256,
                self.temporal_time_authority_executable,
                self.temporal_time_authority_executable_sha256,
                self.temporal_time_authority_did,
            )
        )

    def require_temporal_independent_verifier(
        self,
    ) -> tuple[Path, Path, str, str, Path, str, str]:
        """Return the complete public Gate-4 process profile; never a secret."""

        fields = (
            ("LAKATOS_TEMPORAL_C1_PYTHON", self.temporal_c1_python),
            (
                "LAKATOS_TEMPORAL_C1_ARTIFACT_DIRECTORY",
                self.temporal_c1_artifact_directory,
            ),
            (
                "LAKATOS_TEMPORAL_C1_ARTIFACT_SHA256",
                self.temporal_c1_artifact_sha256,
            ),
            (
                "LAKATOS_TEMPORAL_C1_PYTHON_SHA256",
                self.temporal_c1_python_sha256,
            ),
            (
                "LAKATOS_TEMPORAL_TIME_AUTHORITY_EXECUTABLE",
                self.temporal_time_authority_executable,
            ),
            (
                "LAKATOS_TEMPORAL_TIME_AUTHORITY_EXECUTABLE_SHA256",
                self.temporal_time_authority_executable_sha256,
            ),
            (
                "LAKATOS_TEMPORAL_TIME_AUTHORITY_DID",
                self.temporal_time_authority_did,
            ),
        )
        missing = [name for name, value in fields if not value]
        if missing:
            raise RuntimeError(
                "independent temporal verifier settings missing: "
                + ", ".join(missing)
            )
        python = Path(self.temporal_c1_python or "")
        artifact_directory = Path(self.temporal_c1_artifact_directory or "")
        authority = Path(self.temporal_time_authority_executable or "")
        if not all(path.is_absolute() for path in (python, artifact_directory, authority)):
            raise RuntimeError(
                "independent temporal verifier paths must be absolute"
            )
        artifact_sha = self.temporal_c1_artifact_sha256 or ""
        python_sha = self.temporal_c1_python_sha256 or ""
        authority_sha = self.temporal_time_authority_executable_sha256 or ""
        if any(
            len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)
            for value in (artifact_sha, python_sha, authority_sha)
        ):
            raise RuntimeError(
                "independent temporal verifier pins are malformed"
            )
        authority_did = self.temporal_time_authority_did or ""
        if not (
            authority_did.startswith("did:key:z")
            and authority_did == authority_did.strip()
            and len(authority_did) <= 256
        ):
            raise RuntimeError(
                "independent temporal time-authority DID is malformed"
            )
        return (
            python,
            artifact_directory,
            artifact_sha,
            python_sha,
            authority,
            authority_sha,
            authority_did,
        )

    def require_runtime_writer_authority(self) -> tuple[Path, str, str]:
        """Return a complete runtime-only signer profile or fail closed."""

        missing = [
            name
            for name, value in (
                (
                    "LAKATOS_STORAGE_RUNTIME_WRITER_VERIFIER",
                    self.storage_runtime_writer_verifier,
                ),
                (
                    "LAKATOS_STORAGE_RUNTIME_WRITER_VERIFIER_SHA256",
                    self.storage_runtime_writer_verifier_sha256,
                ),
                (
                    "LAKATOS_STORAGE_RUNTIME_WRITER_PUBLIC_KEY_HEX",
                    self.storage_runtime_writer_public_key_hex,
                ),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                "runtime writer authority settings missing: " + ", ".join(missing)
            )
        path = Path(self.storage_runtime_writer_verifier or "")
        if not path.is_absolute():
            raise RuntimeError("runtime writer verifier path must be absolute")
        verifier_sha = self.storage_runtime_writer_verifier_sha256 or ""
        public_key = self.storage_runtime_writer_public_key_hex or ""
        if any(
            len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)
            for value in (verifier_sha, public_key)
        ):
            raise RuntimeError("runtime writer authority pins are malformed")
        if (
            self.storage_fence_public_key_hex
            and hmac.compare_digest(public_key, self.storage_fence_public_key_hex)
        ):
            raise RuntimeError(
                "runtime writer and historical migration-fence keys must differ"
            )
        return path, verifier_sha, public_key

    def require_pg_runtime_profile(self) -> dict[str, str]:
        """Return the single strict production libpq profile used by all writes."""

        if any(key.startswith("PG") for key in os.environ):
            raise RuntimeError("PostgreSQL runtime ambient PG authority is present")
        if not self.pg_runtime_dsn:
            raise RuntimeError(
                "PostgreSQL runtime settings missing: "
                "LAKATOS_STORAGE_PG_RUNTIME_DSN"
            )
        if not self.pg_runtime_ca_sha256 or not (
            len(self.pg_runtime_ca_sha256) == 64
            and all(char in "0123456789abcdef" for char in self.pg_runtime_ca_sha256)
        ):
            raise RuntimeError(
                "PostgreSQL runtime settings missing or invalid: "
                "LAKATOS_STORAGE_PG_RUNTIME_CA_SHA256"
            )
        try:
            import psycopg2

            parameters = dict(
                psycopg2.extensions.parse_dsn(self.pg_runtime_dsn)
            )
        except Exception as exc:  # noqa: BLE001 - never reflect a credential DSN
            raise RuntimeError("PostgreSQL runtime DSN is invalid") from exc
        required = {
            "host", "hostaddr", "port", "dbname", "user", "password",
            "sslmode", "sslrootcert", "channel_binding", "require_auth",
            "target_session_attrs", "gssencmode", "load_balance_hosts",
            "ssl_min_protocol_version", "ssl_max_protocol_version", "options",
        }
        if set(parameters) != required or any(
            not parameters.get(field) for field in required
        ):
            raise RuntimeError(
                "PostgreSQL runtime DSN does not have the exact strict field set"
            )
        try:
            host = ipaddress.ip_address(str(parameters["host"]))
            hostaddr = ipaddress.ip_address(str(parameters["hostaddr"]))
            port = int(str(parameters["port"]))
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                "PostgreSQL runtime host, hostaddr, or port is invalid"
            ) from exc
        try:
            configured_host = ipaddress.ip_address(self.pg_host)
        except ValueError as exc:
            raise RuntimeError(
                "PostgreSQL runtime pinned host must be a literal IP"
            ) from exc
        if not (
            host == hostaddr == configured_host
            and 1 <= port <= 65535
            and port == self.pg_port
            and str(parameters["dbname"]) == self.pg_db
            and str(parameters["user"]) == self.pg_user
            and bool(self.pg_password)
            and hmac.compare_digest(
                str(parameters["password"]), self.pg_password
            )
        ):
            raise RuntimeError(
                "PostgreSQL runtime DSN differs from the pinned target/profile"
            )
        exact_security = {
            "sslmode": "verify-full",
            "channel_binding": "require",
            "require_auth": "scram-sha-256",
            "target_session_attrs": "read-write",
            "gssencmode": "disable",
            "load_balance_hosts": "disable",
            "ssl_min_protocol_version": "TLSv1.2",
            "ssl_max_protocol_version": "TLSv1.3",
            "options": "-c search_path=pg_catalog",
        }
        if any(
            str(parameters.get(key)) != value
            for key, value in exact_security.items()
        ):
            raise RuntimeError(
                "PostgreSQL runtime DSN weakens transport or session posture"
            )
        root_path = Path(str(parameters["sslrootcert"]))
        _load_immutable_pinned_file(
            root_path, self.pg_runtime_ca_sha256
        )
        parameters.update({
            "application_name": "lakatotree-runtime",
            "connect_timeout": "5",
            "sslcertmode": "disable",
            "sslnegotiation": "postgres",
        })
        return parameters

    def pg_runtime_binding(self) -> dict[str, str]:
        """Digest the non-secret connection posture bound by access policy."""

        parameters = self.require_pg_runtime_profile()
        projection = {
            key: str(parameters[key])
            for key in (
                "host", "hostaddr", "port", "dbname", "user", "sslmode",
                "channel_binding", "require_auth", "target_session_attrs",
                "gssencmode", "load_balance_hosts", "ssl_min_protocol_version",
                "ssl_max_protocol_version", "options", "sslcertmode",
                "sslnegotiation", "application_name", "connect_timeout",
            )
        }
        raw = json.dumps(
            projection, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return {
            "profile_sha256": hashlib.sha256(raw).hexdigest(),
            "ca_sha256": self.pg_runtime_ca_sha256 or "",
        }

    def verify_pg_runtime_connection(self, connection: object) -> None:
        """Prove the live session still has the pinned runtime posture."""

        if not self.storage_access_requested:
            return
        # Re-open and re-hash the CA after libpq established the connection.
        # This prevents the import-time validated pathname from becoming a
        # long-lived trust-root bypass for later pool/lease connections.
        self.require_pg_runtime_profile()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_catalog.current_database(),current_user,session_user,"
                    "system_user,pg_catalog.current_setting('search_path'),"
                    "pg_catalog.current_setting('session_replication_role'),"
                    "pg_catalog.current_setting('transaction_read_only'),"
                    "pg_catalog.host(pg_catalog.inet_server_addr()),"
                    "pg_catalog.inet_server_port()"
                )
                session_row = cursor.fetchone()
                cursor.execute(
                    "SELECT ssl,version,cipher,bits FROM pg_catalog.pg_stat_ssl"
                    " WHERE pid=pg_catalog.pg_backend_pid()"
                )
                tls_row = cursor.fetchone()
        except Exception as exc:  # noqa: BLE001 - posture failure is one boundary
            raise RuntimeError(
                "PostgreSQL runtime session posture readback failed"
            ) from exc
        try:
            configured_ip = ipaddress.ip_address(self.pg_host)
            observed_ip = ipaddress.ip_address(str(session_row[7]))
        except (TypeError, ValueError, IndexError) as exc:
            raise RuntimeError(
                "PostgreSQL runtime session identity is malformed"
            ) from exc
        expected_system_user = f"scram-sha-256:{self.pg_user}"
        session_ok = (
            isinstance(session_row, tuple)
            and len(session_row) == 9
            and session_row[0] == self.pg_db
            and session_row[1] == self.pg_user
            and session_row[2] == self.pg_user
            and session_row[3] == expected_system_user
            and session_row[4] == "pg_catalog"
            and session_row[5] == "origin"
            and str(session_row[6]).lower() == "off"
            and observed_ip == configured_ip
            and session_row[8] == self.pg_port
        )
        tls_ok = (
            isinstance(tls_row, tuple)
            and len(tls_row) == 4
            and tls_row[0] is True
            and tls_row[1] in {"TLSv1.2", "TLSv1.3"}
            and isinstance(tls_row[2], str)
            and bool(tls_row[2])
            and type(tls_row[3]) is int
            and tls_row[3] >= 128
        )
        if not session_ok or not tls_ok:
            raise RuntimeError(
                "PostgreSQL runtime session differs from the pinned TLS/SCRAM posture"
            )

    def require_pg_migration_dsn(self) -> str:
        """Return the explicit migration DSN; parsing/pinning happens at connect."""

        missing = [
            name
            for name, value in (
                ("LAKATOS_STORAGE_PG_MIGRATION_DSN", self.pg_migration_dsn),
                ("LAKATOS_STORAGE_PG_MIGRATION_USER", self.pg_migration_user),
                (
                    "LAKATOS_STORAGE_PG_MIGRATION_PASSWORD",
                    self.pg_migration_password,
                ),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                "PostgreSQL migration settings missing: " + ", ".join(missing)
            )
        if self.pg_migration_user == self.pg_user:
            raise RuntimeError(
                "PostgreSQL migration and runtime principals must be distinct"
            )
        return self.pg_migration_dsn or ""

    def require_neo4j(self) -> tuple[str, str, str]:
        missing = [
            name
            for name, value in (
                ("NEO4J_URI", self.neo4j_uri),
                ("NEO4J_USER", self.neo4j_user),
                ("NEO4J_PASSWORD", self.neo4j_password),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(f"Neo4j settings missing: {', '.join(missing)}")
        uri = _require_pinned_neo4j_uri(
            self.neo4j_uri or "", setting="NEO4J_URI"
        )
        return uri, self.neo4j_user or "", self.neo4j_password or ""

    def require_neo4j_database(self) -> str:
        if not self.neo4j_database:
            raise RuntimeError("Neo4j settings missing: NEO4J_DATABASE")
        return self.neo4j_database

    def require_neo4j_migration(self) -> tuple[str, str, str]:
        """Return the recurring-migration Neo4j profile, never runtime creds."""

        if not self.neo4j_migration_uri:
            raise RuntimeError(
                "Neo4j migration settings missing: "
                "LAKATOS_STORAGE_NEO4J_MIGRATION_URI"
            )
        missing = [
            name
            for name, value in (
                (
                    "LAKATOS_STORAGE_NEO4J_MIGRATION_USER",
                    self.neo4j_migration_user,
                ),
                (
                    "LAKATOS_STORAGE_NEO4J_MIGRATION_PASSWORD",
                    self.neo4j_migration_password,
                ),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                "Neo4j migration settings missing: " + ", ".join(missing)
            )
        if self.neo4j_migration_user == self.neo4j_user:
            raise RuntimeError("Neo4j migration and runtime principals must be distinct")
        if self.neo4j_migration_uri != self.neo4j_uri:
            raise RuntimeError(
                "Neo4j migration and runtime profiles must target the exact same URI"
            )
        uri = _require_pinned_neo4j_uri(
            self.neo4j_migration_uri,
            setting="LAKATOS_STORAGE_NEO4J_MIGRATION_URI",
        )
        return (
            uri,
            self.neo4j_migration_user or "",
            self.neo4j_migration_password or "",
        )
