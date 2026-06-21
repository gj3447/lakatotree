"""E Phase 1 — 시각 트리 GUI 데이터 척추(graph_view.tree_graph) 계약 검증.

GUI 가 렌더할 구조: node(색/klass 본류·퇴행·생존/클릭 패널) + edge(BRANCHED_FROM) + frontier + agenda
(human-in-the-loop 안건). 프론트엔드 없이도 이 데이터가 옳게 나오는지 핀(docs/UI_AND_HUMAN_LOOP §2-4).
"""
from server.dashboard_view import VERDICT_COLORS
from server.graph_view import tree_dot, tree_dot_view, tree_graph


def _td():
    return {
        'name': 'T',
        'nodes': [
            {'tag': 'root', 'verdict': 'canonical_stage', 'parent_edges': []},
            {'tag': 'p1', 'verdict': 'progressive', 'novel_registered': True, 'novel_confirmed': True,
             'pred_metric': 'p95', 'pred_baseline': 1.0, 'metric_value': 0.5, 'source': 'peer://a',
             'parent_edges': [{'tag': 'root', 'relation_kind': 'knowledge_inheritance', 'inferred': False}]},
            {'tag': 'top', 'verdict': 'CANONICAL',
             'parent_edges': [{'tag': 'p1', 'relation_kind': 'x', 'inferred': False}]},
            {'tag': 'bad', 'verdict': 'rejected', 'parent_edges': [{'tag': 'p1', 'inferred': False}]},
        ],
        'frontier': [{'name': 'q1', 'status': 'OPEN', 'body': 'open q'},
                     {'name': 'q2', 'status': 'CLOSED', 'body': ''}],
    }


def _m():
    return {
        'canonical_path': ['root', 'p1', 'top'],
        'rejected': ['bad'],
        'laudan': {'abandon_candidates': [{'leaf': 'bad', 'reason': '연속 비진보 3'}]},
        'bayes': {'low_credence_branches': [{'leaf': 'bad', 'credence': 0.05}]},
    }


def test_tree_graph_klass_colors_and_canonical_path():
    g = tree_graph(_td(), _m())
    by = {n['tag']: n for n in g['nodes']}
    assert by['top']['klass'] == 'canonical' and by['top']['on_canonical_path'] is True
    assert by['p1']['klass'] == 'canonical'                       # 정본 경로 위
    assert by['bad']['klass'] == 'regression'                     # 퇴행/기각 = 잘린 물길
    assert by['bad']['color'] == VERDICT_COLORS['rejected']       # verdict 색 매핑
    assert set(g['legend']) == {'canonical', 'regression', 'live'}


def test_tree_graph_node_click_panel():
    by = {n['tag']: n for n in tree_graph(_td(), _m())['nodes']}
    panel = by['p1']['panel']
    assert panel['prediction']['novel_registered'] is True and panel['prediction']['metric'] == 'p95'
    assert panel['measurement']['value'] == 0.5
    assert panel['source'] == 'peer://a'
    assert panel['links']['standing'].endswith('/p1/standing')   # 노드 클릭→상세 엔드포인트 링크


def test_tree_graph_edges_frontier_agenda():
    g = tree_graph(_td(), _m())
    pairs = {(e['child'], e['parent']) for e in g['edges']}
    assert ('p1', 'root') in pairs and ('top', 'p1') in pairs     # BRANCHED_FROM 엣지
    assert g['counts']['open_frontier'] == 1
    # human-in-the-loop 안건: 퇴행 가지가 검토 안건으로 surface
    kinds = {(a['kind'], a['leaf']) for a in g['agenda']}
    assert ('abandon_candidate', 'bad') in kinds and ('low_credence', 'bad') in kinds


def test_graph_route_handler_wires_tree_data_and_metrics(monkeypatch):
    """라우트 배선(/api/graph/{name}): tree_data → compute_metrics → tree_graph (HTTP/auth 우회 직접호출)."""
    import server.app as app
    monkeypatch.setattr(app, 'tree_data', lambda name: _td())
    monkeypatch.setattr(app, 'compute_metrics', lambda td: _m())
    g = app.tree_graph_view('T')
    assert g['name'] == 'T' and g['counts']['nodes'] == 4
    assert any(n['klass'] == 'canonical' for n in g['nodes'])


# ── E Phase 2: 시각 렌더(DOT + 브라우저 뷰어) ────────────────────────────────
def test_tree_dot_is_valid_graphviz_with_colors_and_edges():
    dot = tree_dot(tree_graph(_td(), _m()))
    assert dot.startswith('digraph lakatotree {') and dot.rstrip().endswith('}')
    assert '"top"' in dot and 'doubleoctagon' in dot           # 정본 경로 노드 모양
    assert '"p1" -> "top"' in dot or '"p1"->"top"' in dot.replace(' ', '')  # parent->child 엣지
    assert VERDICT_COLORS['rejected'] in dot                   # verdict 색 매핑
    assert '#dafbe1' in dot and '#ffebe9' in dot               # klass fill(본류/퇴행)


def test_tree_dot_view_embeds_dot_and_renderer():
    dot = tree_dot(tree_graph(_td(), _m()))
    view = tree_dot_view('T', dot)
    assert '<html' in view and 'LakatoTree: T' in view
    assert 'viz-standalone.js' in view and 'renderSVGElement' in view   # 빌드 0 브라우저 렌더
    assert 'digraph lakatotree' in view                                  # DOT 임베드
