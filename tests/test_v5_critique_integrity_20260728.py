"""V5 argument-pipeline integrity guards.

An attack must target the node verdict or an argument already attached to the
same node.  Argument identities are immutable: an exact retry is an idempotent
no-op, while reusing an id with different content is a conflict.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")

from fastapi import HTTPException  # noqa: E402

from server.contexts.tree.evidence_claim_service import EvidenceClaimService  # noqa: E402
from server.contexts.tree.schemas import CritiqueIn  # noqa: E402


class _Kg:
    """One tree node plus its current immutable arguments."""

    def __init__(self, existing=()):
        self.existing = {a["id"]: dict(a) for a in existing}
        self.written = []
        self.queries = []

    def __call__(self, query, **params):
        self.queries.append(query)
        if "RETURN e.tag AS tag, collect" in query:
            return [{"tag": params.get("tag"), "args": list(self.existing.values())}]
        if "RETURN e.verdict AS verdict" in query:
            return [{
                "verdict": "proof",
                "vur": True,
                "prev_receipt_sha": None,
                "args": list(self.existing.values()),
            }]
        if "SET t._argument_cas" in query:
            full_id = params["arg_full"]
            target_valid = (
                params["attacks"] == params["tag"]
                or f'{params["tree"]}/{params["attacks"]}' in self.existing
                or params["attacks"] in self.existing
            )
            normalized_attacks = (
                params["tag"] if params["attacks"] == params["tag"]
                else params["attacks"].rsplit("/", 1)[-1]
            ) if target_valid else None
            old = self.existing.get(full_id)
            idempotent = bool(old) and all(
                old.get(key) == value
                for key, value in {
                    "by": params["by"],
                    "kind": params["kind"],
                    "body": params["body"],
                    "attacks": normalized_attacks,
                }.items()
            )
            created = target_valid and old is None
            if created:
                stored = {
                    "id": full_id,
                    "by": params["by"],
                    "kind": params["kind"],
                    "body": params["body"],
                    "attacks": normalized_attacks,
                }
                self.existing[full_id] = stored
                self.written.append(stored)
            return [{
                "tag": params.get("tag"),
                "target_valid": target_valid,
                "created": created,
                "idempotent": idempotent,
                "existing_count": int(full_id in self.existing),
                "attacks": normalized_attacks,
            }]
        if "MERGE (a:Argument" in query:  # legacy query shape: useful failure signal
            self.written.append(params)
            return [{"tag": params.get("tag")}]
        return []


class _IncompleteResultKg(_Kg):
    """Simulate a stale/malformed port that omits the integrity verdict."""

    def __call__(self, query, **params):
        if "SET t._argument_cas" in query:
            self.queries.append(query)
            return [{"tag": params.get("tag")}]
        return super().__call__(query, **params)


def _service(kg):
    svc = object.__new__(EvidenceClaimService)
    svc.kg = kg
    svc.hist = lambda *args, **kwargs: None
    return svc


def _critique(arg_id="d1", attacks="n", by="alice", kind="doubt", body="question"):
    return CritiqueIn(arg_id=arg_id, attacks=attacks, by=by, kind=kind, body=body)


def test_attack_on_node_tag_is_accepted():
    kg = _Kg()
    out = _service(kg).add_critique("T", "n", _critique(attacks="n"))
    assert out["ok"] and kg.written
    atomic_query = next(q for q in kg.queries if "SET t._argument_cas" in q)
    assert "FOREACH" in atomic_query and "preexisting_count=0" in atomic_query


def test_attack_on_existing_argument_is_accepted():
    kg = _Kg(existing=[{"id": "T/d1", "attacks": "n", "by": "alice", "kind": "doubt"}])
    out = _service(kg).add_critique(
        "T", "n", _critique(arg_id="r1", attacks="d1", by="bob", kind="rebuttal")
    )
    assert out["ok"]


def test_attack_on_unknown_target_is_rejected_not_silent():
    kg = _Kg(existing=[{"id": "T/d1", "attacks": "n", "by": "alice", "kind": "doubt"}])
    with pytest.raises(HTTPException) as exc:
        _service(kg).add_critique(
            "T", "n", _critique(arg_id="r1", attacks="d1-typo", by="bob")
        )
    assert exc.value.status_code == 422
    assert "attacks" in str(exc.value.detail)


def test_existing_argument_is_immutable_across_actors():
    kg = _Kg(existing=[{
        "id": "T/d1",
        "attacks": "n",
        "by": "alice",
        "kind": "doubt",
        "body": "question",
    }])
    with pytest.raises(HTTPException) as exc:
        _service(kg).add_critique(
            "T",
            "n",
            _critique(
                arg_id="d1",
                attacks="n",
                by="mallory",
                kind="rebuttal",
                body="actually fine",
            ),
        )
    assert exc.value.status_code == 409
    assert "immutable" in str(exc.value.detail).lower()


def test_identical_reregistration_is_idempotent_without_history():
    same = {
        "id": "T/d1",
        "attacks": "n",
        "by": "alice",
        "kind": "doubt",
        "body": "question",
    }
    kg = _Kg(existing=[same])
    history = []
    svc = _service(kg)
    svc.hist = lambda *args, **kwargs: history.append((args, kwargs))

    out = svc.add_critique("T", "n", _critique())

    assert out["ok"] and out.get("idempotent") is True
    assert not kg.written
    assert history == []


def test_incomplete_integrity_result_fails_closed_without_history():
    kg = _IncompleteResultKg()
    history = []
    svc = _service(kg)
    svc.hist = lambda *args, **kwargs: history.append((args, kwargs))

    with pytest.raises(HTTPException) as exc:
        svc.add_critique("T", "n", _critique())

    assert exc.value.status_code == 500
    assert "integrity result incomplete" in str(exc.value.detail)
    assert history == []
