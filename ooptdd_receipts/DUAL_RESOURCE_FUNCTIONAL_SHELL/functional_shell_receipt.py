"""Hermetic OOPTDD receipt for the functional-core/imperative-shell seam."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lakatos.io.resource_journal import SQLiteResourceJournal  # noqa: E402
from lakatos.resource_coordination import (  # noqa: E402
    ENGINE_RULE_SHA256,
    SCHEMA_VERSION,
    RequestGrant,
    ResourceEstimate,
    ResourceState,
    ResourceVector,
)
from lakatos.resource_kernel import DEFAULT_RESOURCE_KERNEL  # noqa: E402


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _event(cid: str, name: str) -> dict:
    # Observation literals belong in this emit adapter, never the engine.
    return {
        "cid": cid,
        "correlation_id": cid,
        "cycle_id": cid,
        "service": "lakatotree.resource_functional_shell",
        "event": name,
    }


def _state(scope: str) -> ResourceState:
    return ResourceState.create(
        budget_id=f"budget:{scope}",
        scope=scope,
        epoch=1,
        hard_caps=ResourceVector(10, 20, 3),
    )


def _command(scope: str) -> RequestGrant:
    return RequestGrant(
        command_id=f"command:{scope}",
        grant_id=f"grant:{scope}",
        fence_token=1,
        observed_at="2026-08-07T11:00:00Z",
        expires_at="2026-08-07T12:00:00Z",
        estimate=ResourceEstimate(
            work_id=f"work:{scope}",
            attempt_id=f"attempt:{scope}",
            workload_sha256=_sha(f"workload:{scope}"),
            adapter="ooptdd-functional-shell",
            adapter_version="1",
            upper_bound=ResourceVector(1, 2, 1),
            valid_until="2026-08-07T12:00:00Z",
        ),
    )


class _TripwireKernel:
    schema_version = SCHEMA_VERSION
    engine_rule_sha256 = ENGINE_RULE_SHA256

    def __init__(self, *, fail_on: str) -> None:
        self._fail_on = fail_on

    def decide(self, state, command):
        if self._fail_on == "decide":
            raise RuntimeError("DECIDE_PORT_USED")
        return DEFAULT_RESOURCE_KERNEL.decide(state, command)

    def evolve(self, state, transition):
        if self._fail_on == "evolve":
            raise RuntimeError("EVOLVE_PORT_USED")
        return DEFAULT_RESOURCE_KERNEL.evolve(state, transition)


def _copy_isolated_package(
    root: Path,
    *,
    mutant_journal: str,
    mutant_contracts: str | None = None,
) -> None:
    package = root / "lakatos"
    io_package = package / "io"
    io_package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (io_package / "__init__.py").write_text("", encoding="utf-8")
    for relative in (
        "resource_coordination.py",
        "resource_kernel.py",
        "write_cert.py",
    ):
        (package / relative).write_bytes((ROOT / "lakatos" / relative).read_bytes())
    for name in (
        "_resource_journal_contracts.py",
        "_resource_journal_codec.py",
        "_resource_anchor.py",
    ):
        source = ROOT / "lakatos" / "io" / name
        if source.exists():
            if name == "_resource_journal_contracts.py" and mutant_contracts is not None:
                (io_package / name).write_text(mutant_contracts, encoding="utf-8")
            else:
                (io_package / name).write_bytes(source.read_bytes())
    (io_package / "resource_journal.py").write_text(mutant_journal, encoding="utf-8")


def _isolated_mutant_must_red(
    *,
    source_marker: str,
    replacement: str,
    probe: str,
    red_marker: str,
) -> None:
    source_path = ROOT / "lakatos" / "io" / "resource_journal.py"
    source = source_path.read_text(encoding="utf-8")
    if source.count(source_marker) != 1:
        raise RuntimeError(f"resource journal mutation marker is not unique: {source_marker!r}")
    mutant = source.replace(source_marker, replacement, 1)
    source_sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()
    if hashlib.sha256(mutant.encode("utf-8")).hexdigest() == source_sha256:
        raise RuntimeError("resource journal mutant did not change the source")

    with tempfile.TemporaryDirectory(prefix="lakatotree-functional-shell-mutant-") as raw:
        root = Path(raw)
        _copy_isolated_package(root, mutant_journal=mutant)
        environment = os.environ.copy()
        environment["PYTHONPATH"] = raw
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        completed = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=raw,
            env=environment,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
    if completed.returncode == 0 or red_marker not in completed.stderr:
        raise RuntimeError(
            "isolated functional-shell mutant did not produce the preregistered RED: "
            f"rc={completed.returncode} stderr={completed.stderr[-500:]}"
        )
    if hashlib.sha256(source_path.read_bytes()).hexdigest() != source_sha256:
        raise RuntimeError("canonical resource journal changed during mutation receipt")


def _port_mutant_must_red(*, method: str) -> None:
    if method == "decide":
        marker = "decision = self._kernel.decide(loaded.state, command)"
        replacement = "decision = DEFAULT_RESOURCE_KERNEL.decide(loaded.state, command)"
    else:
        marker = "next_state = self._kernel.evolve(loaded.state, transition)"
        replacement = (
            "next_state = DEFAULT_RESOURCE_KERNEL.evolve(loaded.state, transition)"
        )
    probe = f'''from pathlib import Path
import hashlib, tempfile
from lakatos.io.resource_journal import SQLiteResourceJournal
from lakatos.resource_coordination import (
    ENGINE_RULE_SHA256, SCHEMA_VERSION, RequestGrant, ResourceEstimate,
    ResourceState, ResourceVector,
)
from lakatos.resource_kernel import DEFAULT_RESOURCE_KERNEL

sha = lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest()
class Tripwire:
    schema_version = SCHEMA_VERSION
    engine_rule_sha256 = ENGINE_RULE_SHA256
    def decide(self, state, command):
        {'raise RuntimeError("DECIDE_PORT_USED")' if method == 'decide' else 'return DEFAULT_RESOURCE_KERNEL.decide(state, command)'}
    def evolve(self, state, transition):
        {'raise RuntimeError("EVOLVE_PORT_USED")' if method == 'evolve' else 'return DEFAULT_RESOURCE_KERNEL.evolve(state, transition)'}

with tempfile.TemporaryDirectory() as raw:
    root = Path(raw)
    scope = "tree:mutant-{method}"
    journal = SQLiteResourceJournal(root / "resource.sqlite3", kernel=Tripwire())
    journal.initialize(ResourceState.create(
        budget_id="budget:mutant-{method}", scope=scope, epoch=1,
        hard_caps=ResourceVector(10, 20, 3),
    ))
    command = RequestGrant(
        command_id="command:mutant-{method}", grant_id="grant:mutant-{method}",
        fence_token=1, observed_at="2026-08-07T11:00:00Z",
        expires_at="2026-08-07T12:00:00Z",
        estimate=ResourceEstimate(
            work_id="work:mutant-{method}", attempt_id="attempt:mutant-{method}",
            workload_sha256=sha("workload:mutant-{method}"), adapter="mutant",
            adapter_version="1", upper_bound=ResourceVector(1, 2, 1),
            valid_until="2026-08-07T12:00:00Z",
        ),
    )
    try:
        journal.apply(scope, command)
    except RuntimeError as exc:
        if str(exc) == "{method.upper()}_PORT_USED":
            raise
        raise
    raise AssertionError("MUTANT_BYPASSED_{method.upper()}_PORT")
'''
    _isolated_mutant_must_red(
        source_marker=marker,
        replacement=replacement,
        probe=probe,
        red_marker=f"MUTANT_BYPASSED_{method.upper()}_PORT",
    )


def _mutable_replay_mutant_must_red() -> None:
    marker = "states=tuple(states),"
    replacement = "states=states,"
    probe = '''from pathlib import Path
import tempfile
from lakatos.io.resource_journal import SQLiteResourceJournal
from lakatos.resource_coordination import ResourceState, ResourceVector

with tempfile.TemporaryDirectory() as raw:
    root = Path(raw)
    scope = "tree:mutable-mutant"
    journal = SQLiteResourceJournal(root / "resource.sqlite3")
    journal.initialize(ResourceState.create(
        budget_id="budget:mutable-mutant", scope=scope, epoch=1,
        hard_caps=ResourceVector(1, 1, 1),
    ))
    connection = journal._connect()
    try:
        connection.execute("BEGIN")
        loaded = journal._load_connection(connection, scope)
        connection.commit()
    finally:
        connection.close()
    try:
        loaded.states[0] = loaded.state
    except TypeError:
        raise
    raise AssertionError("MUTANT_MUTATED_REPLAY_INDEX")
'''
    _isolated_mutant_must_red(
        source_marker=marker,
        replacement=replacement,
        probe=probe,
        red_marker="MUTANT_MUTATED_REPLAY_INDEX",
    )


def _codec_domain_mutant_must_red() -> None:
    source_path = ROOT / "lakatos" / "io" / "_resource_journal_contracts.py"
    source = source_path.read_text(encoding="utf-8")
    marker = r'_JOURNAL_DOMAIN = b"lakatotree-resource-journal\x00v1\n"'
    if source.count(marker) != 1:
        raise RuntimeError("journal-domain mutation marker is not unique")
    mutant = source.replace(marker, marker.replace("v1", "v2"), 1)
    source_sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()

    probe = r'''from lakatos.io._resource_journal_codec import _checkpoint_for
from lakatos.resource_coordination import RequestGrant, ResourceEstimate, ResourceState, ResourceVector
from lakatos.resource_kernel import DEFAULT_RESOURCE_KERNEL
import hashlib

sha = lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest()
scope = "tree:ooptdd-codec"
state = ResourceState.create(
    budget_id=f"budget:{scope}", scope=scope, epoch=1,
    hard_caps=ResourceVector(10, 20, 3),
)
command = RequestGrant(
    command_id=f"command:{scope}", grant_id=f"grant:{scope}", fence_token=1,
    observed_at="2026-08-07T11:00:00Z", expires_at="2026-08-07T12:00:00Z",
    estimate=ResourceEstimate(
        work_id=f"work:{scope}", attempt_id=f"attempt:{scope}",
        workload_sha256=sha(f"workload:{scope}"), adapter="ooptdd-functional-shell",
        adapter_version="1", upper_bound=ResourceVector(1, 2, 1),
        valid_until="2026-08-07T12:00:00Z",
    ),
)
transition = DEFAULT_RESOURCE_KERNEL.decide(state, command).transitions[0]
next_state = DEFAULT_RESOURCE_KERNEL.evolve(state, transition)
genesis = _checkpoint_for(state, previous_journal_head_sha256=None, transition=None)
current = _checkpoint_for(
    next_state,
    previous_journal_head_sha256=genesis.journal_head_sha256,
    transition=transition,
)
assert current.journal_head_sha256 == "edf47a3adbbbab8b8d69cef2d831c16125f3fa1ed76ec93b100cca8bbf3b0c8e", "MUTANT_CODEC_HASH_DRIFT"
'''
    with tempfile.TemporaryDirectory(prefix="lakatotree-codec-domain-mutant-") as raw:
        root = Path(raw)
        _copy_isolated_package(
            root,
            mutant_journal=(ROOT / "lakatos" / "io" / "resource_journal.py").read_text(
                encoding="utf-8"
            ),
            mutant_contracts=mutant,
        )
        environment = os.environ.copy()
        environment["PYTHONPATH"] = raw
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        completed = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=raw,
            env=environment,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
    if completed.returncode == 0 or "MUTANT_CODEC_HASH_DRIFT" not in completed.stderr:
        raise RuntimeError(
            "isolated codec-domain mutant did not produce the preregistered RED: "
            f"rc={completed.returncode} stderr={completed.stderr[-500:]}"
        )
    if hashlib.sha256(source_path.read_bytes()).hexdigest() != source_sha256:
        raise RuntimeError("canonical journal contracts changed during mutation receipt")


def verify(backend, cid):
    scope = "tree:ooptdd-functional"
    state = _state(scope)
    original_sha = state.snapshot_sha256
    left = DEFAULT_RESOURCE_KERNEL.decide(state, _command(scope))
    right = DEFAULT_RESOURCE_KERNEL.decide(state, _command(scope))
    if left != right:
        raise RuntimeError("equal kernel inputs produced unequal decisions")
    if DEFAULT_RESOURCE_KERNEL.evolve(state, left.transitions[0]) != (
        DEFAULT_RESOURCE_KERNEL.evolve(state, right.transitions[0])
    ):
        raise RuntimeError("equal transitions produced unequal states")
    if state.snapshot_sha256 != original_sha or state.revision != 0:
        raise RuntimeError("functional kernel mutated its input state")
    try:
        state.revision = 99
    except FrozenInstanceError:
        pass
    else:
        raise RuntimeError("resource state is not frozen")
    for label, value in (
        ("transitions", list(left.transitions)),
        ("grants", list(state.grants)),
        ("command_records", list(state.command_records)),
    ):
        try:
            if label == "transitions":
                replace(left, transitions=value)
            else:
                replace(state, **{label: value})
        except ValueError:
            pass
        else:
            raise RuntimeError(f"{label} accepted a mutable alias")
    backend.ship([_event(cid, "pure_kernel_referentially_transparent")])

    with tempfile.TemporaryDirectory(prefix="lakatotree-functional-port-") as raw:
        root = Path(raw)
        journal = SQLiteResourceJournal(
            root / "resource.sqlite3",
            kernel=_TripwireKernel(fail_on="decide"),
        )
        journal.initialize(_state(scope))
        try:
            journal.apply(scope, _command(scope))
        except RuntimeError as exc:
            if str(exc) != "DECIDE_PORT_USED":
                raise
        else:
            raise RuntimeError("SQLite shell bypassed its injected decide port")
    backend.ship([_event(cid, "injected_decide_port_used")])

    _port_mutant_must_red(method="decide")
    backend.ship([_event(cid, "decide_port_load_bearing")])

    _port_mutant_must_red(method="evolve")
    backend.ship([_event(cid, "evolve_port_load_bearing")])

    _mutable_replay_mutant_must_red()
    backend.ship([_event(cid, "replay_index_immutability_load_bearing")])

    from lakatos.io import _resource_anchor as anchor
    from lakatos.io import _resource_journal_codec as codec
    from lakatos.io import _resource_journal_contracts as contracts
    from lakatos.io import resource_journal as facade

    if facade.ResourceCheckpoint is not contracts.ResourceCheckpoint:
        raise RuntimeError("journal facade duplicated its checkpoint contract")
    if facade.SignedAppendOnlyFileAnchor is not anchor.SignedAppendOnlyFileAnchor:
        raise RuntimeError("journal facade duplicated its anchor adapter")
    codec_scope = "tree:ooptdd-codec"
    codec_state = _state(codec_scope)
    codec_transition = DEFAULT_RESOURCE_KERNEL.decide(
        codec_state,
        _command(codec_scope),
    ).transitions[0]
    codec_next_state = DEFAULT_RESOURCE_KERNEL.evolve(codec_state, codec_transition)
    codec_genesis = codec._checkpoint_for(
        codec_state,
        previous_journal_head_sha256=None,
        transition=None,
    )
    codec_current = codec._checkpoint_for(
        codec_next_state,
        previous_journal_head_sha256=codec_genesis.journal_head_sha256,
        transition=codec_transition,
    )
    if codec_current.journal_head_sha256 != (
        "edf47a3adbbbab8b8d69cef2d831c16125f3fa1ed76ec93b100cca8bbf3b0c8e"
    ):
        raise RuntimeError("split codec changed the canonical journal head")
    backend.ship([_event(cid, "split_codec_contract_stable")])

    _codec_domain_mutant_must_red()
    backend.ship([_event(cid, "codec_hash_contract_load_bearing")])
