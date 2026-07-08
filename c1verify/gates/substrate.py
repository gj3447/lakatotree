"""substrate gate reverifier (C1 S3) — re-derive receipt integrity from sealed bytes, don't trust.

The engine content-addresses every verdict (:VerdictReceipt seals 13 fields as sha256(header+JCS)).
This gate re-checks that integrity with zero engine import: recompute every receipt's content-sha and
match its claimed receipt_sha (tampering dies here), then fold the chain head->genesis (dangling /
broken / cyclic dies here). A real receipt at the head is required (fail-closed on a legacy/empty chain).

Enumerated residual (never discharged): issuer AUTHENTICITY. Content-addressing proves the chain is
internally consistent and tamper-evident, NOT that a genuine issuer minted it — a dishonest issuer can
mint any content-consistent chain. Authenticity needs the Ed25519 write-cert signature (substrate-B;
the engine must persist signer_did+signature on the receipt at mint).
"""
from __future__ import annotations

from .._decision import ACCEPT, REJECT, gate_decision
from ..receipts import check_chain_integrity

GATE = "substrate"

_RESIDUAL = ("issuer AUTHENTICITY is out-of-band: content-addressing proves the chain is internally "
             "consistent and tamper-evident, NOT that a genuine issuer minted it (a dishonest issuer "
             "can mint any content-consistent chain). Authenticity needs the Ed25519 write-cert "
             "signature — substrate-B, which requires the engine to persist it on the receipt.")


def verify_substrate(payload, ctx) -> dict:
    """payload = bundle['gates']['substrate'] = {'chain': [receipt,...], 'head': '<sha>'}. Total, fail-closed."""
    if not isinstance(payload, dict):
        return gate_decision(GATE, REJECT, "substrate payload absent or not an object")
    fold, reason = check_chain_integrity(payload.get("chain"), payload.get("head"))
    if reason:
        return gate_decision(GATE, REJECT, reason)
    return gate_decision(GATE, ACCEPT,
                         f"receipt chain content-addressed + folded to genesis "
                         f"(verdict={fold['verdict']!r}, source={fold['verdict_source']!r})",
                         residual_trust_surface=_RESIDUAL)
