"""Real-Neo4j proof that a poisoned same-id intent cannot partially register."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException

from server.container import AppContainer
from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import PredictionIn
from server.ports import GuardedKgOps


pytestmark = pytest.mark.integration


class _BorrowedDriver:
    def __init__(self, driver):
        self._driver = driver

    def session(self, *args, **kwargs):
        return self._driver.session(*args, **kwargs)

    def close(self):
        pass


class _DummyMongo:
    def close(self):
        pass


def test_poisoned_prediction_intent_rolls_back_domain_mutation(
    neo4j_driver, pg_kw,
):
    tree = f"PREDICTION_ATOMICITY_{uuid4().hex}"
    container = AppContainer(
        neo=_BorrowedDriver(neo4j_driver),
        mongo=_DummyMongo(),
        pg_kw=pg_kw,
    )
    container.kg(
        "CREATE CONSTRAINT lkt_outbox_id_unique IF NOT EXISTS "
        "FOR (n:OutboxEntry) REQUIRE n.id IS UNIQUE"
    )
    container.kg(
        "CREATE CONSTRAINT lkt_runtime_writer_lease_name_unique IF NOT EXISTS "
        "FOR (n:RuntimeWriterLease) REQUIRE n.name IS UNIQUE"
    )
    assert container.acquire_writer_lease() is True
    container.kg(
        "CREATE (t:LakatosTree {name:$tree})-[:HAS_NODE]->"
        "(e:LakatosNode {name:$node, tag:'n', node_state:'DRAFT'})",
        tree=tree,
        node=f"{tree}/n",
    )
    injected = False

    def poison_then_write(ops):
        nonlocal injected
        assert isinstance(ops, GuardedKgOps)
        operation = list(ops)
        assert len(operation) == 1
        params = operation[0][1]
        if not injected:
            injected = True
            container.kg(
                "CREATE (:OutboxEntry {"
                "id:$id, tree:$tree, op:'prediction_register', "
                "node_tag:$tag, payload:$payload, status:'pending', "
                "created_at:$ts, reason:'prediction_register_commit_intent', "
                "receipt_sha:$poison})",
                id=params["history_event_id"],
                tree=params["tree"],
                tag=params["tag"],
                payload=params["history_payload_json"],
                ts=params["ts"],
                poison="0" * 64,
            )
        return container.writer_fenced_kg_tx(ops)

    service = JudgementService(
        kg=container.kg,
        kg_tx=container.kg_tx,
        ledger_kg_tx=poison_then_write,
        ledger_ready=lambda: None,
        ledger_scope=container.writer_ledger_scope,
        hist=container.hist,
        foundation=lambda _tree: None,
        reproducible_for_node=lambda _tree, _tag: None,
    )
    try:
        with pytest.raises(HTTPException) as error:
            service.register_prediction(
                tree,
                "n",
                PredictionIn(metric_name="latency", baseline_value=10.0),
            )
        assert error.value.status_code == 409
        assert container.kg(
            "MATCH (:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:'n'}) "
            "RETURN e.pred_registered_at AS registered, "
            "e.pred_receipt_sha AS prediction, "
            "e.current_receipt_sha AS current",
            tree=tree,
        ) == [{"registered": None, "prediction": None, "current": None}]
        assert container.kg(
            "MATCH (r:VerdictReceipt {tree:$tree}) RETURN count(r) AS receipts",
            tree=tree,
        ) == [{"receipts": 0}]
    finally:
        try:
            container.kg(
                "MATCH (o:OutboxEntry {tree:$tree}) DETACH DELETE o",
                tree=tree,
            )
            container.kg(
                "MATCH (r:VerdictReceipt {tree:$tree}) DETACH DELETE r",
                tree=tree,
            )
            container.kg(
                "MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e) "
                "DETACH DELETE e",
                tree=tree,
            )
            container.kg(
                "MATCH (t:LakatosTree {name:$tree}) DETACH DELETE t",
                tree=tree,
            )
        finally:
            container.close()
