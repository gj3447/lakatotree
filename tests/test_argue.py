"""논증 채널 TDD — Dung AF. 인간/agent 의문이 판결을 공격, grounded extension 이 정본.
# KG: span_lakatotree_argue
"""
from lakatos.verdict.argue import (
    acceptance_explanation,
    grounded_extension,
    grounded_extension_agrees,
    parse_extension,
    to_apx,
    to_tgf,
    verdict_stands,
)

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


# ── OSS 적용: ICCMA TGF/APX 직렬화 + 외부 solver 교차검증 oracle (THEORY §7: solver=evidence) ──

def test_to_tgf_is_deterministic_iccma_format():
    tgf = to_tgf({'v', 'd', 'r'}, [('r', 'd'), ('d', 'v')])
    # 노드 정렬 → '#' → 엣지 정렬. 같은 AF 는 같은 문자열(결정적).
    assert tgf == "d\nr\nv\n#\nd v\nr d"
    assert to_tgf({'v', 'd', 'r'}, [('d', 'v'), ('r', 'd')]) == tgf   # 입력 순서 불변


def test_to_apx_aspartix_format():
    apx = to_apx({'a', 'b'}, [('a', 'b')])
    assert apx == "arg(a).\narg(b).\natt(a,b)."


def test_to_tgf_drops_dangling_attacks():
    # 미등록 노드 가리키는 공격은 제외(그래프 무결)
    assert to_tgf({'a'}, [('a', 'ghost'), ('ghost', 'a')]) == "a\n#"


def test_grounded_extension_agrees_with_external_solver():
    args, atts = {'v', 'd', 'r'}, [('d', 'v'), ('r', 'd')]
    # 외부 ICCMA solver 가 [r,v] 를 grounded 로 보고 → argue 와 일치(교차검증 통과)
    assert grounded_extension_agrees(args, atts, parse_extension("[r,v]"))
    assert grounded_extension_agrees(args, atts, {'v', 'r'})
    # solver 가 다른 extension 보고 → 불일치 감지(우리 구현 vs oracle 발산을 잡는다)
    assert not grounded_extension_agrees(args, atts, {'d'})


def test_parse_extension_handles_iccma_output_forms():
    assert parse_extension("[a,b,c]") == {'a', 'b', 'c'}
    assert parse_extension("a b\nc") == {'a', 'b', 'c'}
    assert parse_extension("[]") == set()


def test_acceptance_explanation_gives_rebuttal_provenance():
    # r→d→v: v accepted because doubt d is rebutted by r; d rejected by r; r accepted.
    exp = acceptance_explanation({'v', 'd', 'r'}, [('d', 'v'), ('r', 'd')])
    assert exp['v'] == {"status": "accepted", "rebutted_doubts": {'d': ['r']}}
    assert exp['d'] == {"status": "rejected", "unrebutted_doubts": ['r']}
    assert exp['r'] == {"status": "accepted", "rebutted_doubts": {}}


def test_acceptance_explanation_marks_undecided_self_attack():
    # 자기공격 a 는 grounded 에서 undecided(수용도 거절도 아님)
    exp = acceptance_explanation({'a'}, [('a', 'a')])
    assert exp['a']['status'] == 'undecided'
