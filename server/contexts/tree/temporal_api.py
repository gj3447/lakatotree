"""HTTP surface for immutable two-ended temporal proof adjuncts."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Path

from server.contexts.tree.schemas import (
    PredictionTemporalCommitmentIn,
    TemporalSidecarFinalizeIn,
)
from server.contexts.tree.temporal_service import TemporalProofService
from server.contexts.tree.temporal_proof import TemporalProofInvalid


_SHA_PATH = Path(pattern=r"^[0-9a-f]{64}$")


def _translate_invalid(call):
    try:
        return call()
    except TemporalProofInvalid as exc:
        raise HTTPException(422, f"temporal proof invalid: {exc}") from exc


def create_temporal_router(
    service_factory: Callable[[], TemporalProofService],
) -> APIRouter:
    router = APIRouter()

    @router.post(
        "/api/tree/{name}/node/{tag}/receipts/"
        "{prediction_receipt_sha256}/temporal-commitment"
    )
    def attach_prediction_temporal_commitment(
        name: str,
        tag: str,
        request: PredictionTemporalCommitmentIn,
        prediction_receipt_sha256: str = _SHA_PATH,
    ):
        return _translate_invalid(
            lambda: service_factory().attach_prediction_commitment(
                name,
                tag,
                request.prediction_anchors,
                expected_prediction_receipt_sha256=prediction_receipt_sha256,
            )
        )

    @router.post(
        "/api/tree/{name}/node/{tag}/receipts/"
        "{verdict_receipt_sha256}/temporal-sidecar"
    )
    def finalize_temporal_sidecar(
        name: str,
        tag: str,
        request: TemporalSidecarFinalizeIn,
        verdict_receipt_sha256: str = _SHA_PATH,
    ):
        return _translate_invalid(
            lambda: service_factory().finalize_sidecar(
                name,
                tag,
                request.verdict_anchors,
                expected_verdict_receipt_sha256=verdict_receipt_sha256,
            )
        )

    @router.get("/api/tree/{name}/node/{tag}/temporal-proof")
    def temporal_proof(name: str, tag: str):
        return _translate_invalid(
            lambda: service_factory().read_proof(name, tag).public_dict()
        )

    return router
