"""Bounded adapter for the external runtime-writer snapshot authority."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import secrets
import selectors
import subprocess
import tempfile
import time
from typing import Any, Callable, Mapping, Sequence

from server.runtime_authority import (
    RuntimeAuthorityError,
    VerifiedRuntimeSnapshot,
    build_runtime_challenge,
    canonical_json,
    verify_runtime_snapshot,
)
from server.storage_predeploy import _executable_bytes, fence_verifier_identity


RUNTIME_AUTHORITY_TIMEOUT_SECONDS = 5
RUNTIME_AUTHORITY_STDOUT_MAX_BYTES = 64 * 1024
RUNTIME_AUTHORITY_STDERR_MAX_BYTES = 8 * 1024


def _exact_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _run_bounded(executable: Path, challenge: bytes) -> subprocess.CompletedProcess:
    """Run one signer without allowing its pipes to become an unbounded RAM sink."""

    challenge_file = tempfile.TemporaryFile()
    challenge_file.write(challenge)
    challenge_file.seek(0)
    process = subprocess.Popen(
        [str(executable)],
        stdin=challenge_file,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": "",
            "PYTHONNOUSERSITE": "1",
            "LANG": "C",
            "LC_ALL": "C",
        },
    )
    assert process.stdout is not None
    assert process.stderr is not None

    streams = {
        process.stdout: (bytearray(), RUNTIME_AUTHORITY_STDOUT_MAX_BYTES),
        process.stderr: (bytearray(), RUNTIME_AUTHORITY_STDERR_MAX_BYTES),
    }
    selector = selectors.DefaultSelector()
    try:
        for stream in streams:
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ)
        deadline = time.monotonic() + RUNTIME_AUTHORITY_TIMEOUT_SECONDS
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                process.kill()
                process.wait()
                raise RuntimeAuthorityError("runtime authority challenge timed out")
            for key, _mask in selector.select(min(remaining, 0.1)):
                stream = key.fileobj
                buffer, maximum = streams[stream]
                try:
                    chunk = os.read(stream.fileno(), min(8192, maximum - len(buffer) + 1))
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(stream)
                    continue
                buffer.extend(chunk)
                if len(buffer) > maximum:
                    process.kill()
                    process.wait()
                    raise RuntimeAuthorityError(
                        "runtime authority output exceeded its byte limit"
                    )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            process.kill()
            process.wait()
            raise RuntimeAuthorityError("runtime authority challenge timed out")
        returncode = process.wait(timeout=remaining)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.wait()
        raise RuntimeAuthorityError("runtime authority challenge timed out") from exc
    finally:
        selector.close()
        challenge_file.close()
        process.stdout.close()
        process.stderr.close()
        if process.poll() is None:
            process.kill()
            process.wait()
    return subprocess.CompletedProcess(
        [str(executable)],
        returncode,
        bytes(streams[process.stdout][0]),
        bytes(streams[process.stderr][0]),
    )


def challenge_runtime_authority(
    *,
    executable: Path,
    expected_executable_sha256: str,
    public_key_hex: str,
    environment: str,
    boot_id: str,
    artifact: Mapping[str, Any],
    operation_sha256: str,
    target_sha256: str,
    storage_access_policy_file_sha256: str,
    predeploy_receipt_file_sha256: str,
    predeploy_receipt_sha256: str,
    startup_bundle_file_sha256: str,
    historical_drain_lease_id_sha256: str,
    runtime_writer_lease: Mapping[str, Any],
    workers: Sequence[Mapping[str, str]],
    authority_not_after: datetime,
    now: Callable[[], datetime] | None = None,
    nonce_factory: Callable[[int], str] = secrets.token_hex,
) -> VerifiedRuntimeSnapshot:
    """Challenge an exact executable and verify its independently signed reply.

    The executable is copied by exact bytes into a private directory before it
    runs.  Its signing key is never available to this process.
    """

    identity = fence_verifier_identity(executable)
    resolved, verifier_bytes = _executable_bytes(
        executable, "runtime authority verifier"
    )
    del resolved
    if not (
        _exact_sha256(expected_executable_sha256)
        and identity["sha256"] == expected_executable_sha256
        and identity["verifier_content_sha256"]
        == hashlib.sha256(verifier_bytes).hexdigest()
    ):
        raise RuntimeAuthorityError("runtime authority executable identity mismatches")
    nonce = nonce_factory(32)
    challenge = build_runtime_challenge(
        nonce=nonce,
        environment=environment,
        boot_id=boot_id,
        artifact=artifact,
        operation_sha256=operation_sha256,
        target_sha256=target_sha256,
        storage_access_policy_file_sha256=storage_access_policy_file_sha256,
        predeploy_receipt_file_sha256=predeploy_receipt_file_sha256,
        predeploy_receipt_sha256=predeploy_receipt_sha256,
        startup_bundle_file_sha256=startup_bundle_file_sha256,
        historical_drain_lease_id_sha256=historical_drain_lease_id_sha256,
        runtime_writer_lease=runtime_writer_lease,
        workers=workers,
    )
    with tempfile.TemporaryDirectory(prefix="lakatotree-runtime-authority-") as temp_dir:
        private_path = Path(temp_dir) / "verifier"
        descriptor = os.open(
            private_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o500,
        )
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as handle:
                handle.write(verifier_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            os.fchmod(descriptor, 0o500)
        finally:
            os.close(descriptor)
        if hashlib.sha256(private_path.read_bytes()).hexdigest() != identity[
            "verifier_content_sha256"
        ]:
            raise RuntimeAuthorityError("runtime authority private copy mismatches")
        completed = _run_bounded(private_path, canonical_json(challenge))
    interpreter = identity.get("interpreter")
    if isinstance(interpreter, Mapping):
        _path, interpreter_bytes = _executable_bytes(
            Path(str(interpreter["path"])),
            "runtime authority verifier interpreter",
        )
        if hashlib.sha256(interpreter_bytes).hexdigest() != interpreter.get("sha256"):
            raise RuntimeAuthorityError(
                "runtime authority interpreter changed during challenge"
            )
    if completed.returncode != 0 or completed.stderr:
        raise RuntimeAuthorityError("external runtime authority rejected the challenge")
    evaluated_at = (now or (lambda: datetime.now(timezone.utc)))()
    return verify_runtime_snapshot(
        completed.stdout,
        challenge=challenge,
        public_key_hex=public_key_hex,
        evaluated_at=evaluated_at,
        authority_not_after=authority_not_after,
    )
