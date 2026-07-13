"""VoI / positive-heuristic 부활 — 판정엔진 감사 finding D 가드 (D1 expected_gain null sentinel + D2 cost
honesty + D4 novel gating). 감사: metric-progressive 우선순위화(next_directions)가 shadowed default 때문에
사실상 죽어있었다 — schema default expected_gain=0.1 / cost=1.0 가 EVERY question 에 주입돼 (a) directions 의
~120-LOC expected_progress_gain 파생(positive heuristic)이 미발화, (b) voi 의 cost≡1.0 이 VoI≡expected_gain
인데 Howard-1966 cost-정규화를 주장, (c) 아무 novel_* 필드 하나로 PG_NOVEL(0.40, 최대 항)을 사는 Goodhart.

수정: expected_gain/cost 를 NULL sentinel(None) 로 → None 이 end-to-end 보존(SET x=null 은 property 제거)되어
서버 파생이 발화하고 gain_source/cost_source 가 provenance 를 정직 공시. D4 는 has_novel 을 등록 novelty 또는
구조적으로 완전한 NovelTarget spec(metric∧direction∧threshold) 에만 부여.

이 sentinel 이전엔 default 가 항상 주입돼 파생이 죽었으므로, schema default 를 0.1/1.0 로 되돌리면 전 가드 RED.
# KG: span_lakatotree_explore / audit-finding-D-voi-positive-heuristic
"""
import importlib
import os

from lakatos.programme.explore import rank_questions, voi
from lakatos.programme.heuristic import _question_moves
from server.contexts.tree.schemas import QuestionIn


def load_app():
    os.environ.setdefault('NEO4J_URI', 'bolt://localhost:7687')
    os.environ.setdefault('NEO4J_USER', 'neo4j')
    os.environ.setdefault('NEO4J_PASSWORD', 'test')
    return importlib.import_module('server.app')


# ── D1/D2: NULL sentinel schema default (was 0.1 / 1.0 hardcoded, shadowing the derivation) ────
def test_question_in_omitted_fields_are_none_not_hardcoded_default():
    q = QuestionIn(qname='q-dogfood', body='b')
    assert q.expected_gain is None, 'D1: omit 시 None 이어야 derivation 이 발화(전엔 0.1 이 파생을 shadow)'
    assert q.cost is None, 'D2: omit 시 None 이어야 voi 가 cost-정규화를 주장하지 않음(전엔 1.0)'
    # 명시 값은 그대로 존중.
    qe = QuestionIn(qname='q2', expected_gain=0.4, cost=2.0)
    assert (qe.expected_gain, qe.cost) == (0.4, 2.0)


# ── D2: cost 모델 부재면 VoI 를 발행하지 않고 gain×UCB 로 명시적 fallback ────────────────────
def test_no_cost_model_keeps_voi_unmeasured():
    q = rank_questions([
        dict(name='q', expected_gain=0.3, cost=None, credence=0.5, n_visits=1)
    ], total_visits=1)[0]
    assert q['voi'] is None, '비용 미측정인데 숫자 VoI를 만들면 숨은 unit-cost가 부활'
    assert q['cost_source'] == 'unmeasured'
    assert q['ranking_basis'] == 'expected_gain_x_ucb'
    assert q['priority'] == round(q['expected_gain'] * q['ucb'], 4)


def test_voi_normalizes_only_when_client_supplies_cost():
    assert round(voi(0.3, 3.0), 4) == 0.1
    assert voi(0.2, 1.0) > voi(0.2, 4.0)


# ── D1: directions server-side derivation fires + differentiates (positive heuristic 부활) ──────
def test_directions_derives_and_differentiates_when_expected_gain_omitted(monkeypatch):
    app = load_app()
    # CANONICAL 노드가 q-front 를 raise → on_canonical_frontier=True (positive heuristic momentum).
    td = dict(name='T', title='T', hard_core=[], frontier_rule='', doc='',
              coverage_backlog=[], coverage_statement='',
              nodes=[dict(tag='c', verdict='CANONICAL', metric_value=None, questions=['q-front'])],
              frontier=[
                  dict(name='q-front', status='OPEN', body='', expected_gain=None, cost=None, n_visits=1),
                  dict(name='q-off', status='OPEN', body='', expected_gain=None, cost=None, n_visits=1),
                  dict(name='q-exp', status='OPEN', body='', expected_gain=0.5, cost=None, n_visits=1)])
    monkeypatch.setattr(app, 'tree_data', lambda n: td)
    monkeypatch.setattr(app, 'compute_metrics', lambda t: {'bayes': {'canonical_credence': 0.6}})
    out = app.directions('T')
    by = {d['name']: d for d in out['ranked_directions']}
    # omit 된 질문은 서버 파생(derived), 명시 질문은 explicit — provenance 정직.
    assert by['q-front']['gain_source'] == 'derived' and by['q-off']['gain_source'] == 'derived'
    assert by['q-exp']['gain_source'] == 'explicit' and by['q-exp']['expected_gain'] == 0.5
    # 파생이 구조로 차등: 정본 전선 질문 > 전선 밖 질문 (전엔 둘 다 0.1 하드코딩 = 동률).
    assert by['q-front']['expected_gain'] > by['q-off']['expected_gain']
    # cost 미측정 → 출처/순위 기준 공시, 숫자 VoI 발행 금지.
    assert by['q-front']['cost_source'] == 'unmeasured'
    assert by['q-front']['voi'] is None
    assert by['q-front']['ranking_basis'] == 'expected_gain_x_ucb'


# ── D4: PG_NOVEL only for registered novelty OR a structurally-complete NovelTarget spec ────────
def test_has_novel_requires_registered_or_complete_spec_not_mere_field():
    nodes = [dict(tag='c', verdict='CANONICAL', questions=[])]
    bare = _question_moves(nodes, [dict(name='q-bare', novel_target='x')],
                           dict(canonical_credence=0.5), 0.0, None)
    full = _question_moves(nodes, [dict(name='q-full', novel_metric='acc', novel_direction='higher',
                                        novel_threshold=0.9)],
                           dict(canonical_credence=0.5), 0.0, None)
    # mere-field-presence 는 PG_NOVEL 을 못 산다(Goodhart 봉합); 완전 spec 은 정당하게 최상위.
    assert full[0]['est_gain'] > bare[0]['est_gain']
