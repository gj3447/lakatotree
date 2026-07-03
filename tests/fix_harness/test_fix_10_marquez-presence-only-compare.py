"""FIX-HARNESS #10 (P2 honesty): Marquez positive roundtrip 'compare' 가 presence-only.

finding id: #10 (M11 비대칭 절반만 닫힘)
locations:
  - lakatos/io/marquez_verify.py:68-75   MarquezRoundtripStore.reader_opener
      → readback 응답이 {present, count} 를 싣지만 count 는 비교에 쓰이지 않는다.
  - lakatos/io/marquez_verify.py:95-97    marquez_readback
      → present 만 보고 ok=True 를 돌려준다. read_back(=count) 는 보고만 하고 *대조 안 함*.
  - lakatos/io/marquez_verify.py:141-156  assert_positive_roundtrip
      → 결정은 `if not v.get("ok")` 뿐. read_back 을 n_events 와 비교하지 않는다.

the bug:
  M11 docstring 은 "실제 write→독립 read→compare 왕복" 을 광고한다. 그러나 compare 는
  *존재(presence)* 만 본다(ok = present). read_back/count 를 ship 한 n_events 와 결코
  비교하지 않는다. oo 경로(oo_verify.verify_trace:68-69)는 outcomes<expect_total 을
  _partial_loss(RED)로 잡지만, Marquez 는 안 잡는다. 따라서 3개 중 2개가 drop 되고
  1개만 남으면(부분 적재 유실) Marquez 왕복은 *여전히 GREEN* 으로 남는다 —
  '미도착=RED' 의 비대칭이 절반만 닫힌 상태.

the exact fix:
  marquez_readback/assert_positive_roundtrip 에서 read_back/count 를 n_events 와 비교하고
  partial-drop reason 을 추가해라(oo_verify 의 outcomes<expect_total 동형). 즉
  read_back != n_events 이면 ok=False / AssertionError.

xfail(strict) until fixed:
  아래 negative-oracle 은 *수정 후* 올바른 동작(부분 drop ⇒ 왕복 RED)을 단언한다. 오늘은
  presence-only 라 통과(GREEN)하므로 단언이 FAIL = 버그 존재. fix 가 들어오면 strict 가 trip.

hermetic: opener 주입(in-process Marquez 에뮬레이터)으로 네트워크/실자격증명 없음.
실 코드 경로 타격: 실제 marquez_sink.ship(writer opener) + 실제 marquez_readback(reader opener)
+ 실제 assert_positive_roundtrip 결정을 그대로 호출. 유일한 주입은 'Marquez 가 3개 중 1개만
ingest 하고 나머지를 silent drop' 한 상태를 모사하는 reader(oo 의 drop_event 동형).
# KG: span_lakatotree_marquez_sink / span_lakatotree_design_audit_20260625
"""
from __future__ import annotations

import pytest

from lakatos.io import marquez_verify


class _PartialLossStore(marquez_verify.MarquezRoundtripStore):
    """writer 는 ship 한 event 를 전부 저장하지만, reader 는 present=True 로 *일부만* 보고한다.

    Marquez 가 3개 중 1개만 ingest 하고 나머지는 silent drop 한 '부분 적재 유실' 을 모사.
    presence-only compare 는 여기서 GREEN 으로 남는다(버그). read_back 을 n_events 와 비교하면 RED.
    """

    def __init__(self, keep: int = 1) -> None:
        super().__init__()
        self._keep = keep

    def reader_opener(self):
        def _reader(request, timeout=None):   # noqa: ARG001
            run_id = marquez_verify._run_id_from_url(request.get_full_url())
            events = self._by_run.get(run_id, [])
            if not events:   # 전부 미도착 → 404(presence 도 못 잡는 케이스는 별도 가드에서)
                return marquez_verify._CannedResp(
                    {"present": False, "runId": run_id, "count": 0}, status=404)
            kept = min(self._keep, len(events))   # 부분: present 는 True, count < ship 수
            return marquez_verify._CannedResp(
                {"present": True, "runId": run_id, "count": kept}, status=200)
        return _reader


# ── negative oracle (defect axis): 부분 drop 은 왕복 RED 여야 한다 ──────────────────
# [FIXED 2026-06-27] #10 — green regression (assert_positive_roundtrip compares read_back to n_events)
def test_marquez_partial_drop_must_flag_loss(monkeypatch):
    # assert_positive_roundtrip 내부의 store 를 '부분 유실' 에뮬레이터로 교체(실 ship+readback 그대로).
    monkeypatch.setattr(marquez_verify, "MarquezRoundtripStore", lambda: _PartialLossStore(keep=1))

    # 3개 ship → reader 는 1개만 readback(2/3 silent drop). 사전조건: 부분 유실이 실제로 발생함을 고정.
    store = _PartialLossStore(keep=1)
    v_probe = marquez_verify._roundtrip(
        run_id="marquez-partial-probe", n_events=3,
        writer=store.writer_opener(), reader=store.reader_opener())
    assert v_probe["read_back"] == 1            # 독립 reader 가 1개만 읽음(부분 도착)
    assert v_probe["ok"] is True                # presence-only → 오늘은 ok=True (이게 버그의 핵심)

    # 올바른(fix 후) 동작: read_back(1) != n_events(3) 이면 왕복은 부분 유실로 RED 여야 한다.
    with pytest.raises(AssertionError):
        marquez_verify.assert_positive_roundtrip(run_id="marquez-partial-drop", n_events=3)


# ── mechanism oracle (positive): 완전 도착이면 왕복은 GREEN(왕복 메커니즘 존재) ──────────
def test_marquez_full_roundtrip_is_green():
    # 3개 ship → 3개 readback → ok=True, read_back==3. 오늘도 fix 후도 통과해야 하는 메커니즘 가드.
    v = marquez_verify.assert_positive_roundtrip(run_id="marquez-full-roundtrip", n_events=3)
    assert v["ok"] is True
    assert v["read_back"] == 3


# ── mechanism guard (presence tooth): 전부 drop 은 오늘도 잡힌다(비대칭 절반은 닫혀 있음) ──
def test_marquez_total_drop_is_caught():
    # ship 누락(전부 미도착) → 독립 reader 404 → AssertionError. presence-only 가 '전부 유실' 은 잡음.
    # 이 가드는 #10 의 '절반만 닫힘' 을 대조한다: 전부 drop=RED 인데 부분 drop=GREEN 인 비대칭.
    with pytest.raises(AssertionError):
        marquez_verify.assert_positive_roundtrip(run_id="marquez-total-drop", n_events=3, drop=True)
