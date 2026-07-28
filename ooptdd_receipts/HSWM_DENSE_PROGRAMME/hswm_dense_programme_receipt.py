"""Executable receipt for dense HSWM materialization and exact readback.

The adapter imports the production seeder and drives ``validate_manifest``,
``verify_remote``, and ``apply_manifest``.  Its transport seam represents an
already converged API snapshot using the production projection functions; it
does not reimplement manifest or comparison policy.

``LKT_HSWM_DENSE_INJECT=accept-tamper`` temporarily removes the production
exact-equality guard.  The same locked spec then retains the two convergence
events but loses the tamper-rejection event, and the guard is restored in
``finally``.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import sys


_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_SEEDER_PATH = _ROOT / "scripts" / "seed_hswm_larger_ai_programme.py"
_MANIFEST_PATH = _ROOT / "docs" / "data" / "hswm_larger_ai_programme_20260728.json"


def _load_seeder():
    spec = importlib.util.spec_from_file_location("_hswm_dense_receipt_seeder", _SEEDER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load HSWM seeder: {_SEEDER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _event(cid: str, name: str, **attrs) -> dict:
    return {
        "cid": cid,
        "correlation_id": cid,
        "cycle_id": cid,
        "service": "lakatos.hswm_dense_programme",
        "event": name,
        **attrs,
    }


class _ConvergedClient:
    """Read/write seam shaped exactly like the production ``ApiClient``.

    All semantic records are built through seeder projection functions.  POSTs
    are recorded as idempotent acknowledgements, while GETs expose the pinned
    converged snapshot used by both preflight and final readback.
    """

    def __init__(self, seeder, data: dict, *, tamper_node_comment: bool = False):
        self.seeder = seeder
        self.data = data
        self.tamper_node_comment = tamper_node_comment
        self.posts: list[tuple[str, dict]] = []
        self.encoded_name = seeder._url_segment(data["name"])

        tree = seeder._tree_payload(data)
        tree["name"] = data["name"]
        tree["nodes"] = copy.deepcopy(data["nodes"])
        tree["frontier"] = [
            {**copy.deepcopy(question), "name": question["qname"], "status": "OPEN"}
            for question in data["questions"]
        ]
        self.tree = tree
        self.foundation = {"requirements": copy.deepcopy(data["foundations"])}
        self.tradition = copy.deepcopy(data["tradition"])
        self.metrics = {
            "structure": {
                key: data["expected_topology"][key]
                for key in (
                    "nodes", "edges", "roots", "components",
                    "multi_parent_nodes", "typed_edge_ratio",
                )
            }
        }
        self.events_by_tag: dict[str, list[dict]] = {
            node["tag"]: [] for node in data["nodes"]
        }
        for observation in data["observations"]:
            event = seeder._expected_observation_event(data, observation)
            self.events_by_tag[observation["tag"]].append(event)

    def post(self, path: str, payload: dict) -> dict:
        self.posts.append((path, copy.deepcopy(payload)))
        return {"ok": True}

    def get(self, path: str, *, allow_not_found: bool = False) -> dict | None:
        del allow_not_found
        base = f"/api/tree/{self.encoded_name}"
        if path == base:
            result = copy.deepcopy(self.tree)
            if self.tamper_node_comment:
                result["nodes"][0]["comment"] += " [injected-readback-tamper]"
            return result
        if path == f"{base}/metrics":
            return copy.deepcopy(self.metrics)
        if path == f"{base}/foundation":
            return copy.deepcopy(self.foundation)
        if path == f"{base}/tradition":
            return copy.deepcopy(self.tradition)
        prefix = f"{base}/node/"
        if path.startswith(prefix) and path.endswith("/events"):
            encoded_tag = path[len(prefix):-len("/events")]
            for tag, events in self.events_by_tag.items():
                if self.seeder._url_segment(tag) == encoded_tag:
                    return {"events": copy.deepcopy(events)}
        raise AssertionError(f"unexpected HSWM receipt GET: {path}")


def verify(backend, cid):
    seeder = _load_seeder()
    data = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    validation = seeder.validate_manifest(data)
    assert validation["ok"] is True
    assert validation["scientific_progress_verdicts"] == 0
    assert validation["efficacy_claims"] == 0

    client = _ConvergedClient(seeder, data)
    readback = seeder.verify_remote(data, client)
    topology = data["expected_topology"]
    assert readback == {
        "manifest_owner": data["tree"]["manifest_owner"],
        "manifest_digest": data["tree"]["manifest_digest"],
        "nodes": topology["nodes"],
        "edges": topology["edges"],
        "roots": topology["roots"],
        "components": topology["components"],
        "multi_parent_nodes": topology["multi_parent_nodes"],
        "typed_edge_ratio": topology["typed_edge_ratio"],
        "questions": topology["questions"],
        "foundations": topology["foundations"],
        "observations": topology["observations"],
        "tradition_id": data["tradition"]["tradition_id"],
    }
    backend.ship([_event(
        cid,
        "hswm_dense_exact_readback_arrived",
        manifest_digest=readback["manifest_digest"],
        nodes=readback["nodes"],
        edges=readback["edges"],
        observations=readback["observations"],
    )])

    reapplied = seeder.apply_manifest(data, client)
    observation_posts = [
        path for path, _payload in client.posts if path.endswith("/observation")
    ]
    assert reapplied["ok"] is True
    assert reapplied["operations"] == 0
    assert reapplied["nodes_already_exact"] == len(data["nodes"])
    assert reapplied["questions_already_exact"] == len(data["questions"])
    assert reapplied["foundations_already_exact"] == len(data["foundations"])
    assert reapplied["tradition_already_exact"] is True
    assert reapplied["observations_already_exact"] == len(data["observations"])
    assert reapplied["readback"] == readback
    assert observation_posts == []
    backend.ship([_event(
        cid,
        "hswm_restart_converged_without_observation_rewrite",
        operations=reapplied["operations"],
        observations_already_exact=reapplied["observations_already_exact"],
        observation_posts=len(observation_posts),
    )])

    injected = os.getenv("LKT_HSWM_DENSE_INJECT") == "accept-tamper"
    original_require_equal = seeder._require_equal
    tamper_rejected = False
    tamper_reason = ""
    try:
        if injected:
            seeder._require_equal = lambda _label, _expected, _actual: None
        try:
            seeder.verify_remote(
                data,
                _ConvergedClient(seeder, data, tamper_node_comment=True),
            )
        except RuntimeError as exc:
            tamper_rejected = True
            tamper_reason = str(exc)
    finally:
        seeder._require_equal = original_require_equal

    if injected:
        assert not tamper_rejected, "fault injection did not remove the equality guard"
    else:
        assert tamper_rejected, "altered node comment passed exact remote readback"
        assert "remote node semantic set mismatch" in tamper_reason
        backend.ship([_event(
            cid,
            "hswm_tampered_readback_rejected",
            tamper="node.comment",
            guard="verify_remote exact semantic projection",
        )])
