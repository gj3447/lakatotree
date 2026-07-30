"""ARG-1..5 L_IDE harness against disposable real Neo4j and PostgreSQL.

The tests call the production ``EvidenceClaimService.add_critique`` method.  Neo4j
observations and PostgreSQL history counts are read back independently; no fake port
reimplements target validity, immutability, idempotence, locking, or claim ownership.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Barrier
from uuid import uuid4

import pytest

# These values satisfy import-time configuration only.  The service below receives the
# testcontainers driver explicitly and never reads these endpoints.
os.environ.setdefault("NEO4J_URI", "bolt://argument-harness.invalid:7687")
os.environ.setdefault("NEO4J_USER", "unused")
os.environ.setdefault("NEO4J_PASSWORD", "unused")

from fastapi import HTTPException  # noqa: E402

from server.container import AppContainer  # noqa: E402
from server.contexts.tree.evidence_claim_service import EvidenceClaimService  # noqa: E402
from server.contexts.tree.schemas import CritiqueIn  # noqa: E402

pytestmark = pytest.mark.integration

_BARRIER_TIMEOUT = 15
_FUTURE_TIMEOUT = 60


class _BorrowedDriver:
    """Let AppContainer close its own PG pool without closing the session fixture driver."""

    def __init__(self, driver):
        self._driver = driver

    def session(self, *args, **kwargs):
        return self._driver.session(*args, **kwargs)

    def close(self):
        pass


class _DummyMongo:
    def close(self):
        pass


@dataclass
class _World:
    container: AppContainer
    tree: str

    def add_node(self, tag: str) -> None:
        self.container.kg(
            """MATCH (t:LakatosTree {name:$tree})
               CREATE (e:LakatosNode {
                 name:$node_name, tag:$tag, verdict:'proof', valid_until_rebutted:true
               })
               CREATE (t)-[:HAS_NODE]->(e)""",
            tree=self.tree,
            node_name=f"{self.tree}/{tag}",
            tag=tag,
        )

    def service(self) -> EvidenceClaimService:
        service = object.__new__(EvidenceClaimService)
        service.kg = self.container.kg
        service.hist = self.container.hist
        return service

    def history(self, tag: str) -> list[dict]:
        with self.container.pg() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT payload FROM history WHERE tree=%s AND op='critique' AND node_tag=%s "
                "ORDER BY id",
                (self.tree, tag),
            )
            return [row[0] for row in cursor.fetchall()]

    def snapshot(self, arg_id: str) -> dict:
        full_id = f"{self.tree}/{arg_id}"
        argument_rows = self.container.kg(
            """MATCH (a:Argument {id:$id})
               RETURN collect({
                 id:a.id, by:a.by, kind:a.kind, body:a.body, attacks:a.attacks,
                 tree_name:a.tree_name, local_id:a.local_id, labels:labels(a),
                 claim:a._argument_create_claim
               }) AS arguments""",
            id=full_id,
        )
        relationship_rows = self.container.kg(
            """MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e)
               OPTIONAL MATCH (e)-[r:HAS_ARGUMENT]->(a:Argument {id:$id})
               RETURN count(r) AS relationship_count,
                      [x IN collect(DISTINCT CASE WHEN r IS NULL THEN null ELSE e.tag END)
                       WHERE x IS NOT NULL] AS linked_tags""",
            tree=self.tree,
            id=full_id,
        )
        tree_rows = self.container.kg(
            "MATCH (t:LakatosTree {name:$tree}) "
            "RETURN t._argument_cas AS argument_cas",
            tree=self.tree,
        )
        arguments = argument_rows[0]["arguments"]
        return {
            "argument_count": len(arguments),
            "arguments": arguments,
            "relationship_count": relationship_rows[0]["relationship_count"],
            "linked_tags": relationship_rows[0]["linked_tags"],
            "claim_leaks": sum(item["claim"] is not None for item in arguments),
            "argument_cas": tree_rows[0]["argument_cas"],
        }


@pytest.fixture
def argument_world(neo4j_driver, pg_kw):
    tree = f"ARGUMENT_IT_{uuid4().hex}"
    container = AppContainer(
        neo=_BorrowedDriver(neo4j_driver),
        mongo=_DummyMongo(),
        pg_kw=pg_kw,
    )
    container.kg(
        "CREATE CONSTRAINT lkt_argument_id_unique IF NOT EXISTS "
        "FOR (n:LakatosArgument) REQUIRE n.id IS UNIQUE"
    )
    container.kg("CREATE (t:LakatosTree {name:$tree})", tree=tree)
    world = _World(container=container, tree=tree)
    world.add_node("n")
    try:
        yield world
    finally:
        with container.pg() as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM history WHERE tree=%s", (tree,))
        container.kg(
            "MATCH (a:Argument) WHERE a.id STARTS WITH $prefix DETACH DELETE a",
            prefix=f"{tree}/",
        )
        container.kg("MATCH (t:LakatosTree {name:$tree}) DETACH DELETE t", tree=tree)
        container.close()


def _critique(*, arg_id="d1", attacks="n", by="alice", kind="doubt", body="question"):
    return CritiqueIn(arg_id=arg_id, attacks=attacks, by=by, kind=kind, body=body)


def _status(call) -> tuple[str, dict | str]:
    try:
        return "ok", call()
    except HTTPException as exc:
        return str(exc.status_code), str(exc.detail)


def _race(world: _World, tag_and_payload: tuple[tuple[str, CritiqueIn], ...]):
    barrier = Barrier(len(tag_and_payload), timeout=_BARRIER_TIMEOUT)

    def attempt(item):
        tag, payload = item
        barrier.wait()
        status, result = _status(lambda: world.service().add_critique(world.tree, tag, payload))
        return {"status": status, "result": result, "tag": tag, "payload": payload}

    with ThreadPoolExecutor(max_workers=len(tag_and_payload)) as pool:
        futures = [pool.submit(attempt, item) for item in tag_and_payload]
        return [future.result(timeout=_FUTURE_TIMEOUT) for future in futures]


def test_arg_1_dangling_target_is_rejected_without_side_effects(argument_world):
    status, detail = _status(
        lambda: argument_world.service().add_critique(
            argument_world.tree,
            "n",
            _critique(arg_id="dangling", attacks="missing"),
        )
    )

    assert status == "422" and "attacks" in detail
    assert argument_world.snapshot("dangling") == {
        "argument_count": 0,
        "arguments": [],
        "relationship_count": 0,
        "linked_tags": [],
        "claim_leaks": 0,
        "argument_cas": 0,
    }
    assert argument_world.history("n") == []


def test_arg_2_argument_identity_is_immutable(argument_world):
    original = _critique(arg_id="immutable", body="first")
    assert argument_world.service().add_critique(argument_world.tree, "n", original)["ok"]

    status, detail = _status(
        lambda: argument_world.service().add_critique(
            argument_world.tree,
            "n",
            _critique(
                arg_id="immutable",
                by="mallory",
                kind="rebuttal",
                body="replacement",
            ),
        )
    )

    assert status == "409" and "immutable" in detail.lower()
    snapshot = argument_world.snapshot("immutable")
    assert snapshot["argument_count"] == 1
    assert snapshot["relationship_count"] == 1
    assert snapshot["claim_leaks"] == 0
    stored = snapshot["arguments"][0]
    assert {key: stored[key] for key in (
        "id", "by", "kind", "body", "attacks", "tree_name", "local_id", "claim"
    )} == {
        "id": f"{argument_world.tree}/immutable",
        "by": "alice",
        "kind": "doubt",
        "body": "first",
        "attacks": "n",
        "tree_name": argument_world.tree,
        "local_id": "immutable",
        "claim": None,
    }
    assert "LakatosArgument" in stored["labels"]
    assert len(argument_world.history("n")) == 1


def test_arg_3_exact_retry_is_idempotent_without_duplicate_history(argument_world):
    payload = _critique(arg_id="retry")
    first = argument_world.service().add_critique(argument_world.tree, "n", payload)
    second = argument_world.service().add_critique(argument_world.tree, "n", payload)

    assert first["ok"] is True
    assert second["ok"] is True and second["idempotent"] is True
    snapshot = argument_world.snapshot("retry")
    assert snapshot["argument_count"] == 1
    assert snapshot["relationship_count"] == 1
    assert snapshot["claim_leaks"] == 0
    assert len(argument_world.history("n")) == 1


def test_arg_4_tree_lock_serializes_cross_node_identity_race(argument_world):
    argument_world.add_node("other")
    left = _critique(arg_id="contended", attacks="n", by="alice", body="left")
    right = _critique(arg_id="contended", attacks="other", by="bob", body="right")

    outcomes = _race(argument_world, (("n", left), ("other", right)))

    assert sorted(item["status"] for item in outcomes) == ["409", "ok"]
    winner = next(item for item in outcomes if item["status"] == "ok")
    snapshot = argument_world.snapshot("contended")
    stored = snapshot["arguments"][0]
    assert snapshot["argument_count"] == 1
    assert snapshot["relationship_count"] == 1
    assert snapshot["linked_tags"] == [winner["tag"]]
    assert snapshot["argument_cas"] == 0
    assert snapshot["claim_leaks"] == 0
    assert (stored["by"], stored["kind"], stored["body"], stored["attacks"]) == (
        winner["payload"].by,
        winner["payload"].kind,
        winner["payload"].body,
        winner["payload"].attacks,
    )
    assert sum(len(argument_world.history(tag)) for tag in ("n", "other")) == 1


def test_arg_5_create_claim_has_one_owner_and_does_not_leak(argument_world):
    payload = _critique(arg_id="same-request", body="same")

    outcomes = _race(argument_world, (("n", payload), ("n", payload)))

    assert [item["status"] for item in outcomes].count("ok") == 2
    assert sum(
        isinstance(item["result"], dict) and item["result"].get("idempotent") is True
        for item in outcomes
    ) == 1
    snapshot = argument_world.snapshot("same-request")
    assert snapshot["argument_count"] == 1
    assert snapshot["relationship_count"] == 1
    assert snapshot["linked_tags"] == ["n"]
    assert snapshot["claim_leaks"] == 0
    assert "LakatosArgument" in snapshot["arguments"][0]["labels"]
    assert len(argument_world.history("n")) == 1
    constraints = argument_world.container.kg(
        "SHOW CONSTRAINTS YIELD name WHERE name=$name RETURN count(*) AS n",
        name="lkt_argument_id_unique",
    )
    assert constraints == [{"n": 1}]
