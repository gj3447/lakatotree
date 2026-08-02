"""Hermetic negative-oracle receipt for Gate 2 runtime writer authority."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lakatos.write_cert import (  # noqa: E402
    ed25519_public_key,
    ed25519_sign,
)
from server.container import AppContainer  # noqa: E402
from server.ports import WriterFenceLost  # noqa: E402
from server import runtime_authority as authority  # noqa: E402
from server import version  # noqa: E402


NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
SECRET = bytes([29]) * 32
PUBLIC = ed25519_public_key(SECRET).hex()
WRONG_PUBLIC = ed25519_public_key(bytes([31]) * 32).hex()


def _require(condition: bool, message) -> None:
    if not condition:
        raise RuntimeError(f"runtime authority harness red: {message}")


def _event(cid: str, name: str) -> dict:
    return {
        "cid": cid,
        "correlation_id": cid,
        "cycle_id": cid,
        "service": "lakatotree.runtime_authority_snapshot",
        "event": name,
    }


def _artifact(*, wheel: bool = False) -> dict:
    if wheel:
        return {
            "kind": "wheel-record",
            "version": "1.2.3",
            "installed_manifest_sha256": "a" * 64,
            "record_verified_files": 12,
            "stable_files": 14,
        }
    return {"kind": "git", "source_commit": "b" * 40}


def _lease(*, generation: int = 7, lease_id: str = "critique-history-writer-v1") -> dict:
    return {
        "lease_id": lease_id,
        "owner_token_sha256": "c" * 64,
        "generation": generation,
        "postgresql_backend_pid": 4242,
        "postgresql_advisory_key": [1279349588, 20260802],
    }


def _challenge(*, wheel: bool = False, lease: dict | None = None) -> dict:
    return authority.build_runtime_challenge(
        nonce="d" * 64,
        environment="production",
        boot_id="e" * 64,
        artifact=_artifact(wheel=wheel),
        operation_sha256="1" * 64,
        target_sha256="2" * 64,
        storage_access_policy_file_sha256="3" * 64,
        predeploy_receipt_file_sha256="4" * 64,
        predeploy_receipt_sha256="5" * 64,
        startup_bundle_file_sha256="6" * 64,
        historical_drain_lease_id_sha256="7" * 64,
        runtime_writer_lease=lease or _lease(),
        workers=[{"worker_id": "8" * 64, "boot_id": "e" * 64}],
    )


def _response(challenge: dict, *, mutate=None, expires=None) -> bytes:
    body = {
        "schema_version": authority.RUNTIME_SNAPSHOT_SCHEMA,
        "challenge_sha256": authority.challenge_sha256(challenge),
        **{
            key: value
            for key, value in challenge.items()
            if key != "schema_version"
        },
        "active": True,
        "observed_at": NOW.isoformat(),
        "expires_at": (expires or NOW + timedelta(seconds=20)).isoformat(),
        "evidence_refs": ["9" * 64],
    }
    if mutate is not None:
        mutate(body)
    return authority.canonical_json({
        **body,
        "signature": ed25519_sign(SECRET, authority.signing_bytes(body)).hex(),
    })


def _verify(raw: bytes, challenge: dict):
    return authority.verify_runtime_snapshot(
        raw,
        challenge=challenge,
        public_key_hex=PUBLIC,
        evaluated_at=NOW,
        authority_not_after=NOW + timedelta(minutes=1),
    )


class _Connection:
    closed = False
    autocommit = True

    def __init__(self, events):
        self.events = events

    def commit(self):
        self.events.append("commit")

    def rollback(self):
        self.events.append("rollback")


def verify(backend, cid):
    manifest = json.loads(
        Path(__file__).with_name("harness.json").read_text(encoding="utf-8")
    )
    required = set(manifest["required_controls"])
    executed: set[str] = set()

    def control(name: str, condition: bool, message) -> None:
        _require(name in required, f"undeclared control: {name}")
        _require(name not in executed, f"duplicate control: {name}")
        _require(condition, message)
        executed.add(name)

    git_challenge = _challenge()
    git_raw = _response(git_challenge)
    git_proof = _verify(git_raw, git_challenge)
    control("snapshot.git_positive", git_proof.artifact["kind"] == "git", "Git artifact rejected")
    wheel_challenge = _challenge(wheel=True)
    wheel_proof = _verify(_response(wheel_challenge), wheel_challenge)
    control("snapshot.wheel_positive", wheel_proof.artifact["kind"] == "wheel-record", "wheel artifact rejected")
    backend.ship([_event(cid, "exact_runtime_snapshot_verified")])

    tampered = bytearray(git_raw)
    tampered[-3] = ord("0") if tampered[-3] != ord("0") else ord("1")
    try:
        _verify(bytes(tampered), git_challenge)
    except authority.RuntimeAuthorityError:
        rejected = True
    else:
        rejected = False
    control("snapshot.signature_tamper", rejected, "signature tamper accepted")

    for name, mutate in (
        ("snapshot.binding_splice", lambda body: body.__setitem__("target_sha256", "0" * 64)),
        ("snapshot.unknown_field", lambda body: body.__setitem__("smuggled", True)),
    ):
        try:
            _verify(_response(git_challenge, mutate=mutate), git_challenge)
        except authority.RuntimeAuthorityError:
            rejected = True
        else:
            rejected = False
        control(name, rejected, f"attack accepted: {name}")

    try:
        authority.verify_runtime_snapshot(
            git_raw,
            challenge=git_challenge,
            public_key_hex=WRONG_PUBLIC,
            evaluated_at=NOW,
            authority_not_after=NOW + timedelta(minutes=1),
        )
    except authority.RuntimeAuthorityError:
        rejected = True
    else:
        rejected = False
    control("snapshot.wrong_key", rejected, "wrong key accepted")

    try:
        _verify(_response(git_challenge, expires=NOW + timedelta(minutes=2)), git_challenge)
    except authority.RuntimeAuthorityError:
        rejected = True
    else:
        rejected = False
    control("snapshot.expiry", rejected, "overlong snapshot accepted")

    try:
        authority.verify_published_runtime_snapshot(
            git_raw,
            public_key_hex=PUBLIC,
            expected_artifact={"kind": "git", "source_commit": "a" * 40},
            evaluated_at=NOW,
        )
    except authority.RuntimeAuthorityError:
        rejected = True
    else:
        rejected = False
    control("snapshot.artifact_pin", rejected, "wrong collector artifact accepted")

    reused_lease = _lease(lease_id="migration-drain")
    historical = authority.sha256_bytes(reused_lease["lease_id"].encode())
    try:
        authority.build_runtime_challenge(
            **{
                **{
                    key: value for key, value in git_challenge.items()
                    if key not in {"schema_version", "effect_scope", "artifact_identity_sha256", "historical_drain_lease_id_sha256", "runtime_writer_lease"}
                },
                "historical_drain_lease_id_sha256": historical,
                "runtime_writer_lease": reused_lease,
            }
        )
    except authority.RuntimeAuthorityError:
        rejected = True
    else:
        rejected = False
    control("snapshot.drain_lease_separation", rejected, "historical lease reused")

    control(
        "snapshot.boot_replay",
        not authority.snapshot_is_current(
            git_proof, boot_id="0" * 64, lease=_lease(), evaluated_at=NOW
        ),
        "cross-boot replay accepted",
    )
    control(
        "snapshot.generation_replay",
        not authority.snapshot_is_current(
            git_proof, boot_id="e" * 64, lease=_lease(generation=8), evaluated_at=NOW
        ),
        "stale lease generation accepted",
    )
    control(
        "snapshot.backend_pid_replay",
        not authority.snapshot_is_current(
            git_proof,
            boot_id="e" * 64,
            lease={**_lease(), "postgresql_backend_pid": 4243},
            evaluated_at=NOW,
        ),
        "stale PostgreSQL backend accepted",
    )
    control(
        "snapshot.advisory_key_replay",
        not authority.snapshot_is_current(
            git_proof,
            boot_id="e" * 64,
            lease={**_lease(), "postgresql_advisory_key": [1279349588, 20260803]},
            evaluated_at=NOW,
        ),
        "stale PostgreSQL advisory key accepted",
    )
    control(
        "snapshot.commit_margin",
        not authority.snapshot_is_current(
            git_proof,
            boot_id="e" * 64,
            lease=_lease(),
            evaluated_at=NOW + timedelta(seconds=19),
            commit_margin_seconds=1,
        ),
        "expired commit margin accepted",
    )
    backend.ship([_event(cid, "runtime_snapshot_attacks_rejected")])

    events: list[str] = []
    connection = _Connection(events)
    container = AppContainer(
        neo=object(), mongo=object(), pg_kw={},
        writer_commit_guard=lambda: events.append("guard"),
    )
    container._writer_lease_conn = connection
    container.pg_pool = lambda: (_ for _ in ()).throw(RuntimeError("pool used"))
    container._pg_writer_lease_ready_unlocked = lambda: True
    with container._writer_fenced_pg() as yielded:
        events.append("body")
        same = yielded is connection and connection.autocommit is False
    control(
        "postgresql.same_lease_session",
        same and events == ["body", "guard", "commit"] and connection.autocommit is True,
        events,
    )

    events.clear()
    container._writer_commit_guard = lambda: (_ for _ in ()).throw(WriterFenceLost("replaced"))
    try:
        with container._writer_fenced_pg():
            events.append("body")
    except WriterFenceLost:
        rejected = True
    else:
        rejected = False
    control(
        "postgresql.final_guard_rollback",
        rejected and events == ["body", "rollback"],
        events,
    )

    events.clear()
    readiness = iter((True, False))
    container._writer_commit_guard = lambda: None
    container._pg_writer_lease_ready_unlocked = lambda: next(readiness)
    try:
        with container._writer_fenced_pg():
            events.append("body")
    except WriterFenceLost:
        rejected = True
    else:
        rejected = False
    control(
        "postgresql.lease_loss_rollback",
        rejected and events == ["body", "rollback"],
        events,
    )
    backend.ship([_event(cid, "lease_session_commit_fence_verified")])

    full_sha = version._git_head_sha(str(ROOT))
    control(
        "identity.full_git_sha",
        len(full_sha) == 40 and all(char in "0123456789abcdef" for char in full_sha),
        full_sha,
    )
    public_report = git_proof.public_report()
    encoded = json.dumps(public_report, sort_keys=True)
    response = json.loads(git_raw)
    control(
        "projection.redacted",
        all(
            secret not in encoded
            for secret in (
                response["nonce"],
                response["signature"],
                response["runtime_writer_lease"]["owner_token_sha256"],
                PUBLIC,
            )
        ),
        public_report,
    )
    control(
        "projection.not_approval",
        public_report["production_ready"] is False
        and public_report["deployment_status"] == "NOT_READY"
        and response["effect_scope"] == authority.RUNTIME_EFFECT_SCOPE,
        public_report,
    )
    backend.ship([_event(cid, "runtime_snapshot_claim_bounded")])

    control(
        "manifest.exact_control_set",
        executed | {"manifest.exact_control_set"} == required,
        {"missing": sorted(required - executed), "unexpected": sorted(executed - required)},
    )
    _require(executed == required, "executed control manifest drift")
