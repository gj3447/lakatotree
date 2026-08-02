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
        self.outboxes = {}

    def __call__(self, q, **p):
        if "RETURN t.ontology AS ontology, t.research_layout" in q:
            return [dict(self.tree, ontology=None, research_layout=None,
                         layout_owner_did=None, layout_sig=None)]
        if "RETURN e.current_receipt_sha AS prev_rsha" in q:
            return [{
                "prev_rsha": self.node.get("current_receipt_sha"),
                "pred_receipt_sha": self.node.get("pred_receipt_sha"),
                "pred_registered_at": self.node.get("pred_registered_at"),
                "pred_prev_receipt_sha": self.node.get("pred_prev_receipt_sha"),
                "pred_baseline_lineage": self.node.get("baseline_lineage"),
                "pred_anchor_bundle_sha256": self.node.get("anchor_bundle_sha256"),
                "pred_anchor_bundle_json": self.node.get("anchor_bundle_json"),
                "pred_history_payload_sha256": self.node.get("history_payload_sha256"),
                "pred_history_payload": (
                    self.outboxes.get(
                        f"ob-prediction-register-{self.node.get('pred_receipt_sha')}", {}
                    ).get("payload")
                ),
                "pred_anchor_verified": self.node.get("pred_anchor_verified"),
            }]
        if "MATCH (o:OutboxEntry {id:$id})" in q:
            row = self.outboxes.get(p["id"])
            return [dict(row)] if row is not None else []
        self.writes.append(q)
        if "SET e.pred_metric=$metric_name" in q:
            self.node.update(pred_metric=p["metric_name"], pred_registered_at=p["ts"],
                             node_state="PREDICTED", current_receipt_sha=p["rsha"],
                             pred_receipt_sha=p["rsha"],
                             pred_prev_receipt_sha=p.get("prev_rsha"),
                             baseline_lineage=p["baseline_lineage"],
                             anchor_bundle_sha256=p.get("anchor_bundle_sha256"),
                             anchor_bundle_json=p.get("anchor_bundle_json"),
                             history_payload_sha256=p.get("prediction_payload_sha256"))
            if p.get("anchor_rows"):
                self.node.update(
                    pred_anchor_verified=True,
                    pred_anchor_gen_time=p.get("anchor_gen_time"),
                    pred_anchor_quorum=p.get("anchor_quorum"),
                    pred_anchor_threshold=p.get("anchor_threshold"),
                )
            self.outboxes[p["history_event_id"]] = {
                "id": p["history_event_id"],
                "tree": p["tree"],
                "op": "prediction_register",
                "node_tag": p["tag"],
                "payload": p["history_payload_json"],
                "status": "pending",
                "created_at": p["ts"],
                "reason": "prediction_register_commit_intent",
                "applied_at": None,
                "receipt_sha": p["rsha"],
            }
            return [{"tag": "n"}]
        if "e.pred_anchor_verified=true" in q:
            self.node.update(pred_anchor_verified=True, pred_anchor_gen_time=p["gt"])
        return []

    def tx(self, ops):
        return [[] for _ in ops]


def _svc(kg, hist=None):
    return JudgementService(kg=kg, kg_tx=kg.tx, hist=hist or (lambda *a, **k: None),
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


def test_anchor_without_declared_witnesses_is_rejected_before_registration():
    kg = _Kg()
    kg.tree["witness_dids"] = []
    base = PredictionIn(
        metric_name="m", direction="lower", baseline_value=1.0, noise_band=0.0
    )
    digest = spec_digest({
        key: value
        for key, value in base.model_dump().items()
        if key not in ("write_cert", "temporal_anchor", "temporal_anchors")
    })
    anchored = base.model_copy(update={
        "temporal_anchor": _anchor_over(
            base, digest, "2026-07-23T06:00:00+00:00"
        )
    })

    with pytest.raises(Exception) as error:
        _svc(kg).register_prediction("T", "n", anchored)

    assert getattr(error.value, "status_code", None) == 422
    assert kg.node.get("pred_registered_at") is None
    assert kg.outboxes == {}


def test_corrupt_witness_threshold_is_rejected_even_without_anchors():
    kg = _Kg()
    kg.tree["witness_threshold"] = -1

    with pytest.raises(Exception) as error:
        _svc(kg).register_prediction(
            "T",
            "n",
            PredictionIn(metric_name="m", baseline_value=1.0),
        )

    assert getattr(error.value, "status_code", None) == 500
    assert kg.node.get("pred_registered_at") is None
    assert kg.outboxes == {}


def test_single_and_list_anchor_surfaces_are_mutually_exclusive():
    with pytest.raises(ValueError, match="mutually exclusive"):
        PredictionIn(
            metric_name="m",
            baseline_value=1.0,
            temporal_anchor={"witness_did": "one"},
            temporal_anchors=[],
        )


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


def test_anchor_receipt_marker_and_history_intent_are_one_registration_write():
    kg = _Kg()
    base = PredictionIn(
        metric_name="m", direction="lower", baseline_value=1.0, noise_band=0.0
    )
    sd = {
        k: v for k, v in base.model_dump().items()
        if k not in ("write_cert", "temporal_anchor", "temporal_anchors")
    }
    good = _anchor_over(base, spec_digest(sd), "2026-07-23T06:00:00+00:00")

    _svc(kg).register_prediction(
        "T", "n", base.model_copy(update={"temporal_anchor": good})
    )

    registration = [q for q in kg.writes if "SET e.pred_metric=$metric_name" in q]
    assert len(registration) == 1
    assert "MERGE (rec:VerdictReceipt" in registration[0]
    assert "MERGE (an:TemporalAnchor {id:anchor.id})" in registration[0]
    assert "MERGE (o:OutboxEntry" in registration[0]
    assert "SET e.pred_anchor_verified=true" in registration[0]


def test_post_commit_history_crash_retries_from_sealed_anchor_bundle():
    kg = _Kg()
    base = PredictionIn(
        metric_name="m", direction="lower", baseline_value=1.0, noise_band=0.0
    )
    sd = {
        k: v for k, v in base.model_dump().items()
        if k not in ("write_cert", "temporal_anchor", "temporal_anchors")
    }
    prediction = base.model_copy(update={
        "temporal_anchor": _anchor_over(
            base, spec_digest(sd), "2026-07-23T06:00:00+00:00"
        )
    })
    calls = []

    def crash_once(*args, **kwargs):
        calls.append((args, kwargs))
        if len(calls) == 1:
            raise RuntimeError("history projection crash")

    svc = _svc(kg, hist=crash_once)
    with pytest.raises(RuntimeError, match="history projection crash"):
        svc.register_prediction("T", "n", prediction)
    assert kg.node.get("pred_anchor_verified") is True

    retried = svc.register_prediction("T", "n", prediction)
    assert retried["idempotent"] is True
    assert retried["pred_anchor_verified"] is True
    assert calls[0][1]["event_id"] == calls[1][1]["event_id"]


def test_changed_anchor_is_not_an_exact_prediction_retry():
    kg = _Kg()
    base = PredictionIn(
        metric_name="m", direction="lower", baseline_value=1.0, noise_band=0.0
    )
    sd = {
        k: v for k, v in base.model_dump().items()
        if k not in ("write_cert", "temporal_anchor", "temporal_anchors")
    }
    digest = spec_digest(sd)
    first = base.model_copy(update={
        "temporal_anchor": _anchor_over(
            base, digest, "2026-07-23T06:00:00+00:00"
        )
    })
    changed = base.model_copy(update={
        "temporal_anchor": _anchor_over(
            base, digest, "2026-07-23T06:00:01+00:00"
        )
    })
    svc = _svc(kg)
    svc.register_prediction("T", "n", first)

    with pytest.raises(Exception) as exc:
        svc.register_prediction("T", "n", changed)
    assert getattr(exc.value, "status_code", None) == 409
