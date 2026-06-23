"""P5 잔여 frontier 수정 — ROB-1 원자성 / ROB-5 streaming sha / 하네스 server cycle / UCB N.
"""
import hashlib
import importlib
import os


def load_app():
    os.environ.setdefault('NEO4J_URI', 'bolt://localhost:7687')
    os.environ.setdefault('NEO4J_USER', 'neo4j')
    os.environ.setdefault('NEO4J_PASSWORD', 'test')
    return importlib.import_module('server.app')


# ── P5-A: ROB-1 KG 원자성 ──

def test_kg_tx_runs_all_ops_in_one_unit(monkeypatch):
    app = load_app()
    seen = []

    class _Res:
        def data(self): return []

    class _Tx:
        def run(self, cypher, **kw): seen.append(cypher); return _Res()

    class _Sess:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute_write(self, fn): return fn(_Tx())   # 단일 unit-of-work

    monkeypatch.setattr(app.NEO, 'session', lambda: _Sess())
    app.kg_tx([('A', {'x': 1}), ('B', {'y': 2})])
    assert seen == ['A', 'B']                            # 같은 tx 에서 순서대로


def test_add_node_uses_single_atomic_tx(monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, 'tree_data', lambda n: {'nodes': [{'tag': 'root'}]})
    txs = []
    monkeypatch.setattr(app, 'kg_tx', lambda ops: txs.append(ops) or [[]])
    monkeypatch.setattr(app, 'hist', lambda *a, **k: None)
    app.add_node('T', app.NodeIn(tag='e1', parent='root'))
    assert len(txs) == 1                                 # 노드+엣지가 단일 tx (부분쓰기 분기 차단)
    ops = txs[0]
    assert len(ops) == 2 and 'MERGE (e:LakatosNode' in ops[0][0] and 'BRANCHED_FROM' in ops[1][0]


def test_hist_swallows_pg_down(monkeypatch):
    app = load_app()

    def boom():
        raise app.PgOperationalError('down')

    monkeypatch.setattr(app, 'pg', boom)
    app.hist('T', 'op', 'tag', {})                       # PG 다운이 mutation 을 깨지 않음(best-effort)


# ── P5-B: ROB-5 streaming sha ──

def test_file_sha_streams_matches_full_read(tmp_path):
    app = load_app()
    p = tmp_path / 'big.bin'
    data = b'lakatos-zahar' * 200000                     # ~2.6MB (>1MB 청크 여러 개)
    p.write_bytes(data)
    assert app._file_sha(str(p)) == hashlib.sha256(data).hexdigest()


# ── P5-C: 하네스 server cycle (no bash) ──

def test_run_cycle_orchestrates_in_order_no_bash(monkeypatch):
    app = load_app()
    calls = []
    monkeypatch.setattr(app, 'add_node', lambda n, x: (calls.append('node'), {'ok': True})[1])
    monkeypatch.setattr(app, 'register_prediction', lambda n, t, x: (calls.append('predict'), {'ok': True})[1])
    monkeypatch.setattr(app, 'submit_test_result',
                        lambda n, t, x: (calls.append('result'), {'verdict': 'progressive', 'novel': None, 'delta': -0.2})[1])
    monkeypatch.setattr(app, 'add_critique', lambda n, t, x: (calls.append('critique'), {'ok': True})[1])
    monkeypatch.setattr(app, 'standing', lambda n, t: {'stands': True})
    out = app.run_cycle('T', app.CycleIn(tag='e1', metric_name='p95', baseline=0.5, measured=0.4,
                                         critiques=[app.CritiqueIn(arg_id='d1', attacks='e1')]))
    assert calls == ['node', 'predict', 'result', 'critique']   # 한 콜=전 사이클, bash 없음
    assert out['verdict'] == 'progressive' and out['critiques'] == 1 and out['standing'] == {'stands': True}


# ── P5-D: UCB N = 질문 방문 합 ──

def test_directions_total_visits_is_sum_of_visits(monkeypatch):
    app = load_app()
    captured = {}

    def fake_rank(qmeta, total_visits, crisis=False):   # crisis: #9 crisis→explore 시그니처
        captured['tv'] = total_visits
        return qmeta

    monkeypatch.setattr(app, 'rank_questions', fake_rank)
    td = dict(name='T', title='T', hard_core=[], frontier_rule='', doc='',
              coverage_backlog=[], coverage_statement='',
              nodes=[{'tag': 'c', 'verdict': 'CANONICAL', 'metric_value': None}],
              frontier=[dict(name='q1', status='OPEN', body='', expected_gain=0.5, cost=1.0, n_visits=3),
                        dict(name='q2', status='OPEN', body='', expected_gain=0.2, cost=1.0, n_visits=5)])
    monkeypatch.setattr(app, 'tree_data', lambda n: td)
    monkeypatch.setattr(app, 'compute_metrics', lambda t: {'bayes': {'canonical_credence': 0.5}})
    app.directions('T')
    assert captured['tv'] == 8                           # 3+5 (노드수 proxy 아님)


# ── B5 OPS-COR-2/3: _path_sha 공통 헬퍼 (rebuild_verify·get_lineage 공유) ──

def test_path_sha_file_streams_and_dir_composite(tmp_path):
    app = load_app()
    f = tmp_path / 'f.bin'; f.write_bytes(b'zdf' * 100000)
    assert app._path_sha(str(f)) == app._file_sha(str(f))     # 파일=스트리밍 sha
    d = tmp_path / 'lot'; d.mkdir(); (d / 'a.zdf').write_bytes(b'x' * 10); (d / 'b.zdf').write_bytes(b'yy')
    s1 = app._path_sha(str(d)); assert s1 and not s1.startswith('__unreadable__')   # dir=이름+크기 합성
    assert app._path_sha(str(tmp_path / 'nope')) is None      # 부재=None
