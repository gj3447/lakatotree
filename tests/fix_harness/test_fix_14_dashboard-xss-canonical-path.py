"""FIX-HARNESS #14 (P2 보안): 대시보드 정본 경로 라인의 stored XSS.

- finding id: #14
- locations:
    server/dashboard_view.py:67  ->  out.append(f"<p><b>정본 경로</b>: {' → '.join(m['canonical_path'])}</p>")
      같은 함수 내 다른 모든 tag/name 렌더는 html.escape 를 거치지만(예: 50,65,66,93,151,164행)
      정본 경로(canonical_path)만 escape 없이 raw 로 join 된다.
    server/contexts/tree/schemas.py  ->  node 'tag' 은 Field(min_length=1) 뿐, 문자 제한 없음.
    lakatos/quant/metrics.py:110 _canonical_path  ->  canonical_path 는 정본 leaf tag + 그 1차 부모 조상 tag 들.
- bug: tag 에 '<script>alert(1)</script>' 가 들어가고 그 노드가 정본(CANONICAL) 이면
       canonical_path 에 그대로 실려 67행에서 escape 없이 HTML 로 출력 -> stored XSS.
- fix (server/dashboard_view.py:67):
       ' → '.join(html.escape(p) for p in (m['canonical_path'] or []))
- 본 테스트는 fix 가 들어올 때까지 xfail(strict). 고쳐지면 strict 가 trip 한다.
"""
import importlib
import os

import pytest
from fastapi.testclient import TestClient


# tests/test_dashboard.py 의 로더/노드 빌더를 그대로 미러링 (실 ASGI 렌더 경로 타격).
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
                novel_registered=kw.get('nr'), novel_confirmed=kw.get('nc'), questions=kw.get('qs', []))


XSS_TAG = '<script>alert(1)</script>'

# 정본(CANONICAL) leaf 의 tag 에 스크립트 페이로드를 심는다 -> canonical_path 에 raw 로 실린다.
POISONED = dict(
    name='T', title='T tree', hard_core=[], frontier_rule='', doc='',
    coverage_backlog=[], coverage_statement='',
    nodes=[
        _node('root', 'progressive', mn='p95', mv=0.4, pb=0.5, nb=0.05, nr=True, nc=True),
        _node(XSS_TAG, 'CANONICAL', parent='root', mn='p95', mv=0.28),
    ],
    frontier=[dict(name='q1', status='OPEN', body='b', closed_by=None,
                   expected_gain=0.5, cost=1.0, n_visits=1)])


# [FIXED 2026-06-27] #14 — green regression (server/dashboard_view.py:67 now html.escape per element)
def test_canonical_path_tag_is_escaped(monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, 'trees', lambda: [{'name': 'T', 'title': 'T tree'}])
    monkeypatch.setattr(app, 'tree_data', lambda n: POISONED)
    # compute_metrics 는 실제 함수 그대로 — 진짜 canonical_path 계산 경로를 탄다.
    r = TestClient(app.app).get('/')
    assert r.status_code == 200
    html_out = r.text

    # 사전 조건: 정본 경로 라인이 실제로 렌더됐고 페이로드가 canonical_path 에 도달했음을 확인.
    assert '정본 경로' in html_out
    assert XSS_TAG in app.compute_metrics(POISONED)['canonical_path']

    # 올바른(fix 후) 동작: raw 스크립트는 출력에 없고, escape 된 형태만 있어야 한다.
    assert XSS_TAG not in html_out                       # raw <script>alert(1)</script> 금지
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html_out  # 다른 렌더처럼 escape 됨
