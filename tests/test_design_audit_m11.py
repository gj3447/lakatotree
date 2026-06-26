"""설계감사 M11(완성-후 적대감사 2026-06-26) — M9 의 외부 readback 왕복이 oo 백엔드에만, Marquez 는 누락.

결함: M9 수정(oo_verify.assert_positive_roundtrip)은 oo 경로에만 write→독립read→compare 왕복을 뒀다.
M9 발견이 *직접 인용한* 두 번째 백엔드 Marquez(marquez_sink.py)는 여전히 POST fire-and-forget —
send_openlineage_events_to_marquez 의 POST status 만 보고 독립 GET readback 이 없다('예외없음/200=배송됨'
= M9 가 닫으려던 바로 그 실패모드). 한 백엔드는 닫고 다른 백엔드는 연 비대칭.

수정: lakatos/io/marquez_verify.py — oo_verify 와 동형으로 *분리된* writer/reader opener(store 통해서만
정보 흐름, 자기응답 불가) + 독립 readback GET(/api/v1/jobs/runs/{runId}) + drop(silent loss) 이빨.
marquez ship→독립read→compare 의 positive 왕복을 항상 ON 으로 hermetic 하게 돈다(네트워크 불요).
# KG: span_lakatotree_design_audit_20260625
"""
from __future__ import annotations

import pytest

from lakatos.io import marquez_verify


def test_marquez_positive_roundtrip_independent_readback():
    """ship(writer opener)→ 독립 reader 가 GET readback 으로 run 실재 확인 → ok(영수증 연극 아님)."""
    v = marquez_verify.assert_positive_roundtrip(run_id="m11-roundtrip", n_events=3)
    assert v["ok"] is True
    assert v["read_back"] == 3, "독립 readback 이 ship 한 event 수를 못 읽음"


def test_marquez_roundtrip_drop_is_caught():
    """★이빨: ship 을 누락(silent ingest loss)시키면 독립 reader 가 못 읽어 AssertionError — fire-and-forget 봉쇄."""
    with pytest.raises(AssertionError):
        marquez_verify.assert_positive_roundtrip(run_id="m11-drop", n_events=3, drop=True)


def test_marquez_writer_reader_actor_separation():
    """writer==reader(같은 opener 객체)는 영수증 연극 — 구조적으로 거부(Pact actor 분리)."""
    store = marquez_verify.MarquezRoundtripStore()
    same = store.writer_opener()   # 동일 객체를 양측에 → writer is reader
    with pytest.raises(ValueError):
        marquez_verify._roundtrip(run_id="x", n_events=1, writer=same, reader=same)
