# Three-D Inspection Background Knowledge

Date: 2026-06-24

This is the LakatoTree-side background pack for the active BPC/LX3/SX3i
inspection branches. It anchors research-branch decisions to external
metrology and registration literature.

## Anchored Claims

### BPC

Status: adopted in PrismV2 as `bpc.current-production`.

External support:

- Degenerate/planar point-cloud registration literature supports the observed
  failure of unconstrained global ICP on weakly 3D, repetitive, low-curvature
  surfaces.
- Therefore the production branch should stay with frozen per-view transforms,
  feature-level measurement, and robust median/fusion rather than free GICP.

Primary references:

- https://arxiv.org/html/2408.11809v2
- https://www.ipb.uni-bonn.de/pdfs/foerstner17efficient.pdf
- https://www.mdpi.com/2079-9292/13/14/2696

### LX3

Status: research branch progressed; PrismV2 production port pending.

External support:

- Fiducial-marker studies support using multiple observations and error
  propagation checks; they do not justify treating marker pose repeatability as
  final part accuracy.
- The current known-axis ArUco result should be recorded as precision progress,
  with accuracy still open until independent CAD feature checks close it.

Primary references:

- https://pmc.ncbi.nlm.nih.gov/articles/PMC6960891/
- https://www.semanticscholar.org/paper/Determining-and-Improving-the-Localization-Accuracy-Kallwies-Forkel/190a6317ebfbe2c6f29b7684f68a5b5a2104c02c
- https://personalrobotics.cs.washington.edu/publications/jin2017rgbdtags.pdf

### SX3i

Status: research branch only.

External support:

- RGBD/fiducial fusion and incremental registration literature support the
  current branch ordering: first prove marker/feature assembly, then feature
  coincidence, then raw ICP refinement.

Primary references:

- https://personalrobotics.cs.washington.edu/publications/jin2017rgbdtags.pdf
- https://arxiv.org/html/2407.05021v1

### GD&T / Metrology Decision Layer

Status: required before production conformance claims.

External support:

- GUM and point-cloud task-specific uncertainty literature support separating
  precision, accuracy, measurement uncertainty, and conformity decision.

Primary references:

- https://www.bipm.org/documents/20126/2071204/JCGM_100_2008_E.pdf
- https://www.bipm.org/en/committees/jc/jcgm/publications
- https://www.mdpi.com/2673-8244/2/4/24

## How LakatoTree Should Use This

- A branch may be `progressive` on repeatability, but must not close an accuracy
  question without independent feature or artifact evidence.
- A branch may be `adopted` in PrismV2 only when the code path, test path, and
  measurement uncertainty story are all explicit.
- Negative controls matter: wrong-axis, free-ICP, missing-fiducial, and
  low-overlap controls should remain in the tree as protected counterexamples.

## Next Research Moves

1. LX3: run known-axis pose against independent bush/CAD nominal checks.
2. SX3i: close C2 assembly before C3 feature-coincidence.
3. BPC: add uncertainty fields to feature reports, especially washer/cup/outer
   hole measurements.
4. PrismV2: keep the GICP fallback trace as a production safety event.
