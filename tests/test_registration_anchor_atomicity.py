"""등록 원자성 가드 (q-lkt-nonatomic-registration-anchor-20260723) — 앵커 422 가 등록을 소비하면 안 된다.

실측 결함(temporal 프로브 1차 실행, LakatoTree_TemporalWitnessProbe_20260723): register_prediction 이
① 등록 SET(kg write) → ② 앵커 정족수 검증 순서라, 앵커 무효로 422 나도 pred_registered_at 이 이미
소비돼 노드가 stuck(재등록 409). 어뷰징 면: 무효 앵커 반복 제출로 상대 노드를 소진시킬 수 있다.
계약: 검증은 쓰기보다 먼저 — 422 는 상태를 소비하지 않는다(validate-then-write).
# KG: q-lkt-nonatomic-registration-anchor-20260723
"""
import pytest

from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import PredictionIn
from lakatos.temporal import build_temporal_anchor, spec_digest
from lakatos.write_cert import did_key_encode, ed25519_public_key

_W = bytes([151]) * 32
WDID = did_key_encode(ed25519_public_key(_W))


class _Kg:
    """witness 선언 트리 + DRAFT 노드 — register read/write 경로 스텁 (live_wiring 장르)."""

    def __init__(self):
        self.tree = {"witness_dids": [WDID], "witness_threshold": None}
        self.node = {"tag": "n", "node_state": "DRAFT"}
        self.writes = []

    def __call__(self, q, **p):
        if "RETURN t.ontology AS ontology, t.research_layout" in q:
            return [dict(self.tree, ontology=None, research_layout=None,
                         layout_owner_did=None, layout_sig=None)]
        if "RETURN e.current_receipt_sha AS prev_rsha" in q:
            return [{"prev_rsha": self.node.get("current_receipt_sha")}]
        self.writes.append(q)
        if "SET e.pred_metric=$metric_name" in q:
            self.node.update(pred_metric=p["metric_name"], pred_registered_at=p["ts"],
                             node_state="PREDICTED", current_receipt_sha=p["rsha"])
            return [{"tag": "n"}]
        if "e.pred_anchor_verified=true" in q:
            self.node.update(pred_anchor_verified=True, pred_anchor_gen_time=p["gt"])
        return []

    def tx(self, ops):
        return [[] for _ in ops]


def _svc(kg):
    return JudgementService(kg=kg, kg_tx=kg.tx, hist=lambda *a, **k: None,
                            foundation=lambda n: None, reproducible_for_node=lambda n, t: None)


def _anchor_over(payload: PredictionIn, sha: str, gt: str) -> dict:
    return build_temporal_anchor(_W, sha, gt, WDID)


def test_invalid_anchor_does_not_consume_registration():
    """앵커 무효 422 → 노드는 미소비(pred_registered_at 부재) → 재등록 가능해야 한다."""
    kg = _Kg()
    svc = _svc(kg)
    spec = PredictionIn(metric_name="m", direction="lower", baseline_value=1.0, noise_band=0.0)
    bad = _anchor_over(spec, "다른-spec-다이제스트", "2026-07-23T06:00:00+00:00")
    with pytest.raises(Exception) as ei:                      # HTTPException 422 (정족수 무효)
        svc.register_prediction("T", "n", PredictionIn(
            metric_name="m", direction="lower", baseline_value=1.0, noise_band=0.0,
            temporal_anchor=bad))
    assert "422" in str(getattr(ei.value, "status_code", ei.value)) or "정족수" in str(ei.value)
    # ★원자성: 실패한 시도가 등록을 소비했으면 안 된다
    assert kg.node.get("pred_registered_at") is None, \
        "앵커 422 인데 등록이 소비됨 — validate-then-write 위반(노드 stuck)"
    # 후속 유효 등록은 성공해야 한다 (소비되지 않았으므로)
    sd = {k: v for k, v in spec.model_dump().items()
          if k not in ("write_cert", "temporal_anchor", "temporal_anchors")}
    good = _anchor_over(spec, spec_digest(sd), "2026-07-23T06:00:00+00:00")
    out = svc.register_prediction("T", "n", PredictionIn(
        metric_name="m", direction="lower", baseline_value=1.0, noise_band=0.0,
        temporal_anchor=good))
    assert out["ok"] is True and out["pred_anchor_verified"] is True


def test_valid_anchor_registration_still_works():
    """양성 통제: 유효 앵커 등록은 종전과 동일하게 성공 + persist."""
    kg = _Kg()
    spec = PredictionIn(metric_name="m", direction="lower", baseline_value=1.0, noise_band=0.0)
    sd = {k: v for k, v in spec.model_dump().items()
          if k not in ("write_cert", "temporal_anchor", "temporal_anchors")}
    good = _anchor_over(spec, spec_digest(sd), "2026-07-23T06:00:00+00:00")
    out = _svc(kg).register_prediction("T", "n", PredictionIn(
        metric_name="m", direction="lower", baseline_value=1.0, noise_band=0.0,
        temporal_anchor=good))
    assert out["pred_anchor_verified"] is True
    assert kg.node.get("pred_registered_at") is not None
