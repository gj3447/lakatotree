"""Dependency-free constants shared by storage authority surfaces.

Keep this module stdlib-only so packaging and credential-free harness commands
can inspect protocol identities without importing FastAPI or database clients.
"""

from __future__ import annotations


STORAGE_CONTRACT_ID = "lakatotree-critique-history-storage/v1"
NEO4J_SUPPORTED_RELEASES = frozenset({
    (2026, 3),
    (2026, 4),
    (2026, 5),
    (2026, 6),
})
NEO4J_COMMUNITY_SUPPORTED_RELEASES = frozenset({
    (2026, 1),
    (2026, 2),
    (2026, 3),
    (2026, 4),
    (2026, 5),
    (2026, 6),
})
FENCE_VERIFICATION_SCHEMA = "lakatotree-writer-fence-verification/v2"
FENCE_SIGNATURE_DOMAIN = FENCE_VERIFICATION_SCHEMA.encode("ascii") + b"\0"
FENCE_RESPONSE_FIELDS = frozenset({
    "schema_version",
    "active",
    "nonce",
    "environment",
    "target_sha256",
    "operation_sha256",
    "lease_id",
    "drain_receipt_sha256",
    "verified_at",
    "expires_at",
    "evidence_refs",
    "signature",
})
