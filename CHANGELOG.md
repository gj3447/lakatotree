# Changelog

All notable user-visible changes to LakatoTree will be recorded in this file.
The project follows the structure of Keep a Changelog and intends to use semantic
versioning once tagged releases begin.

LakatoTree has not yet published a tagged release or a package to PyPI. The
`Unreleased` section describes work on the default branch, not an available
distribution.

## [Unreleased]

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
