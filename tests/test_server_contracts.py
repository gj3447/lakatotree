"""서버 계약 TDD — v1.1 운영 규약이 API 레벨까지 내려왔는지 검증.

DB는 monkeypatch 한 kg/hist 포트로 대체한다. 테스트 대상은 HTTP 프레임워크가
아니라 서버가 생성하는 그래프/이력 계약이다.
# KG: span_lakatotree_server_contracts
"""
import importlib
import os


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

    monkeypatch.setattr(app, "kg", fake_kg)
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
