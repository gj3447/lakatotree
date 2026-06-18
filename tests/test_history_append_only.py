"""Append-only history invariant (OQ10, partial) — the clean isolable increment of the
lakatotree provenance leg.

The history audit log is the programme's record of what moved when; HC3 (append-only
provenance is a correctness property — a programme that rewrites its own history cannot be
audited, Glean StackedBase / Kythe hermetic-unit discipline) says it must never be rewritten.
It already is INSERT-only (measured: 0 UPDATE/DELETE on `history` in server/). This test LOCKS
that invariant so a future ``UPDATE history`` / ``DELETE FROM history`` fails CI.

DEFERRED (honest, recorded in lakatos node oq10-lakatotree-provenance): stamping every append
with an explicit owning_round/commit ref (provenance *coverage* -> 100%, needs threading a
round id through every mutation callsite), and the tpa-engine StackedBase incremental-reindex
leg (neo4j_sink does a full DETACH DELETE rebuild — NOT a single isolable increment).
"""
from __future__ import annotations

import re
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / "server"


def _server_source() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in SERVER.rglob("*.py"))


def test_history_audit_log_is_append_only():
    src = _server_source()
    assert not re.search(r"UPDATE\s+history\b", src, re.I), "history must never be UPDATEd"
    assert not re.search(r"DELETE\s+FROM\s+history\b", src, re.I), "history must never be DELETEd"
    assert re.search(r"INSERT\s+INTO\s+history\b", src, re.I), "there must be an append path"
