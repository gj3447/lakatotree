"""Claim standing read-model.

상계(internet/human/kg)와 하계(bash/data/git/agent)의 evidence 를 분리해
한 claim 이 현재 어디서 막히는지, 어느 정도 confidence 로 서는지 계산한다.
순수 read-model 이라 KG/HTTP/DB 에 의존하지 않는다.
# KG: span_lakatotree_claim_standing
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from lakatos.engine import (
    FoundationGate,
    FoundationMap,
    Realm,
    ResearchEvent,
    ResearchFrame,
    _clamp01,
)
from lakatos.io.replay import LineageReplayResult   # P8: _clamp01 단일 정본(engine)
from lakatos.grounding import GROUNDED   # P6-3: confidence 문턱 단일 정본


UPPER_REALMS = {Realm.INTERNET, Realm.HUMAN, Realm.KG}
LOWER_REALMS = {Realm.BASH, Realm.DATA, Realm.GIT, Realm.AGENT}

# P7-A(GROUND-2/LKT-T3-1): 증거 confidence 기본값 단일 정본 (전엔 inline dict/literal 하드코딩).
_ACT_CONF = GROUNDED['evidence_action_confidence']['value']
_REALM_CONF = GROUNDED['evidence_realm_confidence']['value']


@dataclass(frozen=True)
class ClaimStandingPolicy:
    """Claim standing 을 판정할 때 필요한 운영 정책."""

    require_upper: bool = True
    require_lower: bool = True
    require_foundation: bool = True
    require_replay: bool = False
    min_confidence: float = GROUNDED['claim_min_confidence']['value']
    strong_confidence: float = GROUNDED['claim_strong_confidence']['value']


@dataclass(frozen=True)
class ClaimNextAction:
    """A machine-readable repair hint for a blocked claim."""

    reason: str
    action: str
    realm: str = ""
    target: str = ""
    hint: str = ""

    def to_dict(self) -> dict:
        return {
            "reason": self.reason,
            "action": self.action,
            "realm": self.realm,
            "target": self.target,
            "hint": self.hint,
        }


@dataclass(frozen=True)
class ClaimStanding:
    claim: str
    stands: bool
    status: str
    confidence: float
    upper_confidence: float
    lower_confidence: float
    blocking_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    realms: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    unresolved_doubts: tuple[str, ...] = ()
    foundation_gaps: tuple[str, ...] = ()
    lineage_reasons: tuple[str, ...] = ()
    next_actions: tuple[ClaimNextAction, ...] = ()

    def to_dict(self) -> dict:
        return {
            "claim": self.claim,
            "stands": self.stands,
            "status": self.status,
            "confidence": self.confidence,
            "upper_confidence": self.upper_confidence,
            "lower_confidence": self.lower_confidence,
            "blocking_reasons": list(self.blocking_reasons),
            "warnings": list(self.warnings),
            "realms": list(self.realms),
            "evidence_refs": list(self.evidence_refs),
            "unresolved_doubts": list(self.unresolved_doubts),
            "foundation_gaps": list(self.foundation_gaps),
            "lineage_reasons": list(self.lineage_reasons),
            "next_actions": [a.to_dict() for a in self.next_actions],
        }


def _payload(event: ResearchEvent) -> dict[str, str]:
    return dict(event.payload)


def _payload_float(payload: dict[str, str], *keys: str) -> float | None:
    for key in keys:
        value = payload.get(key)
        if value is None or value == "":
            continue
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(parsed):    # NaN/inf = malformed → realm default 로 폴백
            continue                     # (전엔 _clamp01(nan)=1.0 = 조용한 최대신뢰 버그)
        return _clamp01(parsed)
    return None


def _action(event: ResearchEvent) -> str:
    return event.action.lower().replace("-", "_")


def _is_doubt(event: ResearchEvent) -> bool:
    if event.realm is not Realm.HUMAN:
        return False
    action = _action(event)
    if action.startswith(("resolve_", "close_")) or action in {"rebuttal", "human_verdict"}:
        return False
    return action in {"doubt", "question", "challenge", "block"} or "doubt" in action


def _resolved_doubt_ids(events: tuple[ResearchEvent, ...]) -> set[str]:
    resolved = set()
    for event in events:
        if event.realm is not Realm.HUMAN:
            continue
        action = _action(event)
        payload = _payload(event)
        if action in {"resolve_doubt", "close_doubt", "rebuttal", "human_verdict"}:
            for key in ("resolves", "resolves_doubt", "closes", "closes_doubt"):
                if payload.get(key):
                    resolved.add(payload[key])
    return resolved


def _event_confidence(event: ResearchEvent) -> float:
    payload = _payload(event)
    explicit = _payload_float(payload, "confidence", "trust", "credence", "score")
    if explicit is not None:
        return explicit

    action = _action(event)
    if _is_doubt(event):
        return _ACT_CONF["doubt"]
    if payload.get("exit_code") == "0":
        return _ACT_CONF["pass"]
    if payload.get("exit_code") not in (None, "", "0"):
        return _ACT_CONF["fail"]
    if any(token in action for token in ("fail", "reject", "error")):
        return _ACT_CONF["fail"]
    if any(token in action for token in ("pass", "success", "replay")):
        return _ACT_CONF["pass"]
    if any(token in action for token in ("verdict", "accept", "approve", "resolve")):
        return _ACT_CONF["verdict"]

    return _REALM_CONF[event.realm.name]


def _combine(scores: list[float]) -> float:
    if not scores:
        return 0.0
    miss = 1.0
    for score in scores:
        miss *= 1.0 - _clamp01(score)
    return round(1.0 - miss, 4)


def _action_for_blocker(reason: str) -> ClaimNextAction:
    if reason == "foundation:missing":
        return ClaimNextAction(
            reason=reason,
            action="record_foundation_map",
            realm=Realm.KG.value,
            hint="add foundation requirements before promoting this claim",
        )
    if reason.startswith("foundation:"):
        target = reason.split(":", 1)[1]
        return ClaimNextAction(
            reason=reason,
            action="satisfy_foundation_requirement",
            realm=Realm.KG.value,
            target=target,
            hint="append evidence_refs or waive the requirement explicitly",
        )
    if reason.startswith("human_doubt:"):
        target = reason.split(":", 1)[1]
        return ClaimNextAction(
            reason=reason,
            action="resolve_human_doubt",
            realm=Realm.HUMAN.value,
            target=target,
            hint=f"append ResearchEvent action=resolve_doubt payload resolves={target}",
        )
    if reason == "lineage:missing":
        return ClaimNextAction(
            reason=reason,
            action="record_lineage",
            realm=Realm.DATA.value,
            hint="record derivations or rerun claim-standing with replay disabled",
        )
    if reason.startswith("lineage:"):
        target = reason.split(":", 1)[1]
        return ClaimNextAction(
            reason=reason,
            action="run_rebuild_or_refresh_lineage",
            realm=Realm.BASH.value,
            target=target,
            hint="run rebuild-verify/rebuild-run, then append the result as lower evidence",
        )
    if reason == "evidence:missing_refs":
        return ClaimNextAction(
            reason=reason,
            action="attach_evidence_refs",
            realm=Realm.KG.value,
            hint="record source, artifact, command, or review refs for this claim",
        )
    if reason == "upper_confidence_below_threshold":
        return ClaimNextAction(
            reason=reason,
            action="add_upper_world_evidence",
            realm="internet|human|kg",
            hint="append internet, human, or KG ResearchEvent with confidence/trust",
        )
    if reason == "lower_confidence_below_threshold":
        return ClaimNextAction(
            reason=reason,
            action="add_lower_world_evidence",
            realm="bash|data|git|agent",
            hint="append bash/data/git/agent ResearchEvent from a reproducible observation",
        )
    return ClaimNextAction(
        reason=reason,
        action="investigate_blocker",
        hint="inspect the claim event stream and add a specific evidence event",
    )


def _next_actions(blocking_reasons: tuple[str, ...], warnings: tuple[str, ...]) -> tuple[ClaimNextAction, ...]:
    actions = [_action_for_blocker(reason) for reason in blocking_reasons]
    if "lineage:not_checked" in warnings:
        actions.append(
            ClaimNextAction(
                reason="lineage:not_checked",
                action="check_lineage_replay",
                realm=Realm.DATA.value,
                hint="run claim-standing with replay enabled before treating the claim as final",
            )
        )
    deduped: dict[tuple[str, str, str], ClaimNextAction] = {}
    for action in actions:
        deduped.setdefault((action.reason, action.action, action.target), action)
    return tuple(deduped.values())


def evaluate_claim_standing(
    claim: str,
    *,
    frame: ResearchFrame,
    foundation: FoundationMap | None = None,
    lineage: LineageReplayResult | None = None,
    policy: ClaimStandingPolicy | None = None,
) -> ClaimStanding:
    """한 claim 의 현재 standing 을 계산한다."""
    policy = policy or ClaimStandingPolicy()
    standing = frame.standing(claim)
    events = frame.events_for(claim)
    evidence_refs = sorted({ref for e in events for ref in e.evidence_refs} | set(standing["evidence_refs"]))
    realms = tuple(sorted({e.realm.value for e in events}))

    upper_scores = [_event_confidence(e) for e in events if e.realm in UPPER_REALMS and not _is_doubt(e)]
    lower_scores = [_event_confidence(e) for e in events if e.realm in LOWER_REALMS]
    if lineage is not None and lineage.passed:
        lower_scores.append(0.85)

    upper_confidence = _combine(upper_scores)
    lower_confidence = _combine(lower_scores)

    active_scores = []
    if policy.require_upper:
        active_scores.append(upper_confidence)
    if policy.require_lower:
        active_scores.append(lower_confidence)
    confidence = round(min(active_scores), 4) if active_scores else round(max(upper_confidence, lower_confidence), 4)

    blocking: list[str] = []
    foundation_gaps: tuple[str, ...] = ()
    if policy.require_foundation:
        if foundation is None:
            blocking.append("foundation:missing")
        else:
            gate = FoundationGate.evaluate(foundation)
            foundation_gaps = tuple(gate.reasons)
            blocking.extend(f"foundation:{gap}" for gap in foundation_gaps)

    resolved = _resolved_doubt_ids(events)
    unresolved_doubts = tuple(e.name for e in events if _is_doubt(e) and e.name not in resolved)
    blocking.extend(f"human_doubt:{name}" for name in unresolved_doubts)

    lineage_reasons: tuple[str, ...] = ()
    if policy.require_replay:
        if lineage is None:
            blocking.append("lineage:missing")
            lineage_reasons = ("missing",)
        elif not lineage.passed:
            lineage_reasons = tuple(lineage.reasons)
            blocking.extend(f"lineage:{reason}" for reason in lineage_reasons)

    if not evidence_refs:
        blocking.append("evidence:missing_refs")
    if policy.require_upper and upper_confidence < policy.min_confidence:
        blocking.append("upper_confidence_below_threshold")
    if policy.require_lower and lower_confidence < policy.min_confidence:
        blocking.append("lower_confidence_below_threshold")

    unique_blocking = tuple(dict.fromkeys(blocking))
    stands = not unique_blocking
    if not stands:
        status = "blocked"
    elif confidence >= policy.strong_confidence:
        status = "stands"
    else:
        status = "conditional"

    warnings = []
    if lineage is None and not policy.require_replay:
        warnings.append("lineage:not_checked")
    warnings_tuple = tuple(warnings)

    return ClaimStanding(
        claim=claim,
        stands=stands,
        status=status,
        confidence=confidence,
        upper_confidence=upper_confidence,
        lower_confidence=lower_confidence,
        blocking_reasons=unique_blocking,
        realms=realms,
        evidence_refs=tuple(evidence_refs),
        unresolved_doubts=unresolved_doubts,
        foundation_gaps=foundation_gaps,
        lineage_reasons=lineage_reasons,
        warnings=warnings_tuple,
        next_actions=_next_actions(unique_blocking, warnings_tuple),
    )
