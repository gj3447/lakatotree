"""E Phase 3 — OS 셸 syscall 레지스트리 + 결정적 baseline 라우터 (docs/UI_AND_HUMAN_LOOP §1).

라카토트리=OS, 셸=LLM 챗봇: 사람 자연어 → OS 콜(트리 조작/조회/시각화). cli.py/mcp_server.py 가 이미
syscall *표면*이다 — 이 모듈은 그 표면을 **데이터(SYSCALLS 레지스트리)**로 명시하고, 결정적 keyword
라우터(baseline)를 둔다. robust NL→intent 번역은 LLM 셸(Phase 3.1, 제품)이 채운다 — 이건 그 LLM 이
호출할 syscall *스펙* + 미해소 시 정직한 fallback(환각으로 임의 호출 금지).
"""
from __future__ import annotations

# OS 콜 표면(데이터) — verb → (HTTP method, path 템플릿, 필수 args, 종류, 설명). LLM 셸/도움말/MCP 가 소비.
SYSCALLS: dict[str, dict] = {
    'metrics':     {'method': 'GET',  'path': '/api/tree/{tree}/metrics',     'args': ['tree'],        'kind': 'query', 'desc': '트리 지표(진보/Bayes/fertility/multiplicity)'},
    'directions':  {'method': 'GET',  'path': '/api/tree/{tree}/directions',  'args': ['tree'],        'kind': 'query', 'desc': '다음 가지 추천(VoI)'},
    'stack':       {'method': 'GET',  'path': '/api/tree/{tree}/stack',       'args': ['tree'],        'kind': 'query', 'desc': '3층 메타규칙 투표(Popper/Bayes/Laudan)'},
    'lifecycle':   {'method': 'GET',  'path': '/api/tree/{tree}/lifecycle',   'args': ['tree'],        'kind': 'query', 'desc': '프로그램 수명주기(harvest/diverge/extinct)'},
    'graph':       {'method': 'GET',  'path': '/api/graph/{tree}',            'args': ['tree'],        'kind': 'viz',   'desc': '시각 트리 그래프 데이터(node 색/패널 + edge + 안건)'},
    'view':        {'method': 'GET',  'path': '/api/graph/{tree}/view',       'args': ['tree'],        'kind': 'viz',   'desc': '브라우저 트리 뷰어(SVG 렌더)'},
    'standing':    {'method': 'GET',  'path': '/api/tree/{tree}/node/{tag}/standing',    'args': ['tree', 'tag'], 'kind': 'query', 'desc': '판결 정당성(Dung grounded extension)'},
    'eureka':      {'method': 'GET',  'path': '/api/tree/{tree}/node/{tag}/eureka',      'args': ['tree', 'tag'], 'kind': 'query', 'desc': '노드 eureka(felt/true/hallucinated)'},
    'certificate': {'method': 'GET',  'path': '/api/tree/{tree}/node/{tag}/certificate', 'args': ['tree', 'tag'], 'kind': 'query', 'desc': '5게이트 AND 인증서'},
}

# 결정적 keyword → syscall (LLM 셸 baseline). 더 구체적인 verb 를 먼저(view 가 graph 보다 우선).
_KEYWORDS: list[tuple[str, str]] = [
    ('viewer', 'view'), ('view', 'view'), ('뷰어', 'view'), ('보여', 'view'), ('render', 'view'), ('시각', 'view'),
    ('graph', 'graph'), ('그래프', 'graph'),
    ('direction', 'directions'), ('다음', 'directions'), ('next', 'directions'),
    ('lifecycle', 'lifecycle'), ('수명', 'lifecycle'),
    ('stack', 'stack'), ('vote', 'stack'),
    ('standing', 'standing'), ('정당', 'standing'),
    ('eureka', 'eureka'), ('유레카', 'eureka'),
    ('certificate', 'certificate'), ('인증', 'certificate'),
    ('metric', 'metrics'), ('지표', 'metrics'), ('progress', 'metrics'),
]


def _extract_after(tokens: list[str], markers) -> str:
    for m in markers:
        if m in tokens and tokens.index(m) + 1 < len(tokens):
            return tokens[tokens.index(m) + 1]
    return ''


def route_intent(text: str, *, tree: str = '', tag: str = '') -> dict:
    """자연어 의도 → syscall (결정적 baseline). 명시 tree/tag 우선, 없으면 텍스트서 추출 시도.

    미해소면 syscall=None + fallback(LLM 셸이 채울 자리) — 환각으로 임의 OS 콜을 만들지 않는다.
    반환: {syscall, call:{method,path}, args, kind, confidence, note}.
    """
    t = (text or '').lower()
    syscall = next((sc for kw, sc in _KEYWORDS if kw in t), None)
    if syscall is None:
        return {'syscall': None, 'confidence': 0.0,
                'note': 'NL→intent 미해소 — LLM 셸(Phase 3.1)이 채울 자리. verbs: '
                        + ','.join(sorted(SYSCALLS))}
    spec = SYSCALLS[syscall]
    toks = t.replace('/', ' ').split()
    args = {}
    if 'tree' in spec['args']:
        args['tree'] = tree or _extract_after(toks, ('tree', '트리', 'for', 'of')) or '?'
    if 'tag' in spec['args']:
        args['tag'] = tag or _extract_after(toks, ('node', '노드', 'tag')) or '?'
    path = spec['path']
    for k, v in args.items():
        path = path.replace('{' + k + '}', v)
    resolved = '?' not in path
    return {'syscall': syscall, 'call': {'method': spec['method'], 'path': path},
            'args': args, 'kind': spec['kind'], 'confidence': 0.6 if resolved else 0.3,
            'note': spec['desc'] + ' (결정적 baseline; robust NL 은 LLM 셸이 채움)'}
