"""RED-first guards for the stale-canonical functional planning seam."""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from lakatos.engine_identity import ENGINE_RULE_SHA
from lakatos.stale_canonical import (
    CanonicalHeadSnapshot,
    StaleCanonicalSweepDecision,
    decide_stale_canonical_sweep,
    draft_stale_canonical_demotions,
    plan_stale_canonical_demotions,
    project_stale_canonical_sweep,
)
from lakatos.verdicts import canonical_receipt_blob, receipt_content_sha
from server.contexts.tree.judgement_service import JudgementService


_FIXED_NOW = datetime(2026, 8, 7, 18, 30, tzinfo=timezone.utc)


def _heads() -> tuple[CanonicalHeadSnapshot, ...]:
    return (
        CanonicalHeadSnapshot("current", "p0", ENGINE_RULE_SHA, True),
        CanonicalHeadSnapshot("legacy", "p1", None, True),
        CanonicalHeadSnapshot("old", "p2", "e" * 64, True),
        CanonicalHeadSnapshot("locked", "p3", None, False),
    )


def test_guard_mechanism_equal_inputs_produce_equal_frozen_decisions():
    heads = _heads()
    left = decide_stale_canonical_sweep(
        tree="T",
        heads=heads,
        effective_floor=frozenset({ENGINE_RULE_SHA}),
        dry_run=False,
    )
    right = decide_stale_canonical_sweep(
        tree="T",
        heads=heads,
        effective_floor=frozenset({ENGINE_RULE_SHA}),
        dry_run=False,
    )

    assert left == right
    assert left.candidates == (heads[1], heads[2])
    assert left.skipped_locked == ("locked",)
    assert heads == _heads()
    with pytest.raises(FrozenInstanceError):
        left.tree = "mutated"  # type: ignore[misc]
    with pytest.raises(ValueError, match="candidates must be a tuple"):
        StaleCanonicalSweepDecision(
            schema_version=left.schema_version,
            tree=left.tree,
            dry_run=left.dry_run,
            floor_size=left.floor_size,
            canonical_total=left.canonical_total,
            candidates=list(left.candidates),  # type: ignore[arg-type]
            skipped_locked=left.skipped_locked,
        )
    with pytest.raises(ValueError, match="CanonicalHeadSnapshot"):
        replace(left, candidates=("not-a-head",))  # type: ignore[arg-type]


def test_guard_defect_projection_preserves_query_order_and_public_shape():
    decision = decide_stale_canonical_sweep(
        tree="T",
        heads=_heads(),
        effective_floor=frozenset({ENGINE_RULE_SHA}),
        dry_run=True,
    )

    assert project_stale_canonical_sweep(decision) == {
        "tree": "T",
        "dry_run": True,
        "floor_size": 1,
        "canonical_total": 4,
        "candidates": [
            {"tag": "legacy", "sealed_engine_rule_sha": None},
            {"tag": "old", "sealed_engine_rule_sha": "e" * 64},
        ],
        "skipped_locked": ["locked"],
        "demoted": [],
    }


def test_guard_mechanism_demotion_plan_uses_one_explicit_clock_and_v2_hash():
    decision = decide_stale_canonical_sweep(
        tree="T",
        heads=_heads(),
        effective_floor=frozenset({ENGINE_RULE_SHA}),
        dry_run=False,
    )
    judged_at = _FIXED_NOW.isoformat()
    plans = plan_stale_canonical_demotions(
        decision,
        judged_at=judged_at,
        engine_rule_sha=ENGINE_RULE_SHA,
    )

    assert [plan.tag for plan in plans] == ["legacy", "old"]
    assert {plan.judged_at for plan in plans} == {judged_at}
    for plan in plans:
        assert plan.schema_version == decision.schema_version
        assert plan.tree == decision.tree
        assert plan.expected_valid_until_rebutted is True
        assert plan.verdict == "former_canonical"
        assert plan.verdict_source == "engine"
        expected_fields = {
            "tree": "T",
            "tag": plan.tag,
            "target_id": None,
            "verdict": "former_canonical",
            "verdict_source": "engine",
            "metric_name": None,
            "metric_value": None,
            "novel_confirmed": None,
            "lakatos_status": None,
            "judged_at": judged_at,
            "judge_script_sha": None,
            "prev_receipt_sha": plan.previous_receipt_sha,
            "engine_rule_sha": ENGINE_RULE_SHA,
        }
        assert plan.receipt_sha == receipt_content_sha(expected_fields)
        assert canonical_receipt_blob(expected_fields).startswith(
            b"verdict-receipt\x00v2\n"
        )
    with pytest.raises(ValueError, match="RFC3339"):
        replace(plans[0], judged_at="not-time")
    with pytest.raises(ValueError, match="RFC3339"):
        replace(plans[0], judged_at="2026-02-30T12:00:00Z")
    with pytest.raises(ValueError, match="SHA-256"):
        replace(plans[0], receipt_sha="not-a-sha")
    with pytest.raises(ValueError, match="does not match demotion content"):
        replace(plans[0], receipt_sha="0" * 64)


class _SweepKg:
    def __init__(
        self,
        *,
        lock_old_after_scan: bool = False,
        events: list[str] | None = None,
    ) -> None:
        self.rows = [
            {"tag": "legacy", "prev_rsha": "p1", "ers": None, "vur": True},
            {"tag": "old", "prev_rsha": "p2", "ers": "e" * 64, "vur": True},
            {"tag": "locked", "prev_rsha": "p3", "ers": None, "vur": False},
        ]
        self.lock_old_after_scan = lock_old_after_scan
        self.events = events
        self.writes: list[dict] = []
        self.write_queries: list[str] = []

    def __call__(self, query: str, **params):
        if "verdict:'CANONICAL'" in query and "RETURN e.tag AS tag" in query:
            if self.events is not None:
                self.events.append("head_scan")
            return [dict(row) for row in self.rows]
        if "pending_predecessors" in query:
            if self.events is not None:
                self.events.append(f"predecessors:{params['tag']}")
            return []
        if "stale_engine_rule_demoted_at" in query:
            if self.events is not None:
                self.events.append(f"write:{params['tag']}")
            self.writes.append(dict(params))
            self.write_queries.append(query)
            if self.lock_old_after_scan and params["tag"] == "old":
                has_lock_cas = (
                    "coalesce(e.valid_until_rebutted,true)=$expected_vur" in query
                )
                if has_lock_cas and params.get("expected_vur") is True:
                    return []
            return [{"tag": params["tag"]}]
        return []


def _service(kg, **ports) -> JudgementService:
    return JudgementService(
        kg=kg,
        kg_tx=lambda ops: [],
        hist=ports.pop("hist", lambda *args, **kwargs: None),
        foundation=lambda name: None,
        reproducible_for_node=lambda name, tag: None,
        rule_floor_provider=ports.pop(
            "rule_floor_provider",
            lambda: frozenset({ENGINE_RULE_SHA}),
        ),
        **ports,
    )


def test_guard_mechanism_service_shell_uses_injected_planners_and_clock():
    kg = _SweepKg()
    calls: list[str] = []
    history: list[tuple] = []

    def decide_port(**kwargs):
        calls.append("decide")
        return decide_stale_canonical_sweep(**kwargs)

    def demotion_port(decision):
        calls.append("plan_demotions")
        return draft_stale_canonical_demotions(decision)

    def clock():
        calls.append("clock")
        return _FIXED_NOW

    service = _service(
        kg,
        hist=lambda *args, **kwargs: history.append(args),
        stale_sweep_decider=decide_port,
        stale_demotion_planner=demotion_port,
        utc_now=clock,
    )
    result = service.demote_stale_canonical("T", dry_run=False)

    assert calls == ["decide", "plan_demotions", "clock"]
    assert result["demoted"] == ["legacy", "old"]
    assert [row["tag"] for row in kg.writes] == ["legacy", "old"]
    assert {row["ts"] for row in kg.writes} == {_FIXED_NOW.isoformat()}
    assert {row["verdict"] for row in kg.writes} == {"former_canonical"}
    assert {row["verdict_source"] for row in kg.writes} == {"engine"}
    assert {row["expected_vur"] for row in kg.writes} == {True}
    assert all("e.verdict=$verdict" in query for query in kg.write_queries)
    assert all("e.verdict='former_canonical'" not in query for query in kg.write_queries)
    assert [item[2] for item in history] == ["legacy", "old"]


def test_guard_defect_dry_run_never_uses_live_only_ports():
    kg = _SweepKg()

    def forbidden(*args, **kwargs):
        raise AssertionError("dry run crossed a live-only port")

    service = _service(
        kg,
        stale_demotion_planner=forbidden,
        utc_now=forbidden,
        ledger_ready=forbidden,
    )

    result = service.demote_stale_canonical("T")
    assert result["dry_run"] is True
    assert [item["tag"] for item in result["candidates"]] == ["legacy", "old"]
    assert kg.writes == []


def test_guard_defect_rogue_injected_plan_fails_closed_before_ledger_write():
    kg = _SweepKg()

    def rogue_planner(decision):
        draft = draft_stale_canonical_demotions(decision)[0]
        return (replace(draft, tag="unobserved"),)

    service = _service(
        kg,
        stale_demotion_planner=rogue_planner,
        utc_now=lambda: _FIXED_NOW,
    )

    with pytest.raises(ValueError, match="demotion draft does not match"):
        service.demote_stale_canonical("T", dry_run=False)
    assert kg.writes == []


def test_guard_defect_mutable_floor_cannot_be_changed_by_injected_decider():
    kg = _SweepKg()

    def mutating_decider(**kwargs):
        floor = kwargs["effective_floor"]
        if isinstance(floor, set):
            floor.clear()
        return decide_stale_canonical_sweep(**kwargs)

    service = _service(
        kg,
        rule_floor_provider=lambda: {ENGINE_RULE_SHA},
        stale_sweep_decider=mutating_decider,
    )

    result = service.demote_stale_canonical("T", dry_run=True)
    assert [candidate["tag"] for candidate in result["candidates"]] == [
        "legacy",
        "old",
    ]


def test_guard_defect_empty_effect_draft_has_no_predecessor_or_clock_effects():
    events: list[str] = []
    kg = _SweepKg(events=events)
    service = _service(
        kg,
        stale_demotion_planner=lambda decision: (),
        utc_now=lambda: events.append("clock") or _FIXED_NOW,
    )

    result = service.demote_stale_canonical("T", dry_run=False)

    assert result["demoted"] == []
    assert events == ["head_scan"]
    assert kg.writes == []


def test_guard_defect_rogue_decider_cannot_reclassify_locked_head():
    kg = _SweepKg()

    def rogue_decider(**kwargs):
        decision = decide_stale_canonical_sweep(**kwargs)
        locked = next(head for head in kwargs["heads"] if head.tag == "locked")
        return replace(
            decision,
            candidates=decision.candidates + (locked,),
            skipped_locked=(),
        )

    service = _service(
        kg,
        stale_sweep_decider=rogue_decider,
        utc_now=lambda: _FIXED_NOW,
    )

    with pytest.raises(ValueError, match="sweep decision does not match"):
        service.demote_stale_canonical("T", dry_run=False)
    assert kg.writes == []


def test_guard_defect_operator_lock_race_is_part_of_the_ledger_cas():
    kg = _SweepKg(lock_old_after_scan=True)
    history: list[tuple] = []
    service = _service(
        kg,
        hist=lambda *args, **kwargs: history.append(args),
        utc_now=lambda: _FIXED_NOW,
    )

    result = service.demote_stale_canonical("T", dry_run=False)

    assert result["demoted"] == ["legacy"]
    assert [item[2] for item in history] == ["legacy"]
    assert all(
        "coalesce(e.valid_until_rebutted,true)=$expected_vur" in query
        for query in kg.write_queries
    )


def test_guard_mechanism_live_effect_order_is_ready_read_fence_clock_write():
    events: list[str] = []
    kg = _SweepKg(events=events)
    service = _service(
        kg,
        rule_floor_provider=lambda: (
            events.append("floor") or frozenset({ENGINE_RULE_SHA})
        ),
        ledger_ready=lambda: events.append("ledger_ready"),
        stale_demotion_planner=lambda decision: (
            events.append("plan") or draft_stale_canonical_demotions(decision)
        ),
        utc_now=lambda: events.append("clock") or _FIXED_NOW,
    )

    result = service.demote_stale_canonical("T", dry_run=False)

    assert result["demoted"] == ["legacy", "old"]
    assert events == [
        "floor",
        "ledger_ready",
        "head_scan",
        "plan",
        "predecessors:legacy",
        "predecessors:old",
        "clock",
        "write:legacy",
        "write:old",
    ]


def test_guard_defect_empty_tree_preserves_existing_empty_projection():
    service = _service(lambda query, **params: [])

    assert service.demote_stale_canonical("", dry_run=True) == {
        "tree": "",
        "dry_run": True,
        "floor_size": 1,
        "canonical_total": 0,
        "candidates": [],
        "skipped_locked": [],
        "demoted": [],
    }


def test_guard_defect_legacy_empty_sha_values_remain_distinct_receipt_inputs():
    kg = _SweepKg()
    kg.rows = [
        {"tag": "empty-legacy", "prev_rsha": "", "ers": "", "vur": True},
    ]
    history: list[tuple] = []
    service = _service(
        kg,
        hist=lambda *args, **kwargs: history.append(args),
        utc_now=lambda: _FIXED_NOW,
    )

    result = service.demote_stale_canonical("T", dry_run=False)

    expected_fields = {
        "tree": "T",
        "tag": "empty-legacy",
        "target_id": None,
        "verdict": "former_canonical",
        "verdict_source": "engine",
        "metric_name": None,
        "metric_value": None,
        "novel_confirmed": None,
        "lakatos_status": None,
        "judged_at": _FIXED_NOW.isoformat(),
        "judge_script_sha": None,
        "prev_receipt_sha": "",
        "engine_rule_sha": ENGINE_RULE_SHA,
    }
    expected_sha = receipt_content_sha(expected_fields)
    assert result["candidates"] == [
        {"tag": "empty-legacy", "sealed_engine_rule_sha": ""},
    ]
    assert result["demoted"] == ["empty-legacy"]
    assert kg.writes[0]["prev"] == ""
    assert kg.writes[0]["rsha"] == expected_sha
    assert history == [
        (
            "T",
            "stale_engine_demotion",
            "empty-legacy",
            {"sealed": "", "floor_size": 1, "receipt_sha": expected_sha},
        )
    ]


def test_guard_defect_failed_live_readiness_stops_before_kg_clock_and_planner():
    events: list[str] = []
    kg = _SweepKg(events=events)

    def not_ready() -> None:
        events.append("ledger_ready")
        raise RuntimeError("ledger not ready")

    def forbidden(*args, **kwargs):
        raise AssertionError("live execution crossed failed readiness")

    service = _service(
        kg,
        rule_floor_provider=lambda: (
            events.append("floor") or frozenset({ENGINE_RULE_SHA})
        ),
        ledger_ready=not_ready,
        stale_sweep_decider=forbidden,
        stale_demotion_planner=forbidden,
        utc_now=forbidden,
    )

    with pytest.raises(RuntimeError, match="ledger not ready"):
        service.demote_stale_canonical("T", dry_run=False)
    assert events == ["floor", "ledger_ready"]


class _RouteService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    def demote_stale_canonical(self, tree: str, *, dry_run: bool = True) -> dict:
        self.calls.append((tree, dry_run))
        return {
            "tree": tree,
            "dry_run": dry_run,
            "floor_size": 1,
            "canonical_total": 0,
            "candidates": [],
            "skipped_locked": [],
            "demoted": [],
        }


def test_guard_defect_ops_route_requires_tree_and_preserves_default_dry_run(
    monkeypatch,
):
    from fastapi.testclient import TestClient
    from server import app as server_app

    route_service = _RouteService()
    monkeypatch.delenv("LAKATOS_API_TOKEN", raising=False)
    monkeypatch.setattr(server_app, "_judgement_service", lambda: route_service)
    client = TestClient(server_app.app)

    missing = client.post("/api/ops/demote-stale-canonical")
    response = client.post("/api/ops/demote-stale-canonical?tree=T")

    assert missing.status_code == 422
    assert response.status_code == 200
    assert response.content == (
        b'{"tree":"T","dry_run":true,"floor_size":1,'
        b'"canonical_total":0,"candidates":[],"skipped_locked":[],'
        b'"demoted":[]}'
    )
    assert list(response.json()) == [
        "tree",
        "dry_run",
        "floor_size",
        "canonical_total",
        "candidates",
        "skipped_locked",
        "demoted",
    ]
    assert response.json()["dry_run"] is True
    assert route_service.calls == [("T", True)]


def test_guard_defect_ops_route_rejects_live_sweep_in_open_auth_posture(
    monkeypatch,
):
    from fastapi.testclient import TestClient
    from server import app as server_app

    route_service = _RouteService()
    monkeypatch.delenv("LAKATOS_API_TOKEN", raising=False)
    monkeypatch.setattr(server_app, "_judgement_service", lambda: route_service)

    response = TestClient(server_app.app).post(
        "/api/ops/demote-stale-canonical?tree=T&dry_run=false"
    )

    assert response.status_code == 403
    assert route_service.calls == []


def test_guard_defect_ops_route_live_sweep_requires_matching_bearer_token(
    monkeypatch,
):
    from fastapi.testclient import TestClient
    from server import app as server_app

    kg = _SweepKg()
    route_service = _service(kg)
    monkeypatch.setenv("LAKATOS_API_TOKEN", "operator-secret")
    monkeypatch.setattr(server_app, "_judgement_service", lambda: route_service)
    client = TestClient(server_app.app)
    path = "/api/ops/demote-stale-canonical?tree=T&dry_run=false"

    assert client.post(path).status_code == 401
    assert (
        client.post(path, headers={"authorization": "Bearer wrong"}).status_code
        == 401
    )
    response = client.post(
        path,
        headers={"authorization": "Bearer operator-secret"},
    )

    assert response.status_code == 200
    assert response.content == (
        b'{"tree":"T","dry_run":false,"floor_size":1,'
        b'"canonical_total":3,"candidates":[{"tag":"legacy",'
        b'"sealed_engine_rule_sha":null},{"tag":"old",'
        + f'"sealed_engine_rule_sha":"{"e" * 64}"'.encode()
        + b'}],"skipped_locked":["locked"],'
        b'"demoted":["legacy","old"]}'
    )
    assert [write["tag"] for write in kg.writes] == ["legacy", "old"]


def test_guard_defect_functional_planner_cannot_import_effect_layers():
    root = Path(__file__).resolve().parents[1]
    config = (root / ".importlinter").read_text(
        encoding="utf-8"
    )
    assert "stale canonical functional planner must not import effects" in config
    assert "lakatos.stale_canonical" in config

    tree = ast.parse((root / "lakatos" / "stale_canonical.py").read_text(encoding="utf-8"))
    imported_roots = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_roots.update(
        node.module.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )
    assert imported_roots.isdisjoint(
        {"datetime", "httpx", "neo4j", "os", "pathlib", "requests", "socket", "subprocess", "time"}
    )
