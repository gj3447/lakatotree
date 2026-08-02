"""Safety boundary for the installable storage migration coordinator."""

from __future__ import annotations

import errno
import json
import hashlib
import http.server
import os
import subprocess
import sys
import threading
import venv
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from server import storage_predeploy as module


TARGET = "a" * 64
OPERATION = "b" * 64
_FENCE_PRIVATE_BYTES = bytes(range(32))


def _fence_public_key_hex():
    return Ed25519PrivateKey.from_private_bytes(
        _FENCE_PRIVATE_BYTES
    ).public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()


def _sign_fence_response(response):
    signed = dict(response)
    signed["signature"] = Ed25519PrivateKey.from_private_bytes(
        _FENCE_PRIVATE_BYTES
    ).sign(module._fence_signing_payload(response)).hex()
    return signed


def _golden_fence_body():
    return {
        "active": True,
        "drain_receipt_sha256": "d" * 64,
        "environment": "staging",
        "evidence_refs": ["lease-store://exact-readback"],
        "expires_at": "2026-08-02T00:00:20+00:00",
        "lease_id": "lease-1",
        "nonce": "1" * 64,
        "operation_sha256": "b" * 64,
        "schema_version": "lakatotree-writer-fence-verification/v2",
        "target_sha256": "a" * 64,
        "verified_at": "2026-08-02T00:00:00+00:00",
    }


def test_fence_v2_domain_separation_golden_vector():
    body = _golden_fence_body()
    public_key = (
        "03a107bff3ce10be1d70dd18e74bc09967e4d6309ba50d5f1ddc8664125531b8"
    )
    signature = (
        "ec00791adafe8ad7e29fb5e66c1c92d1c925614bec0ae3284a466280e71a6183"
        "e1631102e99341c11253cc869a446e99da3e1d6f33c0821f5e3e6baafed06905"
    )
    payload = module._fence_signing_payload(body)
    assert hashlib.sha256(payload).hexdigest() == (
        "a6655823d7dfc078c52d8c57089cb0f855e7cefcccb5d45a8168df2a41128635"
    )
    assert module._verify_fence_response_signature(
        {**body, "signature": signature}, public_key
    ) == body

    bare_signature = Ed25519PrivateKey.from_private_bytes(
        _FENCE_PRIVATE_BYTES
    ).sign(module._canonical(body)).hex()
    with pytest.raises(RuntimeError, match="signature is invalid"):
        module._verify_fence_response_signature(
            {**body, "signature": bare_signature}, public_key
        )


def test_writer_fenced_neo_normalization_uses_exact_raw_payload_cas(monkeypatch):
    calls = []
    expiry = (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()
    before = {
        "id": "ob-legacy",
        "tree": "T",
        "op": "node_create",
        "node_tag": "n",
        "payload": '{"z": 1, "a": 2}',
    }
    after = {**before, "payload": '{"a":2,"z":1}'}
    scans = iter([[before], [after]])

    def fake_query(_driver, query, **params):
        calls.append((query, params))
        if query.startswith("MATCH (o:OutboxEntry)"):
            return next(scans)
        return [{"updated": 1}]

    monkeypatch.setattr(module, "_neo_query", fake_query)

    attestation = module._bounded_neo_payload_normalization(object(), expiry)

    assert attestation["schema_version"] == module.NORMALIZATION_RECEIPT_SCHEMA
    assert attestation["updated_count"] == 1
    assert attestation["before"]["row_count"] == 1
    assert attestation["after"]["row_count"] == 1
    assert (
        attestation["before"]["projection_sha256"]
        != attestation["after"]["projection_sha256"]
    )
    assert calls[1][1]["rows"] == [{
        "id": "ob-legacy",
        "raw_payload": '{"z": 1, "a": 2}',
        "canonical_payload": '{"a":2,"z":1}',
    }]
    assert "WHERE o.payload=row.raw_payload" in calls[1][0]
    assert calls[2][0] == module._OUTBOX_NORMALIZATION_SCAN


def test_writer_fenced_neo_normalization_rescans_a_noop(monkeypatch):
    expiry = (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()
    row = {
        "id": "ob-canonical", "tree": "T", "op": "node_create",
        "node_tag": "n", "payload": '{"a":2,"z":1}',
    }
    calls = []

    def fake_query(_driver, query, **params):
        calls.append((query, params))
        return [dict(row)]

    monkeypatch.setattr(module, "_neo_query", fake_query)
    attestation = module._bounded_neo_payload_normalization(object(), expiry)

    assert len(calls) == 2
    assert attestation["updated_count"] == 0
    assert attestation["before"] == attestation["after"]


def test_writer_fenced_neo_normalization_rejects_cas_mismatch(monkeypatch):
    expiry = (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()
    row = {
        "id": "ob-legacy", "tree": "T", "op": "node_create",
        "node_tag": "n", "payload": '{"z":1,"a":2}',
    }

    def fake_query(_driver, query, **_params):
        if query.startswith("MATCH (o:OutboxEntry)"):
            return [row]
        return [{"updated": 0}]

    monkeypatch.setattr(module, "_neo_query", fake_query)
    with pytest.raises(RuntimeError, match="lost exact CAS authority"):
        module._bounded_neo_payload_normalization(object(), expiry)


def test_writer_fenced_neo_normalization_rejects_postscan_divergence(monkeypatch):
    expiry = (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()
    before = {
        "id": "ob-legacy", "tree": "T", "op": "node_create",
        "node_tag": "n", "payload": '{"z":1,"a":2}',
    }
    divergent = {**before, "payload": '{"different":true}'}
    scans = iter([[before], [divergent]])

    def fake_query(_driver, query, **_params):
        if query.startswith("MATCH (o:OutboxEntry)"):
            return next(scans)
        return [{"updated": 1}]

    monkeypatch.setattr(module, "_neo_query", fake_query)
    with pytest.raises(RuntimeError, match="post-scan diverged"):
        module._bounded_neo_payload_normalization(object(), expiry)


def test_normalization_preflight_rejects_duplicate_json_keys_before_mutation():
    with pytest.raises(ValueError, match="duplicate JSON object key"):
        module._neo_payload_normalization_plan([{
            "id": "ob-legacy",
            "tree": "T",
            "op": "node_create",
            "node_tag": "n",
            "payload": '{"a":1,"a":1}',
        }])

@pytest.mark.parametrize(
    "raw",
    [
        '{"active":true,"active":false}',
        '{"outer":{"nonce":"a","nonce":"b"}}',
        '{"active":NaN}',
    ],
)
def test_security_json_decoder_rejects_duplicate_and_nonfinite_values(raw):
    with pytest.raises(ValueError):
        module._strict_json_loads(raw)


@pytest.mark.parametrize(
    "key,signature",
    [
        ("", "0" * 128),
        ("A" * 64, "0" * 128),
        (_fence_public_key_hex(), "A" * 128),
        (_fence_public_key_hex(), "0" * 126),
    ],
)
def test_fence_signature_encoding_is_exact_lowercase_hex(key, signature):
    with pytest.raises((RuntimeError, ValueError)):
        module._verify_fence_response_signature(
            {**_golden_fence_body(), "signature": signature}, key
        )


def _one_shot_fence_authority(
    *, nonce_override=None, schema_override=None, mixed_timestamp_spelling=False
):
    """Run the test private key outside the verifier process, like production."""

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - stdlib handler API
            length = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(length))
            now = datetime.now(timezone.utc)
            expires = now + timedelta(seconds=20)
            verified_text = now.isoformat()
            expires_text = expires.isoformat()
            if mixed_timestamp_spelling:
                verified_text = verified_text.replace("+00:00", "Z")
                expires_text = expires.astimezone(
                    timezone(timedelta(hours=9))
                ).isoformat()
            response = _sign_fence_response({
                "schema_version": schema_override or request["schema_version"],
                "active": True,
                "nonce": nonce_override or request["nonce"],
                "environment": request["environment"],
                "target_sha256": request["target_sha256"],
                "operation_sha256": request["operation_sha256"],
                "lease_id": request["lease_id"],
                "drain_receipt_sha256": request["drain_receipt_sha256"],
                "verified_at": verified_text,
                "expires_at": expires_text,
                "evidence_refs": ["lease-store://exact-readback"],
            })
            payload = json.dumps(response, sort_keys=True).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args):
            pass

    authority = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)

    def serve_once():
        try:
            authority.handle_request()
        finally:
            authority.server_close()

    threading.Thread(target=serve_once, daemon=True).start()
    return f"http://127.0.0.1:{authority.server_port}/verify"


def _one_shot_lease_bound_authority(snapshot):
    """Test authority that signs only an independently supplied lease snapshot."""

    frozen = dict(snapshot)

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - stdlib handler API
            length = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(length))
            now = datetime.now(timezone.utc)
            try:
                expires_at = datetime.fromisoformat(
                    str(frozen.get("expires_at", "")).replace("Z", "+00:00")
                )
            except ValueError:
                expires_at = now - timedelta(seconds=1)
            exact = (
                frozen.get("active") is True
                and type(frozen.get("writer_count")) is int
                and frozen.get("writer_count") == 0
                and now < expires_at
                and request.get("environment") == frozen.get("environment")
                and request.get("target_sha256") == frozen.get("target_sha256")
                and request.get("operation_sha256") == frozen.get("operation_sha256")
                and request.get("lease_id") == frozen.get("lease_id")
                and request.get("drain_receipt_sha256")
                    == frozen.get("drain_receipt_sha256")
            )
            if not exact:
                self.send_response(409)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            response = _sign_fence_response({
                "schema_version": request["schema_version"],
                "active": True,
                "nonce": request["nonce"],
                "environment": frozen["environment"],
                "target_sha256": frozen["target_sha256"],
                "operation_sha256": frozen["operation_sha256"],
                "lease_id": frozen["lease_id"],
                "drain_receipt_sha256": frozen["drain_receipt_sha256"],
                "verified_at": now.isoformat(),
                "expires_at": min(
                    expires_at, now + timedelta(seconds=20)
                ).isoformat(),
                "evidence_refs": ["lease-store://independent-snapshot"],
            })
            payload = json.dumps(response, sort_keys=True).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args):
            pass

    authority = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)

    def serve_once():
        try:
            authority.handle_request()
        finally:
            authority.server_close()

    threading.Thread(target=serve_once, daemon=True).start()
    return f"http://127.0.0.1:{authority.server_port}/verify"


def _receipt(now: datetime, **overrides):
    doc = {
        "schema_version": module.DRAIN_SCHEMA,
        "contract_id": module.CONTRACT_ID,
        "environment": "staging",
        "lease_id": "lease-1",
        "target_sha256": TARGET,
        "operation_sha256": OPERATION,
        "writers_drained": True,
        "listener_count": 0,
        "replica_count": 0,
        "verified_at": (now - timedelta(seconds=5)).isoformat(),
        "expires_at": (now + timedelta(minutes=5)).isoformat(),
        "evidence_refs": ["ops://drain/readback/1"],
    }
    doc.update(overrides)
    return doc


def _write_receipt(tmp_path, doc):
    path = tmp_path / "drain.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def test_drain_receipt_requires_fresh_target_bound_exact_zero_readback(tmp_path):
    now = datetime.now(timezone.utc)
    path = _write_receipt(tmp_path, _receipt(now))
    bound = module.validate_drain_receipt(
        path, "staging", TARGET, OPERATION, now
    )
    assert bound["environment"] == "staging"
    assert bound["target_sha256"] == TARGET
    assert len(bound["sha256"]) == 64


@pytest.mark.parametrize(
    "override",
    [
        {"writers_drained": 1}, {"listener_count": False}, {"replica_count": 1},
        {"environment": "production"}, {"evidence_refs": []},
        {"target_sha256": "wrong"}, {"operation_sha256": "wrong"},
        {"lease_id": ""},
    ],
)
def test_drain_receipt_rejects_false_green_fields(tmp_path, override):
    now = datetime.now(timezone.utc)
    path = _write_receipt(tmp_path, _receipt(now, **override))
    with pytest.raises(ValueError):
        module.validate_drain_receipt(path, "staging", TARGET, OPERATION, now)


def test_drain_receipt_rejects_expired_or_nearly_expired_attestation(tmp_path):
    now = datetime.now(timezone.utc)
    for expires_at in (
        now - timedelta(minutes=30),
        now + timedelta(seconds=5),
    ):
        path = _write_receipt(
            tmp_path,
            _receipt(
                now,
                verified_at=(now - timedelta(minutes=1)).isoformat(),
                expires_at=expires_at.isoformat(),
            ),
        )
        with pytest.raises(ValueError):
            module.validate_drain_receipt(
                path, "staging", TARGET, OPERATION, now
            )


def test_drain_receipt_revalidation_detects_file_replacement(tmp_path):
    now = datetime.now(timezone.utc)
    path = _write_receipt(tmp_path, _receipt(now))
    first = module.validate_drain_receipt(
        path, "staging", TARGET, OPERATION, now
    )
    path.write_text(json.dumps(_receipt(now, lease_id="lease-2")), encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        module.validate_drain_receipt(
            path, "staging", TARGET, OPERATION, now,
            expected_file_sha256=first["sha256"],
        )


def test_receipt_publish_is_atomic_and_never_overwrites(tmp_path):
    output = tmp_path / "receipt.json"
    module._publish_once(output, {"ok": True})
    published = json.loads(output.read_text())
    digest = published.pop("receipt_sha256")
    assert published == {"ok": True}
    assert digest == module._sha_bytes(module._canonical(published))
    assert output.stat().st_mode & 0o222 == 0
    with pytest.raises(FileExistsError):
        module._publish_once(output, {"ok": False})
    assert json.loads(output.read_text())["ok"] is True


def _valid_apply_settings():
    return SimpleNamespace(
        storage_environment="staging",
        storage_fence_verifier_sha256="f" * 64,
        storage_fence_public_key_hex=_fence_public_key_hex(),
    )


def test_apply_reserves_final_leaf_before_loading_database_clients(
    tmp_path, monkeypatch
):
    output = (tmp_path / "reserved" / "predeploy.json").absolute()
    observed = []

    def database_clients():
        pending = list(output.parent.glob(f".{output.name}.pending-*"))
        observed.append(
            (
                not output.exists(),
                len(pending),
                pending[0].stat().st_size if len(pending) == 1 else None,
            )
        )
        raise RuntimeError("stop after reservation")

    monkeypatch.setattr(
        module.ServerSettings, "from_env", lambda: _valid_apply_settings()
    )
    monkeypatch.setattr(module, "_database_clients", database_clients)

    with pytest.raises(RuntimeError, match="stop after reservation"):
        module.apply(
            drain_receipt=tmp_path / "drain.json",
            environment="staging",
            receipt_out=output,
            fence_verifier=tmp_path / "verifier",
            fence_verifier_sha256="f" * 64,
        )

    assert observed == [(True, 1, 0)]
    assert not output.exists(), "failed apply must remove only its own reservation"


def test_receipt_reservation_rejects_dotdot_before_database_clients(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        module.ServerSettings, "from_env", lambda: _valid_apply_settings()
    )
    monkeypatch.setattr(
        module,
        "_database_clients",
        lambda: (_ for _ in ()).throw(AssertionError("database clients loaded")),
    )
    output = tmp_path / "future" / ".." / "predeploy.json"
    with pytest.raises(ValueError, match="may not contain"):
        module.apply(
            drain_receipt=tmp_path / "drain.json",
            environment="staging",
            receipt_out=output,
            fence_verifier=tmp_path / "verifier",
            fence_verifier_sha256="f" * 64,
        )


def test_receipt_reservation_rejects_symlink_parent_and_broken_leaf(tmp_path):
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(ValueError, match="non-symlink directories"):
        module._reserve_receipt_path(linked_parent / "predeploy.json")

    broken_leaf = tmp_path / "broken-receipt.json"
    broken_leaf.symlink_to(tmp_path / "missing-target.json")
    with pytest.raises(FileExistsError, match="already exists"):
        module._reserve_receipt_path(broken_leaf)


def test_receipt_reservation_rejects_checkout_contained_target(tmp_path):
    checkout = Path(module.__file__).resolve().parents[1]
    target = checkout / f"forbidden-predeploy-{tmp_path.name}.json"
    with pytest.raises(ValueError, match="outside the source checkout"):
        module._reserve_receipt_path(target)
    assert not target.exists()

    doubled = Path("//" + str(target).lstrip("/"))
    with pytest.raises(ValueError, match="canonical POSIX root"):
        module._reserve_receipt_path(doubled)


def test_receipt_reservation_rejects_dotfile_target(tmp_path):
    with pytest.raises(ValueError, match="reserved dotfile namespace"):
        module._reserve_receipt_path(tmp_path / ".predeploy.json")


def test_receipt_reservation_rejects_case_alias_of_checkout(tmp_path):
    checkout = Path(module.__file__).resolve().parents[1]
    parts = list(checkout.parts)
    alias = None
    for index, component in enumerate(parts):
        if not any(char.isalpha() for char in component):
            continue
        toggled = "".join(
            char.swapcase() if char.isalpha() else char for char in component
        )
        candidate = Path(*parts[:index], toggled, *parts[index + 1:])
        try:
            if candidate.exists() and os.path.samefile(candidate, checkout):
                alias = candidate
                break
        except OSError:
            continue
    if alias is None:
        pytest.skip("filesystem has no case-insensitive checkout alias")

    target = alias / f"forbidden-case-alias-{tmp_path.name}.json"
    with pytest.raises(ValueError, match="outside the source checkout"):
        module._reserve_receipt_path(target)
    assert not target.exists()


def test_receipt_reservation_is_exclusive_and_detects_parent_inode_swap(
    tmp_path,
):
    parent = tmp_path / "receipts"
    output = parent / "predeploy.json"
    reservation = module._reserve_receipt_path(output)
    try:
        with pytest.raises(RuntimeError, match="already reserved"):
            module._reserve_receipt_path(output)

        moved_parent = tmp_path / "receipts-original"
        parent.rename(moved_parent)
        parent.mkdir()
        with pytest.raises(RuntimeError, match="parent identity changed"):
            reservation.verify(expect_empty=True)
    finally:
        reservation.abort()
    assert not (moved_parent / output.name).exists()


def test_receipt_reservation_recovers_only_manifest_bound_crash_orphan(tmp_path):
    parent = tmp_path / "receipts"
    output = parent / "predeploy.json"
    parent.mkdir(mode=0o700)
    unrelated = parent / f".{output.name}.pending-{'a' * 32}"
    unrelated.write_bytes(b"")
    unrelated.chmod(0o600)

    pid = os.fork()
    if pid == 0:
        module._reserve_receipt_path(output)
        os._exit(0)
    waited, status = os.waitpid(pid, 0)
    assert waited == pid and os.waitstatus_to_exitcode(status) == 0
    assert len(list(parent.glob(f".{output.name}.pending-*"))) == 2

    reservation = module._reserve_receipt_path(output)
    try:
        pending = list(parent.glob(f".{output.name}.pending-*"))
        assert set(pending) == {unrelated, parent / reservation.pending_name}
    finally:
        reservation.abort()
    assert list(parent.glob(f".{output.name}.pending-*")) == [unrelated]


def test_receipt_reservation_recovers_crash_after_probe_hardlink(tmp_path):
    parent = tmp_path / "receipts"
    parent.mkdir(mode=0o700)
    output = parent / "predeploy.json"

    pid = os.fork()
    if pid == 0:
        real_link = module.os.link

        def crash_after_probe_link(source, target, *args, **kwargs):
            real_link(source, target, *args, **kwargs)
            if isinstance(target, str) and ".probe-" in target:
                os._exit(0)

        module.os.link = crash_after_probe_link
        module._reserve_receipt_path(output)
        os._exit(2)
    waited, status = os.waitpid(pid, 0)
    assert waited == pid and os.waitstatus_to_exitcode(status) == 0
    assert len(list(parent.glob(f".{output.name}.pending-*"))) == 1
    assert len(list(parent.glob(f".{output.name}.probe-*"))) == 1

    retry = module._reserve_receipt_path(output)
    try:
        assert len(list(parent.glob(f".{output.name}.pending-*"))) == 1
        assert list(parent.glob(f".{output.name}.probe-*")) == []
    finally:
        retry.abort()


@pytest.mark.parametrize(
    "torn",
    [
        b'{"schema_version":',
        b'{"identity":[1,2],"pending":".predeploy.json.pending-',
        b"x" * 4097,
    ],
)
def test_torn_receipt_sidecar_does_not_authorize_cleanup_or_block_retry(
    tmp_path, torn
):
    output = tmp_path / "predeploy.json"
    lock = tmp_path / f".{output.name}.lock"
    orphan = tmp_path / f".{output.name}.pending-{'b' * 32}"
    lock.write_bytes(torn)
    lock.chmod(0o600)
    orphan.write_bytes(b"")
    orphan.chmod(0o600)

    reservation = module._reserve_receipt_path(output)
    try:
        assert orphan.exists()
        assert (tmp_path / reservation.pending_name).exists()
    finally:
        reservation.abort()
    assert orphan.exists()


def test_receipt_reservation_preflights_hardlink_before_database_clients(
    tmp_path, monkeypatch
):
    output = (tmp_path / "receipts" / "predeploy.json").absolute()
    monkeypatch.setattr(
        module.ServerSettings, "from_env", lambda: _valid_apply_settings()
    )
    monkeypatch.setattr(
        module,
        "_database_clients",
        lambda: (_ for _ in ()).throw(AssertionError("database clients loaded")),
    )
    monkeypatch.setattr(
        module.os,
        "link",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError(errno.EOPNOTSUPP, "hard links unsupported")
        ),
    )
    with pytest.raises(ValueError, match="hard-link support"):
        module.apply(
            drain_receipt=tmp_path / "drain.json",
            environment="staging",
            receipt_out=output,
            fence_verifier=tmp_path / "verifier",
            fence_verifier_sha256="f" * 64,
        )


def test_receipt_reservation_preflights_fchmod_before_database_clients(
    tmp_path, monkeypatch
):
    output = (tmp_path / "receipts" / "predeploy.json").absolute()
    monkeypatch.setattr(
        module.ServerSettings, "from_env", lambda: _valid_apply_settings()
    )
    monkeypatch.setattr(
        module,
        "_database_clients",
        lambda: (_ for _ in ()).throw(AssertionError("database clients loaded")),
    )
    monkeypatch.setattr(
        module.os,
        "fchmod",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError(errno.EOPNOTSUPP, "chmod unsupported")
        ),
    )
    with pytest.raises(ValueError, match="chmod/hard-link support"):
        module.apply(
            drain_receipt=tmp_path / "drain.json",
            environment="staging",
            receipt_out=output,
            fence_verifier=tmp_path / "verifier",
            fence_verifier_sha256="f" * 64,
        )


def test_receipt_reservation_rejects_nonwritable_parent_before_clients(
    tmp_path, monkeypatch
):
    parent = tmp_path / "receipts"
    parent.mkdir(mode=0o700)
    parent.chmod(0o500)
    monkeypatch.setattr(
        module.ServerSettings, "from_env", lambda: _valid_apply_settings()
    )
    monkeypatch.setattr(
        module,
        "_database_clients",
        lambda: (_ for _ in ()).throw(AssertionError("database clients loaded")),
    )
    try:
        with pytest.raises(ValueError, match="not writable"):
            module.apply(
                drain_receipt=tmp_path / "drain.json",
                environment="staging",
                receipt_out=parent / "predeploy.json",
                fence_verifier=tmp_path / "verifier",
                fence_verifier_sha256="f" * 64,
            )
    finally:
        parent.chmod(0o700)


def test_receipt_abort_cleanup_failure_closes_descriptors_and_releases_lock(
    tmp_path, monkeypatch
):
    output = tmp_path / "predeploy.json"
    reservation = module._reserve_receipt_path(output)
    real_unlink = module.os.unlink

    def fail_pending_unlink(path, *args, **kwargs):
        if path == reservation.pending_name:
            raise OSError(errno.EACCES, "cleanup denied")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(module.os, "unlink", fail_pending_unlink)
    with pytest.raises(RuntimeError, match="failed to clean"):
        reservation.abort()
    assert reservation.pending_fd == -1
    assert reservation.lock_fd == -1
    assert reservation.parent_fd == -1

    monkeypatch.setattr(module.os, "unlink", real_unlink)
    retry = module._reserve_receipt_path(output)
    retry.abort()


def test_receipt_publish_fsyncs_mode_before_link(tmp_path, monkeypatch):
    reservation = module._reserve_receipt_path(tmp_path / "predeploy.json")
    events = []
    real_fsync = module.os.fsync
    real_fchmod = module.os.fchmod
    real_link = module.os.link
    real_unlink = module.os.unlink

    def tracked_fsync(descriptor):
        if descriptor == reservation.pending_fd:
            events.append("fsync-file")
        elif descriptor == reservation.parent_fd:
            events.append("fsync-parent")
        return real_fsync(descriptor)

    def tracked_fchmod(descriptor, mode):
        if descriptor == reservation.pending_fd:
            events.append(f"fchmod-{mode:o}")
        return real_fchmod(descriptor, mode)

    def tracked_link(source, target, *args, **kwargs):
        if source == reservation.pending_name and target == reservation.path.name:
            events.append("link-final")
        return real_link(source, target, *args, **kwargs)

    def tracked_unlink(path, *args, **kwargs):
        if path == reservation.pending_name:
            events.append("unlink-pending")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(module.os, "fsync", tracked_fsync)
    monkeypatch.setattr(module.os, "fchmod", tracked_fchmod)
    monkeypatch.setattr(module.os, "link", tracked_link)
    monkeypatch.setattr(module.os, "unlink", tracked_unlink)
    try:
        reservation.publish({"ok": True})
    finally:
        reservation.close()

    assert events == [
        "fsync-file",
        "fchmod-400",
        "fsync-file",
        "link-final",
        "unlink-pending",
        "fsync-parent",
    ]


def test_installable_migration_resources_are_present_and_content_bound():
    sources = module.migration_sources()
    assert set(sources) == {module.PG_RESOURCE, module.NEO_RESOURCE}
    assert all(len(value) == 64 for value in sources.values())


def _verifier(tmp_path, *, object_response=True, authority_url=None):
    path = (tmp_path / "fence-verifier.py").absolute()
    if object_response:
        authority_url = authority_url or _one_shot_fence_authority()
        body = f"#!{Path(sys.executable).resolve()}\n" + '''\
import json, sys, urllib.request
request = json.load(sys.stdin)
payload = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
call = urllib.request.Request("__AUTHORITY_URL__", data=payload, method="POST")
with urllib.request.urlopen(call, timeout=3) as response:
    sys.stdout.buffer.write(response.read())
'''.replace("__AUTHORITY_URL__", authority_url)
    else:
        body = f"#!{Path(sys.executable).resolve()}\nprint('[]')\n"
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return (
        path,
        module.fence_verifier_identity(path)["sha256"],
        _fence_public_key_hex(),
    )


def test_live_fence_uses_fresh_nonce_and_pinned_external_executable(tmp_path):
    now = datetime.now(timezone.utc)
    drain_path = _write_receipt(tmp_path, _receipt(now))
    drain = module.validate_drain_receipt(
        drain_path, "staging", TARGET, OPERATION, now
    )
    verifier, verifier_sha, public_key = _verifier(tmp_path)

    proof = module.verify_live_fence(verifier, verifier_sha, drain, public_key)

    assert proof["schema_version"] == module.FENCE_VERIFICATION_SCHEMA
    assert proof["verifier_sha256"] == verifier_sha
    with pytest.raises(ValueError, match="hash mismatch"):
        module.verify_live_fence(verifier, "0" * 64, drain, public_key)


def test_live_fence_cannot_outlive_the_writer_drain_lease(tmp_path):
    now = datetime.now(timezone.utc)
    drain_path = _write_receipt(
        tmp_path,
        _receipt(now, expires_at=(now + timedelta(seconds=15)).isoformat()),
    )
    drain = module.validate_drain_receipt(
        drain_path, "staging", TARGET, OPERATION, now
    )
    verifier, verifier_sha, public_key = _verifier(tmp_path)

    with pytest.raises(RuntimeError, match="current exact lease"):
        module.verify_live_fence(verifier, verifier_sha, drain, public_key)


def test_live_fence_preserves_exact_signed_z_and_offset_timestamps(tmp_path):
    now = datetime.now(timezone.utc)
    drain_path = _write_receipt(tmp_path, _receipt(now))
    drain = module.validate_drain_receipt(
        drain_path, "staging", TARGET, OPERATION, now
    )
    authority_url = _one_shot_fence_authority(
        mixed_timestamp_spelling=True
    )
    verifier, verifier_sha, public_key = _verifier(
        tmp_path, authority_url=authority_url
    )

    proof = module.verify_live_fence(verifier, verifier_sha, drain, public_key)

    signed = proof["signed_response"]
    assert signed["verified_at"].endswith("Z")
    assert signed["expires_at"].endswith("+09:00")
    assert proof["verified_at"] == signed["verified_at"]
    assert proof["expires_at"] == signed["expires_at"]


def test_live_fence_rejects_non_object_response_without_attribute_crash(tmp_path):
    now = datetime.now(timezone.utc)
    drain_path = _write_receipt(tmp_path, _receipt(now))
    drain = module.validate_drain_receipt(
        drain_path, "staging", TARGET, OPERATION, now
    )
    verifier, verifier_sha, public_key = _verifier(
        tmp_path, object_response=False
    )
    with pytest.raises(RuntimeError, match="must be an object"):
        module.verify_live_fence(verifier, verifier_sha, drain, public_key)


def test_live_fence_rejects_validly_signed_replayed_nonce(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    drain = module.validate_drain_receipt(
        _write_receipt(tmp_path, _receipt(now)),
        "staging", TARGET, OPERATION, now,
    )
    authority_url = _one_shot_fence_authority(nonce_override="0" * 64)
    verifier, verifier_sha, public_key = _verifier(
        tmp_path, authority_url=authority_url
    )
    monkeypatch.setattr(module.secrets, "token_hex", lambda _n: "1" * 64)
    with pytest.raises(RuntimeError, match="current exact lease"):
        module.verify_live_fence(verifier, verifier_sha, drain, public_key)


@pytest.mark.parametrize(
    "override",
    [
        {"active": False},
        {"writer_count": 1},
        {"expires_at": "2000-01-01T00:00:00+00:00"},
        {"lease_id": "unknown-lease"},
        {"environment": "production"},
        {"target_sha256": "9" * 64},
        {"operation_sha256": "8" * 64},
        {"drain_receipt_sha256": "7" * 64},
    ],
)
def test_independent_lease_authority_denies_nonexact_or_unsafe_state(
    tmp_path, override
):
    now = datetime.now(timezone.utc)
    drain = module.validate_drain_receipt(
        _write_receipt(tmp_path, _receipt(now)),
        "staging",
        TARGET,
        OPERATION,
        now,
    )
    snapshot = {
        "active": True,
        "writer_count": 0,
        "expires_at": (now + timedelta(minutes=2)).isoformat(),
        "environment": drain["environment"],
        "target_sha256": drain["target_sha256"],
        "operation_sha256": drain["operation_sha256"],
        "lease_id": drain["lease_id"],
        "drain_receipt_sha256": drain["sha256"],
    }
    snapshot.update(override)
    verifier, verifier_sha, public_key = _verifier(
        tmp_path,
        authority_url=_one_shot_lease_bound_authority(snapshot),
    )

    with pytest.raises(RuntimeError, match="external writer-fence verifier rejected"):
        module.verify_live_fence(verifier, verifier_sha, drain, public_key)


def test_independent_lease_authority_accepts_exact_safe_snapshot(tmp_path):
    now = datetime.now(timezone.utc)
    drain = module.validate_drain_receipt(
        _write_receipt(tmp_path, _receipt(now)),
        "staging",
        TARGET,
        OPERATION,
        now,
    )
    snapshot = {
        "active": True,
        "writer_count": 0,
        "expires_at": (now + timedelta(minutes=2)).isoformat(),
        "environment": drain["environment"],
        "target_sha256": drain["target_sha256"],
        "operation_sha256": drain["operation_sha256"],
        "lease_id": drain["lease_id"],
        "drain_receipt_sha256": drain["sha256"],
    }
    verifier, verifier_sha, public_key = _verifier(
        tmp_path,
        authority_url=_one_shot_lease_bound_authority(snapshot),
    )

    proof = module.verify_live_fence(
        verifier, verifier_sha, drain, public_key
    )

    assert proof["verifier_sha256"] == verifier_sha
    assert proof["evidence_refs"] == ["lease-store://independent-snapshot"]


def test_full_drain_and_runtime_paths_reject_duplicate_json(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    drain = tmp_path / "duplicate-drain.json"
    drain.write_text(
        '{"schema_version":"%s","schema_version":"%s"}'
        % (module.DRAIN_SCHEMA, module.DRAIN_SCHEMA),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        module.validate_drain_receipt(
            drain, "staging", TARGET, OPERATION, now
        )

    receipt, _sha, _target = _sealed_predeploy_receipt(tmp_path, monkeypatch)
    raw = receipt.read_text(encoding="utf-8")
    duplicate = (tmp_path / "duplicate-runtime.json").absolute()
    duplicate.write_text(
        raw.replace("{", '{"schema_version":"duplicate",', 1),
        encoding="utf-8",
    )
    duplicate.chmod(0o444)
    duplicate_sha = hashlib.sha256(duplicate.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="valid JSON"):
        module.verify_predeploy_receipt(
            duplicate,
            duplicate_sha,
            _runtime_settings(),
            object(),
            object(),
        )


def test_live_fence_rejects_path_selected_interpreter(tmp_path):
    path = (tmp_path / "unsafe-verifier").absolute()
    path.write_text("#!/usr/bin/env python3\nraise SystemExit(1)\n", encoding="utf-8")
    path.chmod(0o755)
    with pytest.raises(ValueError, match="may not select"):
        module.fence_verifier_identity(path)


def test_live_fence_executes_private_bytes_after_configured_path_swap(
    tmp_path, monkeypatch
):
    now = datetime.now(timezone.utc)
    drain_path = _write_receipt(tmp_path, _receipt(now))
    drain = module.validate_drain_receipt(
        drain_path, "staging", TARGET, OPERATION, now
    )
    verifier, verifier_sha, public_key = _verifier(tmp_path)
    real_run = subprocess.run

    def swap_then_run(*args, **kwargs):
        verifier.write_text(
            f"#!{Path(sys.executable).resolve()}\nraise SystemExit(9)\n",
            encoding="utf-8",
        )
        return real_run(*args, **kwargs)

    monkeypatch.setattr(module.subprocess, "run", swap_then_run)
    proof = module.verify_live_fence(verifier, verifier_sha, drain, public_key)
    assert proof["verifier_sha256"] == verifier_sha


def test_live_fence_rejects_sitecustomize_forged_response(tmp_path):
    """A mutable runtime can at most forge JSON, never a valid authority response."""

    poisoned = tmp_path / "poisoned-runtime"
    venv.EnvBuilder(with_pip=False, symlinks=False).create(poisoned)
    interpreter = (poisoned / "bin" / "python").absolute()
    assert interpreter.is_file() and not interpreter.is_symlink()
    site_packages = (
        poisoned
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages"
    )
    site_packages.mkdir(parents=True, exist_ok=True)
    (site_packages / "sitecustomize.py").write_text(
        '''\
import datetime, json, os, sys
request = json.load(sys.stdin)
now = datetime.datetime.now(datetime.timezone.utc)
response = {
    "schema_version": request["schema_version"],
    "active": True,
    "nonce": request["nonce"],
    "environment": request["environment"],
    "target_sha256": request["target_sha256"],
    "operation_sha256": request["operation_sha256"],
    "lease_id": request["lease_id"],
    "drain_receipt_sha256": request["drain_receipt_sha256"],
    "verified_at": now.isoformat(),
    "expires_at": (now + datetime.timedelta(seconds=20)).isoformat(),
    "evidence_refs": ["forged://sitecustomize"],
    "signature": "00" * 64,
}
sys.stdout.write(json.dumps(response, sort_keys=True))
sys.stdout.flush()
os._exit(0)
''',
        encoding="utf-8",
    )
    verifier = (tmp_path / "rejecting-verifier").absolute()
    verifier.write_text(
        f"#!{interpreter}\nraise SystemExit(9)\n", encoding="utf-8"
    )
    verifier.chmod(0o755)
    verifier_sha = module.fence_verifier_identity(verifier)["sha256"]
    now = datetime.now(timezone.utc)
    drain = module.validate_drain_receipt(
        _write_receipt(tmp_path, _receipt(now)),
        "staging",
        TARGET,
        OPERATION,
        now,
    )

    with pytest.raises(RuntimeError) as rejected:
        module.verify_live_fence(
            verifier, verifier_sha, drain, _fence_public_key_hex()
        )
    assert str(rejected.value) in {
        "writer-fence authority signature is invalid",
        "external writer-fence verifier rejected the lease",
    }


def test_bounded_neo_migration_never_starts_query_after_lease_expiry(monkeypatch):
    base = datetime.now(timezone.utc)
    clock = {"late": False}
    ran = []

    class _Clock:
        @classmethod
        def fromisoformat(cls, value):
            return datetime.fromisoformat(value)

        @classmethod
        def now(cls, tz=None):
            current = base + (timedelta(seconds=20) if clock["late"] else timedelta())
            return current if tz is not None else current.replace(tzinfo=None)

    class _Result:
        def data(self):
            return []

    class _Session:
        def __enter__(self):
            clock["late"] = True
            return self

        def __exit__(self, *_args):
            return False

        def run(self, *_args, **_kwargs):
            ran.append(True)
            return _Result()

    class _Driver:
        def session(self):
            return _Session()

    monkeypatch.setattr(module, "datetime", _Clock)
    with pytest.raises(RuntimeError, match="expired before Neo4j query"):
        module._bounded_neo_migration(
            _Driver(),
            (base + timedelta(seconds=10)).isoformat(),
            b"RETURN 1;",
        )
    assert ran == []


def test_bounded_pg_migration_rejects_near_expiry_before_any_cursor_sql():
    touched = []

    class _Connection:
        def cursor(self):
            touched.append("cursor")
            raise AssertionError("PostgreSQL SQL started without lease headroom")

    with pytest.raises(ValueError, match="insufficient time for PostgreSQL"):
        module._bounded_pg_migration(
            _Connection(),
            (datetime.now(timezone.utc) + timedelta(seconds=8)).isoformat(),
            b"SELECT 1;",
        )
    assert touched == []


def test_bounded_pg_migration_arms_timeouts_and_cancel_before_source(
    monkeypatch,
):
    events = []

    class _Cursor:
        def __enter__(self):
            events.append("cursor-enter")
            return self

        def __exit__(self, *_args):
            events.append("cursor-exit")
            return False

        def execute(self, statement, params=None):
            events.append(("sql", statement, params))

    class _Connection:
        def cursor(self):
            events.append("cursor-open")
            return _Cursor()

        def cancel(self):
            events.append("connection-cancel")

    class _Timer:
        daemon = False

        def __init__(self, seconds, callback):
            events.append(("timer-init", seconds, callback.__name__))

        def start(self):
            events.append("timer-start")

        def cancel(self):
            events.append("timer-cancel")

    monkeypatch.setattr(module.threading, "Timer", _Timer)
    source = b"CREATE TABLE exact_migration_probe(id integer);"
    module._bounded_pg_migration(
        _Connection(),
        (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat(),
        source,
    )

    sql_events = [event for event in events if isinstance(event, tuple) and event[0] == "sql"]
    assert [event[1] for event in sql_events[:2]] == [
        "SELECT set_config('lock_timeout', %s, false)",
        "SELECT set_config('statement_timeout', %s, false)",
    ]
    assert sql_events[2] == ("sql", source.decode("utf-8"), None)
    assert events.index("timer-start") < events.index(sql_events[2])
    assert events[-1] == "timer-cancel"


@pytest.mark.parametrize(
    ("environment", "configured_sha", "public_key", "message"),
    [
        ("production", "f" * 64, _fence_public_key_hex(), "environment"),
        ("staging", "0" * 64, _fence_public_key_hex(), "not pinned"),
        ("staging", "f" * 64, None, "public key is not pinned"),
    ],
)
def test_apply_rejects_unpinned_authority_before_loading_database_clients(
    tmp_path, monkeypatch, environment, configured_sha, public_key, message
):
    monkeypatch.setenv("LAKATOS_STORAGE_ENVIRONMENT", environment)
    monkeypatch.setenv("LAKATOS_STORAGE_FENCE_VERIFIER_SHA256", configured_sha)
    if public_key is None:
        monkeypatch.delenv("LAKATOS_STORAGE_FENCE_PUBLIC_KEY_HEX", raising=False)
    else:
        monkeypatch.setenv("LAKATOS_STORAGE_FENCE_PUBLIC_KEY_HEX", public_key)
    monkeypatch.setattr(
        module,
        "_database_clients",
        lambda: (_ for _ in ()).throw(AssertionError("database clients loaded")),
    )
    with pytest.raises(RuntimeError, match=message):
        module.apply(
            drain_receipt=tmp_path / "missing-drain.json",
            environment="staging",
            receipt_out=tmp_path / "new-receipt.json",
            fence_verifier=tmp_path / "missing-verifier",
            fence_verifier_sha256="f" * 64,
        )


def test_apply_rejects_relative_receipt_path_before_loading_database_clients(
    monkeypatch,
):
    monkeypatch.setattr(
        module,
        "_database_clients",
        lambda: (_ for _ in ()).throw(AssertionError("database clients loaded")),
    )
    with pytest.raises(ValueError, match="absolute path"):
        module.apply(
            drain_receipt=Path("drain.json"),
            environment="staging",
            receipt_out=Path("predeploy.json"),
            fence_verifier=Path("verifier"),
            fence_verifier_sha256="f" * 64,
        )


def test_apply_hashes_and_executes_each_captured_migration_read_once(
    tmp_path, monkeypatch
):
    reads = {module.PG_RESOURCE: 0, module.NEO_RESOURCE: 0}
    captured = {
        module.PG_RESOURCE: b"postgresql-captured-once",
        module.NEO_RESOURCE: b"neo4j-captured-once",
    }
    executed = {}

    def resource_bytes(name):
        reads[name] += 1
        if reads[name] > 1:
            return b"changed-on-second-read"
        return captured[name]

    class _Connection:
        autocommit = False

        def close(self):
            return None

    connection = _Connection()

    class _Psycopg:
        @staticmethod
        def connect(**_kwargs):
            return connection

    class _Driver:
        def __init__(self, **_kwargs):
            pass

        def close(self):
            return None

    settings = SimpleNamespace(
        storage_environment="staging",
        storage_fence_verifier_sha256="f" * 64,
        storage_fence_public_key_hex=_fence_public_key_hex(),
        pg_kw={},
    )
    target = {
        "sha256": "e" * 64,
        "details": {"postgresql": {"database_oid": "7"}, "neo4j": {"database_id": "db"}},
    }
    report = {
        "contract_id": module.CONTRACT_ID,
        "ok": True,
        "failures": [],
        "details": {},
    }
    now = datetime.now(timezone.utc)
    live_drain = {
        "sha256": "d" * 64,
        "schema_version": module.DRAIN_SCHEMA,
        "environment": "staging",
        "lease_id": "lease-1",
        "verified_at": (now - timedelta(seconds=5)).isoformat(),
        "expires_at": (now + timedelta(minutes=5)).isoformat(),
        "target_sha256": target["sha256"],
        "operation_sha256": "unused-by-this-boundary-fake",
        "evidence_refs": ["test://drain"],
        "live_fence": {
            "schema_version": module.FENCE_VERIFICATION_SCHEMA,
            "verifier_sha256": "f" * 64,
            "verified_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=20)).isoformat(),
            "evidence_refs": ["test://live"],
        },
    }

    monkeypatch.setattr(module.ServerSettings, "from_env", lambda: settings)
    monkeypatch.setattr(module, "_database_clients", lambda: (_Psycopg, _Driver))
    monkeypatch.setattr(module, "_resource_bytes", resource_bytes)
    monkeypatch.setattr(
        module, "_artifact_identity",
        lambda: {"kind": "git", "source_commit": "c" * 40},
    )
    monkeypatch.setattr(module, "target_identity", lambda *_args: target)
    monkeypatch.setattr(
        module, "validate_drain_receipt", lambda *_args, **_kwargs: {"sha256": "d" * 64}
    )
    monkeypatch.setattr(module, "_revalidate_drain", lambda *_args, **_kwargs: live_drain)
    monkeypatch.setattr(module, "_neo_query", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(module, "inspect_neo_outbox_contract", lambda *_args, **_kwargs: report)
    monkeypatch.setattr(module, "inspect_pg_history_contract", lambda *_args: report)
    monkeypatch.setattr(module, "pg_projection_rows", lambda *_args: [])
    monkeypatch.setattr(
        module, "_bounded_pg_migration",
        lambda _connection, _expires, source: executed.setdefault("pg", source),
    )
    monkeypatch.setattr(
        module, "_bounded_neo_migration",
        lambda _driver, _expires, source: executed.setdefault("neo", source),
    )

    receipt = module.apply(
        drain_receipt=tmp_path / "drain.json",
        environment="staging",
        receipt_out=(tmp_path / "predeploy.json").absolute(),
        fence_verifier=tmp_path / "verifier",
        fence_verifier_sha256="f" * 64,
    )

    assert reads == {module.PG_RESOURCE: 1, module.NEO_RESOURCE: 1}
    assert executed == {"pg": captured[module.PG_RESOURCE], "neo": captured[module.NEO_RESOURCE]}
    assert receipt["operation"]["migration_sources"] == {
        name: module._sha_bytes(source) for name, source in captured.items()
    }
    normalization = receipt["neo4j"]["payload_normalization"]
    assert normalization["updated_count"] == 0
    assert normalization["before"] == normalization["after"]


def test_authority_denial_precedes_the_first_migration_mutation(
    tmp_path, monkeypatch
):
    settings = SimpleNamespace(
        storage_environment="staging",
        storage_fence_verifier_sha256="f" * 64,
        storage_fence_public_key_hex=_fence_public_key_hex(),
        pg_kw={},
    )
    touched = []

    class _Connection:
        autocommit = False

        def close(self):
            touched.append("pg-close")

    connection = _Connection()

    class _Psycopg:
        @staticmethod
        def connect(**_kwargs):
            return connection

    class _Driver:
        def __init__(self, **_kwargs):
            pass

        def close(self):
            touched.append("neo-close")

    monkeypatch.setattr(module.ServerSettings, "from_env", lambda: settings)
    monkeypatch.setattr(module, "_database_clients", lambda: (_Psycopg, _Driver))
    monkeypatch.setattr(module, "_resource_bytes", lambda name: name.encode())
    monkeypatch.setattr(
        module,
        "_artifact_identity",
        lambda: {"kind": "git", "source_commit": "c" * 40},
    )
    monkeypatch.setattr(
        module,
        "target_identity",
        lambda *_args: {"sha256": "e" * 64, "details": {}},
    )
    monkeypatch.setattr(
        module,
        "validate_drain_receipt",
        lambda *_args, **_kwargs: {"sha256": "d" * 64},
    )
    monkeypatch.setattr(
        module,
        "_revalidate_drain",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("external writer-fence verifier rejected the lease")
        ),
    )
    monkeypatch.setattr(
        module,
        "_bounded_pg_migration",
        lambda *_args: touched.append("pg-mutation"),
    )
    monkeypatch.setattr(
        module,
        "_bounded_neo_migration",
        lambda *_args: touched.append("neo-mutation"),
    )

    with pytest.raises(RuntimeError, match="rejected the lease"):
        module.apply(
            drain_receipt=tmp_path / "drain.json",
            environment="staging",
            receipt_out=tmp_path / "new-receipt.json",
            fence_verifier=tmp_path / "verifier",
            fence_verifier_sha256="f" * 64,
        )

    assert "pg-mutation" not in touched
    assert "neo-mutation" not in touched
    assert touched == ["pg-close", "neo-close"]


def _sealed_predeploy_receipt(tmp_path, monkeypatch, *, neo=None):
    now = datetime.now(timezone.utc)
    artifact = {"kind": "git", "source_commit": "c" * 40}
    operation = module.operation_identity(artifact)
    target = {
        "sha256": "e" * 64,
        "details": {"postgresql": {"database_oid": "7"}, "neo4j": {"database_id": "db"}},
    }
    report = {
        "contract_id": module.CONTRACT_ID,
        "ok": True,
        "failures": [],
        "details": {},
    }
    live_verified_at = (now - timedelta(seconds=2)).isoformat()
    live_expires_at = (now + timedelta(seconds=20)).isoformat()
    live_evidence = ["lease-store://exact-readback"]
    signed_response = _sign_fence_response({
        "schema_version": module.FENCE_VERIFICATION_SCHEMA,
        "active": True,
        "nonce": "1" * 64,
        "environment": "staging",
        "target_sha256": target["sha256"],
        "operation_sha256": operation["sha256"],
        "lease_id": "lease-1",
        "drain_receipt_sha256": "d" * 64,
        "verified_at": live_verified_at,
        "expires_at": live_expires_at,
        "evidence_refs": live_evidence,
    })
    body = {
        "schema_version": module.RECEIPT_SCHEMA,
        "contract_id": module.CONTRACT_ID,
        "environment": "staging",
        "artifact": artifact,
        "operation": operation,
        "target_sha256": target["sha256"],
        "target": target["details"],
        "writer_drain": {
            "sha256": "d" * 64,
            "schema_version": module.DRAIN_SCHEMA,
            "environment": "staging",
            "lease_id": "lease-1",
            "verified_at": (now - timedelta(seconds=30)).isoformat(),
            "expires_at": (now + timedelta(minutes=5)).isoformat(),
            "target_sha256": target["sha256"],
            "operation_sha256": operation["sha256"],
            "evidence_refs": ["ops://drain/readback/1"],
            "live_fence": {
                "schema_version": module.FENCE_VERIFICATION_SCHEMA,
                "verifier_sha256": "f" * 64,
                "authority_key_sha256": module._fence_authority_sha256(
                    _fence_public_key_hex()
                ),
                "signed_response": signed_response,
                "verified_at": live_verified_at,
                "expires_at": live_expires_at,
                "evidence_refs": live_evidence,
            },
        },
        "postgresql": {"ok": True, "report": report},
        "neo4j": (
            {
                "ok": True,
                "migration_ok": True,
                "payload_normalization": {
                    "schema_version": module.NORMALIZATION_RECEIPT_SCHEMA,
                    "before": {
                        "row_count": 0,
                        "projection_sha256": "a" * 64,
                    },
                    "after": {
                        "row_count": 0,
                        "projection_sha256": "a" * 64,
                    },
                    "updated_count": 0,
                },
                "report": report,
            }
            if neo is None else neo
        ),
        "created_at": now.isoformat(),
    }
    path = (tmp_path / "predeploy.json").absolute()
    module._publish_once(path, body)
    file_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(module, "_artifact_identity", lambda: artifact)
    monkeypatch.setattr(module, "target_identity", lambda *_args: target)
    return path, file_sha, target


def _runtime_settings():
    return SimpleNamespace(
        storage_environment="staging",
        storage_fence_verifier_sha256="f" * 64,
        storage_fence_public_key_hex=_fence_public_key_hex(),
    )


def _patch_healthy_storage_runtime(app, monkeypatch):
    class _Cursor:
        def execute(self, *_args):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class _Connection:
        def cursor(self):
            return _Cursor()

    @contextmanager
    def healthy_pg():
        yield _Connection()

    healthy_report = {
        "contract_id": module.CONTRACT_ID,
        "ok": True,
        "failures": [],
    }
    monkeypatch.setattr(app, "pg", healthy_pg)
    monkeypatch.setattr(
        app, "inspect_pg_history_contract", lambda _conn: healthy_report
    )
    monkeypatch.setattr(app, "pg_projection_rows", lambda _conn: [])
    monkeypatch.setattr(
        app,
        "inspect_neo_outbox_contract",
        lambda *_args, **_kwargs: healthy_report,
    )
    monkeypatch.setattr(
        app,
        "_semantic_contract_readback",
        lambda: {"ok": True, "failures": [], "violations": []},
    )
    monkeypatch.setattr(app, "kg", lambda *_args, **_kwargs: [{"ok": 1}])
    monkeypatch.setattr(app.MONGO, "command", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        app.MONGO, "list_collection_names", lambda *_args, **_kwargs: []
    )
    monkeypatch.setattr(app._container, "acquire_writer_lease", lambda: True)
    monkeypatch.setattr(app._container, "writer_lease_ready", lambda: True)
    monkeypatch.setattr(app._container, "release_writer_lease", lambda: None)


def _set_runtime_pins(monkeypatch, receipt, file_sha):
    configured = {
        "LAKATOS_STORAGE_PREDEPLOY_RECEIPT": str(receipt),
        "LAKATOS_STORAGE_PREDEPLOY_RECEIPT_SHA256": file_sha,
        "LAKATOS_STORAGE_ENVIRONMENT": "staging",
        "LAKATOS_STORAGE_FENCE_VERIFIER_SHA256": "f" * 64,
        "LAKATOS_STORAGE_FENCE_PUBLIC_KEY_HEX": _fence_public_key_hex(),
    }
    for key, value in configured.items():
        monkeypatch.setenv(key, value)
    return configured


def test_all_runtime_pins_valid_reach_readyz_and_mutation_gate(
    tmp_path, monkeypatch
):
    receipt, file_sha, _target = _sealed_predeploy_receipt(
        tmp_path, monkeypatch
    )
    _set_runtime_pins(monkeypatch, receipt, file_sha)

    import server.app as app

    _patch_healthy_storage_runtime(app, monkeypatch)

    state = app._refresh_storage_contract_state()

    assert state["ok"] is True
    assert TestClient(app.app).get("/readyz").status_code == 200
    app._require_critique_history_ready()


@pytest.mark.parametrize(
    ("pin", "replacement"),
    [
        ("LAKATOS_STORAGE_PREDEPLOY_RECEIPT", None),
        ("LAKATOS_STORAGE_PREDEPLOY_RECEIPT", "missing"),
        ("LAKATOS_STORAGE_PREDEPLOY_RECEIPT_SHA256", None),
        ("LAKATOS_STORAGE_PREDEPLOY_RECEIPT_SHA256", "0" * 64),
        ("LAKATOS_STORAGE_ENVIRONMENT", None),
        ("LAKATOS_STORAGE_ENVIRONMENT", "production"),
        ("LAKATOS_STORAGE_FENCE_VERIFIER_SHA256", None),
        ("LAKATOS_STORAGE_FENCE_VERIFIER_SHA256", "0" * 64),
        ("LAKATOS_STORAGE_FENCE_PUBLIC_KEY_HEX", None),
        ("LAKATOS_STORAGE_FENCE_PUBLIC_KEY_HEX", "0" * 64),
    ],
)
def test_each_runtime_pin_failure_reaches_cached_readyz_and_mutation_503(
    tmp_path, monkeypatch, pin, replacement
):
    receipt, file_sha, _target = _sealed_predeploy_receipt(
        tmp_path, monkeypatch
    )
    configured = _set_runtime_pins(monkeypatch, receipt, file_sha)
    if pin == "LAKATOS_STORAGE_PREDEPLOY_RECEIPT" and replacement == "missing":
        replacement = str((tmp_path / "missing-receipt.json").absolute())
    if replacement is None:
        monkeypatch.delenv(pin, raising=False)
    else:
        monkeypatch.setenv(pin, replacement)

    import server.app as app

    _patch_healthy_storage_runtime(app, monkeypatch)

    state = app._refresh_storage_contract_state()

    assert state["ok"] is False
    assert TestClient(app.app).get("/readyz").status_code == 503
    with pytest.raises(app.HTTPException) as exc:
        app._require_critique_history_ready()
    assert exc.value.status_code == 503


def _republish_receipt(tmp_path, source, mutate, name):
    body = module._strict_json_loads(source.read_bytes())
    body.pop("receipt_sha256")
    mutate(body)
    target = (tmp_path / name).absolute()
    module._publish_once(target, body)
    return target, hashlib.sha256(target.read_bytes()).hexdigest()


def test_runtime_receipt_verification_binds_file_artifact_operation_and_target(
    tmp_path, monkeypatch
):
    path, file_sha, target = _sealed_predeploy_receipt(tmp_path, monkeypatch)

    verified = module.verify_predeploy_receipt(
        path, file_sha, _runtime_settings(), object(), object()
    )

    assert verified["ok"] is True
    assert verified["file_sha256"] == file_sha
    assert verified["target_sha256"] == target["sha256"]
    with pytest.raises(ValueError, match="file SHA-256 mismatch"):
        module.verify_predeploy_receipt(
            path, "0" * 64, _runtime_settings(), object(), object()
        )


def test_runtime_receipt_verification_rejects_live_target_drift(tmp_path, monkeypatch):
    path, file_sha, _target = _sealed_predeploy_receipt(tmp_path, monkeypatch)
    monkeypatch.setattr(
        module,
        "target_identity",
        lambda *_args: {"sha256": "9" * 64, "details": {"drift": True}},
    )
    with pytest.raises(ValueError, match="target-mismatched"):
        module.verify_predeploy_receipt(
            path, file_sha, _runtime_settings(), object(), object()
        )


def test_runtime_receipt_rejects_legacy_receipt_and_fence_schemas(
    tmp_path, monkeypatch
):
    source, _file_sha, _target = _sealed_predeploy_receipt(tmp_path, monkeypatch)

    legacy_receipt, legacy_receipt_sha = _republish_receipt(
        tmp_path,
        source,
        lambda body: body.update(
            schema_version="lakatotree-storage-predeploy-receipt/v3"
        ),
        "legacy-receipt.json",
    )
    with pytest.raises(ValueError):
        module.verify_predeploy_receipt(
            legacy_receipt,
            legacy_receipt_sha,
            _runtime_settings(),
            object(),
            object(),
        )

    def legacy_fence(body):
        live = body["writer_drain"]["live_fence"]
        signed_body = dict(live["signed_response"])
        signed_body.pop("signature")
        signed_body["schema_version"] = "lakatotree-writer-fence-verification/v1"
        live["schema_version"] = signed_body["schema_version"]
        live["signed_response"] = _sign_fence_response(signed_body)

    legacy_fence_path, legacy_fence_sha = _republish_receipt(
        tmp_path, source, legacy_fence, "legacy-fence.json"
    )
    with pytest.raises(ValueError):
        module.verify_predeploy_receipt(
            legacy_fence_path,
            legacy_fence_sha,
            _runtime_settings(),
            object(),
            object(),
        )


@pytest.mark.parametrize("tamper", ["signed_field", "signature", "fingerprint"])
def test_runtime_receipt_rejects_resealed_fence_tampering(
    tmp_path, monkeypatch, tamper
):
    source, _file_sha, _target = _sealed_predeploy_receipt(tmp_path, monkeypatch)

    def mutate(body):
        live = body["writer_drain"]["live_fence"]
        if tamper == "signed_field":
            live["signed_response"]["lease_id"] = "attacker-lease"
        elif tamper == "signature":
            live["signed_response"]["signature"] = "0" * 128
        else:
            live["authority_key_sha256"] = "0" * 64

    path, file_sha = _republish_receipt(
        tmp_path, source, mutate, f"tampered-{tamper}.json"
    )
    with pytest.raises(ValueError):
        module.verify_predeploy_receipt(
            path, file_sha, _runtime_settings(), object(), object()
        )


def test_runtime_receipt_accepts_exact_pending_only_neo_shape(tmp_path, monkeypatch):
    neo = {
        "ok": False,
        "migration_ok": True,
        "payload_normalization": {
            "schema_version": module.NORMALIZATION_RECEIPT_SCHEMA,
            "before": {"row_count": 0, "projection_sha256": "a" * 64},
            "after": {"row_count": 0, "projection_sha256": "a" * 64},
            "updated_count": 0,
        },
        "report": {
            "contract_id": module.CONTRACT_ID,
            "ok": False,
            "failures": ["neo4j.outbox.pending"],
            "details": {},
        },
    }
    path, file_sha, _target = _sealed_predeploy_receipt(
        tmp_path, monkeypatch, neo=neo
    )
    assert module.verify_predeploy_receipt(
        path, file_sha, _runtime_settings(), object(), object()
    )["ok"] is True


@pytest.mark.parametrize(
    "mutate",
    [
        lambda block: block.clear(),
        lambda block: block.update(updated_count=True),
        lambda block: block["before"].update(row_count=2),
        lambda block: block["after"].update(projection_sha256="0" * 64),
        lambda block: block.update(extra="forbidden"),
    ],
)
def test_runtime_receipt_rejects_resealed_normalization_tampering(
    tmp_path, monkeypatch, mutate
):
    source, _file_sha, _target = _sealed_predeploy_receipt(tmp_path, monkeypatch)

    def tamper(body):
        mutate(body["neo4j"]["payload_normalization"])

    path, file_sha = _republish_receipt(
        tmp_path, source, tamper, "tampered-normalization.json"
    )
    with pytest.raises(ValueError, match="postflight success"):
        module.verify_predeploy_receipt(
            path, file_sha, _runtime_settings(), object(), object()
        )


@pytest.mark.parametrize(
    "neo",
    [
        {
            "ok": False, "migration_ok": True,
            "report": {"contract_id": module.CONTRACT_ID, "ok": False},
        },
        {
            "ok": False, "migration_ok": True,
            "report": {
                "contract_id": module.CONTRACT_ID,
                "ok": False,
                "failures": None,
            },
        },
        {
            "ok": False, "migration_ok": True,
            "report": {
                "contract_id": module.CONTRACT_ID,
                "ok": False,
                "failures": ["neo4j.outbox.pending", "neo4j.outbox.pending"],
            },
        },
        {
            "ok": False, "migration_ok": True,
            "report": {
                "contract_id": module.CONTRACT_ID,
                "ok": False,
                "failures": [],
            },
        },
        {
            "ok": True, "migration_ok": True,
            "report": {
                "contract_id": module.CONTRACT_ID,
                "ok": True,
                "failures": ["neo4j.outbox.pending"],
            },
        },
    ],
)
def test_runtime_receipt_rejects_malformed_neo_shapes(tmp_path, monkeypatch, neo):
    path, file_sha, _target = _sealed_predeploy_receipt(
        tmp_path, monkeypatch, neo=neo
    )
    with pytest.raises(ValueError, match="postflight success"):
        module.verify_predeploy_receipt(
            path, file_sha, _runtime_settings(), object(), object()
        )


@pytest.mark.parametrize(
    "settings",
    [
        SimpleNamespace(
            storage_environment="production",
            storage_fence_verifier_sha256="f" * 64,
            storage_fence_public_key_hex=_fence_public_key_hex(),
        ),
        SimpleNamespace(
            storage_environment="staging",
            storage_fence_verifier_sha256="0" * 64,
            storage_fence_public_key_hex=_fence_public_key_hex(),
        ),
        SimpleNamespace(
            storage_environment="staging",
            storage_fence_verifier_sha256="f" * 64,
            storage_fence_public_key_hex="0" * 64,
        ),
    ],
)
def test_runtime_receipt_rejects_unpinned_environment_or_fence_authority(
    tmp_path, monkeypatch, settings
):
    path, file_sha, _target = _sealed_predeploy_receipt(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        module.verify_predeploy_receipt(
            path, file_sha, settings, object(), object()
        )
