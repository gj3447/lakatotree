# LakatoTree — a deterministic verdict engine for research programmes

> A research programme is scored by a **pure scoring function over pre-registered predictions**,
> not by an LLM's self-assessment. A verdict is admissible only if it is the scorer's output for a
> registered prediction and an external measurement — **self-reported verdicts are rejected by
> construction** (formally *modeled* in Lean 4, runtime-enforced by tests — see
> [Formal foundation](#formal-foundation)).
> Lakatos's "vague appraisal criterion" is closed by a quantified **Laudan problem-solving layer**
> (problem balance · PSR · comparative score · explicit abandonment rules).

> **Three views of the same system.** Engineering spec = this file. Conceptual model =
> [`docs/PIDNA.md`](docs/PIDNA.md). Vision/rationale (prose) = [`TOUCH_THE_SKY.md`](TOUCH_THE_SKY.md).
> Machine-checked theory = [`formal/Pidna.lean`](formal/Pidna.lean) (`lake build`, sorry=0).
>
> **Scope (read this first).** The Lean theorems certify the design *model* (`formal/Pidna.lean`),
> **not** the runtime Python: Lean rules out design errors (e.g. "progressive without novelty",
> non-commutative credence); `tests/` rule out implementation bugs in `judge.py`/`bayes.py`.
> "Machine-checked *theory*", not "verified engine" — full account in
> [Formal foundation → Scope, honestly](#formal-foundation).

---

## Problem and approach

LLM agents *confabulate*: they emit fluent self-reports ("implemented, all tests pass") with no
receipt behind them. LakatoTree removes an agent's ability to grade itself by splitting the system
into two subsystems with strict role separation, run as a closed loop:

| subsystem | role | modules |
|---|---|---|
| **Conjecture** | generate the next experiment, register a bold prediction, carry credence | `engine.py` · `heuristic.py` · `bayes.py` |
| **Verification** | deterministic scripted scoring, external-store readback, source-symbol binding | `judge.py` · ooptdd · Longinus |

**Loop:** conjecture registers a prediction → the world is measured → the verification subsystem
scores it (`judge`) → credence/lineage accumulate. **Coupling invariant:** every accepted result
pairs exactly one prediction with one independent verification; neither subsystem scores its own
output. (This is the "ascending double-helix" of `docs/PIDNA.md` stated as an architecture: two
coupled subsystems, role-separated, advancing only when a prediction is met by an external receipt.)

---

## Formal foundation

The kernel's load-bearing claims are **machine-checked in Lean 4** ([`formal/Pidna.lean`](formal/Pidna.lean),
core Lean only, no Mathlib → `lake build` is offline and fast). Ground-truth gate: `error=0, sorry=0`.

```bash
cd formal && lake build      # 12 theorems, sorry=0
```

| theorem | guarantee | code it pins |
|---|---|---|
| `Rung.derived` (field) | a verdict is **unforgeable**: a `Rung` cannot exist unless `verdict = judge …`. Self-report is *uninhabitable*. | the **kernel** verdict rule (caveat, prom-honesty/D: the *persisted* verdict is `dialectical_verdict(judge…)`, which can wrap/override the kernel output, and `novel`'s provenance is enforced at the Python boundary, not Lean-proven — `Rung.derived` pins the kernel, not the whole runtime) |
| `progressive_requires_novel` | progressive ⟹ a corroborated **novel** prediction | `judge.py` (F-CON-3: text alone ≠ novel) |
| `progressive_requires_improved` | progressive ⟹ real improvement past the noise band | `judge.py` |
| `no_novel_no_progressive` | improvement *without* novelty caps at `partial` (Lakatos's ad-hoc patch) | `judge.py` |
| `judge_total` | the verdict is total/exhaustive over the 4 outcomes (closed-world; nothing falls through) | `judge.py` |
| `rung_is_receipt` / `progressive_rung_is_novel` | a rung's verdict *is* the scorer's output, and a progressive rung carries novelty | `Rung` + `judge.py` |
| `rung_verdict_unique` | one verdict per evidence — **no second, negotiated re-score** | server `submit_test_result` lock |
| `reconfirm_idempotent` | re-confirming the same target adds nothing (use-novelty) | `bayes.branch_credence` content-dedup |
| `confirm_order_independent` | credence is independent of confirmation order (Bayesian coherence) | `bayes.branch_credence` |
| `confirm_monotone` | confirming never lowers credence (assets accumulate) | `bayes.branch_credence` |
| `stronger_confirm_strict` | a *new/stronger* target strictly raises credence — distinct novel predictions are independent evidence | `bayes.branch_credence` |

The `Rung` structure is the design's spine: its `derived : verdict = judge pred measured novel`
field means the type checker refuses any rung whose verdict was not produced by the scorer. The
manifesto line *"a self-report raises the helix by zero rungs"* is therefore a **typing rule**, not a
slogan.

**Scope, honestly.** `formal/Pidna.lean` is a **model of the kernel**, hand-written to mirror
`judge.py`/`bayes.branch_credence` — it is *not* an auto-extraction of the Python, so the proofs
certify the *theory*, while `tests/` certify the *implementation*. The two are complementary: Lean
rules out a class of design errors (e.g. "progressive without novelty", non-commutative credence);
pytest rules out coding errors in the actual modules. "Machine-checked theory", not "verified binary".

---

## Rigor stack (philosophy of science as layers, not competitors)
| layer | module | what it sees | strictness |
|---|---|---|---|
| Popper | `judge.py` | refuted ⟹ rejected (discrete verdict) | strongest |
| **Bayes** | `bayes.py` | per-evidence credence update (continuous); a high-asset branch survives one counterexample | mid |
| Laudan | `laudan.py` | problem-solving power over truth/falsity | loose |

**Abandonment timetable** (what Lakatos left unspecified):
- Laudan (discrete, interpretable): ① ≥3 consecutive non-progressive ② 5-node budget spent ∧ 0 hits ③ problem balance ≤ −2
- Bayes (continuous, asset-weighted): branch credence < 0.1. Pre-registered novel hit = strong evidence (BF↑); post-hoc patch = weak (BF≈1)
- Honest limit: Bayes scores *within-tree* credence only — **new-hypothesis generation belongs to `heuristic.py`/`directions`** (the conjecture subsystem), not to the verifier.

---

## Why a tree, not a line

A single path presumes it already knows which conjecture wins. By **computational irreducibility**
(Wolfram), you cannot in general predict which programme progresses without running it — so the
search hedges across branches instead of betting everything on one. The structure is then a search
tree managed by the loop:

- scout the most informative branch — `explore.py` (UCB + Value-of-Information)
- prune degenerating branches — `laudan.should_abandon` (3 rules)
- reinforce advancing branches — `bayes.py` (credence)
- record one programme superseding a rival — `kuhn.py` (Lakatos–Zahar supersession)
- keep genealogy — `prov.py` (W3C PROV-O); a rootless blob cannot say why it is true, which is the
  topology of confabulation

Branches diverge exactly when their verification paths become independent (a sub-question's progress
no longer constrains its sibling's) — operationally, when `explore.rank_questions` ranks them
separately. The tree is *not* a higher-order spiral; spiral (within-branch ascent) and tree
(between-branch competition) are orthogonal (see `docs/PIDNA.md §3`, where the "meta-spiral"
hypothesis was falsified and pruned — the project applies its own method to itself).

## Internet observations as rival-programme evidence

Web data enters the tree through `G-Web`, but it is not treated as a loose citation. An
`InternetObservation` can now be embedded into the programme structure as:

```text
InternetObservation
  -> TheoryEmbedding(lakatos_location, theoretical_basis, foundation_refs)
  -> LakatosNode
  -> RivalProgrammeLink(supports|contradicts|qualifies)
  -> ReferenceSite:Longinus(sourceId, sourcePath)
```

That is the intended meaning of "putting a rival programme on the Lakatos tree": the external
observation is located in the hard-core / protective-belt / heuristic coordinates of the active
programme, then linked as typed evidence for or against a rival. Rival comparisons remain queryable
through the existing Pareto+Borda leaderboard, while Longinus binds the ingestion path back to real
source symbols.

MCP/HTTP path:
`add_observation(..., theory_basis=..., rival_name=..., rival_relation=..., longinus_refs_json=...)`
posts to `/api/tree/{name}/node/{tag}/observation`.

---

## Module map · enforced layering

Pure modules (zero I/O, same ruling anywhere — theory = `THEORY.md`) live under `lakatos/`.
**Dependency direction is enforced** by [`.importlinter`](.importlinter) (import-linter — `lint-imports`):
a strict layering **`programme → verdict → quant → io`** (a layer may import lower layers, never a
higher one) over a shared **foundation** at the package root that any layer may import. `engine.py`
is pure foundation since the split — it imports no `io`/`quant` (`io/replay.py` holds the
lineage-replay gates; `trust.py` is a root scoring primitive). **The layer roster below is a
drift-guarded contract**: `tests/test_readme_longinus.py` checks every module resides in its claimed
layer (and that the set of layers matches `.importlinter`) — this map cannot silently lie.

### Foundation — `lakatos/` (root; shared, importable by any layer)
`engine` `verdicts` `grounding` `trust` `claim` `world_gates` `harness` `harness_run` `longinus` `semantic_surface` `cli` `mcp_server` `eureka` `facts` `research_import`
- `engine` sparse research frame — enums / `GateResult` / gates / possibilities / event log / credence promotion / `SourceCredibilityScore`
- `verdicts` verdict-vocabulary single source of truth · `grounding` all constants with tier honesty (literature / policy-in-scale / policy)
- `trust` TrustRank/EigenTrust source-scoring primitive (shared by `engine` + `quant.bayes`) · `claim` ClaimStanding (upper/lower-realm confidence + blockers)
- `world_gates` G-Web/G-WorldAction · `longinus` code↔KG binding drift audit · `semantic_surface` meaning↔code owner gate · `harness`/`harness_run` ports & adapters · `cli`/`mcp_server` surfaces · `eureka` felt-vs-true detector · `facts` declarative fact-query evaluator · `research_import` internet-search → research-tree import adapter (composes G-Web + credibility gates)

### `verdict/` — judgment kernel (the scorer; modeled in `formal/Pidna.lean`)
`judge` `pnr` `spine` `promote` `certify` `argue` `compose`
- `judge` [Popper] 4 verdicts + pre-registration gate + structural corroboration (NovelTarget vs measurement)
- `pnr` [Proofs & Refutations] counterexample-response dialectic · `spine` `dialectical_verdict` (reconcile metric + qualitative + PnR)
- `promote` fail-closed CANONICAL allowlist · `certify` 5-gate AND certificate · `argue` Dung AF grounded-extension justification · `compose` gate outcome composition

### `quant/` — quantitative substrate
`bayes` `laudan` `metrics` `multiplicity` `fertility` `calibrate`
- `bayes` branch credence over verdict sequence (use-novelty dedup; eigentrust weighting) · `laudan` problem balance / PSR / `should_abandon` (3 rules)
- `metrics` tree metrics (progress / rejection / degeneration + Bayes + fertility + Laudan) · `multiplicity` BH/FDR + Bonferroni false-progressive screen
- `fertility` novel-prediction hit record (`nobel_grade`) · `calibrate` Brier/log/ECE proper scoring

### `programme/` — programme-level / comparative / meta-policy
`kuhn` `leaderboard` `lifecycle` `stack` `agm` `explore` `heuristic` `series` `flip`
- `explore` bandit UCB + VoI (which branch next) · `heuristic` [MSRP] negative (hard-core protection) + positive (`generate_moves`)
- `flip` per-layer verdict-flip metric — counterfactual pivotality: how often each rigor layer (Popper/Bayes/Laudan) actually *changed* the `stack` decision (composes `quant.metrics.branch_inputs` + `stack`; surfaced in `metrics.layer_flips`)
- `kuhn` Lakatos–Zahar supersession · `agm` AGM/Levi hard-core revision (PROTECTED default) · `leaderboard` Pareto+Borda rival ranking
- `stack` inter-layer vote + 2/3 quorum · `lifecycle` harvest/diverge/extinct · `series` path-level diagnostic over programme time-series

### `io/` — evidence, provenance, persistence, observability
`lineage` `replay` `rebuild` `adapters` `prov` `envfp` `oo_sink` `oo_verify` `marquez_sink`
- `lineage` manifest + env fingerprint + root-replay DAG · `replay` lineage-replay gates (`LineageReplayGate`/`ReproducibilityContract`, split out of `engine`)
- `rebuild` "receipts not claims" rebuild-from-raw · `prov` W3C PROV-O triples + replay command · `envfp` environment fingerprint
- `oo_sink`/`oo_verify` observability LTDD · `adapters`/`marquez_sink` external lineage export (OpenLineage / DVC / PROV)

```
formal/    ★Lean 4 formal kernel — machine-checked verdict theory (lake build, sorry=0)
server/    FastAPI shell (:55170) — Neo4j (graph SoT) + PG (append-only history) + Mongo (artifacts)
judges/    scoring scripts (result file → metric, LLM-independent)
examples/  research programmes; euler_polyhedron_programme.py = engine-generated verdicts (no hand-typed verdict)
tests/     verdict/engine/server-contract TDD — rule changes start from RED; test_readme_longinus.py drift-guards this module map
```

## Build & verify
```bash
python -m pytest tests/ -q                  # engine + server contract (Python)
lint-imports                                # enforced layering (programme → verdict → quant → io); .importlinter
cd formal && lake build                     # formal kernel (Lean 4): error=0, sorry=0
bash server/run.sh                          # http://localhost:55170 (dashboard /, API /api/*)
```

CLI (selected):
```bash
python -m lakatos.cli metrics <tree>        # progress rate / Bayes credence / fertility / multiple-comparison correction
python -m lakatos.cli directions <tree>     # next branch by VoI (numerator = positive-heuristic estimate, not a constant)
python -m lakatos.cli heuristic <tree>      # MSRP policy — negative (hard-core protection) + positive (generated moves)
python -m lakatos.cli stack <tree>          # Popper/Bayes/Laudan explicit vote + quorum (gap3)
python -m lakatos.cli lifecycle <tree>      # programme termination: harvest/diverge/extinct/active
python -m lakatos.cli leaderboard a,b,c     # rival programmes — Pareto+Borda (no single-score reduction)
python -m lakatos.cli trust <tree>          # eigentrust global source trust over the observation graph (P6)
python -m lakatos.cli certificate <tree> <tag>   # 5-gate AND certificate
claude mcp add lakatotree -- python -m lakatos.mcp_server
```

## Observability as ground truth (oo LTDD)
The "receipts, not claims" rule (`rebuild.py`) is applied to the **test suite itself**.
`tests/conftest.py` ties each pytest session to a correlation id (cid) and ships each outcome via
`oo_sink` to the `tests` stream; failure RCA is one `trace_cycle(cid)` call. With the gate off
(`CONSUMER_LOGS_E2E`/`OO_PASS` unset) it is a complete no-op (local = quiet); ship failures never break
the build (observation does not change the verdict).
```bash
CONSUMER_LOGS_E2E=1 OO_PASS=*** python -m pytest tests/ -q   # ship traces (gate on)
```

## Server contract (v1.1)
- `BRANCHED_FROM` supports a multi-parent DAG; edges record `inferred/relation_kind/evidence_ref`.
- Closing a question is an append-only `QuestionClosure` event, not a `closed_by` overwrite.
- Verdict vocabulary has a single source of truth: `lakatos.verdicts`.
- `CANONICAL` is not an absolute truth but a temporary current-best with a `current_best_pointer` and a scope/assumption/evidence window.
- `metrics` force-exposes `coverage_backlog` to prevent overstating completeness.
- `ClaimStanding` separates upper-realm (internet/human/kg) from lower-realm (bash/data/git/agent) evidence and reports confidence + blocking reasons; `ResearchEvent` is append-only evidence that never changes a verdict.

## Foundation map
Before a project runs, required prior knowledge is tracked as `FoundationRequirement` in categories:
`theory` · `domain` · `data` · `metric` · `trust` · `reproducibility` · `human_protocol`.
```bash
python -m lakatos.cli foundation <tree>
```

## Theoretical references
- Lakatos, *Methodology of Scientific Research Programmes* (1970) — novel prediction, hard core, two heuristics, programme branching
- Lakatos, *Proofs and Refutations* (1976) — counterexample-response dialectic (`pnr.py`; `examples/euler_polyhedron_programme.py` runs it end-to-end)
- Popper — falsification, bold conjectures
- Laudan, *Progress and its Problems* (1977) — problem-solving effectiveness
- Zahar (1973) — use-novelty (basis of the credence dedup; `bayes.py`)
- Bayesian confirmation: Jeffreys (1961), Kass–Raftery (1995) — BF bands (`grounding.py`, with tier-honesty: literature vs policy-in-scale vs policy)
- Wolfram, *A New Kind of Science* (2002) — computational irreducibility (why a tree, not a line)

Theory detail = [`THEORY.md`](THEORY.md) (7 layers + 8 honest gaps). Quantitative grounding =
[`docs/QUANTITATIVE_GROUNDING.md`](docs/QUANTITATIVE_GROUNDING.md) (auto-generated from `grounding.py`).

# KG: SA_LakatoTree_Server_20260612 / Doctrine 라카토스 / span_lakatotree_engine
