"""논증 채널 TDD — Dung AF. 인간/agent 의문이 판결을 공격, grounded extension 이 정본.
# KG: span_lakatotree_argue
"""
from lakatos.verdict.argue import grounded_extension, verdict_stands

def test_unattacked_argument_accepted():
    ext = grounded_extension({'v', 'd'}, [])
    assert 'v' in ext and 'd' in ext

def test_attack_defeats():
    # d 가 v 를 공격, d 는 무공격 → d 채택, v 탈락 (의문이 판결을 무너뜨림)
    ext = grounded_extension({'v', 'd'}, [('d', 'v')])
    assert 'd' in ext and 'v' not in ext

def test_rebuttal_reinstates():
    # r 이 d 를 공격(반박) → v 복권 (판결이 의문을 막아냄)
    ext = grounded_extension({'v', 'd', 'r'}, [('d', 'v'), ('r', 'd')])
    assert 'v' in ext and 'r' in ext and 'd' not in ext

def test_verdict_stands_helper():
    assert verdict_stands('v', {'v', 'd', 'r'}, [('d', 'v'), ('r', 'd')])
    assert not verdict_stands('v', {'v', 'd'}, [('d', 'v')])
