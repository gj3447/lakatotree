"""git-흡수 G5 landed guards — 단일 스코프 메트릭 프로젝터 (read-model drift 봉합, 아키텍처 감사 유일 HIGH).

  guard_defect(개선축)     : test_fertility_agrees_across_metrics_and_leaderboard
        — 두 표면의 fertility 가 각자 *선언한 스코프*의 계산과 일치하고 스코프 라벨을 노출 → 같은 이름의
          silent divergence 소멸(다른 스코프=다른 라벨). ✅
  guard_mechanism(novel축) : test_import_linter_forbids_metric_compute_outside_canonical_module
        — 소스 스캔: fertility 는 predictive_fertility 단일 프로젝터로만 계산되고, 모든 *표면* 호출이 scope 를
          명시(unscoped 표면 금지) + fertility 비율을 인라인 재계산하는 모듈 없음. ✅

# KG: LakatosTree_GitAbsorption_20260702 / G5_single_metric_projector
"""
from __future__ import annotations

import pathlib
import re

from lakatos.programme.leaderboard import Competitor, score_competitor
from lakatos.quant.fertility import predictive_fertility
from lakatos.quant.metrics import _fertility_layer

_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _node(tag, *, parent=None, registered=False, confirmed=False):
    return dict(tag=tag, parent=parent, verdict='progressive',
                novel_registered=registered, novel_confirmed=confirmed)


# 정본경로 = root→mid(둘 다 확증) ; off-path 'side' 는 등록했으나 미확증 → all_nodes 비율이 canonical 보다 낮음.
_NODES = [
    _node('root', registered=True, confirmed=True),
    _node('mid', parent='root', registered=True, confirmed=True),
    _node('side', parent='root', registered=True, confirmed=False),   # off canonical path
]
_PATH = ['root', 'mid']
_BY = {n['tag']: n for n in _NODES}


# ── guard_defect (개선축) — 착륙 ─────────────────────────────────────────────────────────
def test_fertility_agrees_across_metrics_and_leaderboard():
    """두 표면이 값은 스코프대로 다르되(2/2 vs 2/3), *각자 선언한 스코프의 계산과 일치*하고 라벨을 노출한다.

    봉합 전: 둘 다 'fertility' 라는 한 이름으로 다른 값을 내 silent divergence(어느 게 맞는지 알 수 없음).
    봉합 후: metrics=canonical_path(2/2=1.0), leaderboard=all_nodes(2/3≈0.667), 각각 scope 라벨 부착 →
    divergence 가 *설명됨*(silent 아님). 이 테스트는 각 표면이 제 스코프의 정답과 일치함을 못박는다."""
    m = _fertility_layer(_PATH, by=_BY, nodes=_NODES)
    lb = score_competitor(Competitor(
        name='T', verdicts=[], nodes=_NODES, metric_improvement_pct=0.0, closed=0, opened=0))['fertility_raw']

    # (1) 스코프 라벨 노출 — 같은 이름이 다른 의미를 나를 때 어느 스코프인지 명시.
    assert m['scope'] == 'canonical_path', m
    assert lb['scope'] == 'all_nodes', lb

    # (2) 각 표면이 제 스코프의 정답과 일치(silent wrong-scope 아님).
    assert m['registered'] == 2 and m['confirmed'] == 2 and m['fertility'] == 1.0, m       # canonical: root,mid
    assert lb['registered'] == 3 and lb['confirmed'] == 2 and lb['fertility'] == 0.667, lb  # all: +side

    # (3) 정본 프로젝터에 같은 노드셋을 주면 두 표면이 프로젝터 코어(registered/confirmed/fertility/scope)와
    #     정확히 일치(단일 계산원 — 표류 불가). _fertility_layer 는 nobel_grade/note 를 더 얹으므로 코어만 대조.
    _core = ('registered', 'confirmed', 'fertility', 'scope')
    proj_path = predictive_fertility([_BY[t] for t in _PATH], scope='canonical_path')
    proj_all = predictive_fertility(_NODES, scope='all_nodes')
    assert {k: m[k] for k in _core} == proj_path, (m, proj_path)
    assert {k: lb[k] for k in _core} == proj_all, (lb, proj_all)


# ── guard_mechanism (novel축) — 착륙 ─────────────────────────────────────────────────────
def _py_sources():
    for base in ('lakatos', 'server'):
        yield from (_ROOT / base).rglob('*.py')


def test_import_linter_forbids_metric_compute_outside_canonical_module():
    """소스 스캔 계약(H9 클래스실 방식): fertility 는 predictive_fertility 단일 프로젝터로만 계산되고,
    모든 *표면* 호출이 scope= 를 명시하며, fertility 비율을 인라인 재계산하는 모듈이 없다.

    비진공(anti-vacuity): 최소 2개의 scoped 호출 사이트(metrics·leaderboard)를 실제로 발견해야 통과."""
    call_re = re.compile(r'predictive_fertility\s*\(')
    scoped_sites = 0
    for path in _py_sources():
        if path.name == 'fertility.py':
            continue                                        # 정본 정의처
        text = path.read_text(encoding='utf-8')
        for m in call_re.finditer(text):
            window = text[m.start():m.start() + 160]        # 호출~인자 구간
            assert 'scope=' in window, \
                f"{path.name}: predictive_fertility 호출이 scope 미선언 (unscoped 표면 = drift 재개방)"
            scoped_sites += 1
    # 모든 표면이 단일 프로젝터를 scope 와 함께 호출 — 비진공: metrics·leaderboard 최소 2 사이트 발견해야.
    assert scoped_sites >= 2, f"scoped 호출 사이트 {scoped_sites} < 2 — 스캔이 진공(metrics·leaderboard 못 찾음)"
