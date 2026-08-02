"""Negative-control tests for the read-only live readiness collector."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from server import production_readiness_live as live
from server import runtime_authority as runtime_authority
from server import storage_access as access


FIXED_NOW = datetime(2026, 8, 2, 3, 4, 5, tzinfo=timezone.utc)
EXPECTED_GIT_SHA = "5de2727bd6e9dec952fc5052bc6576180b5eb027"


def _canonical(value) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _request(**adapter_overrides):
    adapters = {
        "runtime": {
            "base_url": "http://127.0.0.1:55170",
            "expected_git_sha": EXPECTED_GIT_SHA,
        },
        "postgresql": {
            "database": "lakatos",
            "owner_role": "lakatos_owner",
            "migrator_role": "lakatos_migrator",
            "runtime_role": "lakatos_runtime",
        },
        "neo4j": {
            "database": "neo4j",
        },
        "predeploy": {
            "path": "/var/lib/lakatotree/predeploy.json",
            "file_sha256": "a" * 64,
        },
        "temporal": {
            "authority_policy": {"path": "/evidence/policy.json", "file_sha256": "b" * 64},
            "sidecar": {"path": "/evidence/sidecar.json", "file_sha256": "c" * 64},
            "runtime_binding": {"path": "/evidence/binding.json", "file_sha256": "d" * 64},
        },
    }
    adapters.update(adapter_overrides)
    return {
        "schema_version": live.REQUEST_SCHEMA,
        "target_id": "production-ct301",
        "timeout_seconds": 3,
        "adapters": adapters,
    }


def _request_v2(**adapter_overrides):
    request = _request(**adapter_overrides)
    request["schema_version"] = live.REQUEST_SCHEMA_V2
    request["challenge_nonce"] = "9" * 64
    if request["adapters"]["postgresql"] is not None:
        request["adapters"]["postgresql"].update({
            "audit_role": "lakatos_audit",
            "host": "127.0.0.1",
            "port": 5432,
        })
    if request["adapters"]["neo4j"] is not None:
        request["adapters"]["neo4j"].update({
            "audit_user": "lakatos_audit_user",
            "audit_role": "lakatos_audit_role",
            "migrator_user": "lakatos_migrator_user",
            "migrator_role": "lakatos_migrator_role",
            "runtime_user": "lakatos_runtime_user",
            "runtime_role": "lakatos_runtime_role",
        })
    return request


def _request_v3(*, public_key: str, **adapter_overrides):
    request = _request_v2(**adapter_overrides)
    request["schema_version"] = live.REQUEST_SCHEMA_V3
    request["adapters"]["runtime"] = {
        "base_url": "http://127.0.0.1:55170",
        "expected_artifact": {
            "kind": "git",
            "source_commit": EXPECTED_GIT_SHA,
        },
        "runtime_authority_public_key_hex": public_key,
    }
    return request


def test_v2_requires_distinct_dedicated_audit_principals_and_full_source_sha():
    request = _request_v2()
    assert live.validate_request(request) is request

    changed = json.loads(json.dumps(request))
    changed["adapters"]["postgresql"]["audit_role"] = "lakatos_runtime"
    with pytest.raises(live.CollectionInputError, match="pairwise distinct"):
        live.validate_request(changed)

    changed = json.loads(json.dumps(request))
    changed["adapters"]["neo4j"]["audit_role"] = "admin"
    with pytest.raises(live.CollectionInputError, match="custom roles"):
        live.validate_request(changed)

    changed = json.loads(json.dumps(request))
    changed["adapters"]["runtime"]["expected_git_sha"] = "5de2727"
    with pytest.raises(live.CollectionInputError, match="full Git SHA"):
        live.validate_request(changed)

    changed = json.loads(json.dumps(request))
    changed["adapters"]["neo4j"]["database"] = "system"
    with pytest.raises(live.CollectionInputError, match="application database"):
        live.validate_request(changed)

    for database in ("*", "DEFAULT", "neo4j.", "-neo4j", "systemfoo"):
        changed = json.loads(json.dumps(request))
        changed["adapters"]["neo4j"]["database"] = database
        with pytest.raises(live.CollectionInputError, match="canonical"):
            live.validate_request(changed)


def test_legacy_v1_short_git_pin_matches_new_full_runtime_identity_only_forward():
    full = "5de2727" + "a" * 33
    assert live._git_sha_match(full, "5de2727") is True
    assert live._git_sha_match("5de2727", full) is False
    assert live._git_sha_match("5de2728" + "a" * 33, "5de2727") is False


def test_v3_requires_exact_artifact_union_and_runtime_authority_key():
    _private, public = _runtime_keypair()
    request = _request_v3(public_key=public)
    assert live.validate_request(request) is request

    changed = json.loads(json.dumps(request))
    changed["adapters"]["runtime"]["expected_artifact"]["source_commit"] = "a" * 7
    with pytest.raises(live.CollectionInputError, match="expected_artifact"):
        live.validate_request(changed)

    changed = json.loads(json.dumps(request))
    changed["adapters"]["runtime"]["runtime_authority_public_key_hex"] = "a" * 63
    with pytest.raises(live.CollectionInputError, match="SHA-256"):
        live.validate_request(changed)


@pytest.mark.parametrize(
    ("version", "supported"),
    [
        ("2026.03.0", True),
        ("2026.06.0", True),
        ("2026.06.1", True),
        ("2026.02.9", False),
        ("2026.07.0", False),
        ("2027.01.0", False),
        ("2026.3.0", False),
        ("2026.003.0", False),
        (" 2026.06.0", False),
        ("2026.06.01", False),
    ],
)
def test_neo4j_release_semantics_are_shared_and_explicit(version, supported):
    assert live._neo_version_supported(version) is supported
    assert access._neo_version_supported(version) is supported


def test_v1_cannot_smuggle_v2_audit_policy_fields():
    request = _request()
    request["adapters"]["postgresql"]["audit_role"] = "lakatos_audit"
    with pytest.raises(live.CollectionInputError, match="non-exact field set"):
        live.validate_request(request)


def _observed(name):
    def port(config, timeout, environ):
        assert isinstance(config, dict)
        assert 0 < timeout <= 3
        assert environ == {}
        return live.AdapterResult("OBSERVED", {"source": name, "read_only": True})

    return port


def _all_observed_ports():
    return live.CollectorPorts(
        runtime=_observed("runtime"),
        postgresql=_observed("postgresql"),
        neo4j=_observed("neo4j"),
        predeploy=_observed("predeploy"),
        temporal=_observed("temporal"),
    )


def test_complete_collection_is_digest_bound_but_never_self_approves():
    request = _request()
    request_sha = hashlib.sha256(_canonical(request)).hexdigest()

    evidence = live.collect_live_evidence(
        request,
        request_file_sha256=request_sha,
        ports=_all_observed_ports(),
        environ={"SAFE": "1"},
        now=lambda: FIXED_NOW,
    )

    assert evidence["status"] == "COLLECTION_COMPLETE"
    assert evidence["request_file_sha256"] == request_sha
    assert evidence["request_bytes_bound"] is False
    assert evidence["adapter_order"] == list(live.ADAPTER_NAMES)
    assert evidence["collection_failures"] == []
    assert evidence["collector_profile"] == "in-process-unattested"
    assert evidence["verification_status"] == "UNVERIFIED"
    assert evidence["snapshot_coherence"] == "UNATTESTED"
    assert evidence["cross_source_binding"] == "UNVERIFIED"
    assert "mutation_attempts" not in evidence
    body = dict(evidence)
    observed_digest = body.pop("evidence_body_sha256")
    assert observed_digest == hashlib.sha256(_canonical(body)).hexdigest()
    encoded = json.dumps(evidence, sort_keys=True).lower()
    for forbidden in ("production_ready", "harness_green", "l3_assurance", "deployment_status"):
        assert forbidden not in encoded
    assert "never production approval" in evidence["claim_boundary"]


def test_missing_sources_are_explicit_and_fail_closed():
    request = _request(
        runtime=None,
        postgresql=None,
        neo4j=None,
        predeploy=None,
        temporal=None,
    )
    evidence = live.collect_live_evidence(
        request,
        request_file_sha256=hashlib.sha256(_canonical(request)).hexdigest(),
        ports=_all_observed_ports(),
        environ={"SAFE": "1"},
        now=lambda: FIXED_NOW,
    )

    assert evidence["status"] == "COLLECTION_INCOMPLETE"
    assert evidence["collection_failures"] == [
        "neo4j.not_configured",
        "postgresql.not_configured",
        "predeploy.not_configured",
        "runtime.not_configured",
        "temporal.not_configured",
    ]
    assert all(
        evidence["adapters"][name] == {
            "status": "NOT_CONFIGURED",
            "facts": {},
            "failure_codes": [f"{name}.not_configured"],
        }
        for name in live.ADAPTER_NAMES
    )


def test_adapter_exceptions_and_authority_material_are_redacted():
    sensitive = "Bearer super-secret postgres://admin:hunter2@database"

    def raises(config, timeout, environ):
        raise RuntimeError(sensitive)

    ports = live.CollectorPorts(
        runtime=raises,
        postgresql=_observed("postgresql"),
        neo4j=_observed("neo4j"),
        predeploy=_observed("predeploy"),
        temporal=_observed("temporal"),
    )
    request = _request()
    evidence = live.collect_live_evidence(
        request,
        request_file_sha256=hashlib.sha256(_canonical(request)).hexdigest(),
        ports=ports,
        environ={"SAFE": "1"},
        now=lambda: FIXED_NOW,
    )
    encoded = json.dumps(evidence, sort_keys=True)
    assert evidence["adapters"]["runtime"] == {
        "status": "UNAVAILABLE",
        "facts": {},
        "failure_codes": ["runtime.collection_failed"],
    }
    assert sensitive not in encoded
    assert "hunter2" not in encoded

    def leaks(config, timeout, environ):
        return live.AdapterResult("OBSERVED", {"password": "hunter2"})

    leaked_ports = live.CollectorPorts(
        runtime=leaks,
        postgresql=_observed("postgresql"),
        neo4j=_observed("neo4j"),
        predeploy=_observed("predeploy"),
        temporal=_observed("temporal"),
    )
    rejected = live.collect_live_evidence(
        request,
        request_file_sha256=hashlib.sha256(_canonical(request)).hexdigest(),
        ports=leaked_ports,
        environ={"SAFE": "1"},
        now=lambda: FIXED_NOW,
    )
    assert rejected["adapters"]["runtime"]["failure_codes"] == [
        "runtime.collection_failed"
    ]
    assert "hunter2" not in json.dumps(rejected, sort_keys=True)


@pytest.mark.parametrize(
    "base_url",
    [
        "http://192.168.0.26:55170",
        "https://example.com:443",
        "http://user:password@127.0.0.1:55170",
        "http://127.0.0.1:55170/path",
        "http://127.0.0.1:55170?token=x",
    ],
)
def test_runtime_origin_is_loopback_credential_free_and_pathless(base_url):
    request = _request()
    request["adapters"]["runtime"]["base_url"] = base_url
    with pytest.raises(live.CollectionInputError, match="loopback HTTP origin"):
        live.validate_request(request)


@pytest.mark.parametrize("field", ["token_env", "dsn_env", "uri_env", "password_env"])
def test_request_rejects_operator_selected_credential_environment_fields(field):
    request = _request()
    target = "runtime" if field == "token_env" else "postgresql" if field == "dsn_env" else "neo4j"
    request["adapters"][target][field] = "ATTACKER_SELECTED_SECRET"
    with pytest.raises(live.CollectionInputError, match="non-exact field set"):
        live.validate_request(request)


def test_request_loader_requires_absolute_regular_pinned_unambiguous_json(tmp_path, monkeypatch):
    request = _request()
    raw = _canonical(request)
    path = (tmp_path / "request.json").resolve()
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    loaded = live.load_request(path, digest)
    assert loaded.raw == raw
    assert loaded.file_sha256 == digest
    bound = live.collect_loaded_request(
        loaded,
        ports=_all_observed_ports(),
        environ={"SAFE": "1"},
        now=lambda: FIXED_NOW,
    )
    assert bound["request_bytes_bound"] is True
    with pytest.raises(live.CollectionInputError, match="no longer match"):
        live.collect_loaded_request(
            live.LoadedRequest(raw=raw + b" ", file_sha256=digest, value=loaded.value),
            ports=_all_observed_ports(),
            environ={"SAFE": "1"},
            now=lambda: FIXED_NOW,
        )

    monkeypatch.chdir(tmp_path)
    with pytest.raises(live.CollectionInputError, match="absolute"):
        live.load_request(Path("request.json"), digest)
    with pytest.raises(live.CollectionInputError, match="mismatch"):
        live.load_request(path, "0" * 64)

    symlink = tmp_path / "request-link.json"
    symlink.symlink_to(path)
    with pytest.raises(live.CollectionInputError, match="non-symlink"):
        live.load_request(symlink.absolute(), digest)

    duplicate = (tmp_path / "duplicate.json").resolve()
    duplicate.write_bytes(b'{"schema_version":"a","schema_version":"b"}')
    with pytest.raises(live.CollectionInputError, match="duplicate"):
        live.load_request(duplicate, hashlib.sha256(duplicate.read_bytes()).hexdigest())


class _RuntimeHandler(BaseHTTPRequestHandler):
    calls: list[tuple[str, str, str | None]] = []

    def do_GET(self):  # noqa: N802
        type(self).calls.append((self.command, self.path, self.headers.get("Authorization")))
        responses = {
            "/healthz": (503, {"status": "degraded", "services": {"neo4j": "ok", "pg": "down"}}),
            "/readyz": (404, {"detail": "Not Found"}),
            "/version": (
                200,
                {
                    "boot_git_sha": EXPECTED_GIT_SHA,
                    "disk_head_sha": EXPECTED_GIT_SHA,
                    "stale": False,
                    "identity_verified": True,
                    "auth_posture": "token_required",
                    "freshness_gate": "on",
                    "secret": "must-not-leak",
                },
            ),
            "/api/ops/outbox-status": (200, {"pending": 247, "token": "must-not-leak"}),
        }
        status_code, body = responses[self.path]
        raw = _canonical(body)
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format, *args):  # noqa: A002
        return


class _SlowRuntimeHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        raw = _canonical({"status": "ok", "padding": "x" * 64})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        try:
            for byte in raw:
                self.wfile.write(bytes([byte]))
                self.wfile.flush()
                time.sleep(0.03)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, format, *args):  # noqa: A002
        return


def test_runtime_adapter_uses_only_credential_free_bounded_gets_and_ignores_proxies(monkeypatch):
    _RuntimeHandler.calls = []
    server = HTTPServer(("127.0.0.1", 0), _RuntimeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:1")
    try:
        config = {
            "base_url": f"http://127.0.0.1:{server.server_port}",
            "expected_git_sha": EXPECTED_GIT_SHA,
        }
        result = live.collect_runtime(config, 3, {})
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)

    assert result.status == "OBSERVED"
    assert result.failure_codes == ()
    assert [call[:2] for call in _RuntimeHandler.calls] == [
        ("GET", "/healthz"),
        ("GET", "/readyz"),
        ("GET", "/version"),
        ("GET", "/api/ops/outbox-status"),
    ]
    assert all(call[2] is None for call in _RuntimeHandler.calls)
    assert result.facts["healthz"]["http_status"] == 503
    assert result.facts["readyz"]["http_status"] == 404
    assert result.facts["version"]["boot_matches_expected"] is True
    assert result.facts["outbox"]["pending"] == 247
    encoded = json.dumps(result.facts, sort_keys=True)
    assert "must-not-leak" not in encoded
    assert config["base_url"] not in encoded


def _runtime_keypair():
    private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("19" * 32))
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    ).hex()
    return private, public


def _signed_runtime_snapshot(*, mutate=None) -> tuple[bytes, str, dict]:
    private, public = _runtime_keypair()
    boot_id = "e" * 64
    artifact = {"kind": "git", "source_commit": EXPECTED_GIT_SHA}
    challenge = runtime_authority.build_runtime_challenge(
        nonce="d" * 64,
        environment="production",
        boot_id=boot_id,
        artifact=artifact,
        operation_sha256="1" * 64,
        target_sha256="2" * 64,
        storage_access_policy_file_sha256="3" * 64,
        predeploy_receipt_file_sha256="4" * 64,
        predeploy_receipt_sha256="5" * 64,
        startup_bundle_file_sha256="6" * 64,
        historical_drain_lease_id_sha256="7" * 64,
        runtime_writer_lease={
            "lease_id": "critique-history-writer-v1",
            "owner_token_sha256": "c" * 64,
            "generation": 9,
            "postgresql_backend_pid": 4242,
            "postgresql_advisory_key": [1279349588, 20260802],
        },
        workers=[{"worker_id": "8" * 64, "boot_id": boot_id}],
    )
    observed = datetime.now(timezone.utc)
    body = {
        "schema_version": runtime_authority.RUNTIME_SNAPSHOT_SCHEMA,
        "challenge_sha256": runtime_authority.challenge_sha256(challenge),
        **{
            key: value
            for key, value in challenge.items()
            if key != "schema_version"
        },
        "active": True,
        "observed_at": observed.isoformat(),
        "expires_at": (observed + timedelta(seconds=20)).isoformat(),
        "evidence_refs": ["9" * 64],
    }
    if mutate is not None:
        mutate(body)
    raw = runtime_authority.canonical_json({
        **body,
        "signature": private.sign(runtime_authority.signing_bytes(body)).hex(),
    })
    return raw, public, artifact


class _RuntimeV3Handler(BaseHTTPRequestHandler):
    calls: list[str] = []
    authority_raw: bytes = b"{}"

    def do_GET(self):  # noqa: N802
        type(self).calls.append(self.path)
        if self.path == "/api/ops/runtime-authority-snapshot":
            status_code = 200
            raw = type(self).authority_raw
        else:
            bodies = {
                "/healthz": {"status": "degraded", "services": {}},
                "/readyz": {"status": "degraded", "services": {}},
                "/version": {
                    "boot_git_sha": EXPECTED_GIT_SHA,
                    "disk_head_sha": EXPECTED_GIT_SHA,
                    "stale": False,
                    "identity_verified": True,
                },
                "/api/ops/outbox-status": {"pending": 0},
            }
            status_code = 200
            raw = _canonical(bodies[self.path])
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format, *args):  # noqa: A002
        return


def test_runtime_v3_verifies_one_cached_snapshot_and_redacts_authority_material():
    raw, public, artifact = _signed_runtime_snapshot()
    _RuntimeV3Handler.calls = []
    _RuntimeV3Handler.authority_raw = raw
    server = HTTPServer(("127.0.0.1", 0), _RuntimeV3Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        config = {
            "base_url": f"http://127.0.0.1:{server.server_port}",
            "expected_artifact": artifact,
            "runtime_authority_public_key_hex": public,
        }
        result = live.collect_runtime(config, 3, {})
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)

    assert result.status == "OBSERVED"
    assert _RuntimeV3Handler.calls == [
        "/healthz",
        "/readyz",
        "/version",
        "/api/ops/outbox-status",
        "/api/ops/runtime-authority-snapshot",
    ]
    authority_fact = result.facts["runtime_authority"]
    assert authority_fact["status"] == "VERIFIED_SIGNED_SNAPSHOT"
    assert authority_fact["effect_scope"] == "critique-history-ledger/v1"
    assert result.binding_material["target_sha256"] == "2" * 64
    encoded = json.dumps(result.facts, sort_keys=True)
    envelope = json.loads(raw)
    for forbidden in (
        envelope["nonce"],
        envelope["signature"],
        envelope["runtime_writer_lease"]["owner_token_sha256"],
        public,
        config["base_url"],
    ):
        assert forbidden not in encoded


def test_runtime_v3_rejects_resigned_artifact_splice():
    raw, public, artifact = _signed_runtime_snapshot(
        mutate=lambda body: body["artifact"].update(source_commit="a" * 40)
    )
    _RuntimeV3Handler.calls = []
    _RuntimeV3Handler.authority_raw = raw
    server = HTTPServer(("127.0.0.1", 0), _RuntimeV3Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = live.collect_runtime(
            {
                "base_url": f"http://127.0.0.1:{server.server_port}",
                "expected_artifact": artifact,
                "runtime_authority_public_key_hex": public,
            },
            3,
            {},
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)

    assert result.status == "PARTIAL"
    assert result.failure_codes == ("runtime.authority.invalid",)
    assert result.facts["runtime_authority"]["status"] == "INVALID"


def test_runtime_fetch_enforces_absolute_deadline_against_slow_trickle():
    server = HTTPServer(("127.0.0.1", 0), _SlowRuntimeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    started = time.monotonic()
    try:
        with pytest.raises(live._PortUnavailable, match="deadline|unavailable"):
            live._runtime_fetch(
                f"http://127.0.0.1:{server.server_port}/healthz",
                timeout=0.15,
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    assert time.monotonic() - started < 0.8


def test_predeploy_and_temporal_ports_emit_digests_not_signatures_or_dids(tmp_path):
    predeploy_body = {
        "schema_version": "lakatotree-storage-predeploy-receipt/v5",
        "contract_id": "lakatotree-critique-history-storage/v1",
        "environment": "production",
        "target_sha256": "1" * 64,
        "operation": {"sha256": "2" * 64},
        "writer_drain": {"live_fence": {"signed_response": {"signature": "sensitive-signature"}}},
        "created_at": "2026-08-02T00:00:00+00:00",
    }
    predeploy = {
        **predeploy_body,
        "receipt_sha256": hashlib.sha256(_canonical(predeploy_body)).hexdigest(),
    }
    predeploy_path = (tmp_path / "predeploy.json").resolve()
    predeploy_path.write_bytes(_canonical(predeploy))
    os.chmod(predeploy_path, 0o400)
    predeploy_config = {
        "path": str(predeploy_path),
        "file_sha256": hashlib.sha256(predeploy_path.read_bytes()).hexdigest(),
    }
    predeploy_result = live.collect_predeploy(predeploy_config, 3, {})
    assert predeploy_result.status == "OBSERVED"
    assert predeploy_result.facts["self_digest_valid"] is True
    assert predeploy_result.facts["signed_fence_present"] is True
    assert "sensitive-signature" not in json.dumps(predeploy_result.facts, sort_keys=True)

    documents = {
        "authority_policy": {
            "schema_version": "lakatotree-temporal-authority-policy/v1",
            "producer_dids": ["did:key:sensitive-producer"],
        },
        "sidecar": {
            "schema_version": "lakatotree-two-ended-temporal-sidecar/v1",
            "prediction_anchors": [{"signature": "sensitive-prediction"}],
            "verdict_anchors": [{"signature": "sensitive-verdict"}],
        },
        "runtime_binding": {
            "schema_version": "lakatotree-temporal-runtime-binding/v1",
            "sidecar_sha256": "3" * 64,
            "receipt_graph_sha256": "4" * 64,
        },
    }
    documents["runtime_binding"]["sidecar_sha256"] = hashlib.sha256(
        live._TEMPORAL_SIDECAR_DOMAIN + _canonical(documents["sidecar"])
    ).hexdigest()
    temporal_config = {}
    for name, document in documents.items():
        path = (tmp_path / f"{name}.json").resolve()
        path.write_bytes(_canonical(document))
        temporal_config[name] = {
            "path": str(path),
            "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    temporal_result = live.collect_temporal(temporal_config, 3, {})
    encoded = json.dumps(temporal_result.facts, sort_keys=True)
    assert temporal_result.status == "OBSERVED"
    assert temporal_result.facts["prediction_anchor_count"] == 1
    assert temporal_result.facts["verdict_anchor_count"] == 1
    assert temporal_result.facts["sidecar_binding_matches"] is True
    for secret in (
        "did:key:sensitive-producer",
        "sensitive-prediction",
        "sensitive-verdict",
    ):
        assert secret not in encoded


def test_postgresql_endpoint_is_single_pinned_and_timer_cancel_is_silent(capsys, monkeypatch):
    import psycopg2

    host, port, parameters = live._validated_pg_endpoint(
        psycopg2,
        "host=db.example hostaddr=127.0.0.1 port=5432 dbname=lakatos "
        "user=a password=b sslmode=verify-full sslrootcert=system",
        "lakatos",
    )
    assert (host, port) == ("db.example", 5432)
    assert parameters["user"] == "a"
    assert parameters["sslmode"] == "verify-full"
    assert parameters["channel_binding"] == "require"
    assert parameters["target_session_attrs"] == "read-only"
    assert parameters["options"] == (
        "-c search_path=pg_catalog -c default_transaction_read_only=on"
    )

    with pytest.raises(live._PortUnavailable, match="pinned target"):
        live._validated_pg_endpoint(
            psycopg2,
            "host=127.0.0.1 hostaddr=192.0.2.10 port=5432 "
            "dbname=lakatos user=a password=b sslmode=verify-full "
            "sslrootcert=system",
            "lakatos",
            expected_host="127.0.0.1",
            expected_port=5432,
        )
    assert parameters["require_auth"] == "scram-sha-256"
    assert parameters["sslcertmode"] == "disable"
    assert parameters["sslcert"] == parameters["sslkey"] == parameters["sslpassword"] == ""
    for dsn in (
        "host=db.example port=5432 dbname=lakatos",
        "host=127.0.0.1,127.0.0.2 port=5432,5433 dbname=lakatos",
        "service=production dbname=lakatos",
        "host=127.0.0.1 port=5432 dbname=other",
        "host=db.example hostaddr=127.0.0.1 port=5432 dbname=lakatos "
        "user=a password=b sslmode=disable sslrootcert=system",
    ):
        with pytest.raises(live._PortUnavailable):
            live._validated_pg_endpoint(psycopg2, dsn, "lakatos")

    result = live.collect_postgresql(
        {
            "database": "lakatos",
            "owner_role": "owner",
            "migrator_role": "migrator",
            "runtime_role": "runtime",
        },
        1.5,
        {live.POSTGRESQL_DSN_ENV: "host=127.0.0.1 port=1 dbname=lakatos"},
    )
    assert result.failure_codes == ("postgresql.deadline_exhausted",)

    monkeypatch.setenv("PGSERVICE", "must-not-be-consulted")
    result = live.collect_postgresql(
        {
            "database": "lakatos",
            "owner_role": "owner",
            "migrator_role": "migrator",
            "runtime_role": "runtime",
        },
        3,
        {
            live.POSTGRESQL_DSN_ENV: (
                "host=db.example hostaddr=127.0.0.1 port=5432 dbname=lakatos "
                "user=a password=b sslmode=verify-full sslrootcert=system"
            )
        },
    )
    assert result.failure_codes == ("postgresql.ambient_authority_present",)

    class BrokenCancel:
        def cancel(self):
            raise RuntimeError("driver-secret-must-not-reach-stderr")

    live._cancel_noexcept(BrokenCancel())
    assert "driver-secret" not in capsys.readouterr().err


def test_neo4j_endpoint_requires_literal_system_trusted_tls():
    assert live._validated_neo_uri("bolt+s://127.0.0.1:7687") == (
        "bolt+s://127.0.0.1:7687"
    )
    for uri in (
        "bolt://127.0.0.1:7687",
        "bolt+s://localhost:7687",
        "neo4j+s://127.0.0.1:7687",
        "bolt+s://db.example:7687",
    ):
        with pytest.raises(live._PortUnavailable):
            live._validated_neo_uri(uri)


def test_default_ports_expose_no_injected_transport_bypass():
    ports = live.default_ports()
    assert ports.postgresql is live.collect_postgresql
    assert ports.neo4j is live.collect_neo4j


def test_cross_source_target_recomputes_storage_predeploy_identity():
    pg = {
        "configured_host": "127.0.0.1",
        "configured_port": 5432,
        "configured_database": "lakatos",
        "database": "lakatos",
        "database_oid": "5",
        "server_address": "127.0.0.1",
        "server_port": 5432,
        "server_version_num": "160000",
        "system_identifier": "12345",
    }
    neo = {
        "configured_uri": "bolt://127.0.0.1:7687",
        "configured_database": "neo4j",
        "database_id": "neo-id",
        "database_name": "neo4j",
    }
    target_sha = hashlib.sha256(_canonical({"postgresql": pg, "neo4j": neo})).hexdigest()
    status, observed = live._cross_source_target(
        {
            "postgresql": pg,
            "neo4j": neo,
            "predeploy": {
                "target_sha256": target_sha,
                "structural_receipt_identity_valid": True,
            },
        }
    )
    assert status == "MATCHED_SEQUENTIAL"
    assert observed == target_sha
    mismatch, _ = live._cross_source_target(
        {
            "postgresql": pg,
            "neo4j": neo,
            "predeploy": {
                "target_sha256": "0" * 64,
                "structural_receipt_identity_valid": True,
            },
        }
    )
    assert mismatch == "MISMATCH"


def test_publish_once_is_private_canonical_and_never_overwrites(tmp_path):
    output = (tmp_path / "evidence.json").resolve()
    document = {"z": 1, "a": "value"}
    digest = live._publish_once(output, document)
    raw = output.read_bytes()
    assert raw == _canonical(document)
    assert digest == hashlib.sha256(raw).hexdigest()
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    with pytest.raises(live.CollectionInputError, match="already exists"):
        live._publish_once(output, document)

    real_parent = tmp_path / "real"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(live.CollectionInputError, match="non-symlink directory"):
        live._publish_once(linked_parent / "evidence.json", document)

    unsafe_parent = tmp_path / "unsafe"
    unsafe_parent.mkdir(mode=0o770)
    os.chmod(unsafe_parent, 0o770)
    with pytest.raises(live.CollectionInputError, match="owner-controlled"):
        live._publish_once((unsafe_parent / "evidence.json").resolve(), document)


def test_publish_once_reports_in_doubt_after_visibility_before_directory_fsync(
    tmp_path, monkeypatch
):
    output = (tmp_path / "in-doubt.json").resolve()
    real_fsync = live.os.fsync
    calls = 0

    def fail_directory_fsync(fd):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated directory fsync failure")
        return real_fsync(fd)

    monkeypatch.setattr(live.os, "fsync", fail_directory_fsync)
    with pytest.raises(live.PublicationInDoubt, match="in doubt"):
        live._publish_once(output, {"value": 1})
    assert output.exists()


def test_cli_writes_incomplete_evidence_and_returns_non_green(tmp_path, capsys):
    request = _request(
        runtime=None,
        postgresql=None,
        neo4j=None,
        predeploy=None,
        temporal=None,
    )
    request_path = (tmp_path / "request.json").resolve()
    request_path.write_bytes(_canonical(request))
    request_sha = hashlib.sha256(request_path.read_bytes()).hexdigest()
    output = (tmp_path / "evidence.json").resolve()

    exit_code = live.main(
        [
            "--request",
            str(request_path),
            "--request-sha256",
            request_sha,
            "--output",
            str(output),
        ]
    )
    captured = capsys.readouterr()
    receipt = json.loads(captured.out)
    evidence = json.loads(output.read_text())
    assert exit_code == 1
    assert receipt["status"] == "WRITTEN"
    assert receipt["collection_status"] == "COLLECTION_INCOMPLETE"
    assert evidence["status"] == "COLLECTION_INCOMPLETE"
    assert evidence["request_bytes_bound"] is True
    assert evidence["verification_status"] == "UNVERIFIED"
    assert evidence["snapshot_coherence"] == "UNATTESTED"
    assert "mutation_attempts" not in evidence

    assert live.main(
        [
            "--request",
            str(request_path),
            "--request-sha256",
            request_sha,
            "--output",
            str(output),
        ]
    ) == 2
    captured = capsys.readouterr()
    assert json.loads(captured.err)["status"] == "INVALID"


def test_source_contains_no_mutating_transport_or_database_statements():
    source = Path(live.__file__).read_text(encoding="utf-8")
    upper = source.upper()
    for forbidden in (
        'METHOD="POST"',
        'METHOD="PATCH"',
        'METHOD="DELETE"',
        'CURSOR.EXECUTE("INSERT',
        'CURSOR.EXECUTE("UPDATE',
        'CURSOR.EXECUTE("DELETE',
        'CURSOR.EXECUTE("ALTER',
        'CURSOR.EXECUTE("CREATE',
        'CURSOR.EXECUTE("DROP',
        "SESSION.RUN(\"CREATE",
        "SESSION.RUN(\"MERGE",
        "SESSION.RUN(\"SET",
        "SESSION.RUN(\"DELETE",
    ):
        assert forbidden not in upper
    assert "Authorization" not in source
    assert "socket.socket" in source
    assert "urllib.request" not in source
    assert "SHOW USER PRIVILEGES" in source
    assert "pg_catalog.aclexplode" in source
    assert "has_column_privilege" in source
    assert ".commit(" not in source
