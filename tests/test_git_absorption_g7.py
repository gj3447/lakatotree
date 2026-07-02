"""git-흡수 G7 landed guards — consilience 연산자 (merge-ort 이식, PIDNA §3.3 재합류 정량조건 폐쇄).

  guard_defect(개선축)     : test_merged_credence_is_not_max_shortcut
        — 병합 credence 는 max(c1,c2) 지름길이 아니라 UNION verdict 시퀀스의 branch_credence fold:
          양측이 *같은 타깃*을 확증하면 1회만(재확증=초과내용 0, Zahar use-novelty), 음의 증거는
          양측 *모두* 누적(Popper 비대칭). target 없는 확증은 fail-closed(q_target_identity_scheme —
          bayes.py 의 permissive None=always-novel 인플레가 consilience 경로로 못 들어온다).
  guard_mechanism(novel축) : test_consilience_is_deterministic_incore_conflict_as_data
        — merge-ort(merge-ort.c:5303-5391) 이식 실재: 3-way(두 leaf + 최근접 BRANCHED_FROM 조상),
          criss-cross 는 조상 재귀병합 가상조상(standing-불활성, :5006-5016 가상커밋에 ref 없음 패턴),
          비양립 = conflict *데이터*{target,base,side1,side2}(clean=false 여도 병합 완료),
          incore 순수(verdict_mutation=False, 입력 불변) + 바이트동일 결정론 리포트.

# KG: LakatosTree_GitAbsorption_20260702 / G7_consilience_operator
"""
from __future__ import annotations

import copy
import json

import pytest

from lakatos.programme import consilience as C
from lakatos.quant.bayes import branch_credence


def _v(tag: str, verdict: str, target: str | None = None, delta: float = 0.0, nb: float = 1.0) -> dict:
    d = {'tag': tag, 'verdict': verdict, 'delta': delta, 'noise_band': nb}
    if target is not None:
        d['target'] = target
    return d


# ── guard_defect (개선축, 음성 오라클): naive 재합류(max 지름길·무타깃 인플레)가 죽었다 ─────────
def test_merged_credence_is_not_max_shortcut():
    base = [_v('n0', 'progressive', 'q-base', delta=5)]
    # side1: 독립 확증 1개. side2: *같은 타깃* 확증 + 음의 증거 1개.
    a1 = _v('a1', 'progressive', 'q-t1', delta=8)
    b1 = _v('b1', 'progressive', 'q-t1', delta=8)
    b2 = _v('b2', 'rejected', delta=3)
    side1, side2 = base + [a1], base + [b1, b2]
    c1, c2 = branch_credence(side1), branch_credence(side2)

    out = C.union_credence(base, side1, side2)
    merged = out['merged']
    # (1) max 지름길 기각: 같은 타깃 dedup + 음의 증거 양측 누적 → merged < max(c1,c2).
    assert merged < max(c1, c2), (merged, c1, c2)
    # (2) 정의 일치: merged == UNION 시퀀스(base + 양측 delta)의 branch_credence fold.
    union_seq = base + [a1, b1, b2]
    assert merged == pytest.approx(branch_credence(union_seq))
    # (3) 재확증=초과내용 0: 양측이 같은 타깃만 확증하면 병합은 단측과 동일 credence(1회 집계).
    s1, s2 = base + [_v('a1', 'progressive', 'q-t1', delta=8)], base + [_v('b1', 'progressive', 'q-t1', delta=8)]
    both = C.union_credence(base, s1, s2)
    assert both['merged'] == pytest.approx(branch_credence(s1))
    # (4) 공유 base 는 tag 정체성으로 1회만 union 에 들어간다(양측 시퀀스에 중복 실려도).
    assert out['union_size'] == len(union_seq)
    # (5) fail-closed: target 없는 *확증*(BF>1 어휘)은 fold 거부 — 무타깃 인플레가 이 경로로 못 들어옴.
    with pytest.raises(C.ConsilienceTargetMissing):
        C.union_credence(base, base + [_v('x1', 'progressive', None, delta=8)], side2)
    # 음의/무정보 증거는 target 없어도 적법(매번 누적이 정직) — 거부 안 함.
    C.union_credence(base, base + [_v('x2', 'rejected')], base + [_v('x3', 'partial')])


# ── guard_mechanism (novel축, 양성 오라클): merge-ort 메커니즘 실재 ─────────────────────────
def _crisscross_fixture():
    # R ← A,B ← X(=A+B), Y(=A+B) ← L1, L2  — X·Y 가 A·B 를 교차상속(criss-cross): NCA(L1,L2)={A,B}.
    parents = {'L1': ['X'], 'L2': ['Y'], 'X': ['A', 'B'], 'Y': ['A', 'B'], 'A': ['R'], 'B': ['R'], 'R': []}
    stances = {
        'R': {'hc': {'v': 'core-0'}},
        'A': {'hc': {'v': 'core-0'}, 't1': {'v': 'p'}},
        'B': {'hc': {'v': 'core-0'}, 't2': {'v': 'q'}},
        'X': {'hc': {'v': 'core-0'}, 't1': {'v': 'p'}, 't2': {'v': 'q'}},
        'Y': {'hc': {'v': 'core-0'}, 't1': {'v': 'p'}, 't2': {'v': 'q'}},
        # side1(L1): t3 를 s1 로, t4 를 same 으로, t5 를 단독 추가. side2(L2): t3 를 s2 로(비양립), t4 same.
        'L1': {'hc': {'v': 'core-0'}, 't1': {'v': 'p'}, 't2': {'v': 'q'},
               't3': {'v': 's1'}, 't4': {'v': 'same'}, 't5': {'v': 'only1'}},
        'L2': {'hc': {'v': 'core-0'}, 't1': {'v': 'p'}, 't2': {'v': 'q'},
               't3': {'v': 's2'}, 't4': {'v': 'same'}},
    }
    return parents, stances


def test_consilience_is_deterministic_incore_conflict_as_data():
    parents, stances = _crisscross_fixture()
    frozen = copy.deepcopy((parents, stances))
    report = C.consilience_report(parents=parents, stances=stances, leaf1='L1', leaf2='L2')

    # (1) criss-cross → 가상조상: A·B 를 재귀병합, standing-불활성(ref 없는 가상커밋 패턴).
    va = report['virtual_ancestor']
    assert va is not None and va['standing_inert'] is True
    assert sorted(va['from']) == ['A', 'B'], va
    # 가상조상은 A 의 t1 과 B 의 t2 를 clean 하게 합쳐 base 로 제공(한쪽만 변경 → 채택).
    assert report['merge_base']['t1'] == {'v': 'p'} and report['merge_base']['t2'] == {'v': 'q'}

    # (2) 3-way 규칙: 동일 변경 1회 채택 · 한쪽만 변경 채택 · 비양립 = conflict *데이터*.
    assert report['merged_stances']['t4'] == {'v': 'same'}
    assert report['merged_stances']['t5'] == {'v': 'only1'}
    assert 't3' not in report['merged_stances']
    assert report['conflicts'] == [{'target': 't3', 'base': None,
                                    'side1': {'v': 's1'}, 'side2': {'v': 's2'}}]
    # (3) clean=False 여도 병합은 *완료*(conflict 는 실패가 아니라 데이터) — canonical 채택만 차단.
    assert report['clean'] is False
    assert report['canonical_adoptable'] is False
    assert report['merged_stances']['t1'] == {'v': 'p'}   # 병합 산출물은 온전
    # (4) incore 순수: verdict_mutation=False + 입력 불변(그래프 쓰기 0 — 판결 권위는 judge/human 게이트).
    assert report['verdict_mutation'] is False
    assert (parents, stances) == frozen, '입력 변이 — incore 계약 위반'
    # (5) 결정론: 입력 dict/list 순서를 뒤섞어도 바이트동일 리포트(merge-ort 결정론 이식).
    parents2 = {k: list(v) for k, v in reversed(list(parents.items()))}
    stances2 = {k: dict(reversed(list(v.items()))) for k, v in reversed(list(stances.items()))}
    report2 = C.consilience_report(parents=parents2, stances=stances2, leaf1='L1', leaf2='L2')
    assert C.report_bytes(report) == C.report_bytes(report2)
    json.loads(C.report_bytes(report))   # 리포트는 적법 JSON(수송 가능 증거)


def test_single_ancestor_merge_has_no_virtual_ancestor():
    """비-criss-cross(NCA 1개)는 가상조상 없이 그 조상이 곧 base — 기본 경로 계약."""
    parents = {'L1': ['A'], 'L2': ['A'], 'A': []}
    stances = {'A': {'t': {'v': 'base'}},
               'L1': {'t': {'v': 'base'}, 'u': {'v': 'x'}},
               'L2': {'t': {'v': 'changed'}}}
    r = C.consilience_report(parents=parents, stances=stances, leaf1='L1', leaf2='L2')
    assert r['virtual_ancestor'] is None
    assert r['merged_stances'] == {'t': {'v': 'changed'}, 'u': {'v': 'x'}}   # 한쪽변경 채택 × 2
    assert r['clean'] is True and r['canonical_adoptable'] is True


def test_modify_delete_is_conflict_not_silent_win():
    """한쪽 삭제 + 한쪽 수정 = conflict 데이터(무음 승자 금지) — merge-ort modify/delete 계약."""
    parents = {'L1': ['A'], 'L2': ['A'], 'A': []}
    stances = {'A': {'t': {'v': 'base'}},
               'L1': {},                          # side1: t 삭제
               'L2': {'t': {'v': 'changed'}}}     # side2: t 수정
    r = C.consilience_report(parents=parents, stances=stances, leaf1='L1', leaf2='L2')
    assert r['conflicts'] == [{'target': 't', 'base': {'v': 'base'},
                               'side1': None, 'side2': {'v': 'changed'}}]
    assert r['clean'] is False
