#!/usr/bin/env python3
"""Sync Longinus code bindings (in-repo SoT) → KG ReferenceSite mirror.

Root cause of the 2026-06-18 drift incident (KG bindings silently stale after the
verdict/quant/programme/io subpackage refactor): the KG ``ReferenceSite:Longinus``
mirror was **hand-pierced once and never regenerated**, so when symbols moved the KG
rotted while nobody noticed. Hand-maintained mirrors drift. The fix is structural:

    ``docs/longinus_bindings.json`` is the single source of truth (symbol-resolved,
    def-line sha, drift-guarded every commit by ``tests/test_longinus_bindings.py``).
    The KG ReferenceSite set is a **GENERATED mirror of it** — produced by this script,
    never edited by hand — so it cannot drift independently of the tested SoT.

Modes:
    --dry-run   (default) print what would change, touch nothing
    --verify    connect (NEO4J_* env), assert KG mirror == manifest; exit 1 on drift
    --apply     UPSERT ReferenceSite:Longinus from the manifest (regenerate the mirror)

Env (only for --verify / --apply):
    NEO4J_URI       (e.g. bolt://localhost:55013)   [also accepts NEO4J_URL]
    NEO4J_USERNAME  (e.g. neo4j)                       [also accepts NEO4J_USER]
    NEO4J_PASSWORD

# KG: lesson-agent-felt-eureka-drift-longinus-20260618, LonginusDriftAudit_lakatotree
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "longinus_bindings.json"

UPSERT = """
UNWIND $sites AS s
MERGE (rs:ReferenceSite:Longinus {sourceId: s.sourceId})
  ON CREATE SET rs.name = s.sourceId, rs.created_at = datetime()
SET rs.repo = $repo, rs.sourcePath = s.path, rs.sha256 = s.sha, rs.layer = s.layer,
    rs.frege_sinn = s.sinn, rs.binding_state = 'PIERCED', rs.anchor_strategy = 'symbol_grep',
    rs.drift_count = 0, rs.commit = $commit, rs.last_validated = datetime(),
    rs.generated_from = 'docs/longinus_bindings.json', rs.kg_mirror_of_sot = true
RETURN count(rs) AS upserted
"""


def _sites() -> list[dict]:
    d = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return [
        {"sourceId": b["sourceId"], "path": f"{b['file']}:{b.get('line_hint', '')}",
         "sha": b["sha256"], "layer": b.get("layer", ""), "sinn": b.get("frege_sinn", "")}
        for b in d["bindings"]
    ]


def _commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                                       text=True).strip()
    except Exception:  # noqa: BLE001 — git absent is non-fatal
        return "unknown"


def _driver():
    uri = os.environ.get("NEO4J_URI") or os.environ.get("NEO4J_URL")
    user = os.environ.get("NEO4J_USERNAME") or os.environ.get("NEO4J_USER")
    pw = os.environ.get("NEO4J_PASSWORD")
    missing = [k for k, v in (("NEO4J_URI", uri), ("NEO4J_USERNAME", user),
                              ("NEO4J_PASSWORD", pw)) if not v]
    if missing:
        sys.exit(f"ERROR: missing env: {', '.join(missing)}")
    try:
        from neo4j import GraphDatabase  # type: ignore
    except ImportError:
        sys.exit("ERROR: neo4j driver not installed (pip install neo4j)")
    return GraphDatabase.driver(uri, auth=(user, pw))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--apply", action="store_true", help="regenerate KG mirror from manifest")
    g.add_argument("--verify", action="store_true", help="assert KG mirror == manifest; exit 1 on drift")
    ap.add_argument("--commit", default=None, help="override git HEAD short hash")
    args = ap.parse_args()

    sites = _sites()
    commit = args.commit or _commit()
    repo = str(ROOT)

    if not (args.apply or args.verify):  # dry-run
        print(f"[dry-run] {len(sites)} manifest bindings → KG ReferenceSite:Longinus "
              f"(commit {commit}). --apply to regenerate, --verify to check drift.")
        for s in sites[:3]:
            print(f"  {s['sourceId']:32} {s['path']:34} {s['sha']}")
        print("  ...")
        return 0

    drv = _driver()
    try:
        if args.verify:
            by_id = {s["sourceId"]: s for s in sites}
            with drv.session() as ses:
                rows = ses.run(
                    "MATCH (rs:ReferenceSite:Longinus) WHERE rs.repo=$repo "
                    "RETURN rs.sourceId AS id, rs.sha256 AS sha, rs.sourcePath AS path",
                    repo=repo).data()
            kg = {r["id"]: r for r in rows}
            missing = [i for i in by_id if i not in kg]
            shadrift = [i for i in by_id if i in kg and kg[i]["sha"] != by_id[i]["sha"]]
            orphan = [i for i in kg if i not in by_id]
            for i in missing:
                print(f"MISSING_IN_KG  {i}")
            for i in shadrift:
                print(f"SHA_DRIFT      {i}  kg={kg[i]['sha']} manifest={by_id[i]['sha']}")
            for i in orphan:
                print(f"KG_ORPHAN      {i}  (in KG, not in manifest — stale binding?)")
            bad = len(missing) + len(shadrift)
            print(f"=== verify: {len(by_id)} manifest, {len(kg)} kg-mirror, "
                  f"{bad} drift, {len(orphan)} orphan ===")
            return 1 if bad else 0

        with drv.session() as ses:
            n = ses.run(UPSERT, sites=sites, repo=repo, commit=commit).single()["upserted"]
        print(f"[apply] regenerated {n} ReferenceSite:Longinus from manifest @ {commit}")
        return 0
    finally:
        drv.close()


if __name__ == "__main__":
    raise SystemExit(main())
