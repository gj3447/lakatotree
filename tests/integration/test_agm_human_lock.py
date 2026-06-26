"""A4-richer 실DB 영수증: belief contraction 의 auto-demote 가 human-lock(valid_until_rebutted)을 존중.

spine.reconcile_standing 정책을 실 Neo4j 로 검증 — CANONICAL ∧ valid_until_rebutted=True 노드는 belief
contraction 시 엔진이 former_canonical 로 강등하지만, 인간이 '반박-자동무효'를 끈(valid_until_rebutted
=False=human_locked) 노드는 belief 가 사라져도 CANONICAL 을 유지한다(인간경계 존중). prom C A4 의 blanket
SET 이 이 lock 을 무시하던 버그를 닫음.
"""
import pytest

from server.container import AppContainer

pytestmark = pytest.mark.integration


class _DummyMongo:
    def close(self):
        pass


def _seed(c, name):
    c.kg_tx([
        ("MERGE (t:LakatosTree {name:$n})", {"n": name}),
        # belief↔node(tag-일치) 2쌍: open(자동무효 허용) / locked(인간 lock).
        ("""MATCH (t:LakatosTree {name:$n})
            MERGE (bo:Belief {belief_id:'open'}) SET bo.kind='protective_belt', bo.credence=0.7
            MERGE (t)-[:HAS_BELIEF]->(bo)
            MERGE (bl:Belief {belief_id:'locked'}) SET bl.kind='protective_belt', bl.credence=0.7
            MERGE (t)-[:HAS_BELIEF]->(bl)
            MERGE (no:LakatosNode {tag:'open'}) SET no.verdict='CANONICAL', no.valid_until_rebutted=true
            MERGE (t)-[:HAS_NODE]->(no)
            MERGE (nl:LakatosNode {tag:'locked'}) SET nl.verdict='CANONICAL', nl.valid_until_rebutted=false
            MERGE (t)-[:HAS_NODE]->(nl)""", {"n": name}),
    ])


def _verdict(c, name, tag):
    return c.kg("MATCH (t:LakatosTree {name:$n})-[:HAS_NODE]->(e {tag:$tag}) RETURN e.verdict AS v",
                n=name, tag=tag)[0]["v"]


def test_belief_contraction_demotes_open_but_preserves_human_locked(monkeypatch, neo4j_driver):
    import server.app as app
    c = AppContainer(neo=neo4j_driver, mongo=_DummyMongo(), pg_kw={})
    name = "a4_humanlock"
    _seed(c, name)
    monkeypatch.setattr(app, "kg", c.kg)
    monkeypatch.setattr(app, "kg_tx", c.kg_tx)
    monkeypatch.setattr(app, "hist", lambda *a, **k: None)

    # open belief 제거 → 자동무효 허용 노드 'open' 은 엔진 강등
    app.agm_revise(app.AgmReviseIn(op="contraction", tree=name, target_id="open"))
    assert _verdict(c, name, "open") == "former_canonical"

    # locked belief 제거 → 인간 lock 노드 'locked' 는 CANONICAL 유지(자동강등 제외)
    app.agm_revise(app.AgmReviseIn(op="contraction", tree=name, target_id="locked"))
    assert _verdict(c, name, "locked") == "CANONICAL"
