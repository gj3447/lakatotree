"""Hermetic OOPTDD receipt for the structural-batch managed-CAS boundary."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.contexts.tree.schemas import (  # noqa: E402
    StructuralBatchCountsIn,
    StructuralBatchIn,
    StructuralExpectedStateIn,
    StructuralQuestionIn,
)
from server.contexts.tree.writer import (  # noqa: E402
    StructuralBatchIdempotencyConflict,
    StructuralInvariantFailure,
    StructuralOwnershipConflict,
    StructuralPrestateMismatch,
    TreeKgWriter,
)
from server.ports import GuardedKgOps, KgTxGuardFailed  # noqa: E402


def _event(cid: str, name: str) -> dict:
    return {
        "cid": cid,
        "correlation_id": cid,
        "cycle_id": cid,
        "service": "lakatotree.structural_batch_cas",
        "event": name,
    }


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


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
        batch_id="phase8-ooptdd-batch",
        manifest_sha256="c" * 64,
        expected_prestate=_state(questions=0, revision=0),
        expected_post_counts=_state(questions=1, revision=1).counts,
        questions=[
            StructuralQuestionIn(
                qname="q-ooptdd-structural-batch",
                body="bounded structural-batch CAS witness",
            )
        ],
    )


class _ReceiptTx:
    """A strict memory port that exposes only the real writer protocol."""

    def __init__(self, *, outcome: str = "ok", prior_row: dict | None = None) -> None:
        self.outcome = outcome
        self.prior_row = prior_row
        self.calls: list[GuardedKgOps] = []
        self.effects = 0

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
        if not isinstance(ops, GuardedKgOps):
            raise AssertionError("structural batch escaped GuardedKgOps")
        if ops.guard_field != "guard_status" or ops.guard_expected != "ok":
            raise AssertionError("structural batch guard contract drifted")
        batch = GuardedKgOps(
            ops,
            guard_field=ops.guard_field,
            guard_expected=ops.guard_expected,
        )
        self.calls.append(batch)
        if self.outcome != "ok":
            row = (
                dict(self.prior_row)
                if self.outcome == "already_committed" and self.prior_row is not None
                else self._receipt_row(batch)
                if self.outcome == "already_committed"
                else {}
            )
            raise KgTxGuardFailed(
                f"guard rejected: {self.outcome}",
                actual=self.outcome,
                row=row,
            )

        # The port observes one successful managed transaction.  It does not
        # emulate Cypher; the assertions below inspect the real writer's op set.
        self.effects += 1
        final = self._receipt_row(batch)
        return [
            [{"guard_status": "ok", "tree_incarnation_id": "incarnation-1"}],
            [{"event_count": len(json.loads(final["event_intents_json"]))}],
            *([[]] * (len(batch) - 3)),
            [final],
        ]


_MANAGED_OPS_MARKER = '''def _structural_batch_managed_ops(
    ops: Sequence[tuple[str, dict]],
) -> GuardedKgOps:
    """The deliberately load-bearing single-transaction CAS boundary."""

    return GuardedKgOps(
        ops,
        guard_field="guard_status",
        guard_expected="ok",
    )'''

_MUTATED_MANAGED_OPS = '''def _structural_batch_managed_ops(
    ops: Sequence[tuple[str, dict]],
) -> GuardedKgOps:
    """The deliberately load-bearing single-transaction CAS boundary."""

    return list(ops)'''


def _prove_guard_is_load_bearing() -> None:
    writer_path = ROOT / "server" / "contexts" / "tree" / "writer.py"
    before = writer_path.read_bytes()
    before_sha = hashlib.sha256(before).hexdigest()
    source = before.decode("utf-8")
    if source.count(_MANAGED_OPS_MARKER) != 1:
        raise RuntimeError("structural managed-op mutation marker is not unique")

    with tempfile.TemporaryDirectory(prefix="structural-batch-ooptdd-") as temp:
        temp_root = Path(temp)
        shutil.copytree(ROOT / "server", temp_root / "server")
        mutated = source.replace(
            _MANAGED_OPS_MARKER,
            _MUTATED_MANAGED_OPS,
            1,
        )
        (temp_root / "server" / "contexts" / "tree" / "writer.py").write_text(
            mutated,
            encoding="utf-8",
        )
        probe = r'''
from server.container import AppContainer
from server.contexts.tree.writer import _structural_batch_managed_ops
from server.ports import KgTxGuardFailed

class Result:
    def __init__(self, rows):
        self._rows = rows
    def data(self):
        return list(self._rows)

class Session:
    def __init__(self, sink):
        self.sink = sink
    def __enter__(self):
        return self
    def __exit__(self, *_args):
        return False
    def execute_write(self, unit):
        return unit(self)
    def run(self, query, **_params):
        self.sink.append(query)
        if query == "GUARD":
            return Result([{"guard_status": "prestate_mismatch"}])
        return Result([{"side_effect": True}])

class Neo:
    def __init__(self):
        self.seen = []
    def session(self):
        return Session(self.seen)
    def close(self):
        return None

class Mongo:
    def close(self):
        return None

neo = Neo()
container = AppContainer(neo=neo, mongo=Mongo(), pg_kw={})
try:
    container.kg_tx(_structural_batch_managed_ops([
        ("GUARD", {}),
        ("SIDE_EFFECT", {}),
    ]))
except KgTxGuardFailed:
    pass

assert neo.seen == ["GUARD"], "MUTANT_PARTIAL_STRUCTURAL_COMMIT"
'''
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join((str(temp_root), str(ROOT)))
        completed = subprocess.run(
            [sys.executable, "-c", probe],
            # Keep ``sys.path[0]`` inside the isolated copy.  Using ROOT as the
            # cwd would place the canonical checkout ahead of PYTHONPATH and
            # make the mutant probe accidentally import the unmodified module.
            cwd=temp_root,
            env=env,
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
        if completed.returncode == 0:
            raise RuntimeError("unguarded structural-batch source mutant stayed GREEN")
        if "MUTANT_PARTIAL_STRUCTURAL_COMMIT" not in completed.stderr:
            raise RuntimeError(
                "unguarded source mutant failed without the preregistered witness: "
                + completed.stderr[-500:]
            )

    after_sha = hashlib.sha256(writer_path.read_bytes()).hexdigest()
    if after_sha != before_sha:
        raise RuntimeError("isolated source mutant changed the canonical writer")


def verify(backend, cid):
    command = _command()

    tx = _ReceiptTx()
    result = TreeKgWriter(tx).apply_structural_batch(
        name="Tree",
        command=command,
        idempotency_key=command.batch_id,
        constraints_ready=True,
    )
    if len(tx.calls) != 1 or tx.effects != 1:
        raise RuntimeError("structural batch did not use exactly one managed transaction")
    batch = tx.calls[0]
    source = "\n".join(query for query, _params in batch)
    required = (
        "StructuralBatchReceipt",
        "OutboxEntry",
        "OpenQuestion",
        "structural_revision",
        "structural_batch_postcondition_mismatch",
    )
    if not all(token in source for token in required):
        raise RuntimeError("managed structural transaction omitted a required phase")
    if batch[0][1].get("constraints_ready") is not True:
        raise RuntimeError("constraint readiness was not carried into the guard")
    if (
        result.idempotent
        or result.summary.tx_count != 1
        or [event["op"] for event in result.event_intents] != ["question_open"]
        or any(event.get("tree") != "Tree" for event in result.event_intents)
    ):
        raise RuntimeError("positive structural-batch receipt drifted")
    backend.ship([_event(cid, "structural_batch_atomic_commit")])

    stale = _ReceiptTx(outcome="prestate_mismatch")
    try:
        TreeKgWriter(stale).apply_structural_batch(
            name="Tree",
            command=command,
            idempotency_key=command.batch_id,
            constraints_ready=True,
        )
    except StructuralPrestateMismatch:
        pass
    else:
        raise RuntimeError("stale structural prestate was accepted")
    if len(stale.calls) != 1 or stale.effects != 0:
        raise RuntimeError("stale structural prestate produced an effect")
    backend.ship([_event(cid, "structural_batch_stale_cas_no_effect")])

    immutable_prior = _ReceiptTx._receipt_row(tx.calls[0])
    replay = _ReceiptTx(
        outcome="already_committed",
        prior_row=immutable_prior,
    )
    replayed = TreeKgWriter(replay).apply_structural_batch(
        name="Tree",
        command=command,
        idempotency_key=command.batch_id,
        constraints_ready=True,
    )
    if (
        not replayed.idempotent
        or replayed.receipt_id != result.receipt_id
        or replayed.request_sha256 != result.request_sha256
        or replayed.event_intents != result.event_intents
        or replayed.created_at != result.created_at
        or replay.effects != 0
    ):
        raise RuntimeError("exact structural-batch replay drifted")
    backend.ship([_event(cid, "structural_batch_exact_replay")])

    corrupt_prior = dict(immutable_prior)
    corrupt_prior["created_at"] = "2026-08-10T12:00:00Z"
    corrupt_timestamp = _ReceiptTx(
        outcome="already_committed",
        prior_row=corrupt_prior,
    )
    try:
        TreeKgWriter(corrupt_timestamp).apply_structural_batch(
            name="Tree",
            command=command,
            idempotency_key=command.batch_id,
            constraints_ready=True,
        )
    except StructuralInvariantFailure:
        pass
    else:
        raise RuntimeError("noncanonical immutable receipt timestamp was accepted")
    if corrupt_timestamp.effects != 0:
        raise RuntimeError("corrupt immutable timestamp produced an effect")
    backend.ship([_event(cid, "structural_batch_immutable_timestamp_binding")])

    conflict = _ReceiptTx(outcome="idempotency_conflict")
    try:
        TreeKgWriter(conflict).apply_structural_batch(
            name="Tree",
            command=command,
            idempotency_key=command.batch_id,
            constraints_ready=True,
        )
    except StructuralBatchIdempotencyConflict:
        pass
    else:
        raise RuntimeError("structural batch idempotency conflict was accepted")
    if conflict.effects != 0:
        raise RuntimeError("idempotency conflict produced an effect")
    backend.ship([_event(cid, "structural_batch_idempotency_conflict")])

    ownership = _ReceiptTx(outcome="ownership_conflict")
    try:
        TreeKgWriter(ownership).apply_structural_batch(
            name="Tree",
            command=command,
            idempotency_key=command.batch_id,
            constraints_ready=True,
        )
    except StructuralOwnershipConflict:
        pass
    else:
        raise RuntimeError("structural identity ownership conflict was accepted")
    if ownership.effects != 0:
        raise RuntimeError("ownership conflict produced an effect")
    backend.ship([_event(cid, "structural_batch_element_ownership_guard")])

    _prove_guard_is_load_bearing()
    backend.ship([_event(cid, "structural_batch_guard_load_bearing")])
