from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from server.contexts.tree.judgement_service import JudgementService


def _service(provider):
    return JudgementService(
        kg=lambda *_args, **_kwargs: [],
        kg_tx=lambda _ops: [],
        hist=lambda *_args, **_kwargs: None,
        foundation=lambda _name: None,
        reproducible_for_node=lambda _name, _tag: None,
        prediction_temporal_commitment_provider=provider,
    )


def test_legacy_prediction_row_does_not_call_temporal_provider():
    def forbidden_provider(_name, _tag):
        raise AssertionError("legacy node must not require a temporal snapshot")

    assert _service(forbidden_provider)._prediction_temporal_binding(
        "T", "n", {"pred_receipt_sha": "p" * 64}
    ) == (None, None)


def test_attached_temporal_commitment_must_be_available():
    service = _service(lambda _name, _tag: None)

    with pytest.raises(HTTPException, match="commitment is unavailable"):
        service._prediction_temporal_binding(
            "T",
            "n",
            {
                "pred_receipt_sha": "p" * 64,
                "prediction_temporal_commitment_count": 1,
            },
        )


def test_attached_temporal_commitment_seals_exact_hashes():
    commitment = SimpleNamespace(
        prediction_receipt_sha256="p" * 64,
        commitment_sha256="c" * 64,
        authority_policy_sha256="a" * 64,
    )
    service = _service(lambda _name, _tag: commitment)

    assert service._prediction_temporal_binding(
        "T",
        "n",
        {
            "pred_receipt_sha": "p" * 64,
            "prediction_temporal_commitment_count": 1,
        },
    ) == ("c" * 64, "a" * 64)


@pytest.mark.parametrize("count", [-1, 2, None, True])
def test_temporal_commitment_cardinality_must_be_exact(count):
    service = _service(lambda _name, _tag: None)

    with pytest.raises(HTTPException, match="cardinality is invalid"):
        service._prediction_temporal_binding(
            "T",
            "n",
            {
                "pred_receipt_sha": "p" * 64,
                "prediction_temporal_commitment_count": count,
            },
        )
