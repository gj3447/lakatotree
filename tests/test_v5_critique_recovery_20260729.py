"""Recovery and contract-hardening tests for V5 critique ingestion."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")

from fastapi import HTTPException  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from server.contexts.tree.evidence_claim_service import EvidenceClaimService  # noqa: E402
from server.contexts.tree.schemas import CreateTreeIn, CritiqueIn  # noqa: E402
from server.contexts.tree.service import TreeService  # noqa: E402


class _RetryPort:
    """A persisted doubt whose first request crashed before standing reconciliation."""

    argument = {
        "id": "T/d1", "attacks": "n", "by": "alice",
        "kind": "doubt", "body": "question",
    }

    def __init__(self, integrity_row=None):
        self.integrity_row = integrity_row
        self.demoted = False
        self.queries = []

    def __call__(self, query, **params):
        self.queries.append(query)
        if "SET t._argument_cas" in query:
            if self.integrity_row is not None:
                return [{"tag": params.get("tag"), **self.integrity_row}]
            return [{
                "tag": params.get("tag"),
                "target_valid": True,
                "created": False,
                "idempotent": True,
                "existing_count": 1,
                "attacks": "n",
            }]
        if "RETURN e.verdict AS verdict" in query:
            return [{
                "verdict": "CANONICAL",
                "vur": True,
                "prev_receipt_sha": None,
                "args": [dict(self.argument)],
            }]
        if "standing_retracted_at" in query:
            self.demoted = True
            return [{"tag": params.get("tag")}]
        return []


def _service(port):
    history = []
    service = object.__new__(EvidenceClaimService)
    service.kg = port
    service.hist = lambda *args, **kwargs: history.append((args, kwargs))
    return service, history


def _critique():
    return CritiqueIn(
        arg_id="d1", attacks="n", by="alice", kind="doubt", body="question"
    )


def test_identical_retry_repairs_interrupted_standing_side_effect():
    port = _RetryPort()
    service, history = _service(port)

    out = service.add_critique("T", "n", _critique())

    assert out["idempotent"] is True
    assert out["standing"]["stands"] is False
    assert out["standing"]["demoted"] is True
    assert port.demoted is True
    assert [args[1] for args, _ in history] == ["standing_retraction"]


def test_argument_id_is_one_unambiguous_segment():
    with pytest.raises(ValidationError):
        CritiqueIn(arg_id="nested/d1", attacks="n")


def test_atomic_query_uses_domain_label_and_current_tree_target_namespace():
    port = _RetryPort()
    service, _ = _service(port)

    service.add_critique("T", "n", _critique())

    query = next(q for q in port.queries if "SET t._argument_cas" in q)
    assert "ON CREATE SET a:LakatosArgument" in query
    assert "a._argument_create_claim=$create_claim" in query
    assert "a.tree_name=$tree" in query and "a.local_id=$arg" in query
    assert "WHEN $attacks STARTS WITH $tree+'/'" in query


def test_new_tree_name_is_one_unambiguous_path_segment():
    service = TreeService(
        kg=lambda *args, **kwargs: [],
        kg_tx=lambda ops: pytest.fail("invalid name reached the writer"),
        hist=lambda *args, **kwargs: None,
        pg=lambda: None,
    )

    with pytest.raises(HTTPException) as exc:
        service.create_tree("nested/T", CreateTreeIn())

    assert exc.value.status_code == 422


@pytest.mark.parametrize(
    "row",
    [
        {"target_valid": "false", "created": False, "idempotent": False,
         "existing_count": 0, "attacks": None},
        {"target_valid": True, "created": True, "idempotent": False,
         "existing_count": 0, "attacks": "n"},
    ],
)
def test_inconsistent_integrity_result_fails_closed(row):
    service, history = _service(_RetryPort(integrity_row=row))

    with pytest.raises(HTTPException) as exc:
        service.add_critique("T", "n", _critique())

    assert exc.value.status_code == 500
    assert "integrity result inconsistent" in str(exc.value.detail)
    assert history == []
