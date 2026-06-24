# Three-D PROM Protocol

PROM = Programme Research Operating Model.

This is the LakatoTree operating protocol for BPC, LX3, SX3i, and later 3D
inspection branches. It converts literature/background knowledge into a branch
promotion discipline.

## Status Vocabulary

- `adopted`: production path exists, tests pass, receipts are replayable, and
  measurement uncertainty/conformity story is explicit.
- `progressive`: a pre-registered metric improved with external receipts.
- `pending-port`: research branch is useful, PrismV2 implementation is not
  production-complete.
- `reference`: background/diagnostic branch; useful but not a production path.
- `blocked`: definition, data, source, or dependency is missing.
- `rejected`: negative control or independent check falsified the claim.

## Promotion Rules

1. Precision does not imply accuracy.
2. ICP residual does not imply GD&T conformance.
3. Marker pose repeatability does not imply part accuracy.
4. A branch needs a negative control before it can be trusted.
5. Production adoption requires a code path and a test path, not only a
   LakatoTree node.

## Current PROM Board

| Branch | Current Status | Next Gate | Kill Criterion |
|---|---|---|---|
| BPC frozen measure-lot | adopted | add uncertainty fields to feature records | silent BPC GICP verdict fallback |
| LX3 known-axis ArUco | pending-port | bush/CAD independent accuracy check | bush/CAD error over tolerance |
| SX3i reader-fix marker branch | research-only | C2 connected assembly, then C3 feature-coincidence | fused precision cannot beat XL250 floor |
| OMD | blocked | source/interface/test contract appears | no definition |

## Experiment Record Template

```json
{
  "programme": "bpc|lx3|sx3i",
  "branch": "branch_tag",
  "registered_claim": "one falsifiable sentence",
  "metric": {"name": "error_mm", "direction": "lower"},
  "baseline": {"value": 1.0, "unit": "mm", "receipt": "path"},
  "threshold": {"value": 0.1, "unit": "mm", "decision_rule": "pre_registered"},
  "receipts": {
    "input": [],
    "command": "",
    "output": [],
    "code": []
  },
  "negative_controls": [],
  "result": {"value": null, "unit": "mm"},
  "uncertainty": {"value": null, "method": "not_estimated"},
  "verdict": "progressive|partial|rejected|blocked"
}
```

## Literature Anchors

- Degeneracy-aware point-cloud registration:
  https://arxiv.org/html/2408.11809v2
- Plane-to-plane point-cloud registration and uncertainty:
  https://www.ipb.uni-bonn.de/pdfs/foerstner17efficient.pdf
- AprilTag/fiducial marker error propagation:
  https://pmc.ncbi.nlm.nih.gov/articles/PMC6960891/
- RGB-D fiducial fusion:
  https://personalrobotics.cs.washington.edu/publications/jin2017rgbdtags.pdf
- GUM uncertainty framework:
  https://www.bipm.org/documents/20126/2071204/JCGM_100_2008_E.pdf
- Point-cloud task-specific uncertainty:
  https://www.mdpi.com/2673-8244/2/4/24

## Enforcement Direction

- Keep existing dogfood programme files as historical/research ledgers.
- Add new claims through PROM records before editing verdict nodes.
- Use PrismV2 tests as production adoption gates; use LakatoTree nodes as
  research-status gates.
- Use `docs/THREE_D_PROM_OPEN_SOURCE_TOOLING_20260624.md` as the tooling board
  for CLI-backed receipts. The default first stack is DVC, pytest/JUnit, and
  Open3D scripts.
