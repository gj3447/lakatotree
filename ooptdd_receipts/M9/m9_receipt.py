"""OOPTDD emit-adapter — LakatoTree 설계감사 M9(외부 readback positive 왕복 + actor 분리)를
*구조화 이벤트 trace*(R02)로 영수증화.

규율(ooptdd): 이벤트 리터럴은 엔진이 아니라 이 adapter 에만(엔진 lakatos/io/oo_verify.py 는 불변).
verify 가 실제 oo_verify.assert_positive_roundtrip / _roundtrip 를 *구동*(재구현 금지)하고, 관측한
사실을 구조화 이벤트로 ship. Longinus 바인딩(R10): 이 emit site(verify)가 must_emit 이벤트를 낸다.

음성 오라클(no-fake-green): 결함(영수증 연극 — producer 가 만든 crafted hits 를 그 producer 가
대조)이 있었다면 틀릴 케이스를 포함:
  (1) drop_event='test_session' → 독립 reader 가 못 읽어 AssertionError(silent ingest loss 의 이빨).
  (2) writer==reader opener → ValueError(자기응답/영수증 연극 구조적 차단).
둘 다 *예외가 나야* 정상이며, 안 나면 receipt 가 fail-loud 한다.
"""
import sys

_LKT = __import__("pathlib").Path(__file__).resolve().parents[2].as_posix()
if _LKT not in sys.path:
    sys.path.insert(0, _LKT)

from lakatos.io import oo_verify   # noqa: E402  (실제 고쳐진 모듈을 import — 재구현 아님)


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.M9", "event": name, **attrs}


def verify(backend, cid):
    """M9 구동 — write→*독립* read→compare 의 positive 왕복(항상 ON, actor 분리)을 실모듈로 구동.

    test_design_audit_m9.py 의 픽스처/패턴을 그대로 차용:
      - assert_positive_roundtrip(expect_total=3) 통과(positive 왕복 GREEN).
      - drop_event='test_session' → AssertionError(왕복 이빨, 잡기).
      - _roundtrip(writer==reader) → ValueError(자기응답 차단, 잡기).
    """
    # (1) positive: 진짜 ship → 독립 read → compare 의 왕복이 GREEN(env 없이 hermetic).
    #     producer(writer opener) ≠ reader opener 가 oo_verify 내부에서 구조적으로 강제됨.
    v = oo_verify.assert_positive_roundtrip(cid=cid + '-roundtrip', expect_total=3)
    assert v['ok'] is True, f'정상 ship 의 positive 왕복은 GREEN 이어야 한다: {v}'
    assert v['outcomes'] == 3 and v['reasons'] == [], v
    assert v['session'].get('total') == 3, v
    backend.ship([_ev(cid, "independent_roundtrip_ok",
                      outcomes=v['outcomes'], total=v['session'].get('total'),
                      records=v.get('records'), attempts=v.get('attempts'))])

    # (2) 음성 오라클#1(RED-with-teeth): test_session 이벤트 1개 drop → 독립 reader 가 못 읽음 → RED.
    #     2026-06-09 22h 미감지 그 silent ingest loss 실패모드. 왕복이 진짜 이빨이 있음을 증명.
    dropped_caught = False
    try:
        oo_verify.assert_positive_roundtrip(
            cid=cid + '-drop', expect_total=3, drop_event='test_session')
    except AssertionError as exc:
        msg = str(exc)
        # 결함이 있었다면(drop 을 reader 가 echo 로 메꿔주면) 이 단언이 틀림.
        assert ('round-trip lost' in msg or '미도착' in msg or 'no_test_session' in msg), msg
        dropped_caught = True
    assert dropped_caught, '음성 오라클 실패: test_session drop 이 RED 를 만들지 않음(영수증 연극 미차단)'
    backend.ship([_ev(cid, "drop_detected",
                      drop_event='test_session', raised='AssertionError')])

    # (3) 음성 오라클#2(추가 이빨): writer opener == reader opener → 자기응답 구조적 차단(ValueError).
    #     Pact actor 분리: 기대 적는 자(producer) ≠ 확인하는 자(reader). 같으면 거부돼야 함.
    store = oo_verify.OoRoundtripStore()
    same = store.opener()
    self_resp_blocked = False
    try:
        oo_verify._roundtrip(cid=cid + '-self', expect_total=1, writer=same, reader=same)
    except ValueError as exc:
        msg = str(exc)
        assert ('writer' in msg or '동일' in msg or 'same' in msg), msg
        self_resp_blocked = True
    assert self_resp_blocked, '음성 오라클 실패: writer==reader(자기응답)가 차단되지 않음'
    backend.ship([_ev(cid, "drop_detected",
                      guard='writer_eq_reader', raised='ValueError')])
