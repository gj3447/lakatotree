"""설계감사 M9 — 외부 readback positive 왕복을 *항상 ON* + actor 분리로 고정.

결함(oo_verify.py:27-29 저자 TODO): 모든 oo/marquez 테스트가 opener 를 주입해 *같은
프로세스가 만든 hand-crafted hits* 를 대조한다(영수증 연극). write→독립 read→compare 의
positive 왕복이 lakatos 경로 어디에도 없고, 유일한 실네트워크 테스트는 기본 OFF + 부정경로
(bogus cid)만. → 외부 영수증의 신뢰가 (테스트 환경에서) 자기응답으로 닫힐 수 있다.

처방(같은 repo 의 부분 정답을 lakatos 경로로 확장): `ooptdd.backends.conformance.
assert_backend_conforms` 는 ship→독립 query→compare 의 *진짜* 왕복을 하고 drop=True(이벤트
누락)면 RED 가 된다. 그 패턴을 oo 의 ship/verify 경로로 차용 — 단 producer 가 만든 응답을
*그 producer 가* 대조하지 않도록 reader 를 producer 와 *구조적으로 분리*(Pact: 기대 적는
자 ≠ 확인하는 자). reader 는 crafted echo 가 아니라 producer 가 *실제로 쓴 store* 를 읽는다.

경계: LTDD trace 적재 검증(관측)이라 verdict 본체가 아님 → medium. 본체 게이트는 안 만진다.
# KG: span_lakatotree_oo_sink / span_lakatotree_marquez_sink
"""
import pytest

from lakatos.io import oo_verify


def test_external_readback_positive_roundtrip_ci():
    """oo 경로 write→*독립* read→compare 의 positive 왕복이 (env 없이) 항상 검증되고,
    이벤트를 1개 drop 하면 RED(왕복 실패 감지)가 된다.

    핵심(M9 해소): reader 는 producer 가 만든 hand-crafted hits 를 echo 하지 않는다 —
    producer(oo_sink.ship 의 writer opener)가 *실제로 쓴 store* 를 reader(verify_trace 의
    reader opener)가 독립적으로 읽어 대조한다. 두 opener 는 서로 다른 객체(actor 분리)이며,
    오직 공유 store 를 통해서만 정보가 흐른다 → 자기응답이 구조적으로 불가능.
    """
    # ── positive: 진짜 ship → 독립 read → compare 의 왕복이 GREEN ──────────────
    #   producer 와 reader 가 *분리*돼 있음을 구조적으로 강제(assert_positive_roundtrip 가
    #   writer/reader opener 동일성을 거부)하고, store 를 통해서만 정보가 흐른다.
    v = oo_verify.assert_positive_roundtrip(cid='m9-roundtrip-cid', expect_total=3)
    assert v['ok'] is True, f'정상 ship 의 positive 왕복은 GREEN 이어야 한다: {v}'
    assert v['outcomes'] == 3 and v['reasons'] == []
    assert v['session'].get('total') == 3

    # ── 음성(RED-with-teeth): test_session 이벤트를 1개 drop → 독립 reader 가 못 읽음 → RED ──
    #   2026-06-09 22h 미감지 그 silent ingest loss 실패모드. 왕복이 진짜 이빨이 있음을 증명.
    with pytest.raises(AssertionError, match='round-trip lost|미도착|no_test_session'):
        oo_verify.assert_positive_roundtrip(
            cid='m9-roundtrip-drop', expect_total=3, drop_event='test_session')


def test_roundtrip_reader_is_not_the_producer():
    """actor 분리의 구조적 강제: writer opener 와 reader opener 가 *같은 객체*면 거부.

    Pact 식 consumer-driven contract — 기대를 적는 자(producer)와 확인하는 자(reader)가
    동일하면 '영수증 연극'이 가능하므로, 같은 opener 를 쓰려는 시도를 fail-loud 로 막는다.
    (이 가드가 미래 회귀 — opener 하나로 ship+verify 를 둘 다 태우는 자기응답 — 를 차단.)
    """
    store = oo_verify.OoRoundtripStore()
    same = store.opener()
    with pytest.raises(ValueError, match='writer.*reader|동일|same'):
        oo_verify._roundtrip(cid='c', expect_total=1, writer=same, reader=same)
