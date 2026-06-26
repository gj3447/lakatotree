"""E Phase 3 — OS 셸 syscall 레지스트리 + baseline 라우터 검증 (docs/UI_AND_HUMAN_LOOP §1).

자연어→OS콜 매핑이 데이터로 명시되고(결정적 baseline), 미해소 시 환각으로 임의 호출하지 않고 fallback.
robust NL 은 LLM 셸(Phase 3.1)이 채움 — 이 테스트는 syscall 스펙 무결성 + baseline 라우팅을 핀.
"""
from server.shell import SYSCALLS, route_intent


def test_syscall_registry_specs_are_well_formed():
    for name, spec in SYSCALLS.items():
        assert spec['method'] in ('GET', 'POST')
        assert spec['path'].startswith('/api/')
        # path 의 모든 {placeholder} 가 args 에 선언돼 있어야(미선언 placeholder = 깨진 호출)
        import re
        placeholders = set(re.findall(r'\{(\w+)\}', spec['path']))
        assert placeholders == set(spec['args']), f'{name}: path 플레이스홀더 {placeholders} != args {spec["args"]}'
        assert spec['kind'] in ('query', 'viz', 'op') and spec['desc']


def test_route_intent_resolves_tree_syscall():
    r = route_intent('show metrics of tree euler', tree='euler')
    assert r['syscall'] == 'metrics' and r['call']['path'] == '/api/tree/euler/metrics'
    assert r['call']['method'] == 'GET' and r['confidence'] > 0.5


def test_route_intent_resolves_node_syscall_with_tag():
    r = route_intent('eureka for node v8', tree='bpc', tag='v8')
    assert r['syscall'] == 'eureka'
    assert r['call']['path'] == '/api/tree/bpc/node/v8/eureka'


def test_route_intent_viz_view_beats_graph_keyword():
    # 'view' 가 'graph' 보다 구체적 — '그래프 보여줘' 류는 브라우저 뷰어로
    r = route_intent('render the tree view', tree='T')
    assert r['syscall'] == 'view' and r['call']['path'] == '/api/graph/T/view'


def test_route_intent_unresolved_is_honest_fallback_not_hallucinated():
    r = route_intent('please make me a sandwich')
    assert r['syscall'] is None and r['confidence'] == 0.0
    assert 'LLM 셸' in r['note']                       # 환각 호출 대신 'LLM 이 채울 자리' 명시
