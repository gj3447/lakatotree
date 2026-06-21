"""longinus (prom-honesty): accepted_grounding_refs 의 kg: ref *실시간 KG 존재* 자동 가드 (gated).

적대 재검증 low: kg: ref 진실성이 사람 동기(allowlist 수기 유지)에만 의존했다 — allowlist 가 stale 돼도
hermetic 가드는 못 잡는다. 이 gated 테스트가 라이브 Neo4j 에 각 kg: 노드가 실재하는지 자동 확인하여
그 동기-의존을 닫는다(stale 되면 RED). CI(hermetic)에선 skip(KG 없음); 실행:
    LAKATOS_KG_LIVE=1 NEO4J_URI=... NEO4J_USER=... NEO4J_PASSWORD=...  python -m pytest tests/test_grounding_refs_live.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_LIVE = (os.getenv("LAKATOS_KG_LIVE") == "1"
         and bool(os.getenv("NEO4J_URI")) and bool(os.getenv("NEO4J_PASSWORD")))


@pytest.mark.skipif(not _LIVE, reason="KG live off — LAKATOS_KG_LIVE=1 + NEO4J_URI/PASSWORD 필요 (allowlist kg: 실재 가드)")
def test_accepted_kg_refs_exist_in_live_kg():
    """allowlist 의 모든 kg: ref 가 라이브 KG 에 실재해야 — 없으면(=stale allowlist) RED."""
    import neo4j

    manifest = json.loads((ROOT / "docs" / "longinus_bindings.json").read_text(encoding="utf-8"))
    kg_nodes = [r.split("kg:", 1)[1] for r in manifest.get("accepted_grounding_refs", ())
                if r.startswith("kg:")]
    assert kg_nodes, "검사할 kg: ref 가 없음 — allowlist 구성 확인"

    driver = neo4j.GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.getenv("NEO4J_USER", "neo4j"), os.environ["NEO4J_PASSWORD"]))
    try:
        with driver.session() as session:
            missing = [name for name in kg_nodes
                       if (session.run("MATCH (n {name:$n}) RETURN count(n) AS c", n=name).single() or {"c": 0})["c"] == 0]
    finally:
        driver.close()

    assert not missing, f"allowlist 의 kg: ref 가 라이브 KG 에 부재(stale) — 동기 필요: {missing}"
