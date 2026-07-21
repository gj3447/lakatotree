"""issuer calibration 투명성 표시 (credence-loop 연구 결정, 2026-07-21).

연구 결정 = CONDITIONAL_CLOSE: realized ECE 를 랭킹 credence *값*에 융합하는 것은 **닫지 않는다**
(범주오류 — pred_credence 예보과신 ≠ verdict-라벨발 branch_credence; tiny-n n=0~10; confirm_monotone
정리 RED; sprt-갭 자세). 대신 *투명성 갭*만 닫는다: 리더보드/cert 독자가 "이 랭킹 credence 는 ECE=0.57
과신 판관이 발급"임을 *보게* 표시층에 BESIDE 로 노출. 랭킹 값 미변경, 불변식 미파괴, 새 상수 0.

★NON-FUSION 불변식(load-bearing): 표시는 dominates()/branch_credence 에 절대 안 들어간다.
# KG: project_lakatotree_verifier_rigor_research_2026_07_21 (credence-loop CONDITIONAL_CLOSE)
"""
from server.contexts.tree.programme_service import issuer_calibration_annotation


def test_issuer_calibration_surfaces_ece_beside_ranking():
    # 발급자 과신(ECE=0.567, n=3) → 랭킹 credence 옆에 그대로 노출(표시-only).
    ann = issuer_calibration_annotation(dict(n=3, calibration_error=0.567), 3)
    assert ann['ece'] == 0.567 and ann['n'] == 3 and ann['status'] == 'surfaced'


def test_issuer_calibration_abstains_on_small_n():
    # tiny-n 은 ECE noise → abstain(완벽 ECE=0.0 이라도 인증 보류, 날조 0 금지).
    ann = issuer_calibration_annotation(dict(n=1, calibration_error=0.0), 3)
    assert ann['ece'] is None and ann['status'] == 'abstain_small_n'


def test_issuer_calibration_NOT_in_ranking_kernel():
    # ★NON-FUSION: 표시가 랭킹(dominates 기준)이나 credence 산출(branch_credence)에 절대 안 들어감.
    import inspect
    from lakatos.programme.leaderboard import CRITERIA
    from lakatos.quant.bayes import branch_credence
    assert CRITERIA == ('laudan_score', 'credence', 'fertility_lb')   # 보정 기준 추가 안 됨
    p = set(inspect.signature(branch_credence).parameters)
    assert 'ece' not in p and 'issuer_calibration' not in p and 'calibration' not in p   # credence 산출 불변


def test_directions_surfaces_issuer_calibration(monkeypatch):
    # 통합: directions() 응답(소비 surface)이 canonical_credence 옆에 issuer_calibration 을 실어 나른다.
    import server.contexts.tree.programme_service as ps
    svc = object.__new__(ps.ProgrammeService)   # __init__ 우회(순수 표시 경로만 검증)
    svc.tree_data = lambda n: {'nodes': [{'tag': 'r', 'verdict': 'CANONICAL', 'questions': []}], 'frontier': []}
    svc.compute_metrics = lambda td: {'bayes': {'canonical_credence': 0.5}, 'max_degeneration_depth': 0}
    svc.calibration = lambda n: dict(n=3, calibration_error=0.567)
    svc.rank_questions = lambda qmeta, **kw: qmeta
    out = svc.directions('T')
    assert out['issuer_calibration']['ece'] == 0.567
    assert out['canonical_credence'] == 0.5   # 랭킹 credence 는 표시 추가에 불변
