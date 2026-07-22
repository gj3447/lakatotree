"""OOPTDD emit-adapter — EXTAUDIT S4(2026-07-23) 해석층 봉인을 구조화 이벤트 trace 로 영수증화.

규율(ooptdd): 이벤트 리터럴은 이 adapter 에만. verify 가 실제
lakatos.verdicts.canonical_receipt_blob/comment_seal_sha/comment_drift + fsck.fsck_node 를 *구동*해:
  ① v3 봉인 + v2/v1 carve-out 바이트동일 + strip 위조 검출
  ② c6 장르 드리프트가 fsck WARN 으로 뜨고, 불변/레거시는 침묵
을 구조화 이벤트로 ship.

음성 오라클(no-fake-green): v3 없이 v2 로 조용히 mint 되거나 드리프트가 침묵하면 assert 가 깨진다.
참고 테스트: lakatotree/tests/test_extaudit_comment_seal.py
# KG: LakatosTree_LakatoTree_SelfDev_20260612 / v23_extaudit_comment_seal
"""
import sys

_LKT = __import__("pathlib").Path(__file__).resolve().parents[2].as_posix()
if _LKT not in sys.path:
    sys.path.insert(0, _LKT)

from lakatos.verdicts import (canonical_receipt_blob, comment_drift, comment_seal_sha,   # noqa: E402
                              match_receipt_encoding, receipt_content_sha)


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.extaudit.comment_seal", "event": name, **attrs}


def _fields(**kw):
    base = dict(tree="t", tag="n", target_id=None, verdict="progressive", verdict_source="scripted",
                metric_name="m", metric_value=0.5, novel_confirmed=True, lakatos_status="progressive",
                judged_at="2026-07-23T00:00:00+00:00", judge_script_sha="j1", prev_receipt_sha=None,
                measurement_grade="server_regenerated", engine_rule_sha="e1")
    base.update(kw)
    return base


def verify(backend, cid):
    """해석층 봉인 구동 — v3 봉인·carve-out·위조검출·드리프트 발화 증언."""
    # (1) v3 봉인 + carve-out + strip 위조 검출.
    sealed = _fields(comment_sha=comment_seal_sha("판정 시점 코멘트"))
    blob3 = canonical_receipt_blob(sealed)
    blob2 = canonical_receipt_blob(_fields())
    assert blob3.startswith(b"verdict-receipt\x00v3\n"), blob3[:24]
    assert blob2.startswith(b"verdict-receipt\x00v2\n") and b"comment_sha" not in blob2, \
        "carve-out 붕괴 — comment_sha 부재인데 v2 바이트가 아님(기존 코퍼스 재유도 파괴)"
    sha3 = receipt_content_sha(sealed)
    stripped = dict(sealed, comment_sha=None)
    assert match_receipt_encoding(dict(sealed), sha3) == "current"
    assert match_receipt_encoding(stripped, sha3) is None, "strip 위조가 검출 안 됨"
    backend.ship([_ev(cid, "v3_seal_and_carveout_hold", sha3=sha3[:12],
                      v2_header=blob2[:20].decode("utf-8", "replace"))])

    # (2) 드리프트 발화 / 불변·레거시 침묵.
    from server.contexts.audit.fsck import fsck_node
    seal = comment_seal_sha("원본")
    drifted = {"tag": "n1", "verdict": "degenerating", "verdict_source": "scripted",
               "pred_registered_at": "x", "source_trust": 1.0, "assurance_tier_resolved": "anchored",
               "current_receipt_sha": "r1",
               "comment": "원본 + 사후 승리 서사", "comment_sha_at_verdict": seal}
    same = dict(drifted, comment="원본")
    legacy = {"tag": "n2", "verdict": "proof", "comment": "아무 코멘트"}
    ids_d = [f.check_id for f in fsck_node(drifted)]
    assert "COMMENT_DRIFT_AFTER_VERDICT" in ids_d, f"c6 장르 드리프트가 침묵: {ids_d}"
    assert "COMMENT_DRIFT_AFTER_VERDICT" not in [f.check_id for f in fsck_node(same)]
    assert comment_drift(legacy) is None, "봉인 이전 레거시가 반증 취급됨(부재≠반증 위반)"
    backend.ship([_ev(cid, "drift_flagged_legacy_held", drift_ids=ids_d)])
