"""R11-SYNC — guarded direct sync·명명 레지스트리·notebook 스탬프 가드.

  guard_defect(음성)     : test_naming_registry_fail_loud_and_notebook_stamp
        — ①미등록 프리픽스/허브 = fail-loud(명명 드리프트 봉합 — 한계비용 0) ②미러 행이 손기록
          verdict_source 를 FORCEFUL 로 위조해도 engine_scored 는 파생(진위 KG 판정) + assurance_tier=
          'notebook' 스탬프(공유 KG 미러는 엔진 판결이 아니라 노트북 tier — 소급 CANONICAL 위장 봉쇄).
  guard_mechanism(양성)  : test_unbound_staging_prototype_is_retired_fail_closed
        — 실제 apply 흐름과 결합되지 않았던 staging/migrate prototype은 호출 즉시 거부한다.
          namespace·constraint·tree lock·protected-node·receipt를 묶는 do_apply만 mutation authority다.

# KG: LakatosTree_GitAbsorption_20260702 / followup-R11-sync
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    'sync_lakatos_programme_to_kg', ROOT / 'scripts' / 'sync_lakatos_programme_to_kg.py')
assert _spec and _spec.loader
sync = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = sync   # @dataclass 의 __module__ 해석용(로더 전 등록)
_spec.loader.exec_module(sync)


# ── guard_defect (음성): 명명 드리프트 + 미러 위조 봉쇄 ──────────────────────────────────────
def test_naming_registry_fail_loud_and_notebook_stamp():
    # (1) 등록된 허브는 정본 프리픽스로 resolve.
    assert sync.resolve_prefix(sync.DEFAULT_HUB_NAME) == sync.DEFAULT_NODE_PREFIX
    # (2) 미등록 허브 = fail-loud(조용한 임의 프리픽스 금지 — 드리프트 봉합).
    with pytest.raises(sync.NamingRegistryError):
        sync.resolve_prefix('LakatosTree_Unregistered_Hub_9999')
    with pytest.raises(sync.NamingRegistryError):
        sync.build_cypher(
            _minimal_programme(),
            hub_name=sync.DEFAULT_HUB_NAME,
            node_prefix='lk-wrong-',
            frontier_prefix=sync.DEFAULT_FRONTIER_PREFIX,
            rival_infix=sync.DEFAULT_RIVAL_INFIX,
            anchor=sync.DEFAULT_ANCHOR,
        )
    with pytest.raises(sync.NamingRegistryError):
        sync.build_cypher(
            _minimal_programme(),
            hub_name=sync.DEFAULT_HUB_NAME,
            node_prefix=sync.DEFAULT_NODE_PREFIX,
            frontier_prefix=sync.DEFAULT_FRONTIER_PREFIX,
            rival_infix=sync.DEFAULT_RIVAL_INFIX,
            anchor='UnregisteredAnchor',
        )
    with pytest.raises(sync.NamingRegistryError):
        sync.build_cypher(
            _minimal_programme(),
            hub_name=sync.DEFAULT_HUB_NAME,
            node_prefix=sync.DEFAULT_NODE_PREFIX,
            frontier_prefix=sync.DEFAULT_FRONTIER_PREFIX,
            rival_infix='',
            anchor=sync.DEFAULT_ANCHOR,
        )
    with pytest.raises(sync.NamingRegistryError):
        sync.build_cypher(
            _minimal_programme(),
            hub_name=sync.DEFAULT_HUB_NAME,
            node_prefix=sync.DEFAULT_NODE_PREFIX,
            frontier_prefix='q-wrong-',
            rival_infix=sync.DEFAULT_RIVAL_INFIX,
            anchor=sync.DEFAULT_ANCHOR,
        )
    # (3) 미러 행: 손기록 verdict_source 를 'scripted'(FORCEFUL)로 위조해도 assurance_tier='notebook'
    #     스탬프 — 공유 KG 미러는 엔진 판결이 아니라 노트북 tier(소급 CANONICAL 위장 봉쇄).
    row = sync._node_row({'tag': 'x', 'verdict': 'CANONICAL', 'verdict_source': 'scripted'},
                         name='lk-bpc-ac-x', branch='canonical_path')
    assert row['assurance_tier'] == 'notebook', '미러 행에 notebook tier 스탬프 부재'
    # engine_scored 는 파생이지만 — 미러는 실제 서버 원장(receipt)이 아니므로 content_sha 로만 무결성.
    assert 'content_sha' in row and row['assurance_tier'] in sync._MIRROR_TIER_ALLOWED


# ── guard_mechanism (양성): 무권한 staging prototype fail-closed ───────────────────────────
def test_unbound_staging_prototype_is_retired_fail_closed():
    rows = [dict(name='lk-bpc-ac-a', tag='a', content_sha='deadbeef00000000'),
            dict(name='lk-bpc-ac-b', tag='b', content_sha='cafebabe00000000')]
    batch = 'sync-20260703-test'
    with pytest.raises(RuntimeError, match='prototype is retired'):
        sync.build_staging_cypher(
            rows, import_batch=batch, hub_name=sync.DEFAULT_HUB_NAME
        )
    with pytest.raises(RuntimeError, match='prototype is retired'):
        sync.build_migrate_cypher(
            import_batch=batch, hub_name=sync.DEFAULT_HUB_NAME
        )
    with pytest.raises(RuntimeError, match='prototype is retired'):
        sync.migrate_is_gated_by_verify()

    source = (ROOT / 'scripts' / 'sync_lakatos_programme_to_kg.py').read_text(
        encoding='utf-8'
    )
    assert 'SET n = properties(s)' not in source
    assert 'def do_apply(' in source


def _minimal_programme():
    return sync.Programme(
        module_name='tests.synthetic',
        nodes=[{'tag': 'n1', 'verdict': 'canonical_stage'}],
        frontier=[{'name': 'q1', 'status': 'OPEN'}],
        rival_nodes=[],
        rival_frontier=[],
        canonical_tag=None,
    )


def _constraint_rows():
    return [
        {
            'name': name,
            'type': 'UNIQUENESS',
            'entityType': 'NODE',
            'labelsOrTypes': [label],
            'properties': list(properties),
        }
        for name, (label, properties) in sync._SYNC_REQUIRED_CONSTRAINTS.items()
    ]


def test_direct_sync_guard_rejects_receipt_bound_or_prediction_bound_targets():
    batch = sync.build_cypher(
        _minimal_programme(),
        hub_name=sync.DEFAULT_HUB_NAME,
        node_prefix=sync.DEFAULT_NODE_PREFIX,
        frontier_prefix=sync.DEFAULT_FRONTIER_PREFIX,
        rival_infix=sync.DEFAULT_RIVAL_INFIX,
        anchor=sync.DEFAULT_ANCHOR,
    )
    guard, params = batch.statements[0]
    assert 'n.current_receipt_sha IS NOT NULL' in guard
    assert 'n.pred_receipt_sha IS NOT NULL' in guard
    assert 'n.verdict_source IN $forceful' in guard
    assert "toUpper(coalesce(n.verdict,''))='CANONICAL'" in guard
    assert "toUpper(coalesce(n.node_state,''))='CANONICAL'" in guard
    assert 'MATCH (n)-[:HAS_RECEIPT]->()' in guard
    assert 'MATCH (n)-[:HAS_ARGUMENT]->()' in guard
    assert "history.op='critique'" in guard
    assert "toUpper(coalesce(q.status,''))='CLOSED'" in guard
    assert 'size(coalesce(q.closed_by,[])) > 0' in guard
    assert 'MATCH (other:LakatosTree)-[:HAS_NODE]->(n)' in guard
    assert 'MATCH (other:LakatosTree)-[:HAS_FRONTIER]->(q)' in guard
    assert "THEN 'scope_conflict'" in guard
    assert "THEN 'tier_conflict'" in guard
    assert '_sync_write_cas' in guard
    assert 'a._sync_write_cas' in guard
    assert "THEN 'receipt_conflict'" in guard
    assert params['target_names'] == [sync.DEFAULT_NODE_PREFIX + 'n1']
    assert 'admin' in params['forceful']
    assert params['props']['assurance_tier'] == 'notebook'
    assert params['anchor'] == sync.DEFAULT_ANCHOR
    assert "WHEN anchor_count<>1 THEN 'anchor_conflict'" in guard
    node_write = batch.statements[1][0]
    assert 'n.assurance_tier = row.assurance_tier' in node_write
    assert 'n.parent_tag = row.parent_tag' in node_write
    assert ' AS mutation_status' in node_write
    anchor_write = batch.statements[4][0]
    assert 'MATCH (a:SemanticAnchor' in anchor_write
    assert 'MERGE (a:SemanticAnchor' not in anchor_write
    assert 'RETURN count(a) AS anchor_link_count' in anchor_write


def test_apply_callback_retry_reads_commit_receipt_and_never_replays_mutations(
    monkeypatch,
):
    batch = sync.build_cypher(
        _minimal_programme(),
        hub_name=sync.DEFAULT_HUB_NAME,
        node_prefix=sync.DEFAULT_NODE_PREFIX,
        frontier_prefix=sync.DEFAULT_FRONTIER_PREFIX,
        rival_infix=sync.DEFAULT_RIVAL_INFIX,
        anchor=sync.DEFAULT_ANCHOR,
    )
    state = {'receipts': {}, 'mutation_runs': 0, 'callbacks': 0}

    class Result:
        def __init__(self, rows):
            self.rows = rows

        def data(self):
            return self.rows

    class Tx:
        def run(self, query, **params):
            if query.lstrip().startswith('MERGE (h:KnowledgeHub:LakatosTree'):
                committed = params.get('sync_event_id') in state['receipts']
                return Result([{
                    'guard_status': (
                        'already_committed' if committed else 'ok'
                    ),
                }])
            if 'CREATE (receipt:ProgrammeSyncReceipt' in query:
                state['receipts'][params['sync_event_id']] = {
                    'request_sha256': params['sync_request_sha256'],
                }
            else:
                state['mutation_runs'] += 1
            if ' AS mutation_status' in query:
                return Result([{'mutation_status': 'ok'}])
            if ' AS anchor_link_count' in query:
                return Result([{'anchor_link_count': 1}])
            return Result([{'ok': True}])

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def run(self, query):
            if query.startswith('CALL db.info()'):
                return Result([{'name': 'research'}])
            return Result(_constraint_rows())

        def execute_write(self, callback):
            state['callbacks'] += 1
            first = callback(Tx())
            assert first in {'applied', 'already_committed'}
            state['callbacks'] += 1
            second = callback(Tx())
            assert second == 'already_committed'
            return second

    class Driver:
        closed = False

        def session(self, *, database):
            assert database == 'research'
            return Session()

        def close(self):
            self.closed = True

    driver = Driver()
    monkeypatch.setattr(sync, '_driver', lambda: driver)
    monkeypatch.setenv('NEO4J_DATABASE', 'research')

    assert sync.do_apply(None, batch, sync.DEFAULT_HUB_NAME) == 0
    assert state['callbacks'] == 2
    assert state['mutation_runs'] == len(batch.statements) - 2
    assert sync.do_apply(None, batch, sync.DEFAULT_HUB_NAME) == 0
    assert state['callbacks'] == 4
    assert state['mutation_runs'] == len(batch.statements) - 2
    assert sync.do_apply(
        None,
        batch,
        sync.DEFAULT_HUB_NAME,
        operation_nonce='repair-after-verified-drift-1',
    ) == 0
    assert state['callbacks'] == 6
    assert state['mutation_runs'] == 2 * (len(batch.statements) - 2)
    assert driver.closed is True


def test_default_apply_identity_is_stable_across_cli_invocations():
    batch = sync.build_cypher(
        _minimal_programme(),
        hub_name=sync.DEFAULT_HUB_NAME,
        node_prefix=sync.DEFAULT_NODE_PREFIX,
        frontier_prefix=sync.DEFAULT_FRONTIER_PREFIX,
        rival_infix=sync.DEFAULT_RIVAL_INFIX,
        anchor=sync.DEFAULT_ANCHOR,
    )

    first = sync.bind_apply_operation(batch)
    second = sync.bind_apply_operation(batch)

    assert first.statements[0][1]['sync_event_id'] == second.statements[0][1]['sync_event_id']
    assert (
        first.statements[0][1]['sync_request_sha256']
        == second.statements[0][1]['sync_request_sha256']
    )


def test_explicit_nonce_is_scoped_by_hub_identity():
    batch = sync.build_cypher(
        _minimal_programme(),
        hub_name=sync.DEFAULT_HUB_NAME,
        node_prefix=sync.DEFAULT_NODE_PREFIX,
        frontier_prefix=sync.DEFAULT_FRONTIER_PREFIX,
        rival_infix=sync.DEFAULT_RIVAL_INFIX,
        anchor=sync.DEFAULT_ANCHOR,
    )
    other = sync.CypherBatch()
    for cypher, params in batch.statements:
        changed = dict(params)
        if 'hub_name' in changed:
            changed['hub_name'] = 'LakatosTree_OtherRegisteredHub'
        other.add(cypher, changed)

    first = sync.bind_apply_operation(batch, operation_nonce='shared-nonce')
    second = sync.bind_apply_operation(other, operation_nonce='shared-nonce')

    assert (
        first.statements[0][1]['sync_event_id']
        != second.statements[0][1]['sync_event_id']
    )


def test_build_rejects_duplicate_generated_live_names():
    programme = sync.Programme(
        module_name='tests.duplicate',
        nodes=[{'tag': 'rival-x'}],
        frontier=[{'name': 'same'}, {'name': 'same'}],
        rival_nodes=[{'tag': 'x'}],
        rival_frontier=[],
        canonical_tag=None,
    )
    with pytest.raises(sync.NamingRegistryError, match='duplicate live node'):
        sync.build_cypher(
            programme,
            hub_name=sync.DEFAULT_HUB_NAME,
            node_prefix=sync.DEFAULT_NODE_PREFIX,
            frontier_prefix=sync.DEFAULT_FRONTIER_PREFIX,
            rival_infix=sync.DEFAULT_RIVAL_INFIX,
            anchor=sync.DEFAULT_ANCHOR,
        )


def test_build_rejects_lineage_endpoint_outside_exact_target_set():
    programme = sync.Programme(
        module_name='tests.bad-lineage',
        nodes=[{'tag': 'child', 'parent': 'outside'}],
        frontier=[],
        rival_nodes=[],
        rival_frontier=[],
        canonical_tag=None,
    )
    with pytest.raises(sync.NamingRegistryError, match='lineage escapes'):
        sync.build_cypher(
            programme,
            hub_name=sync.DEFAULT_HUB_NAME,
            node_prefix=sync.DEFAULT_NODE_PREFIX,
            frontier_prefix=sync.DEFAULT_FRONTIER_PREFIX,
            rival_infix=sync.DEFAULT_RIVAL_INFIX,
            anchor=sync.DEFAULT_ANCHOR,
        )


def test_verify_content_rederives_kg_row_instead_of_trusting_stored_hash():
    source = sync._node_records(
        _minimal_programme(), sync.DEFAULT_NODE_PREFIX, sync.DEFAULT_RIVAL_INFIX
    )
    tampered = dict(source[0])
    tampered['comment'] = 'changed without updating content_sha'

    drift = sync.verify_content(source, {tampered['name']: tampered})

    assert drift[0]['reason'] == 'kg_content_sha_invalid'


def test_apply_rejects_unvalidated_constructed_batch_before_driver(monkeypatch):
    called = False

    def driver():
        nonlocal called
        called = True
        raise AssertionError('driver must not be opened')

    monkeypatch.setattr(sync, '_driver', driver)
    with pytest.raises(sync.NamingRegistryError):
        sync.do_apply(
            None,
            sync.CypherBatch([('RETURN 1', {'hub_name': sync.DEFAULT_HUB_NAME})]),
            sync.DEFAULT_HUB_NAME,
        )
    assert called is False


def test_apply_guard_conflict_aborts_before_any_later_statement(monkeypatch):
    batch = sync.build_cypher(
        _minimal_programme(),
        hub_name=sync.DEFAULT_HUB_NAME,
        node_prefix=sync.DEFAULT_NODE_PREFIX,
        frontier_prefix=sync.DEFAULT_FRONTIER_PREFIX,
        rival_infix=sync.DEFAULT_RIVAL_INFIX,
        anchor=sync.DEFAULT_ANCHOR,
    )
    seen = []

    class Result:
        def data(self):
            return [{'guard_status': 'receipt_conflict'}]

    class Tx:
        def run(self, query, **params):
            seen.append(query)
            return Result()

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def run(self, query):
            if query.startswith('CALL db.info()'):
                class DatabaseResult:
                    def data(self):
                        return [{'name': 'research'}]
                return DatabaseResult()
            class ConstraintResult:
                def data(self):
                    return _constraint_rows()
            return ConstraintResult()

        def execute_write(self, callback):
            return callback(Tx())

    class Driver:
        def session(self, *, database):
            assert database == 'research'
            return Session()

        def close(self):
            pass

    monkeypatch.setattr(sync, '_driver', Driver)
    monkeypatch.setenv('NEO4J_DATABASE', 'research')

    with pytest.raises(RuntimeError, match='receipt_conflict'):
        sync.do_apply(None, batch, sync.DEFAULT_HUB_NAME)
    assert len(seen) == 1


def test_apply_requires_and_pins_explicit_neo4j_database(monkeypatch):
    batch = sync.build_cypher(
        _minimal_programme(),
        hub_name=sync.DEFAULT_HUB_NAME,
        node_prefix=sync.DEFAULT_NODE_PREFIX,
        frontier_prefix=sync.DEFAULT_FRONTIER_PREFIX,
        rival_infix=sync.DEFAULT_RIVAL_INFIX,
        anchor=sync.DEFAULT_ANCHOR,
    )
    monkeypatch.delenv('NEO4J_DATABASE', raising=False)
    monkeypatch.setattr(
        sync, '_driver', lambda: (_ for _ in ()).throw(
            AssertionError('driver must not open without an explicit database')
        )
    )

    with pytest.raises(SystemExit, match='NEO4J_DATABASE'):
        sync.do_apply(None, batch, sync.DEFAULT_HUB_NAME)
