"""q-selfdev-budget-ratchet: cycle_budget raise needs confirm (+ write-cert if attestors)."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from server.contexts.tree.schemas import CreateTreeIn
from server.contexts.tree.service import TreeService
from lakatos.write_cert import (
    build_write_cert,
    did_key_encode,
    ed25519_public_key,
    operation_payload_sha256,
)


class _Svc(TreeService):
    """Minimal subclass — override tree_data without mutating frozen fields."""

    def __init__(self, *, budget=None, attestors=None, missing=False):
        object.__setattr__(self, "_budget", budget)
        object.__setattr__(self, "_att", list(attestors or []))
        object.__setattr__(self, "_missing", missing)
        # ports unused for gate unit
        object.__setattr__(self, "kg", None)
        object.__setattr__(self, "kg_tx", None)
        object.__setattr__(self, "hist", None)
        object.__setattr__(self, "pg", None)
        object.__setattr__(self, "repo", None)
        object.__setattr__(self, "validator", None)
        object.__setattr__(self, "mutations", None)

    def tree_data(self, name: str) -> dict:
        if self._missing:
            raise HTTPException(404, f"나무 없음: {name}")
        return {"cycle_budget": self._budget, "attestor_dids": self._att, "nodes": []}


def test_raise_without_confirm_is_409():
    svc = _Svc(budget=5)
    with pytest.raises(HTTPException) as e:
        svc._assert_budget_raise_gate("T", CreateTreeIn(cycle_budget=10))
    assert e.value.status_code == 409
    assert "confirm_budget_raise" in e.value.detail


def test_raise_with_confirm_ok_without_attestors():
    svc = _Svc(budget=5)
    svc._assert_budget_raise_gate("T", CreateTreeIn(cycle_budget=10, confirm_budget_raise=True))


def test_first_declare_and_new_tree_ok():
    _Svc(budget=None)._assert_budget_raise_gate("T", CreateTreeIn(cycle_budget=3))
    _Svc(missing=True)._assert_budget_raise_gate("NEW", CreateTreeIn(cycle_budget=3))


def test_lower_or_equal_ok():
    svc = _Svc(budget=10)
    svc._assert_budget_raise_gate("T", CreateTreeIn(cycle_budget=10))
    svc._assert_budget_raise_gate("T", CreateTreeIn(cycle_budget=4))


def test_raise_with_attestors_requires_write_cert():
    svc = _Svc(budget=1, attestors=["did:key:zTest"])
    with pytest.raises(HTTPException) as e:
        svc._assert_budget_raise_gate(
            "T", CreateTreeIn(cycle_budget=5, confirm_budget_raise=True))
    assert e.value.status_code == 403
    assert "write-cert" in e.value.detail


def test_budget_authorization_verifies_v4_cert_without_deciding_locked_policy():
    secret = bytes(range(32))
    did = did_key_encode(ed25519_public_key(secret))
    unsigned = CreateTreeIn(cycle_budget=5, confirm_budget_raise=True)
    verb = "create_tree.cycle_budget_raise"
    command = {
        "tree": "T",
        "tag": "__tree__",
        "prev_receipt_sha": None,
        "metric_value": None,
        "script_sha": None,
        "verb": verb,
        "command_version": "v4",
        "result_sha256": None,
        "operation_payload_sha256": operation_payload_sha256(
            verb, unsigned.model_dump(exclude={"write_cert"})
        ),
    }
    spec = CreateTreeIn(
        cycle_budget=5,
        confirm_budget_raise=True,
        write_cert=build_write_cert(secret, command),
    )

    confirmed, verified, snapshot = _Svc(
        budget=1, attestors=[did]
    )._budget_raise_authorization("T", spec)

    assert confirmed is True
    assert verified is True
    assert snapshot == (did,)
