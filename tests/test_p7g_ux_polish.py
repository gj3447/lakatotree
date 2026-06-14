"""P7-G: UX 다듬기 — 대시보드 artifact 링크 + OpenAPI 메타 (TDD).

UX-005  대시보드 노드에 lineage/rebuild 추적 링크(result_path 있을 때) — 전엔 artifact 추적 불가
UX-004  FastAPI description 메타(/docs·/redoc 기본 활성). 응답모델 전면화는 P8(대량 기계작업) 정직 이월.
UX-006  주요 쿼리파라미터(stale/format/require_replay) docstring 문서화.
(UX-003 에러메시지 한/영 통일 = 주관적/저ROI → P8 이월, 본 클러스터 비포함을 정직표기.)
"""
import importlib
import os

from fastapi.testclient import TestClient


def load_app():
    os.environ.setdefault('NEO4J_URI', 'bolt://localhost:7687')
    os.environ.setdefault('NEO4J_USER', 'neo4j')
    os.environ.setdefault('NEO4J_PASSWORD', 'test')
    return importlib.import_module('server.app')


def _node(tag, verdict, parent=None, **kw):
    return dict(tag=tag, verdict=verdict, parent=parent, parents=[parent] if parent else [],
                parent_edges=[], algorithm='a', comment='c', limitation='l',
                metric_name=kw.get('mn'), metric_value=kw.get('mv'), metric_scope=kw.get('scope', 's'),
                pred_baseline=kw.get('pb'), pred_noise_band=kw.get('nb'), pred_direction=kw.get('pd'),
                novel_registered=kw.get('nr'), novel_confirmed=kw.get('nc'),
                questions=kw.get('qs', []), result_path=kw.get('rp'))


def _td(nodes):
    return dict(name='T', title='T tree', hard_core=[], frontier_rule='', doc='',
                coverage_backlog=[], coverage_statement='', nodes=nodes,
                frontier=[dict(name='q1', status='OPEN', body='b', closed_by=None,
                               expected_gain=0.5, cost=1.0, n_visits=1)])


def test_dashboard_shows_lineage_rebuild_links_for_result_path(monkeypatch):
    app = load_app()
    td = _td([
        _node('root', 'CANONICAL', mn='p95', mv=0.4, rp='out/r.json'),     # result_path 있음
        _node('leaf', 'progressive', parent='root', mn='p95', mv=0.3),     # 없음
    ])
    monkeypatch.setattr(app, 'trees', lambda: [{'name': 'T', 'title': 'T tree'}])
    monkeypatch.setattr(app, 'tree_data', lambda n: td)
    html = TestClient(app.app).get('/').text
    assert '/api/lineage/' in html and '/api/rebuild-verify/' in html
    assert 'out%2Fr.json' in html                                          # URL 인코딩됨


def test_dashboard_no_lineage_link_without_result_path(monkeypatch):
    app = load_app()
    td = _td([_node('only', 'CANONICAL', mn='p95', mv=0.4)])               # result_path 없음
    monkeypatch.setattr(app, 'trees', lambda: [{'name': 'T', 'title': 'T tree'}])
    monkeypatch.setattr(app, 'tree_data', lambda n: td)
    html = TestClient(app.app).get('/').text
    assert '/api/rebuild-verify/' not in html


def test_openapi_has_description_and_docs(monkeypatch):
    app = load_app()
    schema = app.app.openapi()
    assert schema['info'].get('description'), 'OpenAPI description 비어있음'
    assert 'PROV-O' in schema['info']['description'] or '계보' in schema['info']['description']


def test_query_params_documented():
    app = load_app()
    assert 'stale' in (app.get_lineage.__doc__ or '')
    assert 'require_replay' in (app.claim_standing.__doc__ or '')
    assert 'format' in (app.artifact_prov.__doc__ or '')
