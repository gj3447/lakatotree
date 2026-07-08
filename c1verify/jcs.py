"""Strict canonical-JSON (JCS genre) codec — the ONLY parse surface of the verifier.

Byte-exact RE-IMPLEMENTATION of lakatos.write_cert._jcs (NOT an import — the external verifier
shares zero engine code; copy-fidelity is pinned by an out-of-band golden test in engine CI).

FAIL-CLOSED TOTALITY: parse_canonical(bytes) is total — it never returns a half-trusted value.
It RAISES JcsError on any doubt: not bytes, not utf-8, invalid JSON, non-finite numbers (NaN/Inf),
duplicate keys, non-object top level, or a non-canonical encoding (must round-trip byte-exact).
The caller turns any JcsError into an all-gates-REJECT report. There is no lenient branch.
"""
from __future__ import annotations

import json


class JcsError(ValueError):
    """Canonical-parse failure — any doubt raises; the caller REJECTs (fail-closed)."""


def jcs(obj) -> bytes:
    """Canonical bytes: sorted keys, minimal separators, no NaN/Inf, UTF-8.
    Byte-identical to lakatos.write_cert._jcs so a bundle canonicalised by the engine round-trips."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _reject_dup_keys(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise JcsError(f"duplicate object key {key!r} (fail-closed)")
        out[key] = value
    return out


def _reject_constant(token: str):
    raise JcsError(f"non-finite JSON constant {token!r} (fail-closed)")


def parse_canonical(data: bytes) -> dict:
    """bytes -> dict. Total & fail-closed (see module docstring). A well-formed bundle MUST be the
    canonical JCS encoding of its object; a merely-parseable-but-non-canonical byte string is
    REJECTED so a tampered/whitespace-padded bundle can never slip past as 'valid'."""
    if not isinstance(data, (bytes, bytearray)):
        raise JcsError(f"bundle is not bytes: {type(data).__name__}")
    if not data:
        raise JcsError("empty bundle")
    try:
        text = bytes(data).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise JcsError(f"bundle is not valid UTF-8: {exc}")
    try:
        obj = json.loads(text, object_pairs_hook=_reject_dup_keys,
                         parse_constant=_reject_constant)
    except JcsError:
        raise
    except (ValueError, RecursionError) as exc:
        raise JcsError(f"invalid JSON: {exc}")
    if not isinstance(obj, dict):
        raise JcsError(f"top-level is not a JSON object: {type(obj).__name__}")
    if jcs(obj) != bytes(data):
        raise JcsError("bundle bytes are not canonical JCS (unsorted keys / whitespace / tamper)")
    return obj
