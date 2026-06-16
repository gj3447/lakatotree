"""Runtime settings for the Lakatos server.

# KG: span_lakatotree_server_architecture
"""

from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class ServerSettings:
    neo4j_uri: str | None
    neo4j_user: str | None
    neo4j_password: str | None
    pg_host: str
    pg_port: int
    pg_user: str
    pg_password: str
    pg_db: str
    mongo_uri: str

    @classmethod
    def from_env(cls) -> "ServerSettings":
        return cls(
            neo4j_uri=os.environ.get("NEO4J_URI"),
            neo4j_user=os.environ.get("NEO4J_USER"),
            neo4j_password=os.environ.get("NEO4J_PASSWORD"),
            pg_host=os.environ.get("LAKATOS_PG_HOST", "localhost"),
            pg_port=int(os.environ.get("LAKATOS_PG_PORT", "55100")),
            pg_user=os.environ.get("LAKATOS_PG_USER", "admin"),
            pg_password=os.environ.get("LAKATOS_PG_PASSWORD", ""),
            pg_db=os.environ.get("LAKATOS_PG_DB", "lakatos"),
            mongo_uri=os.environ.get("LAKATOS_MONGO_URI", "mongodb://localhost:27017"),
        )

    @property
    def pg_kw(self) -> dict:
        return {
            "host": self.pg_host,
            "port": self.pg_port,
            "user": self.pg_user,
            "password": self.pg_password,
            "dbname": self.pg_db,
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
        return self.neo4j_uri or "", self.neo4j_user or "", self.neo4j_password or ""
