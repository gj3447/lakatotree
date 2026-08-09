"""Atomic, expected-prestate structural-batch contract.

These tests are deliberately small and port-driven.  They pin the load-bearing
boundary: every graph mutation and its immutable outbox intents share one
``GuardedKgOps`` transaction, while PostgreSQL history remains a projection of
those already-committed intents.
"""

from __future__ import annotations

import hashlib
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from server.contexts.tree.api import create_tree_router
from server.contexts.tree.diagnostics import (
    STRUCTURAL_BATCH_REQUIRED_CONSTRAINTS,
    structural_batch_identity_audit_query,
)
from server.contexts.tree.schemas import (
    StructuralBatchCountsIn,
    StructuralBatchIn,
    StructuralExpectedStateIn,
    StructuralNodeIn,
    StructuralParentEdgeIn,
    StructuralQuestionIn,
)
from server.contexts.tree.service import TreeService
from server.contexts.tree.writer import (
    StructuralBatchIdempotencyConflict,
    StructuralConstraintUnavailable,
    StructuralInvariantFailure,
    StructuralOwnershipConflict,
    StructuralPrestateMismatch,
    TreeKgWriter,
    structural_batch_outbox_query,
    structural_batch_receipt_query,
    structural_batch_request_document,
    structural_state_query,
)
from lakatos.io.reconcile import validate_history_record
from server.ports import GuardedKgOps, KgTxGuardFailed


def _state(*, questions: int, revision: int) -> StructuralExpectedStateIn:
    return StructuralExpectedStateIn(
        tree_incarnation_id="incarnation-1",
        structural_revision=revision,
        state_sha256=("a" if revision == 0 else "b") * 64,
        counts=StructuralBatchCountsIn(
            nodes=1,
            questions=questions,
            foundations=0,
            elements=0,
            element_uses=0,
            parent_edges=0,
        ),
    )


def _command() -> StructuralBatchIn:
    return StructuralBatchIn(
        schema_version="lakatotree-structural-batch-command/v1",
        capability="structural:draft:additive:v1",
        batch_id="phase8-unit-batch",
        manifest_sha256="c" * 64,
        expected_prestate=_state(questions=0, revision=0),
        expected_post_counts=_state(questions=1, revision=1).counts,
        questions=[
            StructuralQuestionIn(qname="q-new", body="bounded open question")
        ],
    )


class _TripwireTx:
    """Managed transaction stand-in with an explicit first-guard outcome."""

    def __init__(self, *, outcome: str = "ok", row_mutator=None):
        self.outcome = outcome
        self.row_mutator = row_mutator
        self.calls: list[GuardedKgOps] = []

    @staticmethod
    def _receipt_row(batch: GuardedKgOps) -> dict:
        common = batch[0][1]
        final = batch[-1][1]
        prestate = json.loads(final["prestate_json"])
        post_counts = final["expected_post_counts"]
        post_authority = final["expected_authority"]
        events = json.loads(final["event_intents_json"])
        return {
            "created_at": final["ts"],
            "prestate_json": final["prestate_json"],
            "event_intents_json": final["event_intents_json"],
            "post_predictions": post_authority["predictions"],
            "post_progress_verdicts": post_authority["progress_verdicts"],
            "post_results": post_authority["results"],
            "post_verdict_receipts": post_authority["verdict_receipts"],
            "post_elements": post_counts["elements"],
            "post_element_uses": post_counts["element_uses"],
            "post_foundations": post_counts["foundations"],
            "post_nodes": post_counts["nodes"],
            "post_parent_edges": post_counts["parent_edges"],
            "post_questions": post_counts["questions"],
            "post_state_sha256": "b" * 64,
            "post_structural_revision": prestate["structural_revision"] + 1,
            "tree_incarnation_id": prestate["tree_incarnation_id"],
            "batch_id": common["batch_id"],
            "manifest_sha256": common["manifest_sha256"],
            "receipt_id": common["receipt_id"],
            "request_sha256": common["request_sha256"],
            "prior_outboxes": [
                {"event_id": event["event_id"], "created_at": final["ts"]}
                for event in events
            ],
        }

    def __call__(self, ops):
        assert isinstance(ops, GuardedKgOps)
        assert ops.guard_field == "guard_status"
        assert ops.guard_expected == "ok"
        batch = GuardedKgOps(ops, guard_field=ops.guard_field, guard_expected=ops.guard_expected)
        self.calls.append(batch)
        if self.outcome != "ok":
            row = self._receipt_row(batch) if self.outcome == "already_committed" else {}
            if row and self.row_mutator is not None:
                row = self.row_mutator(row)
            raise KgTxGuardFailed(
                f"guarded first statement rejected: {self.outcome!r}",
                actual=self.outcome,
                row=row,
            )

        final = self._receipt_row(batch)
        if self.row_mutator is not None:
            final = self.row_mutator(final)
        return [
            [{"guard_status": "ok", "tree_incarnation_id": "incarnation-1"}],
            [{"event_count": len(json.loads(final["event_intents_json"]))}],
            *([[]] * (len(batch) - 3)),
            [final],
        ]


def test_structural_batch_uses_one_guarded_managed_transaction():
    tx = _TripwireTx()
    result = TreeKgWriter(tx).apply_structural_batch(
        name="Tree",
        command=_command(),
        idempotency_key="phase8-unit-batch",
        constraints_ready=True,
    )

    assert len(tx.calls) == 1
    batch = tx.calls[0]
    assert batch.guard_expected == "ok"
    source = "\n".join(query for query, _params in batch)
    assert "StructuralBatchReceipt" in source
    assert "OutboxEntry" in source
    assert "OpenQuestion" in source
    assert "structural_revision" in source
    assert result.idempotent is False
    assert result.created_at == batch[-1][1]["ts"]
    assert batch[1][1]["ts"] == batch[-1][1]["ts"]
    assert result.summary.tx_count == 1
    assert [event["op"] for event in result.event_intents] == ["question_open"]


def test_stale_prestate_rejects_before_any_later_operation():
    tx = _TripwireTx(outcome="prestate_mismatch")

    with pytest.raises(StructuralPrestateMismatch):
        TreeKgWriter(tx).apply_structural_batch(
            name="Tree",
            command=_command(),
            idempotency_key="phase8-unit-batch",
            constraints_ready=True,
        )

    assert len(tx.calls) == 1
    assert isinstance(tx.calls[0], GuardedKgOps)
    # The adapter raises on the first guard; later statements are never run.
    assert tx.calls[0].guard_expected == "ok"


def test_exact_replay_returns_prior_receipt_without_second_domain_write():
    tx = _TripwireTx(outcome="already_committed")

    result = TreeKgWriter(tx).apply_structural_batch(
        name="Tree",
        command=_command(),
        idempotency_key="phase8-unit-batch",
        constraints_ready=True,
    )

    assert result.idempotent is True
    assert result.receipt_id.startswith("sbr-")
    assert len(tx.calls) == 1


def test_exact_replay_rejects_event_intent_bound_to_another_tree():
    def mutate(row):
        events = json.loads(row["event_intents_json"])
        events[0]["tree"] = "OtherTree"
        row["event_intents_json"] = json.dumps(
            events,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return row

    tx = _TripwireTx(outcome="already_committed", row_mutator=mutate)
    with pytest.raises(StructuralInvariantFailure):
        TreeKgWriter(tx).apply_structural_batch(
            name="Tree",
            command=_command(),
            idempotency_key="phase8-unit-batch",
            constraints_ready=True,
        )


@pytest.mark.parametrize(
    "created_at",
    ["2026-08-10T12:00:00", "2026-08-10T12:00:00Z", "not-a-time"],
)
def test_exact_replay_rejects_noncanonical_receipt_timestamp(created_at):
    def mutate(row):
        row["created_at"] = created_at
        return row

    with pytest.raises(StructuralInvariantFailure):
        TreeKgWriter(
            _TripwireTx(outcome="already_committed", row_mutator=mutate)
        ).apply_structural_batch(
            name="Tree",
            command=_command(),
            idempotency_key="phase8-unit-batch",
            constraints_ready=True,
        )


def test_exact_replay_rejects_outbox_timestamp_drift():
    def mutate(row):
        row["prior_outboxes"][0]["created_at"] = "2026-08-10T12:00:00+00:00"
        return row

    with pytest.raises(StructuralInvariantFailure):
        TreeKgWriter(
            _TripwireTx(outcome="already_committed", row_mutator=mutate)
        ).apply_structural_batch(
            name="Tree",
            command=_command(),
            idempotency_key="phase8-unit-batch",
            constraints_ready=True,
        )


def test_parent_edge_is_emitted_exactly_once_and_counted_logically():
    before = _state(questions=0, revision=0)
    command = StructuralBatchIn(
        schema_version="lakatotree-structural-batch-command/v1",
        capability="structural:draft:additive:v1",
        batch_id="phase8-parent-edge",
        manifest_sha256="d" * 64,
        expected_prestate=before,
        expected_post_counts=StructuralBatchCountsIn(
            **{
                **before.counts.model_dump(),
                "nodes": 2,
                "parent_edges": 1,
            }
        ),
        nodes=[
            StructuralNodeIn(
                tag="child",
                parent_edges=[
                    StructuralParentEdgeIn(
                        tag="existing",
                        relation_kind="bounded_dependency",
                        evidence_ref="git:test#C1",
                    )
                ],
            )
        ],
    )
    tx = _TripwireTx()

    result = TreeKgWriter(tx).apply_structural_batch(
        name="Tree",
        command=command,
        idempotency_key="phase8-parent-edge",
        constraints_ready=True,
    )

    parent_ops = [
        params
        for query, params in tx.calls[0]
        if "structural_batch_parent_edge_count_mismatch" in query
    ]
    assert len(parent_ops) == 1
    assert len(parent_ops[0]["rows"]) == 1
    assert parent_ops[0]["expected"] == 1
    assert result.summary.rows == 4  # node + edge + outbox intent + immutable receipt


@pytest.mark.parametrize(
    ("guard_state", "exception"),
    [
        ("idempotency_conflict", StructuralBatchIdempotencyConflict),
        ("ownership_conflict", StructuralOwnershipConflict),
    ],
)
def test_conflicting_batch_guards_fail_closed(guard_state, exception):
    with pytest.raises(exception):
        TreeKgWriter(_TripwireTx(outcome=guard_state)).apply_structural_batch(
            name="Tree",
            command=_command(),
            idempotency_key="phase8-unit-batch",
            constraints_ready=True,
        )


def test_structural_batch_refuses_to_enter_tx_without_constraint_evidence():
    tx = _TripwireTx()

    with pytest.raises(StructuralConstraintUnavailable):
        TreeKgWriter(tx).apply_structural_batch(
            name="Tree",
            command=_command(),
            idempotency_key="phase8-unit-batch",
        )

    assert tx.calls == []


def test_structural_batch_contract_forbids_unknown_fields_recursively():
    payload = _command().model_dump()
    payload["questions"][0]["scientific_verdict"] = "CONFIRMED"
    with pytest.raises(ValidationError):
        StructuralBatchIn.model_validate(payload)


class _RouteService:
    def structural_state(self, name: str):
        return {"tree": name, "state_sha256": "a" * 64}

    def structural_batch_status(self, name: str, batch_id: str):
        return {"tree": name, "batch_id": batch_id, "status": "GRAPH_COMMITTED"}

    def apply_structural_batch(self, name: str, command, *, idempotency_key: str):
        assert isinstance(command, StructuralBatchIn)
        assert idempotency_key == "phase8-unit-batch"
        return {"tree": name, "status": "APPLIED_HISTORY_PENDING"}


def _route_client() -> TestClient:
    app = FastAPI()
    app.include_router(create_tree_router(lambda: _RouteService()))
    return TestClient(app)


def test_structural_batch_http_requires_key_and_surfaces_pending_projection():
    client = _route_client()
    missing = client.post("/api/tree/Tree/structural-batch", json=_command().model_dump())
    assert missing.status_code == 422

    pending = client.post(
        "/api/tree/Tree/structural-batch",
        headers={"Idempotency-Key": "phase8-unit-batch"},
        json=_command().model_dump(),
    )
    assert pending.status_code == 202
    assert pending.json()["status"] == "APPLIED_HISTORY_PENDING"

    assert client.get("/api/tree/Tree/structural-state").status_code == 200
    assert client.get(
        "/api/tree/Tree/structural-batch/phase8-unit-batch"
    ).status_code == 200


def _canonical_json(value) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _ready_constraint_rows() -> list[dict]:
    return [
        {
            "name": spec.name,
            "type": "UNIQUENESS",
            "entityType": "NODE",
            "labelsOrTypes": [spec.label],
            "properties": list(spec.properties),
        }
        for spec in STRUCTURAL_BATCH_REQUIRED_CONSTRAINTS
    ]


def _ready_identity_rows() -> list[dict]:
    return [
        {"key": spec.key, "null_count": 0, "duplicate_keys": []}
        for spec in STRUCTURAL_BATCH_REQUIRED_CONSTRAINTS
    ]


def _structural_state_row() -> dict:
    authority = {
        "predictions": 0,
        "progress_verdicts": 0,
        "results": 0,
        "verdict_receipts": 0,
    }
    counts = _state(questions=0, revision=0).counts.model_dump()
    state = {
        "authority": authority,
        "elements": [],
        "element_uses": [],
        "foundations": [],
        "nodes": [{"name": "Tree/existing", "tag": "existing"}],
        "parent_edges": [],
        "question_links": [],
        "questions": [],
        "structural_revision": 0,
        "tree_incarnation_id": "incarnation-1",
    }
    state_json = _canonical_json(state)
    return {
        "tree": "Tree",
        "tree_incarnation_id": "incarnation-1",
        "structural_revision": 0,
        "structural_state": state,
        "structural_state_json": state_json,
        "state_sha256": hashlib.sha256(state_json.encode("utf-8")).hexdigest(),
        "counts": counts,
        "authority": authority,
    }


def _receipt_and_outbox_rows(*, pending: bool = False) -> tuple[list[dict], list[dict]]:
    tx = _TripwireTx()
    durable = TreeKgWriter(tx).apply_structural_batch(
        name="Tree",
        command=_command(),
        idempotency_key="phase8-unit-batch",
        constraints_ready=True,
    )
    receipt = _TripwireTx._receipt_row(tx.calls[0])
    receipt.update(
        {
            "receipt_tree": "Tree",
            "recorded_receipt_id": durable.receipt_id,
            "request_json": _canonical_json(
                structural_batch_request_document(
                    "Tree",
                    _command(),
                    "phase8-unit-batch",
                )
            ),
        }
    )
    outbox = []
    for event in durable.event_intents:
        outbox.append(
            {
                "adopted_at": None,
                "adopted_by": None,
                "applied_at": None if pending else durable.created_at,
                "created_at": durable.created_at,
                "event_id": event["event_id"],
                "node_tag": event["node_tag"],
                "op": event["op"],
                "payload": validate_history_record(
                    "Tree",
                    event["op"],
                    event["node_tag"],
                    event["payload"],
                    event["event_id"],
                ),
                "reason": "structural_batch_commit_intent",
                "request_sha256": durable.request_sha256,
                "status": "pending" if pending else "applied",
                "structural_batch_id": durable.batch_id,
                "tree": "Tree",
            }
        )
    return [receipt], outbox


class _KgDispatch:
    def __init__(
        self,
        *,
        constraint_rows=None,
        identity_rows=None,
        state_rows=None,
        receipt_rows=None,
        outbox_rows=None,
    ):
        self.constraint_rows = (
            _ready_constraint_rows()
            if constraint_rows is None
            else constraint_rows
        )
        self.identity_rows = (
            _ready_identity_rows() if identity_rows is None else identity_rows
        )
        self.state_rows = [_structural_state_row()] if state_rows is None else state_rows
        self.receipt_rows = [] if receipt_rows is None else receipt_rows
        self.outbox_rows = [] if outbox_rows is None else outbox_rows
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, query: str, **params):
        self.calls.append((query, params))
        if query == "SHOW CONSTRAINTS":
            return self.constraint_rows
        if query == structural_batch_identity_audit_query():
            return self.identity_rows
        if query == structural_state_query():
            return self.state_rows
        if query == structural_batch_receipt_query():
            return self.receipt_rows
        if query == structural_batch_outbox_query():
            return self.outbox_rows
        raise AssertionError(f"unexpected KG query: {query[:80]!r}")


def _actual_client(
    *,
    enabled: bool,
    hist_result=True,
    kg: _KgDispatch | None = None,
) -> tuple[TestClient, _TripwireTx, _KgDispatch, list[dict]]:
    tx = _TripwireTx()
    query = kg or _KgDispatch()
    history_calls: list[dict] = []

    def history(tree, op, node_tag, payload, *, event_id):
        history_calls.append(
            {
                "tree": tree,
                "op": op,
                "node_tag": node_tag,
                "payload": payload,
                "event_id": event_id,
            }
        )
        return hist_result

    service = TreeService(
        kg=query,
        kg_tx=tx,
        hist=history,
        pg=None,
        structural_batch_apply_enabled=enabled,
    )
    app = FastAPI()
    app.include_router(create_tree_router(lambda: service))
    return TestClient(app), tx, query, history_calls


def test_real_tree_service_keeps_structural_apply_dark_by_default():
    client, tx, kg, history = _actual_client(enabled=False)

    response = client.post(
        "/api/tree/Tree/structural-batch",
        headers={"Idempotency-Key": "phase8-unit-batch"},
        json=_command().model_dump(),
    )

    assert response.status_code == 503
    assert response.json()["detail"] == {"error": "structural_batch_apply_disabled"}
    assert kg.calls == []
    assert tx.calls == []
    assert history == []


@pytest.mark.parametrize(
    ("history_result", "expected_code", "expected_status"),
    [
        (True, 200, "APPLIED"),
        (False, 202, "APPLIED_HISTORY_PENDING"),
    ],
)
def test_real_tree_service_traverses_readiness_writer_and_history(
    history_result,
    expected_code,
    expected_status,
):
    client, tx, kg, history = _actual_client(
        enabled=True,
        hist_result=history_result,
    )

    response = client.post(
        "/api/tree/Tree/structural-batch",
        headers={"Idempotency-Key": "phase8-unit-batch"},
        json=_command().model_dump(),
    )

    assert response.status_code == expected_code
    assert response.json()["status"] == expected_status
    assert [query for query, _params in kg.calls] == [
        "SHOW CONSTRAINTS",
        structural_batch_identity_audit_query(),
    ]
    assert len(tx.calls) == 1
    assert len(history) == 1


def test_real_tree_service_refuses_unready_constraints_before_writer():
    client, tx, _kg, history = _actual_client(
        enabled=True,
        kg=_KgDispatch(constraint_rows=[]),
    )

    response = client.post(
        "/api/tree/Tree/structural-batch",
        headers={"Idempotency-Key": "phase8-unit-batch"},
        json=_command().model_dump(),
    )

    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "structural_batch_constraints_not_ready"
    assert tx.calls == []
    assert history == []


def test_real_tree_service_maps_malformed_readiness_to_503():
    client, tx, _kg, history = _actual_client(
        enabled=True,
        kg=_KgDispatch(constraint_rows=object()),
    )

    response = client.post(
        "/api/tree/Tree/structural-batch",
        headers={"Idempotency-Key": "phase8-unit-batch"},
        json=_command().model_dump(),
    )

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "error": "structural_batch_readiness_unavailable"
    }
    assert tx.calls == []
    assert history == []


def test_real_tree_service_structural_state_get_is_strict_and_read_only():
    client, tx, _kg, history = _actual_client(enabled=False)

    response = client.get("/api/tree/Tree/structural-state")

    assert response.status_code == 200
    assert response.json()["state_sha256"] == _structural_state_row()["state_sha256"]
    assert tx.calls == []
    assert history == []


@pytest.mark.parametrize(
    ("pending", "expected_status"),
    [(False, "APPLIED"), (True, "APPLIED_HISTORY_PENDING")],
)
def test_real_tree_service_status_binds_receipt_and_outbox(
    pending,
    expected_status,
):
    receipt_rows, outbox_rows = _receipt_and_outbox_rows(pending=pending)
    client, tx, _kg, history = _actual_client(
        enabled=False,
        kg=_KgDispatch(receipt_rows=receipt_rows, outbox_rows=outbox_rows),
    )

    response = client.get(
        "/api/tree/Tree/structural-batch/phase8-unit-batch"
    )

    assert response.status_code == 200
    assert response.json()["status"] == expected_status
    assert response.json()["created_at"] == receipt_rows[0]["created_at"]
    assert tx.calls == []
    assert history == []


def test_real_tree_service_status_rejects_outbox_timestamp_drift():
    receipt_rows, outbox_rows = _receipt_and_outbox_rows()
    outbox_rows[0]["created_at"] = "2026-08-10T12:00:00+00:00"
    client, _tx, _kg, _history = _actual_client(
        enabled=False,
        kg=_KgDispatch(receipt_rows=receipt_rows, outbox_rows=outbox_rows),
    )

    response = client.get(
        "/api/tree/Tree/structural-batch/phase8-unit-batch"
    )

    assert response.status_code == 500


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("created_at", "2026-08-10T12:00:00Z"),
        ("created_at", "2026-08-10T21:00:00+09:00"),
        ("applied_at", "2026-08-10T12:00:00Z"),
        ("applied_at", "2026-08-10T21:00:00+09:00"),
    ],
)
def test_real_tree_service_status_rejects_noncanonical_outbox_timestamps(
    field,
    value,
):
    receipt_rows, outbox_rows = _receipt_and_outbox_rows()
    outbox_rows[0][field] = value
    client, _tx, _kg, _history = _actual_client(
        enabled=False,
        kg=_KgDispatch(receipt_rows=receipt_rows, outbox_rows=outbox_rows),
    )

    response = client.get(
        "/api/tree/Tree/structural-batch/phase8-unit-batch"
    )

    assert response.status_code == 500


def test_real_tree_service_status_rejects_applied_time_before_creation():
    receipt_rows, outbox_rows = _receipt_and_outbox_rows()
    outbox_rows[0]["applied_at"] = "2000-01-01T00:00:00+00:00"
    client, _tx, _kg, _history = _actual_client(
        enabled=False,
        kg=_KgDispatch(receipt_rows=receipt_rows, outbox_rows=outbox_rows),
    )

    response = client.get(
        "/api/tree/Tree/structural-batch/phase8-unit-batch"
    )

    assert response.status_code == 500


def test_real_tree_service_status_accepts_applied_time_equal_to_creation():
    receipt_rows, outbox_rows = _receipt_and_outbox_rows()
    outbox_rows[0]["applied_at"] = outbox_rows[0]["created_at"]
    client, _tx, _kg, _history = _actual_client(
        enabled=False,
        kg=_KgDispatch(receipt_rows=receipt_rows, outbox_rows=outbox_rows),
    )

    response = client.get(
        "/api/tree/Tree/structural-batch/phase8-unit-batch"
    )

    assert response.status_code == 200
    assert response.json()["status"] == "APPLIED"


@pytest.mark.parametrize(
    "rows",
    [
        ["not-an-outbox-row"],
        [],
    ],
)
def test_real_tree_service_status_rejects_missing_or_malformed_outbox_set(rows):
    receipt_rows, _outbox_rows = _receipt_and_outbox_rows()
    client, _tx, _kg, _history = _actual_client(
        enabled=False,
        kg=_KgDispatch(receipt_rows=receipt_rows, outbox_rows=rows),
    )

    response = client.get(
        "/api/tree/Tree/structural-batch/phase8-unit-batch"
    )

    assert response.status_code == 500


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tree", "OtherTree"),
        ("op", "node_create"),
        ("node_tag", "other-tag"),
        ("reason", "wrong-reason"),
        ("request_sha256", "f" * 64),
        ("structural_batch_id", "other-batch"),
        ("status", "adopted"),
    ],
)
def test_real_tree_service_status_rejects_outbox_binding_drift(field, value):
    receipt_rows, outbox_rows = _receipt_and_outbox_rows()
    outbox_rows[0][field] = value
    client, _tx, _kg, _history = _actual_client(
        enabled=False,
        kg=_KgDispatch(receipt_rows=receipt_rows, outbox_rows=outbox_rows),
    )

    response = client.get(
        "/api/tree/Tree/structural-batch/phase8-unit-batch"
    )

    assert response.status_code == 500


def test_real_tree_service_status_rejects_duplicate_outbox_event():
    receipt_rows, outbox_rows = _receipt_and_outbox_rows()
    outbox_rows.append(dict(outbox_rows[0]))
    client, _tx, _kg, _history = _actual_client(
        enabled=False,
        kg=_KgDispatch(receipt_rows=receipt_rows, outbox_rows=outbox_rows),
    )

    response = client.get(
        "/api/tree/Tree/structural-batch/phase8-unit-batch"
    )

    assert response.status_code == 500
