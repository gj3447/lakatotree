"""Explicit storage-authority seam for application-composition unit tests.

Production ``server.app`` always composes readiness, the global writer fence,
and the full ledger scope.  Older behavior tests replace the public ``kg`` and
``kg_tx`` ports with deterministic fakes; this helper makes that replacement
explicit without weakening the production composition root.
"""

from __future__ import annotations


def install_live_ledger_test_seam(monkeypatch, app) -> None:
    original_kg_tx = app.kg_tx

    monkeypatch.setattr(app, "_require_critique_history_ready", lambda: None)

    def fenced(ops):
        # Tests that explicitly install a transaction fake own its result
        # shape.  Read/write tests that replace only ``kg`` get a faithful
        # one-query-per-operation adapter.
        if app.kg_tx is not original_kg_tx:
            return app.kg_tx(ops)
        return [app.kg(query, **params) for query, params in ops]

    monkeypatch.setattr(app._container, "writer_fenced_kg_tx", fenced)
