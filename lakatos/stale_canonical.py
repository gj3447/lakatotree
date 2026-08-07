"""Pure planning for stale-CANONICAL sweeps.

The module owns deterministic classification and receipt/effect planning.  It
does not read the rule-floor file, capture time, query a store, execute CAS
mutations, or project history.  Those capabilities stay in the application
shell and are passed in as immutable observations.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass
import re
from typing import Protocol

from lakatos.node_state import NodeState
from lakatos.verdicts import receipt_content_sha


SCHEMA_VERSION = "lakatotree.stale-canonical-sweep-plan/v1"
FORMER_CANONICAL_VERDICT = "former_canonical"
ENGINE_VERDICT_SOURCE = "engine"
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_RFC3339_RE = re.compile(
    r"(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})T"
    r"(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})"
    r"(?:\.\d+)?(?:Z|[+-](?P<offset_hour>\d{2}):(?P<offset_minute>\d{2}))\Z"
)


def _require_text(value: object, field: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")


def _require_non_empty_text(value: object, field: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")


def _require_sha256(value: object, field: str) -> None:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{field} must be a lowercase SHA-256")


def _require_optional_text(value: object, field: str) -> None:
    if value is not None:
        # Neo4j's legacy representation used both null and the empty string.
        # They are distinct receipt preimages, so preserve either verbatim.
        _require_text(value, field)


def _require_rfc3339(value: object, field: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an RFC3339 timestamp")
    match = _RFC3339_RE.fullmatch(value)
    if match is None:
        raise ValueError(f"{field} must be an RFC3339 timestamp")

    parts = {key: int(number) for key, number in match.groupdict().items() if number}
    year = parts["year"]
    month = parts["month"]
    day = parts["day"]
    leap_year = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    days_in_month = (
        31,
        29 if leap_year else 28,
        31,
        30,
        31,
        30,
        31,
        31,
        30,
        31,
        30,
        31,
    )
    valid = (
        year >= 1
        and 1 <= month <= 12
        and 1 <= day <= days_in_month[month - 1]
        and 0 <= parts["hour"] <= 23
        and 0 <= parts["minute"] <= 59
        and 0 <= parts["second"] <= 59
        and parts.get("offset_hour", 0) <= 23
        and parts.get("offset_minute", 0) <= 59
    )
    if not valid:
        raise ValueError(f"{field} must be an RFC3339 timestamp")


def _is_ordered_subset(subset: tuple[object, ...], whole: tuple[object, ...]) -> bool:
    cursor = 0
    for item in subset:
        while cursor < len(whole) and whole[cursor] != item:
            cursor += 1
        if cursor == len(whole):
            return False
        cursor += 1
    return True


@dataclass(frozen=True, slots=True)
class CanonicalHeadSnapshot:
    """One CANONICAL head observed by the effect shell."""

    tag: str
    previous_receipt_sha: str | None
    sealed_engine_rule_sha: str | None
    valid_until_rebutted: bool

    def __post_init__(self) -> None:
        _require_non_empty_text(self.tag, "tag")
        _require_optional_text(self.previous_receipt_sha, "previous_receipt_sha")
        _require_optional_text(self.sealed_engine_rule_sha, "sealed_engine_rule_sha")
        if type(self.valid_until_rebutted) is not bool:
            raise ValueError("valid_until_rebutted must be a boolean")


@dataclass(frozen=True, slots=True)
class StaleCanonicalSweepDecision:
    """Immutable classification result in source-query order."""

    schema_version: str
    tree: str
    dry_run: bool
    floor_size: int
    canonical_total: int
    candidates: tuple[CanonicalHeadSnapshot, ...]
    skipped_locked: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported stale sweep schema: {self.schema_version}")
        # The existing HTTP/service contract accepts ``tree=`` and returns an
        # empty projection.  This DTO preserves that compatibility boundary.
        _require_text(self.tree, "tree")
        if type(self.dry_run) is not bool:
            raise ValueError("dry_run must be a boolean")
        if type(self.floor_size) is not int or self.floor_size < 0:
            raise ValueError("floor_size must be a non-negative integer")
        if type(self.canonical_total) is not int or self.canonical_total < 0:
            raise ValueError("canonical_total must be a non-negative integer")
        if not isinstance(self.candidates, tuple):
            raise ValueError("candidates must be a tuple")
        if any(
            not isinstance(candidate, CanonicalHeadSnapshot)
            for candidate in self.candidates
        ):
            raise ValueError("candidates must contain CanonicalHeadSnapshot values")
        if not isinstance(self.skipped_locked, tuple):
            raise ValueError("skipped_locked must be a tuple")
        if len(self.candidates) + len(self.skipped_locked) > self.canonical_total:
            raise ValueError("stale partition exceeds canonical_total")
        if any(not isinstance(tag, str) or not tag for tag in self.skipped_locked):
            raise ValueError("skipped_locked must contain non-empty strings")


def _validate_demotion_payload(
    *,
    schema_version: str,
    tree: str,
    tag: str,
    previous_receipt_sha: str | None,
    sealed_engine_rule_sha: str | None,
    expected_valid_until_rebutted: bool,
    node_state: str,
    verdict: str,
    verdict_source: str,
) -> None:
    if schema_version != SCHEMA_VERSION:
        raise ValueError(f"unsupported stale sweep schema: {schema_version}")
    # Preserve the existing ``tree=`` compatibility boundary.
    _require_text(tree, "tree")
    _require_non_empty_text(tag, "tag")
    _require_optional_text(previous_receipt_sha, "previous_receipt_sha")
    _require_optional_text(sealed_engine_rule_sha, "sealed_engine_rule_sha")
    if type(expected_valid_until_rebutted) is not bool:
        raise ValueError("expected_valid_until_rebutted must be a boolean")
    if node_state != NodeState.FORMER_CANONICAL.value:
        raise ValueError("stale demotion plan has an invalid node_state")
    if verdict != FORMER_CANONICAL_VERDICT:
        raise ValueError("stale demotion plan has an invalid verdict")
    if verdict_source != ENGINE_VERDICT_SOURCE:
        raise ValueError("stale demotion plan has an invalid verdict_source")


@dataclass(frozen=True, slots=True)
class StaleCanonicalDemotionDraft:
    """Effect selection validated before predecessor projection or clock use."""

    schema_version: str
    tree: str
    tag: str
    previous_receipt_sha: str | None
    sealed_engine_rule_sha: str | None
    expected_valid_until_rebutted: bool
    node_state: str
    verdict: str
    verdict_source: str

    def __post_init__(self) -> None:
        _validate_demotion_payload(
            schema_version=self.schema_version,
            tree=self.tree,
            tag=self.tag,
            previous_receipt_sha=self.previous_receipt_sha,
            sealed_engine_rule_sha=self.sealed_engine_rule_sha,
            expected_valid_until_rebutted=self.expected_valid_until_rebutted,
            node_state=self.node_state,
            verdict=self.verdict,
            verdict_source=self.verdict_source,
        )


@dataclass(frozen=True, slots=True)
class StaleCanonicalDemotionPlan:
    """One sealed CAS mutation and its content-addressed receipt identity."""

    schema_version: str
    tree: str
    tag: str
    previous_receipt_sha: str | None
    sealed_engine_rule_sha: str | None
    expected_valid_until_rebutted: bool
    judged_at: str
    receipt_sha: str
    engine_rule_sha: str
    node_state: str
    verdict: str
    verdict_source: str

    def __post_init__(self) -> None:
        _validate_demotion_payload(
            schema_version=self.schema_version,
            tree=self.tree,
            tag=self.tag,
            previous_receipt_sha=self.previous_receipt_sha,
            sealed_engine_rule_sha=self.sealed_engine_rule_sha,
            expected_valid_until_rebutted=self.expected_valid_until_rebutted,
            node_state=self.node_state,
            verdict=self.verdict,
            verdict_source=self.verdict_source,
        )
        _require_rfc3339(self.judged_at, "judged_at")
        _require_sha256(self.receipt_sha, "receipt_sha")
        _require_sha256(self.engine_rule_sha, "engine_rule_sha")
        fields = {
            "tree": self.tree,
            "tag": self.tag,
            "target_id": None,
            "verdict": self.verdict,
            "verdict_source": self.verdict_source,
            "metric_name": None,
            "metric_value": None,
            "novel_confirmed": None,
            "lakatos_status": None,
            "judged_at": self.judged_at,
            "judge_script_sha": None,
            "prev_receipt_sha": self.previous_receipt_sha,
            "engine_rule_sha": self.engine_rule_sha,
        }
        if self.receipt_sha != receipt_content_sha(fields):
            raise ValueError("receipt_sha does not match demotion content")


class StaleSweepDecider(Protocol):
    def __call__(
        self,
        *,
        tree: str,
        heads: tuple[CanonicalHeadSnapshot, ...],
        effective_floor: Collection[str],
        dry_run: bool,
    ) -> StaleCanonicalSweepDecision: ...


class StaleDemotionPlanner(Protocol):
    def __call__(
        self,
        decision: StaleCanonicalSweepDecision,
    ) -> tuple[StaleCanonicalDemotionDraft, ...]: ...


def decide_stale_canonical_sweep(
    *,
    tree: str,
    heads: tuple[CanonicalHeadSnapshot, ...],
    effective_floor: Collection[str],
    dry_run: bool,
) -> StaleCanonicalSweepDecision:
    """Partition observed heads without effects or ambient authority.

    Only the exact boolean ``False`` is an operator lock, matching the durable
    query contract.  Input order is deliberately retained because it is part
    of the existing response and mutation order.
    """

    stale = tuple(
        head
        for head in heads
        if head.sealed_engine_rule_sha not in effective_floor
    )
    return StaleCanonicalSweepDecision(
        schema_version=SCHEMA_VERSION,
        tree=tree,
        dry_run=dry_run,
        floor_size=len(effective_floor),
        canonical_total=len(heads),
        candidates=tuple(
            head for head in stale if head.valid_until_rebutted is not False
        ),
        skipped_locked=tuple(
            head.tag for head in stale if head.valid_until_rebutted is False
        ),
    )


def validate_stale_canonical_sweep_decision(
    proposed: StaleCanonicalSweepDecision,
    *,
    tree: str,
    heads: tuple[CanonicalHeadSnapshot, ...],
    effective_floor: Collection[str],
    dry_run: bool,
) -> StaleCanonicalSweepDecision:
    """Allow policy suppression but reject invented or reclassified heads."""

    expected = decide_stale_canonical_sweep(
        tree=tree,
        heads=heads,
        effective_floor=effective_floor,
        dry_run=dry_run,
    )
    fixed_fields_match = (
        proposed.schema_version == expected.schema_version
        and proposed.tree == expected.tree
        and proposed.dry_run == expected.dry_run
        and proposed.floor_size == expected.floor_size
        and proposed.canonical_total == expected.canonical_total
        and proposed.skipped_locked == expected.skipped_locked
    )
    if not fixed_fields_match or not _is_ordered_subset(
        proposed.candidates,
        expected.candidates,
    ):
        raise ValueError("stale sweep decision does not match observed heads")
    return proposed


def draft_stale_canonical_demotions(
    decision: StaleCanonicalSweepDecision,
) -> tuple[StaleCanonicalDemotionDraft, ...]:
    """Select immutable effects before any predecessor projection occurs."""

    if decision.dry_run:
        raise ValueError("cannot plan demotion effects for a dry-run decision")
    return tuple(
        StaleCanonicalDemotionDraft(
            schema_version=SCHEMA_VERSION,
            tree=decision.tree,
            tag=candidate.tag,
            previous_receipt_sha=candidate.previous_receipt_sha,
            sealed_engine_rule_sha=candidate.sealed_engine_rule_sha,
            expected_valid_until_rebutted=candidate.valid_until_rebutted,
            node_state=NodeState.FORMER_CANONICAL.value,
            verdict=FORMER_CANONICAL_VERDICT,
            verdict_source=ENGINE_VERDICT_SOURCE,
        )
        for candidate in decision.candidates
    )


def validate_stale_canonical_demotion_drafts(
    decision: StaleCanonicalSweepDecision,
    drafts: Iterable[StaleCanonicalDemotionDraft],
) -> tuple[StaleCanonicalDemotionDraft, ...]:
    """Allow ordered suppression but reject invented or forged effects."""

    proposed = tuple(drafts)
    expected = draft_stale_canonical_demotions(decision)
    if not _is_ordered_subset(proposed, expected):
        raise ValueError("demotion draft does not match the observed decision")
    return proposed


def seal_stale_canonical_demotions(
    decision: StaleCanonicalSweepDecision,
    drafts: Iterable[StaleCanonicalDemotionDraft],
    *,
    judged_at: str,
    engine_rule_sha: str,
) -> tuple[StaleCanonicalDemotionPlan, ...]:
    """Bind validated drafts to one captured clock and receipt authority."""

    selected = validate_stale_canonical_demotion_drafts(decision, drafts)
    plans = []
    for draft in selected:
        fields = {
            "tree": draft.tree,
            "tag": draft.tag,
            "target_id": None,
            "verdict": draft.verdict,
            "verdict_source": draft.verdict_source,
            "metric_name": None,
            "metric_value": None,
            "novel_confirmed": None,
            "lakatos_status": None,
            "judged_at": judged_at,
            "judge_script_sha": None,
            "prev_receipt_sha": draft.previous_receipt_sha,
            "engine_rule_sha": engine_rule_sha,
        }
        plans.append(
            StaleCanonicalDemotionPlan(
                schema_version=SCHEMA_VERSION,
                tree=draft.tree,
                tag=draft.tag,
                previous_receipt_sha=draft.previous_receipt_sha,
                sealed_engine_rule_sha=draft.sealed_engine_rule_sha,
                expected_valid_until_rebutted=draft.expected_valid_until_rebutted,
                judged_at=judged_at,
                receipt_sha=receipt_content_sha(fields),
                engine_rule_sha=engine_rule_sha,
                node_state=draft.node_state,
                verdict=draft.verdict,
                verdict_source=draft.verdict_source,
            )
        )
    return tuple(plans)


def plan_stale_canonical_demotions(
    decision: StaleCanonicalSweepDecision,
    *,
    judged_at: str,
    engine_rule_sha: str,
) -> tuple[StaleCanonicalDemotionPlan, ...]:
    """Convenience composition of the canonical draft and seal functions."""

    return seal_stale_canonical_demotions(
        decision,
        draft_stale_canonical_demotions(decision),
        judged_at=judged_at,
        engine_rule_sha=engine_rule_sha,
    )


def validate_stale_canonical_demotion_plans(
    decision: StaleCanonicalSweepDecision,
    plans: Iterable[StaleCanonicalDemotionPlan],
    *,
    judged_at: str,
    engine_rule_sha: str,
) -> tuple[StaleCanonicalDemotionPlan, ...]:
    """Fail closed unless plans are an ordered canonical-plan subset."""

    proposed = tuple(plans)
    expected = plan_stale_canonical_demotions(
        decision,
        judged_at=judged_at,
        engine_rule_sha=engine_rule_sha,
    )
    if not _is_ordered_subset(proposed, expected):
        raise ValueError("demotion plan does not match the observed decision")
    return proposed


def project_stale_canonical_sweep(
    decision: StaleCanonicalSweepDecision,
    *,
    demoted: Iterable[str] = (),
) -> dict:
    """Project the stable compatibility response at the imperative boundary."""

    return {
        "tree": decision.tree,
        "dry_run": decision.dry_run,
        "floor_size": decision.floor_size,
        "canonical_total": decision.canonical_total,
        "candidates": [
            {
                "tag": candidate.tag,
                "sealed_engine_rule_sha": candidate.sealed_engine_rule_sha,
            }
            for candidate in decision.candidates
        ],
        "skipped_locked": list(decision.skipped_locked),
        "demoted": list(demoted),
    }


__all__ = [
    "SCHEMA_VERSION",
    "ENGINE_VERDICT_SOURCE",
    "FORMER_CANONICAL_VERDICT",
    "CanonicalHeadSnapshot",
    "StaleCanonicalDemotionDraft",
    "StaleCanonicalDemotionPlan",
    "StaleCanonicalSweepDecision",
    "StaleDemotionPlanner",
    "StaleSweepDecider",
    "decide_stale_canonical_sweep",
    "draft_stale_canonical_demotions",
    "plan_stale_canonical_demotions",
    "project_stale_canonical_sweep",
    "seal_stale_canonical_demotions",
    "validate_stale_canonical_demotion_drafts",
    "validate_stale_canonical_demotion_plans",
    "validate_stale_canonical_sweep_decision",
]
