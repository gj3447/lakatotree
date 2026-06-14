"""서버 계약 TDD — v1.1 운영 규약이 API 레벨까지 내려왔는지 검증.

DB는 monkeypatch 한 kg/hist 포트로 대체한다. 테스트 대상은 HTTP 프레임워크가
아니라 서버가 생성하는 그래프/이력 계약이다.
# KG: span_lakatotree_server_contracts
"""
import importlib
import os

import pytest
from fastapi import HTTPException


def load_app():
    os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
    os.environ.setdefault("NEO4J_USER", "neo4j")
    os.environ.setdefault("NEO4J_PASSWORD", "test")
    return importlib.import_module("server.app")


def install_fake_ports(monkeypatch, app, existing_nodes=("p1", "p2")):
    calls = []

    def fake_kg(query, **params):
        calls.append((query, params))
        if "RETURN t.title AS title" in query:
            return [
                {
                    "title": "T",
                    "hard_core": [],
                    "frontier_rule": "",
                    "doc": "",
                    "coverage_backlog": ["unread/spec.md"],
                    "coverage_statement": "partial",
                }
            ]
        if "RETURN e.tag AS tag" in query and "ORDER BY tag" in query:
            return [
                {
                    "tag": tag,
                    "verdict": "proof",
                    "parent": None,
                    "parents": [],
                    "parent_edges": [],
                    "algorithm": "a",
                    "comment": "c",
                    "limitation": "l",
                    "metric_value": None,
                    "metric_scope": None,
                }
                for tag in existing_nodes
            ]
        if "QuestionClosure" in query:
            return [{"name": params.get("qn")}]
        if "RETURN q.name AS name" in query:
            return []
        if "RETURN e.tag AS tag" in query or "RETURN q.name AS name" in query:
            return [{"tag": params.get("tag"), "name": params.get("qn")}]
        return [{"ok": True}]

    def fake_hist(*args, **kwargs):
        calls.append(("hist", args, kwargs))

    def fake_kg_tx(ops):   # ROB-1: kg_tx = 단일 tx 로 묶은 kg 들 — 각 op 를 kg 호출처럼 기록
        return [fake_kg(cypher, **params) for cypher, params in ops]

    monkeypatch.setattr(app, "kg", fake_kg)
    monkeypatch.setattr(app, "kg_tx", fake_kg_tx)
    monkeypatch.setattr(app, "hist", fake_hist)
    return calls


def test_add_node_accepts_multi_parent_dag_edges_with_inferred_metadata(monkeypatch):
    app = load_app()
    calls = install_fake_ports(monkeypatch, app)

    app.add_node(
        "T",
        app.NodeIn(
            tag="child",
            parents=["p1"],
            parent_edges=[
                app.ParentEdgeIn(
                    tag="p2",
                    inferred=True,
                    relation_kind="backfill",
                    evidence_ref="doc:legacy",
                )
            ],
        ),
    )

    edge_calls = [c for c in calls if isinstance(c[0], str) and "MERGE (e)-[r:BRANCHED_FROM]" in c[0]]
    assert len(edge_calls) == 2
    assert {c[1]["parent"] for c in edge_calls} == {"p1", "p2"}
    inferred = next(c for c in edge_calls if c[1]["parent"] == "p2")
    assert inferred[1]["inferred"] is True
    assert inferred[1]["relation_kind"] == "backfill"
    assert inferred[1]["evidence_ref"] == "doc:legacy"


def test_close_question_appends_closure_event_and_preserves_closed_by_history(monkeypatch):
    app = load_app()
    calls = install_fake_ports(monkeypatch, app)

    app.close_question("T", "q1", closed_by="node-a")

    close_calls = [c for c in calls if isinstance(c[0], str) and "QuestionClosure" in c[0]]
    assert close_calls
    query, params = close_calls[0]
    assert "q.closed_by" in query
    assert "q.closed_events" in query
    assert params["by"] == "node-a"


def test_canonical_verdict_records_temporary_best_metadata(monkeypatch):
    app = load_app()
    calls = install_fake_ports(monkeypatch, app)

    app.set_verdict(
        "T",
        "p1",
        app.VerdictIn(
            verdict="CANONICAL",
            scope="heldout:lotoff",
            assumptions=["only under current root artifacts"],
            evidence_window="node-001..node-010",
        ),
    )

    canonical_calls = [c for c in calls if isinstance(c[0], str) and "current_best_pointer" in c[0]]
    assert canonical_calls
    _, params = canonical_calls[0]
    assert params["scope"] == "heldout:lotoff"
    assert params["assumptions"] == ["only under current root artifacts"]
    assert params["evidence_window"] == "node-001..node-010"


def test_lakatos_element_can_be_registered_and_attached_to_node(monkeypatch):
    app = load_app()
    calls = install_fake_ports(monkeypatch, app, existing_nodes=("node-1",))

    app.add_element(
        "T",
        app.ElementIn(
            name="elem-shared-visibility",
            definition="shared observations connect views",
            implication="value is graph connectivity, not the marker itself",
            lifecycle="introduced -> bounded",
        ),
    )
    app.attach_element(
        "T",
        "node-1",
        "elem-shared-visibility",
        app.ElementUseIn(note="used as reusable implication", evidence_ref="node-1"),
    )

    assert any("LakatosElement" in q for q, *_ in calls if isinstance(q, str))
    assert any("USES_ELEMENT" in q for q, *_ in calls if isinstance(q, str))


def test_foundation_requirement_is_saved_as_tree_base_knowledge(monkeypatch):
    app = load_app()
    calls = install_fake_ports(monkeypatch, app)

    app.add_foundation_requirement(
        "T",
        app.FoundationRequirementIn(
            name="metric-contract",
            kind="metric",
            question="which metric judges progress?",
            why_needed="avoid false progress after relabel",
            acceptance_criteria=["metric_name", "direction", "noise_band"],
            evidence_refs=["doc:metric-v1"],
            status="satisfied",
        ),
    )

    foundation_calls = [c for c in calls if isinstance(c[0], str) and "FoundationRequirement" in c[0]]
    assert foundation_calls
    query, params = foundation_calls[0]
    assert "HAS_FOUNDATION" in query
    assert params["kind"] == "metric"
    assert params["evidence_refs"] == ["doc:metric-v1"]


def test_unknown_foundation_kind_is_rejected_before_kg_write(monkeypatch):
    app = load_app()
    calls = install_fake_ports(monkeypatch, app)

    with pytest.raises(HTTPException) as exc:
        app.add_foundation_requirement(
            "T",
            app.FoundationRequirementIn(name="bad", kind="mystery"),
        )

    assert exc.value.status_code == 422
    assert not any(isinstance(c[0], str) and "FoundationRequirement" in c[0] for c in calls)


def test_claim_standing_endpoint_combines_foundation_arguments_and_lineage(monkeypatch):
    app = load_app()
    from lakatos.lineage import Derivation

    calls = []

    def fake_kg(query, **params):
        calls.append((query, params))
        if "RETURN e.tag AS tag, e.verdict AS verdict" in query and "collect({id:a.id" in query:
            return [
                {
                    "tag": "p1",
                    "verdict": "progressive",
                    "source_trust": 0.9,
                    "verdict_source": "scripted",
                    "judge_script": "judge.py",
                    "judge_script_sha": "sha-judge",
                    "result_path": "artifact://final",
                    "args": [
                        {
                            "id": "T/doubt1",
                            "attacks": "p1",
                            "kind": "doubt",
                            "by": "human:reviewer",
                        }
                    ],
                }
            ]
        if "FoundationRequirement" in query and "ORDER BY fr.kind" in query:
            return [
                {
                    "name": "metric-contract",
                    "kind": "metric",
                    "question": "which metric?",
                    "why_needed": "avoid relabel",
                    "acceptance_criteria": ["metric_name"],
                    "evidence_refs": ["doc:metric"],
                    "status": "satisfied",
                    "optional": False,
                    "owner": "",
                    "risk_if_missing": "",
                    "satisfied": True,
                }
            ]
        return []

    def fake_lineage():
        return [
            Derivation("raw://lot", "raw0", "", "", [], kind="source", ts="t0"),
            Derivation(
                "artifact://final",
                "final0",
                "solve.py",
                "sha-solve",
                [("raw://lot", "raw0")],
                kind="final",
                ts="t1",
            ),
        ]

    monkeypatch.setattr(app, "kg", fake_kg)
    monkeypatch.setattr(app, "hist", lambda *a, **k: None)
    monkeypatch.setattr(app, "_load_lineage", fake_lineage)
    monkeypatch.setattr(app, "environment_fingerprint", lambda: {"python": "test"})
    monkeypatch.setattr(app, "fingerprint_sha", lambda _: "")

    out = app.claim_standing("T", "p1", require_replay=True)

    assert out["claim"] == "p1"
    assert out["status"] == "blocked"
    assert "human_doubt:doubt1" in out["blocking_reasons"]
    assert not any(r.startswith("foundation:") for r in out["blocking_reasons"])
    assert not any(r.startswith("lineage:") for r in out["blocking_reasons"])


def test_research_event_is_appended_to_claim_without_overwriting(monkeypatch):
    app = load_app()
    calls = install_fake_ports(monkeypatch, app, existing_nodes=("p1",))

    out = app.add_research_event(
        "T",
        "p1",
        app.ResearchEventIn(
            event_id="evt-web-1",
            realm="kg",   # internet/bash 는 게이트 경로 전용(/observation,/world-action) — 여기선 비게이트 realm
            actor="agent:researcher",
            action="fetch_source",
            evidence_refs=["obs:paper"],
            payload={"trust": "0.82"},
        ),
    )

    event_calls = [c for c in calls if isinstance(c[0], str) and "ResearchEvent" in c[0]]
    assert out["ok"] is True
    assert event_calls
    query, params = event_calls[0]
    assert "MERGE (ev:ResearchEvent" in query
    assert "HAS_RESEARCH_EVENT" in query
    assert params["realm"] == "kg"
    assert params["payload"] == '{"trust": "0.82"}'
    assert any(c[0] == "hist" and c[1][1] == "research_event" for c in calls)


def test_unknown_research_event_realm_is_rejected_before_kg_write(monkeypatch):
    app = load_app()
    calls = install_fake_ports(monkeypatch, app, existing_nodes=("p1",))

    with pytest.raises(HTTPException) as exc:
        app.add_research_event(
            "T",
            "p1",
            app.ResearchEventIn(event_id="evt-bad", realm="dream", actor="x", action="note"),
        )

    assert exc.value.status_code == 422
    assert not any(isinstance(c[0], str) and "ResearchEvent" in c[0] for c in calls)


def test_claim_standing_includes_recorded_research_events(monkeypatch):
    app = load_app()

    def fake_kg(query, **params):
        if "RETURN e.tag AS tag, e.verdict AS verdict" in query and "collect({id:a.id" in query:
            return [
                {
                    "tag": "p1",
                    "verdict": "progressive",
                    "source_trust": None,
                    "verdict_source": "",
                    "judge_script": "",
                    "judge_script_sha": "",
                    "result_path": "",
                    "args": [],
                }
            ]
        if "ResearchEvent" in query and "ORDER BY ev.created_at, ev.name" in query:
            return [
                {
                    "name": "evt-web",
                    "realm": "internet",
                    "actor": "agent:researcher",
                    "action": "fetch_source",
                    "evidence_refs": ["obs:paper"],
                    "payload": '{"trust":"0.9"}',
                    "created_at": "2026-06-12T00:00:00Z",
                },
                {
                    "name": "evt-bash",
                    "realm": "bash",
                    "actor": "agent:builder",
                    "action": "test_passed",
                    "evidence_refs": ["bash:pytest"],
                    "payload": '{"exit_code":"0"}',
                    "created_at": "2026-06-12T00:01:00Z",
                },
            ]
        if "FoundationRequirement" in query and "ORDER BY fr.kind" in query:
            return [
                {
                    "name": "metric-contract",
                    "kind": "metric",
                    "question": "which metric?",
                    "why_needed": "avoid relabel",
                    "acceptance_criteria": ["metric_name"],
                    "evidence_refs": ["doc:metric"],
                    "status": "satisfied",
                    "optional": False,
                    "owner": "",
                    "risk_if_missing": "",
                    "satisfied": True,
                }
            ]
        return []

    monkeypatch.setattr(app, "kg", fake_kg)
    monkeypatch.setattr(app, "hist", lambda *a, **k: None)

    out = app.claim_standing("T", "p1", require_replay=False)

    assert out["status"] == "stands"
    assert out["upper_confidence"] >= 0.9
    assert out["lower_confidence"] >= 0.8
    assert out["realms"] == ["bash", "internet"]


def test_research_events_endpoint_lists_append_only_events(monkeypatch):
    app = load_app()

    def fake_kg(query, **params):
        if "ResearchEvent" in query and "ORDER BY ev.created_at, ev.name" in query:
            return [
                {
                    "id": "T/p1/event/evt-web",
                    "name": "evt-web",
                    "realm": "internet",
                    "actor": "agent:researcher",
                    "action": "fetch_source",
                    "evidence_refs": ["obs:paper"],
                    "payload": '{"trust":"0.9"}',
                    "created_at": "2026-06-12T00:00:00Z",
                },
                {
                    "id": "T/p1/event/evt-bash",
                    "name": "evt-bash",
                    "realm": "bash",
                    "actor": "agent:builder",
                    "action": "test_passed",
                    "evidence_refs": ["bash:pytest"],
                    "payload": '{"exit_code":"0"}',
                    "created_at": "2026-06-12T00:01:00Z",
                },
            ]
        return []

    monkeypatch.setattr(app, "kg", fake_kg)
    monkeypatch.setattr(app, "hist", lambda *a, **k: None)

    out = app.research_events("T", "p1")

    assert out["tag"] == "p1"
    assert out["count"] == 2
    assert out["events"][0]["id"] == "T/p1/event/evt-web"
    assert out["events"][0]["payload"] == {"trust": "0.9"}
    assert out["events"][1]["realm"] == "bash"
