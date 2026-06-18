"""HALCON 3D 검사 프로그램 도그푸드 — 인터넷 리서치가 라카토스 트리로 녹은 결과 박제.

★핵심: verdict 는 엔진이 *생성*한다(노드 손입력 0). 수치는 전부 fixture grounded(레코드 id 추적).
import 층(인터넷 증거 G-Web)과 프로그램 층(judge→pnr→spine)이 한 트리에서 만난다.
"""
from __future__ import annotations

import examples.halcon3d_inspection_programme as prog


def _verdicts():
    return {r["tag"]: r for r in prog.run()}


# ── 도그푸드 규약: 노드는 verdict 를 손입력하지 않는다 ─────────────────────────────
def test_nodes_carry_no_handwritten_verdict():
    # HalconNode 어디에도 verdict 필드가 없다 — 엔진 생성만 인정(euler 규약).
    fields = prog.HalconNode.__dataclass_fields__
    assert "verdict" not in fields and "status" not in fields
    # 모든 노드 수치가 fixture 레코드(_id)로 추적된다.
    assert all(n.source_record for n in prog.NODES)


# ── 엔진 생성 verdict 가 grounded 수치에서 라카토스 구조를 만든다 ────────────────────
def test_engine_generates_lakatos_programme_verdicts():
    v = _verdicts()
    # 핵 확립 root (채점 대상 아님)
    assert v["halcon_cad_programme"]["verdict"] == "canonical_stage"
    # 하드코어 확증: PPF recall 0.77 > 0.70, 새 사실 없음 → partial
    assert v["ppf_surface_match"]["verdict"] == "partial"
    assert v["ppf_surface_match"]["novel"] is False
    # ★progressive crown: frozen 변환(lemma-incorporation) + 미지 lot 새 사실 적중
    assert v["frozen_multiview_calib"]["verdict"] == "progressive"
    assert v["frozen_multiview_calib"]["novel"] is True
    assert v["frozen_multiview_calib"]["pnr_verdict"] == "progressive"


def test_free_gicp_is_rejected_global_counterexample():
    # 음의 휴리스틱이 금지하는 수 — free 6-DOF merge 가 0.93→2.78 mm 로 붕괴(전역 반례).
    v = _verdicts()["free_multiview_gicp"]
    assert v["metric_verdict"] == "rejected"
    assert v["verdict"] == "rejected"


def test_deep_learning_rival_is_different_programme_not_degenerating():
    # ★핵심 정직 구분: 라이벌은 P1 핵(CAD 결정론)을 *보존 안 함* → different_programme.
    # 이건 퇴행(belt 내용 비진보)이 아니라 정체성 축(다른 프로그램). MSRP 곡해 방지.
    v = _verdicts()["densefusion_rival"]
    assert v["pnr_verdict"] == "different_programme"
    assert v["verdict"] == "different_programme"
    # 메트릭상으론 YCB 에서 개선됨(95.30 > 90.0) — 그러나 핵 미보존이 판정을 가른다.
    assert v["metric_verdict"] == "partial"


# ── import 층: 인터넷 증거가 같은 트리에 G-Web 게이트로 녹는다 ─────────────────────
def test_internet_evidence_dissolves_into_same_tree():
    frame, rep = prog.dissolve_internet_evidence()
    # 11/12 인터넷 import(레코드 G = 인터넷 출처 0 → web_gate 거부, 프로그램 층 root 와 무관).
    assert rep["imported"] == 11
    assert rep["rejected"] == ["G"]
    assert rep["n_internet_events"] == 11
    # 트리 노드(가능성)가 import 로 생겼고 INTERNET 이벤트가 붙었다.
    assert len(frame.possibilities()) == 11
    assert all("internet" in frame.standing(p.name)["realms"] for p in frame.possibilities())


# ── 라이벌 regime 교차: 정직(누구도 반증 안 됨) ──────────────────────────────────
def test_rival_regime_crossover_is_honest_neither_refuted():
    x = prog.rival_regime_crossover()
    assert "neither_refuted" in x["verdict"]
    # 각 프로그램이 *서로 다른* regime 을 이긴다(한쪽 일방 승리 = 가짜).
    winners = {k: d["winner"] for k, d in x.items() if k != "verdict"}
    assert "P1_halcon_ppf" in winners.values()
    assert "P2_deep_learning" in winners.values()
