"""c1verify — External Certificate Verifier for LakatoTree (campaign C1, slice S0 skeleton).

The whole point: an OUTSIDER who imports ZERO lakatos/server code re-verifies a lakatotree
Certificate from a self-contained, content-sealed bundle. Today the engine's certificate carries
only POINTERS (paths, endpoint URLs, node properties, comma-joined output sets); an outsider must
TRUST the engine. c1verify replaces that trust with re-derivation: each gate reduces to a total,
FAIL-CLOSED pure function over bundle bytes. Anything not fully re-derivable => REJECT — never trust.

S0 (this slice) is the fail-closed SKELETON: a strict typed JCS parser that defaults to REJECT
(empty ACCEPT set) with ZERO gate logic. Gate reverification (grounded, reproducible, preregistered,
substrate, stands, calibrated) lands slice by slice (S1..S9). Until a gate is implemented it stays
REJECT with reason 'not implemented'. certified is True ONLY when every gate ACCEPTs — impossible
in the skeleton, which is the correct honest behaviour.

Trust base = stdlib only. Zero lakatos/server import (import-linter + clean-venv CI + subprocess guard).
"""
from .core import C1_BUNDLE_VERSION, GATES, ACCEPT, REJECT, verify
from . import jcs

__all__ = ["verify", "GATES", "ACCEPT", "REJECT", "C1_BUNDLE_VERSION", "jcs"]
