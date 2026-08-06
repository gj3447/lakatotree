# Changelog

All notable user-visible changes to LakatoTree will be recorded in this file.
The project follows the structure of Keep a Changelog and intends to use semantic
versioning once tagged releases begin.

LakatoTree has not yet published a tagged release or a package to PyPI. The
`Unreleased` section describes work on the default branch, not an available
distribution.

## [Unreleased]

### Changed

- The `storage` optional-dependency group now pins the Pydantic schema runtime imported
  by the packaged predeploy auditor, while HTTP-only exception construction imports
  FastAPI lazily. A clean storage wheel install therefore exposes a working CLI without
  relying on undeclared packages or pulling in the web framework.
- Storage-backed verdict operations now use one fenced writer scope across the Neo4j
  commit, PostgreSQL history projection, and outbox applied mark. Writer readiness is
  injected into live services, PostgreSQL advisory waits are bounded, and admin
  predecessor projection covers direct and compound-demotion histories.
- Administrative `set_verdict` and measured test-result receipts now mint v6
  history-payload seals, while prediction receipts mint v3 seals over the exact
  preregistration history payload; legacy standing and stale-demotion producers retain
  their frozen earlier receipt versions. The storage audit and
  reconciler validate canonical prediction intent, receipt ownership, complete
  head-to-genesis ancestry, and causal/admin predecessor ancestry before projection.
- Storage predeploy now binds a signed writer-drain/fence authority, exact database
  identities, migrations, installed artifacts, and a write-once receipt. Launchers
  require an explicit Neo4j database, reject migration credentials at runtime, keep
  the storage-audit cache single-worker, and make production `run.sh` enforce a private
  canonical env file. `run_internal.sh` validates that file when present and otherwise
  permits an explicitly injected caller environment for internal/test use.

- engine-unify 잔여 정리 (q-lkt-engine-unify 종결): verdict 어휘 *분류 집합*의
  소비자측 재유도 15지점을 `lakatos/verdicts.py` SSOT 로 흡수
  (`CANONICAL_STATE_VERDICTS`·`SCORED_PROGRESS_VERDICTS`·`FRONTIER_EXPLANATION_VERDICTS`·
  `FRONTIER_PROGRESS_VERDICTS`·`TESTED_CORE_VERDICTS`·`DEMOTABLE_PROGRESS_VERDICTS`·
  `SERIES_*`·`REJECTING_VERDICTS`·`STANDING_VERDICTS`·`SCRIPTED_DIALECTICAL_VERDICTS`·
  `METRIC_IMPROVED_FAMILY_VERDICTS`·`DIALECTIC_OVERRIDE_VERDICTS`·
  `PNR_CONDITIONAL_SOURCE_VERDICTS`). 거동 불변 — 멤버십 동일, 정의 위치만 정본으로.
  `series.py` 의 기존 공개 이름은 하위호환 별칭으로 유지.

### Removed

- `lakatos.verdict.spine.promotion_decision` — 프로덕션 호출부 0인 사장 제2 승격
  composer. 2026-06-27 fix-harness 가 floor drift 를 잡았던 이중 권위의 원천으로,
  문서화된 선택지("delete OR route through floor") 중 삭제를 택해 승격 합성 권위를
  `synthesize_promotion` 단일로 확정. 부활 방지 가드가
  `tests/fix_harness/test_fix_2_promotion-decision-no-floor.py` 에 있다.

### Fixed

- The dependency-free Ed25519 verifiers now apply a LakatoTree strict profile that
  rejects identity, mixed-order, and small-order public keys and signature `R` points,
  closing a subgroup forgery path in both the engine verifier and the independent
  `c1verify` implementation. The non-identity `R` rule is intentionally stricter than
  general RFC 8032 interoperability. Temporal anchors also
  reject non-canonical identities, malformed signatures, and non-witness channels.

- Scoped `OpenQuestion` identity per tree: the `MERGE` key was a global `{name}`,
  so two trees opening the same `qname` silently shared one node (body
  last-write-wins, close/`n_visits` leaking across trees — observed in production
  as `judgment-ledger-repair-20260723`). Writers (`service.open_question`,
  `writer.add_node` M4 edge materialization, `writer.upsert_questions`) and the
  programme sync script now merge on the composite `(tree, name)`, and the
  required constraint changes from `lkt_open_question_name_unique` (global
  UNIQUE on `name`) to `lkt_open_question_tree_name_key` (composite UNIQUE on
  `(tree, name)` — NODE KEY is Enterprise-only; Community Edition gets the
  composite UNIQUE and writers always set `tree` via the MERGE key). Existing graphs need
  `scripts/migrate_open_question_tree_scope_20260723.cypher` (stamps `tree`,
  splits shared nodes per tree, re-points `RAISES_QUESTION`, swaps the
  constraint) before the new constraint can be created.

- License documentation truth: `README.md` still claimed "No `LICENSE` file is
  currently included" and `CONTRIBUTING.md` still claimed the license "has not
  yet been selected" after the dual-license landing (`LICENSE` = AGPL-3.0,
  `LICENSING.md` = AGPL-3.0-or-later or separate commercial). Both now state
  the actual terms.

### Added

- A dependency-free dual-resource coordination kernel now models componentwise,
  all-or-nothing reservations across compute wall time and LLM input/output tokens.
  It produces receipt- and state-chain-bound semantic transitions, enforces causal
  UTC lifecycle ordering as well as validity/expiry, derives public decision metadata
  from the authoritative transition, makes accepted and rejected exact command replay
  a no-op, and reconstructs retained journals from an empty genesis through the same
  deterministic decision function. It retains unknown in-use consumption for
  reconciliation and freezes after measured overrun. A dependency-free SQLite adapter
  now persists commands, transitions, receipts, revision/hash CAS state, and anchor
  intents atomically; exact response-loss retries, concurrent last-slot claims, and
  signed external checkpoint reconciliation are real-file guarded. The bundled file
  anchor is a reference trust boundary and must live on independently administered or
  append-only storage. Its reconciliation is currently synchronous and caller-driven;
  it neither bounds retry work nor fences later local revisions behind an unconfirmed
  head, and it deliberately mints no execution permit. This remains separate from the
  scored-node `cycle_budget`; harness preflight, a bounded anchor-outbox state machine,
  operation-bound effect permits, stop-work effects, and live compute/provider
  metering are explicit follow-up gates.
- A dependency-free production/L3 readiness case evaluator now reverifies exact
  storage bindings, a signed writer fence, least-privilege role projections, runtime
  state, and a policy-bound two-ended signed receipt-time component. Arbitrary cases
  can only become `CASE_ACCEPTED`; `HARNESS_GREEN` belongs to the separately locked
  OOPTDD fixture-and-attack suite. Live mode remains unsupported and no path sets
  `production_ready` or claims runtime VAL L3.
- An explicit HSWM agent-network design contract: agents act through a shared
  causal cut, observations reuse the verdict-free evidence record, LakatoTree
  supplies scientific adjudication, and a changed verdict must causally change
  the next dispatch. The document also records that generic attachment,
  causal-cut commit, and automatic redispatch are design targets rather than
  current default-runtime capabilities; BHGMAN remains an optional executor.
- A bounded HSWM research-programme decision contract with a primary
  validated-progress-per-cost hypothesis, equal-compute baselines, a
  non-hypergraph ablation, phased go/no-go gates, and explicit conditions for
  pruning HSWM, the hypergraph claim, or the LakatoTree scoring policy.
- A Longinus-grounded, machine-readable HSWM related-work boundary covering
  six adjacent systems, with reciprocal prose/URL/non-novelty checks, registered
  grounding references and KG anchor, and an explicit Meaning-SRP runtime gap
  instead of a fabricated code owner.
- Citation metadata for the software and its author.
- Contribution and security-reporting guidance.
- Package discovery metadata, a `lakatos` console entry point, and the installed
  `lakatotree-demo` Euler programme.
- Structured bug, research-proposal, and pull-request templates.
- A source-checkout Euler quickstart with actual deterministic verdict output.

### Changed

- Turned the HSWM implementation critique into a CI-guarded execution contract:
  the missing runtime owner is named as the current bottleneck, completion now
  requires replayable causal A/B receipts and fail-closed tests, and distributed
  agents, UI, graph changes, and further conceptual expansion stay behind that gate.
- Clarified that the README loop is the research-programme lifecycle, not a
  claim that LakatoTree already runs a generic behavioural feedback network.
- Reorganized the README around the public problem, 60-second first run, honest
  measurement and formal-verification limits, proof signals, and MetaHumotonic
  origin while retaining the machine-checked module roster.
- Made the `server` optional-dependency group self-contained by including the
  database drivers imported by the HTTP/MCP server at startup.
- Corrected the Euler flagship generalization to account for disconnected closed
  orientable boundaries (`χ = 2c - 2Σgᵢ`) and added a test that the formula
  actually absorbs the hollow-cube counterexample.
- Replaced unavailable PyPI commands in the consumption guide with commit-pinned
  source-checkout installation instructions for the pre-release period.

[Unreleased]: https://github.com/gj3447/lakatotree/commits/master
