# Research Tradition Axis

Prometheus decision: `IMPLEMENTED` (2026-06-23 — was `DESIGN_FIRST_DOC_READY`).

Laudan's research tradition is broader than a Lakatos hard core. It can include
assumptions about entities, processes, and accepted methods. Lakatotree's hard
core machinery deliberately treats hard-core violation as an identity event:
different programme, not ordinary revision.

Therefore the next step is not production code. The design note is now written:

- `THEORY/lakatotree-open-gaps/research_tradition_design.md`

It covers:

- revisable ontology fields;
- methodology fields;
- migration/compatibility rules;
- relation to existing `LakatosGate` and `HardCoreProtected`.

CLOSED (2026-06-23): `lakatos/programme/tradition.py` now implements the four
objects (`ResearchTradition`, `TraditionCommitment`, `TraditionRevision`,
`TraditionAppraisal`) + `appraise_tradition_revision`, with OOPTDD tests
(`tests/test_tradition.py`) and Longinus bindings (5 public objects +
`span_lakatotree_tradition` kg_anchor). `authority == "diagnostic_only"` per the
design invariants — hard-core identity still routes through `LakatosGate` /
`HardCoreProtected`; `identity_boundary` revision yields a
`different_programme_candidate` diagnostic, never a silent hard-core rewrite.
Step 5 (feeding tradition conceptual pressure into the series diagnostic) is now
DONE (2026-06-23): tradition is authorable+persisted (`POST/GET /api/tree/{name}/tradition`),
revisions are appraised+recorded append-only (`POST /api/tree/{name}/tradition/appraise`),
and `series_view` surfaces the accumulated `tradition_conceptual_pressure`
(diagnostic_only). CLI/MCP parity for the tradition surface remains a minor follow-up.
