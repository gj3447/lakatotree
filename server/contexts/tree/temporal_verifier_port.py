"""Bounded two-process port for Gate-4 independent temporal verification.

The application never holds the time-authority private key.  It challenges a
pinned external authority executable, then sends the signed exact bindings to a
separately pinned, engine-import-forbidden C1 verifier artifact.  Any process,
identity, protocol or cardinality doubt leaves the Gate-3 component at L2.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import secrets
import selectors
import stat
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Callable, Iterable, Mapping

from lakatos.verdicts import PREDICTION_RECEIPT_FIELDS_V3, RECEIPT_FIELDS_V7


BATCH_REQUEST_SCHEMA = "lakatotree-c1-two-ended-temporal-batch/v1"
PROOF_REQUEST_SCHEMA = "lakatotree-c1-two-ended-temporal-proof/v1"
BATCH_REPORT_SCHEMA = "lakatotree-c1-two-ended-temporal-report/v1"
TIME_AUTHORITY_CHALLENGE_SCHEMA = (
    "lakatotree-independent-time-authority-challenge/v1"
)
TIME_AUTHORITY_RESPONSE_SCHEMA = (
    "lakatotree-independent-time-authority-response/v1"
)
TIME_AUTHORITY_ATTESTATION_SCHEMA = (
    "lakatotree-independent-time-authority-attestation/v1"
)
TEMPORAL_ARTIFACT_SCHEMA = "lakatotree-c1-temporal-verifier-artifact/v1"
TEMPORAL_ARTIFACT_DOMAIN = b"lakatotree-c1-temporal-verifier-artifact/v1\0"
TIME_AUTHORITY_CHALLENGE_DOMAIN = (
    b"lakatotree-independent-time-authority-challenge/v1\0"
)
TEMPORAL_REQUEST_ID_DOMAIN = b"lakatotree-independent-temporal-request/v1\0"

TEMPORAL_ARTIFACT_FILES = (
    "_ed25519.py",
    "artifact.py",
    "jcs.py",
    "receipts.py",
    "temporal_cli.py",
    "temporal_sidecar.py",
)
_LOCAL_ARTIFACT_MODULES = frozenset(
    Path(name).stem for name in TEMPORAL_ARTIFACT_FILES
)
_ALLOWED_ARTIFACT_IMPORTS = (
    frozenset(sys.stdlib_module_names) | {"__future__"} | _LOCAL_ARTIFACT_MODULES
)
_EXTERNAL_TEMPORAL_SLOTS = threading.BoundedSemaphore(value=2)
RECEIPT_TRANSPORT_FIELDS = tuple(sorted(
    set(RECEIPT_FIELDS_V7)
    | set(PREDICTION_RECEIPT_FIELDS_V3)
    | {"receipt_sha", "receipt_kind"}
))

MAX_REQUEST_BYTES = 2 * 1024 * 1024
MAX_STDOUT_BYTES = 2 * 1024 * 1024
MAX_STDERR_BYTES = 8 * 1024
MAX_PROOFS = 64
PROCESS_TIMEOUT_SECONDS = 10
_HEX = frozenset("0123456789abcdef")

_CHALLENGE_PROOF_KEYS = frozenset({
    "request_id",
    "tree_incarnation_id",
    "tree",
    "tag",
    "authority_policy_sha256",
    "sidecar_sha256",
    "receipt_graph_sha256",
    "prediction_receipt_sha256",
    "verdict_receipt_sha256",
    "prediction_temporal_commitment_sha256",
    "witness_dids",
    "threshold",
})
_ATTESTATION_KEYS = frozenset({
    "schema_version",
    "challenge_sha256",
    "request_id",
    "signer_did",
    "tree_incarnation_id",
    "tree",
    "tag",
    "authority_policy_sha256",
    "sidecar_sha256",
    "receipt_graph_sha256",
    "prediction_receipt_sha256",
    "verdict_receipt_sha256",
    "prediction_temporal_commitment_sha256",
    "witness_dids",
    "threshold",
    "verifier_artifact_sha256",
    "verifier_python_sha256",
    "observed_at",
    "valid_until",
    "signature",
})
_VERIFIED_RESULT_KEYS = frozenset({
    "request_id",
    "status",
    "component_ok",
    "l3_eligible",
    "reason_code",
    "tree_incarnation_id",
    "tree",
    "tag",
    "authority_policy_sha256",
    "sidecar_sha256",
    "receipt_graph_sha256",
    "prediction_receipt_sha256",
    "verdict_receipt_sha256",
    "prediction_temporal_commitment_sha256",
    "threshold",
    "t1_latest",
    "t2_earliest",
    "independent_verifier",
    "time_authority",
    "independent_valid_until",
    "authority_identity_sha256s",
})
_REJECTED_RESULT_KEYS = frozenset({
    "request_id", "status", "component_ok", "l3_eligible", "reason_code",
})


class IndependentTemporalVerifierUnavailable(RuntimeError):
    """A Gate-4 authority or verifier could not produce exact evidence."""


class UnavailableIndependentTemporalVerifier:
    """Fail-closed port used for an explicitly requested but invalid profile."""

    def verify_batch(self, _candidates):
        raise IndependentTemporalVerifierUnavailable(
            "independent temporal verifier profile is unavailable"
        )


@dataclass(frozen=True)
class IndependentTemporalCandidate:
    request_id: str
    tree_incarnation_id: str
    tree: str
    tag: str
    current_head_sha256: str
    stored_sidecar_sha256: str
    authority_policy: Mapping[str, Any]
    sidecar: Mapping[str, Any]
    chain: tuple[str, ...]
    receipts: tuple[Mapping[str, Any], ...]
    authority_policy_sha256: str
    receipt_graph_sha256: str
    prediction_receipt_sha256: str
    verdict_receipt_sha256: str
    prediction_temporal_commitment_sha256: str
    witness_dids: tuple[str, ...]
    threshold: int

    def authority_binding(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "tree_incarnation_id": self.tree_incarnation_id,
            "tree": self.tree,
            "tag": self.tag,
            "authority_policy_sha256": self.authority_policy_sha256,
            "sidecar_sha256": self.stored_sidecar_sha256,
            "receipt_graph_sha256": self.receipt_graph_sha256,
            "prediction_receipt_sha256": self.prediction_receipt_sha256,
            "verdict_receipt_sha256": self.verdict_receipt_sha256,
            "prediction_temporal_commitment_sha256": (
                self.prediction_temporal_commitment_sha256
            ),
            "witness_dids": list(self.witness_dids),
            "threshold": self.threshold,
        }

    def c1_request(self, attestation: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": PROOF_REQUEST_SCHEMA,
            "request_id": self.request_id,
            "tree_incarnation_id": self.tree_incarnation_id,
            "tree": self.tree,
            "tag": self.tag,
            "current_head_sha256": self.current_head_sha256,
            "stored_sidecar_sha256": self.stored_sidecar_sha256,
            "authority_policy": dict(self.authority_policy),
            "sidecar": dict(self.sidecar),
            "chain": list(self.chain),
            "receipts": [dict(receipt) for receipt in self.receipts],
            "time_authority_attestation": dict(attestation),
        }


@dataclass(frozen=True)
class IndependentTemporalResult:
    request_id: str
    accepted: bool
    reason: str
    input_sha256: str
    sidecar_sha256: str | None = None
    authority_policy_sha256: str | None = None
    receipt_graph_sha256: str | None = None
    prediction_receipt_sha256: str | None = None
    verdict_receipt_sha256: str | None = None
    prediction_temporal_commitment_sha256: str | None = None
    threshold: int | None = None
    t1_latest: str | None = None
    t2_earliest: str | None = None
    independent_verifier: str | None = None
    time_authority: str | None = None
    independent_valid_until: str | None = None
    authority_identity_sha256s: tuple[str, ...] = ()


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise IndependentTemporalVerifierUnavailable(
            "temporal verifier value is not canonical JSON"
        ) from exc


def _unique_object(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise IndependentTemporalVerifierUnavailable(
                "temporal verifier output has duplicate keys"
            )
        out[key] = value
    return out


def _strict_json(raw: bytes, *, allow_trailing_newline: bool = False) -> dict[str, Any]:
    body = raw[:-1] if allow_trailing_newline and raw.endswith(b"\n") else raw
    if not body or (allow_trailing_newline and raw not in {body, body + b"\n"}):
        raise IndependentTemporalVerifierUnavailable(
            "temporal verifier output framing is invalid"
        )
    try:
        value = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda token: (_ for _ in ()).throw(
                IndependentTemporalVerifierUnavailable(
                    f"non-finite JSON is forbidden: {token}"
                )
            ),
        )
    except IndependentTemporalVerifierUnavailable:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise IndependentTemporalVerifierUnavailable(
            "temporal verifier output is invalid JSON"
        ) from exc
    if not isinstance(value, dict) or _canonical(value) != body:
        raise IndependentTemporalVerifierUnavailable(
            "temporal verifier output is not canonical"
        )
    return value


def _exact_sha(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in _HEX for char in value)
    )


def _regular_bytes(path: Path, *, label: str, maximum: int) -> tuple[Path, bytes]:
    if not path.is_absolute():
        raise IndependentTemporalVerifierUnavailable(f"{label} path is not absolute")
    try:
        before = path.lstat()
        resolved = path.resolve(strict=True)
        target = resolved.lstat()
    except OSError as exc:
        raise IndependentTemporalVerifierUnavailable(f"{label} is unavailable") from exc
    if (
        stat.S_ISLNK(before.st_mode)
        or stat.S_ISLNK(target.st_mode)
        or not stat.S_ISREG(target.st_mode)
    ):
        raise IndependentTemporalVerifierUnavailable(f"{label} is not a regular file")
    if not 0 < target.st_size <= maximum:
        raise IndependentTemporalVerifierUnavailable(f"{label} size is unsafe")
    try:
        raw = resolved.read_bytes()
        after = resolved.stat()
    except OSError as exc:
        raise IndependentTemporalVerifierUnavailable(f"{label} cannot be read") from exc
    if (
        len(raw) != target.st_size
        or (target.st_dev, target.st_ino, target.st_size, target.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    ):
        raise IndependentTemporalVerifierUnavailable(f"{label} changed during read")
    return resolved, raw


def temporal_artifact_sha256(directory: Path) -> tuple[str, dict[str, bytes]]:
    if not directory.is_absolute():
        raise IndependentTemporalVerifierUnavailable(
            "temporal verifier artifact directory is not absolute"
        )
    files: dict[str, bytes] = {}
    manifest = []
    for relative in TEMPORAL_ARTIFACT_FILES:
        _resolved, raw = _regular_bytes(
            directory / relative,
            label=f"temporal verifier artifact {relative}",
            maximum=2 * 1024 * 1024,
        )
        try:
            tree = ast.parse(raw, filename=relative)
        except (SyntaxError, ValueError) as exc:
            raise IndependentTemporalVerifierUnavailable(
                f"temporal verifier source is invalid: {relative}"
            ) from exc
        for node in ast.walk(tree):
            names: tuple[str, ...] = ()
            if isinstance(node, ast.Import):
                names = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                names = (node.module or "",)
            for name in names:
                root = name.split(".", 1)[0]
                if root and root not in _ALLOWED_ARTIFACT_IMPORTS:
                    raise IndependentTemporalVerifierUnavailable(
                        "temporal verifier import escapes pinned closure"
                    )
        files[relative] = raw
        manifest.append({
            "path": relative,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size": len(raw),
        })
    body = {"schema_version": TEMPORAL_ARTIFACT_SCHEMA, "files": manifest}
    return hashlib.sha256(TEMPORAL_ARTIFACT_DOMAIN + _canonical(body)).hexdigest(), files


def transport_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Project an engine receipt to the one exact cross-process transport shape."""

    return {field: receipt.get(field) for field in RECEIPT_TRANSPORT_FIELDS}


def temporal_request_id(
    *, tree_incarnation_id: str, tree: str, tag: str, verdict_receipt_sha256: str
) -> str:
    body = {
        "tree_incarnation_id": tree_incarnation_id,
        "tree": tree,
        "tag": tag,
        "verdict_receipt_sha256": verdict_receipt_sha256,
    }
    return hashlib.sha256(TEMPORAL_REQUEST_ID_DOMAIN + _canonical(body)).hexdigest()


def _run_bounded(
    argv: list[str],
    request: bytes,
    *,
    timeout_seconds: float = PROCESS_TIMEOUT_SECONDS,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess:
    if not 0 < len(request) <= MAX_REQUEST_BYTES:
        raise IndependentTemporalVerifierUnavailable(
            "temporal verifier request exceeds its byte limit"
        )
    request_file = tempfile.TemporaryFile()
    request_file.write(request)
    request_file.seek(0)
    try:
        process = subprocess.Popen(
            argv,
            stdin=request_file,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(cwd) if cwd is not None else None,
            env={
                "PATH": "/usr/bin:/bin",
                "PYTHONPATH": "",
                "PYTHONNOUSERSITE": "1",
                "LANG": "C",
                "LC_ALL": "C",
            },
        )
    except OSError as exc:
        request_file.close()
        raise IndependentTemporalVerifierUnavailable(
            "external temporal process could not start"
        ) from exc
    assert process.stdout is not None and process.stderr is not None
    streams = {
        process.stdout: (bytearray(), MAX_STDOUT_BYTES),
        process.stderr: (bytearray(), MAX_STDERR_BYTES),
    }
    selector = selectors.DefaultSelector()
    try:
        for stream in streams:
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ)
        deadline = time.monotonic() + timeout_seconds
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise IndependentTemporalVerifierUnavailable(
                    "external temporal process timed out"
                )
            for key, _mask in selector.select(min(remaining, 0.1)):
                stream = key.fileobj
                buffer, maximum = streams[stream]
                try:
                    chunk = os.read(
                        stream.fileno(), min(8192, maximum - len(buffer) + 1)
                    )
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(stream)
                    continue
                buffer.extend(chunk)
                if len(buffer) > maximum:
                    raise IndependentTemporalVerifierUnavailable(
                        "external temporal process output exceeded its byte limit"
                    )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise IndependentTemporalVerifierUnavailable(
                "external temporal process timed out"
            )
        returncode = process.wait(timeout=remaining)
    except (subprocess.TimeoutExpired, IndependentTemporalVerifierUnavailable) as exc:
        process.kill()
        process.wait()
        if isinstance(exc, IndependentTemporalVerifierUnavailable):
            raise
        raise IndependentTemporalVerifierUnavailable(
            "external temporal process timed out"
        ) from exc
    finally:
        selector.close()
        request_file.close()
        process.stdout.close()
        process.stderr.close()
        if process.poll() is None:
            process.kill()
            process.wait()
    return subprocess.CompletedProcess(
        argv,
        returncode,
        bytes(streams[process.stdout][0]),
        bytes(streams[process.stderr][0]),
    )


class SubprocessTimeAuthority:
    """Challenge an exact executable which exclusively holds the authority key."""

    def __init__(
        self,
        *,
        executable: Path,
        expected_executable_sha256: str,
        expected_signer_did: str,
        requested_validity_seconds: int = 60,
        nonce_factory: Callable[[int], str] = secrets.token_hex,
    ):
        self.executable = executable
        self.expected_executable_sha256 = expected_executable_sha256
        self.expected_signer_did = expected_signer_did
        self.requested_validity_seconds = requested_validity_seconds
        self.nonce_factory = nonce_factory

    def attest(
        self,
        candidates: tuple[IndependentTemporalCandidate, ...],
        *,
        verifier_artifact_sha256: str,
        verifier_python_sha256: str,
    ) -> tuple[str, dict[str, dict[str, Any]]]:
        _resolved, executable_bytes = _regular_bytes(
            self.executable,
            label="independent time authority executable",
            maximum=2 * 1024 * 1024,
        )
        if not (
            _exact_sha(self.expected_executable_sha256)
            and hashlib.sha256(executable_bytes).hexdigest()
            == self.expected_executable_sha256
            and 1 <= self.requested_validity_seconds <= 300
        ):
            raise IndependentTemporalVerifierUnavailable(
                "independent time authority identity or validity is invalid"
            )
        challenge = {
            "schema_version": TIME_AUTHORITY_CHALLENGE_SCHEMA,
            "nonce": self.nonce_factory(32),
            "verifier_artifact_sha256": verifier_artifact_sha256,
            "verifier_python_sha256": verifier_python_sha256,
            "requested_validity_seconds": self.requested_validity_seconds,
            "proofs": [candidate.authority_binding() for candidate in candidates],
        }
        challenge_bytes = _canonical(challenge)
        challenge_sha = hashlib.sha256(
            TIME_AUTHORITY_CHALLENGE_DOMAIN + challenge_bytes
        ).hexdigest()
        with tempfile.TemporaryDirectory(prefix="lakatotree-time-authority-") as temp:
            private = Path(temp) / "authority"
            descriptor = os.open(private, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o500)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(executable_bytes)
                handle.flush()
                os.fsync(handle.fileno())
                os.fchmod(handle.fileno(), 0o500)
            completed = _run_bounded([str(private)], challenge_bytes, cwd=Path(temp))
        if completed.returncode != 0 or completed.stderr:
            raise IndependentTemporalVerifierUnavailable(
                "independent time authority rejected the challenge"
            )
        response = _strict_json(completed.stdout, allow_trailing_newline=True)
        if set(response) != {"schema_version", "challenge_sha256", "attestations"}:
            raise IndependentTemporalVerifierUnavailable(
                "independent time authority response shape is invalid"
            )
        if not (
            response.get("schema_version") == TIME_AUTHORITY_RESPONSE_SCHEMA
            and response.get("challenge_sha256") == challenge_sha
            and isinstance(response.get("attestations"), list)
            and len(response["attestations"]) == len(candidates)
        ):
            raise IndependentTemporalVerifierUnavailable(
                "independent time authority response binding is invalid"
            )
        expected = {candidate.request_id: candidate for candidate in candidates}
        attestations: dict[str, dict[str, Any]] = {}
        for raw in response["attestations"]:
            if not isinstance(raw, dict) or set(raw) != _ATTESTATION_KEYS:
                raise IndependentTemporalVerifierUnavailable(
                    "independent time authority attestation shape is invalid"
                )
            request_id = raw.get("request_id")
            candidate = expected.get(request_id)
            if (
                candidate is None
                or request_id in attestations
                or raw.get("schema_version") != TIME_AUTHORITY_ATTESTATION_SCHEMA
                or raw.get("challenge_sha256") != challenge_sha
                or raw.get("signer_did") != self.expected_signer_did
                or any(raw.get(key) != value
                       for key, value in candidate.authority_binding().items())
                or raw.get("verifier_artifact_sha256") != verifier_artifact_sha256
                or raw.get("verifier_python_sha256") != verifier_python_sha256
            ):
                raise IndependentTemporalVerifierUnavailable(
                    "independent time authority attestation is spliced"
                )
            attestations[request_id] = dict(raw)
        if set(attestations) != set(expected):
            raise IndependentTemporalVerifierUnavailable(
                "independent time authority response is incomplete"
            )
        return challenge_sha, attestations


class SubprocessIndependentTemporalVerifier:
    """Run the authority and C1 verifier once each for one bounded batch."""

    def __init__(
        self,
        *,
        python_executable: Path,
        artifact_directory: Path,
        expected_artifact_sha256: str,
        expected_python_sha256: str,
        time_authority: SubprocessTimeAuthority,
    ):
        self.python_executable = python_executable
        self.artifact_directory = artifact_directory
        self.expected_artifact_sha256 = expected_artifact_sha256
        self.expected_python_sha256 = expected_python_sha256
        self.time_authority = time_authority

    def verify_batch(
        self,
        candidates: Iterable[IndependentTemporalCandidate],
    ) -> dict[str, IndependentTemporalResult]:
        batch = tuple(sorted(candidates, key=lambda item: item.request_id))
        if not batch:
            return {}
        if not _EXTERNAL_TEMPORAL_SLOTS.acquire(blocking=False):
            raise IndependentTemporalVerifierUnavailable(
                "independent temporal verifier concurrency is saturated"
            )
        try:
            return self._verify_batch_held(batch)
        finally:
            _EXTERNAL_TEMPORAL_SLOTS.release()

    def _verify_batch_held(
        self,
        batch: tuple[IndependentTemporalCandidate, ...],
    ) -> dict[str, IndependentTemporalResult]:
        if len(batch) > MAX_PROOFS or len({item.request_id for item in batch}) != len(batch):
            raise IndependentTemporalVerifierUnavailable(
                "independent temporal batch cardinality is invalid"
            )
        artifact_sha, artifact_files = temporal_artifact_sha256(
            self.artifact_directory
        )
        python_path, python_bytes = _regular_bytes(
            self.python_executable,
            label="independent verifier Python interpreter",
            maximum=256 * 1024 * 1024,
        )
        python_sha = hashlib.sha256(python_bytes).hexdigest()
        if not (
            _exact_sha(self.expected_artifact_sha256)
            and artifact_sha == self.expected_artifact_sha256
            and _exact_sha(self.expected_python_sha256)
            and python_sha == self.expected_python_sha256
        ):
            raise IndependentTemporalVerifierUnavailable(
                "independent verifier artifact identity mismatches"
            )
        challenge_sha, attestations = self.time_authority.attest(
            batch,
            verifier_artifact_sha256=artifact_sha,
            verifier_python_sha256=python_sha,
        )
        request = {
            "schema_version": BATCH_REQUEST_SCHEMA,
            "expected_time_authority_did": self.time_authority.expected_signer_did,
            "verifier_artifact_sha256": artifact_sha,
            "verifier_python_sha256": python_sha,
            "authority_challenge_sha256": challenge_sha,
            "proofs": [
                candidate.c1_request(attestations[candidate.request_id])
                for candidate in batch
            ],
        }
        request_bytes = _canonical(request)
        input_sha = hashlib.sha256(request_bytes).hexdigest()
        with tempfile.TemporaryDirectory(prefix="lakatotree-c1-temporal-") as temp:
            private = Path(temp)
            for relative, raw in artifact_files.items():
                target = private / relative
                descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(raw)
                    handle.flush()
                    os.fsync(handle.fileno())
                    os.fchmod(handle.fileno(), 0o400)
            copied_sha, _copied_files = temporal_artifact_sha256(private)
            if copied_sha != artifact_sha:
                raise IndependentTemporalVerifierUnavailable(
                    "private verifier artifact copy mismatches"
                )
            completed = _run_bounded(
                [
                    str(python_path),
                    "-I",
                    "-S",
                    "-B",
                    str(private / "temporal_cli.py"),
                ],
                request_bytes,
                cwd=private,
            )
        if completed.returncode not in {0, 1} or completed.stderr:
            raise IndependentTemporalVerifierUnavailable(
                "independent C1 verifier failed to produce a decision"
            )
        report = _strict_json(completed.stdout, allow_trailing_newline=True)
        if set(report) != {
            "schema_version",
            "status",
            "verifier_artifact_sha256",
            "verifier_python_sha256",
            "results",
            "input_sha256",
        }:
            raise IndependentTemporalVerifierUnavailable(
                "independent C1 report shape is invalid"
            )
        if not (
            report.get("schema_version") == BATCH_REPORT_SCHEMA
            and report.get("status") in {"VERIFIED", "REJECTED"}
            and report.get("input_sha256") == input_sha
            and report.get("verifier_artifact_sha256") == artifact_sha
            and report.get("verifier_python_sha256") == python_sha
            and isinstance(report.get("results"), list)
            and len(report["results"]) == len(batch)
            and (completed.returncode == 0) == (report.get("status") == "VERIFIED")
        ):
            raise IndependentTemporalVerifierUnavailable(
                "independent C1 report binding is invalid"
            )
        expected = {candidate.request_id: candidate for candidate in batch}
        results: dict[str, IndependentTemporalResult] = {}
        for raw in report["results"]:
            if not isinstance(raw, dict):
                raise IndependentTemporalVerifierUnavailable(
                    "independent C1 result is malformed"
                )
            request_id = raw.get("request_id")
            candidate = expected.get(request_id)
            if candidate is None or request_id in results:
                raise IndependentTemporalVerifierUnavailable(
                    "independent C1 result identity is ambiguous"
                )
            if raw.get("status") == "VERIFIED":
                bindings = candidate.authority_binding()
                expected_authority_identities = tuple(sorted({
                    hashlib.sha256(did.encode("utf-8")).hexdigest()
                    for did in (
                        *candidate.authority_policy["witness_allowlist"],
                        *candidate.authority_policy["producer_dids"],
                        *candidate.authority_policy["attestor_dids"],
                        self.time_authority.expected_signer_did,
                    )
                }))
                if not (
                    set(raw) == _VERIFIED_RESULT_KEYS
                    and raw.get("component_ok") is True
                    and raw.get("l3_eligible") is True
                    and raw.get("reason_code")
                    == "independent_two_ended_temporal_verified"
                    and all(raw.get(key) == value for key, value in bindings.items()
                            if key != "witness_dids")
                    and raw.get("independent_verifier") == "sha256:" + artifact_sha
                    and isinstance(raw.get("time_authority"), str)
                    and raw["time_authority"].startswith("did-key-sha256:")
                    and isinstance(raw.get("independent_valid_until"), str)
                    and raw.get("authority_identity_sha256s")
                    == list(expected_authority_identities)
                ):
                    raise IndependentTemporalVerifierUnavailable(
                        "independent C1 verified result is spliced"
                    )
                result = IndependentTemporalResult(
                    request_id=request_id,
                    accepted=True,
                    reason=raw["reason_code"],
                    input_sha256=input_sha,
                    sidecar_sha256=raw["sidecar_sha256"],
                    authority_policy_sha256=raw["authority_policy_sha256"],
                    receipt_graph_sha256=raw["receipt_graph_sha256"],
                    prediction_receipt_sha256=raw[
                        "prediction_receipt_sha256"
                    ],
                    verdict_receipt_sha256=raw["verdict_receipt_sha256"],
                    prediction_temporal_commitment_sha256=raw[
                        "prediction_temporal_commitment_sha256"
                    ],
                    threshold=raw["threshold"],
                    t1_latest=raw["t1_latest"],
                    t2_earliest=raw["t2_earliest"],
                    independent_verifier=raw["independent_verifier"],
                    time_authority=raw["time_authority"],
                    independent_valid_until=raw["independent_valid_until"],
                    authority_identity_sha256s=expected_authority_identities,
                )
            else:
                if not (
                    set(raw) == _REJECTED_RESULT_KEYS
                    and raw.get("status") == "REJECTED"
                    and raw.get("component_ok") is False
                    and raw.get("l3_eligible") is False
                    and isinstance(raw.get("reason_code"), str)
                    and raw["reason_code"]
                ):
                    raise IndependentTemporalVerifierUnavailable(
                        "independent C1 rejected result is malformed"
                    )
                result = IndependentTemporalResult(
                    request_id=request_id,
                    accepted=False,
                    reason=raw["reason_code"],
                    input_sha256=input_sha,
                )
            results[request_id] = result
        if set(results) != set(expected):
            raise IndependentTemporalVerifierUnavailable(
                "independent C1 report is incomplete"
            )
        return results


__all__ = [
    "IndependentTemporalCandidate",
    "IndependentTemporalResult",
    "IndependentTemporalVerifierUnavailable",
    "SubprocessIndependentTemporalVerifier",
    "SubprocessTimeAuthority",
    "UnavailableIndependentTemporalVerifier",
    "temporal_artifact_sha256",
    "temporal_request_id",
    "transport_receipt",
]
