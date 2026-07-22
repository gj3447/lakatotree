"""OOPTDD emit-adapter — EXTAUDIT S1(2026-07-22) 측정등급 게이트를 구조화 이벤트 trace 로 영수증화.

규율(ooptdd): 이벤트 리터럴은 엔진이 아니라 이 adapter 에만(엔진 lakatos/verdicts.py·quant/metrics.py 불변).
verify 가 실제 lakatos.verdicts.force_of_row / lakatos.quant.metrics.tree_metrics 를 *구동*해:
  ① client_asserted ∧ replay!=verified → INCONCLUSIVE (라벨·포인터 다음의 세 번째 축 = 값의 소유)
  ② 양성 통제: server_regenerated/attested/키-부재 는 COUNTS 유지 (무회귀)
  ③ fertility 파급: 무검증 client 값 제외 + verified 된 client 값은 credit 유지 (인센티브 역전)
을 구조화 이벤트로 ship.

음성 오라클(no-fake-green): 옛 거동(client_asserted 가 'scripted' 라벨로 COUNTS)이 살아있었다면
①의 assert 가 'COUNTS' 를 보고 깨지고, ③에서 confirmed 가 부풀어 깨진다.

참고 테스트: lakatotree/tests/test_extaudit_grade_gate.py
# KG: LakatosTree_LakatoTree_SelfDev_20260612 / v19_extaudit_grade_gate
"""
import sys

_LKT = __import__("pathlib").Path(__file__).resolve().parents[2].as_posix()
if _LKT not in sys.path:
    sys.path.insert(0, _LKT)

from lakatos.verdicts import force_of_row          # noqa: E402
from lakatos.quant.metrics import tree_metrics     # noqa: E402


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.extaudit.grade_gate", "event": name, **attrs}


def _node(tag, **kw):
    base = dict(tag=tag, parent=None, verdict="progressive", verdict_source="scripted",
                novel_registered=True, novel_confirmed=True,
                metric_name="m", metric_value=1.0, metric_scope="s",
                current_receipt_sha="r-" + tag)
    base.update(kw)
    return base


def verify(backend, cid):
    """측정등급 게이트 구동 — 실제 force_of_row / tree_metrics 로 강등·무회귀·파급 증언."""
    # (1) 음성 오라클: client_asserted 무검증 → INCONCLUSIVE. 옛 라벨-only 면 'COUNTS' 라 여기서 깨진다.
    f_asserted = force_of_row({"verdict": "progressive", "verdict_source": "scripted",
                               "current_receipt_sha": "r1",
                               "measurement_grade": "client_asserted",
                               "replay_status": "not_attempted"})
    f_nokey = force_of_row({"verdict": "progressive", "verdict_source": "scripted",
                            "current_receipt_sha": "r1",
                            "measurement_grade": "client_asserted"})
    assert f_asserted == "INCONCLUSIVE", f"client_asserted 무검증이 credit 됨(옛 누출): {f_asserted}"
    assert f_nokey == "INCONCLUSIVE", f"replay_status 키 없어도 '검증됨' 아님: {f_nokey}"
    backend.ship([_ev(cid, "client_asserted_unreplayed_inconclusive",
                      unreplayed=f_asserted, no_replay_key=f_nokey)])

    # (2) 양성 통제 3종 — 강등이 과잉이면(전부 INCONCLUSIVE 로 뭉개면) 여기서 깨진다(vacuous-zero 방지).
    f_regen = force_of_row({"verdict": "progressive", "verdict_source": "scripted",
                            "current_receipt_sha": "r1",
                            "measurement_grade": "server_regenerated",
                            "replay_status": "verified"})
    f_attested = force_of_row({"verdict": "progressive", "verdict_source": "scripted",
                               "current_receipt_sha": "r1",
                               "measurement_grade": "attested",
                               "replay_status": "not_attempted"})
    f_legacy = force_of_row({"verdict": "progressive", "verdict_source": "scripted",
                             "current_receipt_sha": "r1"})
    assert f_regen == "COUNTS", f"server_regenerated 가 강등됨(과잉): {f_regen}"
    assert f_attested == "COUNTS", f"attested(서명) 가 강등됨(범위 초과): {f_attested}"
    assert f_legacy == "COUNTS", f"키 부재(레거시)가 강등됨(_SOURCE_ABSENT 계약 위반): {f_legacy}"
    backend.ship([_ev(cid, "grade_gate_positive_controls_hold",
                      regenerated=f_regen, attested=f_attested, legacy_absent=f_legacy)])

    # (3) 파급: fertility 가 무검증 client 값을 안 세고, verified 된 client 값은 센다(인센티브 역전).
    m_ex = tree_metrics([
        _node("clean", measurement_grade="server_regenerated", replay_status="verified"),
        _node("a1", measurement_grade="client_asserted", replay_status="not_attempted"),
        _node("a2", measurement_grade="client_asserted", replay_status="not_attempted"),
    ], [], None)["fertility"]
    m_keep = tree_metrics([
        _node("v", measurement_grade="client_asserted", replay_status="verified"),
    ], [], None)["fertility"]
    assert m_ex["confirmed"] == 1, f"무검증 client 값이 fertility credit 됨: {m_ex}"
    assert m_keep["confirmed"] == 1, f"verified 된 client 값이 credit 안 됨(과잉): {m_keep}"
    backend.ship([_ev(cid, "fertility_excludes_unverified_client_asserted",
                      excluded_confirmed=m_ex["confirmed"], verified_kept=m_keep["confirmed"])])
