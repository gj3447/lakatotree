"""R9-CONSIL — G7 consilience 연산자의 유저 표면 가드 (후속 PROM 2026-07-03).

배경: lakatos/programme/consilience.py(G7, PIDNA §3.3 재합류)는 순수 모듈만 있고 호출자 0
— 진열장 코드. 재료(load_tree_data 노드 행: parents/pred_closes/verdict/…)는 전부 있으므로
projector(행→연산자 입력) + GET verb 로 유저 표면을 연다.

  guard_defect(음성)    : test_credence_fail_closed_translates_to_422_not_silent_merge
        — credence=true 에서 BF>1 어휘(progressive) 무타깃 verdict 는 무음 병합이 아니라
          HTTP 422(ConsilienceTargetMissing 번역). projector 가 무타깃 확증을 *무음 필터*하면
          union_credence 가 못 보고 200 이 샌다 = RED. 라우트 부재(구현 전)=404 = RED.
  guard_mechanism(양성) : test_crisscross_get_route_returns_deterministic_report
        — criss-cross 노드 행(fake tree_data) → GET 라우트 → virtual_ancestor.standing_inert
          true + 같은 입력 2회 report_sha/리포트 바이트동일 + verdict_mutation false.
          stance target 은 pred_closes SSOT + pred_metric fallback 이 실제로 투영됨을 확인.

# KG: LakatosTree_GitAbsorption_20260702 / followup-R9-consil
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.contexts.tree.api import create_tree_router
from server.contexts.tree.service import TreeService


def _row(tag: str, parents: list | None = None, verdict: str = 'proof',
         pred_closes: str | None = None, pred_metric: str | None = None,
         metric_value: float | None = None, pred_baseline: float | None = None,
         pred_noise_band: float | None = None, source_trust: float | None = None) -> dict:
    """load_tree_data 정규화 노드 행의 최소 아날로그(consilience projector 가 소비하는 필드만)."""
    return dict(tag=tag, parents=list(parents or []), verdict=verdict,
                pred_closes=pred_closes, pred_metric=pred_metric,
                metric_value=metric_value, pred_baseline=pred_baseline,
                pred_noise_band=pred_noise_band, source_trust=source_trust)


def _crisscross_rows() -> list[dict]:
    """test_git_absorption_g7._crisscross_fixture 의 노드-행 형태: NCA(L1,L2)={A,B}(criss-cross).
    X = progressive 인데 무타깃(pred_closes/pred_metric 없음) — credence fold 의 fail-closed 표적.
    L2 = pred_closes 빈값 + pred_metric 만(fallback 경로 실증)."""
    return [
        _row('R'),
        _row('A', ['R'], verdict='progressive', pred_closes='t1',
             metric_value=1.0, pred_baseline=2.0, pred_noise_band=0.5),
        _row('B', ['R'], verdict='progressive', pred_closes='t2',
             metric_value=3.0, pred_baseline=4.0, pred_noise_band=0.5),
        _row('X', ['A', 'B'], verdict='progressive'),          # ★무타깃 확증(BF>1)
        _row('Y', ['A', 'B'], verdict='partial'),              # 무타깃이어도 적법(BF=1)
        _row('L1', ['X'], verdict='progressive', pred_closes='t3',
             metric_value=5.0, pred_baseline=6.0, pred_noise_band=0.5),
        _row('L2', ['Y'], verdict='partial', pred_metric='t4', metric_value=7.0),
    ]


class _Repo:
    """tree_data 읽기 계약의 무-KG 더블 — load_tree_data 산출(dict)만 흉내."""

    def __init__(self, nodes: list[dict]):
        self.nodes = nodes

    def load_tree_data(self, name: str) -> dict:
        return {'name': name, 'nodes': [dict(r) for r in self.nodes], 'frontier': []}


def _client(nodes: list[dict]) -> TestClient:
    svc = TreeService(kg=lambda *a, **k: [], kg_tx=lambda ops: [],
                      hist=lambda *a, **k: None, pg=lambda: None, repo=_Repo(nodes))
    app = FastAPI()
    app.include_router(create_tree_router(lambda: svc))
    return TestClient(app)


# ── guard_defect (음성): 무타깃 확증의 credence 는 무음 병합이 아니라 422 ────────────────────
def test_credence_fail_closed_translates_to_422_not_silent_merge():
    c = _client(_crisscross_rows())
    # (1) credence=true: L1 조상경로의 X(progressive, 무타깃) → ConsilienceTargetMissing → 422.
    #     projector 가 X 를 무음 필터하면 200 이 새어나온다(=이 단언이 죽음을 증언).
    r = c.get('/api/tree/T/consilience', params={'leaf1': 'L1', 'leaf2': 'L2', 'credence': 'true'})
    assert r.status_code == 422, f'무타깃 확증이 무음 병합됨(fail-closed 실종): {r.status_code} {r.text[:200]}'
    assert 'X' in str(r.json().get('detail', '')), r.text
    # (2) credence=false(기본): 같은 트리가 리포트는 받는다 — 레거시(무 pred_closes) 트리 오폭 금지.
    r2 = c.get('/api/tree/T/consilience', params={'leaf1': 'L1', 'leaf2': 'L2'})
    assert r2.status_code == 200, r2.text
    assert 'credence' not in r2.json()['report']
    # (3) 없는 leaf = 404 (빈 조상으로 무음 빈-병합 금지).
    assert c.get('/api/tree/T/consilience',
                 params={'leaf1': 'NOPE', 'leaf2': 'L2'}).status_code == 404


# ── guard_mechanism (양성): criss-cross 가상조상 + 결정론 리포트가 GET 표면에 실재 ───────────
def test_crisscross_get_route_returns_deterministic_report():
    c = _client(_crisscross_rows())
    r1 = c.get('/api/tree/T/consilience', params={'leaf1': 'L1', 'leaf2': 'L2'})
    assert r1.status_code == 200, r1.text
    body = r1.json()
    report = body['report']
    # (1) criss-cross: NCA(L1,L2)={A,B} → 가상조상(standing-불활성, ref 없는 가상커밋 패턴).
    va = report['virtual_ancestor']
    assert va is not None and va['standing_inert'] is True
    assert sorted(va['from']) == ['A', 'B'], va
    # (2) projector: pred_closes SSOT(t1/t2/t3) + pred_metric fallback(t4) stance 가 실제 투영됨.
    assert report['merge_base']['t1'] == {'verdict': 'progressive', 'metric_value': 1.0}
    assert report['merge_base']['t2'] == {'verdict': 'progressive', 'metric_value': 3.0}
    assert report['merged_stances']['t3'] == {'verdict': 'progressive', 'metric_value': 5.0}
    assert report['merged_stances']['t4'] == {'verdict': 'partial', 'metric_value': 7.0}
    # (3) incore 계약이 HTTP 표면까지 유지: GET=무변이, verdict 권위는 기존 게이트에 남는다.
    assert report['verdict_mutation'] is False
    # (4) 결정론: 같은 입력 2회 → report_sha 동일 + 리포트 바이트동일(수송 가능한 증거).
    r2 = c.get('/api/tree/T/consilience', params={'leaf1': 'L1', 'leaf2': 'L2'})
    assert r2.status_code == 200
    assert body['report_sha'] == r2.json()['report_sha']
    assert len(body['report_sha']) == 16
    from lakatos.programme.consilience import report_bytes
    assert report_bytes(report) == report_bytes(r2.json()['report'])
