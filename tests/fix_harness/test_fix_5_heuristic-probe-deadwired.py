"""FIX-HARNESS #5 (P2 정직성): heuristic PROBE 'already-probed' 억제 분기가 죽은 배선이다.

finding id: #5
locations:
  - lakatos/programme/heuristic.py:144-153  _probe_moves(hard_core, tested_core)
      `untested = [c for c in hard_core if c not in set(tested_core)]` — docstring 은
      hard-core 가정마다 PROBE 를 내되 *이미 탐침된* 가정은 제외한다고 광고한다.
  - server/contexts/tree/programme_service.py:184-189  heuristic_view (유일한 production caller)
      hard_core 를 *통째 free-text tree.hard_core 문자열 1개* 를 담은 단일-원소 튜플로 감싸고,
      tested_core 는 노드 metric_name 들이다 → 두 namespace 가 분리(disjoint)되어
      억제 분기가 *절대* 발화하지 못한다.
  - server/contexts/tree/judgement_service.py:465-466  같은 hard_core 필드를
      `.replace(';', ',') ... split(',')` 로 *토큰화*한다 → 단일-blob 취급은 의도가 아니라
      불일치(inconsistency)다.

the bug:
  hard_core 가 'A; B; C' 같은 다중 가정 free-text 면, production 은 그것을 ('A; B; C',) 한 덩어리로
  넘겨 _probe_moves 가 가정 1개당이 아니라 *문자열 전체* 를 target 으로 하는 PROBE 1개만 낸다.
  억제(이미 탐침 제외)는 tested_core 가 그 전체 문자열을 글자 그대로 담아야만 발화 → 영영 죽은 분기.
  VERIFIED: _probe_moves(('물리는 결정론적이다; 에너지는 보존된다',), ('accuracy','rmse')) → 1 move,
  target = 문자열 전체.

the exact fix:
  heuristic_view 에서 tree.hard_core 를 judgement_service(465-466) 토큰화를 재사용해 개별 가정으로
  쪼갠 뒤 generate_moves 에 넘긴다; tested_core 는 실제 탐침된 hard-core 식별자로 공급.
  (대안: _probe_moves 안에서 토큰화.) → 가정 N개면 PROBE N개(억제 시 N-1).

negative oracle(guard_defect) = test_heuristic_view_emits_per_assumption_probes:
  실 production caller(heuristic_view)를 다중 가정 hard_core 문자열로 구동 → 가정마다 PROBE 가
  나와야 한다(전체 blob target 금지). 오늘은 blob 1개 → RED.
mechanism oracle(guard_mechanism) = test_probe_moves_suppression_works_on_tokenized_input:
  _probe_moves 는 *토큰화된* 입력엔 억제가 동작함을 증명(메커니즘 존재) — production 배선만 굶주림.

xfail(strict) until fixed (lakatos/programme/heuristic.py:146 / server/contexts/tree/programme_service.py:184-189).
"""
from __future__ import annotations

import pytest

from lakatos.programme.heuristic import MOVE_PROBE, _probe_moves
from server.contexts.tree.programme_service import ProgrammeService


# 다중 가정 hard core (judgement_service 가 토큰화하는 바로 그 ';'-구분 free-text 형태).
ASSUMPTIONS = ("물리는 결정론적이다", "에너지는 보존된다", "정보는 손실되지 않는다")
HARD_CORE_BLOB = "; ".join(ASSUMPTIONS)

# 정본(CANONICAL) leaf 1개 — branch_inputs 가 leaf 를 잡고 tested(metric_name) 를 채우게 한다.
_TD = dict(
    name="T",
    hard_core=HARD_CORE_BLOB,
    nodes=[dict(tag="canon", verdict="CANONICAL", parent=None, parents=[],
                metric_name="accuracy", metric_value=None, pred_baseline=None,
                pred_noise_band=None, novel_registered=False, questions=[])],
    frontier=[],
)


def _service() -> ProgrammeService:
    # heuristic_view 는 tree_data + compute_metrics + branch_stack(=tree_data+branch_inputs) 만 탄다.
    # 나머지 포트는 이 경로에서 호출되지 않으므로 더미로 충족(실 production 코드 경로는 그대로).
    _unused = lambda *a, **k: None
    return ProgrammeService(
        kg=_unused, hist=_unused, pg=_unused,
        tree_data=lambda n: _TD,
        compute_metrics=lambda td: {"bayes": {"canonical_credence": 0.6}},
        add_node=_unused, register_prediction=_unused, submit_test_result=_unused,
        add_critique=_unused, standing=_unused, insert_artifact=_unused,
    )


# [FIXED 2026-06-27] #5 — green regression (heuristic_view tokenizes hard_core → per-assumption PROBE)
def test_heuristic_view_emits_per_assumption_probes():
    plan = _service().heuristic_view("T")
    probes = [m for m in plan["moves"] if m["kind"] == MOVE_PROBE]

    # 사전조건: 실제로 production 경로를 탔고 PROBE 가 생성됐다.
    assert probes, "PROBE move 가 전혀 없음 — production 경로 미도달"

    # (fix 후) 올바른 동작: 가정마다 PROBE 1개. 전체 blob 문자열이 target 으로 새면 안 된다.
    targets = {p["target"] for p in probes}
    assert HARD_CORE_BLOB not in targets, (
        f"hard_core 전체 blob 이 통째 PROBE target 으로 샜다(토큰화 안 됨): {targets!r}")
    assert len(probes) == len(ASSUMPTIONS), (
        f"가정 {len(ASSUMPTIONS)}개면 PROBE {len(ASSUMPTIONS)}개여야 하는데 {len(probes)}개")
    assert set(ASSUMPTIONS) <= targets


def test_probe_moves_suppression_works_on_tokenized_input():
    # 메커니즘 positive oracle: _probe_moves 는 *토큰화된* hard_core 엔 억제(N-1)가 동작한다 —
    # 즉 버그는 함수가 아니라 production 배선(blob 주입)이다. (오늘도 PASS — xfail 아님.)
    moves = _probe_moves(tuple(ASSUMPTIONS), (ASSUMPTIONS[1],))  # 가운데 가정 이미 탐침됨
    targets = {m["target"] for m in moves}
    assert len(moves) == len(ASSUMPTIONS) - 1     # 정확히 1개 억제
    assert ASSUMPTIONS[1] not in targets          # 탐침된 그 가정만 제외
    assert targets == {ASSUMPTIONS[0], ASSUMPTIONS[2]}
