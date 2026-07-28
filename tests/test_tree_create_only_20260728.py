"""Atomic create-only contract for the tree POST surface."""

from __future__ import annotations

from copy import deepcopy

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.contexts.tree.api import create_tree_router
from server.contexts.tree.service import TreeService


class _AtomicTreeTx:
    """Small Neo4j stand-in that applies the metadata MERGE as one transaction."""

    def __init__(self, trees: dict[str, dict] | None = None):
        self.trees = deepcopy(trees or {})
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, ops):
        assert len(ops) == 1
        cypher, params = ops[0]
        self.calls.append((cypher, params))

        name = params["tree"]
        created = name not in self.trees
        if created:
            self.trees[name] = {
                "assurance_tier": params["declared_tier"] or params["default_tier"],
            }

        # This models the required single-statement conditional update. A
        # create-only loser observes the existing row but changes no property.
        if created or not params.get("create_only", False):
            self.trees[name].update({
                "title": params["title"],
                "hard_core": params["hard_core"],
                "frontier_rule": params["frontier_rule"],
                "doc": params["doc"],
                "coverage_status": params["coverage_status"],
            })

        return [[{
            "created": created,
            "assurance_tier": self.trees[name]["assurance_tier"],
        }]]


def _client(tx: _AtomicTreeTx, history: list[tuple]) -> TestClient:
    service = TreeService(
        kg=lambda *_args, **_kwargs: [],
        kg_tx=tx,
        hist=lambda *args: history.append(args),
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
    assert len(tx.calls) == 1
    cypher, params = tx.calls[0]
    assert params["create_only"] is True
    assert "MERGE (t:LakatosTree" in cypher
    assert "$create_only" in cypher and "FOREACH" in cypher and "created" in cypher
    assert "coalesce(t._create_claim = $create_claim, false)" in cypher


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
