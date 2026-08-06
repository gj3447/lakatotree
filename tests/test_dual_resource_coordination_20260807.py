"""RED-first guards for LakatoTree's dual-resource coordination kernel.

The existing ``cycle_budget`` counts scientific judgements.  These guards cover a
different boundary: reserving compute and LLM-token capacity before costly work.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib

import pytest

from lakatos.resource_coordination import (
    BudgetStatus,
    CancelGrant,
    CapacityExceeded,
    DeadlineObserved,
    GrantStatus,
    IdempotencyConflict,
    InvalidTransition,
    RequestGrant,
    ResourceBudget,
    ResourceEstimate,
    ResourceState,
    ResourceUsage,
    ResourceVector,
    SettleGrant,
    StartGrant,
    UsageUnknown,
    decide,
    evolve_all,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _state(*, wall: int = 1_000, input_tokens: int = 500,
           output_tokens: int = 200) -> ResourceState:
    return ResourceState.create(
        budget_id="budget-T-1",
        scope="tree:T",
        epoch=1,
        hard_caps=ResourceVector(
            compute_wall_ms=wall,
            llm_input_tokens=input_tokens,
            llm_output_tokens=output_tokens,
        ),
    )


def _request(
    command_id: str = "cmd-reserve-1",
    *,
    grant_id: str = "grant-1",
    wall: int = 400,
    input_tokens: int = 200,
    output_tokens: int = 80,
    observed_at: str = "2026-08-07T11:00:00Z",
    expires_at: str = "2026-08-07T12:00:00Z",
    valid_until: str = "2026-08-07T12:00:00Z",
) -> RequestGrant:
    estimate = ResourceEstimate(
        work_id="work-1",
        attempt_id="attempt-1",
        workload_sha256=_sha("workload-1"),
        adapter="test-adapter",
        adapter_version="1",
        upper_bound=ResourceVector(
            compute_wall_ms=wall,
            llm_input_tokens=input_tokens,
            llm_output_tokens=output_tokens,
        ),
        valid_until=valid_until,
    )
    return RequestGrant(
        command_id=command_id,
        grant_id=grant_id,
        fence_token=1,
        observed_at=observed_at,
        expires_at=expires_at,
        estimate=estimate,
    )


def _apply(state: ResourceState, command):
    decision = decide(state, command)
    return evolve_all(state, decision), decision


def _usage(actual: ResourceVector, label: str) -> ResourceUsage:
    return ResourceUsage(
        actual=actual,
        measured_at="2026-08-07T11:10:00Z",
        measurement_sha256=_sha(f"measurement-{label}"),
        evidence_sha256=_sha(f"evidence-{label}"),
    )


def test_guard_defect_one_exhausted_axis_cannot_partially_reserve_other_axes():
    """Token overflow must not leave a compute reservation behind (vector atomicity)."""
    state = _state(wall=100, input_tokens=100, output_tokens=20)
    command = _request(wall=10, input_tokens=101, output_tokens=1)

    decision = decide(state, command)
    assert isinstance(decision.rejection, CapacityExceeded)
    assert decision.rejection.dimensions == ("llm.input_tokens",)
    rejected = evolve_all(state, decision)
    assert state.reserved == ResourceVector.zero()
    assert state.revision == 0
    assert not state.grants
    assert rejected.revision == 1
    assert rejected.reserved == ResourceVector.zero()
    assert not rejected.grants


def test_guard_mechanism_compute_and_token_caps_are_independent_and_symmetric():
    state = _state(wall=100, input_tokens=100, output_tokens=20)

    compute = decide(state, _request(wall=101, input_tokens=1, output_tokens=1))
    assert isinstance(compute.rejection, CapacityExceeded)
    assert compute.rejection.dimensions == ("compute.wall_ms",)

    output = decide(state, _request(wall=1, input_tokens=1, output_tokens=21))
    assert isinstance(output.rejection, CapacityExceeded)
    assert output.rejection.dimensions == ("llm.output_tokens",)


def test_reserve_start_settle_releases_unused_capacity_and_charges_actual_usage():
    state = _state()
    state, reservation = _apply(state, _request())
    assert state.revision == 1
    assert state.reserved == ResourceVector(400, 200, 80)
    assert state.spent == ResourceVector.zero()
    assert state.grant("grant-1").status is GrantStatus.RESERVED

    state, started = _apply(state, StartGrant(
        command_id="cmd-start-1",
        grant_id="grant-1",
        fence_token=1,
        workload_sha256=_sha("workload-1"),
        observed_at="2026-08-07T11:00:00Z",
    ))
    assert state.grant("grant-1").status is GrantStatus.IN_USE

    actual = ResourceVector(350, 180, 60)
    state, settled = _apply(state, SettleGrant(
        command_id="cmd-settle-1",
        grant_id="grant-1",
        fence_token=1,
        workload_sha256=_sha("workload-1"),
        observed_at="2026-08-07T11:10:00Z",
        usage=_usage(actual, "1"),
    ))

    assert state.reserved == ResourceVector.zero()
    assert state.spent == actual
    assert state.remaining == ResourceVector(650, 320, 140)
    assert state.grant("grant-1").status is GrantStatus.SETTLED
    assert reservation.receipt.operation == "request_grant"
    assert started.receipt.operation == "start_grant"
    assert settled.receipt.actual == actual
    assert settled.receipt.released == ResourceVector(50, 20, 20)


def test_exact_command_replay_is_a_noop_but_changed_payload_conflicts():
    state = _state()
    command = _request()
    state, first = _apply(state, command)

    replay = decide(state, command)
    assert replay.replayed is True
    assert replay.transitions == ()
    assert replay.receipt == first.receipt
    assert evolve_all(state, replay) == state

    with pytest.raises(IdempotencyConflict):
        decide(state, _request(input_tokens=201))


def test_unused_cancel_and_deadline_release_but_unknown_in_use_usage_stays_held():
    state, _ = _apply(_state(), _request())
    cancelled, _ = _apply(state, CancelGrant(
        command_id="cmd-cancel-1", grant_id="grant-1", fence_token=1,
        workload_sha256=_sha("workload-1"), observed_at="2026-08-07T11:00:00Z",
        reason="operator_cancelled",
    ))
    assert cancelled.reserved == ResourceVector.zero()
    assert cancelled.grant("grant-1").status is GrantStatus.CANCELLED_UNUSED

    state, _ = _apply(_state(), _request())
    expired, _ = _apply(state, DeadlineObserved(
        command_id="cmd-expire-1", grant_id="grant-1", fence_token=1,
        workload_sha256=_sha("workload-1"), observed_at="2026-08-07T12:01:00Z",
    ))
    assert expired.reserved == ResourceVector.zero()
    assert expired.grant("grant-1").status is GrantStatus.EXPIRED_UNUSED

    state, _ = _apply(_state(), _request())
    state, _ = _apply(state, StartGrant(
        command_id="cmd-start-1", grant_id="grant-1", fence_token=1,
        workload_sha256=_sha("workload-1"), observed_at="2026-08-07T11:00:00Z",
    ))
    held, _ = _apply(state, UsageUnknown(
        command_id="cmd-unknown-1", grant_id="grant-1", fence_token=1,
        workload_sha256=_sha("workload-1"), observed_at="2026-08-07T11:10:00Z",
        reason="meter_unavailable",
    ))
    assert held.reserved == ResourceVector(400, 200, 80)
    assert held.grant("grant-1").status is GrantStatus.RECONCILIATION_REQUIRED


def test_cancel_intent_survives_unknown_usage_until_cancelled_settlement():
    state, _ = _apply(_state(), _request())
    state, _ = _apply(state, StartGrant(
        command_id="cmd-start-1", grant_id="grant-1", fence_token=1,
        workload_sha256=_sha("workload-1"), observed_at="2026-08-07T11:00:00Z",
    ))
    state, _ = _apply(state, CancelGrant(
        command_id="cmd-cancel-1", grant_id="grant-1", fence_token=1,
        workload_sha256=_sha("workload-1"), observed_at="2026-08-07T11:01:00Z",
        reason="operator_cancelled",
    ))
    state, _ = _apply(state, UsageUnknown(
        command_id="cmd-unknown-1", grant_id="grant-1", fence_token=1,
        workload_sha256=_sha("workload-1"), observed_at="2026-08-07T11:02:00Z",
        reason="meter_temporarily_unavailable",
    ))
    state, _ = _apply(state, SettleGrant(
        command_id="cmd-settle-1", grant_id="grant-1", fence_token=1,
        workload_sha256=_sha("workload-1"),
        observed_at="2026-08-07T11:03:00Z",
        usage=ResourceUsage(
            actual=ResourceVector(10, 5, 2),
            measured_at="2026-08-07T11:03:00Z",
            measurement_sha256=_sha("cancel-measurement"),
            evidence_sha256=_sha("cancel-evidence"),
        ),
    ))
    assert state.grant("grant-1").status is GrantStatus.CANCELLED_SETTLED
    assert state.reserved == ResourceVector.zero()
    assert state.spent == ResourceVector(10, 5, 2)


def test_measured_overrun_is_preserved_and_freezes_further_admission():
    state, _ = _apply(_state(), _request())
    state, _ = _apply(state, StartGrant(
        command_id="cmd-start-1", grant_id="grant-1", fence_token=1,
        workload_sha256=_sha("workload-1"), observed_at="2026-08-07T11:00:00Z",
    ))
    state, decision = _apply(state, SettleGrant(
        command_id="cmd-overrun-1", grant_id="grant-1", fence_token=1,
        workload_sha256=_sha("workload-1"),
        observed_at="2026-08-07T11:10:00Z",
        usage=_usage(ResourceVector(401, 200, 80), "overrun"),
    ))

    assert state.status is BudgetStatus.FROZEN
    assert state.grant("grant-1").status is GrantStatus.QUARANTINED_OVERRUN
    assert state.spent == ResourceVector(401, 200, 80)
    assert decision.receipt.outcome == "quarantined_overrun"
    frozen = decide(state, _request(command_id="cmd-reserve-2", grant_id="grant-2"))
    assert frozen.rejection is not None
    assert frozen.rejection.code == "BUDGET_FROZEN"


def test_resource_receipt_has_no_scientific_verdict_surface():
    _state_after, decision = _apply(_state(), _request())
    payload = decision.receipt.to_dict()
    forbidden = {"verdict", "progressive", "canonical", "novelty", "novel"}
    assert forbidden.isdisjoint(payload)
    assert payload["schema_version"] == "lakatotree.resource/v1"
    assert len(decision.receipt.receipt_sha256) == 64


def test_content_addressed_transition_rejects_payload_tampering_before_state_change():
    state = _state()
    decision = decide(state, _request())
    tampered = replace(
        decision.transitions[0],
        spent_delta=ResourceVector(compute_wall_ms=1),
    )
    with pytest.raises(InvalidTransition, match="content hash"):
        evolve_all(state, replace(decision, transitions=(tampered,)))
    assert state.revision == 0
    assert state.spent == ResourceVector.zero()


def test_receipt_is_bound_into_transition_and_cannot_forge_scope_or_outcome():
    import lakatos.resource_coordination as resource_module

    state = _state()
    decision = decide(state, _request())
    transition = decision.transitions[0]

    for forged_receipt in (
        replace(decision.receipt, scope="tree:forged"),
        replace(decision.receipt, outcome="fabricated"),
    ):
        forged = replace(transition, receipt=forged_receipt)
        with pytest.raises(InvalidTransition, match="receipt payload"):
            evolve_all(state, replace(decision, transitions=(forged,)))

    # Even if an attacker recomputes both public content hashes, the reducer
    # regenerates the pure decision and rejects the forged semantics.
    forged_receipt = replace(decision.receipt, outcome="fabricated")
    forged_receipt_sha256 = forged_receipt.receipt_sha256
    self_consistent_forgery = replace(
        transition,
        receipt=forged_receipt,
        receipt_sha256=forged_receipt_sha256,
        transition_sha256=resource_module._canonical_sha(
            resource_module._transition_envelope(
                transition.transition_payload_sha256,
                forged_receipt_sha256,
            )
        ),
    )
    with pytest.raises(InvalidTransition, match="deterministic decision"):
        evolve_all(
            state,
            replace(decision, transitions=(self_consistent_forgery,)),
        )
    assert state.revision == 0


def test_time_guards_reject_stale_admission_late_start_and_early_deadline():
    stale = decide(
        _state(),
        _request(
            observed_at="2026-08-07T12:00:01Z",
            expires_at="2026-08-07T12:00:02Z",
        ),
    )
    assert stale.rejection is not None
    assert stale.rejection.code == "INVALID_TRANSITION"

    outlives_estimate = decide(
        _state(),
        _request(
            expires_at="2026-08-07T12:00:01Z",
            valid_until="2026-08-07T12:00:00Z",
        ),
    )
    assert outlives_estimate.rejection is not None

    state, _ = _apply(_state(), _request())
    late_start = decide(state, StartGrant(
        command_id="cmd-late-start", grant_id="grant-1", fence_token=1,
        workload_sha256=_sha("workload-1"), observed_at="2026-08-07T12:00:00Z",
    ))
    assert late_start.rejection is not None
    assert late_start.rejection.code == "INVALID_TRANSITION"

    early_deadline = decide(state, DeadlineObserved(
        command_id="cmd-early-deadline", grant_id="grant-1", fence_token=1,
        workload_sha256=_sha("workload-1"), observed_at="2026-08-07T11:59:59Z",
    ))
    assert early_deadline.rejection is not None
    assert early_deadline.rejection.code == "INVALID_TRANSITION"


def test_rejected_command_is_receipted_and_exact_replay_stays_rejected():
    state = _state(wall=100, input_tokens=100, output_tokens=20)
    command = _request(wall=101, input_tokens=1, output_tokens=1)
    state, first = _apply(state, command)
    assert isinstance(first.rejection, CapacityExceeded)
    assert state.revision == 1

    replay = decide(state, command)
    assert replay.replayed is True
    assert replay.transitions == ()
    assert isinstance(replay.rejection, CapacityExceeded)
    assert replay.receipt == first.receipt
    with pytest.raises(ValueError, match="budget genesis"):
        replace(state, hard_caps=ResourceVector(1_000, 1_000, 1_000))


def test_exported_dimension_description_cannot_disable_production_admission():
    import lakatos.resource_coordination as resource_module

    original = resource_module.DIMENSIONS
    try:
        resource_module.DIMENSIONS = ()
        decision = decide(
            _state(wall=100, input_tokens=100, output_tokens=20),
            _request(wall=101, input_tokens=1, output_tokens=1),
        )
    finally:
        resource_module.DIMENSIONS = original
    assert isinstance(decision.rejection, CapacityExceeded)
    assert decision.rejection.dimensions == ("compute.wall_ms",)


def test_public_budget_estimate_usage_grant_and_receipt_are_versioned():
    state = _state()
    assert isinstance(state.budget, ResourceBudget)
    assert state.budget.schema_version == "lakatotree.resource/v1"
    command = _request()
    assert command.estimate.schema_version == state.schema_version
    state, _ = _apply(state, command)
    assert state.grant("grant-1").schema_version == state.schema_version
    usage = _usage(ResourceVector(1, 1, 1), "schema")
    assert usage.schema_version == state.schema_version


def test_lifecycle_observations_and_measurements_cannot_move_backwards():
    state, _ = _apply(_state(), _request())
    pre_admission_start = decide(state, StartGrant(
        command_id="cmd-pre-admission-start", grant_id="grant-1", fence_token=1,
        workload_sha256=_sha("workload-1"), observed_at="2026-08-07T10:59:59Z",
    ))
    assert pre_admission_start.rejection is not None
    assert pre_admission_start.rejection.code == "INVALID_TRANSITION"

    state, _ = _apply(state, StartGrant(
        command_id="cmd-start-causal", grant_id="grant-1", fence_token=1,
        workload_sha256=_sha("workload-1"), observed_at="2026-08-07T11:00:01Z",
    ))
    pre_start_measurement = decide(state, SettleGrant(
        command_id="cmd-pre-start-measurement", grant_id="grant-1", fence_token=1,
        workload_sha256=_sha("workload-1"),
        observed_at="2026-08-07T11:10:00Z",
        usage=ResourceUsage(
            actual=ResourceVector(1, 1, 1),
            measured_at="2026-08-07T11:00:00Z",
            measurement_sha256=_sha("pre-start-measurement"),
            evidence_sha256=_sha("pre-start-evidence"),
        ),
    ))
    assert pre_start_measurement.rejection is not None
    assert pre_start_measurement.rejection.code == "INVALID_TRANSITION"

    future_measurement = decide(state, SettleGrant(
        command_id="cmd-future-measurement", grant_id="grant-1", fence_token=1,
        workload_sha256=_sha("workload-1"),
        observed_at="2026-08-07T11:10:00Z",
        usage=ResourceUsage(
            actual=ResourceVector(1, 1, 1),
            measured_at="2026-08-07T11:10:01Z",
            measurement_sha256=_sha("future-measurement"),
            evidence_sha256=_sha("future-evidence"),
        ),
    ))
    assert future_measurement.rejection is not None


def test_decision_acceptance_and_receipt_are_derived_from_authoritative_transition():
    rejected = decide(
        _state(wall=100, input_tokens=100, output_tokens=20),
        _request(wall=101, input_tokens=1, output_tokens=1),
    )
    assert rejected.accepted is False
    assert isinstance(rejected.rejection, CapacityExceeded)
    assert rejected.receipt is rejected.transitions[0].receipt

    with pytest.raises(TypeError):
        replace(rejected, rejection=None)
    with pytest.raises(TypeError):
        replace(rejected, receipt=replace(rejected.receipt, outcome="reserved"))
    with pytest.raises(ValueError, match="exactly one"):
        replace(rejected, transitions=())


def test_state_snapshot_is_hash_chained_to_receipts_and_transition_records():
    state, _ = _apply(_state(), _request())
    state, _ = _apply(state, StartGrant(
        command_id="cmd-start-chain", grant_id="grant-1", fence_token=1,
        workload_sha256=_sha("workload-1"), observed_at="2026-08-07T11:00:01Z",
    ))
    state, _ = _apply(state, SettleGrant(
        command_id="cmd-overrun-chain", grant_id="grant-1", fence_token=1,
        workload_sha256=_sha("workload-1"),
        observed_at="2026-08-07T11:10:00Z",
        usage=_usage(ResourceVector(401, 200, 80), "chain-overrun"),
    ))

    forged_actual = ResourceVector(450, 200, 80)
    forged_grant = replace(state.grants[0], actual=forged_actual)
    with pytest.raises(ValueError, match="diverges from the retained journal"):
        replace(state, grants=(forged_grant,), spent=forged_actual)

    forged_record = replace(
        state.command_records[-1],
        transition_sha256="0" * 64,
    )
    with pytest.raises(ValueError, match="transition hash"):
        replace(
            state,
            command_records=state.command_records[:-1] + (forged_record,),
        )

    with pytest.raises(ValueError, match="must exceed"):
        replace(
            state.grants[0],
            actual=ResourceVector(400, 200, 80),
        )


def test_empty_journal_cannot_smuggle_a_phantom_reservation_into_genesis():
    reserved, _decision = _apply(_state(), _request())

    with pytest.raises(ValueError, match="empty journal.*budget genesis"):
        replace(
            reserved,
            revision=0,
            command_records=(),
        )


def test_retained_journal_replays_semantics_not_only_self_consistent_hashes():
    import lakatos.resource_coordination as resource_module

    state, _decision = _apply(
        _state(wall=100, input_tokens=100, output_tokens=20),
        _request(wall=101, input_tokens=1, output_tokens=1),
    )
    record = state.command_records[0]
    forged_receipt = replace(
        record.receipt,
        outcome="reserved",
        failure_code=None,
        failure_detail=None,
        failure_dimensions=(),
    )
    forged_receipt_sha256 = forged_receipt.receipt_sha256
    forged_transition = replace(
        record.transition,
        receipt=forged_receipt,
        receipt_sha256=forged_receipt_sha256,
        transition_sha256=resource_module._canonical_sha(
            resource_module._transition_envelope(
                record.transition.transition_payload_sha256,
                forged_receipt_sha256,
            )
        ),
    )
    forged_record = replace(
        record,
        receipt=forged_receipt,
        receipt_sha256=forged_receipt_sha256,
        transition_sha256=forged_transition.transition_sha256,
        transition=forged_transition,
    )

    with pytest.raises(ValueError, match="deterministic semantic replay"):
        replace(state, command_records=(forged_record,))
