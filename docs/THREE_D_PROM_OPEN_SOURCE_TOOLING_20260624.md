# Three-D PROM Open Source Tooling

Date: 2026-06-24

This LakatoTree note records open-source CLI tools that can support the 3D PROM
discipline without changing the meaning of branch status nodes.

## Tool Board

| Tool | Status | Use In LakatoTree | Promotion Risk |
|---|---|---|---|
| DVC | adopt-first | bind scan fixtures, replay outputs, metric JSON, and data hashes | low |
| pytest + JUnit XML | adopted | bind production gate receipts from PrismV2 | low |
| coverage.py / pytest-cov | adopt-light | record decision-logic coverage for promoted branches | low |
| Open3D | adopt-script | generate geometry metrics and negative-control receipts | medium |
| MLflow | pilot | compare long experiment sweeps and artifacts | medium |
| Papis | optional | maintain literature metadata and BibTeX exports | low |
| CloudCompare CLI | optional-heavy | independent cloud/mesh comparison outside CI | medium |
| PCL tools | optional-heavy | second-stack registration/filtering comparison | medium |
| evo | reference-only | trajectory error metrics if pose trajectories become receipts | low |

## Promotion Rule

A tool can help a branch move status only if it leaves replayable receipts:

- exact command
- input paths or data hashes
- output paths
- scalar metrics
- negative-control result
- code/test path that consumed the result

Screenshots, GUI-only steps, and unversioned local notebooks are diagnostic
evidence only. They do not promote a branch.

## Recommended Path

1. Use DVC for scan fixtures and generated PROM artifacts.
2. Use PrismV2 pytest markers and JUnit XML as the production gate receipt.
3. Use Open3D scripts for point-cloud distance, registration smoke checks, and
   wrong-axis/free-ICP negative controls.
4. Add MLflow only for large sweeps where comparing runs in a UI saves real
   operator time.

## Branch Mapping

| Branch | First Useful Tooling |
|---|---|
| BPC current production | pytest/JUnit, coverage.py, DVC for representative scan receipts |
| LX3 migration | Open3D distance metrics, DVC fixtures, pytest replay |
| SX3i research | Open3D scripts, DVC, later MLflow if parameter sweeps grow |
| OMD | no tool until a source/interface/test contract exists |

## Source Anchors

- DVC: https://doc.dvc.org/user-guide
- MLflow CLI: https://mlflow.org/docs/latest/cli.html
- Papis: https://papis.readthedocs.io/
- Open3D point clouds:
  https://www.open3d.org/docs/release/tutorial/geometry/pointcloud.html
- Open3D registration:
  https://www.open3d.org/docs/release/tutorial/pipelines/global_registration.html
- CloudCompare CLI:
  https://www.cloudcompare.org/doc/wiki/index.php/Command_line_mode
- PCL: https://pointcloudlibrary.github.io/
- evo: https://github.com/MichaelGrupp/evo
- pytest markers: https://docs.pytest.org/en/stable/how-to/mark.html
- coverage.py: https://coverage.readthedocs.io/
