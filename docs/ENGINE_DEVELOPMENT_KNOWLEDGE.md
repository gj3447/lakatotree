# LakatoTree Engine Development Knowledge

> Goal: make LakatoTree a small, testable research-program engine that can bind
> internet observations, human/agent critique, bash execution, source history,
> and raw-data replay into one auditable tree.

## Hard Core

These rules are not ordinary configuration. A branch that violates them cannot
be marked `progressive`.

1. Internet observations are untrusted world observations, not citation text.
2. Human and agent comments, questions, doubts, and verdicts are first-class
   critique nodes.
3. Agent-owned code building must leave bash/test/git evidence.
4. Final data artifacts are canonical only when replayable from raw roots.
5. Buffers and caches are allowed, but only as invalidatable derived artifacts.
6. Every important claim must have a Lakatos location and a verdict.
7. Degenerating branches are preserved as history; they are not deleted.

## Existing Engine Modules

| Module | Responsibility | Development note |
|---|---|---|
| `lakatos/engine.py` | Cross-layer gates for internet, Lakatos verdict, bash, and lineage replay | Keep it pure and dependency-light. |
| `lakatos/lineage.py` | Raw-to-final derivation DAG and stale detection | This is the BPC ZDF replayability core. |
| `lakatos/trust.py` | TrustRank/EigenTrust style internet trust signals | Use as a component of evidence, never as truth. |
| `lakatos/prov.py` | W3C PROV-style entity/activity/agent mapping | Bridge to RDF/PROV-JSON later. |
| `lakatos/argue.py` | Human+agent critique via argumentation | Unanswered doubts must block silent promotion. |
| `lakatos/claim.py` | ClaimStanding read-model | Combine upper/lower confidence with foundation, doubt, and lineage blockers. |
| `lakatos/harness.py` | Hexagonal cycle harness | Keep ports explicit: internet read, bash exec, git, HTTP/KG. |

## Open Source References

### 1. OpenLineage

Reference: https://openlineage.io/

Use for the event vocabulary of pipeline lineage: `Run`, `Job`, `Dataset`, input
datasets, output datasets, and run facets. This maps directly to:

```text
PipelineRun -> TransformStep/Job
RawDataArtifact/DerivedDataArtifact -> Dataset
PipelineRun start/complete -> OpenLineage RunEvent
```

Do not copy the full OpenLineage stack into the core engine. Add an optional
adapter at the edge. Current implementation: `lakatos/adapters.py` exports
OpenLineage-shaped `RunEvent` dictionaries from `Derivation` and
`LineageReplayResult`.

### 2. Marquez

Reference: https://marquezproject.ai/

Use as the optional UI/backend reference for OpenLineage events. It is useful
when LakatoTree needs a lineage graph viewer, but the canonical engine should
still work without a server.

Good future adapter shape:

```text
LineageReplayGate result
  -> OpenLineage RunEvent
  -> Marquez HTTP endpoint
```

### 3. DVC

Reference: https://doc.dvc.org/start/data-pipelines/data-pipelines

Use as the closest open-source reference for raw-rooted replay:

```text
raw ZDF/deps + command + params + outs -> dvc.yaml style stage
recorded output hashes -> dvc.lock style manifest
rebuild from raw roots -> dvc repro style replay
```

LakatoTree should not require DVC, because BPC data may live outside a neat ML
project. But `RebuildRecipe` should be close enough that exporting to `dvc.yaml`
is mechanical. Current implementation: `derivations_to_dvc_pipeline()`,
`derivations_to_dvc_lock()`, and `rebuild_recipe_manifest()` expose a
DVC-style replay manifest from raw roots.

### 4. W3C PROV / Python `prov`

References:
- https://www.w3.org/TR/prov-dm/
- https://pypi.org/project/prov/

Use W3C PROV as the semantic floor:

```text
Entity   -> InternetObservation, RawDataArtifact, DerivedDataArtifact, SourceCodeNode
Activity -> PipelineRun, BashAct, AgentBuild, WebFetch
Agent    -> HumanSigmaOracle, AgentPureBuilder, Tool, Organization
```

Python `prov` is a good optional serializer target for PROV-N, PROV-JSON,
PROV-XML, RDF, and graph visualizations. Keep `lakatos/prov.py` as the local
minimal model, then add a serializer adapter if needed. Current implementation:
`derivations_to_prov_document()`, `observation_to_prov_document()`, and
`bash_act_to_prov_document()` emit PROV-shaped documents without importing
`prov`.

### 5. MLflow Dataset Tracking

Reference: https://mlflow.org/docs/latest/ml/dataset/

Use as a reference for experiment artifacts, params, metrics, and dataset
tracking. Do not use it as the canonical source of truth for Lakatos verdicts.
LakatoTree's verdict requires Lakatos gates plus critique and replayability,
which MLflow does not provide by itself.

### 6. NetworkX / Neo4j

Use NetworkX for pure in-memory graph algorithms and tests. Use Neo4j for the
long-lived KG mirror and queryable audit history. Do not make the pure engine
depend on Neo4j.

## Required Ontology

The engine should preserve these labels even if the storage backend changes.

| Label | Meaning |
|---|---|
| `LakatosTree` | Research programme root |
| `LakatosNode` | Branch or hypothesis node |
| `InternetObservation` | One append-only web fetch/snapshot |
| `SourceCredibilityScore` | Decomposed source trust components |
| `HumanQuestion` / `HumanComment` / `HumanVerdict` | Sigma-oracle critique |
| `AgentBuild` | Agent-owned implementation action |
| `BashAct` | Shell execution with stdout/stderr/exit evidence |
| `RawDataArtifact` | Immutable raw source such as a ZDF file |
| `DerivedDataArtifact` | Generated buffer, cache, report, or final output |
| `BufferArtifact` | Intermediate artifact, never canonical by itself |
| `FinalArtifact` | Accepted output that must have a rebuild recipe |
| `PipelineRun` | One execution from inputs to outputs |
| `TransformStep` | Logical step with code, params, and environment binding |
| `RebuildRecipe` | Replay command sequence from raw roots |

## Gates

| Gate | Blocks when |
|---|---|
| `G-Web` | Web source lacks URL, fetch time, content hash/snapshot, source type, trust components, or Lakatos location |
| `G-Trust` | A claim is promoted from ambiguous/inferred without direct source, corroboration, or human verdict |
| `G-Lakatos` | Branch lacks anomaly reframing, independent testable consequence, excess empirical content, or hard-core preservation |
| `G-WorldAction` | A bash-supported claim lacks command, cwd, exit code, output summary/hash, or touched-file evidence |
| `G-DataLineage` | Generated artifacts lack role, path, hash, inputs, producing command, code commit, params, env, schema, or cache policy |
| `G-RebuildFromRaw` | Final artifact cannot be replayed from raw roots or declared metric tolerance |
| `G-SourceHistory` | Source code change lacks git status/diff/test or Longinus-style source binding |
| `G-Human` | Hard-core mutation, ambiguous source promotion, or practical acceptance of a degenerating branch lacks human verdict |
| `G-ClaimStanding` | A claim has foundation gaps, unresolved human doubts, missing upper/lower evidence, or failed raw replay |

## BPC ZDF Rule

For BPC-like pipelines, every final output must answer:

1. Which raw ZDF files are the roots?
2. Which scripts and code commits produced each buffer?
3. Which params and environment produced each output hash?
4. Which buffers are invalidated when raw ZDF, code, params, or env changes?
5. Can the final output be reproduced by ignoring existing buffers and running
   the recorded recipe from raw ZDF roots?

If answer 5 is no, the branch remains `progressive_conditional`.

## Implemented Reference Adapters

`lakatos/adapters.py` now keeps the pure engine DB-free while exposing external
ecosystem vocabulary:

1. OpenLineage-shaped `RunEvent` export for `Derivation` and
   `LineageReplayResult`.
2. DVC-shaped `dvc.yaml`/`dvc.lock` export and a raw-rooted rebuild manifest.
3. W3C PROV-shaped documents for pipeline derivations, internet observations,
   and bash actions.

## Immediate Development Backlog

1. Add a first-class manifest dataclass that groups raw ZDF roots with content
   hashes and schema metadata.
2. Add environment fingerprint support: Python version, package lock hash,
   relevant env vars, CUDA/HALCON/Zivid versions if present.
3. Add a CLI command that verifies `G-RebuildFromRaw` for one final artifact.
4. Add an I/O layer that sends the existing OpenLineage event dicts to Marquez.
5. Add optional `prov` package serialization for PROV-N/PROV-JSON/RDF.

## Non-Goals

- Do not turn the pure engine into an Airflow/Dagster replacement.
- Do not require a database for unit tests.
- Do not let PageRank, TrustRank, or MLflow metrics alone decide truth.
- Do not make buffers canonical just because they are expensive to recompute.
- Do not delete rejected branches; rejected branches are negative evidence.

## Backlog Status (2026-06-12, Claude Fable)

- [x] **1. Manifest dataclass** — `lakatos/lineage.py` `RawRoot` + `RebuildManifest` +
  `build_manifest(final, bo, root_schemas, env_sha, tolerance)`. Groups raw roots
  (path+sha+schema) with env fingerprint and topo recipe.
- [x] **2. Environment fingerprint** — `lakatos/envfp.py`: python/platform/numeric
  packages(numpy/scipy/trimesh)/determinism env vars/domain tools(Zivid/HALCON/CUDA)
  → deterministic dict + sha256. Wired into `Derivation.env`, `lineage.env_drift`,
  and `LineageReplayGate.evaluate(..., current_env=)` (G-RebuildFromRaw now env-aware).
- [x] **3. G-RebuildFromRaw CLI/endpoint** — `GET /api/rebuild-verify/{artifact}` +
  `lakatos rebuild-verify <final>`: reproducible + stale + env_drift → `rebuildable`
  or `progressive_conditional` (BPC ZDF Rule #5), emits full RebuildManifest.
- [x] **4. Marquez I/O** — `send_openlineage_events_to_marquez()` posts existing
  OpenLineage-shaped event dicts to Marquez `POST /api/v1/lineage`, with
  injected opener for network-free TDD and explicit failure surfacing.
- [x] **5. `prov` package serializer** — `prov_document_to_prov_json()` emits
  dependency-free PROV-JSON shape; `serialize_prov_document(..., use_prov_package=True)`
  delegates to optional `prov` for PROV-N/other package-supported formats.
- [x] **6. ClaimStanding read-model** — `lakatos/claim.py` combines
  upper-world evidence (`internet/human/kg`) and lower-world evidence
  (`bash/data/git/agent`) with foundation gaps, unresolved doubts, and
  `LineageReplayGate` results. Exposed as `GET /api/tree/{name}/node/{tag}/claim-standing`,
  CLI `claim-standing`, and MCP `claim_standing`.
