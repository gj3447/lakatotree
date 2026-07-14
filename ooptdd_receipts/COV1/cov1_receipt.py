"""COV1 emit-adapter — explicit coverage status through real read/write contracts."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lakatos.quant.metrics import _coverage  # noqa: E402
from server.contexts.tree.repository import normalize_tree_row  # noqa: E402
from server.contexts.tree.schemas import CreateTreeIn  # noqa: E402


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.COV1", "event": name, **attrs}


def verify(backend, cid):
    absent = _coverage({})
    prose_only = _coverage({"coverage_statement": "reviewed some files"})
    assert absent["status"] == prose_only["status"] == "unknown"
    assert not absent["exhaustive"] and not prose_only["exhaustive"]
    backend.ship([_ev(cid, "undeclared_coverage_fails_closed",
                      absent_status=absent["status"])])

    scoped = CreateTreeIn(
        coverage_status="exhaustive",
        coverage_statement="scope=src/** @ commit abc123",
        coverage_backlog=[],
    )
    earned = _coverage(scoped.model_dump())
    assert earned["status"] == "exhaustive" and earned["exhaustive"]
    try:
        CreateTreeIn(coverage_status="exhaustive", coverage_statement="")
    except ValidationError:
        pass
    else:
        raise AssertionError("unscoped exhaustive declaration was accepted")
    backend.ship([_ev(cid, "scoped_exhaustive_is_earned",
                      statement=scoped.coverage_statement)])

    legacy = CreateTreeIn(coverage_backlog=["src/unread.py"])
    corrupt = normalize_tree_row({
        "coverage_status": "exhaustive",
        "coverage_statement": "scope=src/**",
        "coverage_backlog": ["src/unread.py"],
    })
    assert legacy.coverage_status == corrupt["coverage_status"] == "partial"
    backend.ship([_ev(cid, "backlog_forces_partial", backlog_count=1)])

    with patch("lakatos.coverage.resolve_coverage_status",
               lambda declared, *, statement="", backlog=(): "exhaustive"):
        compromised = _coverage({})
    assert compromised["exhaustive"], "resolver 제거 결함을 음성 오라클이 검출하지 못함"
    assert compromised["status"] != absent["status"]
    backend.ship([_ev(cid, "empty_backlog_negative_oracle",
                      compromised_status=compromised["status"])])
