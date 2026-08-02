"""Atomic create-only contract for the tree POST surface."""

from __future__ import annotations

from copy import deepcopy

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.contexts.tree.api import create_tree_router
from server.contexts.tree.service import TreeService
from server.ports import KgTxGuardFailed


class _AtomicTreeTx:
    """Small Neo4j stand-in that applies the metadata MERGE as one transaction."""

    def __init__(self, trees: dict[str, dict] | None = None):
        self.trees = deepcopy(trees or {})
        self.calls: list[tuple[str, dict]] = []
        self.executed: list[tuple[str, dict]] = []
        self.outboxes: dict[str, dict] = {}

    def __call__(self, ops):
        batch = list(ops)
        self.calls.extend(batch)
        cypher, params = batch[0]
        self.executed.append(batch[0])

        name = params["tree"]
        created = name not in self.trees
        event_id = params["event_id"]
        prior = self.outboxes.get(event_id)
        if prior is not None:
            if (
                prior["tree"] == name
                and prior["request_sha256"] == params["request_sha256"]
                and prior["idempotency_key_sha256"]
                    == params["idempotency_key_sha256"]
                and prior["tree_incarnation_id"]
                    == self.trees.get(name, {}).get("tree_incarnation_id")
            ):
                raise KgTxGuardFailed(
                    "guarded first statement rejected: 'already_committed'",
                    actual="already_committed",
                    row={
                        "prior_generation": prior["tree_upsert_generation"],
                        "prior_payload": prior["payload"],
                        "prior_superseded": (
                            self.trees[name].get("last_tree_upsert_event_id")
                            != event_id
                        ),
                    },
                )
            raise KgTxGuardFailed("guarded first statement rejected: 'intent_conflict'")
        current_budget = self.trees.get(name, {}).get("cycle_budget")
        requested_budget = params.get("cycle_budget")
        if current_budget is not None and type(current_budget) is not int:
            raise KgTxGuardFailed("guarded first statement rejected: 'budget_corrupt'")
        if (
            type(requested_budget) is int
            and type(current_budget) is int
            and requested_budget > current_budget
        ):
            if not params.get("budget_raise_confirmed"):
                raise KgTxGuardFailed("guarded first statement rejected: 'budget_raise'")
            current_attestors = self.trees[name].get("attestor_dids") or []
            if current_attestors and (
                not params.get("budget_write_cert_verified")
                or current_attestors != params.get("budget_attestors_snapshot")
            ):
                raise KgTxGuardFailed("guarded first statement rejected: 'budget_cert'")
        if params.get("create_only") and not created:
            raise KgTxGuardFailed("guarded first statement rejected: 'already_exists'")
        if created:
            self.trees[name] = {
                "assurance_tier": params["declared_tier"] or params["default_tier"],
                "tree_incarnation_id": params["incarnation_id"],
                "tree_upsert_generation": 0,
            }
        else:
            self.trees[name].setdefault(
                "tree_incarnation_id", params["incarnation_id"]
            )

        metadata = next(p for _q, p in batch if "title" in p)
        generation = self.trees[name].get("tree_upsert_generation", 0) + 1
        self.trees[name].update({
            "title": metadata["title"],
            "hard_core": metadata["hard_core"],
            "frontier_rule": metadata["frontier_rule"],
            "doc": metadata["doc"],
            "coverage_status": metadata["coverage_status"],
            "last_tree_upsert_event_id": event_id,
            "tree_upsert_generation": generation,
        })
        if metadata.get("cycle_budget") is not None:
            self.trees[name]["cycle_budget"] = metadata["cycle_budget"]
        if metadata.get("attestor_dids") is not None:
            self.trees[name]["attestor_dids"] = metadata["attestor_dids"]
        self.outboxes[event_id] = {
            "tree": name,
            "payload": params["payload"],
            "request_sha256": params["request_sha256"],
            "idempotency_key_sha256": params["idempotency_key_sha256"],
            "tree_incarnation_id": self.trees[name]["tree_incarnation_id"],
            "tree_upsert_generation": generation,
        }
        self.executed.extend(batch[1:])

        return [[{
            "created": created,
            "assurance_tier": self.trees[name]["assurance_tier"],
            "guard_status": "ok",
        }], [{"tree_upsert_generation": generation}]] + [
            [] for _ in batch[2:]
        ]


def _client(tx: _AtomicTreeTx, history: list[tuple]) -> TestClient:
    service = TreeService(
        kg=lambda *_args, **_kwargs: [],
        kg_tx=tx,
        hist=lambda *args, **kwargs: history.append(args),
        pg=lambda: None,
    )
    app = FastAPI()
    app.include_router(create_tree_router(lambda: service))
    return TestClient(app)


def test_create_only_existing_tree_is_409_and_has_no_side_effects():
    original = {
        "OnlyOnce": {
            "title": "original",
            "hard_core": "original HC",
            "frontier_rule": "original FR",
            "doc": "original doc",
            "coverage_status": "unknown",
            "assurance_tier": "anchored",
        }
    }
    tx = _AtomicTreeTx(original)
    history: list[tuple] = []

    response = _client(tx, history).post(
        "/api/tree/OnlyOnce?create_only=true",
        json={"title": "replacement", "hard_core": "new HC", "frontier_rule": "new FR"},
    )

    assert response.status_code == 409
    assert tx.trees == original
    assert history == []
    assert len(tx.calls) == 4
    cypher, params = tx.calls[0]
    assert params["create_only"] is True
    assert "MERGE (t:LakatosTree" in cypher
    assert "$create_only" in cypher and "created" in cypher
    assert "coalesce(t._bundle_create_claim=$bundle_claim,false)" in cypher


def test_post_without_create_only_remains_last_write_wins_upsert():
    tx = _AtomicTreeTx({
        "Mutable": {
            "title": "old",
            "hard_core": "old HC",
            "frontier_rule": "old FR",
            "doc": "",
            "coverage_status": "unknown",
            "assurance_tier": "anchored",
        }
    })
    history: list[tuple] = []

    response = _client(tx, history).post(
        "/api/tree/Mutable",
        json={"title": "new", "hard_core": "new HC", "frontier_rule": "new FR"},
    )

    assert response.status_code == 200
    assert tx.trees["Mutable"]["title"] == "new"
    assert tx.calls[0][1]["create_only"] is False
    assert [entry[1] for entry in history] == ["tree_upsert"]


def test_create_only_claim_creates_absent_tree_once():
    tx = _AtomicTreeTx()
    history: list[tuple] = []

    response = _client(tx, history).post(
        "/api/tree/Fresh?create_only=true",
        json={"title": "fresh", "hard_core": "HC", "frontier_rule": "FR"},
    )

    assert response.status_code == 200
    assert tx.trees["Fresh"]["title"] == "fresh"
    assert tx.calls[0][1]["create_only"] is True
    assert [entry[1] for entry in history] == ["tree_upsert"]


def test_keyed_exact_retry_reuses_receipt_without_executing_bundle_again():
    tx = _AtomicTreeTx()
    history: list[tuple] = []
    client = _client(tx, history)
    headers = {"Idempotency-Key": "create-fresh-attempt-1"}
    body = {"title": "A", "hard_core": "HC", "frontier_rule": "FR"}

    first = client.post("/api/tree/Fresh", json=body, headers=headers)
    executed_after_first = len(tx.executed)
    second = client.post("/api/tree/Fresh", json=body, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["idempotent"] is True
    assert second.json()["tree_upsert_generation"] == 1
    assert len(tx.executed) == executed_after_first + 1
    assert len(tx.outboxes) == 1


def test_keyed_retry_reuses_committed_history_payload_after_policy_drift():
    tx = _AtomicTreeTx()
    writer = __import__(
        "server.contexts.tree.writer", fromlist=["TreeKgWriter"]
    ).TreeKgWriter(tx)
    first_payload = {
        "nodes": 0,
        "questions": 0,
        "tx_count": 1,
        "policy_warnings": ["old-policy-warning"],
    }
    changed_derived_payload = {
        "nodes": 0,
        "questions": 0,
        "tx_count": 1,
        "policy_warnings": ["new-policy-warning"],
    }

    first = writer.upsert_tree_bundle(
        name="T",
        metadata={"title": "A"},
        nodes=[],
        parent_edges_by_tag={},
        questions=[],
        history_payload=first_payload,
        idempotency_key="stable-key",
    )
    replay = writer.upsert_tree_bundle(
        name="T",
        metadata={"title": "A"},
        nodes=[],
        parent_edges_by_tag={},
        questions=[],
        history_payload=changed_derived_payload,
        idempotency_key="stable-key",
    )

    assert first.idempotent is False
    assert replay.idempotent is True
    assert replay.payload == first_payload


def test_key_reuse_with_different_semantic_request_is_conflict():
    tx = _AtomicTreeTx()
    client = _client(tx, [])
    headers = {"Idempotency-Key": "logical-operation-1"}

    assert client.post(
        "/api/tree/Mutable",
        json={"title": "A", "hard_core": "HC", "frontier_rule": "FR"},
        headers=headers,
    ).status_code == 200
    conflicting = client.post(
        "/api/tree/Mutable",
        json={"title": "B", "hard_core": "HC", "frontier_rule": "FR"},
        headers=headers,
    )

    assert conflicting.status_code == 409
    assert tx.trees["Mutable"]["title"] == "A"


def test_a_b_a_are_distinct_lww_operations_and_old_key_retry_never_clobbers_b():
    tx = _AtomicTreeTx()
    client = _client(tx, [])

    first_a = client.post(
        "/api/tree/Mutable",
        json={"title": "A", "hard_core": "HC", "frontier_rule": "FR"},
        headers={"Idempotency-Key": "a-1"},
    )
    b = client.post(
        "/api/tree/Mutable",
        json={"title": "B", "hard_core": "HC", "frontier_rule": "FR"},
        headers={"Idempotency-Key": "b-1"},
    )
    stale_a_retry = client.post(
        "/api/tree/Mutable",
        json={"title": "A", "hard_core": "HC", "frontier_rule": "FR"},
        headers={"Idempotency-Key": "a-1"},
    )
    new_a = client.post(
        "/api/tree/Mutable",
        json={"title": "A", "hard_core": "HC", "frontier_rule": "FR"},
        headers={"Idempotency-Key": "a-2"},
    )

    assert first_a.status_code == b.status_code == 200
    assert stale_a_retry.status_code == 200
    assert stale_a_retry.json()["idempotent"] is True
    assert stale_a_retry.json()["superseded"] is True
    assert tx.trees["Mutable"]["title"] == "A"
    assert new_a.status_code == 200
    assert tx.trees["Mutable"]["tree_upsert_generation"] == 3


def test_keyed_create_only_retry_is_success_but_new_operation_is_conflict():
    tx = _AtomicTreeTx()
    client = _client(tx, [])
    body = {"title": "one", "hard_core": "HC", "frontier_rule": "FR"}

    assert client.post(
        "/api/tree/OnlyOnce?create_only=true",
        json=body,
        headers={"Idempotency-Key": "create-1"},
    ).status_code == 200
    retry = client.post(
        "/api/tree/OnlyOnce?create_only=true",
        json=body,
        headers={"Idempotency-Key": "create-1"},
    )
    second_operation = client.post(
        "/api/tree/OnlyOnce?create_only=true",
        json=body,
        headers={"Idempotency-Key": "create-2"},
    )

    assert retry.status_code == 200 and retry.json()["idempotent"] is True
    assert second_operation.status_code == 409


def test_budget_a_b_a_exact_retry_wins_before_current_raise_policy():
    tx = _AtomicTreeTx({
        "Budgeted": {
            "assurance_tier": "anchored",
            "cycle_budget": 5,
            "tree_incarnation_id": "inc-1",
        }
    })
    client = _client(tx, [])
    a_body = {
        "hard_core": "HC",
        "frontier_rule": "FR",
        "cycle_budget": 10,
        "confirm_budget_raise": True,
    }

    first_a = client.post(
        "/api/tree/Budgeted",
        json=a_body,
        headers={"Idempotency-Key": "budget-a"},
    )
    lower_b = client.post(
        "/api/tree/Budgeted",
        json={"hard_core": "HC", "frontier_rule": "FR", "cycle_budget": 3},
        headers={"Idempotency-Key": "budget-b"},
    )
    stale_a = client.post(
        "/api/tree/Budgeted",
        json=a_body,
        headers={"Idempotency-Key": "budget-a"},
    )

    assert first_a.status_code == lower_b.status_code == stale_a.status_code == 200
    assert stale_a.json()["idempotent"] is True
    assert stale_a.json()["superseded"] is True
    assert tx.trees["Budgeted"]["cycle_budget"] == 3


def test_locked_budget_state_rejects_stale_unconfirmed_raise():
    tx = _AtomicTreeTx({
        "Budgeted": {
            "assurance_tier": "anchored",
            "cycle_budget": 3,
            "tree_incarnation_id": "inc-1",
        }
    })
    response = _client(tx, []).post(
        "/api/tree/Budgeted",
        json={"hard_core": "HC", "frontier_rule": "FR", "cycle_budget": 5},
        headers={"Idempotency-Key": "stale-read"},
    )

    assert response.status_code == 409
    assert "confirm_budget_raise" in response.json()["detail"]
    assert tx.trees["Budgeted"]["cycle_budget"] == 3
    assert tx.outboxes == {}
