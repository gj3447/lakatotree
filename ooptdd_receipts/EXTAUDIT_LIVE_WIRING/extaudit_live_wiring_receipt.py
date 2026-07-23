"""OOPTDD emit-adapter — EXTAUDIT S6b/S7b/S8b(2026-07-23) 라이브 배선을 구조화 이벤트로 영수증화.

규율(ooptdd): 이벤트 리터럴은 이 adapter 에만. verify 가 실제 JudgementService.register_prediction
을 스텁 KG 로 *구동*해:
  ① S6b: 무서명/역할밖 예측 거부, 역할 내 서명 통과
  ② S7b: 유효 증인 앵커 persist(pred_anchor_verified), digest 밀반입 422
을 구조화 이벤트로 ship.

음성 오라클(no-fake-green): 무서명 예측이 통과하거나 앵커가 persist 안 되면 assert 가 깨진다.
참고 테스트: lakatotree/tests/test_extaudit_live_wiring.py
# KG: LakatosTree_LakatoTree_SelfDev_20260612 / v28_extaudit_live_wiring
"""
import json
import sys

_LKT = __import__("pathlib").Path(__file__).resolve().parents[2].as_posix()
if _LKT not in sys.path:
    sys.path.insert(0, _LKT)

from lakatos.layout import canonical_layout_blob                                   # noqa: E402
from lakatos.temporal import build_temporal_anchor, spec_digest                    # noqa: E402
from lakatos.write_cert import (build_write_cert, did_key_encode,                  # noqa: E402
                                ed25519_public_key, ed25519_sign)
from server.contexts.tree.judgement_service import JudgementService               # noqa: E402
from server.contexts.tree.schemas import PredictionIn                             # noqa: E402

_S = {n: bytes([180 + n]) * 32 for n in (1, 2, 3)}
DID = {n: did_key_encode(ed25519_public_key(_S[n])) for n in _S}


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.extaudit.live_wiring", "event": name, **attrs}


class _Kg:
    def __init__(self, tree):
        self.tree = tree
        self.node = {"tag": "n", "node_state": "DRAFT"}

    def __call__(self, q, **p):
        if "RETURN t.ontology AS ontology, t.research_layout" in q:
            return [dict(self.tree, ontology=None)]
        if "RETURN e.current_receipt_sha AS prev_rsha" in q:
            return [{"prev_rsha": self.node.get("current_receipt_sha")}]
        if "SET e.pred_metric=$metric_name" in q:
            self.node.update(current_receipt_sha=p["rsha"], node_state="PREDICTED")
            return [{"tag": "n"}]
        if "e.pred_anchor_verified=true" in q:
            self.node.update(pred_anchor_verified=True, pred_anchor_gen_time=p["gt"])
        return []

    def tx(self, ops):
        return [[{"claimed": "n"}] for _ in ops]


def _tree():
    lo = {"layout_version": 1, "steps": [
        {"verb": "register_prediction", "pubkeys": [DID[2]], "threshold": 1}]}
    return {"research_layout": json.dumps(lo, ensure_ascii=False), "layout_owner_did": DID[1],
            "layout_sig": ed25519_sign(_S[1], canonical_layout_blob(lo)).hex(),
            "witness_dids": [DID[3]], "assurance_tier": "notebook", "attestor_dids": None}


def _svc(kg):
    return JudgementService(kg=kg, kg_tx=kg.tx, hist=lambda *a, **k: None,
                            foundation=lambda n: None, reproducible_for_node=lambda n, t: None)


def _cert(sec, did, verb="register_prediction", script_sha=None):
    c = build_write_cert(sec, {"tree": "T", "tag": "n", "prev_receipt_sha": None,
                               "metric_value": None, "script_sha": script_sha, "verb": verb})
    c["signer_did"] = did
    return c


def verify(backend, cid):
    """라이브 배선 구동 — 예측서명 강제·앵커 persist 증언."""
    base = dict(metric_name="m", direction="lower", baseline_value=1.0, noise_band=0.0)

    # (1) S6b — 무서명 거부 / 역할밖 거부 / 역할내 통과.
    unsigned_rejected = wrong_rejected = right_ok = False
    try:
        _svc(_Kg(_tree())).register_prediction("T", "n", PredictionIn(**base))
    except Exception:
        unsigned_rejected = True
    try:
        _svc(_Kg(_tree())).register_prediction("T", "n", PredictionIn(
            **base, write_cert=_cert(_S[1], DID[1])))     # owner=역할밖
    except Exception:
        wrong_rejected = True
    out = _svc(_Kg(_tree())).register_prediction("T", "n", PredictionIn(
        **base, write_cert=_cert(_S[2], DID[2])))
    right_ok = bool(out.get("pred_receipt_sha"))
    assert unsigned_rejected and wrong_rejected and right_ok, \
        (unsigned_rejected, wrong_rejected, right_ok)
    backend.ship([_ev(cid, "register_cert_enforced", unsigned=unsigned_rejected,
                      wrong_role=wrong_rejected, right_role=right_ok)])

    # (2) S7b — 유효 앵커 persist / digest 밀반입 422.
    kg = _Kg(_tree())
    spec = PredictionIn(**base)
    sd = {k: v for k, v in spec.model_dump().items() if k not in ("write_cert", "temporal_anchor", "temporal_anchors")}
    good = build_temporal_anchor(_S[3], spec_digest(sd), "2026-07-23T07:00:00+00:00", DID[3])
    out2 = _svc(kg).register_prediction("T", "n", PredictionIn(
        **base, write_cert=_cert(_S[2], DID[2]), temporal_anchor=good))
    assert out2.get("pred_anchor_verified") is True and kg.node.get("pred_anchor_verified") is True
    smuggled = build_temporal_anchor(_S[3], spec_digest({"other": 1}), "2026-07-23T07:00:00+00:00", DID[3])
    smuggle_rejected = False
    try:
        _svc(_Kg(_tree())).register_prediction("T", "n", PredictionIn(
            **base, write_cert=_cert(_S[2], DID[2]), temporal_anchor=smuggled))
    except Exception:
        smuggle_rejected = True
    assert smuggle_rejected, "digest 밀반입 앵커가 통과(밀반입 봉쇄 실패)"
    backend.ship([_ev(cid, "temporal_anchor_persisted",
                      gen_time=kg.node.get("pred_anchor_gen_time"), smuggle_rejected=smuggle_rejected)])
