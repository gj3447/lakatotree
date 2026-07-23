# Changelog

All notable user-visible changes to LakatoTree will be recorded in this file.
The project follows the structure of Keep a Changelog and intends to use semantic
versioning once tagged releases begin.

LakatoTree has not yet published a tagged release or a package to PyPI. The
`Unreleased` section describes work on the default branch, not an available
distribution.

## [Unreleased]

### Fixed

- Scoped `OpenQuestion` identity per tree: the `MERGE` key was a global `{name}`,
  so two trees opening the same `qname` silently shared one node (body
  last-write-wins, close/`n_visits` leaking across trees — observed in production
  as `judgment-ledger-repair-20260723`). Writers (`service.open_question`,
  `writer.add_node` M4 edge materialization, `writer.upsert_questions`) and the
  programme sync script now merge on the composite `(tree, name)`, and the
  required constraint changes from `lkt_open_question_name_unique` (global
  UNIQUE on `name`) to `lkt_open_question_tree_name_key` (NODE KEY on
  `(tree, name)`). Existing graphs need
  `scripts/migrate_open_question_tree_scope_20260723.cypher` (stamps `tree`,
  splits shared nodes per tree, re-points `RAISES_QUESTION`, swaps the
  constraint) before the new constraint can be created.

### Added

- Citation metadata for the software and its author.
- Contribution and security-reporting guidance.
- Package discovery metadata, a `lakatos` console entry point, and the installed
  `lakatotree-demo` Euler programme.
- Structured bug, research-proposal, and pull-request templates.
- A source-checkout Euler quickstart with actual deterministic verdict output.

### Changed

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
