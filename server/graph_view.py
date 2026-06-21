"""E Phase 1 — 시각 트리 GUI 의 *데이터 척추* (docs/UI_AND_HUMAN_LOOP.md §2-4 'vision' 의 첫 물질화).

UI 비전은 "트리를 항해하는 GUI": 브랜치 줌, 노드 클릭→prediction/measurement/verdict/prov/pnr 패널,
프론티어·퇴행 가지·정본 경로를 색으로 구분, shift_candidate/standing 철회 같은 *안건* surface.

이 모듈은 그 GUI 가 렌더할 **구조화 그래프 JSON** 을 만든다(프론트엔드는 Phase 2, 별도). 즉 React/SVG
없이도 GUI 가 필요로 하는 데이터 — node(색/klass/패널) + edge(BRANCHED_FROM) + frontier + agenda — 를
read-model 로 제공한다. load_tree_data + compute_metrics 산출을 소비(새 KG 쿼리 0).
"""

from __future__ import annotations

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
