"""Verdict-receipt kernel — byte-exact RE-IMPLEMENTATION of lakatos.verdicts (NOT an import).

The engine content-addresses every verdict: a :VerdictReceipt seals 13 fields as
sha256(header + JCS(fields)); the node's current_receipt_sha points at the head, and prev_receipt_sha
links each receipt to its predecessor (a git-reflog-shaped immutable chain). C1 re-derives that here
so an outsider re-checks receipt INTEGRITY (fields hash to their claimed sha) and folds the chain to
genesis — with zero engine import. Copy-fidelity to lakatos.verdicts is pinned by an out-of-band
golden cross-check that runs only in engine CI.

Trust base = sha256 + stdlib json. This proves TAMPER-EVIDENCE (fields can't change after minting
without breaking the sha), NOT AUTHENTICITY (who minted it) — that is substrate-B (Ed25519 write-cert).
"""
from __future__ import annotations

import hashlib
import json
import math

#: The sealed field set (order irrelevant under sort_keys; the SET is the contract). receipt_sha is
#: self-referential and excluded. prev_receipt_sha is IN the payload, so chain position is in the sha.
RECEIPT_FIELDS = (
    "tree", "tag", "target_id", "verdict", "verdict_source", "metric_name", "metric_value",
    "novel_confirmed", "lakatos_status", "judged_at", "judge_script_sha", "prev_receipt_sha",
    "measurement_grade",
)
_RECEIPT_ENCODING_VERSION = "v1"


def _coerce_metric_value(v):
    """None stays None; numbers unify to float (int 3 == float 3.0); non-finite -> None. Both the
    engine's write path and this re-derivation pass through here so legacy ints can't diverge the sha."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _coerce_judged_at(v):
    """ISO str stays; anything else (legacy dict/epoch) becomes a deterministic string."""
    if v is None or isinstance(v, str):
        return v
    return str(v)


def canonical_receipt_blob(fields: dict) -> bytes:
    """Versioned type header + JCS(sorted-keys, compact, UTF-8) over the fixed field set, with
    metric_value/judged_at normalised — byte-identical to lakatos.verdicts.canonical_receipt_blob."""
    payload = {k: fields.get(k) for k in RECEIPT_FIELDS}
    payload["metric_value"] = _coerce_metric_value(payload.get("metric_value"))
    payload["judged_at"] = _coerce_judged_at(payload.get("judged_at"))
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    header = f"verdict-receipt\x00{_RECEIPT_ENCODING_VERSION}\n"
    return header.encode("utf-8") + body.encode("utf-8")


def receipt_content_sha(fields: dict) -> str:
    """Content-address: sha256 (full 64-hex) of the canonical blob."""
    return hashlib.sha256(canonical_receipt_blob(fields)).hexdigest()


class ReceiptChainBroken(Exception):
    """head_sha absent (dangling) or a prev link missing / a cycle = tamper / corruption."""


def fold_receipt_chain(receipts: list, head_sha, cache_verdict=None, cache_source=None) -> dict:
    """Walk head->prev to genesis, verify reachability/acyclicity, re-derive {verdict, verdict_source}.
    receipts: [{receipt_sha, prev_receipt_sha, verdict, verdict_source, ...}]. Mirrors the engine fold:
    empty chain + no head => legacy cache fallback (from_receipt False); dangling/broken/cyclic => raise."""
    by_sha = {r.get("receipt_sha"): r for r in receipts}
    if not head_sha and not by_sha:
        return {"verdict": cache_verdict, "verdict_source": cache_source, "from_receipt": False}
    if head_sha not in by_sha:
        raise ReceiptChainBroken(f"current_receipt_sha={head_sha!r} not in chain (dangling/tampered)")
    head = by_sha[head_sha]
    seen, cur = set(), head_sha
    while cur is not None:
        if cur in seen:
            raise ReceiptChainBroken(f"cycle detected @ {cur!r}")
        seen.add(cur)
        node = by_sha.get(cur)
        if node is None:
            raise ReceiptChainBroken(f"prev link {cur!r} not in chain (broken)")
        cur = node.get("prev_receipt_sha")
    return {"verdict": head.get("verdict"), "verdict_source": head.get("verdict_source"),
            "from_receipt": True}


def check_chain_integrity(chain, head):
    """Shared gate helper: recompute EVERY receipt's content-sha (== its claimed receipt_sha) then
    fold head->genesis. Returns (fold_dict, None) on success or (None, reject_reason) — fail-closed on
    a malformed/tampered/broken/legacy-absent chain (a real receipt at the head is required)."""
    if not isinstance(chain, list) or not chain:
        return None, "receipt chain absent or empty (fail-closed)"
    if not isinstance(head, str) or not head:
        return None, "no head pointer (current_receipt_sha)"
    for r in chain:
        if not isinstance(r, dict) or not isinstance(r.get("receipt_sha"), str):
            return None, "malformed receipt (missing receipt_sha)"
        if receipt_content_sha(r) != r["receipt_sha"]:
            return None, f"receipt content-sha mismatch — tampered @ {r.get('receipt_sha', '')[:12]}…"
    try:
        fold = fold_receipt_chain(chain, head)
    except ReceiptChainBroken as exc:
        return None, f"chain broken: {exc}"
    if not fold["from_receipt"]:
        return None, "no receipt at head (legacy/absent) — nothing to re-derive (fail-closed)"
    return fold, None
