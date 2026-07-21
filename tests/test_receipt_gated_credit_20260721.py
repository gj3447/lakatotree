"""영수증 게이트 (파이드나 재감사 2026-07-21) — force_of 는 *라벨*이 아니라 *영수증*을 봐야 한다.

재감사 발견(적대검증 5-lens 수렴): force_of/force_of_row 는 verdict_source *라벨*('scripted')만 보고
COUNTS 를 냈다 — 실제 영수증(current_receipt_sha)이 없어도. fsck._check_forceful_receipt 가 그 부재를
flag(라이브 FORCEFUL_SOURCE_WITHOUT_RECEIPT=159)하지만 judge(크레딧) 경로는 그걸 안 보고 그대로 셌다
(= 사용자 lesson '지적만 하면 정정 아님'). 또 producer-replay 가 측정을 반증(replay_status='mismatch')해도
verdict 강등이 없어 fertility/eureka 가 credit 했다(라이브 MEASUREMENT_REFUTED_BUT_STANDING=33).

이 파일이 그 둘을 영수증으로 고정(RED-first 이중가드):
  - force_of_row 는 FORCEFUL source 인데 current_receipt_sha 가 present-but-empty 면 INCONCLUSIVE(159 봉합).
  - tree_metrics 는 그 노드 + replay-mismatch standing 노드를 진보/발전성/eureka credit 에서 제외.
  - 레거시/픽스처(current_receipt_sha 키 부재)는 신뢰 유지(기존 force_of 철학 비파괴, golden 불변).
# KG: project_lakatotree_pidna_fidelity_reaudit_2026_07_21
"""
from lakatos.verdicts import force_of_row
from lakatos.quant.metrics import tree_metrics


def _node(tag, **kw):
    base = dict(tag=tag, parent=None, verdict='progressive', verdict_source='scripted',
                novel_registered=True, novel_confirmed=True,
                metric_name='m', metric_value=1.0, metric_scope='s')
    base.update(kw)
    return base


# ── force_of_row: 라벨이 아니라 영수증 ────────────────────────────────────────────────
def test_force_of_row_forceful_without_receipt_is_inconclusive():
    # 159 장르: 실 KG row 는 current_receipt_sha 키를 항상 싣는다(present-but-None = 원장 부재).
    assert force_of_row({'verdict': 'progressive', 'verdict_source': 'scripted',
                         'current_receipt_sha': None}) == 'INCONCLUSIVE'


def test_force_of_row_forceful_with_receipt_counts():
    assert force_of_row({'verdict': 'progressive', 'verdict_source': 'scripted',
                         'current_receipt_sha': 'a1b2c3'}) == 'COUNTS'


def test_force_of_row_legacy_absent_receipt_key_still_trusted():
    # 키 부재(레거시/픽스처) → 신뢰(비파괴, 기존 golden 유지).
    assert force_of_row({'verdict': 'progressive', 'verdict_source': 'scripted'}) == 'COUNTS'


# ── tree_metrics: 영수증 없는/반증된 노드는 발전성·eureka credit 에서 빠진다 ────────────
def test_tree_metrics_excludes_receiptless_forceful_from_fertility():
    nodes = [
        _node('clean', current_receipt_sha='r1'),          # 영수증 O → credit
        _node('noreceipt1', current_receipt_sha=None),     # 159 장르 → 제외
        _node('noreceipt2', current_receipt_sha=None),     # 159 장르 → 제외
    ]
    m = tree_metrics(nodes, [], None)
    assert m['fertility']['confirmed'] == 1, m['fertility']   # clean 만 credit


def test_tree_metrics_excludes_replay_refuted_from_fertility():
    nodes = [
        _node('clean', current_receipt_sha='r1'),
        _node('refuted', current_receipt_sha='r2', replay_status='mismatch'),   # 33 장르 → 제외
    ]
    m = tree_metrics(nodes, [], None)
    assert m['fertility']['confirmed'] == 1, m['fertility']


def test_tree_metrics_still_credits_clean_receipted_node():
    # 이중가드(메커니즘 실재): fix 가 전부 0 으로 만드는 게 아니라 *영수증 있는* 노드는 센다.
    nodes = [_node('clean', current_receipt_sha='r1', replay_status='verified')]
    m = tree_metrics(nodes, [], None)
    assert m['fertility']['confirmed'] == 1, m['fertility']


# ── 열매(fertility)를 리더보드→패러다임 경로에서도 receipt-gate (하네스=열매) ──────────────
def test_leaderboard_score_excludes_receiptless_forceful_fruit():
    # score_competitor 는 raw 노드에 predictive_fertility 직접 호출(tree_metrics neutralize 우회) —
    # 영수증 없는 열매가 fertility_lb 를 부풀려 kuhn supersession 을 오염시키던 구멍.
    from lakatos.programme.leaderboard import Competitor, score_competitor
    fake_fruit = [_node(f'n{i}', current_receipt_sha=None) for i in range(9)]
    c = Competitor('receiptless', [{'verdict': 'progressive', 'delta': -0.5, 'noise_band': 0.05}] * 9,
                   fake_fruit, metric_improvement_pct=27.0, closed=5, opened=1)
    s = score_competitor(c)
    assert s['fertility_raw']['confirmed'] == 0, s['fertility_raw']   # 가짜 열매 credit 안 됨
    assert s['fertility_lb'] == 0.0


def test_leaderboard_score_still_credits_receipted_fruit():
    from lakatos.programme.leaderboard import Competitor, score_competitor
    real_fruit = [_node(f'n{i}', current_receipt_sha=f'r{i}') for i in range(9)]
    c = Competitor('receipted', [{'verdict': 'progressive', 'delta': -0.5, 'noise_band': 0.05}] * 9,
                   real_fruit, metric_improvement_pct=27.0, closed=5, opened=1)
    s = score_competitor(c)
    assert s['fertility_raw']['confirmed'] == 9, s['fertility_raw']   # 영수증 있는 열매는 credit


# ── credence 도 열매와 같은 SSOT 로 receipt-gate (PROM16 P0 — fertility만 막고 credence raw면 ─────
#    영수증 없는 progressive 가 credence=1.0 → dominates() → kuhn supersession 오염, Goodhart) ────
def _receiptless_progressive_chain():
    """영수증 없는 forceful progressive 조상들 + 영수증 있는 CANONICAL leaf (branch_inputs 가 leaf 찾음)."""
    chain = [dict(tag=f'p{i}', parent=(f'p{i-1}' if i else None), verdict='progressive',
                  verdict_source='scripted', current_receipt_sha=None,
                  metric_value=float(10 + i), pred_baseline=2.0, pred_noise_band=0.1,
                  novel_registered=True, novel_confirmed=True) for i in range(6)]
    chain.append(dict(tag='leaf', parent='p5', verdict='CANONICAL', verdict_source='scripted',
                      current_receipt_sha='r_leaf', metric_value=20.0, pred_baseline=2.0,
                      pred_noise_band=0.1, novel_registered=True, novel_confirmed=True))
    return chain


def test_competitor_for_tree_gates_credence(monkeypatch):
    import server.app as app
    from lakatos.programme.leaderboard import score_competitor
    from lakatos.quant.metrics import branch_inputs
    from lakatos.quant.bayes import branch_credence
    chain = _receiptless_progressive_chain()
    monkeypatch.setattr(app, 'tree_data', lambda name: {'nodes': chain, 'frontier': []})
    gated = score_competitor(app._competitor_for_tree('x'))['credence']
    raw = round(branch_credence(branch_inputs(chain, [])['verdicts']), 3)   # neutralize 없이 = 부풀림
    assert gated < raw, (gated, raw)   # 영수증 없는 progressive 가 credence 를 부풀리지 못한다


# ── 감사 삼총사 완성 (metric-gate): 무영수증 노드의 raw metric_value 도 무력화 ────────────────
#    neutralize 가 verdict+novel_confirmed 만 끄고 metric_value 를 살려두면, 무영수증 조상의 측정값이
#    정본경로 improvement_pct→laudan_score(리더보드 Pareto·kuhn supersession) 를 여전히 움직인다.
def _metric_leak_chain():
    """무영수증 belt 조상(측정값 살아있으면 improvement_pct 조종) + 영수증 final CANONICAL leaf."""
    belt = [dict(tag=f'b{i}', parent=(f'b{i-1}' if i else None), verdict='progressive',
                 verdict_source='scripted', current_receipt_sha=None, metric_scope='belt',
                 metric_value=v, pred_baseline=2.0, pred_noise_band=0.1,
                 novel_registered=True, novel_confirmed=True)
            for i, v in enumerate([50.0, 30.0, 10.0])]
    belt.append(dict(tag='leaf', parent='b2', verdict='CANONICAL', verdict_source='scripted',
                     current_receipt_sha='r_leaf', metric_scope='final', metric_value=100.0,
                     pred_baseline=2.0, pred_noise_band=0.1, novel_registered=True, novel_confirmed=True))
    return belt


def test_tree_metrics_neutralizes_metric_value_of_receiptless():
    # guard_defect(음성 오라클): 무영수증 belt 측정값이 진보%를 못 움직인다 (현재 +80.0 → RED).
    prog = tree_metrics(_metric_leak_chain(), [], None)['progress'] or {}
    assert prog.get('improvement_pct') is None, prog
    assert prog.get('scope') != 'belt', prog   # belt scope 로 진보 계산 안 함


def test_tree_metrics_credits_receipted_metric_improvement():
    # guard_mechanism(양성 오라클): 영수증 있는 실개선은 보존 (과잉방어=정당 진보 지움 방지).
    nodes = [dict(tag='q0', parent=None, verdict='progressive', verdict_source='scripted',
                  current_receipt_sha='r0', metric_scope='s', metric_value=50.0,
                  pred_baseline=2.0, pred_noise_band=0.1),
             dict(tag='q1', parent='q0', verdict='CANONICAL', verdict_source='scripted',
                  current_receipt_sha='r1', metric_scope='s', metric_value=25.0,
                  pred_baseline=2.0, pred_noise_band=0.1)]
    assert tree_metrics(nodes, [], None)['progress']['improvement_pct'] == 50.0
