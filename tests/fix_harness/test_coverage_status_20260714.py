"""COV1 dual guards — empty backlog alone must never mint exhaustive coverage."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from lakatos.quant.metrics import _coverage
from server.contexts.tree.repository import normalize_tree_row
from server.contexts.tree.schemas import CreateTreeIn


def test_missing_coverage_declaration_must_not_mint_exhaustive():
    absent = _coverage({})
    prose_only = _coverage({"coverage_statement": "reviewed some files"})

    assert absent["status"] == "unknown" and absent["exhaustive"] is False
    assert prose_only["status"] == "unknown" and prose_only["exhaustive"] is False


def test_scoped_exhaustive_declaration_is_earned_and_guarded():
    spec = CreateTreeIn(
        coverage_status="exhaustive",
        coverage_statement="scope=src/** @ commit abc123",
        coverage_backlog=[],
    )
    earned = _coverage(spec.model_dump())
    assert earned["status"] == "exhaustive" and earned["exhaustive"] is True

    with pytest.raises(ValidationError):
        CreateTreeIn(coverage_status="exhaustive", coverage_statement="")
    with pytest.raises(ValidationError):
        CreateTreeIn(
            coverage_status="exhaustive",
            coverage_statement="scope=src/**",
            coverage_backlog=["src/unread.py"],
        )


def test_legacy_backlog_and_corrupt_rows_fail_closed():
    legacy = CreateTreeIn(coverage_backlog=["src/unread.py"])
    assert legacy.coverage_status == "partial"

    corrupt = normalize_tree_row({
        "coverage_status": "exhaustive",
        "coverage_statement": "scope=src/**",
        "coverage_backlog": ["src/unread.py"],
    })
    assert corrupt["coverage_status"] == "partial"

    invalid = normalize_tree_row({"coverage_status": "COMPLETE"})
    assert invalid["coverage_status"] == "unknown"
