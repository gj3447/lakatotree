"""OpenQuestion 트리-스코프 수리 가드 (2026-07-23).

결함(실충돌 관측: judgment-ledger-repair-20260723): OpenQuestion 의 MERGE 키가 {name} 전역이라
두 트리가 같은 qname 을 쓰면 *하나의* 노드를 공유했다 — body last-write-wins 덮어씀, 한 트리의
close/n_visits 가 다른 트리 frontier 에 새어나감. 제약 lkt_open_question_name_unique(name 전역
UNIQUE)가 이 공유를 구조적으로 강제했다.

수리: MERGE 키를 (tree, name) 복합으로 — service.open_question / writer.add_node(M4) /
writer.upsert_questions / sync 스크립트 전부. 제약은 (tree, name) NODE KEY 로 교체(선행
마이그레이션: scripts/migrate_open_question_tree_scope_20260723.cypher).

읽기 경로(close_question, judgement_service closes, repository/metrics)는 원래 (t)-[:HAS_FRONTIER]->(q)
엣지로 트리-스코프돼 있어 무수정 — writer 키만 문제였다.
# KG: LakatosTree_LakatoTree_SelfDev / open-question-tree-scope-20260723
"""
from __future__ import annotations

from server.contexts.tree.diagnostics import diagnose_required_constraints
from server.contexts.tree.schemas import NodeIn, QuestionIn
from server.contexts.tree.service import TreeService
from server.contexts.tree.writer import TreeKgWriter


class _CaptureKg:
    """발행된 (cypher, params) 를 전부 잡는 최소 페이크 — monkeypatch dict 우회 아님."""

    def __init__(self) -> None:
        self.ops: list[tuple[str, dict]] = []

    def __call__(self, cypher, **params):
        self.ops.append((cypher, params))
        return [{"t": 1}]


class _CaptureKgTx:
    def __init__(self) -> None:
        self.txs: list[list[tuple[str, dict]]] = []

    def __call__(self, ops):
        self.txs.append(list(ops))
        return [[{"t": 1}] for _ in ops]


def _service(capture: _CaptureKg) -> TreeService:
    # frozen dataclass — 생성자로 주입(__new__ + setattr 불가)
    return TreeService(kg=capture, kg_tx=None, hist=lambda *a, **k: None, pg=None)


def test_open_question_merge_key_is_tree_scoped():
    """service.open_question 이 {name:$qn, tree:$tree} 복합키로 MERGE 한다(전역 {name} 아님)."""
    cap = _CaptureKg()
    _service(cap).open_question("TreeA", QuestionIn(qname="shared-q", body="body-A"))
    cypher, params = cap.ops[0]
    assert "MERGE (qn:OpenQuestion {name:$qn, tree:$tree})" in cypher
    assert "MERGE (qn:OpenQuestion {name:$qn})" not in cypher
    assert params["tree"] == "TreeA" and params["qn"] == "shared-q"


def test_two_trees_same_qname_emit_distinct_identities():
    """같은 qname 을 두 트리에 열어도 MERGE 키의 tree 슬롯이 달라 별개 노드로 간다."""
    cap = _CaptureKg()
    svc = _service(cap)
    svc.open_question("TreeA", QuestionIn(qname="shared-q", body="A 본문"))
    svc.open_question("TreeB", QuestionIn(qname="shared-q", body="B 본문 — 덮어씀 아님"))
    trees = [params["tree"] for cypher, params in cap.ops if "OpenQuestion" in cypher]
    bodies = [params["body"] for cypher, params in cap.ops if "OpenQuestion" in cypher]
    assert trees == ["TreeA", "TreeB"]           # 트리별 별개 MERGE 키
    assert bodies == ["A 본문", "B 본문 — 덮어씀 아님"]  # body 가 각자 키에 귀속


def test_writer_add_node_raises_question_tree_scoped():
    """M4 블록(add_node 의 open_question 실체화)도 (tree, qname) 복합키로 MERGE 한다."""
    cap = _CaptureKgTx()
    TreeKgWriter(cap).add_node(
        "T", NodeIn(tag="n", algorithm="problem", open_question="q-x"), [])
    cyphers = [c for tx in cap.txs for c, _ in tx]
    assert any("MERGE (q:OpenQuestion {name:$qname, tree:$tree})" in c for c in cyphers)


def test_writer_upsert_questions_tree_scoped():
    cap = _CaptureKgTx()
    TreeKgWriter(cap).upsert_questions("T", [QuestionIn(qname="q1", body="b")])
    cyphers = [c for tx in cap.txs for c, _ in tx]
    assert any("MERGE (qn:OpenQuestion {name:row.qname, tree:$tree})" in c for c in cyphers)


def test_legacy_global_unique_constraint_no_longer_satisfies():
    """종전 name-전역 UNIQUE 제약만 있는 KG 는 요구 제약 미충족으로 진단된다(마이그레이션 강제)."""
    report = diagnose_required_constraints([
        {"name": "lkt_open_question_name_unique", "labelsOrTypes": ["OpenQuestion"],
         "properties": ["name"]},
        {"name": "lkt_tree_name_unique", "labelsOrTypes": ["LakatosTree"], "properties": ["name"]},
        {"name": "lkt_node_name_unique", "labelsOrTypes": ["LakatosNode"], "properties": ["name"]},
        {"name": "lkt_research_event_id_unique", "labelsOrTypes": ["ResearchEvent"],
         "properties": ["id"]},
        {"name": "lkt_research_tradition_id_unique", "labelsOrTypes": ["ResearchTradition"],
         "properties": ["tradition_id"]},
    ])
    assert report["ok"] is False
    assert "OpenQuestion.(tree+name)" in report["missing"]
    assert any("IS NODE KEY" in c and "n.tree" in c for c in report["migration_cypher"])


def test_composite_node_key_constraint_satisfies():
    """(tree, name) NODE KEY 가 있으면 OpenQuestion 요구 제약 충족."""
    report = diagnose_required_constraints([
        {"name": "lkt_open_question_tree_name_key", "labelsOrTypes": ["OpenQuestion"],
         "properties": ["tree", "name"]},
    ])
    assert "OpenQuestion.(tree+name)" in report["present"]
    assert "OpenQuestion.(tree+name)" not in report["missing"]
