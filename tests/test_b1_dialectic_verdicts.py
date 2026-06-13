"""B1 — dialectical verdict vocabulary(degenerating/withdrawn/progressive_conditional)가
promote/metrics/bayes/verdicts 전반에 일관 인식되는지 (prom16 ENG-CORR-1/2, THR-1/F2).

핵심 안전버그: promote 가 'rejected' 만 막아 degenerating/withdrawn 노드가 CANONICAL 승격 가능했음.
"""
from lakatos.promote import promotion_gate
from lakatos.spine import synthesize_promotion
from lakatos.verdicts import is_registered_verdict, VERDICT_REGISTRY
from lakatos.bayes import branch_credence
from lakatos.metrics import branch_inputs, NONPROGRESSIVE


# ── ENG-CORR-1: 퇴행/철회 판결은 CANONICAL 승격 불가 (allowlist fail-closed) ──

def test_promotion_blocks_degenerating_and_withdrawn():
    for v in ('degenerating', 'withdrawn', 'ambiguous', 'rejected', 'metric_mismatch'):
        ok, reasons = promotion_gate(scripted_verdict=v, stands=True, reproducible=True)
        assert ok is False, f'{v} 가 승격 통과됨 (안전게이트 구멍)'
        assert any('promotable' in r or v in r for r in reasons)


def test_promotion_allows_progress_verdicts():
    for v in ('progressive', 'progressive_conditional', 'partial', 'equivalent', 'CANONICAL'):
        ok, _ = promotion_gate(scripted_verdict=v, stands=True, reproducible=True)
        assert ok is True, f'{v} 가 부당하게 차단됨'


def test_synthesize_promotion_blocks_degenerating_node():
    # 헤드라인: monster-barring → dialectical 'degenerating' 노드가 CANONICAL 못 됨
    out = synthesize_promotion(scripted_verdict='degenerating', stands=True, reproducible=True)
    assert out['ok'] is False
    assert not out['gates']['constitution']['passed']


# ── ENG-CORR-2: 'withdrawn' 등록 어휘 ──

def test_withdrawn_is_registered_verdict():
    assert is_registered_verdict('withdrawn')
    assert 'withdrawn' in VERDICT_REGISTRY


# ── THR-1: metrics NONPROGRESSIVE 가 degenerating/withdrawn 인식 ──

def _node(tag, verdict, parent=None, q=None):
    return dict(tag=tag, verdict=verdict, parent=parent, parents=[parent] if parent else [],
                parent_edges=[], metric_value=None, pred_baseline=None, pred_noise_band=None,
                novel_registered=False, questions=q or [])


def test_degenerating_withdrawn_count_as_nonprogressive():
    assert 'degenerating' in NONPROGRESSIVE and 'withdrawn' in NONPROGRESSIVE
    nodes = [_node('root', 'CANONICAL'),
             _node('a', 'degenerating', parent='root'),
             _node('b', 'withdrawn', parent='a')]
    bi = branch_inputs(nodes, [], leaf='b')
    assert bi['consecutive_nonprogressive'] == 2   # 전엔 0 (둘 다 progress 로 오인)


def test_progressive_conditional_counts_as_prediction_hit():
    nodes = [_node('root', 'progressive'),
             _node('a', 'progressive_conditional', parent='root')]
    bi = branch_inputs(nodes, [], leaf='a')
    assert bi['prediction_hits'] == 2   # progressive + progressive_conditional 둘 다


# ── THR-1: bayes 가 degenerating 을 음의 증거로 (neutral 오인 금지) ──

def test_bayes_degenerating_lowers_credence():
    base = branch_credence([{'verdict': 'progressive', 'delta': -0.5, 'noise_band': 0.05}])
    degen = branch_credence([{'verdict': 'progressive', 'delta': -0.5, 'noise_band': 0.05},
                             {'verdict': 'degenerating', 'delta': 0.3, 'noise_band': 0.05}])
    assert degen < base   # degenerating 이 신뢰도를 낮춤 (전엔 BF=1 neutral → 불변)
