# Changelog

All notable user-visible changes to LakatoTree will be recorded in this file.
The project follows the structure of Keep a Changelog and intends to use semantic
versioning once tagged releases begin.

LakatoTree has not yet published a tagged release or a package to PyPI. The
`Unreleased` section describes work on the default branch, not an available
distribution.

## [Unreleased]

### Changed

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
