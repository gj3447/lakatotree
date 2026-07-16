"""Compatibility wrapper for the packaged Euler demonstration.

The canonical implementation ships inside the ``lakatotree`` wheel at
``lakatos.demos.euler``. Existing imports and direct script execution remain
stable through this wrapper.

# KG: span_lakatotree_euler_dogfood
"""
import sys
from pathlib import Path

# Direct execution sets sys.path[0] to examples/, while the canonical package is
# a sibling at the repository root. Keep the historical source-tree entrypoint
# runnable even in a clean environment where lakatotree is not installed.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lakatos.demos.euler import (
    NODES,
    EulerNode,
    _EULER_CHI as _EULER_CHI,
    closed_orientable_euler_characteristic,
    main,
    run,
    scored_measured,
    scored_novel_measured,
)

__all__ = (
    "EulerNode",
    "NODES",
    "closed_orientable_euler_characteristic",
    "scored_measured",
    "scored_novel_measured",
    "run",
    "main",
)


if __name__ == "__main__":
    main()
