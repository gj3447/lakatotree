"""Runtime settings for the Lakatos server.

# KG: span_lakatotree_server_architecture
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from urllib.parse import urlsplit


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
        )

    @property
    def pg_kw(self) -> dict:
        return {
            "host": self.pg_host,
            "port": self.pg_port,
            "user": self.pg_user,
            "password": self.pg_password,
            "dbname": self.pg_db,
            "connect_timeout": 5,
        }

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
        parsed = urlsplit(self.neo4j_uri or "")
        if parsed.username is not None or parsed.password is not None:
            raise RuntimeError(
                "NEO4J_URI must not contain credentials; use NEO4J_USER and "
                "NEO4J_PASSWORD"
            )
        return self.neo4j_uri or "", self.neo4j_user or "", self.neo4j_password or ""

    def require_neo4j_database(self) -> str:
        if not self.neo4j_database:
            raise RuntimeError("Neo4j settings missing: NEO4J_DATABASE")
        return self.neo4j_database
