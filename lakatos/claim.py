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


# ── claim standing 구성요소 — 각 의미(신뢰도 결합 · blocking 사유 소스)가 자기 함수 ──────────
#   SRP: evaluate_claim_standing 은 오케스트레이터. blocking 은 5 소스(foundation/doubt/lineage/
#   evidence/confidence)에서 오는데 전엔 한 함수에 inline 융합돼 있었다 → 소스별 함수로 분해.
def _realm_confidences(events: tuple, lineage: 'LineageReplayResult | None') -> tuple[float, float]:
    """상계(internet/human/kg, 의문 제외) / 하계(bash/data/git/agent + lineage 통과) 신뢰도 결합."""
    upper = [_event_confidence(e) for e in events if e.realm in UPPER_REALMS and not _is_doubt(e)]
    lower = [_event_confidence(e) for e in events if e.realm in LOWER_REALMS]
    if lineage is not None and lineage.passed:
        lower.append(0.85)
    return _combine(upper), _combine(lower)


def _combined_confidence(upper: float, lower: float, policy: 'ClaimStandingPolicy') -> float:
    """정책이 요구하는 계의 최소값 — 둘 다 요구면 약한 쪽이 claim 을 끈다. 요구 없으면 max."""
    active = []
    if policy.require_upper:
        active.append(upper)
    if policy.require_lower:
        active.append(lower)
    return round(min(active), 4) if active else round(max(upper, lower), 4)


def _foundation_block(foundation: 'FoundationMap | None', policy) -> tuple[list[str], tuple[str, ...]]:
    """기반지식 게이트 blocking — 연구 전 기반지식 충족(한 의미)."""
    if not policy.require_foundation:
        return [], ()
    if foundation is None:
        return ["foundation:missing"], ()
    gaps = tuple(FoundationGate.evaluate(foundation).reasons)
    return [f"foundation:{g}" for g in gaps], gaps


def _doubt_block(events: tuple) -> tuple[list[str], tuple[str, ...]]:
    """미해소 인간/agent 의문 blocking — 막지 못한 의문이 있으면 stand 못 함."""
    resolved = _resolved_doubt_ids(events)
    unresolved = tuple(e.name for e in events if _is_doubt(e) and e.name not in resolved)
    return [f"human_doubt:{n}" for n in unresolved], unresolved


def _lineage_block(lineage: 'LineageReplayResult | None', policy) -> tuple[list[str], tuple[str, ...]]:
    """재현(lineage replay) 게이트 blocking — 하계 산출물이 root 서 재생성 가능한가."""
    if not policy.require_replay:
        return [], ()
    if lineage is None:
        return ["lineage:missing"], ("missing",)
    if not lineage.passed:
        reasons = tuple(lineage.reasons)
        return [f"lineage:{r}" for r in reasons], reasons
    return [], ()


def _confidence_evidence_block(upper: float, lower: float, evidence_refs: list, policy) -> list[str]:
    """증거 존재 + 신뢰도 문턱 blocking."""
    blocking = []
    if not evidence_refs:
        blocking.append("evidence:missing_refs")
    if policy.require_upper and upper < policy.min_confidence:
        blocking.append("upper_confidence_below_threshold")
    if policy.require_lower and lower < policy.min_confidence:
        blocking.append("lower_confidence_below_threshold")
    return blocking


def _standing_status(stands: bool, confidence: float, policy) -> str:
    if not stands:
        return "blocked"
    return "stands" if confidence >= policy.strong_confidence else "conditional"


def evaluate_claim_standing(
    claim: str,
    *,
    frame: ResearchFrame,
    foundation: FoundationMap | None = None,
    lineage: LineageReplayResult | None = None,
    policy: ClaimStandingPolicy | None = None,
) -> ClaimStanding:
    """한 claim 의 현재 standing — 상/하계 신뢰도 + 5 blocking 소스 합성(각 소스 = 자기 함수, 위 참조).
    blocking 순서 보존: foundation → doubt → lineage → evidence/confidence (dict.fromkeys 순서 dedup)."""
    policy = policy or ClaimStandingPolicy()
    standing = frame.standing(claim)
    events = frame.events_for(claim)
    evidence_refs = sorted({ref for e in events for ref in e.evidence_refs} | set(standing["evidence_refs"]))
    realms = tuple(sorted({e.realm.value for e in events}))

    upper_confidence, lower_confidence = _realm_confidences(events, lineage)
    confidence = _combined_confidence(upper_confidence, lower_confidence, policy)

    found_block, foundation_gaps = _foundation_block(foundation, policy)
    doubt_block, unresolved_doubts = _doubt_block(events)
    lin_block, lineage_reasons = _lineage_block(lineage, policy)
    conf_block = _confidence_evidence_block(upper_confidence, lower_confidence, evidence_refs, policy)
    unique_blocking = tuple(dict.fromkeys(found_block + doubt_block + lin_block + conf_block))

    stands = not unique_blocking
    status = _standing_status(stands, confidence, policy)
    warnings_tuple = ("lineage:not_checked",) if (lineage is None and not policy.require_replay) else ()

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
