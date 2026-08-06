"""Hermetic OOPTDD receipt for the dual-resource coordination kernel."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lakatos.resource_coordination import (  # noqa: E402
    CapacityExceeded,
    RequestGrant,
    ResourceEstimate,
    ResourceState,
    ResourceVector,
    decide,
    evolve_all,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _event(cid: str, name: str) -> dict:
    # External observation literals belong in this emit adapter, never the kernel.
    return {
        "cid": cid,
        "correlation_id": cid,
        "cycle_id": cid,
        "service": "lakatotree.resource_coordination",
        "event": name,
    }


def _state() -> ResourceState:
    return ResourceState.create(
        budget_id="receipt-budget",
        scope="tree:receipt",
        epoch=1,
        hard_caps=ResourceVector(100, 100, 20),
    )


def _request(
    *,
    wall: int,
    input_tokens: int,
    output_tokens: int,
) -> RequestGrant:
    return RequestGrant(
        command_id="receipt-command",
        grant_id="receipt-grant",
        fence_token=1,
        observed_at="2026-08-07T11:00:00Z",
        expires_at="2026-08-07T12:00:00Z",
        estimate=ResourceEstimate(
            work_id="receipt-work",
            attempt_id="receipt-attempt",
            workload_sha256=_sha("receipt-workload"),
            adapter="ooptdd",
            adapter_version="1",
            upper_bound=ResourceVector(wall, input_tokens, output_tokens),
            valid_until="2026-08-07T12:00:00Z",
        ),
    )


_ADMISSION_FUNCTION = '''def _admission_deficits(
    requested: ResourceVector,
    remaining: ResourceVector,
    _dimensions: tuple[str, ...] = _DIMENSIONS,
) -> tuple[str, ...]:
    """Admission guard.  OOPTDD mutates only this function in an isolated copy."""

    return requested.exceeds(remaining, dimensions=_dimensions)
'''


def _isolated_mutant_must_red(
    *,
    source_marker: str,
    replacement: str,
    probe: str,
    red_marker: str,
) -> None:
    source_path = ROOT / "lakatos" / "resource_coordination.py"
    source = source_path.read_text(encoding="utf-8")
    if source.count(source_marker) != 1:
        raise RuntimeError("resource mutation marker is not unique")
    mutant = source.replace(source_marker, replacement, 1)
    source_sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()
    if hashlib.sha256(mutant.encode("utf-8")).hexdigest() == source_sha256:
        raise RuntimeError("resource mutant did not change the source")

    with tempfile.TemporaryDirectory(prefix="lakatotree-resource-mutant-") as temp:
        package = Path(temp) / "lakatos"
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "resource_coordination.py").write_text(mutant, encoding="utf-8")
        environment = os.environ.copy()
        environment["PYTHONPATH"] = temp
        completed = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=temp,
            env=environment,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
    if completed.returncode == 0 or red_marker not in completed.stderr:
        raise RuntimeError(
            "isolated resource mutant did not produce the preregistered RED: "
            f"rc={completed.returncode} stderr={completed.stderr[-500:]}"
        )
    if hashlib.sha256(source_path.read_bytes()).hexdigest() != source_sha256:
        raise RuntimeError("canonical resource kernel changed during mutation receipt")


def _guard_mutant_must_red(
    *,
    dimension: str,
    wall: int,
    input_tokens: int,
    output_tokens: int,
) -> None:
    """Mutate one guard only in a temporary module and require its probe to RED."""

    mutant_function = _ADMISSION_FUNCTION.replace(
        "    return requested.exceeds(remaining, dimensions=_dimensions)\n",
        (
            "    _dimensions = tuple(axis for axis in _dimensions "
            f"if axis != {dimension!r})\n"
            "    return requested.exceeds(remaining, dimensions=_dimensions)\n"
        ),
    )
    probe = f'''from lakatos.resource_coordination import (
    RequestGrant, ResourceEstimate, ResourceState, ResourceVector, decide
)
import hashlib

sha = lambda text: hashlib.sha256(text.encode("utf-8")).hexdigest()
state = ResourceState.create(
    budget_id="mutant-budget", scope="tree:mutant", epoch=1,
    hard_caps=ResourceVector(100, 100, 20),
)
command = RequestGrant(
    command_id="mutant-command", grant_id="mutant-grant", fence_token=1,
    observed_at="2026-08-07T11:00:00Z",
    expires_at="2026-08-07T12:00:00Z",
    estimate=ResourceEstimate(
        work_id="mutant-work", attempt_id="mutant-attempt",
        workload_sha256=sha("mutant-workload"), adapter="mutant",
        adapter_version="1",
        upper_bound=ResourceVector({wall}, {input_tokens}, {output_tokens}),
        valid_until="2026-08-07T12:00:00Z",
    ),
)
decision = decide(state, command)
assert decision.rejection is not None, "MUTANT_ADMITTED_{dimension}"
'''
    _isolated_mutant_must_red(
        source_marker=_ADMISSION_FUNCTION,
        replacement=mutant_function,
        probe=probe,
        red_marker=f"MUTANT_ADMITTED_{dimension}",
    )


def _causal_time_mutant_must_red() -> None:
    marker = (
        '        if start_observed < _utc_instant('
        'grant.last_observed_at, "last_observed_at"):\n'
    )
    replacement = marker.replace("if start_observed <", "if False and start_observed <")
    probe = '''from lakatos.resource_coordination import (
    RequestGrant, ResourceEstimate, ResourceState, ResourceVector, StartGrant,
    decide, evolve_all
)
import hashlib

sha = lambda text: hashlib.sha256(text.encode("utf-8")).hexdigest()
state = ResourceState.create(
    budget_id="time-budget", scope="tree:time", epoch=1,
    hard_caps=ResourceVector(100, 100, 20),
)
request = RequestGrant(
    command_id="reserve", grant_id="grant", fence_token=1,
    observed_at="2026-08-07T11:00:00Z", expires_at="2026-08-07T12:00:00Z",
    estimate=ResourceEstimate(
        work_id="work", attempt_id="attempt", workload_sha256=sha("work"),
        adapter="mutant", adapter_version="1", upper_bound=ResourceVector(1, 1, 1),
        valid_until="2026-08-07T12:00:00Z",
    ),
)
state = evolve_all(state, decide(state, request))
start = StartGrant(
    command_id="start", grant_id="grant", fence_token=1,
    workload_sha256=sha("work"), observed_at="2026-08-07T10:59:59Z",
)
assert decide(state, start).rejection is not None, "MUTANT_ACCEPTED_TIME_TRAVEL"
'''
    _isolated_mutant_must_red(
        source_marker=marker,
        replacement=replacement,
        probe=probe,
        red_marker="MUTANT_ACCEPTED_TIME_TRAVEL",
    )


def _decision_binding_mutant_must_red() -> None:
    marker = '''    @property
    def accepted(self) -> bool:
        return self.receipt.outcome != "rejected"
'''
    replacement = marker.replace(
        'return self.receipt.outcome != "rejected"',
        "return True",
    )
    probe = '''from lakatos.resource_coordination import (
    RequestGrant, ResourceEstimate, ResourceState, ResourceVector, decide
)
import hashlib

sha = lambda text: hashlib.sha256(text.encode("utf-8")).hexdigest()
state = ResourceState.create(
    budget_id="decision-budget", scope="tree:decision", epoch=1,
    hard_caps=ResourceVector(1, 1, 1),
)
request = RequestGrant(
    command_id="reject", grant_id="grant", fence_token=1,
    observed_at="2026-08-07T11:00:00Z", expires_at="2026-08-07T12:00:00Z",
    estimate=ResourceEstimate(
        work_id="work", attempt_id="attempt", workload_sha256=sha("work"),
        adapter="mutant", adapter_version="1", upper_bound=ResourceVector(2, 1, 1),
        valid_until="2026-08-07T12:00:00Z",
    ),
)
assert not decide(state, request).accepted, "MUTANT_INVERTED_REJECTION"
'''
    _isolated_mutant_must_red(
        source_marker=marker,
        replacement=replacement,
        probe=probe,
        red_marker="MUTANT_INVERTED_REJECTION",
    )


def _journal_semantics_mutant_must_red() -> None:
    marker = '''    expected = _decide_fresh(state, transition.command)
    if expected.transitions != (transition,):
        raise InvalidTransition("transition does not match the deterministic decision")
'''
    replacement = marker.replace(
        "if expected.transitions != (transition,):",
        "if False and expected.transitions != (transition,):",
    )
    probe = '''from dataclasses import replace
import hashlib
import lakatos.resource_coordination as rc

sha = lambda text: hashlib.sha256(text.encode("utf-8")).hexdigest()
state = rc.ResourceState.create(
    budget_id="journal-budget", scope="tree:journal", epoch=1,
    hard_caps=rc.ResourceVector(1, 1, 1),
)
request = rc.RequestGrant(
    command_id="reject", grant_id="grant", fence_token=1,
    observed_at="2026-08-07T11:00:00Z", expires_at="2026-08-07T12:00:00Z",
    estimate=rc.ResourceEstimate(
        work_id="work", attempt_id="attempt", workload_sha256=sha("work"),
        adapter="mutant", adapter_version="1",
        upper_bound=rc.ResourceVector(2, 1, 1),
        valid_until="2026-08-07T12:00:00Z",
    ),
)
state = rc.evolve_all(state, rc.decide(state, request))
record = state.command_records[0]
receipt = replace(
    record.receipt, outcome="reserved", failure_code=None,
    failure_detail=None, failure_dimensions=(),
)
receipt_sha256 = receipt.receipt_sha256
transition = replace(
    record.transition, receipt=receipt, receipt_sha256=receipt_sha256,
    transition_sha256=rc._canonical_sha(rc._transition_envelope(
        record.transition.transition_payload_sha256, receipt_sha256,
    )),
)
record = replace(
    record, receipt=receipt, receipt_sha256=receipt_sha256,
    transition_sha256=transition.transition_sha256, transition=transition,
)
forged = replace(state, command_records=(record,))
assert not rc.decide(forged, request).accepted, "MUTANT_REPLAYED_FORGED_ACCEPTANCE"
'''
    _isolated_mutant_must_red(
        source_marker=marker,
        replacement=replacement,
        probe=probe,
        red_marker="MUTANT_REPLAYED_FORGED_ACCEPTANCE",
    )


def verify(backend, cid):
    state = _state()
    overages = (
        (_request(wall=101, input_tokens=1, output_tokens=1), "compute.wall_ms"),
        (_request(wall=1, input_tokens=101, output_tokens=1), "llm.input_tokens"),
        (_request(wall=1, input_tokens=1, output_tokens=21), "llm.output_tokens"),
    )
    for command, dimension in overages:
        decision = decide(state, command)
        if not (
            isinstance(decision.rejection, CapacityExceeded)
            and decision.rejection.dimensions == (dimension,)
        ):
            raise RuntimeError(f"{dimension} overflow was not rejected atomically")
    if state.reserved != ResourceVector.zero() or state.revision != 0:
        raise RuntimeError("rejection mutated an uncommitted resource state")
    backend.ship([_event(cid, "dual_vector_admission_rejected")])

    valid = _request(wall=10, input_tokens=10, output_tokens=1)
    first = decide(state, valid)
    admitted = evolve_all(state, first)
    replay = decide(admitted, valid)
    replayed = evolve_all(admitted, replay)
    if not (
        replay.replayed
        and not replay.transitions
        and replay.receipt == first.receipt
        and replayed == admitted
        and admitted.reserved == ResourceVector(10, 10, 1)
    ):
        raise RuntimeError("reservation replay changed the ledger")
    backend.ship([_event(cid, "reservation_replay_idempotent")])

    _guard_mutant_must_red(
        dimension="llm.input_tokens",
        wall=1,
        input_tokens=101,
        output_tokens=1,
    )
    backend.ship([_event(cid, "input_token_guard_load_bearing")])

    _guard_mutant_must_red(
        dimension="llm.output_tokens",
        wall=1,
        input_tokens=1,
        output_tokens=21,
    )
    backend.ship([_event(cid, "output_token_guard_load_bearing")])

    _guard_mutant_must_red(
        dimension="compute.wall_ms",
        wall=101,
        input_tokens=1,
        output_tokens=1,
    )
    backend.ship([_event(cid, "compute_guard_load_bearing")])

    _causal_time_mutant_must_red()
    backend.ship([_event(cid, "causal_time_guard_load_bearing")])

    _decision_binding_mutant_must_red()
    backend.ship([_event(cid, "decision_binding_load_bearing")])

    _journal_semantics_mutant_must_red()
    backend.ship([_event(cid, "journal_semantics_load_bearing")])
