"""RED-first guards for the functional resource kernel and durable shell.

The resource coordinator is a deterministic functional core.  Persistence is an
imperative shell that must depend on the core through a narrow injected port and
must not expose mutable replay indexes after history verification.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import hashlib
from pathlib import Path

import pytest

from lakatos.io.resource_journal import SQLiteResourceJournal
from lakatos.resource_coordination import (
    ENGINE_RULE_SHA256,
    SCHEMA_VERSION,
    RequestGrant,
    ResourceEstimate,
    ResourceState,
    ResourceVector,
    decide,
    evolve,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _state() -> ResourceState:
    return ResourceState.create(
        budget_id="budget:solid",
        scope="tree:solid",
        epoch=1,
        hard_caps=ResourceVector(10, 20, 3),
    )


def _command() -> RequestGrant:
    return RequestGrant(
        command_id="command:solid",
        grant_id="grant:solid",
        fence_token=1,
        observed_at="2026-08-07T11:00:00Z",
        expires_at="2026-08-07T12:00:00Z",
        estimate=ResourceEstimate(
            work_id="work:solid",
            attempt_id="attempt:solid",
            workload_sha256=_sha("workload:solid"),
            adapter="solid-test",
            adapter_version="1",
            upper_bound=ResourceVector(1, 2, 1),
            valid_until="2026-08-07T12:00:00Z",
        ),
    )


def test_guard_mechanism_default_kernel_is_referentially_transparent():
    from lakatos.resource_kernel import DEFAULT_RESOURCE_KERNEL

    state = _state()
    before = state.snapshot_sha256

    left = DEFAULT_RESOURCE_KERNEL.decide(state, _command())
    right = DEFAULT_RESOURCE_KERNEL.decide(state, _command())
    assert left == right

    left_state = DEFAULT_RESOURCE_KERNEL.evolve(state, left.transitions[0])
    right_state = DEFAULT_RESOURCE_KERNEL.evolve(state, right.transitions[0])
    assert left_state == right_state
    assert left_state is not state
    assert state.snapshot_sha256 == before
    assert state.revision == 0

    with pytest.raises(FrozenInstanceError):
        state.revision = 99  # type: ignore[misc]


def test_guard_defect_authority_sequences_reject_mutable_aliases():
    from lakatos.resource_kernel import DEFAULT_RESOURCE_KERNEL

    state = _state()
    decision = DEFAULT_RESOURCE_KERNEL.decide(state, _command())

    with pytest.raises(ValueError, match="transitions must be a tuple"):
        replace(decision, transitions=list(decision.transitions))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="grants must be a tuple"):
        replace(state, grants=list(state.grants))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="command_records must be a tuple"):
        replace(state, command_records=list(state.command_records))  # type: ignore[arg-type]


class _TripwireKernel:
    schema_version = SCHEMA_VERSION
    engine_rule_sha256 = ENGINE_RULE_SHA256

    def __init__(self, *, fail_on: str) -> None:
        from lakatos.resource_kernel import DEFAULT_RESOURCE_KERNEL

        self._delegate = DEFAULT_RESOURCE_KERNEL
        self._fail_on = fail_on

    def decide(self, state, command):
        if self._fail_on == "decide":
            raise RuntimeError("DECIDE_PORT_USED")
        return self._delegate.decide(state, command)

    def evolve(self, state, transition):
        if self._fail_on == "evolve":
            raise RuntimeError("EVOLVE_PORT_USED")
        return self._delegate.evolve(state, transition)


@pytest.mark.parametrize(
    ("fail_on", "marker"),
    (("decide", "DECIDE_PORT_USED"), ("evolve", "EVOLVE_PORT_USED")),
)
def test_guard_mechanism_sqlite_shell_uses_injected_kernel_port(
    tmp_path,
    fail_on: str,
    marker: str,
):
    journal = SQLiteResourceJournal(
        tmp_path / "resource.sqlite3",
        kernel=_TripwireKernel(fail_on=fail_on),
    )
    journal.initialize(_state())

    with pytest.raises(RuntimeError, match=marker):
        journal.apply("tree:solid", _command())

    assert SQLiteResourceJournal(tmp_path / "resource.sqlite3").load(
        "tree:solid"
    ).state.revision == 0


def test_guard_mechanism_verified_replay_indexes_are_deeply_immutable(tmp_path):
    journal = SQLiteResourceJournal(tmp_path / "resource.sqlite3")
    journal.initialize(_state())
    journal.apply("tree:solid", _command())

    connection = journal._connect()
    try:
        connection.execute("BEGIN")
        replayed = journal._load_connection(connection, "tree:solid")
        connection.commit()
    finally:
        connection.close()

    assert replayed is not None
    assert isinstance(replayed.states, tuple)
    assert isinstance(replayed.checkpoints, tuple)
    assert isinstance(replayed.anchor_statuses, tuple)
    with pytest.raises(TypeError):
        replayed.states[0] = replayed.state  # type: ignore[index]


def test_guard_defect_functional_core_io_dependency_contract_is_declared():
    config = (Path(__file__).resolve().parents[1] / ".importlinter").read_text(
        encoding="utf-8"
    )
    assert "resource functional core must not import effects" in config
    assert "source_modules =\n    lakatos.resource_coordination\n    lakatos.resource_kernel" in config
    assert "forbidden_modules =\n    lakatos.io\n    server" in config


def test_guard_mechanism_journal_facade_preserves_split_contract_identities():
    from lakatos.io import _resource_anchor as anchor
    from lakatos.io import _resource_journal_contracts as contracts
    from lakatos.io import resource_journal as facade

    assert facade.ResourceCheckpoint is contracts.ResourceCheckpoint
    assert facade.JournalSnapshot is contracts.JournalSnapshot
    assert facade.DurableDecision is contracts.DurableDecision
    assert facade.TrustedAnchorStore is contracts.TrustedAnchorStore
    assert facade.AnchorConflict is contracts.AnchorConflict
    assert facade.SignedAppendOnlyFileAnchor is anchor.SignedAppendOnlyFileAnchor


def test_guard_defect_codec_split_preserves_canonical_wire_hashes():
    from lakatos.io import _resource_journal_codec as codec

    state = _state()
    transition = decide(state, _command()).transitions[0]
    next_state = evolve(state, transition)
    genesis = codec._checkpoint_for(
        state,
        previous_journal_head_sha256=None,
        transition=None,
    )
    current = codec._checkpoint_for(
        next_state,
        previous_journal_head_sha256=genesis.journal_head_sha256,
        transition=transition,
    )

    budget_blob = codec._budget_blob(state.budget)
    transition_blob = codec._transition_blob(transition)
    assert hashlib.sha256(budget_blob).hexdigest() == (
        "07936dedfd9262f8651be985c491679036005d3b3c481166214c12e3bcca9d18"
    )
    assert hashlib.sha256(transition_blob).hexdigest() == (
        "c362eb6c485f74209c0dac5c9105038412c845bffdbfa3678faabf1a639cde04"
    )
    assert genesis.checkpoint_sha256 == (
        "143b995a1594add9884a8188fa26e37340b7718fd855bee5dfe6ed95ee2508c9"
    )
    assert current.checkpoint_sha256 == (
        "89864cb5f3785acf5264bf0a69f593e7b5e3e96cf672fc1958077fee65549d68"
    )
    assert genesis.journal_head_sha256 == (
        "b070dd3efe46a0c43b41c70dc85eab4ccd33aaa4217724f044b0aca022f28c91"
    )
    assert current.journal_head_sha256 == (
        "a4dc48f296b8c3e2f11bc0e24522b6d68f5fbffd4d44b845bf4286ddebbf3dfd"
    )
    assert codec._budget_from_blob(budget_blob) == state.budget
    assert codec._transition_from_blob(transition_blob) == transition
