"""Signed append-only trusted-anchor effect adapter for resource journals."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
from typing import Iterator

try:  # POSIX is the supported substrate for the append-only file authority.
    import fcntl
except ImportError:  # pragma: no cover - hosted CI and deployment are POSIX.
    fcntl = None

from lakatos.io._resource_journal_contracts import (
    AnchorConflict,
    ResourceCheckpoint,
    TrustedAnchorCorruption,
    TrustedAnchorUnavailable,
    _ANCHOR_DOMAIN,
    _canonical_bytes,
    _checkpoint_from_dict,
    _expect_keys,
    _expect_mapping,
    _require_identifier,
    _require_sha256,
)
from lakatos.write_cert import ed25519_public_key, ed25519_sign, ed25519_verify


class SignedAppendOnlyFileAnchor:
    """Signed, append-only reference implementation of a trusted anchor.

    The directory must be a trust boundary independent from the SQLite file.
    Each checkpoint is an immutable signed file; reads scan the complete chain
    instead of trusting a rollbackable mutable head pointer.  Production callers
    should place the directory on separately administered or append-only storage,
    or replace this adapter with a remote CAS authority.
    """

    def __init__(
        self,
        directory: str | os.PathLike[str],
        *,
        signing_key: bytes | None = None,
        verify_key: bytes | None = None,
    ) -> None:
        if fcntl is None:
            raise OSError("SignedAppendOnlyFileAnchor requires POSIX file locking")
        if signing_key is None and verify_key is None:
            raise ValueError("an anchor signing_key or pinned verify_key is required")
        self._directory = Path(directory)
        self._directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._signing_key = signing_key
        derived = ed25519_public_key(signing_key) if signing_key is not None else None
        if verify_key is not None and derived is not None and verify_key != derived:
            raise ValueError("anchor signing key does not match the pinned verify key")
        self._verify_key = verify_key if verify_key is not None else derived
        assert self._verify_key is not None
        if len(self._verify_key) != 32:
            raise ValueError("anchor verify_key must contain 32 bytes")

    @staticmethod
    def _scope_key(scope: str) -> str:
        _require_identifier(scope, "anchor scope")
        return hashlib.sha256(scope.encode("utf-8")).hexdigest()

    def _record_path(self, checkpoint: ResourceCheckpoint) -> Path:
        return self._directory / (
            f"{self._scope_key(checkpoint.scope)}."
            f"{checkpoint.revision:020d}."
            f"{checkpoint.journal_head_sha256}.json"
        )

    @contextmanager
    def _locked(self, scope: str, *, exclusive: bool) -> Iterator[None]:
        key = self._scope_key(scope)
        lock_path = self._directory / f".{key}.lock"
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            fcntl.flock(descriptor, operation)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _decode_record(self, path: Path) -> ResourceCheckpoint:
        try:
            raw = path.read_bytes()
            envelope = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TrustedAnchorCorruption(f"anchor record is unreadable: {path.name}") from exc
        if not isinstance(envelope, dict) or _canonical_bytes(envelope) != raw:
            raise TrustedAnchorCorruption(f"anchor record is not canonical: {path.name}")
        try:
            _expect_keys(
                envelope,
                {"checkpoint", "signature_algorithm", "signer_public_key", "signature"},
                "signed anchor",
            )
            if envelope["signature_algorithm"] != "Ed25519":
                raise ValueError("unsupported anchor signature algorithm")
            signer = bytes.fromhex(envelope["signer_public_key"])
            signature = bytes.fromhex(envelope["signature"])
            if signer != self._verify_key:
                raise ValueError("anchor signer is not the pinned authority")
            checkpoint = _checkpoint_from_dict(
                _expect_mapping(envelope["checkpoint"], "anchor checkpoint")
            )
            signing_bytes = _ANCHOR_DOMAIN + _canonical_bytes(checkpoint.to_dict())
            if not ed25519_verify(self._verify_key, signing_bytes, signature):
                raise ValueError("anchor signature is invalid")
            if path != self._record_path(checkpoint):
                raise ValueError("anchor filename does not match its signed checkpoint")
            return checkpoint
        except (TypeError, ValueError) as exc:
            raise TrustedAnchorCorruption(f"anchor verification failed: {path.name}") from exc

    def _read_all_unlocked(self, scope: str) -> tuple[ResourceCheckpoint, ...]:
        prefix = self._scope_key(scope)
        paths = sorted(self._directory.glob(f"{prefix}.*.json"))
        checkpoints = [self._decode_record(path) for path in paths]
        if not checkpoints:
            return ()
        by_revision: dict[int, ResourceCheckpoint] = {}
        for checkpoint in checkpoints:
            if checkpoint.scope != scope:
                raise TrustedAnchorCorruption("anchor scope hash collision or substitution")
            previous = by_revision.get(checkpoint.revision)
            if previous is not None and previous != checkpoint:
                raise AnchorConflict(
                    f"external anchor fork at revision {checkpoint.revision}"
                )
            by_revision[checkpoint.revision] = checkpoint
        revisions = sorted(by_revision)
        if revisions != list(range(revisions[-1] + 1)):
            raise TrustedAnchorCorruption("external anchor chain has a revision gap")
        ordered = tuple(by_revision[revision] for revision in revisions)
        for index, checkpoint in enumerate(ordered):
            if index == 0:
                if checkpoint.previous_journal_head_sha256 is not None:
                    raise TrustedAnchorCorruption("external genesis has a predecessor")
                continue
            previous = ordered[index - 1]
            if (
                checkpoint.budget_id != previous.budget_id
                or checkpoint.scope != previous.scope
                or checkpoint.epoch != previous.epoch
                or checkpoint.previous_journal_head_sha256
                != previous.journal_head_sha256
            ):
                raise TrustedAnchorCorruption("external anchor chain is not contiguous")
        return ordered

    def read(self, scope: str) -> ResourceCheckpoint | None:
        with self._locked(scope, exclusive=False):
            checkpoints = self._read_all_unlocked(scope)
        return checkpoints[-1] if checkpoints else None

    def compare_and_set(
        self,
        *,
        expected_journal_head_sha256: str | None,
        checkpoint: ResourceCheckpoint,
    ) -> ResourceCheckpoint:
        if self._signing_key is None:
            raise TrustedAnchorUnavailable("anchor is configured for verification only")
        if expected_journal_head_sha256 is not None:
            _require_sha256(expected_journal_head_sha256, "expected anchor head")
        with self._locked(checkpoint.scope, exclusive=True):
            checkpoints = self._read_all_unlocked(checkpoint.scope)
            current = checkpoints[-1] if checkpoints else None
            if current == checkpoint:
                return current
            if current is None:
                if expected_journal_head_sha256 is not None or checkpoint.revision != 0:
                    raise AnchorConflict("external anchor genesis CAS predecessor mismatch")
            elif (
                current.journal_head_sha256 != expected_journal_head_sha256
                or checkpoint.previous_journal_head_sha256
                != expected_journal_head_sha256
                or checkpoint.revision != current.revision + 1
                or checkpoint.budget_id != current.budget_id
                or checkpoint.epoch != current.epoch
            ):
                raise AnchorConflict("external anchor predecessor CAS failed")
            signing_bytes = _ANCHOR_DOMAIN + _canonical_bytes(checkpoint.to_dict())
            envelope = {
                "checkpoint": checkpoint.to_dict(),
                "signature_algorithm": "Ed25519",
                "signer_public_key": self._verify_key.hex(),
                "signature": ed25519_sign(self._signing_key, signing_bytes).hex(),
            }
            raw = _canonical_bytes(envelope)
            destination = self._record_path(checkpoint)
            temporary = self._directory / (
                f".anchor-{os.getpid()}-{id(checkpoint):x}-{checkpoint.revision}.tmp"
            )
            descriptor = None
            try:
                descriptor = os.open(
                    temporary,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
                offset = 0
                while offset < len(raw):
                    offset += os.write(descriptor, raw[offset:])
                os.fsync(descriptor)
                os.close(descriptor)
                descriptor = None
                os.link(temporary, destination)
                os.unlink(temporary)
                directory_fd = os.open(self._directory, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except FileExistsError:
                if temporary.exists():
                    temporary.unlink()
                existing = self._decode_record(destination)
                if existing != checkpoint:
                    raise AnchorConflict("external anchor identity was reused")
            finally:
                if descriptor is not None:
                    os.close(descriptor)
                if temporary.exists():
                    temporary.unlink()
            stored = self._decode_record(destination)
            if stored != checkpoint:
                raise TrustedAnchorCorruption("external anchor exact readback diverged")
            return stored


__all__ = ["SignedAppendOnlyFileAnchor"]
