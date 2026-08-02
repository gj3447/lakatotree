"""V6 administrative verdict intents are atomic, replayable, and authority-bound."""

from __future__ import annotations

import contextlib
import copy
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock, RLock

import pytest
from fastapi import HTTPException

from lakatos.engine_identity import ENGINE_RULE_SHA
from lakatos.io.reconcile import canonical_history_payload
from lakatos.verdicts import (
    RECEIPT_FIELDS,
    receipt_content_sha,
    verdict_history_payload_sha,
)
from server.container import AppContainer
from server.contexts.tree.admin_intents import (
    AdminIntentError,
    validate_admin_verdict_intent,
)
from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import PredictionIn, VerdictIn
from server.storage_contract import _diagnose_neo_outbox_projection


TS = "2026-08-02T00:00:00+00:00"


def _receipt(*, tree, tag, verdict, source, previous, history_preimage):
    fields = {key: None for key in RECEIPT_FIELDS}
    fields.update(
        tree=tree,
        tag=tag,
        verdict=verdict,
        verdict_source=source,
        judged_at=TS,
        prev_receipt_sha=previous,
        engine_rule_sha=ENGINE_RULE_SHA,
        history_payload_sha256=verdict_history_payload_sha(history_preimage),
    )
    sha = receipt_content_sha(fields)
    return {"receipt_sha": sha, **fields}, {
        "tag": tag,
        "verdict": verdict,
        "verdict_source": source,
        "prev_receipt_sha": previous,
        "receipt_sha": sha,
    }


def _compound_fixture(*, demotion=True):
    request = VerdictIn(verdict="CANONICAL").model_dump()
    demoted_receipt = demoted_effect = demoted_current = None
    if demotion:
        demoted_summary = {
            "tag": "old",
            "verdict": "former_canonical",
            "verdict_source": "engine",
            "prev_receipt_sha": None,
        }
        demoted_receipt, demoted_effect = _receipt(
            tree="T",
            tag="old",
            verdict="former_canonical",
            source="engine",
            previous=None,
            history_preimage=demoted_summary,
        )
        demoted_current = {
            "tag": "old",
            "current_receipt_sha": demoted_effect["receipt_sha"],
            "verdict": "former_canonical",
            "verdict_source": "engine",
        }
    promoted_summary = {
        "tag": "new",
        "verdict": "CANONICAL",
        "verdict_source": "admin",
        "prev_receipt_sha": None,
    }
    promotion_preimage = {
        "request": request,
        "promoted": promoted_summary,
        "demoted": demoted_effect,
    }
    promoted_receipt, promoted_effect = _receipt(
        tree="T",
        tag="new",
        verdict="CANONICAL",
        source="admin",
        previous=None,
        history_preimage=promotion_preimage,
    )
    payload = {
        "request": request,
        "promoted": promoted_effect,
        "demoted": demoted_effect,
    }
    event_id = f"ob-verdict-{promoted_effect['receipt_sha']}"
    outbox = {
        "id": event_id,
        "tree": "T",
        "op": "verdict",
        "node_tag": "new",
        "payload": canonical_history_payload(payload),
        "status": "pending",
        "created_at": TS,
        "reason": "verdict_commit_intent",
        "applied_at": None,
        "adopted_by": None,
        "adopted_at": None,
        "receipt_sha": promoted_effect["receipt_sha"],
        "demoted_tag": demoted_effect["tag"] if demoted_effect else None,
        "demoted_receipt_sha": (
            demoted_effect["receipt_sha"] if demoted_effect else None
        ),
    }
    return {
        "tree": "T",
        "tag": "new",
        "receipt_sha": promoted_effect["receipt_sha"],
        "receipt": promoted_receipt,
        "current": {
            "current_receipt_sha": promoted_effect["receipt_sha"],
            "verdict": "CANONICAL",
            "verdict_source": "admin",
        },
        "outbox": outbox,
        "demoted_receipt": demoted_receipt,
        "demoted_current": demoted_current,
    }


def test_compound_promotion_and_demotion_validates_as_one_intent():
    fixture = _compound_fixture()
    payload = validate_admin_verdict_intent(**fixture)
    assert payload["promoted"]["tag"] == "new"
    assert payload["demoted"]["tag"] == "old"


def _admin_authority(fixture):
    return {
        "event_id": fixture["outbox"]["id"],
        "outbox": fixture["outbox"],
        "current_receipt_sha": fixture["current"]["current_receipt_sha"],
        "current_verdict": fixture["current"]["verdict"],
        "current_verdict_source": fixture["current"]["verdict_source"],
        "receipt": fixture["receipt"],
        "demoted_receipt": fixture["demoted_receipt"],
        "demoted_current": fixture["demoted_current"],
    }


def _admin_storage_report(fixture):
    entry = fixture["outbox"]
    return _diagnose_neo_outbox_projection(
        [],
        [{"id": entry["id"], "copies": 1}],
        [entry],
        admin_authority_rows=[_admin_authority(fixture)],
    )


def _receipt_graph_rows(fixture):
    scopes = [
        ("node-new", "new", fixture["current"], fixture["receipt"]),
    ]
    if fixture["demoted_receipt"] is not None:
        scopes.append((
            "node-old", "old", fixture["demoted_current"],
            fixture["demoted_receipt"],
        ))
    node_rows = []
    identity_rows = []
    for node_element_id, tag, current, receipt in scopes:
        receipt_element_id = f"receipt-{tag}"
        node_rows.append({
            "node_element_id": node_element_id,
            "tree": "T",
            "tag": tag,
            "current_receipt_sha": current["current_receipt_sha"],
            "pred_receipt_sha": None,
            "receipts": [{
                "receipt_element_id": receipt_element_id,
                "receipt": receipt,
            }],
        })
        identity_rows.append({
            "receipt_element_id": receipt_element_id,
            "receipt_sha": receipt["receipt_sha"],
            "receipt": receipt,
            "all_bindings": 1,
            "owners": [{
                "node_element_id": node_element_id,
                "tree": "T",
                "tag": tag,
            }],
        })
    return node_rows, identity_rows


def test_storage_audit_accepts_valid_pending_and_historical_admin_intents():
    pending = _compound_fixture()
    assert "neo4j.outbox.admin_intent" not in _admin_storage_report(
        pending
    )["failures"]

    historical = copy.deepcopy(pending)
    historical["outbox"]["status"] = "applied"
    historical["outbox"]["applied_at"] = TS
    historical["current"].update(
        current_receipt_sha="f" * 64,
        verdict="proof",
        verdict_source="scripted",
    )
    historical["demoted_current"].update(
        current_receipt_sha="e" * 64,
        verdict="refuted",
        verdict_source="scripted",
    )
    assert "neo4j.outbox.admin_intent" not in _admin_storage_report(
        historical
    )["failures"]


@pytest.mark.parametrize("tamper", ["promoted_digest", "demoted_digest", "pointer"])
def test_storage_audit_rejects_semantically_corrupt_admin_intent(tamper):
    fixture = copy.deepcopy(_compound_fixture())
    payload = json.loads(fixture["outbox"]["payload"])
    if tamper == "promoted_digest":
        payload["request"]["scope"] = "resealed-but-uncommitted"
        fixture["outbox"]["payload"] = canonical_history_payload(payload)
    elif tamper == "demoted_digest":
        fixture["demoted_receipt"]["history_payload_sha256"] = "f" * 64
        fields = {
            key: fixture["demoted_receipt"].get(key)
            for key in RECEIPT_FIELDS
        }
        new_sha = receipt_content_sha(fields)
        fixture["demoted_receipt"]["receipt_sha"] = new_sha
        payload["demoted"]["receipt_sha"] = new_sha
        fixture["outbox"]["payload"] = canonical_history_payload(payload)
        fixture["outbox"]["demoted_receipt_sha"] = new_sha
        fixture["demoted_current"]["current_receipt_sha"] = new_sha
    else:
        fixture["demoted_current"]["current_receipt_sha"] = "0" * 64

    report = _admin_storage_report(fixture)
    assert "neo4j.outbox.admin_intent" in report["failures"]


@pytest.mark.parametrize(
    "tamper",
    ["request", "promoted", "demoted", "receipt", "timestamp"],
)
def test_compound_intent_rejects_any_unsealed_or_divergent_effect(tamper):
    fixture = copy.deepcopy(_compound_fixture())
    if tamper in {"request", "promoted", "demoted"}:
        payload = copy.deepcopy(json.loads(fixture["outbox"]["payload"]))
        if tamper == "request":
            payload["request"]["scope"] = "tampered"
        elif tamper == "promoted":
            payload["promoted"]["verdict"] = "proof"
        else:
            payload["demoted"]["tag"] = "somebody-else"
        fixture["outbox"]["payload"] = canonical_history_payload(payload)
    elif tamper == "receipt":
        fixture["receipt"]["history_payload_sha256"] = "0" * 64
    else:
        fixture["outbox"]["created_at"] = "2026-08-02T00:00:01+00:00"
    with pytest.raises(AdminIntentError):
        validate_admin_verdict_intent(**fixture)


class _LostAckKg:
    def __init__(self):
        self.current = {
            "verdict": None,
            "verdict_source": None,
            "node_state": None,
            "current_receipt_sha": None,
        }
        self.receipt = None
        self.outbox = None
        self.mutations = 0

    def __call__(self, query, **params):
        if "properties(o) AS outbox" in query:
            return [{
                "receipt_sha": self.current["current_receipt_sha"],
                "current_verdict": self.current["verdict"],
                "current_verdict_source": self.current["verdict_source"],
                "receipt": self.receipt,
                "outbox": self.outbox,
                "demoted_current": None,
                "demoted_receipt": None,
            }]
        if "reason:'verdict_commit_intent'" in query:
            self.mutations += 1
            fields = {key: None for key in RECEIPT_FIELDS}
            fields.update(
                tree=params["tree"],
                tag=params["tag"],
                verdict=params["verdict"],
                verdict_source="admin",
                judged_at=params["ts"],
                prev_receipt_sha=params["prev_rsha"],
                engine_rule_sha=params["engine_rule_sha"],
                history_payload_sha256=params["history_payload_sha256"],
            )
            self.receipt = {"receipt_sha": params["rsha"], **fields}
            self.outbox = {
                "id": params["history_event_id"],
                "tree": params["tree"],
                "op": "verdict",
                "node_tag": params["tag"],
                "payload": params["history_payload_json"],
                "status": "pending",
                "created_at": params["ts"],
                "reason": "verdict_commit_intent",
                "applied_at": None,
                "receipt_sha": params["rsha"],
                "demoted_tag": None,
                "demoted_receipt_sha": None,
            }
            self.current.update(
                verdict=params["verdict"],
                verdict_source="admin",
                node_state=params["node_state"],
                current_receipt_sha=params["rsha"],
            )
            return [{"tag": params["tag"]}]
        if "cycle_budget" in query:
            return [{"cycle_budget": None, "used": 0}]
        if "RETURN e.verdict AS verdict" in query and "pred_registered_at" in query:
            return [{
                "verdict": self.current["verdict"],
                "verdict_source": self.current["verdict_source"],
                "node_state": self.current["node_state"],
                "pred_registered_at": None,
                "judged_at": None,
                "metric_value": None,
                "prev_receipt_sha": self.current["current_receipt_sha"],
            }]
        return []


def test_history_lost_ack_retry_reuses_the_committed_admin_receipt():
    kg = _LostAckKg()
    projections = []

    def hist(*args, **kwargs):
        projections.append((args, kwargs))
        return False if len(projections) == 1 else True

    svc = JudgementService(
        kg=kg,
        kg_tx=lambda _ops: [],
        hist=hist,
        foundation=lambda *_args: None,
        reproducible_for_node=lambda *_args: None,
    )
    request = VerdictIn(verdict="proof")
    first = svc.set_verdict("T", "new", request)
    second = svc.set_verdict("T", "new", request)

    assert first == {"ok": True, "idempotent": False, "history_pending": True}
    assert second == {"ok": True, "idempotent": True, "history_pending": False}
    assert kg.mutations == 1
    assert projections[0][0][3] == projections[1][0][3]
    assert projections[0][1]["event_id"] == projections[1][1]["event_id"]


def test_different_admin_request_after_projection_mints_a_successor():
    kg = _LostAckKg()
    projections = []
    svc = JudgementService(
        kg=kg,
        kg_tx=lambda _ops: [],
        hist=lambda *args, **kwargs: projections.append((args, kwargs)) or True,
        foundation=lambda *_args: None,
        reproducible_for_node=lambda *_args: None,
    )

    first = svc.set_verdict("T", "new", VerdictIn(verdict="proof"))
    second = svc.set_verdict("T", "new", VerdictIn(verdict="superseded"))

    assert first["idempotent"] is False
    assert second["idempotent"] is False
    assert kg.mutations == 2
    assert kg.current["verdict"] == "superseded"
    assert projections[0][1]["event_id"] != projections[-1][1]["event_id"]


def test_different_admin_request_waits_for_prior_projection():
    kg = _LostAckKg()
    svc = JudgementService(
        kg=kg,
        kg_tx=lambda _ops: [],
        hist=lambda *_args, **_kwargs: False,
        foundation=lambda *_args: None,
        reproducible_for_node=lambda *_args: None,
    )

    first = svc.set_verdict("T", "new", VerdictIn(verdict="proof"))
    with pytest.raises(HTTPException) as exc:
        svc.set_verdict("T", "new", VerdictIn(verdict="superseded"))

    assert first["history_pending"] is True
    assert exc.value.status_code == 503
    assert kg.mutations == 1
    assert kg.current["verdict"] == "proof"


def test_scripted_v6_head_is_not_misclassified_as_admin_intent():
    kg = _LostAckKg()
    kg.current.update(
        verdict="progressive",
        verdict_source="scripted",
        node_state="TESTED",
        current_receipt_sha="a" * 64,
    )
    kg.receipt = {
        "receipt_sha": "a" * 64,
        "verdict_source": "scripted",
        "history_payload_sha256": "b" * 64,
    }
    svc = JudgementService(
        kg=kg,
        kg_tx=lambda _ops: [],
        hist=lambda *_args, **_kwargs: True,
        foundation=lambda *_args: None,
        reproducible_for_node=lambda *_args: None,
    )

    result = svc.set_verdict("T", "new", VerdictIn(verdict="proof"))

    assert result["idempotent"] is False
    assert kg.mutations == 1
    assert kg.current["verdict"] == "proof"


def test_ledger_scope_blocks_successor_until_prior_history_projection_finishes():
    kg = _LostAckKg()
    first_projection_entered = Event()
    release_first_projection = Event()
    second_started = Event()
    second_ready = Event()
    readiness_count = 0
    readiness_lock = Lock()
    history_count = 0

    def ready():
        nonlocal readiness_count
        with readiness_lock:
            readiness_count += 1
            if readiness_count == 2:
                second_ready.set()

    def hist(*_args, **_kwargs):
        nonlocal history_count
        history_count += 1
        if history_count == 1:
            first_projection_entered.set()
            assert release_first_projection.wait(2)
        return True

    scope_lock = RLock()
    svc = JudgementService(
        kg=kg,
        kg_tx=lambda _ops: [],
        hist=hist,
        foundation=lambda *_args: None,
        reproducible_for_node=lambda *_args: None,
        ledger_ready=ready,
        ledger_scope=lambda: scope_lock,
    )

    def successor():
        second_started.set()
        return svc.set_verdict(
            "T", "new", VerdictIn(verdict="superseded")
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            svc.set_verdict, "T", "new", VerdictIn(verdict="proof")
        )
        assert first_projection_entered.wait(2)
        second = pool.submit(successor)
        assert second_started.wait(2)
        assert second_ready.wait(0.1) is False
        assert kg.mutations == 1
        release_first_projection.set()
        assert first.result(timeout=2)["ok"] is True
        assert second.result(timeout=2)["ok"] is True

    assert kg.mutations == 2
    assert kg.current["verdict"] == "superseded"


class _PendingAdminPredecessorKg:
    def __init__(self, *, target):
        self.fixture = _compound_fixture()
        self.target = target
        self.mutations = 0

    def __call__(self, query, **params):
        fixture = self.fixture
        if "properties(head_receipt) AS head_receipt" in query:
            if self.target == "new":
                return [{
                    "head_receipt": fixture["receipt"],
                    "direct_outbox": fixture["outbox"],
                    "pending_predecessors": [],
                }]
            return [{
                "head_receipt": fixture["demoted_receipt"],
                "direct_outbox": None,
                "pending_predecessors": [fixture["outbox"]],
            }]
        if "properties(o) AS outbox" in query:
            return [_admin_authority(fixture)]
        if "RETURN o.status AS status" in query:
            return [{
                "status": fixture["outbox"]["status"],
                "applied_at": fixture["outbox"]["applied_at"],
            }]
        if "SET e.pred_metric" in query:
            self.mutations += 1
        return []


@pytest.mark.parametrize("target", ["new", "old"])
def test_pending_direct_and_compound_admin_predecessors_project_before_advance(target):
    kg = _PendingAdminPredecessorKg(target=target)
    projections = []

    def hist(*args, **kwargs):
        projections.append((args, kwargs))
        kg.fixture["outbox"].update(status="applied", applied_at=TS)
        return True

    svc = JudgementService(
        kg=kg,
        kg_tx=lambda _ops: [],
        hist=hist,
        foundation=lambda *_args: None,
        reproducible_for_node=lambda *_args: None,
    )

    svc._project_pending_admin_predecessors("T", target)

    assert len(projections) == 1
    assert projections[0][1]["event_id"] == kg.fixture["outbox"]["id"]
    assert kg.fixture["outbox"]["status"] == "applied"


@pytest.mark.parametrize("target", ["new", "old"])
def test_unprojected_admin_predecessor_blocks_prediction_before_domain_write(target):
    kg = _PendingAdminPredecessorKg(target=target)
    svc = JudgementService(
        kg=kg,
        kg_tx=lambda _ops: [],
        hist=lambda *_args, **_kwargs: False,
        foundation=lambda *_args: None,
        reproducible_for_node=lambda *_args: None,
    )

    with pytest.raises(HTTPException) as exc:
        svc.register_prediction(
            "T", target,
            PredictionIn(metric_name="m", baseline_value=1.0),
        )

    assert exc.value.status_code == 503
    assert kg.mutations == 0


def test_multiple_canonical_incumbents_fail_before_any_mutation():
    mutations = []

    def kg(query, **params):
        if "properties(o) AS outbox" in query:
            return []
        if "cycle_budget" in query:
            return [{"cycle_budget": None, "used": 0}]
        if "HAS_ARGUMENT" in query and "oldrecs" in query:
            return [{
                "verdict": "progressive",
                "verdict_source": "scripted",
                "node_state": "CANONICAL_CANDIDATE",
                "source_trust": "internal",
                "novel_confirmed": True,
                "qualitative_self_report": False,
                "author": None,
                "assurance_tier": None,
                "attestor_dids": None,
                "prev_receipt_sha": "2" * 64,
                "oldrecs": [
                    {"tag": "old-a", "prev": "a" * 64},
                    {"tag": "old-b", "prev": "b" * 64},
                ],
                "args": [],
            }]
        if "verdict_commit_intent" in query:
            mutations.append((query, params))
        return []

    svc = JudgementService(
        kg=kg,
        kg_tx=lambda _ops: [],
        hist=lambda *_args, **_kwargs: True,
        foundation=lambda *_args: None,
        reproducible_for_node=lambda *_args: None,
    )
    with pytest.raises(HTTPException) as exc:
        svc.set_verdict("T", "new", VerdictIn(verdict="CANONICAL"))
    assert exc.value.status_code == 500
    assert mutations == []


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def data(self):
        return self.rows


class _Session:
    def __init__(self, handler):
        self.handler = handler

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def run(self, query, **params):
        return _Result(self.handler(query, params))


class _Neo:
    def __init__(self, handler):
        self.handler = handler

    def session(self):
        return _Session(self.handler)


class _Cursor:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _Connection:
    def cursor(self):
        return _Cursor()


def test_reconciler_uses_current_admin_authority_not_stale_plan_payload():
    fixture = _compound_fixture()
    authority_outbox = fixture["outbox"]
    stale_plan = copy.deepcopy(authority_outbox)
    stale_plan["payload"] = canonical_history_payload({"stale": True})
    inserted = []
    applied = []

    def handler(query, _params):
        if "RETURN count(o) AS n" in query:
            return [{"n": 0}]
        if "OutboxEntry {status:'pending'}" in query:
            return [stale_plan]
        if "RETURN elementId(e) AS node_element_id" in query:
            return _receipt_graph_rows(fixture)[0]
        if "RETURN elementId(rec) AS receipt_element_id" in query:
            return _receipt_graph_rows(fixture)[1]
        if "UNWIND $ids AS event_id" in query:
            return [{
                "event_id": authority_outbox["id"],
                "outbox": authority_outbox,
                "current_receipt_sha": fixture["current"]["current_receipt_sha"],
                "current_verdict": fixture["current"]["verdict"],
                "current_verdict_source": fixture["current"]["verdict_source"],
                "receipt": fixture["receipt"],
                "demoted_current": fixture["demoted_current"],
                "demoted_receipt": fixture["demoted_receipt"],
            }]
        return []

    container = AppContainer(neo=_Neo(handler), mongo=object(), pg_kw={})

    @contextlib.contextmanager
    def pg():
        yield _Connection()

    container.pg = pg
    container._insert_history = lambda _cur, tree, op, tag, payload, event_id: (
        inserted.append((tree, op, tag, payload, event_id))
        or (None, event_id, event_id)
    )
    container._mark_outbox_applied = (
        lambda event_id, *_args: applied.append(event_id)
    )

    result = container.reconcile_outbox()

    assert result["ok"] is True
    assert inserted == [(
        "T", "verdict", "new", authority_outbox["payload"],
        authority_outbox["id"],
    )]
    assert applied == [authority_outbox["id"]]
