"""OOPTDD emit-adapter — LakatoTree 판정엔진 감사 finding D(VoI/positive-heuristic 부활)를
*구조화 이벤트 trace*(R02)로 영수증화.

규율(ooptdd): 이벤트 리터럴은 엔진이 아니라 이 adapter 에만(엔진 explore/heuristic 은 불변).
verify 가 실제 lakatos.programme.explore.rank_questions / heuristic.expected_progress_gain / _question_moves 를
*구동*해:
  ① D2 정직: cost 모델 부재(None)면 숫자 VoI를 발행하지 않고 gain×UCB fallback을 명시
  ② D1 파생 실재: expected_progress_gain 이 정본 전선(momentum)·문제압(pressure)·novel 로 차등 —
     shadowed 0.1 하드코딩이 아니라 구조 도출값(전선 질문 > 전선 밖 질문)
  ③ D4 gating: PG_NOVEL(최대 항)은 등록 novelty 또는 완전 spec(metric∧direction∧threshold)에만 — mere-field Goodhart 봉합
을 구조화 이벤트로 ship.

음성 오라클(no-fake-green): D2 에서 cost 미측정인데 숫자 VoI가 나오거나, D1 에서 전선
질문이 전선 밖 질문과 동률이거나(파생 미발화 = 옛 0.1 하드코딩), D4 에서 bare-field 가 full-spec 과 동률이면
(Goodhart 미봉합) verify assert 가 깨진다. 즉 어느 결함이든 살아있으면 *틀린다*.

참고 테스트: lakatotree/tests/test_voi_positive_heuristic_20260713.py.
# KG: lakatotree-judge-engine-audit finding D / voi-positive-heuristic-2026-07-12
"""
import sys

_LKT = __import__("pathlib").Path(__file__).resolve().parents[2].as_posix()
if _LKT not in sys.path:
    sys.path.insert(0, _LKT)

from lakatos.programme.explore import rank_questions, voi  # noqa: E402
from lakatos.programme.heuristic import _question_moves, expected_progress_gain  # noqa: E402


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.programme.finding_D", "event": name, **attrs}


def verify(backend, cid):
    """finding D 구동 — 실제 voi / expected_progress_gain / _question_moves 로 정직·파생·gating 증언."""
    # (1) D2 정직: cost None = 비용모델 부재 → 숫자 VoI 없음, gain×UCB fallback을 공시.
    unmeasured = rank_questions([
        dict(name='q', expected_gain=0.3, cost=None, credence=0.5, n_visits=1)
    ], total_visits=1)[0]
    v_cost = voi(0.3, 3.0)
    assert unmeasured['voi'] is None, f"cost 부재인데 숫자 VoI 발행: {unmeasured['voi']}"
    assert unmeasured['cost_source'] == 'unmeasured'
    assert unmeasured['ranking_basis'] == 'expected_gain_x_ucb'
    assert round(v_cost, 4) == 0.1, f"client cost 정규화 미작동: voi(0.3,3.0)={v_cost}"
    backend.ship([_ev(cid, "voi_cost_honest", voi_no_cost=None,
                      fallback=unmeasured['ranking_basis'], voi_with_cost=round(v_cost, 4))])

    # (2) D1 파생 실재: 정본 전선(momentum) 질문 > 전선 밖 질문 — shadowed 0.1 하드코딩이면 동률.
    g_front = expected_progress_gain(canonical_credence=0.6, on_canonical_frontier=True, problem_pressure=0.0)
    g_off = expected_progress_gain(canonical_credence=0.6, on_canonical_frontier=False, problem_pressure=0.0)
    assert g_front > g_off, f"파생 미차등(옛 0.1 하드코딩 shadow?): front={g_front} off={g_off}"
    assert g_off != 0.1, f"파생이 하드코딩 0.1 로 붕괴: {g_off}"
    backend.ship([_ev(cid, "gain_derived_differentiates", front=g_front, off=g_off)])

    # (3) D4 gating: PG_NOVEL 은 완전 NovelTarget spec(metric∧direction∧threshold)에만 — mere-field 는 못 산다.
    nodes = [{"tag": "c", "verdict": "CANONICAL", "questions": []}]
    bare = _question_moves(nodes, [{"name": "q-bare", "novel_target": "x"}],
                           {"canonical_credence": 0.5}, 0.0, None)[0]["est_gain"]
    full = _question_moves(nodes, [{"name": "q-full", "novel_metric": "acc",
                                    "novel_direction": "higher", "novel_threshold": 0.9}],
                           {"canonical_credence": 0.5}, 0.0, None)[0]["est_gain"]
    assert full > bare, f"mere-field 가 full-spec 과 동률(Goodhart 미봉합): bare={bare} full={full}"
    backend.ship([_ev(cid, "novel_gating_closes_goodhart", bare=bare, full=full)])
