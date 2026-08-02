"""Autonomous recovery for the semantic side of durable critiques."""

from __future__ import annotations

from server.contexts.tree.evidence_claim_service import EvidenceClaimService


class _SemanticWorld:
    def __init__(self, *, verdict="CANONICAL", vur=True, demotion_succeeds=True):
        self.node = {
            "verdict": verdict,
            "node_state": "CANONICAL" if verdict == "CANONICAL" else verdict,
            "vur": vur,
            "prev_receipt_sha": "old-head",
            "args": [{"id": "T/d1", "attacks": "n", "by": "alice"}],
        }
        self.demotion_succeeds = demotion_succeeds
        self.demotions = []
        self.history = []

    def kg(self, query, **params):
        if "MATCH (t:LakatosTree)-[:HAS_NODE]->(e)" in query:
            if self.node["verdict"] in {"CANONICAL", "former_canonical"}:
                return [{"tree": "T", "tag": "n", **self.node}]
            return []
        if "WHERE e.verdict='former_canonical'" in query:
            if (
                self.node["verdict"] == "former_canonical"
                and self.node.get("node_state") == params["expected_state"]
            ):
                self.node["node_state"] = params["former_node_state"]
                return [{"tag": "n"}]
            return []
        if "RETURN e.verdict AS verdict" in query:
            return [{**self.node, "args": [dict(item) for item in self.node["args"]]}]
        if "MERGE (o:OutboxEntry {id:$event_id})" in query:
            self.demotions.append((query, dict(params)))
            if not self.demotion_succeeds:
                return []
            self.node["verdict"] = "former_canonical"
            self.node["node_state"] = params["former_node_state"]
            self.node["prev_receipt_sha"] = params["rsha"]
            return [{"tag": "n", "outbox_valid": True}]
        return []

    def hist(self, *args, **kwargs):
        self.history.append((args, kwargs))


def _service(world):
    return EvidenceClaimService(
        kg=world.kg,
        hist=world.hist,
        foundation=lambda _name: None,
        load_lineage=lambda: [],
        reproducible_for_node=lambda _name, _tag: None,
    )


def test_durable_argument_state_repairs_semantics_without_client_retry():
    world = _SemanticWorld()
    result = _service(world).reconcile_critique_standing()

    assert result["ok"] is True
    assert world.node["verdict"] == "former_canonical"
    assert world.node["node_state"] == "FORMER_CANONICAL"
    assert len(world.demotions) == 1
    query, params = world.demotions[0]
    assert "e.valid_until_rebutted" in query
    assert "{id:a.id, attacks:a.attacks, by:a.by}" in query
    assert params["exp_args"] == [
        {"id": "T/d1", "attacks": "n", "by": "alice"}
    ]
    assert "MERGE (rec:VerdictReceipt" in query
    assert "MERGE (o:OutboxEntry" in query
    assert "e.node_state=$former_node_state" in query
    assert len(world.history) == 1
    assert world.history[0][1]["event_id"].startswith("ob-standing-")

    second = _service(world).reconcile_critique_standing()
    assert second["ok"] is True
    assert len(world.demotions) == 1
    assert len(world.history) == 1


def test_cas_miss_with_remaining_violation_never_reports_green():
    world = _SemanticWorld(demotion_succeeds=False)
    result = _service(world).reconcile_critique_standing()

    assert result["ok"] is False
    assert result["failures"] == ["semantic.critique_standing"]
    assert result["violations"] == [{"tree": "T", "tag": "n"}]
    assert world.history == []


def test_human_lock_and_noncanonical_nodes_are_semantic_noops():
    for world in (
        _SemanticWorld(vur=False),
        _SemanticWorld(verdict="progressive", vur=True),
    ):
        result = _service(world).reconcile_critique_standing()
        assert result["ok"] is True
        assert world.demotions == []
        assert world.history == []


def test_malformed_valid_until_rebutted_fails_closed():
    world = _SemanticWorld(vur="true")

    result = _service(world).audit_critique_standing()

    assert result["ok"] is False
    assert result["failures"] == ["semantic.audit.HistoryPayloadError"]


def test_legacy_former_canonical_state_drift_is_repaired_before_green():
    world = _SemanticWorld(verdict="former_canonical")
    world.node["node_state"] = "CANONICAL"

    result = _service(world).reconcile_critique_standing()

    assert result["ok"] is True
    assert result["state_repaired"] == [{"tree": "T", "tag": "n"}]
    assert world.node["node_state"] == "FORMER_CANONICAL"
