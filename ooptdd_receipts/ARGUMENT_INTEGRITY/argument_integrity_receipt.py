"""Executable receipt for immutable, target-valid argument ingestion.

The adapter calls ``EvidenceClaimService.add_critique`` directly.  Setting
``LKT_ARGUMENT_INTEGRITY_INJECT=legacy-row`` makes the port return the old tag-only write
shape; the locked rejection requirements then turn RED, demonstrating that the receipt is
sensitive to removal of the integrity result contract.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")

from fastapi import HTTPException  # noqa: E402

from server.contexts.tree.evidence_claim_service import EvidenceClaimService  # noqa: E402
from server.contexts.tree.schemas import CritiqueIn  # noqa: E402


def _event(cid, name, **attrs):
    return {
        "cid": cid,
        "correlation_id": cid,
        "cycle_id": cid,
        "service": "lakatos.argument_integrity",
        "event": name,
        **attrs,
    }


class _Port:
    def __init__(self, existing=()):
        self.existing = {item["id"]: dict(item) for item in existing}
        self.queries = []

    def __call__(self, query, **params):
        self.queries.append(query)
        if "SET t._argument_cas" in query:
            if os.getenv("LKT_ARGUMENT_INTEGRITY_INJECT") == "legacy-row":
                return [{"tag": params["tag"]}]
            target_valid = (
                params["attacks"] == params["tag"]
                or f'{params["tree"]}/{params["attacks"]}' in self.existing
                or params["attacks"] in self.existing
            )
            normalized = (
                params["tag"] if params["attacks"] == params["tag"]
                else params["attacks"].rsplit("/", 1)[-1]
            ) if target_valid else None
            old = self.existing.get(params["arg_full"])
            same = bool(old) and all(
                old.get(key) == value
                for key, value in {
                    "by": params["by"],
                    "kind": params["kind"],
                    "body": params["body"],
                    "attacks": normalized,
                }.items()
            )
            created = target_valid and old is None
            if created:
                self.existing[params["arg_full"]] = {
                    "id": params["arg_full"],
                    "by": params["by"],
                    "kind": params["kind"],
                    "body": params["body"],
                    "attacks": normalized,
                }
            return [{
                "tag": params["tag"],
                "target_valid": target_valid,
                "created": created,
                "idempotent": same,
                "existing_count": int(params["arg_full"] in self.existing),
                "attacks": normalized,
            }]
        if "RETURN e.verdict AS verdict" in query:
            return [{
                "verdict": "proof",
                "vur": True,
                "prev_receipt_sha": None,
                "args": list(self.existing.values()),
            }]
        return []


def _service(port):
    history = []
    service = object.__new__(EvidenceClaimService)
    service.kg = port
    service.hist = lambda *args, **kwargs: history.append((args, kwargs))
    return service, history


def _status(call):
    try:
        return "ok", call()
    except HTTPException as exc:
        return str(exc.status_code), exc.detail


def verify(backend, cid):
    unknown_port = _Port(existing=[{
        "id": "T/d1", "attacks": "n", "by": "alice", "kind": "doubt", "body": "q"
    }])
    unknown, _ = _service(unknown_port)
    status, _ = _status(lambda: unknown.add_critique(
        "T", "n", CritiqueIn(arg_id="r1", attacks="typo", by="bob", body="r")
    ))
    assert status == "422", f"dangling attack accepted: {status}"
    backend.ship([_event(cid, "dangling_attack_rejected", status=422)])

    immutable_port = _Port(existing=[{
        "id": "T/d1", "attacks": "n", "by": "alice", "kind": "doubt", "body": "q"
    }])
    immutable, _ = _service(immutable_port)
    status, _ = _status(lambda: immutable.add_critique(
        "T", "n", CritiqueIn(
            arg_id="d1", attacks="n", by="mallory", kind="rebuttal", body="rewrite"
        )
    ))
    assert status == "409", f"argument overwrite accepted: {status}"
    backend.ship([_event(cid, "argument_overwrite_rejected", status=409)])

    retry_port = _Port(existing=[{
        "id": "T/d1", "attacks": "n", "by": "alice", "kind": "doubt", "body": "q"
    }])
    retry, history = _service(retry_port)
    status, result = _status(lambda: retry.add_critique(
        "T", "n", CritiqueIn(arg_id="d1", attacks="n", by="alice", kind="doubt", body="q")
    ))
    assert status == "ok" and result.get("idempotent") is True and history == []
    backend.ship([_event(cid, "identical_retry_idempotent", history_events=0)])

    create_port = _Port()
    create, _ = _service(create_port)
    status, _ = _status(lambda: create.add_critique(
        "T", "n", CritiqueIn(arg_id="d2", attacks="n", by="alice", body="new")
    ))
    assert status == "ok"
    query = next(q for q in create_port.queries if "SET t._argument_cas" in q)
    assert "preexisting_count=0" in query and "FOREACH" in query and "ON CREATE SET" in query
    backend.ship([_event(cid, "tree_locked_first_write", lock="t._argument_cas")])
    assert "a._argument_create_claim=$create_claim" in query
    assert "actual._argument_create_claim=$create_claim" in query
    assert "REMOVE actual._argument_create_claim" in query
    backend.ship([_event(cid, "create_claim_verified", token="transaction_owned")])
