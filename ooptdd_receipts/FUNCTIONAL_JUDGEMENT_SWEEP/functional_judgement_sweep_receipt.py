"""Hermetic OOPTDD receipt for one functional judgement-service slice."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lakatos.engine_identity import ENGINE_RULE_SHA  # noqa: E402
from lakatos.stale_canonical import (  # noqa: E402
    CanonicalHeadSnapshot,
    decide_stale_canonical_sweep,
    draft_stale_canonical_demotions,
    plan_stale_canonical_demotions,
)
from lakatos.verdicts import receipt_content_sha  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from server.contexts.tree.judgement_service import JudgementService  # noqa: E402


FIXED_NOW = datetime(2026, 8, 7, 18, 45, tzinfo=timezone.utc)
_HEAD_GUARD = "coalesce(e.current_receipt_sha,'') = coalesce($prev,'')"
_LOCK_GUARD = "coalesce(e.valid_until_rebutted,true)=$expected_vur"
_VERDICT_GUARD = "e.verdict='CANONICAL'"


def _is_and_conjunct(query: str, predicate: str) -> bool:
    """Accept only the production WHERE as a pure three-term conjunction."""

    try:
        where = query.split("WHERE", 1)[1].split("SET", 1)[0]
    except IndexError:
        return False
    normalized = lambda value: re.sub(r"\s+", "", value)
    actual = [normalized(part) for part in re.split(r"\bAND\b", where)]
    expected = [
        normalized(_VERDICT_GUARD),
        normalized(_HEAD_GUARD),
        normalized(_LOCK_GUARD),
    ]
    return len(actual) == len(expected) and set(actual) == set(expected) and (
        normalized(predicate) in actual
    )


def _event(cid: str, name: str) -> dict:
    # Observation literals belong in this emit adapter, never the engine.
    return {
        "cid": cid,
        "correlation_id": cid,
        "cycle_id": cid,
        "service": "lakatotree.functional_judgement_sweep",
        "event": name,
    }


class _SweepKg:
    def __init__(
        self,
        *,
        lose_second_cas: bool = False,
        lock_second_after_scan: bool = False,
    ) -> None:
        self.rows = [
            {"tag": "legacy", "prev_rsha": "p1", "ers": None, "vur": True},
            {"tag": "old", "prev_rsha": "p2", "ers": "e" * 64, "vur": True},
            {"tag": "locked", "prev_rsha": "p3", "ers": None, "vur": False},
        ]
        self.lose_second_cas = lose_second_cas
        self.lock_second_after_scan = lock_second_after_scan
        self.predecessor_checks: list[str] = []
        self.writes: list[dict] = []
        self.write_queries: list[str] = []

    def __call__(self, query: str, **params):
        if "verdict:'CANONICAL'" in query and "RETURN e.tag AS tag" in query:
            return [dict(row) for row in self.rows]
        if "pending_predecessors" in query:
            self.predecessor_checks.append(params["tag"])
            return []
        if "stale_engine_rule_demoted_at" in query:
            self.writes.append(dict(params))
            self.write_queries.append(query)
            if self.lose_second_cas and params["tag"] == "old":
                actual_receipt_head = "raced-p2"
                if (
                    actual_receipt_head != params.get("prev")
                    and _is_and_conjunct(query, _HEAD_GUARD)
                ):
                    return []
            if self.lock_second_after_scan and params["tag"] == "old":
                actual_lock = False
                if (
                    actual_lock != params.get("expected_vur")
                    and _is_and_conjunct(query, _LOCK_GUARD)
                ):
                    return []
            return [{"tag": params["tag"]}]
        return []


def _service(kg, *, hist=None, **ports) -> JudgementService:
    return JudgementService(
        kg=kg,
        kg_tx=lambda ops: [],
        hist=(lambda *args, **kwargs: None) if hist is None else hist,
        foundation=lambda name: None,
        reproducible_for_node=lambda name, tag: None,
        rule_floor_provider=ports.pop(
            "rule_floor_provider", lambda: {ENGINE_RULE_SHA}
        ),
        utc_now=ports.pop("utc_now", lambda: FIXED_NOW),
        **ports,
    )


def verify(backend, cid):
    safe_where = (
        f"MATCH (e) WHERE {_VERDICT_GUARD} AND {_HEAD_GUARD} "
        f"AND {_LOCK_GUARD} SET e.verdict=$verdict"
    )
    unsafe_where = (
        f"MATCH (e) WHERE true OR {_VERDICT_GUARD} AND {_HEAD_GUARD} "
        f"AND {_LOCK_GUARD} SET e.verdict=$verdict"
    )
    if not all(
        _is_and_conjunct(safe_where, predicate)
        for predicate in (_HEAD_GUARD, _LOCK_GUARD)
    ) or any(
        _is_and_conjunct(unsafe_where, predicate)
        for predicate in (_HEAD_GUARD, _LOCK_GUARD)
    ):
        raise RuntimeError("CAS oracle accepts a non-conjunctive WHERE bypass")

    heads = (
        CanonicalHeadSnapshot("current", "p0", ENGINE_RULE_SHA, True),
        CanonicalHeadSnapshot("legacy", "p1", None, True),
        CanonicalHeadSnapshot("old", "p2", "e" * 64, True),
        CanonicalHeadSnapshot("locked", "p3", None, False),
    )
    kwargs = {
        "tree": "T",
        "heads": heads,
        "effective_floor": frozenset({ENGINE_RULE_SHA}),
        "dry_run": False,
    }
    left = decide_stale_canonical_sweep(**kwargs)
    right = decide_stale_canonical_sweep(**kwargs)
    if left != right or left.candidates != (heads[1], heads[2]):
        raise RuntimeError("stale sweep is not referentially transparent")
    try:
        left.tree = "mutated"
    except FrozenInstanceError:
        pass
    else:
        raise RuntimeError("stale sweep decision is mutable")
    backend.ship([_event(cid, "stale_sweep_pure_decision")])

    calls: list[str] = []

    def decide_port(**values):
        calls.append("decide")
        return decide_stale_canonical_sweep(**values)

    def demotion_port(decision):
        calls.append("plan")
        return draft_stale_canonical_demotions(decision)

    def clock():
        calls.append("clock")
        return FIXED_NOW

    kg = _SweepKg()
    service = _service(
        kg,
        stale_sweep_decider=decide_port,
        stale_demotion_planner=demotion_port,
        utc_now=clock,
    )
    result = service.demote_stale_canonical("T", dry_run=False)
    if calls != ["decide", "plan", "clock"] or result["demoted"] != ["legacy", "old"]:
        raise RuntimeError("JudgementService bypassed an injected planning port")
    backend.ship([_event(cid, "stale_sweep_injected_ports_used")])

    def empty_decider(**values):
        decision = decide_stale_canonical_sweep(**values)
        return replace(decision, candidates=())

    kg = _SweepKg()
    result = _service(kg, stale_sweep_decider=empty_decider).demote_stale_canonical(
        "T", dry_run=False
    )
    if result["demoted"] or kg.writes:
        raise RuntimeError("empty injected decision did not suppress demotions")
    backend.ship([_event(cid, "stale_sweep_decider_load_bearing")])

    kg = _SweepKg()
    result = _service(
        kg,
        stale_demotion_planner=lambda decision: (),
    ).demote_stale_canonical("T", dry_run=False)
    if result["demoted"] or kg.predecessor_checks or kg.writes:
        raise RuntimeError("empty injected demotion plan did not suppress effects")
    backend.ship([_event(cid, "stale_sweep_demotion_plan_load_bearing")])

    def rogue_decider(**values):
        decision = decide_stale_canonical_sweep(**values)
        locked = next(head for head in values["heads"] if head.tag == "locked")
        return replace(
            decision,
            candidates=decision.candidates + (locked,),
            skipped_locked=(),
        )

    kg = _SweepKg()
    try:
        _service(kg, stale_sweep_decider=rogue_decider).demote_stale_canonical(
            "T", dry_run=False
        )
    except ValueError:
        pass
    else:
        raise RuntimeError("rogue decision crossed the observed-head boundary")
    if kg.writes:
        raise RuntimeError("rogue decision reached the ledger")

    def rogue_planner(decision):
        draft = draft_stale_canonical_demotions(decision)[0]
        return (replace(draft, tag="unobserved"),)

    kg = _SweepKg()
    try:
        _service(kg, stale_demotion_planner=rogue_planner).demote_stale_canonical(
            "T", dry_run=False
        )
    except ValueError:
        pass
    else:
        raise RuntimeError("rogue effect plan crossed the canonical-plan boundary")
    if kg.predecessor_checks or kg.writes:
        raise RuntimeError("rogue effect plan reached the ledger")

    def reordered_decider(**values):
        decision = decide_stale_canonical_sweep(**values)
        return replace(decision, candidates=tuple(reversed(decision.candidates)))

    kg = _SweepKg()
    try:
        _service(kg, stale_sweep_decider=reordered_decider).demote_stale_canonical(
            "T", dry_run=False
        )
    except ValueError:
        pass
    else:
        raise RuntimeError("reordered decision crossed the observed-head boundary")
    if kg.predecessor_checks or kg.writes:
        raise RuntimeError("reordered decision reached an effect port")

    def reordered_planner(decision):
        return tuple(reversed(draft_stale_canonical_demotions(decision)))

    kg = _SweepKg()
    try:
        _service(kg, stale_demotion_planner=reordered_planner).demote_stale_canonical(
            "T", dry_run=False
        )
    except ValueError:
        pass
    else:
        raise RuntimeError("reordered effect plan crossed the canonical-plan boundary")
    if kg.predecessor_checks or kg.writes:
        raise RuntimeError("reordered effect plan reached an effect port")

    def forged_planner(decision):
        draft = draft_stale_canonical_demotions(decision)[0]
        return (replace(draft, previous_receipt_sha="forged-head"),)

    kg = _SweepKg()
    try:
        _service(kg, stale_demotion_planner=forged_planner).demote_stale_canonical(
            "T", dry_run=False
        )
    except ValueError:
        pass
    else:
        raise RuntimeError("forged effect plan crossed the canonical-plan boundary")
    if kg.predecessor_checks or kg.writes:
        raise RuntimeError("forged effect plan reached an effect port")

    def mutating_decider(**values):
        floor = values["effective_floor"]
        if isinstance(floor, set):
            floor.clear()
        return decide_stale_canonical_sweep(**values)

    kg = _SweepKg()
    kg.rows.insert(
        0,
        {"tag": "current", "prev_rsha": "p0", "ers": ENGINE_RULE_SHA, "vur": True},
    )
    result = _service(
        kg,
        stale_sweep_decider=mutating_decider,
        rule_floor_provider=lambda: {ENGINE_RULE_SHA},
    ).demote_stale_canonical("T", dry_run=True)
    if [candidate["tag"] for candidate in result["candidates"]] != ["legacy", "old"]:
        raise RuntimeError("injected decider mutated the captured floor")
    backend.ship([_event(cid, "stale_sweep_injected_outputs_fail_closed")])

    history: list[tuple] = []
    kg = _SweepKg(lose_second_cas=True)
    result = _service(kg, hist=lambda *args, **kwargs: history.append(args)).demote_stale_canonical(
        "T", dry_run=False
    )
    expected_result = {
        "tree": "T",
        "dry_run": False,
        "floor_size": 1,
        "canonical_total": 3,
        "candidates": [
            {"tag": "legacy", "sealed_engine_rule_sha": None},
            {"tag": "old", "sealed_engine_rule_sha": "e" * 64},
        ],
        "skipped_locked": ["locked"],
        "demoted": ["legacy"],
    }
    if result != expected_result:
        raise RuntimeError("public stale-sweep response values or order drifted")
    expected_response_bytes = (
        b'{"tree":"T","dry_run":false,"floor_size":1,'
        b'"canonical_total":3,"candidates":[{"tag":"legacy",'
        b'"sealed_engine_rule_sha":null},{"tag":"old",'
        + f'"sealed_engine_rule_sha":"{"e" * 64}"'.encode()
        + b'}],"skipped_locked":["locked"],"demoted":["legacy"]}'
    )
    if JSONResponse(content=result).body != expected_response_bytes:
        raise RuntimeError("public stale-sweep response bytes or key order drifted")
    if {item["ts"] for item in kg.writes} != {FIXED_NOW.isoformat()}:
        raise RuntimeError("demotions did not share one explicit timestamp")
    first = kg.writes[0]
    expected_sha = receipt_content_sha({
        "tree": "T",
        "tag": "legacy",
        "target_id": None,
        "verdict": "former_canonical",
        "verdict_source": "engine",
        "metric_name": None,
        "metric_value": None,
        "novel_confirmed": None,
        "lakatos_status": None,
        "judged_at": FIXED_NOW.isoformat(),
        "judge_script_sha": None,
        "prev_receipt_sha": "p1",
        "engine_rule_sha": ENGINE_RULE_SHA,
    })
    if first["rsha"] != expected_sha:
        raise RuntimeError("stale-sweep v2 receipt identity drifted")
    expected_history = (
        "T",
        "stale_engine_demotion",
        "legacy",
        {"sealed": None, "floor_size": 1, "receipt_sha": expected_sha},
    )
    if history != [expected_history]:
        raise RuntimeError("history operation, payload, or commit filtering drifted")

    lock_history: list[tuple] = []
    lock_kg = _SweepKg(lock_second_after_scan=True)
    lock_result = _service(
        lock_kg,
        hist=lambda *args, **kwargs: lock_history.append(args),
    ).demote_stale_canonical("T", dry_run=False)
    if lock_result["demoted"] != ["legacy"] or [x[2] for x in lock_history] != ["legacy"]:
        raise RuntimeError("operator-lock CAS race was not fenced")
    backend.ship([_event(cid, "stale_sweep_compatibility_preserved")])
