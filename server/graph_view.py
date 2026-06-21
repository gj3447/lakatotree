"""E Phase 1 — 시각 트리 GUI 의 *데이터 척추* (docs/UI_AND_HUMAN_LOOP.md §2-4 'vision' 의 첫 물질화).

UI 비전은 "트리를 항해하는 GUI": 브랜치 줌, 노드 클릭→prediction/measurement/verdict/prov/pnr 패널,
프론티어·퇴행 가지·정본 경로를 색으로 구분, shift_candidate/standing 철회 같은 *안건* surface.

이 모듈은 그 GUI 가 렌더할 **구조화 그래프 JSON** 을 만든다(프론트엔드는 Phase 2, 별도). 즉 React/SVG
없이도 GUI 가 필요로 하는 데이터 — node(색/klass/패널) + edge(BRANCHED_FROM) + frontier + agenda — 를
read-model 로 제공한다. load_tree_data + compute_metrics 산출을 소비(새 KG 쿼리 0).
"""

from __future__ import annotations

import html

from server.dashboard_view import VERDICT_COLORS

# 정본 경로=본류 / 퇴행·기각=잘린 물길 / 그 외=살아있는 가지 (색 구분 — '왜 나무인가')
KLASS_LEGEND = {
    'canonical': '본류 (정본 경로)',
    'regression': '잘린 물길 (퇴행/폐기후보/저신뢰/기각)',
    'live': '살아있는 가지',
}


def _node_panel(r: dict) -> dict:
    """노드 클릭 패널 — prediction/measurement/verdict/eureka/source 요약(prov/pnr 는 전용 엔드포인트 링크)."""
    return {
        'prediction': {
            'metric': r.get('pred_metric') or r.get('metric_name'),
            'baseline': r.get('pred_baseline'),
            'noise_band': r.get('pred_noise_band'),
            'novel_registered': bool(r.get('novel_registered')),
        },
        'measurement': {'value': r.get('metric_value'), 'scope': r.get('metric_scope')},
        'verdict': r.get('verdict'),
        'novel_confirmed': bool(r.get('novel_confirmed')),
        'eureka': {'felt': r.get('eureka_felt'), 'true': r.get('eureka_true'),
                   'hallucinated': r.get('eureka_hallucinated')},
        'source': r.get('source'),
        'source_trust': r.get('source_trust'),
        'links': {'prov': f"/api/tree/{{name}}/node/{r['tag']}/provenance",
                  'standing': f"/api/tree/{{name}}/node/{r['tag']}/standing",
                  'certificate': f"/api/tree/{{name}}/node/{r['tag']}/certificate",
                  'eureka': f"/api/tree/{{name}}/node/{r['tag']}/eureka"},
    }


def tree_graph(td: dict, m: dict) -> dict:
    """트리 → GUI 렌더용 그래프. node(색/klass/패널) + edge + frontier + agenda(human-in-the-loop)."""
    canon = set(m.get('canonical_path') or [])
    rejected = set(m.get('rejected') or [])
    abandon = {c['leaf'] for c in (m.get('laudan') or {}).get('abandon_candidates', [])}
    low_cred = {b['leaf'] for b in (m.get('bayes') or {}).get('low_credence_branches', [])}
    regression = abandon | low_cred | rejected

    nodes = []
    for r in td['nodes']:
        tag = r['tag']
        klass = 'canonical' if tag in canon else ('regression' if tag in regression else 'live')
        nodes.append({
            'tag': tag, 'verdict': r.get('verdict'),
            'color': VERDICT_COLORS.get(r.get('verdict'), '#57606a'),
            'klass': klass,                          # 색 구분: 본류/잘린물길/살아있는가지
            'on_canonical_path': tag in canon,
            'panel': _node_panel(r),
        })

    edges = []
    for r in td['nodes']:
        for pe in (r.get('parent_edges') or []):
            if pe.get('tag'):
                edges.append({'child': r['tag'], 'parent': pe['tag'],
                              'relation_kind': pe.get('relation_kind'),
                              'inferred': bool(pe.get('inferred'))})

    frontier = [{'name': q.get('name'), 'status': q.get('status'),
                 'body': (q.get('body') or '')[:160]} for q in td.get('frontier', [])]

    # 안건(human-in-the-loop surface) — docs/UI_AND_HUMAN_LOOP §2: standing 철회/검토가 필요한 가지를 알림으로.
    agenda = (
        [{'kind': 'abandon_candidate', 'leaf': c['leaf'], 'reason': c.get('reason'),
          'action': 'review/branch-switch'}
         for c in (m.get('laudan') or {}).get('abandon_candidates', [])]
        + [{'kind': 'low_credence', 'leaf': b['leaf'], 'credence': b.get('credence'),
            'action': 'review'}
           for b in (m.get('bayes') or {}).get('low_credence_branches', [])]
    )

    return {
        'name': td.get('name'),
        'canonical_path': m.get('canonical_path'),
        'legend': KLASS_LEGEND,
        'nodes': nodes,
        'edges': edges,
        'frontier': frontier,
        'agenda': agenda,
        'counts': {'nodes': len(nodes), 'edges': len(edges),
                   'open_frontier': sum(1 for f in frontier if f['status'] == 'OPEN'),
                   'agenda': len(agenda)},
        'note': 'E Phase 1 — 시각 GUI 데이터 척추(프론트엔드 렌더는 Phase 2). klass 로 본류/퇴행/생존 색 구분.',
    }


# ── E Phase 2 — 시각 렌더 (프론트 빌드 없이 서버가 표준 포맷 + 브라우저 뷰어 방출) ────────────
_KLASS_FILL = {'canonical': '#dafbe1', 'regression': '#ffebe9', 'live': '#ddf4ff'}


def tree_dot(graph: dict) -> str:
    """graph(JSON) → Graphviz DOT. `dot -Tsvg` 로 렌더되는 표준 시각 포맷 — 색=klass/verdict, 모양=정본여부,
    엣지 점선=inferred. 결정적(테스트 가능). 브라우저 뷰어(tree_dot_view)와 CLI/툴 양쪽이 소비."""
    def q(s: str) -> str:
        return str(s).replace('\\', '').replace('"', "'")
    lines = ['digraph lakatotree {', '  rankdir=TB;',
             '  node [style=filled, fontname="monospace", fontsize=10];']
    for n in graph.get('nodes', []):
        fill = _KLASS_FILL.get(n.get('klass'), '#ffffff')
        shape = 'doubleoctagon' if n.get('on_canonical_path') else 'box'
        label = f"{q(n['tag'])}\\n{q(n.get('verdict') or '')}"
        lines.append(f'  "{q(n["tag"])}" [label="{label}", fillcolor="{fill}", '
                     f'color="{n.get("color", "#57606a")}", shape={shape}];')
    for e in graph.get('edges', []):
        style = 'dashed' if e.get('inferred') else 'solid'
        lines.append(f'  "{q(e["parent"])}" -> "{q(e["child"])}" '
                     f'[style={style}, label="{q(e.get("relation_kind") or "")}", fontsize=8];')
    lines.append('}')
    return '\n'.join(lines)


def tree_dot_view(name: str, dot: str) -> str:
    """브라우저 뷰어 — DOT 를 inline 임베드 + @viz-js CDN 으로 렌더(빌드 스텝 0). 본류/퇴행/생존 색 구분."""
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        f'<title>{html.escape(name)} — LakatoTree</title>'
        '<style>body{font-family:monospace;margin:20px}#g svg{max-width:100%}'
        '.lg span{padding:2px 8px;border-radius:4px;margin-right:8px}</style></head><body>'
        f'<h2>LakatoTree: {html.escape(name)}</h2>'
        '<p class="lg"><span style="background:#dafbe1">본류(정본 경로)</span>'
        '<span style="background:#ffebe9">퇴행/기각</span>'
        '<span style="background:#ddf4ff">살아있는 가지</span></p>'
        '<div id="g">렌더 중…</div>'
        f'<pre id="dot" style="display:none">{html.escape(dot)}</pre>'
        '<script src="https://cdn.jsdelivr.net/npm/@viz-js/viz@3/lib/viz-standalone.js"></script>'
        '<script>Viz.instance().then(function(v){'
        'var d=document.getElementById("dot").textContent;var g=document.getElementById("g");'
        'g.innerHTML="";g.appendChild(v.renderSVGElement(d));});</script>'
        f'<p><small>DOT: <a href="/api/graph/{html.escape(name)}/dot">/api/graph/{html.escape(name)}/dot</a> '
        '(<code>dot -Tsvg</code> 로도 렌더). 노드 상세 = /api/graph/{name} JSON 의 panel.</small></p>'
        '</body></html>')

