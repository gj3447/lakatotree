"""Pure contracts for a resource-accounted local subprocess build.

The values in this module bind every declared execution input before the I/O
shell can reserve resources or launch a process.  They read no clock,
environment, filesystem, journal, database, or subprocess.  The local adapter
is intentionally scoped to provider-free build/TDD commands: token usage is
therefore zero by contract, not guessed from arbitrary model traffic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import hashlib
import json
from pathlib import PurePath
import re
from typing import Mapping

from lakatos.resource_coordination import ResourceUsage, ResourceVector


BUILD_EXECUTION_SCHEMA_VERSION = "lakatotree.build-execution/v1"
LOCAL_BUILD_ADAPTER = "lakatotree.local-subprocess-build"
LOCAL_BUILD_ADAPTER_VERSION = "1"
_WORKLOAD_DOMAIN = b"lakatotree-local-build-workload\x00v1\n"
_EVIDENCE_DOMAIN = b"lakatotree-local-build-evidence\x00v1\n"
_MEASUREMENT_DOMAIN = b"lakatotree-local-build-measurement\x00v1\n"
_ENVIRONMENT_DOMAIN = b"lakatotree-local-build-environment\x00v1\n"
_RFC3339_UTC = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$"
)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_sha256(value: str, label: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or value != value.lower()
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{label} must be a canonical lowercase SHA-256")


def _require_identifier(value: str, label: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 256
        or not value.isprintable()
    ):
        raise ValueError(f"{label} must be printable, non-empty, and <= 256 chars")


def _require_utc(value: str, label: str) -> datetime:
    if not isinstance(value, str) or _RFC3339_UTC.fullmatch(value) is None:
        raise ValueError(f"{label} must be an RFC3339 UTC timestamp ending in Z")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{label} must be a valid RFC3339 UTC timestamp") from exc


def environment_sha256(environment: Mapping[str, str]) -> str:
    """Hash a closed child environment without persisting its plaintext values."""

    if not isinstance(environment, Mapping):
        raise TypeError("environment must be a string mapping")
    canonical: dict[str, str] = {}
    for key, value in environment.items():
        if (
            not isinstance(key, str)
            or not key
            or "=" in key
            or "\0" in key
        ):
            raise ValueError("environment keys must be non-empty strings without '=' or NUL")
        if not isinstance(value, str) or "\0" in value:
            raise ValueError("environment values must be strings without NUL")
        canonical[key] = value
    return _sha256_bytes(_ENVIRONMENT_DOMAIN + _canonical_bytes(canonical))


@dataclass(frozen=True, slots=True)
class BuildExecutionSpec:
    """Closed execution input for one provider-free shell build attempt."""

    command: str
    cwd: str
    shell: str
    timeout_seconds: int
    environment_sha256: str
    input_manifest_sha256: str
    isolation_adapter: str
    isolation_version: str
    isolation_policy_sha256: str
    output_tail_bytes: int = 65_536
    max_output_bytes: int = 16_777_216
    provider_calls: str = "forbidden"
    schema_version: str = BUILD_EXECUTION_SCHEMA_VERSION
    adapter: str = LOCAL_BUILD_ADAPTER
    adapter_version: str = LOCAL_BUILD_ADAPTER_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != BUILD_EXECUTION_SCHEMA_VERSION:
            raise ValueError("unsupported build execution schema")
        if not isinstance(self.command, str) or not self.command or "\0" in self.command:
            raise ValueError("command must be a non-empty string without NUL")
        if len(self.command.encode("utf-8")) > 1_048_576:
            raise ValueError("command exceeds the 1 MiB build contract limit")
        for label, value in (("cwd", self.cwd), ("shell", self.shell)):
            if not isinstance(value, str) or not PurePath(value).is_absolute():
                raise ValueError(f"{label} must be an absolute path")
            if "\0" in value:
                raise ValueError(f"{label} cannot contain NUL")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, int)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be a positive integer")
        if (
            isinstance(self.output_tail_bytes, bool)
            or not isinstance(self.output_tail_bytes, int)
            or not 1 <= self.output_tail_bytes <= 1_048_576
        ):
            raise ValueError("output_tail_bytes must be between 1 and 1048576")
        if (
            isinstance(self.max_output_bytes, bool)
            or not isinstance(self.max_output_bytes, int)
            or not 1 <= self.max_output_bytes <= 1_073_741_824
        ):
            raise ValueError("max_output_bytes must be between 1 and 1073741824")
        if self.output_tail_bytes > self.max_output_bytes:
            raise ValueError("output_tail_bytes cannot exceed max_output_bytes")
        _require_sha256(self.environment_sha256, "environment_sha256")
        _require_sha256(self.input_manifest_sha256, "input_manifest_sha256")
        _require_identifier(self.isolation_adapter, "isolation_adapter")
        _require_identifier(self.isolation_version, "isolation_version")
        _require_sha256(self.isolation_policy_sha256, "isolation_policy_sha256")
        _require_identifier(self.adapter, "adapter")
        _require_identifier(self.adapter_version, "adapter_version")
        if self.provider_calls != "forbidden":
            raise ValueError(
                "the v1 local build adapter only meters provider-free subprocesses"
            )

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "adapter": self.adapter,
            "adapter_version": self.adapter_version,
            "command": self.command,
            "cwd": self.cwd,
            "shell": self.shell,
            "timeout_seconds": self.timeout_seconds,
            "environment_sha256": self.environment_sha256,
            "input_manifest_sha256": self.input_manifest_sha256,
            "isolation_adapter": self.isolation_adapter,
            "isolation_version": self.isolation_version,
            "isolation_policy_sha256": self.isolation_policy_sha256,
            "output_tail_bytes": self.output_tail_bytes,
            "max_output_bytes": self.max_output_bytes,
            "provider_calls": self.provider_calls,
        }

    @property
    def workload_sha256(self) -> str:
        return _sha256_bytes(_WORKLOAD_DOMAIN + _canonical_bytes(self.to_dict()))


class BuildTerminalStatus(str, Enum):
    EXITED = "EXITED"
    TIMED_OUT = "TIMED_OUT"
    OUTPUT_LIMIT_EXCEEDED = "OUTPUT_LIMIT_EXCEEDED"
    SPAWN_FAILED = "SPAWN_FAILED"


@dataclass(frozen=True, slots=True)
class BuildExecutionResult:
    """Durable terminal subprocess evidence, independent of scientific success."""

    effect_id: str
    workload_sha256: str
    intent_sha256: str
    fence_token: int
    status: BuildTerminalStatus
    returncode: int | None
    started_at: str
    completed_at: str
    elapsed_monotonic_ns: int
    compute_wall_ms: int
    stdout_sha256: str
    stderr_sha256: str
    stdout_bytes: int
    stderr_bytes: int
    output_tail: str
    schema_version: str = BUILD_EXECUTION_SCHEMA_VERSION
    measurement_method: str = "subprocess.monotonic_elapsed.ceil_ms/v1"

    def __post_init__(self) -> None:
        if self.schema_version != BUILD_EXECUTION_SCHEMA_VERSION:
            raise ValueError("unsupported build execution result schema")
        _require_identifier(self.effect_id, "effect_id")
        _require_sha256(self.workload_sha256, "workload_sha256")
        _require_sha256(self.intent_sha256, "intent_sha256")
        if (
            isinstance(self.fence_token, bool)
            or not isinstance(self.fence_token, int)
            or self.fence_token < 1
        ):
            raise ValueError("fence_token must be an integer >= 1")
        if not isinstance(self.status, BuildTerminalStatus):
            raise ValueError("status must be a BuildTerminalStatus")
        if self.status in {
            BuildTerminalStatus.TIMED_OUT,
            BuildTerminalStatus.OUTPUT_LIMIT_EXCEEDED,
        }:
            if self.returncode is not None:
                raise ValueError(
                    "forced-stop result cannot claim a process return code"
                )
        elif isinstance(self.returncode, bool) or not isinstance(self.returncode, int):
            raise ValueError("exited/spawn-failed result requires an integer return code")
        started = _require_utc(self.started_at, "started_at")
        completed = _require_utc(self.completed_at, "completed_at")
        if completed < started:
            raise ValueError("completed_at cannot precede started_at")
        if (
            isinstance(self.elapsed_monotonic_ns, bool)
            or not isinstance(self.elapsed_monotonic_ns, int)
            or self.elapsed_monotonic_ns < 0
        ):
            raise ValueError("elapsed_monotonic_ns must be an integer >= 0")
        expected_ms = (self.elapsed_monotonic_ns + 999_999) // 1_000_000
        if self.compute_wall_ms != expected_ms:
            raise ValueError("compute_wall_ms must be monotonic elapsed time rounded up")
        for label, value in (
            ("stdout_bytes", self.stdout_bytes),
            ("stderr_bytes", self.stderr_bytes),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{label} must be an integer >= 0")
        _require_sha256(self.stdout_sha256, "stdout_sha256")
        _require_sha256(self.stderr_sha256, "stderr_sha256")
        if not isinstance(self.output_tail, str):
            raise ValueError("output_tail must be text")
        if len(self.output_tail.encode("utf-8")) > 1_048_576:
            raise ValueError("output_tail exceeds the v1 1 MiB evidence limit")
        _require_identifier(self.measurement_method, "measurement_method")

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "effect_id": self.effect_id,
            "workload_sha256": self.workload_sha256,
            "intent_sha256": self.intent_sha256,
            "fence_token": self.fence_token,
            "status": self.status.value,
            "returncode": self.returncode,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "elapsed_monotonic_ns": self.elapsed_monotonic_ns,
            "compute_wall_ms": self.compute_wall_ms,
            "stdout_sha256": self.stdout_sha256,
            "stderr_sha256": self.stderr_sha256,
            "stdout_bytes": self.stdout_bytes,
            "stderr_bytes": self.stderr_bytes,
            "output_tail": self.output_tail,
            "measurement_method": self.measurement_method,
        }

    @classmethod
    def from_dict(cls, value: dict) -> "BuildExecutionResult":
        expected = {
            "schema_version",
            "effect_id",
            "workload_sha256",
            "intent_sha256",
            "fence_token",
            "status",
            "returncode",
            "started_at",
            "completed_at",
            "elapsed_monotonic_ns",
            "compute_wall_ms",
            "stdout_sha256",
            "stderr_sha256",
            "stdout_bytes",
            "stderr_bytes",
            "output_tail",
            "measurement_method",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError("build result fields diverged from the closed v1 schema")
        return cls(
            **{**value, "status": BuildTerminalStatus(value["status"])}
        )

    @property
    def evidence_sha256(self) -> str:
        return _sha256_bytes(_EVIDENCE_DOMAIN + _canonical_bytes(self.to_dict()))

    @property
    def usage(self) -> ResourceUsage:
        actual = ResourceVector(compute_wall_ms=self.compute_wall_ms)
        measurement = {
            "schema_version": self.schema_version,
            "measurement_method": self.measurement_method,
            "effect_id": self.effect_id,
            "workload_sha256": self.workload_sha256,
            "intent_sha256": self.intent_sha256,
            "elapsed_monotonic_ns": self.elapsed_monotonic_ns,
            "actual": actual.to_dict(),
            "evidence_sha256": self.evidence_sha256,
        }
        return ResourceUsage(
            actual=actual,
            measured_at=self.completed_at,
            measurement_sha256=_sha256_bytes(
                _MEASUREMENT_DOMAIN + _canonical_bytes(measurement)
            ),
            evidence_sha256=self.evidence_sha256,
        )


@dataclass(frozen=True, slots=True)
class BuildRun:
    """Legacy-compatible build result plus operation-scoped resource evidence."""

    output: str
    returncode: int
    timed_out: bool
    effect_id: str
    workload_sha256: str
    intent_sha256: str
    dispatch_receipt_sha256: str
    evidence_sha256: str
    measurement_sha256: str
    settlement_receipt_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.output, str):
            raise ValueError("output must be text")
        if isinstance(self.returncode, bool) or not isinstance(self.returncode, int):
            raise ValueError("returncode must be an integer")
        if not isinstance(self.timed_out, bool):
            raise ValueError("timed_out must be boolean")
        _require_identifier(self.effect_id, "effect_id")
        for label, value in (
            ("workload_sha256", self.workload_sha256),
            ("intent_sha256", self.intent_sha256),
            ("dispatch_receipt_sha256", self.dispatch_receipt_sha256),
            ("evidence_sha256", self.evidence_sha256),
            ("measurement_sha256", self.measurement_sha256),
            ("settlement_receipt_sha256", self.settlement_receipt_sha256),
        ):
            _require_sha256(value, label)

    @property
    def resource_provenance(self) -> dict[str, str]:
        return {
            "effect_id": self.effect_id,
            "workload_sha256": self.workload_sha256,
            "intent_sha256": self.intent_sha256,
            "dispatch_receipt_sha256": self.dispatch_receipt_sha256,
            "evidence_sha256": self.evidence_sha256,
            "measurement_sha256": self.measurement_sha256,
            "settlement_receipt_sha256": self.settlement_receipt_sha256,
        }


class ResourceBuildError(RuntimeError):
    """Base class for typed failures at the resource-gated build boundary."""


class ResourceBuildConfigError(ResourceBuildError):
    """The opt-in build resource composition is incomplete or inconsistent."""


class ResourceBuildOutcomeUnknown(ResourceBuildError):
    """A durable claim exists but target completion cannot be proven."""


class ResourceBuildOverrun(ResourceBuildError):
    """Measured build use exceeded its reservation and froze the budget."""


__all__ = [
    "BUILD_EXECUTION_SCHEMA_VERSION",
    "BuildExecutionResult",
    "BuildExecutionSpec",
    "BuildRun",
    "BuildTerminalStatus",
    "LOCAL_BUILD_ADAPTER",
    "LOCAL_BUILD_ADAPTER_VERSION",
    "ResourceBuildConfigError",
    "ResourceBuildError",
    "ResourceBuildOutcomeUnknown",
    "ResourceBuildOverrun",
    "environment_sha256",
]
