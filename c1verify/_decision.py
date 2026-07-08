"""Decision vocabulary shared by the core and every gate reverifier.

Kept in its own module so gate reverifiers (c1verify.gates.*) and the core never import each other
(no cycle): both import from here. Stdlib only.
"""
from __future__ import annotations

ACCEPT = "ACCEPT"
REJECT = "REJECT"


def gate_decision(gate: str, decision: str, reason: str, residual_trust_surface=None) -> dict:
    """The one shape every gate returns. residual_trust_surface names what an ACCEPT does NOT
    discharge (hard core: residual surfaces are enumerated, never dropped); None on REJECT."""
    return {"gate": gate, "decision": decision, "reason": reason,
            "residual_trust_surface": residual_trust_surface}
