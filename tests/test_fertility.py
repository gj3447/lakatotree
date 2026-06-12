"""이론 발전성 TDD — novel 예측을 미리 맞힌 비율(라카토스 핵심=노벨상 본질).
# KG: span_lakatotree_fertility
"""
from lakatos.fertility import predictive_fertility, nobel_grade

NODES = [
 dict(tag='a', verdict='CANONICAL', novel_registered=True, novel_confirmed=True),
 dict(tag='b', verdict='progressive', novel_registered=True, novel_confirmed=True),
 dict(tag='c', verdict='partial', novel_registered=True, novel_confirmed=False),
 dict(tag='d', verdict='rejected', novel_registered=False, novel_confirmed=False),
]

def test_fertility_basic():
    f = predictive_fertility(NODES)
    assert f['registered'] == 3 and f['confirmed'] == 2
    assert f['fertility'] == round(2/3, 3)

def test_fertility_zero_when_no_predictions():
    f = predictive_fertility([dict(tag='x', verdict='partial', novel_registered=False, novel_confirmed=False)])
    assert f['fertility'] == 0.0 and f['registered'] == 0

def test_nobel_grade_requires_volume_and_hitrate():
    # 노벨급 = 충분한 예측 수 AND 높은 적중률 (둘 다)
    strong = [dict(tag=str(i), verdict='progressive', novel_registered=True, novel_confirmed=True) for i in range(5)]
    assert nobel_grade(predictive_fertility(strong))
    few = [dict(tag='a', verdict='progressive', novel_registered=True, novel_confirmed=True)]
    assert not nobel_grade(predictive_fertility(few))   # 적중률 100%여도 표본 부족
    noisy = [dict(tag=str(i), verdict='progressive', novel_registered=True, novel_confirmed=(i<2)) for i in range(5)]
    assert not nobel_grade(predictive_fertility(noisy))  # 표본 충분해도 적중률 낮음(2/5)
