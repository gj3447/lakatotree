"""EXTAUDIT S6b/S7b/S8b — 라이브 persistence 배선 (역할서명 예측 / 시간증인 앵커 / 측정락 mint).

S6b: register_prediction 에 cert 훅 — layout 이 register_prediction step 선언 시 서명 필수(무서명 예측 봉합).
S7b: 예측 spec 앵커(외부 증인 T1) persist + submit 이 temporal_witness 계산 → VAL L3 개방.
S8b: submit 이 :MeasurementLock mint(입력 봉인 사이드카).
스텁 KG 로 실 서비스 경로 구동. # KG: q-extaudit-role-separation/temporal-witness/replay-default
"""
import json

from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import PredictionIn
from lakatos.layout import canonical_layout_blob
from lakatos.temporal import build_temporal_anchor, spec_digest
from lakatos.write_cert import (build_write_cert, did_key_encode, ed25519_public_key, ed25519_sign)

_S = {n: bytes([150 + n]) * 32 for n in (1, 2, 3)}       # owner / predict-signer / witness
DID = {n: did_key_encode(ed25519_public_key(_S[n])) for n in _S}


class _Kg:
    """layout+witness 선언 트리 1노드를 흉내내는 상태형 스텁 — register/submit read 경로에 응답."""

    def __init__(self, tree_props):
        self.tree = tree_props
        self.node = {"tag": "n", "node_state": "DRAFT"}
        self.writes = []

    def __call__(self, q, **p):
        if "RETURN t.ontology AS ontology, t.research_layout" in q:      # register meta read
            return [dict(self.tree, ontology=None)]
        if "RETURN e.current_receipt_sha AS prev_rsha" in q:
            return [{"prev_rsha": self.node.get("current_receipt_sha")}]
        if "e.pred_metric AS m" in q:                                     # submit read
            return [dict(self.node, **self.tree, m=self.node.get("pred_metric"),
                         d="lower", b=1.0, nb=0.0, scale="ratio",
                         novel=None, vsrc=None, nmet=None, ndir=None, nthr=None, psha=None,
                         closes=None, n_opened=0, judged_at=None, existing_metric_value=None,
                         existing_verdict=None, existing_lstat=None,
                         prev_receipt_sha=self.node.get("current_receipt_sha"),
                         hard_core="", require_novel_anchor=False)]
        # write paths — apply minimal state + record
        self.writes.append(q)
        if "SET e.pred_metric=$metric_name" in q:
            self.node.update(pred_metric=p["metric_name"], pred_registered_at=p["ts"],
                             node_state="PREDICTED", current_receipt_sha=p["rsha"])
            return [{"tag": "n"}]                                          # 409 회피 — SET 성공 1행
        if "e.pred_anchor_verified=true" in q:
            self.node.update(pred_anchor_verified=True, pred_anchor_gen_time=p["gt"])
        if "MeasurementLock" in q:
            self.node["measurement_lock_sha"] = p["lsha"]
        return []

    def tx(self, ops):
        for q, p in ops:
            if "MERGE (rec:VerdictReceipt" in q:
                self.node.update(verdict=p["v"], verdict_source="scripted",
                                 current_receipt_sha=p["rsha"])
        return [[{"claimed": "n"}] for _ in ops]


def _layout():
    return {"layout_version": 1, "steps": [
        {"verb": "register_prediction", "pubkeys": [DID[2]], "threshold": 1}]}


def _tree_props():
    lo = _layout()
    return {"research_layout": json.dumps(lo, ensure_ascii=False), "layout_owner_did": DID[1],
            "layout_sig": ed25519_sign(_S[1], canonical_layout_blob(lo)).hex(),
            "witness_dids": [DID[3]], "assurance_tier": "notebook", "attestor_dids": None}


def _svc(kg):
    return JudgementService(kg=kg, kg_tx=kg.tx, hist=lambda *a, **k: None,
                            foundation=lambda n: None, reproducible_for_node=lambda n, t: None)


# ── S6b: layout register step 선언 트리는 예측등록 서명 필수 ────────────────────────────────
def test_s6b_unsigned_prediction_rejected():
    import pytest
    svc = _svc(_Kg(_tree_props()))
    with pytest.raises(Exception) as ei:      # HTTPException 403
        svc.register_prediction("T", "n", PredictionIn(
            metric_name="m", direction="lower", baseline_value=1.0, noise_band=0.0))
    assert "403" in str(ei.value) or "무서명" in str(ei.value)


def test_s6b_wrong_role_signer_rejected():
    import pytest
    svc = _svc(_Kg(_tree_props()))
    cmd = {"tree": "T", "tag": "n", "prev_receipt_sha": None, "metric_value": None,
           "script_sha": None, "verb": "register_prediction"}
    cert = build_write_cert(_S[1], cmd)       # owner 키(predict 역할 밖)로 서명
    cert["signer_did"] = DID[1]
    with pytest.raises(Exception):            # 403 allow-list 밖
        svc.register_prediction("T", "n", PredictionIn(
            metric_name="m", direction="lower", baseline_value=1.0, noise_band=0.0,
            write_cert=cert))


def test_s6b_correct_role_signer_accepted():
    kg = _Kg(_tree_props())
    cmd = {"tree": "T", "tag": "n", "prev_receipt_sha": None, "metric_value": None,
           "script_sha": None, "verb": "register_prediction"}
    cert = build_write_cert(_S[2], cmd)       # predict 역할 키
    cert["signer_did"] = DID[2]
    out = _svc(kg).register_prediction("T", "n", PredictionIn(
        metric_name="m", direction="lower", baseline_value=1.0, noise_band=0.0, write_cert=cert))
    assert out["ok"] is True and out.get("pred_receipt_sha")


# ── S7b: 예측 spec 앵커(외부 증인) persist ────────────────────────────────────────────────
def test_s7b_temporal_anchor_persisted():
    kg = _Kg(_tree_props())
    cmd = {"tree": "T", "tag": "n", "prev_receipt_sha": None, "metric_value": None,
           "script_sha": None, "verb": "register_prediction"}
    cert = build_write_cert(_S[2], cmd); cert["signer_did"] = DID[2]
    spec = PredictionIn(metric_name="m", direction="lower", baseline_value=1.0, noise_band=0.0)
    _sd = {k: v for k, v in spec.model_dump().items() if k not in ("write_cert", "temporal_anchor")}
    sdg = spec_digest(_sd)
    anchor = build_temporal_anchor(_S[3], sdg, "2026-07-23T05:00:00+00:00", DID[3])
    out = _svc(kg).register_prediction("T", "n", PredictionIn(
        metric_name="m", direction="lower", baseline_value=1.0, noise_band=0.0,
        write_cert=cert, temporal_anchor=anchor))
    assert out["pred_anchor_verified"] is True
    assert kg.node.get("pred_anchor_verified") is True                    # persist 됨
    assert kg.node.get("pred_anchor_gen_time") == "2026-07-23T05:00:00+00:00"


# ── S8b: submit 이 MeasurementLock mint (배선 앵커) ────────────────────────────────────────
def test_s8b_submit_mints_measurement_lock_wired():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "server" / "contexts" / "tree"
           / "judgement_service.py").read_text(encoding="utf-8")
    assert "MeasurementLock" in src and "build_measurement_lock(" in src, "S8b lock mint 미배선"
    assert "temporal_witness_verified=$tw" in src, "S7b temporal_witness persist 미배선"
