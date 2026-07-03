"""Drift guard — the "consume as a library, don't touch the repo" contract cannot silently regress.

Pins the load-bearing claims of docs/CONSUMING_LAKATOTREE.md to reality (receipts, not prose):
  1. the library core stays installable with ZERO third-party deps (base install = stdlib-only),
  2. the public authoring API lives at its canonical home (not examples/, not vendored),
  3. the old examples/ imports keep working via back-compat shims (in-repo programmes unbroken),
  4. the engine ⊥ examples boundary contract stays declared (import-linter enforces it at runtime).

If any of these drift, the "you do not touch this repo" guarantee has quietly broken — RED here.
"""
import ast
import pathlib
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent

# core library modules an external author imports — must not pull third-party packages
_CORE_MODULES = [
    "lakatos/programme/authoring.py",
    "lakatos/programme/evidence.py",
    "lakatos/programme/record_judge.py",
]
_THIRD_PARTY = {"fastapi", "starlette", "uvicorn", "httpx", "pydantic", "mcp",
                "psycopg2", "pymongo", "neo4j", "prov", "lxml", "rdflib", "numpy", "scipy"}


def test_base_install_has_no_third_party_deps():
    """pyproject base dependencies stay empty — the library core is stdlib-only (multi-engine cheapness)."""
    d = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert d["project"]["dependencies"] == [], (
        "base deps must stay empty (server/db/mcp/prov are extras); "
        f"got {d['project']['dependencies']}"
    )
    extras = d["project"]["optional-dependencies"]
    for k in ("server", "db", "prov", "all"):
        assert k in extras, f"missing optional-dependencies extra: {k}"


def test_core_authoring_modules_import_no_third_party():
    """Static guard: the public authoring modules import only stdlib or lakatos.* — never a heavy dep."""
    offenders = {}
    for rel in _CORE_MODULES:
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            names = []
            if isinstance(n, ast.Import):
                names = [a.name.split(".")[0] for a in n.names]
            elif isinstance(n, ast.ImportFrom) and n.module:
                names = [n.module.split(".")[0]]
            hits = _THIRD_PARTY.intersection(names)
            if hits:
                offenders.setdefault(rel, set()).update(hits)
    assert not offenders, f"library core grew a third-party import (breaks stdlib-only base): {offenders}"


def test_public_authoring_api_at_canonical_home():
    """External authors import these — not examples/ siblings, not vendored copies."""
    from lakatos.programme.authoring import node
    from lakatos.programme.evidence import load_record, is_grounded, summarize  # noqa: F401
    from lakatos.programme.record_judge import judge_record  # noqa: F401

    n = node("p", "canonical_stage", None, algo="problem")
    assert n["tag"] == "p" and n["verdict"] == "canonical_stage"
    # measured node carries the multiple-comparison family key
    d1 = node("d1", "partial", "p", m=0.02, base=0.05, mn="sigma_mm", nr=True, nc=False)
    assert d1["metric_name"] == "sigma_mm" and d1["novel_registered"] is True


def test_examples_shims_stay_backcompat():
    """Old imports keep working via re-export shims (in-repo programmes must not break)."""
    from examples._evidence import load_record, is_grounded, summarize  # noqa: F401
    from examples.record_judge import judge_record  # noqa: F401
    from examples.bpc_icp_programme import _n

    assert _n.__module__ == "lakatos.programme.authoring", "bpc_icp._n must alias the public node()"


def test_engine_examples_boundary_contract_declared():
    """The engine ⊥ examples forbidden contract must stay in .importlinter (lint-imports enforces it)."""
    cfg = (ROOT / ".importlinter").read_text(encoding="utf-8")
    assert "engine (lakatos, server) must not import examples" in cfg, "boundary contract removed"
    assert "type = forbidden" in cfg and "examples" in cfg
