"""Cross-layer read-model metric composition for Lakatos trees.

The tree read-model *projection* itself now lives on the production path
(`server.contexts.tree.repository.TreeKgRepository.load_tree_data`) — the single
source of truth (D1 audit 2026-06-26: there used to be a second, test-only copy
here that diverged, leaving A2 eigentrust + D1 provenance inert on every HTTP
path). This module keeps only the metric composition, which intentionally lives
*outside* the `.importlinter` layered contract so it can merge `quant` + `programme`.
"""

from __future__ import annotations

from lakatos.programme.flip import layer_flips
from lakatos.quant.metrics import tree_metrics


def compute_tree_metrics(td: dict) -> dict:
    """Compute report metrics from a projected tree read model.

    `layer_flips` is merged here (not inside `tree_metrics`) on purpose: it lives in
    `lakatos.programme` and `tree_metrics` lives in `lakatos.quant` — folding it in there
    would be an upward `quant → programme` import that `.importlinter` forbids. The server
    read-model is outside the layered contract, so it is the clean seam to compose them.
    """
    cfg = {
        "coverage_backlog": td.get("coverage_backlog") or [],
        "coverage_statement": td.get("coverage_statement") or "",
    }
    # A2: 관측이 있으면 eigentrust 글로벌 출처신뢰 맵을 구성해 credence 가중에 주입(없으면 레거시).
    observations = td.get("observations")
    if observations:
        from lakatos.trust import global_source_trust
        gst = global_source_trust(observations)
        if gst["trust"]:
            cfg["source_trust_map"] = gst["trust"]
            cfg["trust_coverage_mode"] = gst["coverage"]["mode"]
    m = tree_metrics(td["nodes"], td["frontier"], cfg=cfg)
    m["layer_flips"] = layer_flips(td["nodes"], td["frontier"])
    return m
