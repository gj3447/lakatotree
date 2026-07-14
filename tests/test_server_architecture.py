"""Architecture fitness checks for the Lakatos server.

# KG: span_lakatotree_server_architecture
"""

from __future__ import annotations

import os
import subprocess
import sys
import ast
from pathlib import Path

from fastapi import HTTPException
import pytest

from server.api_schemas import NodeIn, ParentEdgeIn
from server.contexts.tree import schemas as tree_schemas
from server.contexts.tree.repository import normalize_text, normalize_tree_row
from server.contexts.tree.service import TreeService
from server.contexts.tree.validation import LakatosSemanticValidator
from server.file_hashing import path_sha


ROOT = Path(__file__).resolve().parents[1]


def _flatten_routes(app):
    """Yield leaf routes, unwrapping FastAPI's ``_IncludedRouter`` wrappers.

    FastAPI >=0.137 keeps an included router as an ``_IncludedRouter`` wrapper
    in ``app.routes`` (exposing the sub-routes under ``original_router.routes``)
    instead of flattening its sub-routes inline as older versions did. These
    ownership checks read each route's real ``endpoint.__module__``, which lives
    on the leaf — so walk both shapes to stay correct across FastAPI versions.
    """
    for route in app.routes:
        sub = getattr(route, "original_router", None)
        if sub is not None and hasattr(sub, "routes"):
            yield from _flatten_routes(sub)
        else:
            yield route


def _body_without_docstring(fn: ast.FunctionDef) -> list[ast.stmt]:
    body = list(fn.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        return body[1:]
    return body


def test_server_app_import_has_no_neo4j_env_requirement():
    env = os.environ.copy()
    for key in ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD"):
        env.pop(key, None)
    cp = subprocess.run(
        [sys.executable, "-c", "import server.app; print('ok')"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert cp.returncode == 0, cp.stderr
    assert cp.stdout.strip() == "ok"


def test_tree_service_uses_explicit_ports_for_add_node():
    calls = []

    def kg(query, **params):
        calls.append(("kg", query, params))
        if "RETURN t.title AS title" in query:
            return [{"title": "T", "hard_core": [], "frontier_rule": "", "doc": ""}]
        if "ORDER BY tag" in query:
            return [{"tag": "root", "verdict": "proof", "parent": None, "parents": [], "parent_edges": []}]
        if "RETURN q.name AS name" in query:
            return []
        return [{"ok": True}]

    def kg_tx(ops):
        calls.append(("tx", ops))
        return [[{"ok": True}] for _ in ops]

    def hist(*args):
        calls.append(("hist", args))

    svc = TreeService(kg=kg, kg_tx=kg_tx, hist=hist, pg=lambda: None)
    out = svc.add_node(
        "T",
        NodeIn(
            tag="child",
            parent_edges=[ParentEdgeIn(
                tag="root",
                inferred=True,
                relation_kind="backfill",
                evidence_ref="doc:backfill",
            )],
        ),
    )

    assert out == {"ok": True, "tag": "child"}
    tx = next(c for c in calls if c[0] == "tx")
    assert len(tx[1]) == 2
    assert any(params.get("parent") == "root" and params.get("inferred") is True for _, params in tx[1])
    assert any(c[0] == "hist" for c in calls)


def test_tree_service_rejects_missing_parent_before_write():
    def kg(query, **params):
        if "RETURN t.title AS title" in query:
            return [{"title": "T", "hard_core": [], "frontier_rule": "", "doc": ""}]
        if "ORDER BY tag" in query:
            return [{"tag": "root", "verdict": "proof", "parent": None, "parents": [], "parent_edges": []}]
        return []

    wrote = []
    svc = TreeService(kg=kg, kg_tx=lambda ops: wrote.append(ops), hist=lambda *a: None, pg=lambda: None)

    with pytest.raises(HTTPException) as exc:
        svc.add_node("T", NodeIn(tag="child", parent="ghost"))

    assert exc.value.status_code == 400
    assert wrote == []


def test_tree_service_rejects_unknown_verdict_before_write():
    wrote = []
    svc = TreeService(
        kg=lambda *a, **k: [],
        kg_tx=lambda ops: wrote.append(ops),
        hist=lambda *a: None,
        pg=lambda: None,
    )
    tree = {"nodes": [{"tag": "root", "verdict": "proof", "parent": None, "parents": []}]}

    with pytest.raises(HTTPException) as exc:
        svc.add_node("T", NodeIn(tag="child", parent="root", verdict="made_up"), tree_data=tree)

    assert exc.value.status_code == 422
    assert wrote == []


def test_lakatos_semantic_validator_rejects_self_parent():
    validator = LakatosSemanticValidator()
    tree = {"nodes": [{"tag": "root"}]}

    with pytest.raises(HTTPException) as exc:
        validator.validate_node_create("T", tree, NodeIn(tag="root", parent="root"))

    assert exc.value.status_code == 400


def test_kg_read_normalization_handles_string_list_and_null_values():
    assert normalize_text(None) == ""
    assert normalize_text("alpha") == "alpha"
    assert normalize_text(["alpha", "beta"]) == "alpha\nbeta"
    row = normalize_tree_row({"hard_core": ["h1", "h2"], "coverage_backlog": "missing.md",
                              "coverage_status": "partial"})
    assert row["hard_core"] == "h1\nh2"
    assert row["coverage_backlog"] == ["missing.md"]
    assert row["coverage_status"] == "partial"
    assert normalize_tree_row({"coverage_status": "COMPLETE"})["coverage_status"] == "unknown"


def test_core_tree_routes_are_owned_by_tree_context_router():
    import importlib

    app_mod = importlib.import_module("server.app")
    core_paths = {
        ("GET", "/api/trees"),
        ("GET", "/api/tree/{name}"),
        ("GET", "/api/tree/{name}/metrics"),
        ("POST", "/api/tree/{name}/node"),
        ("POST", "/api/tree/{name}/question"),
        ("POST", "/api/tree/{name}/question/{qname}/close"),
    }
    owners = {}
    for route in _flatten_routes(app_mod.app):
        for method in getattr(route, "methods", set()) or set():
            key = (method, route.path)
            if key in core_paths:
                owners.setdefault(key, set()).add(route.endpoint.__module__)

    assert owners.keys() >= core_paths
    assert all(mods == {"server.contexts.tree.api"} for mods in owners.values())


def test_evidence_claim_tree_routes_are_owned_by_context_router():
    import importlib

    app_mod = importlib.import_module("server.app")
    evidence_claim_paths = {
        ("GET", "/api/tree/{name}/node/{tag}/provenance"),
        ("POST", "/api/tree/{name}/node/{tag}/critique"),
        ("POST", "/api/tree/{name}/node/{tag}/event"),
        ("POST", "/api/tree/{name}/node/{tag}/observation"),
        ("POST", "/api/tree/{name}/node/{tag}/world-action"),
        ("GET", "/api/tree/{name}/node/{tag}/standing"),
        ("GET", "/api/tree/{name}/node/{tag}/events"),
        ("GET", "/api/tree/{name}/node/{tag}/claim-standing"),
        ("GET", "/api/tree/{name}/node/{tag}/certificate"),
    }
    owners = {}
    for route in _flatten_routes(app_mod.app):
        for method in getattr(route, "methods", set()) or set():
            key = (method, route.path)
            if key in evidence_claim_paths:
                owners.setdefault(key, set()).add(route.endpoint.__module__)

    assert owners.keys() >= evidence_claim_paths
    assert all(mods == {"server.contexts.tree.evidence_claim"} for mods in owners.values())


def test_programme_tree_routes_are_owned_by_context_router():
    import importlib

    app_mod = importlib.import_module("server.app")
    programme_paths = {
        ("GET", "/api/tree/{name}/calibration"),
        ("GET", "/api/tree/{name}/directions"),
        ("GET", "/api/tree/{name}/stack"),
        ("GET", "/api/tree/{name}/lifecycle"),
        ("POST", "/api/tree/{name}/cycle"),
        ("POST", "/api/tree/{name}/artifact"),
        ("POST", "/api/tree/{name}/element"),
        ("POST", "/api/tree/{name}/node/{tag}/element/{element_name}"),
        ("POST", "/api/tree/{name}/foundation"),
        ("GET", "/api/tree/{name}/foundation"),
        ("GET", "/api/tree/{name}/history"),
        ("GET", "/api/tree/ops/neo4j-constraints"),
    }
    owners = {}
    for route in _flatten_routes(app_mod.app):
        for method in getattr(route, "methods", set()) or set():
            key = (method, route.path)
            if key in programme_paths:
                owners.setdefault(key, set()).add(route.endpoint.__module__)

    assert owners.keys() >= programme_paths
    assert all(mods == {"server.contexts.tree.programme"} for mods in owners.values())


def test_judgement_tree_routes_are_owned_by_context_router():
    import importlib

    app_mod = importlib.import_module("server.app")
    judgement_paths = {
        ("POST", "/api/tree/{name}/node/{tag}/prediction"),
        ("POST", "/api/tree/{name}/node/{tag}/test_result"),
        ("POST", "/api/tree/{name}/node/{tag}/verdict"),
    }
    owners = {}
    for route in _flatten_routes(app_mod.app):
        for method in getattr(route, "methods", set()) or set():
            key = (method, route.path)
            if key in judgement_paths:
                owners.setdefault(key, set()).add(route.endpoint.__module__)

    assert owners.keys() >= judgement_paths
    assert all(mods == {"server.contexts.tree.judgement"} for mods in owners.values())


def test_lineage_routes_are_owned_by_context_router():
    import importlib

    app_mod = importlib.import_module("server.app")
    lineage_paths = {
        ("POST", "/api/lineage/derivation"),
        ("GET", "/api/openlineage/{artifact:path}"),
        ("POST", "/api/openlineage/{artifact:path}/marquez"),
        ("GET", "/api/dvc/{artifact:path}"),
        ("GET", "/api/prov/{artifact:path}"),
        ("GET", "/api/rebuild-verify/{artifact:path}"),
        ("GET", "/api/lineage-script/{producer:path}"),
        ("GET", "/api/lineage/{artifact:path}"),
    }
    owners = {}
    for route in _flatten_routes(app_mod.app):
        for method in getattr(route, "methods", set()) or set():
            key = (method, route.path)
            if key in lineage_paths:
                owners.setdefault(key, set()).add(route.endpoint.__module__)

    assert owners.keys() >= lineage_paths
    assert all(mods == {"server.contexts.lineage.api"} for mods in owners.values())


def test_server_app_tree_route_surface_is_bounded_after_context_split():
    import importlib

    app_mod = importlib.import_module("server.app")
    app_owned = []
    for route in _flatten_routes(app_mod.app):
        if not getattr(route, "path", "").startswith("/api/tree"):
            continue
        if route.endpoint.__module__ != "server.app":
            continue
        for method in getattr(route, "methods", set()) or set():
            if method not in {"HEAD", "OPTIONS"}:
                app_owned.append((method, route.path))

    assert sorted(app_owned) == []


def test_server_app_judgement_facades_delegate_to_context_service():
    tree = ast.parse((ROOT / "server" / "app.py").read_text(encoding="utf-8"))
    expected = {"set_verdict", "register_prediction", "submit_test_result"}
    funcs = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    assert expected <= funcs.keys()
    for name in expected:
        body = _body_without_docstring(funcs[name])
        assert len(body) == 1
        assert isinstance(body[0], ast.Return)
        assert "_judgement_service()" in ast.unparse(body[0])


def test_server_app_evidence_claim_facades_delegate_to_context_service():
    tree = ast.parse((ROOT / "server" / "app.py").read_text(encoding="utf-8"))
    expected = {
        "provenance",
        "add_critique",
        "add_research_event",
        "_store_research_event",
        "add_observation",
        "add_world_action",
        "standing",
        "research_events",
        "claim_standing",
        "node_certificate",
    }
    funcs = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    assert expected <= funcs.keys()
    for name in expected:
        body = _body_without_docstring(funcs[name])
        assert len(body) == 1
        assert isinstance(body[0], ast.Return)
        assert "_evidence_claim_service(" in ast.unparse(body[0])


def test_server_app_programme_facades_delegate_to_context_service():
    tree = ast.parse((ROOT / "server" / "app.py").read_text(encoding="utf-8"))
    expected = {
        "calibration",
        "directions",
        "stack_view",
        "lifecycle_view",
        "run_cycle",
        "add_artifact",
        "add_element",
        "attach_element",
        "add_foundation_requirement",
        "get_foundation_requirements",
        "history",
        "neo4j_constraint_diagnostics",
    }
    funcs = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    assert expected <= funcs.keys()
    for name in expected:
        body = _body_without_docstring(funcs[name])
        assert len(body) == 1
        assert isinstance(body[0], ast.Return)
        assert "_programme_service(" in ast.unparse(body[0])


def test_server_app_lineage_facades_delegate_to_context_service():
    tree = ast.parse((ROOT / "server" / "app.py").read_text(encoding="utf-8"))
    expected = {
        "record_derivation",
        "_load_lineage",
        "artifact_openlineage",
        "send_artifact_to_marquez",
        "artifact_dvc",
        "artifact_prov",
        "rebuild_verify",
        "get_script_history",
        "get_lineage",
    }
    funcs = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    assert expected <= funcs.keys()
    for name in expected:
        body = _body_without_docstring(funcs[name])
        assert len(body) == 1
        assert isinstance(body[0], ast.Return)
        assert "_lineage_service(" in ast.unparse(body[0])


def test_tree_context_imports_schema_from_context_not_api_facade():
    offenders = []
    for path in (ROOT / "server" / "contexts" / "tree").glob("*.py"):
        if "from server.api_schemas import" in path.read_text(encoding="utf-8"):
            offenders.append(path.relative_to(ROOT).as_posix())

    assert offenders == []


def test_api_schemas_reexports_tree_context_models():
    import server.api_schemas as api_schemas

    assert api_schemas.NodeIn is tree_schemas.NodeIn
    assert api_schemas.QuestionIn is tree_schemas.QuestionIn
    assert api_schemas.ObservationIn is tree_schemas.ObservationIn
    assert api_schemas.FoundationRequirementIn is tree_schemas.FoundationRequirementIn


def test_api_schemas_facade_stays_thin():
    lines = (ROOT / "server" / "api_schemas.py").read_text(encoding="utf-8").splitlines()

    assert len(lines) <= 120


def test_directory_path_sha_detects_same_size_content_change(tmp_path, monkeypatch):
    monkeypatch.setenv("LAKATOS_RAW_ROOT", str(tmp_path))   # #15: path_sha confinement — tmp 를 raw root 로 선언
    d = tmp_path / "lot"
    d.mkdir()
    f = d / "a.zdf"
    f.write_bytes(b"abc")
    before = path_sha(str(d))
    f.write_bytes(b"xyz")
    after = path_sha(str(d))
    assert before != after
