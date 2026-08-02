"""Crash-window contracts for critique history projection."""
from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from lakatos.io.reconcile import history_event_id
from server.contexts.tree.evidence_claim_service import (
    EvidenceClaimService,
    normalize_critique_attack,
)
from server.contexts.tree.schemas import CritiqueIn


class _CritiquePort:
    def __init__(self):
        self.argument = None
        self.intent = None
        self.atomic_params = []

    def __call__(self, query, **params):
        if "a._argument_create_claim=$create_claim" in query:
            self.atomic_params.append((query, params))
            normalized = params["normalized_attacks"]
            current = {
                "id": params["arg_full"],
                "by": params["by"],
                "kind": params["kind"],
                "body": params["body"],
                "attacks": normalized,
            }
            created = self.argument is None
            idempotent = self.argument == current
            if created:
                self.argument = current
            if created or idempotent:
                self.intent = {
                    "id": params["history_event_id"],
                    "payload": params["history_payload_json"],
                }
            return [
                {
                    "tag": params["tag"],
                    "target_valid": True,
                    "created": created,
                    "idempotent": idempotent,
                    "existing_count": 1,
                    "attacks": normalized,
                    "intent_count": 1,
                    "intent_valid": True,
                }
            ]
        if "RETURN e.verdict AS verdict" in query:
            return [
                {
                    "verdict": "proof",
                    "vur": True,
                    "prev_receipt_sha": None,
                    "args": [dict(self.argument)],
                }
            ]
        return []


def _service(port, hist):
    service = object.__new__(EvidenceClaimService)
    service.kg = port
    service.hist = hist
    return service


def _critique():
    return CritiqueIn(
        arg_id="d1",
        attacks="T/root",
        by="검증자",
        kind="doubt",
        body="question",
    )


def test_history_event_id_binds_logical_identity_not_mutable_content():
    left = history_event_id("T", "critique", "T/d1")
    right = history_event_id("T", "critique", "T/d1")

    assert left == right
    assert left.startswith("he-") and len(left) == 67
    assert left != history_event_id("T", "critique", "T/d2")
    assert left != history_event_id("T2", "critique", "T/d1")


@pytest.mark.parametrize(
    ("tree", "tag", "raw", "normalized", "targets_node", "reference_valid"),
    [
        ("T", "T/root", "T/root", "T/root", True, True),
        ("T", "root", "root", "root", True, True),
        ("T", "root", "d1", "d1", False, True),
        ("T", "root", "T/d1", "d1", False, True),
        ("T", "root", "X/d1", "X/d1", False, False),
        ("T", "root", "T/a/b", "a/b", False, False),
    ],
)
def test_critique_attack_normalization_is_one_unambiguous_authority(
    tree, tag, raw, normalized, targets_node, reference_valid
):
    assert normalize_critique_attack(tree, tag, raw) == (
        normalized,
        targets_node,
        reference_valid,
    )


def test_argument_creation_and_pending_history_intent_share_one_cypher():
    port = _CritiquePort()
    calls = []
    service = _service(
        port, lambda *args, **kwargs: calls.append((args, kwargs))
    )

    service.add_critique("T", "root", _critique())

    query, params = port.atomic_params[0]
    assert "MERGE (o:OutboxEntry {id:$history_event_id, tree:$tree" in query
    assert "o.status='pending'" in query
    assert "STARTS WITH $tree" not in query
    assert "last(split" not in query
    assert calls[0][1]["event_id"] == params["history_event_id"]
    assert json.loads(params["history_payload_json"])["attacks"] == "root"


def test_slash_bearing_node_tag_commits_matching_argument_and_intent_payload():
    port = _CritiquePort()
    calls = []
    service = _service(port, lambda *args, **kwargs: calls.append((args, kwargs)))
    critique = CritiqueIn(
        arg_id="d1",
        attacks="T/root",
        by="검증자",
        kind="doubt",
        body="question",
    )

    out = service.add_critique("T", "T/root", critique)

    assert out["ok"] is True
    assert port.argument["attacks"] == "T/root"
    assert json.loads(port.intent["payload"])["attacks"] == "T/root"
    assert calls[0][0][3]["attacks"] == "T/root"


def test_retry_after_post_commit_history_crash_reuses_stable_event_id():
    port = _CritiquePort()
    first_event_ids = []

    def crash_after_domain_commit(*_args, **kwargs):
        first_event_ids.append(kwargs["event_id"])
        raise RuntimeError("simulated process death before history projection")

    with pytest.raises(RuntimeError, match="simulated process death"):
        _service(port, crash_after_domain_commit).add_critique(
            "T", "root", _critique()
        )

    repaired = []
    out = _service(
        port, lambda *args, **kwargs: repaired.append((args, kwargs))
    ).add_critique("T", "root", _critique())

    assert out["idempotent"] is True
    assert repaired[0][1]["event_id"] == first_event_ids[0]
    assert port.atomic_params[0][1]["history_event_id"] == first_event_ids[0]
    assert port.atomic_params[1][1]["history_event_id"] == first_event_ids[0]
    assert port.intent["id"] == first_event_ids[0]


def test_corrupt_preexisting_intent_fails_before_history_projection():
    class _CorruptIntentPort(_CritiquePort):
        def __call__(self, query, **params):
            if "a._argument_create_claim=$create_claim" in query:
                self.atomic_params.append((query, params))
                return [{
                    "tag": params["tag"],
                    "target_valid": True,
                    "created": False,
                    "idempotent": False,
                    "existing_count": 0,
                    "attacks": params["normalized_attacks"],
                    "intent_count": 1,
                    "intent_valid": False,
                }]
            return super().__call__(query, **params)

    projected = []
    port = _CorruptIntentPort()

    with pytest.raises(HTTPException) as exc:
        _service(
            port, lambda *args, **kwargs: projected.append((args, kwargs))
        ).add_critique("T", "root", _critique())

    assert exc.value.status_code == 500
    assert projected == []
    query, _ = port.atomic_params[0]
    assert "intent_prevalid" in query
    assert "(created OR idempotent) AND intent_prevalid" in query


@pytest.mark.parametrize("poison", ["nul\x00text", "lone-surrogate-\ud800"])
def test_postgresql_hostile_text_is_rejected_before_domain_commit(poison):
    port = _CritiquePort()
    projected = []
    critique = CritiqueIn(
        arg_id="d1", attacks="root", by="reviewer", kind="doubt", body=poison,
    )

    with pytest.raises(HTTPException) as exc:
        _service(
            port, lambda *args, **kwargs: projected.append((args, kwargs))
        ).add_critique("T", "root", critique)

    assert exc.value.status_code == 422
    assert port.atomic_params == []
    assert port.argument is None
    assert port.intent is None
    assert projected == []


def test_storage_readiness_gate_runs_before_any_critique_domain_mutation():
    port = _CritiquePort()
    service = _service(port, lambda *_args, **_kwargs: None)

    def blocked():
        raise HTTPException(503, "storage not verified")

    service.critique_ready = blocked
    with pytest.raises(HTTPException) as exc:
        service.add_critique("T", "root", _critique())
    assert exc.value.status_code == 503
    assert port.atomic_params == []
