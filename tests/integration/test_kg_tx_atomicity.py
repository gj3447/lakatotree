"""실 Neo4j 로 kg_tx(ROB-1) all-or-nothing + 복구=멱등 재실행 characterize (D 통합티어).

mock 으로는 검증 불가했던 것을 실 DB 로: AppContainer.kg_tx 가 execute_write(managed write tx)라
중간 실패 시 전체 롤백(부분 KG 쓰기 없음)이고, MERGE 기반 write 는 재실행이 수렴한다(2026-06-16
복구 모델). prom C 의 atomic observation bind / A4 belief 영속+auto-demote / submit_test_result 의
판결+PROV 단일 tx 가 모두 이 보장에 의존한다.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from time import monotonic, sleep
from uuid import uuid4

import pytest

from server.container import AppContainer
from server.contexts.tree.cycle_budget import LOCKED_BUDGET_GUARD, budget_state
from server.contexts.tree.schemas import NodeIn
from server.contexts.tree.writer import (
    TreeAlreadyExists,
    TreeIdempotencyConflict,
    TreeNotEmpty,
    TreeKgWriter,
)
from lakatos.verdicts import FORCEFUL_SOURCES
from server.ports import GuardedKgOps, KgTxGuardFailed

pytestmark = pytest.mark.integration


class _DummyMongo:
    def close(self):
        pass


def _container(driver):
    # kg/kg_tx 만 실 Neo4j. PG(hist)=best-effort 라 이 테스트서 미사용 → pg_kw 비움(lazy, 미연결).
    return AppContainer(neo=driver, mongo=_DummyMongo(), pg_kw={})


def test_kg_tx_rolls_back_on_midtx_failure(neo4j_driver):
    """ROB-1: op1(노드 생성) 성공 + op2(잘못된 Cypher) 실패 → 전체 tx 롤백 → op1 미반영."""
    c = _container(neo4j_driver)
    with pytest.raises(Exception):
        c.kg_tx([
            ("CREATE (n:ITNode {tag:'rollback-probe'})", {}),
            ("THIS IS NOT VALID CYPHER", {}),
        ])
    rows = c.kg("MATCH (n:ITNode {tag:'rollback-probe'}) RETURN count(n) AS c")
    assert rows[0]['c'] == 0, 'mid-tx 실패 후 op1 이 남으면 롤백이 깨진 것 (ROB-1 위반)'


def test_kg_tx_commits_all_ops_on_success(neo4j_driver):
    """성공 경로: op-list 전부 한 tx 로 커밋(부분 아님)."""
    c = _container(neo4j_driver)
    c.kg_tx([
        ("CREATE (n:ITNode {tag:'commit-a'})", {}),
        ("CREATE (n:ITNode {tag:'commit-b'})", {}),
    ])
    rows = c.kg("MATCH (n:ITNode) WHERE n.tag IN ['commit-a','commit-b'] RETURN count(n) AS c")
    assert rows[0]['c'] == 2


def test_recovery_is_rerun_idempotent_merge(neo4j_driver):
    """복구=재실행: 같은 MERGE op 를 두 번(부분 실패 후 재실행 시뮬) 돌려도 노드 1개로 수렴(멱등)."""
    c = _container(neo4j_driver)
    op = ("MERGE (n:ITNode {tag:'rerun'}) SET n.v=$v", {'v': 1})
    c.kg_tx([op])
    c.kg_tx([op])
    rows = c.kg("MATCH (n:ITNode {tag:'rerun'}) RETURN count(n) AS c")
    assert rows[0]['c'] == 1, 'MERGE 재실행이 중복 생성하면 복구=재실행 모델이 깨진 것'


def test_create_only_concurrent_claim_has_one_winner_and_no_loser_clobber(neo4j_driver):
    """동명 create-only 두 호출은 unique key 아래 정확히 하나만 생성하고 loser 는 409 원인으로 끝난다."""
    c = _container(neo4j_driver)
    name = 'IT_CreateOnlyAtomic_20260728'
    c.kg("CREATE CONSTRAINT lkt_tree_name_unique IF NOT EXISTS "
         "FOR (t:LakatosTree) REQUIRE t.name IS UNIQUE")
    c.kg("MATCH (t:LakatosTree {name:$name}) DETACH DELETE t", name=name)
    barrier = Barrier(2)

    def attempt(title: str) -> tuple[str, str]:
        writer = TreeKgWriter(c.kg_tx)
        barrier.wait()
        try:
            writer.upsert_tree_meta(
                name=name,
                title=title,
                hard_core=f'{title} HC',
                frontier_rule=f'{title} FR',
                create_only=True,
            )
        except TreeAlreadyExists:
            return 'conflict', title
        return 'created', title

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(attempt, ('alpha', 'beta')))
        assert sorted(status for status, _ in outcomes) == ['conflict', 'created']
        winner = next(title for status, title in outcomes if status == 'created')
        rows = c.kg(
            "MATCH (t:LakatosTree {name:$name}) "
            "RETURN count(t) AS n, t.title AS title, t.hard_core AS hard_core, "
            "t._create_claim AS leaked_claim",
            name=name,
        )
        assert rows == [{
            'n': 1,
            'title': winner,
            'hard_core': f'{winner} HC',
            'leaked_claim': None,
        }]
    finally:
        c.kg("MATCH (t:LakatosTree {name:$name}) DETACH DELETE t", name=name)


def test_delete_retry_is_incarnation_aware_and_cascade_bound(neo4j_driver):
    c = _container(neo4j_driver)
    name = f"IT_DeleteABA_{uuid4().hex}"
    key = f"delete-{uuid4().hex}"
    c.kg(
        "CREATE CONSTRAINT lkt_tree_name_unique IF NOT EXISTS "
        "FOR (t:LakatosTree) REQUIRE t.name IS UNIQUE"
    )
    c.kg(
        "CREATE CONSTRAINT lkt_outbox_id_unique IF NOT EXISTS "
        "FOR (o:OutboxEntry) REQUIRE o.id IS UNIQUE"
    )
    c.kg(
        "CREATE (t:LakatosTree {name:$name, tree_incarnation_id:'old-inc'}) "
        "CREATE (t)-[:HAS_NODE]->(:LakatosNode {name:$node, tag:'n'})",
        name=name,
        node=f"{name}/n",
    )
    writer = TreeKgWriter(c.kg_tx)

    try:
        first = writer.delete_tree(name, cascade=True, idempotency_key=key)
        c.kg(
            "CREATE (:LakatosTree {name:$name, tree_incarnation_id:'new-inc'})",
            name=name,
        )
        replay = writer.delete_tree(name, cascade=True, idempotency_key=key)

        assert first["idempotent"] is False
        assert replay["idempotent"] is True
        assert replay["superseded"] is True
        assert replay["deleted_nodes"] == first["deleted_nodes"]
        assert c.kg(
            "MATCH (t:LakatosTree {name:$name}) "
            "RETURN t.tree_incarnation_id AS incarnation",
            name=name,
        ) == [{"incarnation": "new-inc"}]
        with pytest.raises(TreeIdempotencyConflict):
            writer.delete_tree(name, cascade=False, idempotency_key=key)
        assert c.kg(
            "MATCH (o:OutboxEntry {id:$event_id}) RETURN count(o) AS n",
            event_id=first["event_id"],
        ) == [{"n": 1}]
    finally:
        c.kg(
            "MATCH (o:OutboxEntry {tree:$name}) DETACH DELETE o",
            name=name,
        )
        c.kg(
            "MATCH (t:LakatosTree {name:$name}) "
            "OPTIONAL MATCH (t)-[:HAS_NODE]->(e) DETACH DELETE e, t",
            name=name,
        )


def test_janitor_empty_snapshot_cannot_delete_a_late_node(neo4j_driver):
    c = _container(neo4j_driver)
    name = f"IT_JanitorEmptyRace_{uuid4().hex}"
    c.kg(
        "CREATE (:LakatosTree {name:$name, tree_incarnation_id:'inc'})",
        name=name,
    )
    # Janitor observed the empty tree here. Another writer wins before delete.
    assert c.kg(
        "MATCH (t:LakatosTree {name:$name}) "
        "RETURN COUNT { MATCH (t)-[:HAS_NODE]->() } AS nodes",
        name=name,
    ) == [{"nodes": 0}]
    c.kg(
        "MATCH (t:LakatosTree {name:$name}) "
        "CREATE (t)-[:HAS_NODE]->(:LakatosNode {name:$node, tag:'late'})",
        name=name,
        node=f"{name}/late",
    )
    writer = TreeKgWriter(c.kg_tx)
    try:
        with pytest.raises(TreeNotEmpty):
            writer.delete_tree(
                name,
                cascade=True,
                idempotency_key=f"janitor-{uuid4().hex}",
                require_empty=True,
                require_incarnation_match=True,
                expected_incarnation_id="inc",
            )
        assert c.kg(
            "MATCH (t:LakatosTree {name:$name})-[:HAS_NODE]->(e {tag:'late'}) "
            "RETURN count(t) AS trees, count(e) AS nodes",
            name=name,
        ) == [{"trees": 1, "nodes": 1}]
        writer.delete_tree(
            name,
            cascade=True,
            idempotency_key=f"operator-{uuid4().hex}",
            require_empty=False,
        )
    finally:
        c.kg(
            "MATCH (o:OutboxEntry {tree:$name}) DETACH DELETE o",
            name=name,
        )
        c.kg(
            "MATCH (t:LakatosTree {name:$name}) "
            "OPTIONAL MATCH (t)-[:HAS_NODE]->(e) DETACH DELETE e, t",
            name=name,
        )


def test_generic_writers_preserve_legacy_authority_but_not_prediction_result_path(
    neo4j_driver,
):
    c = _container(neo4j_driver)
    name = f"IT_WriterLegacyAuthority_{uuid4().hex}"
    c.kg(
        "CREATE (t:LakatosTree {name:$name}) "
        "CREATE (legacy:LakatosNode:PrismExperiment {"
        "  name:$legacy_name, tag:'legacy', verdict:'CANONICAL', "
        "  node_state:'CANONICAL', metric_name:'old', metric_value:1.0, "
        "  metric_scope:'old', result_path:'legacy-old.json'}) "
        "CREATE (rel:LakatosNode:PrismExperiment {"
        "  name:$rel_name, tag:'rel', verdict:'rejected', "
        "  node_state:'JUDGED_SCRIPTED', metric_name:'old', metric_value:2.0, "
        "  metric_scope:'old', result_path:'rel-old.json'}) "
        "CREATE (pred:LakatosNode:PrismExperiment {"
        "  name:$pred_name, tag:'pred', verdict:'proof', "
        "  node_state:'PREDICTED', metric_name:'old', metric_value:3.0, "
        "  metric_scope:'old', result_path:'pred-old.json'}) "
        "CREATE (draft:LakatosNode:PrismExperiment {"
        "  name:$draft_name, tag:'draft', verdict:'proof', "
        "  node_state:'DRAFT', metric_name:'old', metric_value:4.0, "
        "  metric_scope:'old', result_path:'draft-old.json'}) "
        "CREATE (vr:VerdictReceipt:ITWriterReceipt {"
        "  receipt_sha:$verdict_receipt, tree:$name, tag:'rel'}) "
        "CREATE (pr:VerdictReceipt:ITWriterReceipt {"
        "  receipt_sha:$prediction_receipt, receipt_kind:'prediction', "
        "  tree:$name, tag:'pred'}) "
        "CREATE (t)-[:HAS_NODE]->(legacy) "
        "CREATE (t)-[:HAS_NODE]->(rel) "
        "CREATE (t)-[:HAS_NODE]->(pred) "
        "CREATE (t)-[:HAS_NODE]->(draft) "
        "CREATE (rel)-[:HAS_RECEIPT]->(vr) "
        "CREATE (pred)-[:HAS_RECEIPT]->(pr)",
        name=name,
        legacy_name=f"{name}/legacy",
        rel_name=f"{name}/rel",
        pred_name=f"{name}/pred",
        draft_name=f"{name}/draft",
        verdict_receipt=f"it-writer-verdict-{uuid4().hex}",
        prediction_receipt=f"it-writer-prediction-{uuid4().hex}",
    )
    writer = TreeKgWriter(c.kg_tx)
    incoming = dict(
        verdict="proof",
        metric_name="new",
        metric_value=99.0,
        metric_scope="new",
    )
    try:
        writer.add_node(
            name,
            NodeIn(tag="legacy", result_path="legacy-new.json", **incoming),
            [],
        )
        writer.upsert_nodes(
            name,
            [
                NodeIn(tag="rel", result_path="rel-new.json", **incoming),
                NodeIn(tag="pred", result_path="pred-new.json", **incoming),
                NodeIn(tag="draft", result_path="draft-new.json", **incoming),
            ],
        )
        rows = c.kg(
            "MATCH (:LakatosTree {name:$name})-[:HAS_NODE]->(e) "
            "RETURN e.tag AS tag, e.verdict AS verdict, "
            "e.node_state AS node_state, e.metric_name AS metric_name, "
            "e.metric_value AS metric_value, e.metric_scope AS metric_scope, "
            "e.result_path AS result_path ORDER BY tag",
            name=name,
        )
        assert rows == [
            {
                "tag": "draft",
                "verdict": "proof",
                "node_state": "DRAFT",
                "metric_name": "new",
                "metric_value": 99.0,
                "metric_scope": "new",
                "result_path": "draft-new.json",
            },
            {
                "tag": "legacy",
                "verdict": "CANONICAL",
                "node_state": "CANONICAL",
                "metric_name": "old",
                "metric_value": 1.0,
                "metric_scope": "old",
                "result_path": "legacy-new.json",
            },
            {
                "tag": "pred",
                "verdict": "proof",
                "node_state": "PREDICTED",
                "metric_name": "old",
                "metric_value": 3.0,
                "metric_scope": "old",
                "result_path": "pred-new.json",
            },
            {
                "tag": "rel",
                "verdict": "rejected",
                "node_state": "JUDGED_SCRIPTED",
                "metric_name": "old",
                "metric_value": 2.0,
                "metric_scope": "old",
                "result_path": "rel-old.json",
            },
        ]
    finally:
        c.kg(
            "MATCH (r:ITWriterReceipt {tree:$name}) DETACH DELETE r",
            name=name,
        )
        c.kg(
            "MATCH (t:LakatosTree {name:$name})-[:HAS_NODE]->(e) "
            "DETACH DELETE e",
            name=name,
        )
        c.kg("MATCH (t:LakatosTree {name:$name}) DETACH DELETE t", name=name)


def test_same_cycle_claim_race_revokes_delete_authority_before_admission(
    neo4j_driver,
):
    c = _container(neo4j_driver)
    name = f"IT_CycleClaim_{uuid4().hex}"
    claim = "cycle-" + "a" * 64
    barrier = Barrier(2)
    c.kg(
        "CREATE CONSTRAINT lkt_tree_name_unique IF NOT EXISTS "
        "FOR (t:LakatosTree) REQUIRE t.name IS UNIQUE"
    )
    c.kg(
        "CREATE CONSTRAINT lkt_node_name_unique IF NOT EXISTS "
        "FOR (e:LakatosNode) REQUIRE e.name IS UNIQUE"
    )
    c.kg("CREATE (:LakatosTree {name:$name})", name=name)

    def attempt():
        barrier.wait()
        return TreeKgWriter(c.kg_tx).add_cycle_node(
            name, NodeIn(tag="n"), [], claim
        )[1]

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            created = list(pool.map(lambda _index: attempt(), range(2)))
        assert sorted(created) == [False, True]
        assert c.kg(
            "MATCH (:LakatosTree {name:$name})-[:HAS_NODE]->(e {tag:'n'}) "
            "RETURN count(e) AS nodes, e._cycle_created_by AS owner, "
            "e._cycle_create_claim AS create_claim",
            name=name,
        ) == [{"nodes": 1, "owner": None, "create_claim": None}]
        assert TreeKgWriter(c.kg_tx).rollback_cycle_node(
            name, "n", claim
        ) == "not_owned"
        assert c.kg(
            "MATCH (:LakatosTree {name:$name})-[:HAS_NODE]->(e {tag:'n'}) "
            "RETURN count(e) AS nodes",
            name=name,
        ) == [{"nodes": 1}]
    finally:
        c.kg(
            "MATCH (t:LakatosTree {name:$name}) "
            "OPTIONAL MATCH (t)-[:HAS_NODE]->(e) DETACH DELETE e, t",
            name=name,
        )


def _budget_mutation_query(marker):
    return (
        f"/* {marker} */ MATCH (t:LakatosTree {{name:$tree}}) "
        + LOCKED_BUDGET_GUARD
        + """
          MATCH (t)-[:HAS_NODE]->(e {tag:$tag})
          WHERE e.verdict_source IS NULL
          SET e.verdict='proof', e.verdict_source=$source
          CREATE (r:VerdictReceipt:ITBudgetReceipt {
            receipt_sha:$receipt_sha, tree:$tree, tag:$tag,
            verdict:'proof', verdict_source:$source
          })
          CREATE (e)-[:HAS_RECEIPT]->(r)
          RETURN e.tag AS tag
        """
    )


@pytest.mark.parametrize(
    ("left_source", "right_source"),
    [
        pytest.param("scripted", "scripted", id="submit-submit"),
        pytest.param("admin", "admin", id="verdict-verdict"),
        pytest.param("scripted", "admin", id="submit-verdict"),
    ],
)
def test_lock_held_cycle_budget_allows_only_one_last_slot(
    neo4j_driver,
    left_source,
    right_source,
):
    """The shared production guard serializes every verdict-writer pairing.

    This executes the exact ``LOCKED_BUDGET_GUARD`` fragment used by
    ``submit_test_result`` and both ``set_verdict`` branches against real Neo4j.
    The small tail stands in only for each verb's post-guard receipt mutation;
    unit source-contract tests ensure all public writers embed this fragment.
    """
    c = _container(neo4j_driver)
    name = f"IT_BudgetLock_{uuid4().hex}"
    marker = f"IT_BUDGET_WAITER_{uuid4().hex}"
    left_query = _budget_mutation_query(f"IT_BUDGET_HOLDER_{uuid4().hex}")
    right_query = _budget_mutation_query(marker)
    c.kg(
        "CREATE (t:LakatosTree {name:$name, cycle_budget:1}) "
        "CREATE (t)-[:HAS_NODE]->(:LakatosNode {name:$left_name, tag:'left'}) "
        "CREATE (t)-[:HAS_NODE]->(:LakatosNode {name:$right_name, tag:'right'})",
        name=name,
        left_name=f"{name}/left",
        right_name=f"{name}/right",
    )

    left_params = dict(
        tree=name,
        tag="left",
        source=left_source,
        receipt_sha=f"it-budget-{name}-left",
        forceful=sorted(FORCEFUL_SOURCES),
    )
    right_params = dict(
        tree=name,
        tag="right",
        source=right_source,
        receipt_sha=f"it-budget-{name}-right",
        forceful=sorted(FORCEFUL_SOURCES),
    )
    started = Event()

    def contender():
        started.set()
        if right_source == "scripted":
            try:
                c.kg_tx(GuardedKgOps([(right_query, right_params)]))
            except KgTxGuardFailed:
                return "rejected"
            return "committed"
        return (
            "committed"
            if c.kg(
                right_query,
                **right_params,
            )
            else "rejected"
        )

    session_a = neo4j_driver.session()
    tx_a = session_a.begin_transaction()
    executor = ThreadPoolExecutor(max_workers=1)
    future = None
    holder_open = True
    try:
        assert tx_a.run(left_query, **left_params).data() == [{"tag": "left"}]
        future = executor.submit(contender)
        assert started.wait(timeout=2)

        deadline = monotonic() + 10
        waiter_observed = False
        while monotonic() < deadline:
            transactions = c.kg(
                "SHOW TRANSACTIONS YIELD currentQuery, status, "
                "currentQueryStatus, resourceInformation "
                "WHERE currentQuery CONTAINS $marker "
                "RETURN status, currentQueryStatus, resourceInformation",
                marker=marker,
            )
            waiter_observed = any(
                str(row.get("currentQueryStatus", "")).lower() == "waiting"
                or str(row.get("status", "")).lower() == "blocked"
                or bool(row.get("resourceInformation"))
                for row in transactions
            )
            if waiter_observed:
                break
            sleep(0.05)
        assert waiter_observed, "contender never reached the held tree NODE lock"

        tx_a.commit()
        holder_open = False
        assert future.result(timeout=10) == "rejected"
        assert budget_state(c.kg, name) == (1, 1)
        assert c.kg(
            "MATCH (:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:'right'}) "
            "RETURN e.verdict AS verdict, "
            "COUNT { MATCH (e)-[:HAS_RECEIPT]->(:ITBudgetReceipt) } AS receipts",
            tree=name,
        ) == [{"verdict": None, "receipts": 0}]
    finally:
        if holder_open:
            tx_a.rollback()
        if future is not None:
            future.result(timeout=10)
        executor.shutdown(wait=True, cancel_futures=True)
        session_a.close()
        c.kg(
            "MATCH (r:ITBudgetReceipt {tree:$name}) DETACH DELETE r",
            name=name,
        )
        c.kg(
            "MATCH (t:LakatosTree {name:$name})-[:HAS_NODE]->(e) "
            "DETACH DELETE e",
            name=name,
        )
        c.kg("MATCH (t:LakatosTree {name:$name}) DETACH DELETE t", name=name)


@pytest.mark.parametrize("bad_budget", ["1", -1, 1.5, True])
def test_lock_held_cycle_budget_rejects_corrupt_declarations_atomically(
    neo4j_driver,
    bad_budget,
):
    c = _container(neo4j_driver)
    name = f"IT_BudgetCorrupt_{uuid4().hex}"
    query = _budget_mutation_query(f"IT_BUDGET_CORRUPT_{uuid4().hex}")
    c.kg(
        "CREATE (t:LakatosTree {name:$name, cycle_budget:$budget}) "
        "CREATE (t)-[:HAS_NODE]->(:LakatosNode {name:$node, tag:'n'})",
        name=name,
        budget=bad_budget,
        node=f"{name}/n",
    )
    params = dict(
        tree=name,
        tag="n",
        source="scripted",
        receipt_sha=f"it-budget-{name}-n",
        forceful=sorted(FORCEFUL_SOURCES),
    )
    try:
        with pytest.raises(KgTxGuardFailed):
            c.kg_tx(GuardedKgOps([(query, params)]))
        assert c.kg(
            "MATCH (t:LakatosTree {name:$tree})-[:HAS_NODE]->(e {tag:'n'}) "
            "RETURN e.verdict AS verdict, "
            "t._cycle_budget_lock AS leaked_lock, "
            "COUNT { MATCH (e)-[:HAS_RECEIPT]->(:ITBudgetReceipt) } AS receipts",
            tree=name,
        ) == [{"verdict": None, "leaked_lock": None, "receipts": 0}]
    finally:
        c.kg(
            "MATCH (r:ITBudgetReceipt {tree:$name}) DETACH DELETE r",
            name=name,
        )
        c.kg(
            "MATCH (t:LakatosTree {name:$name})-[:HAS_NODE]->(e) "
            "DETACH DELETE e",
            name=name,
        )
        c.kg("MATCH (t:LakatosTree {name:$name}) DETACH DELETE t", name=name)
