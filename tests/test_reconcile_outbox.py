"""B1 (override 2026-06-21): transactional-outbox + 멱등 reconcile 헤르메틱 검증.

hist(PG best-effort) 실패를 *조용히 잃지 않고* KG OutboxEntry(정본)에 기록 → reconcile_outbox 가 멱등
재적용(ON CONFLICT event_id). KG=truth/PG=best-effort 불변 유지하되 발산을 auditable 화. (실DB 영수증은
tests/integration/test_outbox_reconcile.py.)
"""
import contextlib
import hashlib
import json

import pytest
from psycopg2 import OperationalError as PgOperationalError

from lakatos.io.reconcile import (
    canonical_history_payload,
    history_event_id,
    outbox_id,
    plan_reconcile,
)
from lakatos.verdicts import (
    RECEIPT_FIELDS,
    receipt_content_sha,
    verdict_history_payload_sha,
)
from server.container import AppContainer
from server.contexts.tree.receipt_chain import (
    RECEIPT_CHAIN_ROWS_CYPHER,
    RECEIPT_IDENTITIES_CYPHER,
)
from server.contexts.tree.temporal_intents import (
    PREDICTION_TEMPORAL_IDENTITY_CYPHER,
)
from server.ports import HistoryEventConflict
from tests.test_temporal_intents import (
    _World,
    _attach_t1,
    _commitment_args,
    _graph_rows,
)


TS = "2026-08-02T00:00:00+00:00"


def _authorized_container(**kwargs):
    """Unit harness authority; fence mechanics are covered in test_container."""

    container = AppContainer(**kwargs)
    container.writer_fenced_kg_tx = container.kg_tx
    return container


def _critique_payload(arg_id="d1", attacks="n", body="same"):
    return {
        "arg_id": arg_id,
        "attacks": attacks,
        "by": "",
        "kind": "doubt",
        "body": body,
    }


def _outbox_row(event_id, tree, op, tag, payload, **overrides):
    row = {
        "id": event_id, "tree": tree, "op": op, "node_tag": tag,
        "payload": payload, "status": "pending", "created_at": TS,
        "reason": "critique_commit_intent" if event_id and event_id.startswith("he-")
        else "PgOperationalError",
        "applied_at": None, "adopted_by": None, "adopted_at": None,
    }
    row.update(overrides)
    return row


# ── 순수 로직 ────────────────────────────────────────────────────────────────
def test_outbox_id_deterministic_and_ts_sensitive():
    a = outbox_id('t', 'op', 'n', {'x': 1}, '2026-06-21T01:00:00')
    assert a == outbox_id('t', 'op', 'n', {'x': 1}, '2026-06-21T01:00:00')   # 결정적(중복 pending 방지)
    assert a != outbox_id('t', 'op', 'n', {'x': 1}, '2026-06-21T02:00:00')   # 다른 시점 구분
    assert a.startswith('ob-')


def test_plan_reconcile_skips_already_applied():
    pending = [{'id': 'a'}, {'id': 'b'}, {'id': 'c'}]
    p = plan_reconcile(pending, applied_ids={'b'})
    assert [e['id'] for e in p['to_replay']] == ['a', 'c']     # 멱등: 적용분 건너뜀
    assert p['already_applied'] == ['b'] and p['pending_total'] == 3 and p['replay_count'] == 2


# ── container 통합(가짜 neo/pg) ──────────────────────────────────────────────
class _Res:
    def __init__(self, rows): self._rows = rows
    def data(self): return self._rows


class _Sess:
    def __init__(self, handler, log): self._h, self._log = handler, log
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def run(self, cypher, **kw):
        self._log.append((cypher, kw))
        rows = self._h(cypher, kw)
        if not rows and "RETURN guard_status" in cypher:
            rows = [{"guard_status": "create"}]
        return _Res(rows)
    def execute_write(self, fn): return fn(self)


class _Neo:
    def __init__(self, handler, log): self._h, self._log = handler, log
    def session(self): return _Sess(self._h, self._log)
    def close(self): pass


class _Cur:
    def __init__(self, log, row=(True,), fetchalls=None, fetchones=None):
        self._log, self._row = log, row
        self._fetchalls = list(fetchalls or [])
        self._fetchones = list(fetchones or [])
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, sql, params=None): self._log.append((sql, params))
    def fetchone(self):
        return self._fetchones.pop(0) if self._fetchones else self._row
    def fetchall(self):
        return self._fetchalls.pop(0) if self._fetchalls else []


class _Conn:
    def __init__(self, log, row=(True,), fetchalls=None, fetchones=None):
        self._log, self._row = log, row
        self._fetchalls, self._fetchones = fetchalls, fetchones
    def cursor(self):
        return _Cur(
            self._log,
            self._row,
            fetchalls=self._fetchalls,
            fetchones=self._fetchones,
        )


def _successful_mark_result(cypher, params, *, tree, op, tag, payload):
    if "AS exact_bindings" in cypher:
        return [{"arguments": 1, "owners": 1, "exact_bindings": 1}]
    if "WHERE o.id IN $ids" in cypher:
        return [
            _outbox_row(event_id, tree, op, tag, payload)
            for event_id in params["ids"]
        ]
    if "UNWIND $expected AS exp" in cypher:
        return [{
            "prevalid": True,
            "argument_valid": True,
            "postvalid": True,
            "ids": [row["id"] for row in params["expected"]],
        }]
    return None


def test_hist_records_outbox_entry_on_pg_failure():
    """PG 다운 시 hist 가 이력을 잃지 않고 KG OutboxEntry(pending)로 기록."""
    neolog = []
    def handler(cypher, params):
        if "MERGE (o:OutboxEntry" in cypher:
            return [_outbox_row(
                params["id"], params["tree"], params["op"], params["tag"],
                params["payload"], reason=params["reason"], created_at=params["ts"],
            )]
        return []
    c = _authorized_container(neo=_Neo(handler, neolog), mongo=object(), pg_kw={})

    @contextlib.contextmanager
    def _down():
        raise PgOperationalError('pg down')
        yield  # noqa: unreachable
    c.pg = _down
    c.hist('T', 'test_result', 'v', {'verdict': 'progressive'})
    merges = [cy for cy, _ in neolog if 'OutboxEntry' in cy]
    assert any('MERGE (o:OutboxEntry' in cypher for cypher in merges)  # 유실 대신 outbox 기록
    assert any("status='pending'" in cy for cy in merges)


def test_reconcile_outbox_replays_pending_with_idempotent_upsert():
    """pending OutboxEntry 를 PG 에 ON CONFLICT 재적용 + applied 표기(재실행 시 skip=멱등)."""
    neolog, pglog = [], []

    def handler(cypher, kw):
        if "RETURN count(o) AS n" in cypher:
            return [{"n": 0}]
        if "OutboxEntry {status:'pending'}" in cypher:
            return [_outbox_row(
                'ob-1', 'T', 'node_add', 'v', '{"verdict":"progressive"}'
            )]
        marked = _successful_mark_result(
            cypher,
            kw,
            tree="T",
            op="node_add",
            tag="v",
            payload='{"verdict":"progressive"}',
        )
        if marked is not None:
            return marked
        return []
    c = _authorized_container(neo=_Neo(handler, neolog), mongo=object(), pg_kw={})

    @contextlib.contextmanager
    def _ok():
        yield _Conn(pglog)
    c.pg = _ok
    out = c.reconcile_outbox()
    assert out['replayed_count'] == 1 and out['replayed'] == ['ob-1'] and out['still_pending'] == 0
    inserts = [sql for sql, _ in pglog if 'INSERT INTO public.history' in sql]
    assert inserts and 'ON CONFLICT (event_id)' in inserts[0] and 'DO NOTHING' in inserts[0]   # 멱등 upsert
    assert any("status='applied'" in cy for cy, _ in neolog)               # outbox applied 표기


def _temporal_authority_row(world):
    args = _commitment_args(world, pending=True)
    counts = args["identity_counts"]
    return {
        **{key: value for key, value in counts.items()
           if key != "expected_label"},
        "event_id": args["outbox"]["id"],
        "outbox": args["outbox"],
        "tree_record": args["tree_record"],
        "node_record": args["node_record"],
        "adjunct_record": args["commitment_record"],
    }


def test_reconcile_temporal_commitment_uses_cryptographic_authority_snapshot():
    world = _World()
    _attach_t1(world)
    authority = _temporal_authority_row(world)
    pending = authority["outbox"]
    nodes, identities = _graph_rows(world)
    neolog, pglog = [], []

    def handler(cypher, params):
        if "RETURN count(o) AS n" in cypher:
            return [{"n": 0}]
        if "OutboxEntry {status:'pending'}" in cypher:
            return [pending]
        if cypher == PREDICTION_TEMPORAL_IDENTITY_CYPHER:
            return [authority]
        if cypher == RECEIPT_CHAIN_ROWS_CYPHER:
            return nodes
        if cypher == RECEIPT_IDENTITIES_CYPHER:
            return identities
        marked = _successful_mark_result(
            cypher, params,
            tree="T", op=pending["op"], tag="n", payload=pending["payload"],
        )
        return marked or []

    container = _authorized_container(
        neo=_Neo(handler, neolog), mongo=object(), pg_kw={}
    )

    @contextlib.contextmanager
    def _ok():
        yield _Conn(pglog)

    container.pg = _ok
    result = container.reconcile_outbox()

    assert result["replayed"] == [pending["id"]]
    assert result["conflicts"] == []


def test_malformed_temporal_namespace_never_falls_through_generic_replay():
    bad = _outbox_row(
        "ob-prediction-temporal-not-a-sha",
        "T",
        "node_add",
        "n",
        '{"x":1}',
    )
    generic = _outbox_row("ob-generic", "T", "node_add", "n", '{"x":2}')
    nodes, identities = [], []
    neolog, pglog = [], []

    def handler(cypher, params):
        if "RETURN count(o) AS n" in cypher:
            return [{"n": 1}]
        if "OutboxEntry {status:'pending'}" in cypher:
            return [bad, generic]
        if cypher == PREDICTION_TEMPORAL_IDENTITY_CYPHER:
            return []
        if cypher in {RECEIPT_CHAIN_ROWS_CYPHER, RECEIPT_IDENTITIES_CYPHER}:
            return nodes if cypher == RECEIPT_CHAIN_ROWS_CYPHER else identities
        marked = _successful_mark_result(
            cypher, params,
            tree="T", op="node_add", tag="n", payload=generic["payload"],
        )
        return marked or []

    container = _authorized_container(
        neo=_Neo(handler, neolog), mongo=object(), pg_kw={}
    )

    @contextlib.contextmanager
    def _ok():
        yield _Conn(pglog)

    container.pg = _ok
    result = container.reconcile_outbox()

    assert result["replayed"] == [generic["id"]]
    assert [item["id"] for item in result["conflicts"]] == [bad["id"]]


def _causal_verdict_fixture(*, include_close=True):
    cycle_request = ["T", {
        "baseline": 0.0,
        "metric_name": "m",
        "tag": "n",
    }]
    claim = hashlib.sha256(json.dumps(
        cycle_request,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()
    request_sha256 = "c" * 64
    test_summary = {
        "value": 1.0, "baseline": 0.0, "delta": 1.0,
        "verdict": "progressive", "script": "inline",
        "result_path": "/srv/result.json", "source_script_path": "/src/judge.py",
        "source_result_path": "/src/result.json", "result_sha256": "4" * 64,
        "measurement_lock_sha": "5" * 64, "novel": None,
        "script_sha": "3" * 64, "freshen": False,
        "replay_status": "verified",
        "replay_reason": "matched",
        "regenerated_metric": 1.0, "lakatos": "unverified",
        "metric_verdict": "progressive",
        "novel_server_anchored": False,
        "requires_human": False,
        "script_sha_server_verified": False,
        "rule": "improved", "attested_by": None,
        "cycle_claim": f"cycle-{claim}",
        "cycle_request_sha256": claim,
        "request_sha256": request_sha256,
        "verdict_display": "progressive@L2(replay_verified)",
        "assurance": {"val": 2, "basis": []},
        "qualitative_self_report": False,
        "replay_authoritative": True,
        "eureka_open": {
            "felt": False, "true": False, "hallucinated": False,
            "reasons": [], "bf": 0.0,
        },
        "eureka_closed": {
            "felt": False, "true": False, "hallucinated": False,
            "reasons": [], "bf": 0.0,
        },
    }
    receipt_fields = {
        "tree": "T", "tag": "n", "target_id": ("q" if include_close else None),
        "verdict": "progressive", "verdict_source": "scripted",
        "metric_name": "m", "metric_value": 1.0, "novel_confirmed": None,
        "lakatos_status": "unverified", "judged_at": TS,
        "judge_script_sha": "3" * 64, "prev_receipt_sha": None,
        "measurement_grade": "server_regenerated", "engine_rule_sha": None,
        "comment_sha": None, "replay_status": "verified",
        "replay_reason": "matched", "regenerated_metric": 1.0,
        "judge_script_path": "inline", "result_path": "/srv/result.json",
        "result_sha256": "4" * 64, "measurement_lock_sha": "5" * 64,
        "source_script_path": "/src/judge.py", "source_result_path": "/src/result.json",
        "history_payload_sha256": verdict_history_payload_sha(test_summary),
        "prediction_temporal_commitment_sha256": None,
    }
    receipt = receipt_content_sha(receipt_fields)
    test_id = f"ob-test-result-{receipt}"
    close_id = f"ob-question-close-{receipt}"
    cycle_id = f"ob-cycle-result-{claim}"
    dependencies = [test_id, *([close_id] if include_close else [])]
    rows = [
        _outbox_row(
            test_id, "T", "test_result", "n",
            canonical_history_payload({**test_summary, "receipt_sha": receipt}),
            reason="test_result_commit_intent",
            causal_group=receipt, causal_index=0, receipt_sha=receipt,
            request_sha256=request_sha256,
        ),
    ]
    if include_close:
        rows.append(_outbox_row(
            close_id, "T", "question_close", "n",
            canonical_history_payload({
                "question": "q", "receipt_sha": receipt,
                "trigger": "ADJUDICATED", "verdict": "progressive",
            }),
            reason="question_close_commit_intent",
            causal_group=receipt, causal_index=1, receipt_sha=receipt,
        ))
    rows.append(_outbox_row(
        cycle_id, "T", "cycle_result", "n",
        canonical_history_payload({
            "cycle_claim": f"cycle-{claim}",
            "cycle_request": cycle_request,
            "dependent_history_event_ids": dependencies,
            "result": {
                "delta": 1.0, "lakatos": "unverified", "novel": None,
                "novel_server_anchored": False,
                "verdict": "progressive",
            },
            "verdict_receipt_sha": receipt,
        }),
        reason="cycle_result_commit_intent",
        causal_group=receipt, causal_index=2, receipt_sha=receipt,
    ))
    authority = {
        "group": receipt,
        "current_tree": "T", "current_tag": "n",
        "current_receipt_sha": receipt,
        "current_verdict": "progressive",
        "current_verdict_source": "scripted",
        "current_lakatos_status": "unverified",
        "current_metric_value": 1.0,
        "bound_receipt_sha": receipt,
        **{f"receipt_{key}": receipt_fields[key] for key in RECEIPT_FIELDS},
        "question_state": ("CLOSED" if include_close else None),
        "question_closed_by": (["n"] if include_close else None),
        "question_closed_events": ([receipt] if include_close else None),
        "closure_id": (receipt if include_close else None),
        "closure_closed_by": ("n" if include_close else None),
        "closure_at": (TS if include_close else None),
        "closure_tree": ("T" if include_close else None),
        "closure_question": ("q" if include_close else None),
        "closure_trigger": ("ADJUDICATED" if include_close else None),
        "closure_verdict": ("progressive" if include_close else None),
        "closure_receipt_sha": (receipt if include_close else None),
        "closure_bound_count": (1 if include_close else 0),
        "closure_global_count": (1 if include_close else 0),
        "closes_rel_count": (1 if include_close else 0),
        "closes_rel_receipt_sha": (receipt if include_close else None),
        "closes_rel_verdict": (
            "progressive" if include_close else None
        ),
        "closes_rel_at": (TS if include_close else None),
    }
    return rows, authority


def _causal_receipt_graph(authority):
    receipt = {
        "receipt_sha": authority["bound_receipt_sha"],
        **{
            key: authority[f"receipt_{key}"]
            for key in RECEIPT_FIELDS
        },
    }
    node = {
        "node_element_id": "node-n",
        "tree": authority["current_tree"],
        "tag": authority["current_tag"],
        "current_receipt_sha": authority["current_receipt_sha"],
        "pred_receipt_sha": None,
        "receipts": [{
            "receipt_element_id": "receipt-n",
            "receipt": receipt,
        }],
    }
    identity = {
        "receipt_element_id": "receipt-n",
        "receipt_sha": receipt["receipt_sha"],
        "receipt": receipt,
        "all_bindings": 1,
        "owners": [{
            "node_element_id": "node-n",
            "tree": authority["current_tree"],
            "tag": authority["current_tag"],
        }],
    }
    return [node], [identity]


def test_reconcile_rejects_lone_cycle_with_missing_manifest_predecessor():
    fixture_rows, authority = _causal_verdict_fixture(include_close=False)
    rows = fixture_rows[-1:]
    pglog = []

    def handler(cypher, _params):
        if "RETURN count(o) AS n" in cypher:
            return [{"n": 1}]
        if "OutboxEntry {status:'pending'}" in cypher:
            return rows
        if "o.causal_group IN $groups" in cypher:
            return rows
        if "RETURN elementId(e) AS node_element_id" in cypher:
            return _causal_receipt_graph(authority)[0]
        if "RETURN elementId(rec) AS receipt_element_id" in cypher:
            return _causal_receipt_graph(authority)[1]
        if "UNWIND $groups AS group" in cypher:
            return [authority]
        return []

    c = _authorized_container(
        neo=_Neo(handler, []), mongo=object(), pg_kw={}
    )

    @contextlib.contextmanager
    def _pg_must_not_run():
        yield _Conn(pglog)

    c.pg = _pg_must_not_run
    out = c.reconcile_outbox()

    assert out["ok"] is False
    assert out["replayed"] == []
    assert rows[0]["id"] in out["causal_deferred"]
    assert "lacks test-result predecessor" in out["conflicts"][0]["error"]
    assert pglog == []


def test_reconcile_blocks_causal_successors_when_test_projection_conflicts():
    rows, authority = _causal_verdict_fixture(include_close=True)

    def handler(cypher, _params):
        if "RETURN count(o) AS n" in cypher:
            return [{"n": len(rows)}]
        if "OutboxEntry {status:'pending'}" in cypher:
            return rows
        if "o.causal_group IN $groups" in cypher:
            return rows
        if "RETURN elementId(e) AS node_element_id" in cypher:
            return _causal_receipt_graph(authority)[0]
        if "RETURN elementId(rec) AS receipt_element_id" in cypher:
            return _causal_receipt_graph(authority)[1]
        if "UNWIND $groups AS group" in cypher:
            return [authority]
        return []

    c = _authorized_container(
        neo=_Neo(handler, []), mongo=object(), pg_kw={}
    )

    @contextlib.contextmanager
    def _ok():
        yield _Conn([])

    c.pg = _ok

    def _conflict(*_args, **_kwargs):
        raise HistoryEventConflict("test projection conflict")

    c._insert_history = _conflict
    out = c.reconcile_outbox()

    assert out["replayed"] == []
    assert out["conflicts"][0]["id"] == rows[0]["id"]
    assert out["causal_deferred"] == [rows[1]["id"], rows[2]["id"]]


def test_reconcile_requires_causal_metadata_for_stable_new_intent_namespace():
    fixture_rows, _authority = _causal_verdict_fixture(include_close=False)
    row = fixture_rows[0]
    row.pop("causal_group")
    row.pop("causal_index")

    def handler(cypher, _params):
        if "RETURN count(o) AS n" in cypher:
            return [{"n": 1}]
        if "OutboxEntry {status:'pending'}" in cypher:
            return [row]
        return []

    c = _authorized_container(
        neo=_Neo(handler, []), mongo=object(), pg_kw={}
    )
    out = c.reconcile_outbox()

    assert out["replayed"] == []
    assert "malformed causal receipt binding" in out["conflicts"][0]["error"]


def test_reconcile_never_projects_unbound_prediction_intent():
    receipt_sha = "a" * 64
    event_id = f"ob-prediction-register-{receipt_sha}"
    row = _outbox_row(
        event_id,
        "T",
        "prediction_register",
        "n",
        canonical_history_payload({
            "metric_name": "forged",
            "direction": "lower",
            "baseline_value": 1.0,
        }),
        reason="prediction_register_commit_intent",
        receipt_sha=receipt_sha,
    )
    pglog = []

    def handler(cypher, _params):
        if "RETURN count(o) AS n" in cypher:
            return [{"n": 1}]
        if "OutboxEntry {status:'pending'}" in cypher:
            return [row]
        return []

    c = _authorized_container(
        neo=_Neo(handler, []), mongo=object(), pg_kw={}
    )

    @contextlib.contextmanager
    def _pg_must_not_run():
        yield _Conn(pglog)

    c.pg = _pg_must_not_run
    out = c.reconcile_outbox()

    assert out["replayed"] == []
    assert out["conflicts"][0]["id"] == event_id
    assert "prediction intent" in out["conflicts"][0]["error"]
    assert pglog == []


@pytest.mark.parametrize(
    "op",
    ["verdict", "prediction_register", "test_result", "question_close", "cycle_result"],
)
def test_reconcile_never_downgrades_protected_op_to_generic_intent(op):
    event_id = f"ob-legacy-{op.replace('_', '-')}"
    row = _outbox_row(event_id, "T", op, "n", '{}')
    pglog = []

    def handler(cypher, _params):
        if "RETURN count(o) AS n" in cypher:
            return [{"n": 1}]
        if "OutboxEntry {status:'pending'}" in cypher:
            return [row]
        return []

    container = _authorized_container(
        neo=_Neo(handler, []), mongo=object(), pg_kw={}
    )

    @contextlib.contextmanager
    def _pg_must_not_run():
        yield _Conn(pglog)

    container.pg = _pg_must_not_run
    result = container.reconcile_outbox()

    assert result["replayed"] == []
    assert result["conflicts"][0]["id"] == event_id
    assert pglog == []


def test_stable_history_insert_requires_exact_row_readback_before_applied():
    neolog, pglog = [], []
    payload = _critique_payload(body="x")
    event_id = history_event_id("T", "critique", "T/d1")
    payload_json = canonical_history_payload(payload)

    def handler(cypher, params):
        return _successful_mark_result(
            cypher,
            params,
            tree="T",
            op="critique",
            tag="n",
            payload=payload_json,
        ) or []

    c = _authorized_container(neo=_Neo(handler, neolog), mongo=object(), pg_kw={})

    @contextlib.contextmanager
    def _ok():
        yield _Conn(
            pglog,
            fetchalls=[
                [],
                [],
                [(7, event_id, True)],
                [(7, event_id, True)],
                [(7, event_id, True)],
            ],
        )

    c.pg = _ok
    c.hist('T', 'critique', 'n', payload, event_id=event_id)

    assert any('ON CONFLICT (event_id)' in sql for sql, _ in pglog)
    assert any('pg_advisory_xact_lock' in sql for sql, _ in pglog)
    assert any("payload->>'arg_id'=%s" in sql for sql, _ in pglog)
    assert any("status='applied'" in cy for cy, _ in neolog)


def test_stable_history_id_collision_fails_loud_without_marking_applied():
    neolog, pglog = [], []
    c = _authorized_container(neo=_Neo(lambda _cy, _kw: [], neolog), mongo=object(), pg_kw={})
    payload = _critique_payload(body="new")
    event_id = history_event_id("T", "critique", "T/d1")

    @contextlib.contextmanager
    def _conflict():
        yield _Conn(pglog, fetchalls=[[], [(7, event_id, False)]])

    c.pg = _conflict
    with pytest.raises(HistoryEventConflict):
        c.hist('T', 'critique', 'n', payload, event_id=event_id)

    assert not any("status='applied'" in cy for cy, _ in neolog)


@pytest.mark.parametrize("legacy_event_id", [None, "ob-legacy"])
def test_exact_legacy_critique_row_is_claimed_without_rewrite_or_duplicate(
    legacy_event_id,
):
    neolog, pglog = [], []
    payload = _critique_payload()
    event_id = history_event_id("T", "critique", "T/d1")
    payload_json = canonical_history_payload(payload)

    def handler(cypher, params):
        return _successful_mark_result(
            cypher,
            params,
            tree="T",
            op="critique",
            tag="n",
            payload=payload_json,
        ) or []

    c = _authorized_container(neo=_Neo(handler, neolog), mongo=object(), pg_kw={})

    @contextlib.contextmanager
    def _legacy():
        yield _Conn(
            pglog,
            fetchalls=[
                [],
                [(41, legacy_event_id, True)],
                [(41, legacy_event_id, True)],
                [(41, legacy_event_id, True)],
            ],
        )

    c.pg = _legacy
    c.hist('T', 'critique', 'n', payload, event_id=event_id)

    claims = [
        (sql, params)
        for sql, params in pglog
        if sql.startswith("INSERT INTO public.history_event_claims")
    ]
    assert len(claims) == 1
    assert claims[0][1] == (event_id, 41)
    assert not any(sql.startswith("UPDATE public.history") for sql, _ in pglog)
    assert not any(sql.startswith("INSERT INTO public.history(") for sql, _ in pglog)
    mark_params = next(
        params for cypher, params in neolog
        if "UNWIND $expected AS exp" in cypher
    )
    assert mark_params["stable_id"] == event_id
    assert {
        row["id"]: row["desired_status"] for row in mark_params["expected"]
    } == ({event_id: "applied", legacy_event_id: "adopted"}
          if legacy_event_id is not None else {event_id: "applied"})


def test_legacy_pending_critique_without_pg_row_materializes_stable_identity():
    pglog = []
    payload = _critique_payload()
    payload_json = canonical_history_payload(payload)
    stable_id = history_event_id("T", "critique", "T/d1")
    legacy_id = "ob-legacy"
    stable_row = [(7, stable_id, True)]
    cursor = _Cur(
        pglog,
        fetchalls=[[], [], stable_row, stable_row, stable_row],
    )

    projection = AppContainer._insert_history(
        cursor,
        "T",
        "critique",
        "n",
        payload_json,
        legacy_id,
    )

    history_insert = next(
        params
        for statement, params in pglog
        if statement.startswith("INSERT INTO public.history(")
    )
    assert history_insert[-1] == stable_id
    assert projection == (7, stable_id, stable_id)


def test_duplicate_legacy_critique_rows_fail_loud():
    neolog, pglog = [], []
    c = _authorized_container(neo=_Neo(lambda _cy, _kw: [], neolog), mongo=object(), pg_kw={})
    payload = _critique_payload()
    event_id = history_event_id("T", "critique", "T/d1")

    @contextlib.contextmanager
    def _duplicates():
        yield _Conn(
            pglog,
            fetchalls=[[], [(41, None, True), (42, "ob-old", True)]],
        )

    c.pg = _duplicates
    with pytest.raises(HistoryEventConflict):
        c.hist('T', 'critique', 'n', payload, event_id=event_id)

    assert not any(sql.startswith(("INSERT", "UPDATE")) for sql, _ in pglog)
    assert not any("status='applied'" in cy for cy, _ in neolog)


def test_legacy_and_stable_critique_projection_share_canonical_lock_set():
    payload = {"body": "same", "attacks": "n", "arg_id": "d1"}
    stable_id = history_event_id("T", "critique", "T/d1")
    old_log, stable_log = [], []
    legacy_row = [(41, "ob-old", True)]
    old_cur = _Cur(
        old_log,
        fetchalls=[[], legacy_row, legacy_row, legacy_row],
    )
    stable_cur = _Cur(
        stable_log,
        fetchalls=[legacy_row, legacy_row, legacy_row, legacy_row],
    )

    AppContainer._insert_history(
        old_cur,
        "T",
        "critique",
        "n",
        json.dumps(payload, ensure_ascii=False),
        "ob-old",
    )
    AppContainer._insert_history(
        stable_cur,
        "T",
        "critique",
        "n",
        canonical_history_payload(payload),
        stable_id,
    )

    old_locks = {
        params[0] for sql, params in old_log if "pg_advisory_xact_lock" in sql
    }
    stable_locks = {
        params[0] for sql, params in stable_log if "pg_advisory_xact_lock" in sql
    }
    assert stable_locks <= old_locks


def test_reconcile_reports_poison_entry_and_continues_independent_work():
    pending = [
        _outbox_row(
            "ob-bad", "T", "critique", "n",
            canonical_history_payload(_critique_payload(arg_id="bad")),
        ),
        _outbox_row("ob-good", "U", "node_add", "m", '{}'),
    ]
    neolog, applied = [], []

    def handler(cypher, _params):
        if "AS exact_bindings" in cypher:
            return [{"arguments": 1, "owners": 1, "exact_bindings": 1}]
        if "RETURN count(o) AS n" in cypher:
            return [{"n": 1}]
        if "OutboxEntry {status:'pending'}" in cypher:
            return pending
        return []

    c = _authorized_container(neo=_Neo(handler, neolog), mongo=object(), pg_kw={})

    @contextlib.contextmanager
    def _ok():
        yield _Conn([])

    def insert(_cur, _tree, _op, _tag, _payload, event_id):
        if event_id == "ob-bad":
            raise HistoryEventConflict("poison")
        return None, event_id, event_id

    c.pg = _ok
    c._insert_history = insert
    c._mark_outbox_applied = lambda event_id, *_args: applied.append(event_id)

    result = c.reconcile_outbox()

    assert result["ok"] is False
    assert result["conflicts"] == [{"id": "ob-bad", "error": "poison"}]
    assert result["replayed"] == ["ob-good"]
    assert applied == ["ob-good"]
    assert result["still_pending"] == 1


def test_legacy_critique_without_exact_argument_binding_stays_pending():
    payload = canonical_history_payload(_critique_payload())
    pending = [_outbox_row("ob-legacy", "T", "critique", "n", payload)]
    neolog = []

    def handler(cypher, _params):
        if "AS exact_bindings" in cypher:
            return [{"arguments": 0, "owners": 0, "exact_bindings": 0}]
        if "RETURN count(o) AS n" in cypher:
            return [{"n": 1}]
        if "OutboxEntry {status:'pending'}" in cypher:
            return pending
        return []

    c = _authorized_container(neo=_Neo(handler, neolog), mongo=object(), pg_kw={})

    @contextlib.contextmanager
    def _must_not_reach_pg():
        raise AssertionError("unbound legacy critique reached PostgreSQL")
        yield

    c.pg = _must_not_reach_pg
    result = c.reconcile_outbox()

    assert result["ok"] is False
    assert result["replayed"] == []
    assert result["still_pending"] == 1
    assert "exact Argument binding" in result["conflicts"][0]["error"]


def test_outbox_transition_rechecks_argument_binding_in_same_neo_query():
    payload = canonical_history_payload(_critique_payload())
    event_id = history_event_id("T", "critique", "T/d1")
    neolog = []

    def handler(cypher, params):
        if "AS exact_bindings" in cypher:
            return [{"arguments": 1, "owners": 1, "exact_bindings": 1}]
        if "WHERE o.id IN $ids" in cypher:
            return [_outbox_row(event_id, "T", "critique", "n", payload)]
        if "UNWIND $expected AS exp" in cypher:
            return [{
                "prevalid": False,
                "argument_valid": False,
                "postvalid": False,
                "ids": [event_id],
            }]
        return []

    c = _authorized_container(neo=_Neo(handler, neolog), mongo=object(), pg_kw={})

    with pytest.raises(HistoryEventConflict, match="state transition failed"):
        c._mark_outbox_applied(
            event_id,
            "T",
            "critique",
            "n",
            payload,
            (41, event_id, event_id),
        )

    transition = next(
        cypher for cypher, _params in neolog if "UNWIND $expected AS exp" in cypher
    )
    assert "argument_valid AND outbox_prevalid" in transition
    assert "SET t._argument_cas=coalesce(t._argument_cas,0)+0" in transition


def test_multiple_legacy_aliases_for_one_critique_fail_closed_before_pg():
    payload = canonical_history_payload(_critique_payload())
    pending = [
        _outbox_row("ob-legacy-1", "T", "critique", "n", payload),
        _outbox_row("ob-legacy-2", "T", "critique", "n", payload),
    ]
    neolog = []

    def handler(cypher, _params):
        if "RETURN count(o) AS n" in cypher:
            return [{"n": 2}]
        if "OutboxEntry {status:'pending'}" in cypher:
            return pending
        return []

    c = _authorized_container(neo=_Neo(handler, neolog), mongo=object(), pg_kw={})

    @contextlib.contextmanager
    def _must_not_reach_pg():
        raise AssertionError("duplicate legacy aliases reached PostgreSQL")
        yield

    c.pg = _must_not_reach_pg
    result = c.reconcile_outbox()

    assert result["ok"] is False
    assert result["replayed"] == []
    assert result["still_pending"] == 2
    assert {item["id"] for item in result["conflicts"]} == {
        "ob-legacy-1", "ob-legacy-2",
    }


def test_prior_adopted_legacy_alias_blocks_second_pending_alias_before_pg():
    payload = canonical_history_payload(_critique_payload())
    stable_id = history_event_id("T", "critique", "T/d1")
    pending = _outbox_row("ob-new", "T", "critique", "n", payload)
    adopted = _outbox_row(
        "ob-old",
        "T",
        "critique",
        "n",
        payload,
        status="adopted",
        adopted_by=stable_id,
        adopted_at=TS,
    )
    neolog = []

    def handler(cypher, _params):
        if "RETURN count(o) AS n" in cypher:
            return [{"n": 1}]
        if "OutboxEntry {status:'pending'}" in cypher:
            return [pending]
        if "o.tree IN $trees" in cypher:
            return [adopted, pending]
        return []

    c = _authorized_container(neo=_Neo(handler, neolog), mongo=object(), pg_kw={})

    @contextlib.contextmanager
    def _must_not_reach_pg():
        raise AssertionError("second legacy alias reached PostgreSQL")
        yield

    c.pg = _must_not_reach_pg
    result = c.reconcile_outbox()

    assert result["ok"] is False
    assert result["replayed"] == []
    assert result["still_pending"] == 1
    assert result["conflicts"] == [{
        "id": "ob-new",
        "error": "multiple legacy critique intents share one stable identity",
    }]


def test_malformed_pending_entries_are_conflicts_without_blocking_valid_entry():
    pending = [
        _outbox_row(None, "T", "test_result", "n", '{}'),
        _outbox_row("ob-nan", "T", "test_result", "n", '{"value":NaN}'),
        _outbox_row("ob-nul", "T", "test_result", "n", '{"value":"\\u0000"}'),
        _outbox_row("ob-surrogate", "T", "test_result", "n",
                    '{"value":"\\ud800"}'),
        _outbox_row("ob-no-tree", None, "test_result", "n", '{}'),
        _outbox_row("ob-good", "U", "node_add", "m", '{}'),
    ]
    neolog, inserted, applied = [], [], []

    def handler(cypher, _params):
        if "RETURN count(o) AS n" in cypher:
            return [{"n": 5}]
        if "OutboxEntry {status:'pending'}" in cypher:
            return pending
        return []

    c = _authorized_container(neo=_Neo(handler, neolog), mongo=object(), pg_kw={})

    @contextlib.contextmanager
    def _ok():
        yield _Conn([])

    def insert(_cur, tree, op, tag, payload, event_id):
        inserted.append((tree, op, tag, payload, event_id))
        return None, event_id, event_id

    c.pg = _ok
    c._insert_history = insert
    c._mark_outbox_applied = lambda event_id, *_args: applied.append(event_id)

    result = c.reconcile_outbox()

    assert result["ok"] is False
    assert [row["id"] for row in result["conflicts"]] == [
        "None", "ob-nan", "ob-nul", "ob-surrogate", "ob-no-tree"
    ]
    assert [row[-1] for row in inserted] == ["ob-good"]
    assert applied == ["ob-good"]
    assert result["replayed"] == ["ob-good"]


def test_outbox_mark_missing_exact_row_fails_instead_of_reporting_replayed():
    neolog = []
    c = _authorized_container(
        neo=_Neo(lambda _cy, _params: [], neolog),
        mongo=object(),
        pg_kw={},
    )
    event_id = history_event_id("T", "critique", "T/d1")

    with pytest.raises(HistoryEventConflict, match="absent or duplicated"):
        c._mark_outbox_applied(
            event_id,
            "T",
            "critique",
            "n",
            '{"arg_id":"d1","attacks":"n"}',
            (41, None, event_id),
        )

    assert not any("UNWIND $expected AS exp" in cypher for cypher, _ in neolog)


def test_pg_down_reuses_caller_stable_id_for_outbox_merge():
    neolog = []
    payload = _critique_payload()
    event_id = history_event_id('T', 'critique', 'T/d1')

    def handler(cypher, params):
        if "AS exact_bindings" in cypher:
            return [{"arguments": 1, "owners": 1, "exact_bindings": 1}]
        if "MERGE (o:OutboxEntry" in cypher:
            return [_outbox_row(
                params["id"], params["tree"], params["op"], params["tag"],
                params["payload"], reason=params["reason"], created_at=params["ts"],
            )]
        return []

    c = _authorized_container(neo=_Neo(handler, neolog), mongo=object(), pg_kw={})

    @contextlib.contextmanager
    def _down():
        raise PgOperationalError('pg down')
        yield

    c.pg = _down
    c.hist('T', 'critique', 'n', payload, event_id=event_id)
    c.hist('T', 'critique', 'n', payload, event_id=event_id)

    outbox_params = [params for cypher, params in neolog if 'MERGE (o:OutboxEntry' in cypher]
    assert [params['id'] for params in outbox_params] == [event_id, event_id]


def test_pg_down_outbox_id_collision_fails_exact_immutable_readback():
    neolog = []

    def handler(cypher, params):
        if "MERGE (o:OutboxEntry" in cypher:
            return [_outbox_row(
                params["id"], "other-tree", params["op"], params["tag"],
                '{"different":true}', reason=params["reason"], created_at=params["ts"],
            )]
        return []

    c = _authorized_container(neo=_Neo(handler, neolog), mongo=object(), pg_kw={})

    @contextlib.contextmanager
    def _down():
        raise PgOperationalError("pg down")
        yield

    c.pg = _down
    with pytest.raises(HistoryEventConflict, match="immutable binding mismatch"):
        c.hist("T", "test_result", "n", {"same": True}, event_id="ob-collision")
