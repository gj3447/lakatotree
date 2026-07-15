# LakatoTree

**Deterministic verdicts for research programmes: pre-register a prediction, measure the world, and derive a reproducible judgement without letting the agent grade itself.**

[![CI](https://github.com/gj3447/lakatotree/actions/workflows/ci.yml/badge.svg)](https://github.com/gj3447/lakatotree/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-%3E%3D3.10-3776AB)
![Lean](https://img.shields.io/badge/Lean_4-theory_model-6B4FBB)

LakatoTree is a Python engine for running branching, Lakatosian research programmes. An experiment starts with a locked prediction and metric. A measurement is then scored by a pure function, producing one of four kernel verdicts: `progressive`, `partial`, `equivalent`, or `rejected`. The result can be carried into programme history, Bayesian credence, Laudan problem-solving metrics, provenance, and rival-programme comparison.

The project is useful when an AI agent, research workflow, or evaluation harness must show *why* it claims progress. It is not a general experiment runner, a truth oracle, or a replacement for domain-specific measurement. If you only need to log arbitrary scores, LakatoTree is deliberately stricter than necessary.

> **Honest scope.** Verdict derivation is deterministic, but the default live path currently receives a client-submitted numeric value. Receipts seal and replay that value: **reproduction-confirmation, not value-ownership**. See the [measurement-sovereignty ADR](docs/ADR-measurement-sovereignty-20260703.md). Lean checks the kernel's theory model; it does not verify the Python binary or prove the provenance of a measurement.

## Try it in 60 seconds

The Euler polyhedron example needs no database, web server, credentials, or third-party runtime dependency. LakatoTree is not currently published on PyPI, so install it from a source checkout:

```bash
git clone https://github.com/gj3447/lakatotree.git
cd lakatotree
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
lakatotree-demo
```

Actual output:

```text
convex_conjecture    χ=   2  metric=       None  pnr=          None  → canonical_stage
hollow_cube          χ=   4  metric=   rejected  pnr=          None  → rejected
monster_barring      χ=None  metric=    partial  pnr=  degenerating  → degenerating
exception_barring    χ=None  metric=    partial  pnr=  degenerating  → degenerating
proofs_refutations   χ=   0  metric=progressive  pnr=   progressive  → progressive
```

No scored node hand-types its verdict. The unscored administrative root is labeled `canonical_stage`. Each experimental node carries an in-process `Prediction`; topology-derived measurements are used where topology is present, while the monster- and exception-barring scenarios declare their post-exclusion fit and a Proofs-and-Refutations response. The demo exercises the pure scoring contract, not the service's timestamped registration lock. Its mature formula `χ = 2c − 2Σgᵢ` both absorbs the hollow-cube boundary (`c=2`, `χ=4`) and predicts the connected torus result (`c=1`, `g=1`, `χ=0`).

The same installed demo is available as `python -m lakatos.demos.euler`; `examples/euler_polyhedron_programme.py` remains a source-checkout compatibility wrapper.

## The loop

```text
Conjecture                    Verification
generate a question          read a measurement
        │                            │
        └── pre-register prediction ─┤
                                     ▼
                         deterministic judge
                                     │
                    verdict + receipt + lineage
                                     │
                       update / branch / prune
                                     └──────► next conjecture
```

The conjecture side proposes experiments; the verification side scores them. A claim of novelty is not enough: `progressive` requires both improvement beyond the noise band and a corroborated structural `NovelTarget`. Improvement without novelty is `partial`. A refutation is `rejected`; movement within the declared noise band is `equivalent`.

Programme-level layers add context without weakening that kernel rule:

- Popper supplies discrete falsification through `judge.py`.
- Bayes accumulates branch credence while deduplicating repeated target confirmations.
- Laudan tracks problem balance and explicit abandonment conditions.
- Proofs and Refutations models responses to counterexamples.
- A tree keeps rival conjectures alive until evidence justifies reinforcement, pruning, or supersession.

## Use the pure Python core

The installed `lakatos` core uses only the Python standard library. This minimal pure-function example constructs an improvement target and a distinct novel target, supplies both measurements, and lets the engine derive the verdict. Production timestamp and identity locking occur at the service boundary, not in this constructor call:

```python
from lakatos.verdict.judge import NovelTarget, Prediction, judge

prediction = Prediction(
    metric_name="latency_ms",
    direction="lower",
    baseline_value=100,
    noise_band=5,
    novel_prediction="error rate stays below 1%",
    closes_question="q-latency",
)
novel = NovelTarget(
    metric_name="error_rate",
    direction="lower",
    threshold=0.01,
)

result = judge(
    prediction,
    measured=72,
    novel_target=novel,
    novel_measured=0.006,
)
print(result.verdict)  # progressive
```

For programme authoring, evidence-record validation, and tree metrics, use `lakatos.programme.authoring`, `lakatos.programme.evidence`, `lakatos.programme.record_judge`, and `lakatos.quant.metrics`. The [consumption guide](docs/CONSUMING_LAKATOTREE.md) explains the API boundary and gives source-checkout installation paths for the current pre-release period.

### Portable format: `lakato-evidence-record/v1`

The input format is a small, **tool-agnostic** JSON contract you can adopt on its own — a producer emits an evidence record; a ~25-line validator rejects it unless the claim was **pre-registered**, **grounded in cited inputs**, and carries **no self-authored verdict** (the producer never grades itself). Emit it from any harness, in any language; LakatoTree is just one consumer. **Spec: [`docs/lakato-evidence-record-v1.md`](docs/lakato-evidence-record-v1.md).**

The CLI is available as a module, for example `python -m lakatos.cli --help`. Commands that read or mutate a named tree require a configured LakatoTree server and its backing stores; the repository's current server launch scripts contain deployment-specific assumptions and are not a portable public quickstart. The pure library and Euler demo do not require that service.

Optional dependency groups are declared in `pyproject.toml`: `server`, `db`, `prov`, `receipts`, `dev`, `integration`, and `all`. From a checkout, install one with `python -m pip install -e ".[dev]"` or the relevant extra.

## Proof signals and limits

LakatoTree treats verification claims as artifacts that can fail CI:

- [`formal/Pidna.lean`](formal/Pidna.lean) contains **12 theorems** with `sorry=0`, built with pinned Lean 4 and no Mathlib.
- The gating Python suite covers the engine and server contract; the verdict and quantitative kernel has a `>=95%` coverage ratchet.
- `.importlinter` enforces dependency direction and prevents the engine from importing research examples.
- OOPTDD receipts are rediscovered and re-verified in CI.
- `c1verify` is installed and tested in a clean environment where `lakatos` and `server` are not importable, checking verifier independence by construction.
- This README's theorem count and module roster are regression-tested against Lean, the filesystem, and `.importlinter`.

The central Lean structure is `Rung`: its `derived` field binds a kernel verdict to `judge prediction measured novel`. This rules out a forged kernel `Rung` inside the model. It does **not** prove the entire runtime. Persisted results may be wrapped by `dialectical_verdict(judge(...))`; novelty provenance, registration locks, receipt storage, and measurement handling are enforced at Python and service boundaries. In short: machine-checked theory plus tested implementation, not a formally verified executable.

## Origin and ethos

LakatoTree is developed by **Gyeongjun Ra (라경준)** inside [MetaHumotonic](https://metahumotonic.com), his philosophy-and-engineering world. It is one executable artifact of that larger body of work, not a complete definition of it. The connection is an ethic of traceable consequence: a system should confront the observable traces left by its own rules instead of declaring itself successful.

That origin does not turn mythology into a software guarantee. Claims in this repository stand or fall by code, tests, proofs within their stated scope, and reproducible receipts. User-authored MetaHumotonic canon remains the primary source; project rationale such as [`TOUCH_THE_SKY.md`](TOUCH_THE_SKY.md) is an interpretive engineering layer, not a substitute for the canon.

## Architecture at a glance

The dependency direction is `programme → verdict → quant → io`, over a shared foundation. Pure scoring lives under `lakatos/`; `server/` is the optional FastAPI and persistence shell; `formal/` contains the Lean model; `examples/` contains research programmes; `judges/` contains scoring scripts; and `tests/` holds executable contracts.

| path | responsibility |
|---|---|
| `lakatos/verdict/` | deterministic judgement and dialectical composition |
| `lakatos/quant/` | credence, problem-solving, calibration, multiplicity |
| `lakatos/programme/` | branching, lifecycle, comparison, public authoring |
| `lakatos/io/` | receipts, lineage, replay, persistence adapters |
| `formal/` | machine-checked kernel model |
| `server/` | optional HTTP/MCP surface and stores |

Detailed explanations belong in [THEORY.md](THEORY.md), the [PIDNA conceptual model](docs/PIDNA.md), [quantitative grounding](docs/QUANTITATIVE_GROUNDING.md), and the prose rationale [TOUCH_THE_SKY.md](TOUCH_THE_SKY.md).

## Module map

This compact roster is machine-checked against the package. See the architecture links above for meaning.

### Foundation — `lakatos/`
`engine` `engine_identity` `verdicts` `node_state` `grounding` `coverage` `trust` `claim` `world_gates` `harness` `harness_run` `longinus` `longinus_dashboard` `semantic_surface` `cli` `mcp_server` `eureka` `facts` `research_import` `provenance_backfill` `ontology` `assurance` `write_cert`

### `verdict/`
`judge` `pnr` `spine` `promote` `certify` `cert_gate` `argue` `compose` `industrial` `kusari` `z_height`

### `quant/`
`bayes` `laudan` `metrics` `multiplicity` `fertility` `calibrate`

### `programme/`
`kuhn` `leaderboard` `lifecycle` `stack` `agm` `explore` `heuristic` `series` `flip` `tradition` `consilience` `authoring` `evidence` `record_judge`

### `io/`
`lineage` `replay` `rebuild` `reconcile` `adapters` `prov` `envfp` `oo_sink` `oo_verify` `marquez_sink` `marquez_verify`

## Develop and verify

```bash
python -m pip install -e ".[dev]"
python -m pytest tests/ -q
lint-imports
(cd formal && lake build)
```

Lean requires its pinned toolchain. Database integration tests and the optional service have additional environment requirements; the default unit suite and Euler demo do not.

## Documentation paths

- **Start integrating:** [Consuming LakatoTree](docs/CONSUMING_LAKATOTREE.md)
- **Understand the design:** [THEORY.md](THEORY.md) and [PIDNA](docs/PIDNA.md)
- **Inspect formal claims:** [formal/Pidna.lean](formal/Pidna.lean)
- **Review measurement limits:** [measurement-sovereignty ADR](docs/ADR-measurement-sovereignty-20260703.md)
- **Read the philosophical rationale:** [TOUCH_THE_SKY.md](TOUCH_THE_SKY.md)

## Cite and reuse

GitHub can render the repository's [`CITATION.cff`](CITATION.cff) as a software citation for **Gyeongjun Ra (라경준)**. No DOI or tagged release exists yet, so include the repository URL, access date, and exact commit SHA when reproducibility depends on the current source revision.

No `LICENSE` file is currently included. Public visibility does not by itself state reuse terms; review the repository status before copying, modifying, or redistributing the code. Contribution and vulnerability-reporting paths are documented in [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`SECURITY.md`](SECURITY.md); unreleased changes are tracked in [`CHANGELOG.md`](CHANGELOG.md).

## Theoretical references

The engine draws on Lakatos's *Methodology of Scientific Research Programmes* and *Proofs and Refutations*, Popper on falsification, Laudan's *Progress and its Problems*, Zahar on use-novelty, and Bayesian confirmation work by Jeffreys and Kass–Raftery. [THEORY.md](THEORY.md) distinguishes implemented rules, operational policy, open limits, and philosophical motivation; it should be preferred over treating this short list as a complete bibliography.

<!-- Internal drift anchor required by the repository's Longinus binding test: span_lakatotree_engine -->
