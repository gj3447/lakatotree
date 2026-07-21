"""OOPTDD emit-adapter — LakatoTree 파이드나 재감사(2026-07-21) 영수증 게이트를 구조화 이벤트 trace 로 영수증화.

규율(ooptdd): 이벤트 리터럴은 엔진이 아니라 이 adapter 에만(엔진 lakatos/verdicts.py·quant/metrics.py 불변).
verify 가 실제 lakatos.verdicts.force_of_row / lakatos.quant.metrics.tree_metrics 를 *구동*해:
  ① FORCEFUL 라벨인데 current_receipt_sha present-but-empty → INCONCLUSIVE(라벨-only COUNTS 아님)
  ② tree_metrics 가 영수증 없는 forceful 노드를 fertility credit 서 제외(novel_confirmed 무력화)
  ③ replay_status='mismatch' standing 노드도 fertility credit 서 제외
  ④ 영수증 있고 verified 인 clean 노드는 여전히 credit(이중가드 — vacuous-zero 아님)
을 구조화 이벤트로 ship.

음성 오라클(no-fake-green): force_of 가 verdict_source *라벨*만 보던 옛 거동(receipt 미확인)이 살아있었다면
①의 force_of_row(...)=='COUNTS' 라 첫 assert 가 깨지고, ②/③에서 confirmed 가 부풀어 assert 가 깨진다.
즉 이 영수증은 결함이 살아있으면 *틀린다*. Longinus 바인딩(R10): 이 emit site(verify)가 must_emit 을 낸다.

참고 테스트: lakatotree/tests/test_receipt_gated_credit_20260721.py
# KG: project_lakatotree_pidna_fidelity_reaudit_2026_07_21
"""
import sys

_LKT = __import__("pathlib").Path(__file__).resolve().parents[2].as_posix()
if _LKT not in sys.path:
    sys.path.insert(0, _LKT)

from lakatos.verdicts import force_of_row          # noqa: E402
from lakatos.quant.metrics import tree_metrics     # noqa: E402


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.pidna_reaudit.receipt_gated_credit", "event": name, **attrs}


def _node(tag, **kw):
    base = dict(tag=tag, parent=None, verdict="progressive", verdict_source="scripted",
                novel_registered=True, novel_confirmed=True,
                metric_name="m", metric_value=1.0, metric_scope="s")
    base.update(kw)
    return base


def verify(backend, cid):
    """영수증 게이트 구동 — 실제 force_of_row / tree_metrics 로 강등·제외·이중가드 증언."""
    # (1) 음성 오라클: FORCEFUL 라벨 + current_receipt_sha present-but-empty → INCONCLUSIVE.
    #     옛 라벨-only force_of 가 살아있었다면 'COUNTS' 라 여기서 깨진다.
    f_none = force_of_row({"verdict": "progressive", "verdict_source": "scripted",
                           "current_receipt_sha": None})
    f_have = force_of_row({"verdict": "progressive", "verdict_source": "scripted",
                           "current_receipt_sha": "r1"})
    f_legacy = force_of_row({"verdict": "progressive", "verdict_source": "scripted"})   # 키 부재=신뢰
    assert f_none == "INCONCLUSIVE", f"receiptless forceful 은 강등돼야: {f_none}"
    assert f_have == "COUNTS", f"영수증 있으면 COUNTS: {f_have}"
    assert f_legacy == "COUNTS", f"키 부재(레거시/픽스처)는 신뢰 유지: {f_legacy}"
    backend.ship([_ev(cid, "forceful_without_receipt_inconclusive",
                      receiptless=f_none, receipted=f_have, legacy_absent=f_legacy)])

    # (2) receiptless-forceful 은 fertility credit 서 제외 — confirmed 는 clean 1 만.
    nodes2 = [_node("clean", current_receipt_sha="r1"),
              _node("nr1", current_receipt_sha=None),
              _node("nr2", current_receipt_sha=None)]
    m2 = tree_metrics(nodes2, [], None)["fertility"]
    assert m2["confirmed"] == 1, f"영수증 없는 forceful 이 credit 됨(옛 누출): {m2}"
    backend.ship([_ev(cid, "receiptless_excluded_from_fertility",
                      confirmed=m2["confirmed"], registered=m2["registered"])])

    # (3) replay_status='mismatch' standing 노드도 제외 — confirmed 는 clean 1 만.
    nodes3 = [_node("clean", current_receipt_sha="r1"),
              _node("refuted", current_receipt_sha="r2", replay_status="mismatch")]
    m3 = tree_metrics(nodes3, [], None)["fertility"]
    assert m3["confirmed"] == 1, f"측정 반증(mismatch) 노드가 credit 됨: {m3}"
    backend.ship([_ev(cid, "replay_refuted_excluded_from_fertility",
                      confirmed=m3["confirmed"])])

    # (4) 이중가드: 영수증 있고 verified 인 clean 노드는 여전히 credit(vacuous-zero 아님).
    m4 = tree_metrics([_node("clean", current_receipt_sha="r1", replay_status="verified")],
                      [], None)["fertility"]
    assert m4["confirmed"] == 1, f"clean 영수증 노드가 credit 안 됨(fix 가 vacuous?): {m4}"
    backend.ship([_ev(cid, "clean_receipted_still_credited", confirmed=m4["confirmed"])])

    # (5) 열매(fertility)를 리더보드→패러다임 경로에서도 receipt-gate — score_competitor 가 SSOT
    #     neutralize 를 거친다. 음성 오라클: 우회(옛 raw 호출)면 confirmed=9/fertility_lb≈0.7 로 새서 깨진다.
    from lakatos.programme.leaderboard import Competitor, score_competitor
    fake_fruit = [_node(f"n{i}", current_receipt_sha=None) for i in range(9)]
    real_fruit = [_node(f"n{i}", current_receipt_sha=f"r{i}") for i in range(9)]
    verdicts = [{"verdict": "progressive", "delta": -0.5, "noise_band": 0.05}] * 9
    s_fake = score_competitor(Competitor("receiptless", verdicts, fake_fruit, 27.0, 5, 1))
    s_real = score_competitor(Competitor("receipted", verdicts, real_fruit, 27.0, 5, 1))
    assert s_fake["fertility_raw"]["confirmed"] == 0, f"영수증 없는 열매가 리더보드서 credit 됨: {s_fake}"
    assert s_fake["fertility_lb"] == 0.0, f"가짜 열매가 fertility_lb 부풀림(kuhn 오염): {s_fake}"
    assert s_real["fertility_raw"]["confirmed"] == 9, f"영수증 있는 열매가 credit 안 됨: {s_real}"
    backend.ship([_ev(cid, "leaderboard_fruit_receipt_gated",
                      fake_confirmed=s_fake["fertility_raw"]["confirmed"],
                      fake_fertility_lb=s_fake["fertility_lb"],
                      real_confirmed=s_real["fertility_raw"]["confirmed"])])
