"""Pure canonical codec and hash-chain functions for the resource journal."""

from __future__ import annotations

from lakatos.io._resource_journal_contracts import (
    ANCHOR_SCHEMA_VERSION,
    CODEC_VERSION,
    JOURNAL_SCHEMA_VERSION,
    JournalCorruption,
    ResourceCheckpoint,
    _JOURNAL_DOMAIN,
    _canonical_bytes,
    _decode_canonical_blob,
    _expect_keys,
    _expect_mapping,
    _sha256_bytes,
)
from lakatos.resource_coordination import (
    CancelGrant,
    DeadlineObserved,
    ENGINE_RULE_SHA256,
    GrantStatus,
    RequestGrant,
    ResourceBudget,
    ResourceCommand,
    ResourceEstimate,
    ResourceGrant,
    ResourceReceipt,
    ResourceState,
    ResourceTransition,
    ResourceUsage,
    ResourceVector,
    SCHEMA_VERSION,
    SettleGrant,
    StartGrant,
    UsageUnknown,
)


def _budget_blob(budget: ResourceBudget) -> bytes:
    return _canonical_bytes({"codec_version": CODEC_VERSION, "budget": budget.to_dict()})


def _budget_from_blob(blob: object) -> ResourceBudget:
    envelope = _decode_canonical_blob(blob, "resource budget")
    _expect_keys(envelope, {"codec_version", "budget"}, "resource budget envelope")
    if envelope["codec_version"] != CODEC_VERSION:
        raise JournalCorruption("resource budget codec is unsupported")
    value = _expect_mapping(envelope["budget"], "resource budget payload")
    _expect_keys(
        value,
        {"schema_version", "budget_id", "scope", "epoch", "hard_caps"},
        "resource budget payload",
    )
    return ResourceBudget(
        schema_version=value["schema_version"],
        budget_id=value["budget_id"],
        scope=value["scope"],
        epoch=value["epoch"],
        hard_caps=ResourceVector.from_dict(
            _expect_mapping(value["hard_caps"], "budget hard caps")
        ),
    )


def _estimate_from_dict(value: dict) -> ResourceEstimate:
    _expect_keys(
        value,
        {
            "schema_version",
            "work_id",
            "attempt_id",
            "workload_sha256",
            "adapter",
            "adapter_version",
            "upper_bound",
            "valid_until",
            "expected",
        },
        "resource estimate",
    )
    expected = value["expected"]
    return ResourceEstimate(
        schema_version=value["schema_version"],
        work_id=value["work_id"],
        attempt_id=value["attempt_id"],
        workload_sha256=value["workload_sha256"],
        adapter=value["adapter"],
        adapter_version=value["adapter_version"],
        upper_bound=ResourceVector.from_dict(
            _expect_mapping(value["upper_bound"], "estimate upper bound")
        ),
        valid_until=value["valid_until"],
        expected=(
            None
            if expected is None
            else ResourceVector.from_dict(_expect_mapping(expected, "estimate expected"))
        ),
    )


def _usage_from_dict(value: dict) -> ResourceUsage:
    _expect_keys(
        value,
        {
            "schema_version",
            "actual",
            "measured_at",
            "measurement_sha256",
            "evidence_sha256",
        },
        "resource usage",
    )
    return ResourceUsage(
        schema_version=value["schema_version"],
        actual=ResourceVector.from_dict(_expect_mapping(value["actual"], "usage actual")),
        measured_at=value["measured_at"],
        measurement_sha256=value["measurement_sha256"],
        evidence_sha256=value["evidence_sha256"],
    )


def _command_from_dict(value: dict) -> ResourceCommand:
    operation = value.get("type")
    base = {"type", "command_id", "grant_id", "fence_token", "observed_at"}
    if operation == "request_grant":
        _expect_keys(value, base | {"expires_at", "estimate"}, "request_grant command")
        return RequestGrant(
            command_id=value["command_id"],
            grant_id=value["grant_id"],
            fence_token=value["fence_token"],
            observed_at=value["observed_at"],
            expires_at=value["expires_at"],
            estimate=_estimate_from_dict(
                _expect_mapping(value["estimate"], "request estimate")
            ),
        )
    grant_base = base | {"workload_sha256"}
    if operation == "start_grant":
        _expect_keys(value, grant_base, "start_grant command")
        return StartGrant(**{key: value[key] for key in grant_base if key != "type"})
    if operation == "deadline_observed":
        _expect_keys(value, grant_base, "deadline_observed command")
        return DeadlineObserved(**{key: value[key] for key in grant_base if key != "type"})
    if operation == "cancel_grant":
        _expect_keys(value, grant_base | {"reason"}, "cancel_grant command")
        return CancelGrant(
            **{key: value[key] for key in grant_base if key != "type"},
            reason=value["reason"],
        )
    if operation == "usage_unknown":
        _expect_keys(value, grant_base | {"reason"}, "usage_unknown command")
        return UsageUnknown(
            **{key: value[key] for key in grant_base if key != "type"},
            reason=value["reason"],
        )
    if operation == "settle_grant":
        _expect_keys(value, grant_base | {"usage"}, "settle_grant command")
        return SettleGrant(
            **{key: value[key] for key in grant_base if key != "type"},
            usage=_usage_from_dict(_expect_mapping(value["usage"], "settlement usage")),
        )
    raise ValueError(f"unsupported durable resource command type: {operation!r}")


def _grant_from_dict(value: dict) -> ResourceGrant:
    expected = {
        "schema_version",
        "grant_id",
        "estimate_sha256",
        "workload_sha256",
        "reserved",
        "reserved_at",
        "expires_at",
        "fence_token",
        "status",
        "last_observed_at",
        "started_at",
        "actual",
        "measured_at",
        "measurement_sha256",
        "evidence_sha256",
        "cancel_requested",
    }
    _expect_keys(value, expected, "resource grant")
    return ResourceGrant(
        schema_version=value["schema_version"],
        grant_id=value["grant_id"],
        estimate_sha256=value["estimate_sha256"],
        workload_sha256=value["workload_sha256"],
        reserved=ResourceVector.from_dict(
            _expect_mapping(value["reserved"], "grant reserved")
        ),
        reserved_at=value["reserved_at"],
        expires_at=value["expires_at"],
        fence_token=value["fence_token"],
        status=GrantStatus(value["status"]),
        last_observed_at=value["last_observed_at"],
        started_at=value["started_at"],
        actual=ResourceVector.from_dict(_expect_mapping(value["actual"], "grant actual")),
        measured_at=value["measured_at"],
        measurement_sha256=value["measurement_sha256"],
        evidence_sha256=value["evidence_sha256"],
        cancel_requested=value["cancel_requested"],
    )


def _receipt_from_dict(value: dict) -> ResourceReceipt:
    expected = {
        "schema_version",
        "budget_id",
        "scope",
        "epoch",
        "operation",
        "outcome",
        "command_id",
        "command_sha256",
        "before_state_sha256",
        "after_state_sha256",
        "transition_payload_sha256",
        "before_revision",
        "after_revision",
        "grant_id",
        "reserved",
        "actual",
        "released",
        "failure_code",
        "failure_detail",
        "failure_dimensions",
        "evidence_sha256",
        "engine_rule_sha256",
    }
    _expect_keys(value, expected, "resource receipt")
    dimensions = value["failure_dimensions"]
    if not isinstance(dimensions, list):
        raise ValueError("receipt failure_dimensions must be a list on disk")
    return ResourceReceipt(
        schema_version=value["schema_version"],
        budget_id=value["budget_id"],
        scope=value["scope"],
        epoch=value["epoch"],
        operation=value["operation"],
        outcome=value["outcome"],
        command_id=value["command_id"],
        command_sha256=value["command_sha256"],
        before_state_sha256=value["before_state_sha256"],
        after_state_sha256=value["after_state_sha256"],
        transition_payload_sha256=value["transition_payload_sha256"],
        before_revision=value["before_revision"],
        after_revision=value["after_revision"],
        grant_id=value["grant_id"],
        reserved=ResourceVector.from_dict(
            _expect_mapping(value["reserved"], "receipt reserved")
        ),
        actual=ResourceVector.from_dict(_expect_mapping(value["actual"], "receipt actual")),
        released=ResourceVector.from_dict(
            _expect_mapping(value["released"], "receipt released")
        ),
        failure_code=value["failure_code"],
        failure_detail=value["failure_detail"],
        failure_dimensions=tuple(dimensions),
        evidence_sha256=value["evidence_sha256"],
        engine_rule_sha256=value["engine_rule_sha256"],
    )


def _transition_blob(transition: ResourceTransition) -> bytes:
    return _canonical_bytes(
        {
            "codec_version": CODEC_VERSION,
            "transition": {
                "command": transition.command.to_dict(),
                "command_sha256": transition.command_sha256,
                "transition_payload_sha256": transition.transition_payload_sha256,
                "receipt_sha256": transition.receipt_sha256,
                "transition_sha256": transition.transition_sha256,
                "grant": None if transition.grant is None else transition.grant.to_dict(),
                "spent_delta": transition.spent_delta.to_dict(),
                "freeze_budget": transition.freeze_budget,
                "receipt": transition.receipt.to_dict(),
            },
        }
    )


def _transition_from_blob(blob: object) -> ResourceTransition:
    envelope = _decode_canonical_blob(blob, "resource transition")
    _expect_keys(envelope, {"codec_version", "transition"}, "transition envelope")
    if envelope["codec_version"] != CODEC_VERSION:
        raise JournalCorruption("resource transition codec is unsupported")
    value = _expect_mapping(envelope["transition"], "transition payload")
    _expect_keys(
        value,
        {
            "command",
            "command_sha256",
            "transition_payload_sha256",
            "receipt_sha256",
            "transition_sha256",
            "grant",
            "spent_delta",
            "freeze_budget",
            "receipt",
        },
        "transition payload",
    )
    grant = value["grant"]
    return ResourceTransition(
        command=_command_from_dict(_expect_mapping(value["command"], "transition command")),
        command_sha256=value["command_sha256"],
        transition_payload_sha256=value["transition_payload_sha256"],
        receipt_sha256=value["receipt_sha256"],
        transition_sha256=value["transition_sha256"],
        grant=(
            None
            if grant is None
            else _grant_from_dict(_expect_mapping(grant, "transition grant"))
        ),
        spent_delta=ResourceVector.from_dict(
            _expect_mapping(value["spent_delta"], "transition spent_delta")
        ),
        freeze_budget=value["freeze_budget"],
        receipt=_receipt_from_dict(_expect_mapping(value["receipt"], "transition receipt")),
    )


def _journal_head_sha256(
    *,
    budget: ResourceBudget,
    revision: int,
    state_sha256: str,
    previous_journal_head_sha256: str | None,
    command_id: str | None,
    command_sha256: str | None,
    transition_sha256: str | None,
    receipt_sha256: str | None,
) -> str:
    payload = {
        "journal_schema_version": JOURNAL_SCHEMA_VERSION,
        "codec_version": CODEC_VERSION,
        "kernel_schema_version": SCHEMA_VERSION,
        "engine_rule_sha256": ENGINE_RULE_SHA256,
        "budget": budget.to_dict(),
        "revision": revision,
        "state_sha256": state_sha256,
        "previous_journal_head_sha256": previous_journal_head_sha256,
        "command_id": command_id,
        "command_sha256": command_sha256,
        "transition_sha256": transition_sha256,
        "receipt_sha256": receipt_sha256,
    }
    return _sha256_bytes(_JOURNAL_DOMAIN + _canonical_bytes(payload))


def _checkpoint_for(
    state: ResourceState,
    *,
    previous_journal_head_sha256: str | None,
    transition: ResourceTransition | None,
) -> ResourceCheckpoint:
    command = None if transition is None else transition.command
    head = _journal_head_sha256(
        budget=state.budget,
        revision=state.revision,
        state_sha256=state.snapshot_sha256,
        previous_journal_head_sha256=previous_journal_head_sha256,
        command_id=None if command is None else command.command_id,
        command_sha256=None if transition is None else transition.command_sha256,
        transition_sha256=None if transition is None else transition.transition_sha256,
        receipt_sha256=None if transition is None else transition.receipt_sha256,
    )
    return ResourceCheckpoint(
        schema_version=ANCHOR_SCHEMA_VERSION,
        codec_version=CODEC_VERSION,
        kernel_schema_version=SCHEMA_VERSION,
        engine_rule_sha256=ENGINE_RULE_SHA256,
        budget_id=state.budget_id,
        scope=state.scope,
        epoch=state.epoch,
        revision=state.revision,
        state_sha256=state.snapshot_sha256,
        journal_head_sha256=head,
        previous_journal_head_sha256=previous_journal_head_sha256,
        command_id=None if command is None else command.command_id,
        command_sha256=None if transition is None else transition.command_sha256,
        transition_sha256=None if transition is None else transition.transition_sha256,
        receipt_sha256=None if transition is None else transition.receipt_sha256,
    )


__all__ = [
    "_budget_blob",
    "_budget_from_blob",
    "_checkpoint_for",
    "_journal_head_sha256",
    "_transition_blob",
    "_transition_from_blob",
]
