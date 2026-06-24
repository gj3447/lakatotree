"""대시보드 생성기 회귀 가드 — 의존성0 인라인 SVG 가 통합 트리를 정직하게 렌더하는가."""
from examples.three_d_dashboard import run, _inline_svg, _depths
from examples.three_d_detection import UNIFIED_NODES
from lakatos.quant.metrics import tree_metrics
from examples.three_d_detection import UNIFIED_FRONTIER


def test_dashboard_builds_without_write():
    out = run(write=False)                       # 파일 안 쓰고 생성만
    assert out['html'].startswith('<!doctype html>')
    assert '<svg' in out['svg']
    assert out['metrics']['canonical'] == 'v8_pipeline'


def test_svg_renders_every_node_offline():
    m = tree_metrics(UNIFIED_NODES, UNIFIED_FRONTIER)
    svg = _inline_svg(UNIFIED_NODES, m)
    # 모든 노드가 박스로 렌더 (오프라인, graphviz/CDN 불필요)
    assert svg.count('<rect') == len(UNIFIED_NODES)
    # 줄기/가지 핵심 마디가 보임
    for tag in ('v8_pipeline', 'aruco_metric', 'sx3i_prob', 'lx3_prob'):
        assert tag in svg


def test_depths_root_is_zero_and_blooms_deeper():
    depth = _depths(UNIFIED_NODES)
    assert depth['prob_statement'] == 0                  # 단일 root
    assert depth['sx3i_prob'] > depth['v8_pipeline']     # SX3i 는 v8 아래에서 개화
    assert depth['lx3_prob'] > depth['aruco_metric']     # LX3 는 aruco_metric 아래에서 개화
